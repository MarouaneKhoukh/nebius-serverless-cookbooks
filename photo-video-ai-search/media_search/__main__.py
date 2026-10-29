import argparse
from dataclasses import asdict
import json
from pathlib import Path
import sys
import uuid

from .config import Settings
from .embedding import Embedder, EmbeddingError
from .media import SUPPORTED_SUFFIXES, prepare_file
from .store import Store


def ingest(settings, source, force=False, max_files=20):
    if not source.is_dir():
        raise ValueError("Input must be a directory of local images and short videos.")
    # Reject recursive use of prepared output as new input.
    if (source.resolve() == settings.data_dir.resolve()
        or source.resolve() in settings.data_dir.resolve().parents
        or settings.data_dir.resolve() in source.resolve().parents):
        raise ValueError("Keep the media input directory separate from DATA_DIR (and its parents).")
    files = sorted(p for p in source.rglob("*")
                   if p.is_file() and not p.is_symlink() and p.suffix.lower() in SUPPORTED_SUFFIXES)
    if len(files) > max_files:
        raise ValueError(f"Found {len(files)} media files; first-run limit is {max_files}. "
                         "Use a smaller input directory or explicitly raise --max-files.")
    if not files:
        raise ValueError("No supported media found in input directory.")
    embedder = Embedder(settings)
    store = Store(settings)
    added = skipped = failed = 0
    try:
        store.ensure()
        for source_file in files:
            try:
                for media in prepare_file(source_file, settings.data_dir):
                    point_id = str(uuid.uuid5(uuid.NAMESPACE_URL, f"media-search:{media.id}"))
                    if not force and store.existing(point_id):
                        skipped += 1
                        print(f"skip {media.title}")
                        continue
                    vector = embedder.media(settings.data_dir / media.media_path, media.kind)
                    payload = asdict(media)
                    # URLs are rooted at data/media rather than at data itself.
                    payload["media_path"] = str(Path(media.media_path).relative_to("media"))
                    payload["thumbnail_path"] = str(Path(media.thumbnail_path).relative_to("media"))
                    store.upsert(point_id, vector, payload)
                    added += 1
                    print(f"indexed {media.title}")
            except EmbeddingError as exc:
                failed += 1
                print(f"failed {source_file.name}: {exc} Stopping this batch; retry after fixing the Endpoint.", file=sys.stderr)
                break
            except (ValueError, RuntimeError, OSError) as exc:
                failed += 1
                print(f"failed {source_file.name}: {exc}", file=sys.stderr)
        print(json.dumps({"indexed": added, "skipped": skipped, "failed_sources": failed,
                          "collection_points": store.count()}))
        return 1 if failed else 0
    finally:
        embedder.close()
        store.close()


def main():
    parser = argparse.ArgumentParser(description="Persistent photo and video search with Qwen3-VL + Qdrant.")
    sub = parser.add_subparsers(dest="command", required=True)
    p = sub.add_parser("ingest", help="Preprocess and embed local media (uses your GPU Endpoint).")
    p.add_argument("source", type=Path)
    p.add_argument("--max-files", type=int, default=20)
    p.add_argument("--force", action="store_true", help="Re-embed existing deterministic points.")
    p = sub.add_parser("check-endpoint", help="Wait for readiness, then request one text embedding.")
    p.add_argument("--timeout", type=int, default=900)
    p = sub.add_parser("search", help="Embed a text query and return matching media.")
    p.add_argument("query")
    p.add_argument("--kind", choices=["all", "image", "video"], default="all")
    sub.add_parser("serve", help="Start local gallery on http://127.0.0.1:8080.")
    args = parser.parse_args()
    settings = Settings.from_env()
    try:
        if args.command == "serve":
            import uvicorn
            from .app import create_app
            uvicorn.run(create_app(settings), host="127.0.0.1", port=8080)
            return 0
        if args.command == "ingest":
            if args.max_files < 1:
                raise ValueError("--max-files must be positive.")
            return ingest(settings, args.source, args.force, args.max_files)
        embedder = Embedder(settings)
        try:
            if args.command == "check-endpoint":
                if not 1 <= args.timeout <= 1800:
                    raise ValueError("--timeout must be between 1 and 1800 seconds.")
                embedder.wait_ready(args.timeout)
                vector = embedder.text("a red circle")
                print(json.dumps({"ready": True, "model": settings.model, "dimensions": len(vector)}))
            else:
                if not args.query.strip() or len(args.query) > 500:
                    raise ValueError("Query must contain 1–500 characters.")
                store = Store(settings)
                try:
                    store.ensure()
                    print(json.dumps({"query": args.query,
                        "items": store.search(embedder.text(args.query), args.kind)}, indent=2))
                finally:
                    store.close()
        finally:
            embedder.close()
    except Exception as exc:
        # SDK exception strings can contain request details. Display only our own errors.
        message = str(exc) if isinstance(exc, (ValueError, RuntimeError)) else (
            "Operation failed; check local files, Qdrant availability and configuration.")
        print(message, file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
