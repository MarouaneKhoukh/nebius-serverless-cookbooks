# One GPU, two model APIs

This container keeps the proven Qwen3-VL embedding server and the official FLUX 3
Image Klein implementation in separate Python environments. Both use CUDA device
`0`. Two gateways share a filesystem lock, so an embedding request and generation
cannot run at the same time. The generator also runs FLUX's dedicated 9B prompt
upsampler; the embedding model does not generate captions.

**The Linux amd64 image build and real shared-GPU acceptance checks succeed.**
On 2 November 2026, Qwen and FLUX ran together on one RTX PRO 6000 Blackwell:
three real-photo searches passed, two 1024×1024 images were generated and both
were found again through Qwen/Qdrant. The sampled session peak was **82,689 MiB**
(about **80.75 GiB**) with **15,198 MiB** free at the final observation. The
Endpoint was verified **STOPPED** after testing.

The cloud test booted the public vLLM base and injected these Endpoint sources,
then installed the frozen 204-package FLUX environment. The custom image itself
has passed build/import checks and was pushed successfully to a private registry
(digest `sha256:17f6d08f155237bd8bfbb871a09f5752986096de06c363bfb05e78767e010185`),
but **has not been pulled and booted on the GPU**. See
[the validation record](../VALIDATION.md) for the distinction, latency definitions
and current limits. This small acceptance pass is not a production-load benchmark.

## Build

From the cookbook directory:

```bash
docker build --platform linux/amd64 -f endpoint/Dockerfile \
  -t YOUR_REGISTRY/photo-video-search-generate:flux3-v1 .
docker push YOUR_REGISTRY/photo-video-search-generate:flux3-v1
```

For a source-only development rebuild after the full image already exists locally:

```bash
docker build --platform linux/amd64 -f endpoint/Dockerfile.incremental \
  --build-arg RUNTIME_BASE=nebius-media-search-flux3:local \
  -t nebius-media-search-flux3:metrics .
```

This optional shortcut reuses the already installed dependency stack. Use the
standard Dockerfile for a clean build from the registry base; its dependency
layer now precedes the source copy and caches package downloads with BuildKit.

The build downloads dependency packages and the pinned public reference source.
It does **not** download model weights, use a Hugging Face token or accept a
model's access terms. The official generator stack uses CUDA 13.0 wheels; the
host driver must be **580.65.06 or newer**; the supervisor checks this before
downloading weights. The generator gets its own CUDA library search path so the
embedding image's CUDA 12.9 libraries do not shadow its CUDA 13 wheels. The source pins are in `versions.json`;
the installed generation dependency snapshot is written inside the image to
`/opt/cookbook/endpoint/flux-resolved.txt`. Transitive dependencies are resolved
at build time, so this is not a fully hashed dependency lock.

In a Nebius Endpoint, use the image's default command and publish only
**8000/http** and **8001/http** with managed token authentication enabled. Keep
the image private if it contains any organization-specific additions.

## Runtime configuration

| Variable | Default / meaning |
| --- | --- |
| `HF_TOKEN` | Required runtime secret belonging to an account granted FLUX 3 access. Accept the applicable terms yourself first. Never bake the token into the image. |
| `WEIGHTS_DIR` | `/var/cache/cookbook/weights`; downloads approximately 52 GB for the generator stack. |
| `HF_HOME` | `/var/cache/cookbook/huggingface`; embedding model cache is additional. |
| `QWEN_GPU_MEMORY_UTILIZATION` | `0.25`; vLLM's allocation fraction of the whole visible GPU. |
| `PUP_GPU_MEMORY_UTILIZATION` | `0.30`; the official prompt upsampler's vLLM allocation fraction. |
| `GPU_LOCK_PATH` | `/run/cookbook/gpu.lock`; shared by both gateways. |
| `GPU_TELEMETRY_PATH` | `/run/cookbook/gpu-telemetry.json`; shared numeric metrics, with no prompts or credentials. |

Set at least a 200 GiB Endpoint boot disk (500 GiB leaves room for startup
downloads and caches) and 16 GiB shared memory. Stopping a Nebius Endpoint loses
its ephemeral disk; the next start must fetch weights again unless a separately
configured persistent cache is used.

The default budget is roughly 24 GB for the embedding server, 29 GB for the
upsampler, and the reference implementation's approximately 31 GB BF16 FLUX
peak. These are initial budget estimates, not per-process measurements. The live
acceptance checks measured the combined runtime on the target GPU; see the validation
record for the two generation timings, observed whole-GPU memory and remaining limits.
Qwen is restricted to one active sequence and eager execution. Generation is
one 1024×1024 image, 16 distilled steps, including real prompt expansion. The
official reference content checks remain enabled and PNG files retain AI
generation EXIF tags. Those checks are a demo baseline, not comprehensive abuse
prevention for anonymous public hosting.

