[← Back to the cookbook](../README.md)

# Dual-model Endpoint reference

The [README](../README.md) contains the complete build, model-access, console/CLI/agent deployment, readiness and stop instructions. This page explains the runtime choices.

## One GPU, two application capabilities

The image exposes **two HTTP ports** on one Nebius Serverless AI Endpoint. All components select **GPU 0**. They share GPU memory; inference requests are serialized rather than sent to different GPUs.

| Port | Service | Expose through Nebius? |
| --- | --- | --- |
| `8000` | Embedding gateway: `POST /v1/embeddings` | Yes, HTTP with Endpoint token authentication |
| `8001` | Image gateway: `POST /v1/images/generations` | Yes, HTTP with the same Endpoint token authentication |
| `8002` | Private Qwen vLLM backend | No; loopback only |
| `8003` | Private FLUX backend | No; loopback only |

The generation capability includes **FLUX 3 Image Klein**, its text encoder/autoencoder, the official **9B prompt upsampler**, and a content classifier. It is therefore more than two bare model weight files. A separate embedding Qwen model serves retrieval. The supervisor starts the components, monitors them and ends the runtime if a required child exits.

[`endpoint/gateway.py`](../endpoint/gateway.py) uses a shared Linux file lock for embedding and generation. A gateway waits briefly for the GPU and returns HTTP 429 if it stays busy; it does not allow two independent full inference workloads to overlap. A timed-out model operation shuts down its gateway so the supervisor can stop the model processes instead of accepting another request while an unknown operation may still be running.

## Build and configuration

Build from the **cookbook root** and push the resulting `linux/amd64` image to your registry:

```bash
docker buildx build --platform linux/amd64 \
  -f endpoint/Dockerfile \
  -t YOUR_REGISTRY/photo-video-search-generate:flux3-v1 --push .
```

Do not add a token to the build. [`endpoint/versions.json`](../endpoint/versions.json) records source/model revisions. The Dockerfile isolates the original Qwen vLLM environment from the newer FLUX inference environment. The default entrypoint is the supervisor; leave **Entrypoint command** empty in Nebius.

| Setting | Initial value |
| --- | --- |
| Recommended GPU | One H200: `gpu-h200-sxm` / `1gpu-16vcpu-200gb` |
| Alternative GPU | One RTX PRO 6000 Blackwell, 96 GB: `gpu-rtx6000` or `gpu-rtx6000-a` / `1gpu-24vcpu-218gb`, if available in your project |
| VM pricing | Regular by default; explicit Spot alternative below |
| Ports | `8000/http`, `8001/http` |
| Container disk / shared memory | 500 GiB / 16 GiB |
| Endpoint authentication | Token required for both exposed APIs |
| `HF_TOKEN` | Secret environment variable with access to the gated repositories |
| `QWEN_GPU_MEMORY_UTILIZATION` | `0.25` |
| `PUP_GPU_MEMORY_UTILIZATION` | `0.30` |
| Model cache | `/var/cache/cookbook`; downloads occur at startup |
| FLUX request | Distilled model, 16 steps, one 1024×1024 image |

The two utilization values reserve separate vLLM budgets; they do not describe total runtime memory. FLUX's image pipeline and other allocations require additional memory. **The earlier RTX PRO 6000 run generated two images, with a sampled whole-GPU peak of 82,689 MiB. The current connection, search, prompt approval and Add/Discard journey passed a separate Regular H200 run.** These live runs injected the Endpoint sources and frozen dependencies into the public vLLM base; they do not establish GPU boot from the separately built custom image. See [validation](../VALIDATION.md) for measurements and limits. The newer FLUX stack needs **NVIDIA driver 580.65.06 or newer**, as required by [CUDA 13.0](https://docs.nvidia.com/cuda/archive/13.0.0/cuda-toolkit-release-notes/). The supervisor checks this before downloading weights; the Endpoint image cannot replace the VM's host driver. Do not infer compatibility from GPU memory capacity alone.

