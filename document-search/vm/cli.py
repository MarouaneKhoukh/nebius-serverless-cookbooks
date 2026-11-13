"""Index on a standalone VM; keep authoritative vectors/progress outside it."""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import html
import json
import os
from pathlib import Path
import statistics
import sys
import time
import uuid

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from embed import QUERY_INSTRUCTION, semantic_rank  # existing pooling/retrieval contract
from vm.data import load_documents, manifest_digest
from vm.durable import RunConfig, index_documents, inspect_documents, load_records, open_store

SOURCE_FILES = ("documents.jsonl", "manifest.json", "LICENSE", "SOURCE.md")


def settings_from(path: Path) -> dict:
    settings = json.loads(path.read_text())
    encoder = settings["encoder_settings"]
    if encoder.get("pooling") != "last-token" or encoder.get("normalize") is not True:
        raise ValueError("This encoder requires last-token pooling and normalize=true.")
    revision = settings["model_revision"]
    if len(revision) != 40 or any(c not in "0123456789abcdef" for c in revision):
        raise ValueError("Pin model_revision to its full commit SHA.")
    return settings


def run_config(data: Path, settings: dict) -> RunConfig:
    return RunConfig(manifest_sha256=manifest_digest(data), model=settings["model"],
                     model_revision=settings["model_revision"], dimensions=settings["dimensions"],
                     chunk_words=settings["chunk_words"], encoder_settings=settings["encoder_settings"])


def write_json(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, ensure_ascii=False, allow_nan=False) + "\n")


def write_search(folder: Path, query: str, matches: list[dict], fingerprint: str) -> None:
    folder.mkdir(parents=True, exist_ok=True)
    write_json(folder / "search.json", {"query": query, "run_fingerprint": fingerprint, "matches": matches})
    cards = []
    for match in matches:
        title = html.escape(match.get("title", match["source"]))
        url = match.get("source_url", "")
        if not url.startswith("https://"):
            raise ValueError("Search source links must use HTTPS.")
        cards.append(f'<article><h2><a href="{html.escape(url, quote=True)}">{title}</a></h2>'
                     f'<p>Similarity {match["similarity"]:.4f}</p><p>{html.escape(match["text"])}</p></article>')
    # VM reports deliberately carry no Serverless branding.
    logo = (ROOT / "docs/brand/nebius-logo.svg").read_text()
    (folder / "search.html").write_text(
        '<!doctype html><html lang="en"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">'
        '<title>Document search on Nebius Compute</title><style>body{font:17px/1.6 system-ui;max-width:920px;margin:40px auto;padding:0 24px;color:#24271f;background:#fafaf6}'
        'header svg{width:140px;height:auto}article{padding:20px 0;border-bottom:1px solid #ddd}a{color:inherit}</style>'
        f'<header>{logo}<p>Powered by Nebius Compute</p></header><h1>{html.escape(query)}</h1>'
        + ''.join(cards) + '<p>Scores express similarity, not answer confidence.</p>'
        '<footer><p>Passages: <a href="https://huggingface.co/datasets/databricks/databricks-dolly-15k">Databricks Dolly 15k</a>'
        ' (Wikipedia reference text), <a href="https://creativecommons.org/licenses/by-sa/3.0/">CC BY-SA 3.0</a>.</p></footer></html>', encoding="utf-8")


def parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description=__doc__)
    sub = p.add_subparsers(dest="command", required=True)
    for command in ("index", "verify", "status", "query"):
        c = sub.add_parser(command)
        c.add_argument("--data", type=Path, default=ROOT / "data/vm-documents")
        c.add_argument("--store", required=True, help="s3://bucket/prefix; plain local paths are for offline tests")
        c.add_argument("--config", type=Path, default=ROOT / "vm/runtime.json")
        c.add_argument("--report", type=Path)
        if command in ("index", "query"):
            c.add_argument("--device", choices=("cuda", "cpu"), default="cuda")
        if command == "index":
            c.add_argument("--batch-size", type=int)
            c.add_argument("--stop-after-documents", type=int, help="Controlled stop after this many unfinished documents are durably completed")
            c.add_argument("--crash-after-saved-chunks", type=int, help="Controlled hard exit after N NEW chunks; exit 75")
        if command == "query":
            c.add_argument("--text", required=True)
            c.add_argument("--top-k", type=int, default=5)
            c.add_argument("--output-dir", type=Path, default=Path("results-vm-search"))
    for command in ("upload-inputs", "download-inputs"):
        c = sub.add_parser(command)
        c.add_argument("--data", type=Path, default=ROOT / "data/vm-documents")
        c.add_argument("--store", required=True, help="Separate s3://bucket/input-prefix")
    return p


