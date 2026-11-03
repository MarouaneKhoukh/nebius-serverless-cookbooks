# Search Your Photos and Create New Images

Build a gallery that finds existing photos with **Qwen3-VL** and creates new images with **FLUX 3 Image Klein**. Both models are core parts of this cookbook: review each creation prompt, generate a preview, then decide whether to keep it.

**Powered by Nebius Serverless AI**

**The build:** Qwen3-VL Embedding and FLUX run in a Nebius Serverless AI GPU Endpoint. The interactive demo runs on a normal web host: each visitor connects their own Endpoint and keeps their collection in that browser. The optional Python implementation uses **Qdrant** for a persistent server-side collection.

> The shared-model runtime passed RTX PRO 6000 Blackwell and H200 tests. The current browser-connected search, approval, Add, Discard and reconnect flow also passed a live H200 run. These runs used the Endpoint sources and frozen dependencies bootstrapped into the public vLLM base; the separately published custom image still needs its own GPU boot test. See the [validation record](VALIDATION.md) for the separate checks and remaining limits.

**Regular or Spot:** use Regular for the first interactive run. A capped Spot option is included in step 5. Our 3 November H200 Spot trial was preempted twice before both models were ready, so successful inference on Spot is **not yet validated**.

## Try it with your Endpoint

**Hosted demo URL: publication pending.** To try the same app on your computer now, use the short local launch below.

1. Open the demo and search **coffee**. If you have not connected an Endpoint, the app asks you to connect first and keeps your search ready.
2. Connect the search stage with your Endpoint's **port-8000 public HTTPS URL** and **Endpoint authentication token**. Complete the image-creation connection with its **port-8001 URL** when you first choose **Create an image**. Both URLs are required for the complete demo. Use base URLs without `/v1`; copy them from **Serverless AI → Endpoints → your Endpoint → Overview → Public endpoints**.
3. Choose **Connect and index photos**. The app checks the models, embeds the three starter photos, then runs your search. **Coffee beans** should appear as a relevant result. Try **espresso** for a visual match, then **football**: with the starter collection, that should show **No matching photos**, without unrelated suggestions.

**Where is the token?** Use the Endpoint token saved during creation. For an existing token-protected Endpoint, open its **Overview → View code** and copy only the value after **`--token`** in the displayed CLI example, without surrounding quotes. Paste it directly into the app's token field. **Do not run that example's Endpoint creation command.** This is the inference Endpoint's token, not a Nebius account API key or Hugging Face token; do not share the code example or token in screenshots.

To create an image, enter a description and choose **Create an image** near Search. An empty search result also asks whether you want to create one: choose **Yes, create an image**. If creation is not connected yet, complete setup with your **port-8001 public HTTPS URL**; the app reuses your existing Endpoint token unless you provide a different one. Review or edit the prompt, then choose **Approve and generate**. Inspect the unsaved preview and choose **Add to collection** or **Discard**. **No, keep searching** lets you continue searching. Connecting never generates an image or adds one to your collection.

Your token stays in the page's memory and is sent through the demo's proxy to the Endpoint you selected. The hosted app uses HTTPS; the local preview uses HTTP only on your computer's loopback address and HTTPS from its proxy to Nebius. The token is not saved with your photos. Saved photos and metadata stay in this browser's IndexedDB, with a maximum of **20 images**; vectors stay in page memory. Collections do not sync across devices. Reconnect after reloading the page: each connection re-embeds the collection with that Endpoint before search becomes ready. **Disconnect** clears the connection without stopping your paid GPU.

### Run the interactive demo locally

