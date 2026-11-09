"""A resumable local client for a Spot-hosted OpenAI-compatible model.

The durable state belongs on the client, never on the preemptible Endpoint.
No access token or Endpoint URL is written to result files.
"""

from __future__ import annotations

import csv
import fcntl
import hashlib
import html
import io
import json
import os
from pathlib import Path
import re
import tempfile
import time
from typing import Callable
import urllib.error
import urllib.parse
import urllib.request

MODEL = "Qwen/Qwen2.5-0.5B-Instruct"
LABELS = ("billing", "technical", "account")
SYSTEM_PROMPT = "Classify support tickets as billing, technical, or account. Return only the category."


class RecipeError(Exception):
    """An actionable error safe to show without leaking Endpoint credentials."""


def load_rows(path: Path, *, evaluation: bool = False) -> list[dict[str, str]]:
    with path.open(encoding="utf-8-sig", newline="") as stream:
        reader = csv.DictReader(stream)
        required = {"id", "prompt"} | ({"expected"} if evaluation else set())
        if reader.fieldnames is None or not required.issubset(reader.fieldnames):
            raise RecipeError(f"CSV must contain columns: {', '.join(sorted(required))}")
        if len(set(reader.fieldnames)) != len(reader.fieldnames):
            raise RecipeError("CSV has duplicate column names")
        rows: list[dict[str, str]] = []
        seen: set[str] = set()
        for line, source in enumerate(reader, 2):
            if None in source or any(value is None for value in source.values()):
                raise RecipeError(f"Malformed CSV row at line {line}")
            row = {key: value.strip() for key, value in source.items()}
            if not row["id"] or not row["prompt"]:
                raise RecipeError(f"Empty id or prompt at line {line}")
            if row["id"] in seen:
                raise RecipeError(f"Duplicate id at line {line}: {row['id']}")
            if evaluation and row["expected"] not in LABELS:
                raise RecipeError(f"Expected label at line {line} must be one of {LABELS}")
            seen.add(row["id"])
            rows.append(row)
    if not rows:
        raise RecipeError("CSV has no input rows")
    return rows


def normalize_label(response: str) -> str | None:
    # Permit formatting around a single label; never accept a label buried in prose.
    value = response.strip().lower().removesuffix(".").strip()
    value = value.strip('"\'`').strip()
    return value if value in LABELS else None


def atomic_write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary: str | None = None
    try:
        with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=path.parent, delete=False) as stream:
            temporary = stream.name
            stream.write(text)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
        temporary = None
        directory = os.open(path.parent, os.O_RDONLY)
        try:
            os.fsync(directory)
        finally:
            os.close(directory)
    finally:
        if temporary is not None:
            Path(temporary).unlink(missing_ok=True)


def write_json(path: Path, value: object) -> None:
    atomic_write(path, json.dumps(value, ensure_ascii=False, indent=2) + "\n")


def read_json(path: Path) -> dict:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(value, dict):
            raise ValueError("not an object")
        return value
    except (ValueError, OSError) as exc:
        raise RecipeError(f"Cannot read saved state {path}. Keep it for inspection; use a new output directory.") from exc


def safe_base_url(value: str) -> str:
    base = value.rstrip("/")
    if base.endswith("/v1"):
        base = base[:-3]
    parsed = urllib.parse.urlparse(base)
    loopback = parsed.hostname in {"localhost", "127.0.0.1", "::1"}
    if parsed.scheme != "https" and not (parsed.scheme == "http" and loopback):
        raise RecipeError("BASE_URL must use HTTPS (HTTP is allowed only for local tests)")
    if not parsed.hostname or parsed.username or parsed.password or parsed.query or parsed.fragment:
        raise RecipeError("BASE_URL must be an Endpoint URL without credentials, query parameters or a fragment")
    return base


