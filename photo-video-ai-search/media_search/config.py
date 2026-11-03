from dataclasses import dataclass
import hashlib
import json
import math
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
    generation_url: str = ""
    generation_token: str = ""
    generation_model: str = "black-forest-labs/flux-3-image-klein"
    match_threshold: float = 0.25
    max_generations_per_day: int = 20
    search_requests_per_hour: int = 120
    generation_requests_per_hour_per_ip: int = 3
    public_demo: bool = False
    demo_username: str = "demo"
    demo_password: str = ""

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
            generation_url=os.getenv("GENERATION_BASE_URL", "").rstrip("/"),
            generation_token=os.getenv("GENERATION_API_KEY", ""),
            generation_model=os.getenv("GENERATION_MODEL", "black-forest-labs/flux-3-image-klein"),
            match_threshold=float(os.getenv("MATCH_THRESHOLD", "0.25")),
            max_generations_per_day=int(os.getenv("MAX_GENERATIONS_PER_DAY", "20")),
            search_requests_per_hour=int(os.getenv("SEARCH_REQUESTS_PER_HOUR", "120")),
            generation_requests_per_hour_per_ip=int(os.getenv("GENERATION_REQUESTS_PER_HOUR_PER_IP", "3")),
            public_demo=os.getenv("PUBLIC_DEMO", "false").lower() == "true",
            demo_username=os.getenv("DEMO_USERNAME", "demo"),
            demo_password=os.getenv("DEMO_PASSWORD", ""),
        )

    def validate_demo(self):
        if not math.isfinite(self.match_threshold) or not -1 <= self.match_threshold <= 1:
            raise ValueError("MATCH_THRESHOLD must be a finite cosine similarity between -1 and 1.")
        if min(self.max_generations_per_day, self.search_requests_per_hour,
               self.generation_requests_per_hour_per_ip) < 1:
            raise ValueError("Demo search and generation request budgets must be positive.")
        if self.generation_url:
            self.require_generation()

    def require_generation(self):
        self._require_url(self.generation_url, "GENERATION_BASE_URL")
        if not self.generation_token:
            raise ValueError("Set GENERATION_API_KEY to the token protecting your generation Endpoint.")

    @staticmethod
    def _require_url(url, name):
        parsed = urlsplit(url)
        if (not parsed.hostname or parsed.query or parsed.fragment or parsed.username is not None
            or parsed.password is not None or parsed.path.rstrip("/")):
            raise ValueError(f"{name} must be a base URL without /v1, credentials, query or fragment.")
        if parsed.scheme != "https" and not (
            parsed.scheme == "http" and parsed.hostname in {"127.0.0.1", "localhost", "::1"}
        ):
            raise ValueError(f"Use a managed HTTPS URL for {name}.")

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
