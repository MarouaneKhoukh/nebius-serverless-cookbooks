"""Fetch only pinned packages needed by the official BF16 distilled pipeline.

No gate is accepted here. HF_TOKEN must already have access granted by its owner.
Never print exception bodies, URLs with credentials, or the token.
"""
import json
import os
import sys
from pathlib import Path


def main():
    from huggingface_hub import snapshot_download

    if not os.environ.get("HF_TOKEN"):
        raise RuntimeError("HF_TOKEN is required; accept model access terms before starting.")
    versions = json.loads(Path(__file__).with_name("versions.json").read_text())
    root = Path(os.environ["WEIGHTS_DIR"])
    packages = [
        ("generation", "flux-3-image-klein", [
            "model.safetensors", "config.json", "manifest.json", "ae.safetensors",
            "text_encoder/*", "README.md", "LICENSE.md", "NOTICE.md",
        ]),
        ("upsampler", "pup", None),
        ("classifier", "nsfw-classifier", None),
    ]
    for name, folder, patterns in packages:
        print(f"Preparing pinned {name} weights.", flush=True)
        snapshot_download(
            repo_id=versions[f"{name}_model"], revision=versions[f"{name}_revision"],
            local_dir=root / folder, allow_patterns=patterns,
            token=os.environ["HF_TOKEN"], max_workers=4,
        )
    print("Generation weights are available.", flush=True)


if __name__ == "__main__":
    try:
        main()
    except Exception:
        print("Weight preparation failed. Check HF_TOKEN access, model terms, network and disk space.", file=sys.stderr)
        sys.exit(1)