class Endpoint:
    def __init__(self, base_url: str, token: str, *, timeout: float = 120, attempts: int = 3):
        self.base_url = safe_base_url(base_url)
        if not token:
            raise RecipeError("ENDPOINT_TOKEN is missing. Run through scripts/endpoint.py or set it in your shell.")
        if attempts < 1 or attempts > 5 or timeout <= 0:
            raise RecipeError("Request attempts must be 1–5 and timeout must be positive")
        self._token = token
        self.timeout, self.attempts = timeout, attempts

    @classmethod
    def from_environment(cls, **kwargs) -> "Endpoint":
        base = os.environ.get("BASE_URL", "")
        if not base:
            raise RecipeError("BASE_URL is missing. Run through scripts/endpoint.py or set it in your shell.")
        return cls(base, os.environ.get("ENDPOINT_TOKEN", ""), **kwargs)

    def request(self, path: str, payload: dict | None = None) -> dict:
        body = None if payload is None else json.dumps(payload).encode()
        request = urllib.request.Request(
            self.base_url + path,
            data=body,
            headers={"Authorization": "Bearer " + self._token, "Content-Type": "application/json"},
            method="GET" if payload is None else "POST",
        )
        for attempt in range(self.attempts):
            try:
                with urllib.request.urlopen(request, timeout=self.timeout) as response:
                    result = json.load(response)
                if not isinstance(result, dict):
                    raise RecipeError("Endpoint returned a non-object JSON response")
                return result
            except urllib.error.HTTPError as exc:
                code = exc.code
                # Do not print response bodies: they can echo request details or secrets.
                if code in {401, 403}:
                    raise RecipeError(f"Endpoint returned HTTP {code}. Check token/authentication; no retry was attempted.") from None
                if code not in {408, 429, 500, 502, 503, 504}:
                    raise RecipeError(f"Endpoint returned HTTP {code}. Check the model and request configuration.") from None
                message = f"Endpoint returned HTTP {code}"
            except (urllib.error.URLError, TimeoutError, ConnectionError, OSError):
                message = "Endpoint could not be reached"
            except (json.JSONDecodeError, UnicodeError):
                raise RecipeError("Endpoint returned invalid JSON") from None
            if attempt + 1 == self.attempts:
                raise RecipeError(message + ". Saved rows are safe. Check Endpoint state, restart if needed, then rerun the same command.")
            time.sleep(min(2 ** attempt, 4))
        raise AssertionError("unreachable")

    def wait(self, model: str, *, deadline: float = 900) -> None:
        end = time.monotonic() + deadline
        while True:
            try:
                payload = self.request("/v1/models")
                models = {item.get("id") for item in payload.get("data", []) if isinstance(item, dict)}
                if model not in models:
                    raise RecipeError(f"Endpoint is ready but does not list model {model}")
                return
            except RecipeError as exc:
                if "HTTP 401" in str(exc) or "HTTP 403" in str(exc) or "does not list model" in str(exc):
                    raise
                if time.monotonic() >= end:
                    raise RecipeError("Model readiness timed out. Check Endpoint state and logs; stop compute while diagnosing.") from None
                time.sleep(min(5, max(0, end - time.monotonic())))

    def complete(self, prompt: str, settings: dict) -> dict:
        payload = self.request("/v1/chat/completions", {
            "model": settings["model"],
            "messages": [{"role": "system", "content": settings["system_prompt"]}, {"role": "user", "content": prompt}],
            "temperature": settings["temperature"], "max_tokens": settings["max_tokens"], "seed": settings["seed"],
        })
        try:
            choice = payload["choices"][0]
            response = choice["message"]["content"]
            if not isinstance(response, str) or not response.strip():
                raise ValueError("empty response")
            return {"response": response, "label": normalize_label(response), "finish_reason": choice.get("finish_reason"), "usage": payload.get("usage", {})}
        except (KeyError, IndexError, TypeError, ValueError):
            raise RecipeError("Endpoint returned no usable assistant text. This row was not marked complete.") from None


def settings_for(model: str = MODEL, revision: str = "") -> dict:
    return {"model": model, "model_revision": revision, "system_prompt": SYSTEM_PROMPT, "temperature": 0, "max_tokens": 16, "seed": 42}


def record_path(directory: Path, row_id: str) -> Path:
    return directory / "items" / (hashlib.sha256(row_id.encode()).hexdigest() + ".json")


