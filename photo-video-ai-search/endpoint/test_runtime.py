"""CPU-only API boundary and shared-lock checks; no weights or GPU are loaded.

Run: python -m unittest discover -s endpoint -p 'test_*.py' -v
Requires the cookbook's existing FastAPI/httpx development environment.
"""
import concurrent.futures
import importlib.util
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import patch

import httpx
from fastapi.testclient import TestClient
from pydantic import ValidationError

HERE = Path(__file__).parent


def load(name):
    spec = importlib.util.spec_from_file_location(name, HERE / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


gateway = load("gateway")
flux_service = load("flux_service")
supervisor = load("supervise")


class RuntimeTests(unittest.TestCase):
    def test_preflight_rejects_small_gpu_or_old_cuda_driver(self):
        from types import SimpleNamespace
        for row in ("81920, 580.95.05\n", "96256, 575.57.08\n"):
            with patch.object(supervisor.subprocess, "run", return_value=SimpleNamespace(stdout=row)):
                with self.subTest(row=row), self.assertRaises(RuntimeError):
                    supervisor.validate_memory()

    def test_preflight_accepts_one_96gb_gpu_and_cuda13_driver(self):
        from types import SimpleNamespace
        with patch.object(supervisor.subprocess, "run", return_value=SimpleNamespace(stdout="96256, 580.95.05\n")):
            self.assertEqual(supervisor.validate_memory(), 0.25)

    def test_generation_contract_rejects_unbounded_work(self):
        self.assertEqual(flux_service.ImageRequest(prompt="a cabin").n, 1)
        for change in [
            {"n": 2}, {"size": "2048x2048"}, {"model": "another-model"},
            {"response_format": "url"}, {"prompt": "   "}, {"steps": 50},
        ]:
            with self.subTest(change=change), self.assertRaises(ValidationError):
                flux_service.ImageRequest(**({"prompt": "a cabin"} | change))

    def test_embedding_payload_passes_without_credential_forwarding(self):
        captured = []

        class Backend:
            def __init__(self, **kwargs):
                pass
            def __enter__(self):
                return self
            def __exit__(self, *args):
                pass
            def post(self, url, **kwargs):
                captured.append((url, kwargs))
                return httpx.Response(200, json={"data": [{"embedding": [0.1, 0.2]}]})

        body = {"model": "Qwen/Qwen3-VL-Embedding-8B", "messages": [{"role": "user", "content": [
            {"type": "image_url", "image_url": {"url": "data:image/jpeg;base64,eA=="}},
        ]}], "continue_final_message": True, "encoding_format": "float"}
        with tempfile.TemporaryDirectory() as folder, patch.dict("os.environ", {"GPU_LOCK_PATH": folder + "/gpu.lock"}):
            app = gateway.create_app("embedding")
            client = TestClient(app)
            with patch.object(gateway.httpx, "Client", Backend):
                result = client.post("/v1/embeddings", json=body, headers={"Authorization": "Bearer test-public-only"})
        self.assertEqual(result.status_code, 200)
        self.assertEqual(captured, [("http://127.0.0.1:8002/v1/embeddings", {"json": body})])

    def test_generation_holds_shared_lock_against_embedding_gateway(self):
        active = threading.Event()
        release = threading.Event()
        calls = []

        class Backend:
            def __init__(self, **kwargs):
                pass
            def __enter__(self):
                return self
            def __exit__(self, *args):
                pass
            def post(self, url, **kwargs):
                calls.append(url)
                active.set()
                release.wait(3)
                return httpx.Response(200, json={"data": [{"b64_json": "eA=="}]})

        original_lock = gateway.gpu_lock
        with tempfile.TemporaryDirectory() as folder, patch.dict("os.environ", {"GPU_LOCK_PATH": folder + "/gpu.lock"}):
            generation = TestClient(gateway.create_app("generation"))
            embedding = TestClient(gateway.create_app("embedding"))
            with patch.object(gateway.httpx, "Client", Backend), patch.object(
                gateway, "gpu_lock", lambda path: original_lock(path, seconds=0.1)
            ), concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
                future = pool.submit(generation.post, "/v1/images/generations", json={"prompt": "a cabin"})
                self.assertTrue(active.wait(2))
                result = embedding.post("/v1/embeddings", json={"model": "Qwen/Qwen3-VL-Embedding-8B"})
                self.assertEqual(result.status_code, 429)
                self.assertEqual(len(calls), 1, "Embedding must not reach its model during generation.")
                release.set()
                self.assertEqual(future.result(timeout=2).status_code, 200)

    def test_upstream_error_body_is_not_exposed(self):
        class Backend:
            def __init__(self, **kwargs):
                pass
            def __enter__(self):
                return self
            def __exit__(self, *args):
                pass
            def post(self, *args, **kwargs):
                return httpx.Response(500, text="private prompt / secret upstream diagnostics")
        with tempfile.TemporaryDirectory() as folder, patch.dict("os.environ", {"GPU_LOCK_PATH": folder + "/gpu.lock"}):
            client = TestClient(gateway.create_app("generation"))
            with patch.object(gateway.httpx, "Client", Backend):
                result = client.post("/v1/images/generations", json={"prompt": "a cabin"})
        self.assertEqual(result.status_code, 500)
        self.assertNotIn("private", result.text)
        self.assertNotIn("secret", result.text)

    def test_invalid_json_rejected_without_backend(self):
        with tempfile.TemporaryDirectory() as folder, patch.dict("os.environ", {"GPU_LOCK_PATH": folder + "/gpu.lock"}):
            client = TestClient(gateway.create_app("embedding"))
            self.assertEqual(client.post("/v1/embeddings", content="[1,2]").status_code, 400)
            self.assertEqual(client.post("/v1/embeddings", content="broken").status_code, 400)


if __name__ == "__main__":
    unittest.main()
