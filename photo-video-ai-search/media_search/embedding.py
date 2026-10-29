import base64
import math
import time
from pathlib import Path

import httpx

from .config import INSTRUCTION, VIDEO_FRAMES, Settings


class EmbeddingError(RuntimeError):
    pass


class Embedder:
    def __init__(self, settings: Settings, client: httpx.Client | None = None):
        settings.require_embedding()
        self.settings = settings
        self.client = client or httpx.Client(timeout=httpx.Timeout(300, connect=15),
                                             follow_redirects=False)

    def close(self):
        self.client.close()

    def _request(self, content: list[dict], video: bool = False):
        body = {
            "model": self.settings.model,
            "encoding_format": "float",
            "messages": [
                {"role": "system", "content": [{"type": "text", "text": INSTRUCTION}]},
                {"role": "user", "content": content},
                {"role": "assistant", "content": [{"type": "text", "text": ""}]},
            ],
            "continue_final_message": True,
            "add_special_tokens": True,
        }
        if video:
            body["media_io_kwargs"] = {"video": {"num_frames": VIDEO_FRAMES}}
        try:
            response = self.client.post(
                f"{self.settings.embedding_url}/v1/embeddings", json=body,
                headers={"Authorization": f"Bearer {self.settings.embedding_token}"},
            )
            response.raise_for_status()
            data = response.json()["data"]
            if len(data) != 1:
                raise ValueError("expected one embedding")
            vector = data[0]["embedding"]
            if not isinstance(vector, list) or len(vector) != self.settings.dimensions:
                raise ValueError("unexpected embedding dimension")
            if any(type(x) not in {float, int} or not math.isfinite(x) for x in vector):
                raise ValueError("non-finite or non-numeric embedding")
            norm = math.sqrt(sum(x * x for x in vector))
            if norm == 0 or not math.isfinite(norm):
                raise ValueError("invalid embedding norm")
            return [x / norm for x in vector]
        except httpx.HTTPStatusError as exc:
            # Do not echo an upstream body: it can contain media or request details.
            raise EmbeddingError(f"Embedding Endpoint returned HTTP {exc.response.status_code}; "
                                 "check readiness, auth, model and payload limits.") from None
        except httpx.HTTPError:
            raise EmbeddingError("Cannot reach the embedding Endpoint; check its URL and running state.") from None
        except (ValueError, KeyError, TypeError, OverflowError):
            raise EmbeddingError("Invalid embedding response; check the model and EMBEDDING_DIMENSIONS.") from None

    def text(self, text: str):
        return self._request([{"type": "text", "text": text}])

    def media(self, path: Path, kind: str):
        if path.stat().st_size > 8 * 1024 * 1024:
            raise ValueError("Prepared media exceeds the 8 MiB per-item upload limit.")
        if kind not in {"image", "video"}:
            raise ValueError("Unsupported media kind.")
        mime = "image/jpeg" if kind == "image" else "video/mp4"
        key = f"{kind}_url"
        url = f"data:{mime};base64," + base64.b64encode(path.read_bytes()).decode("ascii")
        return self._request([{ "type": key, key: {"url": url}},
                              {"type": "text", "text": ""}], video=kind == "video")

    def wait_ready(self, seconds: int = 900):
        deadline = time.monotonic() + seconds
        while time.monotonic() < deadline:
            try:
                result = self.client.get(f"{self.settings.embedding_url}/v1/models",
                    headers={"Authorization": f"Bearer {self.settings.embedding_token}"}, timeout=15)
                if result.status_code in {401, 403}:
                    raise EmbeddingError("Endpoint rejected authentication; check EMBEDDING_API_KEY.")
                if result.is_success:
                    models = result.json().get("data", [])
                    if any(m.get("id") == self.settings.model for m in models):
                        return
                    raise EmbeddingError("Endpoint is serving a different model than EMBEDDING_MODEL.")
            except (httpx.HTTPError, ValueError):
                pass
            time.sleep(min(5, max(0, deadline - time.monotonic())))
        raise EmbeddingError("Endpoint was not ready within the bounded wait. Inspect its status and logs.")