def run_rows(rows: list[dict[str, str]], directory: Path, settings: dict, complete: Callable, *, limit: int | None = None) -> list[dict]:
    if limit is not None and limit < 1:
        raise RecipeError("--limit must be at least 1")
    directory.mkdir(parents=True, exist_ok=True)
    with (directory / ".lock").open("a+") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise RecipeError("Another process is using this output directory") from None
        content = {"schema": 1, "rows": rows, "settings": settings}
        fingerprint = hashlib.sha256(json.dumps(content, ensure_ascii=False, sort_keys=True).encode()).hexdigest()
        manifest_path = directory / "run.json"
        if manifest_path.exists():
            if read_json(manifest_path).get("fingerprint") != fingerprint:
                raise RecipeError("Input, model or generation settings changed. Use a new --output-dir; existing results were preserved.")
        else:
            write_json(manifest_path, {"fingerprint": fingerprint, "settings": settings, "input_rows": len(rows)})
        records: list[dict] = []
        generated = 0
        for row in rows:
            path = record_path(directory, row["id"])
            if path.exists():
                record = read_json(path)
                if record.get("fingerprint") != fingerprint or record.get("id") != row["id"] or not isinstance(record.get("response"), str):
                    raise RecipeError(f"Saved record for {row['id']} does not match this run; use a new output directory.")
                print(f"saved: {row['id']}", flush=True)
            elif limit is None or generated < limit:
                result = complete(row["prompt"], settings)
                record = {**row, **result, "fingerprint": fingerprint}
                write_json(path, record)
                generated += 1
                print(f"completed: {row['id']}", flush=True)
            else:
                continue
            records.append(record)
        return records


def saved_records(rows: list[dict[str, str]], directory: Path) -> list[dict]:
    return [read_json(record_path(directory, row["id"])) for row in rows if record_path(directory, row["id"]).exists()]


def write_csv(path: Path, fields: list[str], records: list[dict]) -> None:
    stream = io.StringIO(newline="")
    writer = csv.DictWriter(stream, fieldnames=fields, extrasaction="ignore")
    writer.writeheader()
    writer.writerows(records)
    atomic_write(path, stream.getvalue())


def brand_svg() -> str:
    path = Path(__file__).resolve().parents[1] / "docs" / "brand" / "nebius-logo.svg"
    if not path.is_file():
        raise RecipeError("Bundled Nebius artwork is missing; restore docs/brand/nebius-logo.svg before running.")
    return path.read_text(encoding="utf-8")


def render_report(path: Path, title: str, summary: str, fields: list[str], records: list[dict]) -> None:
    heading = "".join("<th>" + html.escape(field) + "</th>" for field in fields)
    body = "".join("<tr>" + "".join("<td>" + html.escape(str(record.get(field, "") if record.get(field) is not None else "invalid")) + "</td>" for field in fields) + "</tr>" for record in records)
    atomic_write(path, "<!doctype html><html lang='en'><meta charset='utf-8'><meta name='viewport' content='width=device-width,initial-scale=1'>"
        + "<title>" + html.escape(title) + "</title><style>body{font:16px/1.55 system-ui,sans-serif;color:#24271f;background:#f7f7ef;margin:0;padding:32px}main{max-width:1180px;margin:auto}header{display:flex;gap:24px;align-items:center;flex-wrap:wrap}header svg{width:140px;height:auto}h1{font-size:32px;line-height:1.15}p{color:#555a4c}.summary{padding:20px;background:#e1f58a;border-radius:12px;color:#24271f}.table{overflow:auto;background:white;border:1px solid #d8ddce;border-radius:12px}table{border-collapse:collapse;width:100%}th,td{padding:14px;text-align:left;vertical-align:top;border-bottom:1px solid #e1e4db}th{background:#ecefe3}footer{margin-top:24px;font-size:14px;color:#555a4c}</style><main><header>"
        + brand_svg() + "<strong>Powered by Nebius Serverless AI</strong></header><h1>" + html.escape(title) + "</h1><p class='summary'>" + html.escape(summary)
        + "</p><div class='table'><table><thead><tr>" + heading + "</tr></thead><tbody>" + body
        + "</tbody></table></div><footer>Saved model responses.</footer></main></html>")