The image downloads only runtime artifacts selected by its downloader. It does not distribute the gated weights in the registry image. Ensure the `HF_TOKEN` secret has a payload entry named **`HF_TOKEN`**. CLI creation uses `--env-secret "HF_TOKEN=$HF_TOKEN_SECRET"`, where the value is a secret **selector**, not the token. The current console calls its service SecretStash; older help may say MysteryBox. See the [official Endpoint configuration](https://docs.nebius.com/serverless/endpoints/manage).

## Regular or Spot

Both choices serve the same two APIs and use the same demo connection form. **Regular is the default for an uninterrupted walkthrough. Spot is an experiment for interruptible sessions:** Nebius can reclaim its GPU during loading or inference. A stopped Spot Endpoint must be started deliberately, and the models must become ready again. Do not automatically repeat an image request after an uncertain response.

Before choosing Spot, check your project's current price and whether its selected GPU platform supports preemptible capacity. In the console, select **Preemptible**, then select or create a pricing policy for that project and platform. A policy caps the **price per GPU hour**; container-disk charges are separate. The market price changes and can exceed Regular prices. **Follow spot price has no price cap.** A cap does not guarantee available capacity. See [Spot pricing and policies](https://docs.nebius.com/signup-billing/pricing-policy).

The included helper preserves a separate creation step. With the common deployment variables from the README already set, choose one:

```bash
# Recommended first run: Regular H200.
export ENDPOINT_IMAGE="$IMAGE"
export ENDPOINT_NAME=media-search-generate
export GPU_PLATFORM=gpu-h200-sxm
export GPU_PRESET=1gpu-16vcpu-200gb
export PRICING_MODEL=regular
unset SPOT_PRICING_POLICY_ID SPOT_FOLLOWS_PRICE
bash scripts/endpoint-command.sh --dry-run
bash scripts/endpoint-command.sh
```

For capped Spot, use the ID of a pricing policy belonging to **your project and selected platform**:

```bash
export ENDPOINT_IMAGE="$IMAGE"
export ENDPOINT_NAME=media-search-generate-spot
export GPU_PLATFORM=gpu-h200-sxm
export GPU_PRESET=1gpu-16vcpu-200gb
export PRICING_MODEL=spot
export SPOT_PRICING_POLICY_ID=pricingpolicy-REPLACE_WITH_YOUR_ID
unset SPOT_FOLLOWS_PRICE
bash scripts/endpoint-command.sh --dry-run
bash scripts/endpoint-command.sh
```

Replace the placeholder before running. `--dry-run` validates without creating a resource; the second invocation **prints** the create command. Review and run that printed command once to provision. The helper uses a distinct default Spot name (`media-search-generate-spot`), emits `--preemptible --spot-pricing-policy-id`, and never falls back to Regular. Inspect matching Endpoint names before provisioning; after an ambiguous response, inspect the existing operation/resource instead of creating again.

If you deliberately accept uncapped prices, clear `SPOT_PRICING_POLICY_ID` and set `SPOT_FOLLOWS_PRICE=yes`; this emits `--preemptible --follows-spot-price`. Do not set both pricing choices. Regular emits `--on-demand`. These flags were checked against **CLI 0.12.299**; check `nebius ai endpoint create --help` after installing or updating the CLI.

**Observed Spot result, 3 November 2026:** the separate H200 Endpoint was reclaimed twice during startup, before inference could be tested, and ended **STOPPED**. Its quoted GPU-plus-500-GiB-disk rate at 10:00:58 UTC was about **$1.45/hour**, compared with **$5.45/hour** for Regular; the selected **$2/GPU-hour cap** excluded disk and tax. This is a dated price comparison, not a successful Spot inference run or a promise of future savings. The Regular H200 remained running throughout the test.

## API contract

Both API URLs use the managed HTTPS **base URL without `/v1`** in application configuration. Nebius authenticates the exposed requests; do not publish this container directly on an unprotected internet port.

Embedding uses the OpenAI-style `POST /v1/embeddings` contract with Qwen's multimodal chat body. The query and image must use the same model and formatting described in [REFERENCE.md](REFERENCE.md). The current gallery is image-only; the backend retains its earlier video embedding support for compatibility.

Generation accepts this JSON body:

```json
{
  "model": "black-forest-labs/flux-3-image-klein",
  "prompt": "A tiny astronaut tending a greenhouse on the moon",
  "n": 1,
  "size": "1024x1024",
  "response_format": "b64_json"
}
```

The service expands the description with the prompt upsampler, uses the official generation/content-check path and returns one base64-encoded image. This cookbook does not offer image editing, other image dimensions or video generation. The browser never calls this model API directly.

`GET /v1/models` and `GET /health` establish service readiness. They do not generate an image. The README's browser test must demonstrate a real generated result and its subsequent retrieval before the deployment is considered validated.

## Stop and restart

Use your recipe's actual Endpoint ID:

```bash
export ENDPOINT_ID=aiendpoint-REPLACE_WITH_YOUR_ID
export AI_AGENT="${AI_AGENT:-codex}"
nebius ai endpoint stop --id "$ENDPOINT_ID"
nebius ai endpoint get --id "$ENDPOINT_ID" --format jsonpath='{.status.state}'
```

Wait for `STOPPED`. Restart deliberately when needed:

```bash
nebius ai endpoint start --id "$ENDPOINT_ID"
python3 -m media_search check-endpoint --timeout 1800
python3 -m media_search check-generation --timeout 1800
```

A stop preserves the Endpoint configuration but releases its running VM and boot disk. Restarting can download the weights again. Gallery media, the local generation ledger and Qdrant persist outside that Endpoint. Stopped compute/boot-disk billing and separately retained storage are described in [Serverless billing](https://docs.nebius.com/serverless/pricing-quotas).

If Spot stops with `Preempted`, inspect the same Endpoint and its current pricing policy before deliberately starting it again. The managed URLs are retained, but startup downloads and model initialization repeat on the new VM; the earlier Regular H200 cold start took about 25 minutes. Wait for **both** model checks before reconnecting. Browser-saved photos remain on that device; reconnecting re-indexes them. An unsaved generated preview can be lost, so review the collection before approving another generation. See [Endpoint stop/restart behavior](https://docs.nebius.com/serverless/maintenance/stop-start).

[`LIVE-TEST.md`](../LIVE-TEST.md) describes the earlier **single-model H100 embedding test**. It is historical evidence only; it does not establish FLUX generation or one-GPU coexistence.