## API contract

Both public ports offer `GET /health` and `GET /v1/models`. Startup exposes the
gateways only after both internal models report ready. Use both health URLs
before ingestion or a public showcase. Weight preparation and model startup
together have a 30-minute maximum wait; failure ends the container. Stop the
Endpoint in Nebius if it fails, because an application exiting is not a billing
shutdown.

- **8000:** `POST /v1/embeddings`, unchanged Qwen multimodal message contract.
- **8001:** `POST /v1/images/generations`:

```json
{
  "model": "black-forest-labs/flux-3-image-klein",
  "prompt": "a tiny cabin on a floating island at sunset",
  "n": 1,
  "size": "1024x1024",
  "response_format": "b64_json"
}
```

The response has `data[0].b64_json` (PNG), `data[0].revised_prompt` (the expanded
scene caption), `model`, `created`, `seed` and `steps`. Optional integer `seed`
allows reproducible requests within the same software/hardware configuration.
Other sizes, batch counts, model names and unknown fields are rejected.

Never publish internal ports **8002** (Qwen) or **8003** (FLUX). They bind to
loopback and bypass the shared request gateways. The container itself delegates
external authentication to the Nebius managed gateway; if run elsewhere, add an
authenticated reverse proxy. Model credentials stay on the server.

Requests have a 12 MiB body limit. Each public gateway accepts at most two
in-flight requests, waits at most 10 seconds for the shared GPU, then returns
429 when busy. Upstream inference timeouts are 300 seconds for embeddings and
600 seconds for generation. A timed-out GPU operation marks the runtime
unhealthy and ends all model processes rather than risk overlapping work.
The container must be restarted by its host if a child fails. Nebius control
plane running state alone is not proof that both models are ready.

## Measure the shared GPU

`GET /v1/runtime/gpu` on either managed, authenticated public port returns the
same numeric report. It contains current `nvidia-smi` memory used, total/free
memory and reported GPU utilization, plus sample age and a `stale` flag. It does
not return process command lines, GPU UUIDs or credentials.

The supervisor samples approximately every second during startup and idle.
Each inference gateway marks its operation's start/end and takes additional
boundary samples while holding the shared GPU lock. The report separates
`phase_peaks` (`embedding_startup`, `generation_startup`, `idle`, `embedding`,
`generation`), an aggregate `startup` peak, and records the last operation per role with duration and sample
count. `overall` retains the maximum sampled memory since this container start.
Operation duration spans the locked gateway window, including the two boundary
queries; it is not pure model latency. Startup also logs numeric phase snapshots.
The supervisor prints a final `[gpu-final]` summary before its final process
cleanup, including startup failures when the public gateways never opened.

These are **whole-GPU sampled peaks**, not CUDA allocator high-water marks or
per-model allocations. Short spikes can be missed, and `nvidia-smi` utilization
is the utilization window reported by the driver. Unavailable readings have an
explicit sanitized error and retain the last good sample with its age. Measure
representative image-search and image-generation requests before using the
remaining memory as evidence for adding another model. The current demo is image-only.

## Sources

- [FLUX 3 model card](https://huggingface.co/black-forest-labs/flux-3-image-klein): checkpoints, memory estimates and mandatory prompt expansion.
- [Pinned official reference implementation](https://github.com/black-forest-labs/flux-3-image-klein/tree/bfc8889a4497f846416f253a3972a1941ac698b9): `Models` / `generate`, safety checks and pinned generator dependencies.
- [Official vLLM-Omni recipe](https://recipes.vllm.ai/black-forest-labs/flux-3-image-klein): alternative serving stack; its published validation is on GB200, not this combined RTX deployment. We use the reference stack here to keep its integrated prompt expansion and checks.
- [Qwen3-VL Embedding](https://huggingface.co/Qwen/Qwen3-VL-Embedding-8B).
- [NVIDIA CUDA 13.0 driver compatibility](https://docs.nvidia.com/cuda/archive/13.0.0/cuda-toolkit-release-notes/).
- [FLUX Kommunity License](https://huggingface.co/black-forest-labs/flux-3-image-klein/blob/337337621b8526e120f2275d250242f4a6bedd75/LICENSE.md). Public hosting still requires that the operator's use meets its terms; downloading this container does not grant that qualification.