def main(argv=None) -> int:
    args = parser().parse_args(argv)
    try:
        start = time.perf_counter()
        store = open_store(args.store)
        if args.command in ("upload-inputs", "download-inputs"):
            if args.command == "upload-inputs":
                load_documents(args.data)
                for name in SOURCE_FILES:
                    value = (args.data / name).read_bytes()
                    store.put(name, value)
                    if store.get(name) != value:
                        raise ValueError("Uploaded input failed read-back validation: " + name)
            else:
                args.data.mkdir(parents=True, exist_ok=True)
                for name in SOURCE_FILES:
                    value = store.get(name)
                    if value is None:
                        raise ValueError("Durable input is missing: " + name)
                    path = args.data / name
                    if path.exists() and path.read_bytes() != value:
                        raise ValueError("Local input differs. Download into a fresh --data directory.")
                    path.write_bytes(value)
                load_documents(args.data)
            print(json.dumps({"action": args.command, "documents": 1000, "manifest_sha256": manifest_digest(args.data),
                              "transfer_seconds": time.perf_counter() - start}, indent=2))
            return 0
        settings = settings_from(args.config)
        documents = load_documents(args.data)
        config = run_config(args.data, settings)
        if args.command in ("verify", "status"):
            result = inspect_documents(documents, store, config)
            stats = result["stats"]
            if args.command == "verify" and not stats["complete"]:
                raise ValueError("Index is incomplete; inspect status and finish the same run.")
            if args.report:
                write_json(args.report, stats)
            print(json.dumps(stats, indent=2))
            return 0
        inspected = None
        if args.command == "query":
            inspected = inspect_documents(documents, store, config)
            if not inspected["stats"]["complete"]:
                raise ValueError("Index is incomplete; finish it before searching.")
        from vm.model import LocalEncoder
        if args.command == "index":
            encoder, model_startup_seconds = None, 0.0
            def encode(texts):
                nonlocal encoder, model_startup_seconds
                if encoder is None:
                    loading = time.perf_counter()
                    encoder = LocalEncoder(settings, device=args.device)
                    model_startup_seconds = time.perf_counter() - loading
                return encoder(texts)
            saved = 0
            def after_chunk(_record):
                nonlocal saved
                saved += 1
                if args.crash_after_saved_chunks is not None and saved >= args.crash_after_saved_chunks:
                    print(json.dumps({"controlled_interruption": True, "new_chunks_saved": saved,
                                      "note": "Hard process exit before document completion; not a Nebius preemption."}), flush=True)
                    os._exit(75)
            if args.crash_after_saved_chunks is not None and args.crash_after_saved_chunks < 1:
                raise ValueError("--crash-after-saved-chunks must be positive")
            stats = index_documents(documents, store, encode, config,
                                    batch_size=args.batch_size or settings["batch_size"],
                                    stop_after_documents=args.stop_after_documents, after_chunk_saved=after_chunk)
            # Engine timing includes the first lazy call; separate model startup
            # from actual embedding instead of calling their sum throughput.
            stats["embedding_seconds"] = max(0.0, stats["embedding_seconds"] - model_startup_seconds)
            hardware = encoder.hardware if encoder is not None else {
                "device": args.device, "model_load_seconds": 0.0, "model_not_loaded": True}
            record = {**stats, "hardware": hardware, "model_startup_seconds": model_startup_seconds,
                      "batch_size": args.batch_size or settings["batch_size"],
                      "settings": settings, "utc": datetime.now(timezone.utc).isoformat(),
                      "application_wall_seconds": time.perf_counter() - start,
                      "controlled_stop_after_documents": args.stop_after_documents}
            sizes = sorted(len(doc["text"].split()) for doc in documents)
            record["corpus"] = {"documents": len(documents), "chunks": stats["chunks_total"],
                                "text_words": sum(sizes), "text_utf8_bytes": sum(len(doc["text"].encode()) for doc in documents),
                                "document_words": {"min": min(sizes), "median": statistics.median(sizes),
                                                   "p95": sizes[int((len(sizes) - 1) * 0.95)], "max": max(sizes)}}
            # Measurements live beside, rather than inside, the strict index prefix.
            metrics = open_store(args.store.rstrip("/") + "-measurements")
            metrics.put(uuid.uuid4().hex + ".json", json.dumps(record, allow_nan=False).encode())
            if args.report:
                write_json(args.report, record)
            print(json.dumps(record, indent=2))
        else:
            if not args.text.strip() or not 1 <= args.top_k <= 20:
                raise ValueError("Use a nonempty query and --top-k 1–20")
            records = inspected["records"]
            encoder = LocalEncoder(settings, device=args.device)
            vector = encoder([f"Instruct: {QUERY_INSTRUCTION}\nQuery:{args.text.strip()}"])[0]
            matches = semantic_rank(records, vector, args.top_k)
            state = inspected["stats"]
            write_search(args.output_dir, args.text, matches, state["run_fingerprint"])
            for index, match in enumerate(matches, 1):
                print(f'{index}. {match.get("title", match["source"])} ({match["similarity"]:.4f})\n   {match.get("source_url", "")}\n   {match["text"][:450]}\n')
            print("Saved report:", args.output_dir / "search.html")
        return 0
    except (ValueError, OSError, KeyError, RuntimeError) as exc:
        # Storage/model exceptions must not dump credential-bearing requests.
        print("Error:", str(exc), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
