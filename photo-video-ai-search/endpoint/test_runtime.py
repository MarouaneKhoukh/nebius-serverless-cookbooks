"""CPU-only API boundary and shared-lock checks; no weights or GPU are loaded.

Run: python -m unittest discover -s endpoint -p 'test_*.py' -v
Requires the cookbook's existing FastAPI/httpx development environment.
"""
import concurrent.futures
import importlib.util
import sys
import tempfile
import threading
import unittest
from contextlib import nullcontext
from pathlib import Path
from types import ModuleType, SimpleNamespace
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

    def test_official_refusal_messages_have_safe_specific_diagnostics(self):
        cases = [
            ("The prompt may name a copyrighted character, a brand or a public figure.",
             "prompt", "copyright_or_public_figure"),
            ("The generated image may show a copyrighted character, a brand or a public figure, so it was not returned. Try another prompt or seed.",
             "output", "copyright_or_public_figure"),
            ("The generated image may show nudity or other adult content, so it was not returned. Try another prompt or seed.",
             "output", "adult_content"),
            ("Reference image 1 may show nudity or other adult content.", "reference", "adult_content"),
            ("Reference image 12 may show a copyrighted character, a brand or a public figure.",
             "reference", "copyright_or_public_figure"),
        ]
        for message, stage, category in cases:
            with self.subTest(stage=stage, category=category):
                self.assertEqual(flux_service.refusal_diagnostic(Exception(message)), {
                    "stage": stage, "category": category,
                })
        for message in [
            "private prompt: football; token=secret",
            "The prompt may name a copyrighted character, a brand or a public figure. private prompt",
            "The generated image may show private media, so it was not returned. Try another prompt or seed.",
        ]:
            self.assertEqual(flux_service.refusal_diagnostic(Exception(message)), {
                "stage": "unknown", "category": "unknown",
            })

    def test_generation_refusal_retains_checks_and_releases_generation_lock(self):
        class Refused(Exception):
            pass

        calls = []
        generate_module = ModuleType("flux3.generate")
        generate_module.Refused = Refused

        def generate(*args, **kwargs):
            calls.append(kwargs)
            raise Refused("The prompt may name a copyrighted character, a brand or a public figure.")

        generate_module.generate = generate
        safety_module = ModuleType("flux3.safety")
        safety_module.exif = lambda model: None
        fake_modules = {
            "torch": SimpleNamespace(inference_mode=nullcontext),
            "flux3": ModuleType("flux3"), "flux3.generate": generate_module, "flux3.safety": safety_module,
        }
        with patch.dict(sys.modules, fake_modules), patch.object(flux_service, "models", object()):
            client = TestClient(flux_service.app)
            for _ in range(2):
                result = client.post("/v1/images/generations", json={"prompt": "private prompt"})
                self.assertEqual(result.status_code, 400)
                self.assertEqual(result.json()["detail"]["code"], "model_declined")
                self.assertEqual(result.json()["detail"]["stage"], "prompt")
                self.assertNotIn("private prompt", result.text)
        self.assertEqual(len(calls), 2, "A refusal must release the local generation lock.")
        self.assertTrue(all(call["safety"] is True and call["pup"] is True for call in calls))

    def test_gateway_exposes_only_allowlisted_refusal_labels(self):
        for labels, expected in [
            ({"stage": "output", "category": "adult_content"}, {"stage": "output", "category": "adult_content"}),
            ({"stage": "private prompt", "category": "secret"}, {"stage": "unknown", "category": "unknown"}),
            ({"stage": ["output"], "category": {"secret": True}}, {"stage": "unknown", "category": "unknown"}),
        ]:
            backend_response = httpx.Response(400, json={"detail": {
                "code": "model_declined", "message": "private prompt / secret", "unexpected": "secret", **labels,
            }, "prompt": "secret"})

            class Backend:
                def __init__(self, **kwargs):
                    pass
                def __enter__(self):
                    return self
                def __exit__(self, *args):
                    pass
                def post(self, *args, **kwargs):
                    return backend_response

            with tempfile.TemporaryDirectory() as folder, patch.dict("os.environ", {"GPU_LOCK_PATH": folder + "/gpu.lock"}):
                client = TestClient(gateway.create_app("generation"))
                with patch.object(gateway.httpx, "Client", Backend):
                    result = client.post("/v1/images/generations", json={"prompt": "a cabin"})
            self.assertEqual(result.status_code, 400)
            payload = result.json()
            self.assertEqual(set(payload), {"detail", "code", "stage", "category"})
            self.assertEqual(payload["code"], "model_declined")
            self.assertEqual({key: payload[key] for key in expected}, expected)
            self.assertNotIn("private", result.text)
            self.assertNotIn("secret", result.text)

    def test_other_bad_requests_are_not_reported_as_model_refusals(self):
        for response in [
            httpx.Response(400, text="private prompt / secret"),
            httpx.Response(400, json={"detail": "private prompt / secret"}),
            httpx.Response(400, json={"detail": {"code": "invalid_request", "stage": "output"}}),
            httpx.Response(422, json={"detail": {"code": "model_declined", "stage": "output"}}),
        ]:
            self.assertIsNone(gateway.model_declined_diagnostic(response))

            class Backend:
                def __init__(self, **kwargs):
                    pass
                def __enter__(self):
                    return self
                def __exit__(self, *args):
                    pass
                def post(self, *args, **kwargs):
                    return response

            with tempfile.TemporaryDirectory() as folder, patch.dict("os.environ", {"GPU_LOCK_PATH": folder + "/gpu.lock"}):
                client = TestClient(gateway.create_app("generation"))
                with patch.object(gateway.httpx, "Client", Backend):
                    result = client.post("/v1/images/generations", json={"prompt": "a cabin"})
            self.assertEqual(result.status_code, response.status_code)
            self.assertNotIn("model_declined", result.text)
            self.assertNotIn("private", result.text)
            self.assertNotIn("secret", result.text)

    def test_invalid_json_rejected_without_backend(self):
        with tempfile.TemporaryDirectory() as folder, patch.dict("os.environ", {"GPU_LOCK_PATH": folder + "/gpu.lock"}):
            client = TestClient(gateway.create_app("embedding"))
            self.assertEqual(client.post("/v1/embeddings", content="[1,2]").status_code, 400)
            self.assertEqual(client.post("/v1/embeddings", content="broken").status_code, 400)


if __name__ == "__main__":
    unittest.main()
