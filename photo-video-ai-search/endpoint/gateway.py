"""Two thin public gateways sharing one Linux advisory GPU lock.

Inference stays locked until the upstream completes. An inference timeout exits
this gateway; the supervisor then stops all model processes, preventing a timed-
out background generation from overlapping a subsequent embedding request.
"""
import argparse
import fcntl
import json
import os
import threading
import time
from contextlib import contextmanager
from pathlib import Path

import httpx
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse, Response
from starlette.background import BackgroundTask
try:
    from endpoint.gpu_telemetry import GpuTelemetry
except ModuleNotFoundError:
    from gpu_telemetry import GpuTelemetry

MAX_BODY = 12 * 1024 * 1024
WAIT_SECONDS = 10


@contextmanager
def gpu_lock(path, seconds=WAIT_SECONDS):
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    with open(path, "a") as handle:
        deadline = time.monotonic() + seconds
        while True:
            try:
                fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
                break
            except BlockingIOError:
                if time.monotonic() >= deadline:
                    raise HTTPException(429, "GPU is busy; retry after the current request finishes.") from None
                time.sleep(0.05)
        try:
            yield
        finally:
            fcntl.flock(handle, fcntl.LOCK_UN)


def create_app(kind: str):
    if kind not in {"embedding", "generation"}:
        raise ValueError("Unsupported gateway kind")
    app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None)
    backend = "http://127.0.0.1:" + ("8002" if kind == "embedding" else "8003")
    max_seconds = 300 if kind == "embedding" else 600
    slots = threading.BoundedSemaphore(2)
    lock_path = os.environ.get("GPU_LOCK_PATH", "/run/cookbook/gpu.lock")
    telemetry = GpuTelemetry()

    @app.get("/v1/runtime/gpu")
    def gpu_runtime():
        return telemetry.snapshot()

    @app.get("/health")
    def health():
        if Path(lock_path + ".unhealthy").exists():
            raise HTTPException(503, "Model runtime is restarting safely.")
        try:
            with httpx.Client(timeout=3, trust_env=False) as client:
                result = client.get(backend + "/health")
            if result.status_code == 200:
                return {"status": "ready", "service": kind}
        except httpx.HTTPError:
            pass
        raise HTTPException(503, "Model service is not ready.")

    @app.get("/v1/models")
    def models_list():
        try:
            with httpx.Client(timeout=3, trust_env=False) as client:
                result = client.get(backend + "/v1/models")
            if result.status_code == 200:
                return Response(result.content, media_type="application/json")
        except httpx.HTTPError:
            pass
        raise HTTPException(503, "Model service is not ready.")

    @app.post("/v1/embeddings" if kind == "embedding" else "/v1/images/generations")
    async def inference(request: Request):
        # Enforce bytes while reading; Content-Length is not trusted.
        payload = bytearray()
        async for chunk in request.stream():
            payload.extend(chunk)
            if len(payload) > MAX_BODY:
                raise HTTPException(413, "Request exceeds the 12 MiB limit.")
        try:
            body = json.loads(payload)
            if not isinstance(body, dict):
                raise ValueError
        except (ValueError, UnicodeError):
            raise HTTPException(400, "Expected a JSON object.") from None
        if not slots.acquire(blocking=False):
            raise HTTPException(429, "Request queue is full; retry shortly.")
        try:
            # Offload the whole synchronous lock + proxy operation together.
            # Cancelling a browser request does not cancel or unlock this worker.
            from starlette.concurrency import run_in_threadpool
            return await run_in_threadpool(forward, body)
        finally:
            slots.release()

    def forward(body):
        with gpu_lock(lock_path):
            poison = Path(lock_path + ".unhealthy")
            if poison.exists():
                raise HTTPException(503, "Model runtime is restarting safely.")
            with telemetry.operation(kind):
                return proxy(body, poison)

    def proxy(body, poison):
        try:
            path = "/v1/embeddings" if kind == "embedding" else "/v1/images/generations"
            with httpx.Client(timeout=httpx.Timeout(max_seconds, connect=5), trust_env=False) as client:
                result = client.post(backend + path, json=body)
        except httpx.TimeoutException:
            # Never run a new GPU operation while a timed-out one may persist.
            poison.touch()
            return JSONResponse(
                {"detail": "Model operation timed out; the runtime is restarting safely."},
                status_code=504, background=BackgroundTask(os._exit, 70),
            )
        except httpx.HTTPError:
            raise HTTPException(503, "Model service is unavailable.") from None
        if result.is_success:
            return Response(result.content, media_type="application/json")
        # Do not forward upstream error bodies that can contain prompts/media.
        message = "Model request was rejected; check request fields and media limits."
        if result.status_code == 429:
            message = "GPU is busy; retry shortly."
        elif kind == "generation" and result.status_code == 400:
            message = "The model declined the request or its output. Try a different description."
        return JSONResponse({"detail": message}, status_code=result.status_code)

    return app


if __name__ == "__main__":
    import uvicorn
    parser = argparse.ArgumentParser()
    parser.add_argument("kind", choices=["embedding", "generation"])
    args = parser.parse_args()
    uvicorn.run(create_app(args.kind), host="0.0.0.0", port=8000 if args.kind == "embedding" else 8001,
                workers=1, access_log=False, log_level="warning")
