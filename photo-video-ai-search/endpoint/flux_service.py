"""Private FLUX3 service. Only the serialized gateway may call this loopback port."""
import base64
import io
import os
import secrets
import threading
import time
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Literal

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, ConfigDict, Field

MODEL = "black-forest-labs/flux-3-image-klein"
generation_lock = threading.Lock()
models = None


class ImageRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    model: Literal["black-forest-labs/flux-3-image-klein"] = MODEL
    prompt: str = Field(min_length=1, max_length=2000)
    n: Literal[1] = 1
    size: Literal["1024x1024"] = "1024x1024"
    response_format: Literal["b64_json"] = "b64_json"
    seed: int | None = Field(default=None, ge=0, le=4294967295)


@asynccontextmanager
async def lifespan(app):
    global models
    import torch
    from flux3.generate import Models
    from flux3.pipeline import WEIGHTS, dit_path
    # Respect the official upsampler + text encoder + autoencoder pipeline.
    # Default PUP engine batch capacity is lowered before its constructor.
    from flux3 import pup
    pup.ENGINE["max_num_seqs"] = 1
    pup.ENGINE["max_model_len"] = 8192
    pup.ENGINE["enforce_eager"] = True
    # This API supports text-to-image only. One image is still needed by the
    # official output moderation check; ten reference images need no budget.
    pup.MAX_REFERENCES = 1
    with torch.inference_mode():
        models = Models(
            {"distilled": str(dit_path("distilled"))},
            pup=str(WEIGHTS / "pup"),
            pup_memory=float(os.environ.get("PUP_GPU_MEMORY_UTILIZATION", "0.30")),
        )
    yield
    models = None


app = FastAPI(lifespan=lifespan, docs_url=None, redoc_url=None, openapi_url=None)


@app.get("/health")
def health():
    if models is None:
        raise HTTPException(503, "Generation models are starting.")
    return {"status": "ready", "model": MODEL, "prompt_upsampling": True}


@app.get("/v1/models")
def list_models():
    return {"object": "list", "data": [{"id": MODEL, "object": "model", "owned_by": "black-forest-labs"}]}


@app.post("/v1/images/generations")
def generate_image(body: ImageRequest):
    if models is None:
        raise HTTPException(503, "Generation models are starting.")
    if not generation_lock.acquire(blocking=False):
        raise HTTPException(429, "Generation is busy; retry shortly.")
    try:
        import torch
        from flux3.generate import Refused, generate
        from flux3.safety import exif
        with torch.inference_mode():
            image, record = generate(
                models, "distilled", body.prompt, images=[], width=1024, height=1024,
                steps=16, guidance=None, seed=body.seed if body.seed is not None else secrets.randbits(32),
                pup=True, safety=True,
            )
        if not record.get("upsampled"):
            raise RuntimeError("Prompt expansion did not complete.")
        output = io.BytesIO()
        image.save(output, format="PNG", exif=exif("distilled"))
        return {
            "created": int(time.time()), "model": MODEL,
            "data": [{"b64_json": base64.b64encode(output.getvalue()).decode("ascii"),
                      "revised_prompt": record["prompt"]}],
            "seed": record["seed"], "steps": 16,
        }
    except Refused:
        raise HTTPException(400, "This request or its output was declined by the model's content checks.") from None
    except Exception:
        raise HTTPException(503, "Image generation failed. Inspect sanitized runtime logs and GPU capacity.") from None
    finally:
        generation_lock.release()


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="127.0.0.1", port=8003, workers=1, access_log=False, log_level="warning")
