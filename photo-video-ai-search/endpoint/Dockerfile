# syntax=docker/dockerfile:1.7
# Build from the cookbook root; weights and credentials are fetched only at run time.
FROM vllm/vllm-openai:v0.19.1
USER root
RUN apt-get update && apt-get install -y --no-install-recommends git ca-certificates \
    && rm -rf /var/lib/apt/lists/*
WORKDIR /opt/cookbook

# The official FLUX3 stack uses newer CUDA/PyTorch/vLLM than the proven embedder.
# A separate venv prevents its dependency versions from replacing vLLM 0.19.1.
# The final vLLM image installs Python 3.12 and uv system-wide.
RUN --mount=type=cache,target=/root/.cache/uv \
    mkdir -p /opt/cookbook/endpoint \
    && uv venv --python /usr/bin/python3 /opt/flux-venv \
    && git init /opt/flux3 \
    && git -C /opt/flux3 remote add origin https://github.com/black-forest-labs/flux-3-image-klein.git \
    && git -C /opt/flux3 fetch --depth 1 origin bfc8889a4497f846416f253a3972a1941ac698b9 \
    && git -C /opt/flux3 checkout --detach FETCH_HEAD \
    && uv pip install --python /opt/flux-venv/bin/python --prerelease=allow \
       --extra-index-url https://download.pytorch.org/whl/cu130 /opt/flux3 \
    && /opt/flux-venv/bin/python -c "import flux3.generate, fastapi, uvicorn; import torch; assert torch.__version__.split('+')[0] == '2.11.0'; assert torch.version.cuda == '13.0'" \
    && /usr/bin/python3 -c "import vllm, fastapi, httpx, uvicorn; assert vllm.__version__ == '0.19.1'" \
    && uv pip freeze --python /opt/flux-venv/bin/python > /opt/cookbook/endpoint/flux-resolved.txt

# Keep source changes after the expensive dependency layer.
COPY endpoint/ /opt/cookbook/endpoint/

ENV CUDA_VISIBLE_DEVICES=0 \
    HF_HOME=/var/cache/cookbook/huggingface \
    WEIGHTS_DIR=/var/cache/cookbook/weights \
    HF_HUB_DISABLE_TELEMETRY=1 \
    PYTHONUNBUFFERED=1 \
    QWEN_GPU_MEMORY_UTILIZATION=0.25 \
    PUP_GPU_MEMORY_UTILIZATION=0.30 \
    VLLM_WORKER_MULTIPROC_METHOD=spawn \
    GPU_LOCK_PATH=/run/cookbook/gpu.lock \
    GPU_TELEMETRY_PATH=/run/cookbook/gpu-telemetry.json
EXPOSE 8000 8001
HEALTHCHECK --interval=30s --timeout=5s --start-period=1800s --retries=3 \
    CMD ["/usr/bin/python3", "/opt/cookbook/endpoint/healthcheck.py"]
ENTRYPOINT ["/usr/bin/python3", "/opt/cookbook/endpoint/supervise.py"]
