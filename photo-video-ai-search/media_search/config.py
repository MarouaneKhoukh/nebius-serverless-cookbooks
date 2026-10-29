from dataclasses import dataclass
import hashlib
import json
import os
from pathlib import Path
from urllib.parse import urlsplit

from dotenv import load_dotenv

from .media import PREPROCESS_VERSION


INSTRUCTION = "Represent the user's input."
VIDEO_FRAMES = 8


@dataclass(frozen=True)
class Settings:
    data_dir: Path = Path("data")
    qdrant_url: str = "http://127.0.0.1:6333"
    collection: str = "photo_video_qwen3vl8b_v1"
    embedding_url: str = ""
    embedding_token: str = ""
    model: str = "Qwen/Qwen3-VL-Embedding-8B"
    dimensions: int = 4096
    qdrant_api_key: str = ""

    @classmethod
    def from_env(cls):
        load_dotenv()
        return cls(
            data_dir=Path(os.getenv("DATA_DIR", "data")).resolve(),
            qdrant_url=os.getenv("QDRANT_URL", "http://127.0.0.1:6333"),
            collection=os.getenv("QDRANT_COLLECTION", "photo_video_qwen3vl8b_v1"),
            embedding_url=os.getenv("EMBEDDING_BASE_URL", "").rstrip("/"),
            embedding_token=os.getenv("EMBEDDING_API_KEY", ""),
            model=os.getenv("EMBEDDING_MODEL", "Qwen/Qwen3-VL-Embedding-8B"),
            dimensions=int(os.getenv("EMBEDDING_DIMENSIONS", "4096")),
            qdrant_api_key=os.getenv("QDRANT_API_KEY", ""),
        )

    @property
    def vector_name(self):
        # A same-size vector from a different model/prompt is not compatible.
        contract = [self.model, self.dimensions, INSTRUCTION,
                    "vllm-0.19.1-chat-final-assistant", VIDEO_FRAMES, PREPROCESS_VERSION]
        digest = hashlib.sha256(json.dumps(contract).encode()).hexdigest()[:16]
        return f"media_{digest}"

    def require_embedding(self):
        parsed = urlsplit(self.embedding_url)
        if (not parsed.hostname or parsed.query or parsed.fragment
            or parsed.username is not None or parsed.password is not None):
            raise ValueError("Set EMBEDDING_BASE_URL to the Endpoint base URL (without /v1 or credentials).")
        if parsed.path.rstrip("/"):
            raise ValueError("EMBEDDING_BASE_URL must be the base URL, without /v1 or another path.")
        if parsed.scheme != "https" and not (
            parsed.scheme == "http" and parsed.hostname in {"127.0.0.1", "localhost", "::1"}
        ):
            raise ValueError("Use the Endpoint's managed HTTPS URL.")
        if not self.embedding_token:
            raise ValueError("Set EMBEDDING_API_KEY to your token-authenticated Endpoint's token.")
        if self.dimensions < 1:
            raise ValueError("EMBEDDING_DIMENSIONS must be positive.")