If you already have a compatible Endpoint, download this repository with **Code → Download ZIP**, extract it, open its **`photo-video-ai-search`** directory, and install [Node.js 22 or newer](https://nodejs.org/) if needed. Then run:

```bash
cd hosted-demo
node server.mjs
```

Open **[http://127.0.0.1:8085](http://127.0.0.1:8085)** on that computer and follow the three steps above. Python and Docker are not required for this app when your Endpoint already exists. The address belongs to your computer; share a deployed HTTPS URL with other people.

Keep this terminal running. If the page stops responding, run `node server.mjs` again from `hosted-demo/`; restarting the local web app does not restart your GPU. After a page reload, reconnect your Endpoint to re-index the saved photos.

Need an Endpoint first? Follow the complete build below. It includes console, CLI and Nebius-agent creation routes.

## What it looks like

Current **Search + Create** interface: [both features connected](docs/media/search-create-core.png). Creation is a primary action; both model connections are required to complete setup.

![Live connected search, prompt approval, generated-image saving and retrieval](docs/media/byo-endpoint-live.gif)

[Watch the live walkthrough](docs/media/byo-endpoint-live.mp4) · [Coffee search screenshot](docs/media/byo-endpoint-live.jpg) · [Connection-only preview](docs/media/connect-endpoint-preview.mp4)

Current creation flow: [choose whether to create](docs/media/create-choice-final.png) → [connect FLUX if needed](docs/media/connect-flux-after-choice.png) → [review the prompt](docs/media/review-after-connection.png). Search check: [espresso → coffee-related photos](docs/media/search-espresso-match.png).

*Actual browser captures from the Node app connected to a real H200 Endpoint show coffee matching coffee beans, reviewed prompt approval, a saved robot barista and its later retrieval. A separate violet-pineapple preview shows the Add/Discard choice; it was discarded. The walkthrough predates the simpler create-first connection step shown in the screenshots above. Screenshot holds shorten waiting periods and do not represent generation latency. Credential entry is omitted; public URLs shown belong to the test Endpoint—use your own. This local run does not establish public hosting. [Capture details](docs/media/CAPTURE.md).*

The three starter photos are by [Negative Space](https://www.pexels.com/photo/beans-coffee-cup-mug-34079/), [eberhard grossgasteiger](https://www.pexels.com/photo/landscape-photo-of-snowy-mountains-near-lake-1292677/) and [Robert Stokoe](https://www.pexels.com/photo/city-buildings-at-night-9097693/) on Pexels. [License and supplied files](examples/SOURCES.md).

<details>
<summary><strong>Earlier Python app: live prompt approval and image saving</strong></summary>

[Watch the earlier H200 walkthrough](docs/media/search-create-live.mp4) · [Animated preview](docs/media/search-create-live.gif) · [Screenshot](docs/media/search-create-live.jpg)

This historical capture shows the Python/Qdrant app reviewing a prompt, creating an unsaved preview, explicitly saving it and retrieving it later. It used real Qwen and FLUX inference; screenshot holds shorten waiting periods and are not generation timings. It does **not** demonstrate the new browser-connected app or a published deployment. See [validation](VALIDATION.md) for the separate checks actually performed.

</details>

## Before you start

- This build path uses **macOS**, Node.js, Python 3.12 and Docker Desktop. Your computer does not need a GPU. Linux works with the same tools already installed. Docker builds the GPU image; Python supports the CLI token setup and optional Qdrant implementation.
- You need a **Nebius project with billing, editor access, a subnet, and available quota/capacity for one H200**. RTX PRO 6000 Blackwell is a tested smaller alternative where available in your project. The managed GPU host needs **NVIDIA driver 580.65.06 or newer** for the pinned CUDA 13 FLUX stack. Confirm that support before paying for a test; a GPU name alone does not guarantee compatibility.
- You need a **Hugging Face account** with access to the gated FLUX model and its prompt upsampler, and a read token. You also need a container registry account to publish the custom image. This recipe uses GitHub Container Registry (GHCR).
- Review the [FLUX Kommunity License](https://huggingface.co/black-forest-labs/flux-3-image-klein/blob/main/LICENSE.md) for the operator of your demo. Public hosting uses its qualifying-user/commercial terms; being a free demo alone does not establish permission. Model access and license acceptance are human steps.
- The GPU is billable while starting or running. Review your project's price before creation, set a test window, and stop the Endpoint in step 9. No automatic idle shutdown is assumed.

## 1. Install the tools

Skip tools you already have. If needed, install [Homebrew](https://brew.sh):

```bash
/bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"
```

Follow its **Next steps** to add Homebrew to your shell. Then:

```bash
brew install node python@3.12
brew install --cask docker-desktop
open -a Docker
```

Finish Docker Desktop setup and wait until it is running. Check the tools:

```bash
python3.12 --version
node --version
docker info
docker compose version
docker buildx version
```

The GPU image contains separate inference environments and a large CUDA stack. **Plan for roughly 100 GB of free Docker build space** for image layers and caches. This is a planning estimate, not a validated minimum; the Endpoint's separate runtime disk is configured in step 5.

## 2. Download the cookbook

On [this repository's Code page](https://github.com/MarouaneKhoukh/nebius-serverless-cookbooks), choose **Code → Download ZIP** and save it in Downloads. Extract it, then prepare Python for the deployment commands and optional Qdrant version:

```bash
unzip ~/Downloads/nebius-serverless-cookbooks-main.zip -d ~/Downloads
cd ~/Downloads/nebius-serverless-cookbooks-main/photo-video-ai-search
python3.12 -m venv .venv
source .venv/bin/activate
python3 -m pip install -r requirements.txt
cp .env.example .env
chmod 600 .env
```

If the ZIP is saved elsewhere, change its path. Run the remaining commands from this cookbook directory. The repository contains the web app, GPU runtime, examples and deployment instructions.

## 3. Prepare model access

1. Sign in to Hugging Face and open [FLUX 3 Image Klein](https://huggingface.co/black-forest-labs/flux-3-image-klein) and [its prompt upsampler](https://huggingface.co/black-forest-labs/flux-3-image-klein-pup). Review and accept each repository's access conditions as the appropriate individual or organization. Wait for access if approval is required.
2. In [Hugging Face access tokens](https://huggingface.co/settings/tokens), create a **read** token with access to those repositories. Keep it private; it is different from your Nebius Endpoint token.
3. In [console.nebius.com](https://console.nebius.com), select your intended project. Check **Administration → IAM** for `editor` access and **Administration → Limits → Quotas** for one H200 and the necessary network allocation. For Spot, check preemptible capacity/quota too.
4. Select an existing subnet in that project under **Networking → Virtual Networks → Subnets**. Save its ID and your project ID for the CLI alternative below. If the GPU is unavailable, stop and choose an available supported GPU deliberately; do not create resources in a different project by accident.

You will inject `HF_TOKEN` as a **secret environment variable** when creating the Endpoint. Do not put it in the Dockerfile, build arguments, source code, an image, or ordinary Endpoint environment variables.

## 4. Build and publish the GPU image

The supplied [`endpoint/Dockerfile`](endpoint/Dockerfile) starts the embedding API on **8000** and the image-generation API on **8001**. It downloads model weights at startup, using the secret from step 3. The image itself contains no private token or model weights.

For GHCR, open GitHub **Settings → Developer settings → Personal access tokens → Tokens (classic) → Generate new token (classic)**. Give the token **`write:packages`** permission; authorize organization SSO if your registry requires it. GitHub documents these permissions in its [registry instructions](https://docs.github.com/en/packages/working-with-a-github-packages-registry/working-with-the-container-registry#authenticating-to-the-container-registry). Replace the username below with your **lowercase** GitHub username:

```bash
docker login ghcr.io -u YOUR_GITHUB_USERNAME
export IMAGE=ghcr.io/YOUR_LOWERCASE_USERNAME/photo-video-search-generate:flux3-v1
docker buildx build --platform linux/amd64 \
  -f endpoint/Dockerfile -t "$IMAGE" --push .
```

Paste the GitHub token only at Docker's password prompt. A successful build and push must finish before continuing. On an Apple Silicon Mac, `--platform linux/amd64` builds the architecture used by this Endpoint.

For the simplest pull, open your GitHub profile's **Packages**, select this image, and change its visibility to **Public** in package settings. This publishes the runtime code, not your media or gated weights. Save the full image name.

If you keep the image private, instead configure **Private registry** in the Endpoint form with `ghcr.io`, your registry username, and a token allowed to read this package. For CLI creation, store those credentials in a registry secret and use `--registry-secret`; do not put a registry password in a command or plain environment variable.

## 5. Create one dual-model Endpoint

Choose **one** route below. Do not run both creation routes.

Choose your running mode before creating it:

- **Regular — recommended for this interactive demo.** Steadier availability; billed while the Endpoint is starting or running.
- **Spot — lower running price, possible interruptions.** Choose a maximum-price policy for your project and GPU platform. Nebius can reclaim the GPU during startup or inference; an Endpoint does not automatically restart. A restart needs model downloads/loading again.

The 3 November 2026 H200 quote was **about $1.45/hour on Spot versus $5.45/hour Regular**, including a 500 GiB disk, before tax. That is a dated estimate, not a guaranteed price or a successful Spot serving result. Check the current quote in your console. [Spot pricing](https://docs.nebius.com/signup-billing/pricing-policy) · [Our actual test](docs/evidence/spot-endpoint-2026-11-03.json).

### Console route

In **Serverless AI → Endpoints → Create endpoint**, choose **Custom**:

| Setting | Value |
| --- | --- |
| Name | `media-search-generate`, or `media-search-generate-spot` for a separate Spot test |
| Image path | Your full image name from step 4 |
| Entrypoint command | Leave empty; use the image's default supervisor |
| Ports | **8000 / HTTP** and **8001 / HTTP** |
| Authentication | **Token**, enabled; securely save the generated token |
| Computing resources | GPU, **Regular**, **H200**, **1 GPU / 16 vCPUs / 200 GiB** |
| Container disk / shared memory | **500 GiB / 16 GiB** |
| Network | The subnet selected in step 3; managed HTTPS access |

Under **Secret environment variables**, add **`HF_TOKEN`** using the token from step 3. Use **Create secret** if it is not already stored. The console may label the secret service **SecretStash**; some CLI/skill references use **MysteryBox**. The secret must contain a payload entry named **`HF_TOKEN`**. This must be a secret reference, not a plain environment value.

For **Spot**, change capacity to **Preemptible** and select an existing H200 pricing policy or create one with your chosen maximum USD price per GPU-hour. Review the current Spot quote first; a cap below the current price blocks startup. The cap excludes disk and tax. Keep the other settings the same. Do not select an uncapped price unless you intend to accept price increases. See the CLI option below for the same capped setup.

The image checks for **NVIDIA driver 580.65.06+** before downloading weights. You cannot replace the managed host driver from inside this image; verify compatibility before creation. Leave the runtime's default memory budgets and image-generation settings unchanged for the first test. It uses one GPU, serializes inference, and starts a separate prompt upsampler required by FLUX. Both H200 and the 96 GB RTX PRO 6000 Blackwell passed bounded Regular shared-GPU runs; the custom-image packaging route still needs its separate boot check. See [validation](VALIDATION.md).

Review the displayed price and your test window, then click **Create endpoint** once. Creation starts the Endpoint. Wait for **Running**, then open **Overview → Public endpoints** and copy its two managed HTTPS URLs, matching **8000** to embeddings and **8001** to generation. Do not expose internal ports 8002 or 8003. Keep the token saved during creation. If you need to find it again, **Overview → View code** shows a CLI example: copy only the value after `--token`, without quotes, and **do not run the displayed creation command**.

<details>
<summary><strong>CLI alternative: same Endpoint, without console creation</strong></summary>

Install the [Nebius CLI](https://docs.nebius.com/cli/install) if needed:

```bash
curl -sSL https://artifacts.nebius.cloud/cli/install.sh | bash
```

Restart Terminal, return to the extracted cookbook, activate `.venv`, and sign in:

```bash
cd ~/Downloads/nebius-serverless-cookbooks-main/photo-video-ai-search
source .venv/bin/activate
export AI_AGENT="${AI_AGENT:-codex}"
nebius version
nebius profile create
```

Use CLI **0.12.299 or newer**; that version was used to verify these pricing flags. If older, run `nebius update` before continuing. In profile setup, choose the intended tenant/project and your account's sign-in method. Reuse a compatible existing profile if you already have one.

Set your real project and subnet IDs, then discover the platforms/presets available to that project:

```bash
export PROJECT_ID=project-REPLACE_WITH_YOUR_ID
export SUBNET_ID=vpcsubnet-REPLACE_WITH_YOUR_ID
nebius compute platform list --parent-id "$PROJECT_ID" --format json
```

Choose **`gpu-h200-sxm`** with **`1gpu-16vcpu-200gb`** if your project lists it. For Spot, the platform must also report `allowed_for_preemptibles: true`. RTX PRO 6000 Blackwell is an alternative: the [documented identifiers](https://docs.nebius.com/compute/virtual-machines/types) include `gpu-rtx6000` or `gpu-rtx6000-a` with `1gpu-24vcpu-218gb`; use the pair returned for your project. A platform listing is not a capacity guarantee.

In the console, create/select the secret with a payload entry named `HF_TOKEN` and save its secret selector; the CLI references the secret, never its value. For a private image, create a registry secret containing `REGISTRY_USERNAME` and `REGISTRY_PASSWORD` and save its selector.

Set the remaining values to your selected identifiers and image:

```bash
export GPU_PLATFORM=gpu-h200-sxm
export GPU_PRESET=1gpu-16vcpu-200gb
export HF_TOKEN_SECRET=REPLACE_WITH_HF_TOKEN_SECRET_SELECTOR
export IMAGE=ghcr.io/YOUR_LOWERCASE_USERNAME/photo-video-search-generate:flux3-v1
export ENDPOINT_NAME=media-search-generate
PRICING_ARGS=(--on-demand)
```

**For Spot instead of Regular**, first list your existing policies:

```bash
nebius billing pricing-policy list --parent-id "$PROJECT_ID" --format json
```

Reuse a policy for the same project and `$GPU_PLATFORM`. If none is suitable, create one **once**, choosing the cap after checking the current quote. `2.000` below is an example per-GPU-hour USD cap, not a universal recommendation:

```bash
nebius billing pricing-policy create \
  --parent-id "$PROJECT_ID" --name media-search-gpu-cap \
  --compute-instance-spec-v1-platform "$GPU_PLATFORM" \
  --pricing-max-price-v1-max-price 2.000 \
  --format json
```

Copy the returned policy's `metadata.id`, then replace this placeholder:

```bash
export SPOT_PRICING_POLICY_ID=pricingpolicy-REPLACE_WITH_YOUR_ID
export ENDPOINT_NAME=media-search-generate-spot
PRICING_ARGS=(--preemptible --spot-pricing-policy-id "$SPOT_PRICING_POLICY_ID")
```

A policy below the market price cannot start. A price increase above the cap stops the Endpoint; capacity can be reclaimed even below the cap. If Regular is selected, keep `PRICING_ARGS=(--on-demand)` and skip policy creation.

Before creating anything, check for an Endpoint with the selected name:

```bash
nebius ai endpoint get-by-name --parent-id "$PROJECT_ID" --name "$ENDPOINT_NAME" \
  --format jsonpath='{.metadata.id}{"\n"}{.status.state}{"\n"}{.status.public_endpoints}{"\n"}'
```

If a compatible Endpoint already exists, reuse its URLs and saved token and skip token generation/creation below. Proceed only when the name is absent; resolve authentication or access errors before creating.

For a new Endpoint, generate its token and save it for both APIs without printing it:

```bash
export MEDIA_ENDPOINT_TOKEN="$(python3 -c 'import secrets; print(secrets.token_urlsafe(32))')"
python3 - <<'PYTOKEN'
import os
from dotenv import set_key
for key in ('EMBEDDING_API_KEY', 'GENERATION_API_KEY'):
    set_key('.env', key, os.environ['MEDIA_ENDPOINT_TOKEN'])
os.chmod('.env', 0o600)
PYTOKEN
```

Create once. If using a private image, add `--registry-secret YOUR_REGISTRY_SECRET_SELECTOR` to this command:

```bash
nebius ai endpoint create \
  --parent-id "$PROJECT_ID" \
  --name "$ENDPOINT_NAME" \
  --image "$IMAGE" \
  --platform "$GPU_PLATFORM" \
  --preset "$GPU_PRESET" \
  --subnet-id "$SUBNET_ID" \
  --container-port 8000/http \
  --container-port 8001/http \
  --disk-size 500Gi \
  --shm-size 16Gi \
  --env-secret "HF_TOKEN=$HF_TOKEN_SECRET" \
  --auth token --token "$MEDIA_ENDPOINT_TOKEN" \
  "${PRICING_ARGS[@]}" \
  --async
unset MEDIA_ENDPOINT_TOKEN
```

The asynchronous create prints an **operation ID**, not the Endpoint resource ID. The image supplies its own entrypoint; do not replace it with the old single-model vLLM command. Use this lookup for the actual Endpoint ID, state and URLs without displaying credentials:

```bash
nebius ai endpoint get-by-name \
  --parent-id "$PROJECT_ID" --name "$ENDPOINT_NAME" \
  --format jsonpath='{.metadata.id}{"\n"}{.status.state}{"\n"}{.status.public_endpoints}{"\n"}'
```

Save the Endpoint ID for cleanup. If provisioning is incomplete, repeat this **read** command; do not repeat creation. Match the managed URLs to ports 8000 and 8001 in the console's Endpoint details, then continue at step 6. Tokens are already in `.env`.

The optional `scripts/endpoint-command.sh` helper prints the same kind of command for review. Set `ENDPOINT_IMAGE="$IMAGE"` and `PRICING_MODEL=regular`, or `PRICING_MODEL=spot` with `SPOT_PRICING_POLICY_ID`; its `--dry-run` validates configuration without creating an Endpoint.

</details>

<details>
<summary><strong>Agent alternative: Nebius skills or operational MCP</strong></summary>

First complete CLI installation/sign-in above, model access, and image publication. Then open this cookbook directory in an agent with terminal access.

For the [official Nebius skills](https://github.com/nebius/skills):

```bash
brew install node
npx skills add nebius/skills
```

Select your agent and `nebius-cloud-basics`, `nebius-serverless-endpoints`, and `nebius-serverless-data-secrets`. Restart the agent if necessary.

Or connect the [official operational Nebius MCP](https://github.com/nebius/mcp-server), which requires its own Python 3.13+ runtime:

```bash
brew install uv
uv python install 3.13
```

For a client accepting `mcpServers` configuration:

```json
{
  "mcpServers": {
    "nebius": {
      "command": "uvx",
      "args": ["--python", "3.13", "--refresh-package", "nebius-mcp-server", "nebius-mcp-server@git+https://github.com/nebius/mcp-server@main"],
      "env": {"SAFE_MODE": "true"}
    }
  }
}
```

If the client cannot find `uvx`, use the full path from `command -v uvx`; its environment must also find `nebius`. Reconnect and check for `nebius_profiles`, `nebius_cli_help`, and `nebius_cli_execute`. Keep safe mode enabled. The documentation-only `docs.nebius.com/mcp` cannot deploy resources.

Use this prompt:

```text
Run this cookbook's Qwen + FLUX 3 Image Klein extension. Use the installed
Nebius cloud-basics, endpoints and data-secrets skills or operational MCP.
Read README.md. Confirm my project, published image, HF_TOKEN secret selector,
H200 (or the supported RTX alternative) one-GPU platform/preset and driver
compatibility. Stay entirely in my selected project; do not create a new one.
Reuse a compatible recipe Endpoint if one exists; do not alter unrelated ones.

Use the custom image's default entrypoint, ports 8000/http and 8001/http,
token auth, 500 GiB disk and 16 GiB shared memory. Ask which running mode I
want before provisioning: Regular, or Spot with an agreed price cap. For Spot,
verify current pricing/capacity, use a same-project/platform pricing policy,
and report that preemption can stop startup or inference with no auto-restart.
Do not replace or stop a working Regular Endpoint to test Spot. Never expose
internal ports 8002/8003. Do not accept a model license on my behalf.

Show the exact deployment and current cost before paid execution, and ask
for a bounded test authorization unless I already gave it. Keep credentials
out of chat and MCP output: use secret selectors and safe field projections.
Use a local terminal for private token capture, or hand those commands to me.

Follow steps 6–7 using the browser-connected demo. Confirm that searching coffee
finds the supplied coffee-beans photo without a misleading no-match message.
For generation, choose Create image, review/edit the proposed prompt, then
explicitly Approve and generate. Confirm the finished private preview does not
change the collection count. Choose Add to collection, verify the AI-generated
label and subsequent retrieval, and check Discard on a separate unsaved preview
only if a second generation is within my approved test scope. Report actual
results, failures, memory use, Endpoint ID/URLs/state and the stop action.
Stop at my approved deadline; never leave paid compute running silently.
```

An MCP-only agent can prepare deployment and monitor safe state fields; do private credential capture in your terminal using the CLI alternative. Do not retrieve auth tokens or secret payloads through MCP.

</details>

## 6. Launch, connect and try the app

From the cookbook directory:

```bash
cd hosted-demo
node server.mjs
```

Open **[http://127.0.0.1:8085](http://127.0.0.1:8085)**. The app starts disconnected; it does not use a cookbook author's credentials.

Keep that terminal open. If the local address is unreachable, restart `node server.mjs` from `hosted-demo/`. This restores the web app; it does not create or restart cloud resources.

1. Search **coffee**. The connection form opens and retains that query.
2. Connect the search stage with the **port-8000 managed HTTPS base URL** and **Endpoint token** from step 5. Keep the **port-8001 URL** ready for the creation step below. The complete demo requires both Qwen and FLUX. Do not enter a project ID, console page URL, account API key or `HF_TOKEN`.
3. Choose **Connect and index photos**. Wait while the app checks authentication, the expected model IDs and the 4096-dimensional embedding response, then indexes **coffee beans, a mountain lake and a city at night**. A Running Endpoint may still be loading models. If connection fails, fix the displayed error and retry this connection; do not create another Endpoint.
4. Confirm that **coffee beans** appears for **coffee** and **espresso**. Try **a lake in the mountains** or **a city after dark**, then **football**. The starter collection contains no football photo, so that search should show **No matching photos**. Results combine visual embeddings with useful title matches; low-scoring neighbors are excluded. Similarity is a ranking signal, not a confidence percentage.
5. Enter a description and choose **Create an image** near Search, or choose **Yes, create an image** after a no-match result. Complete the creation connection with the **port-8001 managed HTTPS base URL** from step 5. The form uses your current Endpoint token; add a separate token only if the generation API needs a different one. Choose **Connect and review prompt**. Your search and indexed photos stay ready. Review/edit the proposed prompt, then choose **Approve and generate**. Searching, choosing yes, connecting and editing never start generation by themselves. Both features should now be connected.
6. Inspect the **AI-generated preview**. The collection count must stay unchanged. Choose **Add to collection** to embed it, save it in this browser and make it searchable. Or choose **Discard** to remove the preview without adding it.
7. Search for an image you added. Reload the page and reconnect: saved images remain on this browser, but credentials are requested again and the collection is re-embedded before searching.

The three starter photos and their [sources](examples/SOURCES.md) are bundled. Saved images and their metadata live in IndexedDB on this device, with a **20-image limit**. Embedding vectors live in page memory and are recomputed on connection. This collection is separate from the optional Python/Qdrant collection below. The unsaved generation preview lives only in the open page; save or discard it before closing or reloading. Clearing browser site data removes this browser collection.

Queries and images are sent through the app's server proxy to the Endpoint you connect. Tokens live only in page memory and are supplied with these requests, never saved in IndexedDB or shipped with the source. Generated pixels are embedded only when you choose **Add to collection**. Disconnecting the app does not stop or delete your Endpoint.

### If your Spot GPU is reclaimed

The gallery can still show locally saved photos, but search and creation need the GPU. In the console, check the Endpoint's state and reason. For **Stopped / Preempted**, restart that **same** Endpoint once when you are ready to pay for another attempt, then wait for both model APIs before reconnecting. Or use the CLI with its saved resource ID:

```bash
export ENDPOINT_ID=aiendpoint-REPLACE_WITH_YOUR_ID
nebius ai endpoint get --id "$ENDPOINT_ID" \
  --format jsonpath='{.status.state}{"\n"}{.status.state_details.code}{"\n"}'
# Only after confirming STOPPED / Preempted and reviewing the current price:
nebius ai endpoint start --id "$ENDPOINT_ID" --async
```

Restarting repeats the cold start; do not assume model weights or an unfinished image survive. Saved browser photos remain on this device, but an unsaved preview does not survive a page reload. If a generation request was interrupted, review its outcome and explicitly approve a new attempt rather than silently repeating it. Repeated preemption means the current capacity is unsuitable for a dependable live demo; use Regular rather than looping restarts. [Endpoint lifecycle](https://docs.nebius.com/serverless/endpoints/manage).

## 7. Publish the connected demo

Publish **`hosted-demo/`**, including its server proxy, to share an HTTPS app that visitors connect to their own Nebius Endpoints. A static file host alone is insufficient: the proxy handles authenticated Endpoint calls without depending on Endpoint browser CORS settings. Your GPU token does not belong in the deployment's environment or frontend source.

This project supports publication through the **Sites plugin in a compatible agent**. Enable that plugin, open this cookbook directory in the agent, and use this handoff:

```text
Publish this cookbook's hosted-demo as a Sites app. Use the installed Sites
skill and its supported Worker build/source/publication workflow. Read
README.md and hosted-demo's source first. Reuse its .openai/hosting.json
project identity if present; do not create duplicate Sites.

Run node --test hosted-demo/tests/*.test.mjs from the cookbook root, then
run node scripts/build.mjs from hosted-demo. Use the generated Worker in
the Sites Worker ESM publication workflow; do not deploy server.mjs.

Publish the supplied frontend, authentic Nebius logo, starter photos and
same-origin Endpoint proxy together. Keep the exact label
"Powered by Nebius Serverless AI". No Python service or Qdrant is required
for this browser-local demo. Do not put any Nebius Endpoint token in source,
Site environment variables, screenshots, logs or publication output.

Start visitors disconnected. Preserve Search -> Connect -> model checks ->
photo indexing -> resumed search. Check coffee returns coffee beans.
Preserve reviewed prompt approval, an unsaved generated preview, explicit
Add to collection or Discard, and browser-local image persistence.

Make the app accessible to the intended readers using supported Sites access
settings. If public access is unavailable, report that limit instead of
calling an owner-private URL a public demo. Test the deployed HTTPS origin,
then report the actual deployment URL and audience. Update the cookbook's
Hosted demo URL only after publication succeeds. Do not create, restart,
stop or modify any Nebius resources as part of publishing this web app.
```

Sites hosts the web app and proxy; the visitor pays for their own running GPU. If a visitor has no Endpoint, direct them to steps 3–5 rather than supplying an author's token. Any hosting access/sign-in requirement is separate from Nebius Endpoint authentication. The hosted collection remains device-local, not a shared cloud gallery. See [hosting notes](docs/PUBLIC-HOSTING.md) for these boundaries and the separate persistent-server option.

## 8. Optional: build the persistent Python + Qdrant version

Use this version when you want to study Qdrant ingestion or keep a gallery on a server. Its configuration and saved collection are independent of the browser-connected demo. On a public deployment, **saved images are shared by its visitors**; this is not the private browser collection from steps 6–7.

Return to the cookbook root, activate the Python environment created in step 2, and edit `.env`:

```bash
cd ..
source .venv/bin/activate
nano .env
```

Set the two base URLs and Endpoint token from step 5. CLI users already saved both token fields; leave those values in place:

```dotenv
EMBEDDING_BASE_URL=https://YOUR_PORT_8000_MANAGED_HOST
EMBEDDING_API_KEY=YOUR_ENDPOINT_TOKEN
GENERATION_BASE_URL=https://YOUR_PORT_8001_MANAGED_HOST
GENERATION_API_KEY=YOUR_ENDPOINT_TOKEN
GENERATION_MODEL=black-forest-labs/flux-3-image-klein
```

Save with **Ctrl+O**, Enter, then **Ctrl+X**. Use base URLs without `/v1`; keep `.env` private. Configure and check both model APIs to complete this search-and-create recipe.

```bash
docker compose up -d qdrant
curl --fail http://127.0.0.1:6333/collections
python3 -m media_search check-endpoint --timeout 1800
python3 -m media_search check-generation --timeout 1800
python3 -m media_search ingest examples/images
python3 -m media_search serve
```

Qdrant should report `"status":"ok"`. The embedding check must return `"ready": true` and `"dimensions": 4096`; readiness alone does not prove successful generation. On a fresh collection, ingestion should report **three points** and `"failed_sources": 0`. Re-ingestion skips identical indexed photos. Open **[http://127.0.0.1:8080](http://127.0.0.1:8080)** and repeat the search, approval, unsaved-preview, Add and Discard checks from step 6. This app reads its Endpoint connection from `.env` rather than the browser connection dialog.

To index your own photos, use a second terminal in the cookbook root:

```bash
source .venv/bin/activate
python3 -m media_search ingest /absolute/path/to/my-images
```

Start with up to **20 JPG, PNG or WebP images** and keep the input folder separate from `data/`. This walkthrough displays images only; historical video records, if present, remain untouched. Save both media files and Qdrant data when backing up: vectors do not contain image bytes.

<details>
<summary><strong>Optional: host this shared Qdrant gallery on your own domain</strong></summary>

This is a separate deployment from the browser-connected Sites app. It needs a **Linux CPU server you control**, Docker Engine and Docker Compose, a domain whose DNS points to that server, and inbound **80/TCP and 443/TCP**. The CPU server has its own cost and does not need a GPU. This cookbook does not acquire a server or register a domain.

Copy the complete cookbook to that server. From its cookbook root:

```bash
cp deploy/.env.example deploy/.env
chmod 600 deploy/.env
nano deploy/.env
```

Fill in `DOMAIN` (hostname only), `ACME_EMAIL`, both managed model URLs/tokens, and a long random `QDRANT_API_KEY`. For a password-gated showcase, set `DEMO_USERNAME` and a long `DEMO_PASSWORD`. These are operator credentials for this shared-gallery version; visitors do not bring their own Endpoint.

```bash
docker compose --env-file deploy/.env -f deploy/public.compose.yaml up -d --build
docker compose --env-file deploy/.env -f deploy/public.compose.yaml logs --tail 50 caddy web
docker compose --env-file deploy/.env -f deploy/public.compose.yaml cp \
  examples/images web:/tmp/example-images
docker compose --env-file deploy/.env -f deploy/public.compose.yaml exec web \
  python3 -m media_search ingest /tmp/example-images
```

Caddy obtains HTTPS when DNS and ports are correct. Open `https://YOUR_DOMAIN`, sign in if configured, and repeat the browser checks. This deployment starts with its own data volumes; the ingestion commands above add the starter photos. Only ports 80/443 are exposed; Qdrant stays internal. Review [public-hosting notes](docs/PUBLIC-HOSTING.md) for persistence and operating limits.

Take this web deployment offline without deleting its data:

```bash
docker compose --env-file deploy/.env -f deploy/public.compose.yaml down
```

This does **not** stop the paid GPU. Complete step 9 too.

</details>

## 9. Stop paid compute when finished

Use **Disconnect** in the connected app when you are done with its credentials. Press **Ctrl+C** in any local demo server terminal. If you ran local Qdrant, stop its containers from the cookbook root:

```bash
docker compose down
```

Then open **Serverless AI → Endpoints**, find **media-search-generate** (or **media-search-generate-spot**), choose **Stop**, and wait for **Stopped**. Stop each recipe Endpoint you deliberately created, leaving unrelated resources alone. Or use the Endpoint ID saved in step 5:

```bash
export ENDPOINT_ID=aiendpoint-REPLACE_WITH_YOUR_ID
export AI_AGENT="${AI_AGENT:-codex}"
nebius ai endpoint stop --id "$ENDPOINT_ID"
nebius ai endpoint get --id "$ENDPOINT_ID" --format jsonpath='{.status.state}'
```

Wait for `STOPPED`. **Disconnecting, closing a browser or stopping the web app does not stop the GPU.** An idle running Endpoint is still billable. Separate storage and web hosting can also have costs; check [Serverless billing](https://docs.nebius.com/serverless/pricing-quotas).

For the browser demo, saved images remain in this device's browser storage; reconnect to re-index them when you return. For the Qdrant version, keep `data/` and the Qdrant volume together. Start the same Endpoint when needed rather than creating another one. Model downloads may run again after an Endpoint restart.

## If something goes wrong

| Problem | Check |
| --- | --- |
| Local demo cannot be reached | Run `node server.mjs` from `hosted-demo/` and keep its terminal open. Open port **8085** on the same computer; this is separate from GPU readiness. |
| Search asks to connect | Supply the embedding public base URL and Endpoint token; the pending search runs after connection and indexing. |
| Connection returns 401/403 | Use the token protecting that Endpoint, not a Nebius account API key, login token or Hugging Face token. |
| Cannot find the Endpoint token | Use the token saved at creation, or open the Endpoint's **Overview → View code** and copy only its `--token` value. Do not execute the example's creation command. |
| Connection rejects a URL | Use the Nebius-managed HTTPS base URL for the correct port, without `/v1`, credentials, query parameters or a console-page path. Copy each port URL explicitly. |
| Connection reports the wrong model | Port 8000 must serve `Qwen/Qwen3-VL-Embedding-8B` with 4096 dimensions. Port 8001 must serve `black-forest-labs/flux-3-image-klein`; both are required for the complete demo. |
| Endpoint is Running but connection fails | Models may still be loading. Check readiness/startup logs; retry connection rather than creation. |
| Spot Endpoint is Stopped / Preempted | Use the recovery steps above. The same managed URLs can be reconnected after a successful restart; do not create duplicate Endpoints or automatically repeat generation. |
| Creation is not connected | Choose **Create an image** and supply the port-8001 URL and, if different, its authentication token. Creation is a required part of the complete demo; its setup is requested at the first creation action. |
| Request is busy or fails | Read the displayed error. A shared GPU may serialize generation and embedding; wait for the current operation before an explicit retry. |
| Generated image is not in search | Choose **Add to collection** and wait for embedding. The unsaved preview and **Discard** do not add an image. |
| Photos are missing on another device | The connected demo stores photos in this browser only. It does not synchronize collections between devices or host them in Qdrant. |
| Reload asks for the token again | Credentials deliberately live only in page memory. Reconnect to re-embed the saved collection. |
| Collection is full | The connected demo has a 20-image limit; inspect the app's collection controls before adding more. |
| Image build/push fails | Docker disk space, build dependencies, registry credentials and package permissions. No Endpoint is required to debug a build. |
| FLUX download returns 401/403 | Human access approval for both gated repositories and the `HF_TOKEN` secret reference. |
| Qdrant has vectors but missing previews | Restore the matching media directory as well as the database. |

[Technical reference](docs/REFERENCE.md) · [Endpoint settings](docs/ENDPOINT.md) · [Public hosting](docs/PUBLIC-HOSTING.md) · [Current validation](VALIDATION.md)
