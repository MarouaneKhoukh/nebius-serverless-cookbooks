# Build AI Search for Your Photos and Videos

Type a description and find matching photos or video clips in your own gallery. Qwen3-VL Embedding runs on **Nebius Serverless AI**; the gallery and **Qdrant** run on your computer.

**Powered by Nebius Serverless AI**

## See it in action

![Browse photos and play video clips in the gallery](docs/media/gallery-tour.gif)

[Watch the 12-second recording](docs/media/gallery-tour.mp4) · [Screenshot](preview.png)

*The recording shows browsing and playback of synthetic media previously indexed with real inference. It does not show a new AI search.*

## Before you start

This walkthrough covers local setup, creating the GPU Endpoint, connecting the app, searching the sample and stopping the resources. You do not need another guide or a pre-existing Endpoint.

- The installation commands below use **macOS** and Terminal, the environment used for the live test. On Linux, the app commands work with Python 3.12+, FFmpeg/ffprobe and Docker Compose already installed.
- You need a **Nebius account with billing enabled**, permission to create resources (the `editor` role), and available quota/capacity for **one H100 GPU** in your project. Account approval, billing and quota are external requirements.
- The repository is currently private: you need access to download it.
- The Endpoint is billable while starting or running. Review the price shown in the console before creating it, and stop it in step 9. Your computer does not need a GPU.

## 1. Install the local tools

You need Python 3.12, FFmpeg (including ffprobe and H.264 encoding), and Docker Compose. Skip installations you already have.

If Homebrew is not installed, run its [official installer](https://brew.sh) in Terminal:

```bash
/bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"
```

Follow the installer's **Next steps** to add Homebrew to your shell. Then install the tools:

```bash
brew install python@3.12 ffmpeg
brew install --cask docker-desktop
open -a Docker
```

Finish Docker Desktop's first-launch setup and wait until it is running. Verify:

```bash
python3.12 --version
ffmpeg -version
ffprobe -version
docker info
docker compose version
```

## 2. Download the code and install the app

Open [the repository](https://github.com/MarouaneKhoukh/nebius-serverless-cookbooks), choose **Code → Download ZIP**, and extract the ZIP in Downloads. In Terminal:

```bash
cd ~/Downloads/nebius-serverless-cookbooks-main/photo-video-ai-search
python3.12 -m venv .venv
source .venv/bin/activate
python3 -m pip install -r requirements.txt
cp .env.example .env
chmod 600 .env
```

If you extracted the ZIP elsewhere, change the first path. Keep this terminal open and run the remaining app commands from this directory.

## 3. Sign in to Nebius and select your project

Open [console.nebius.com](https://console.nebius.com) and sign in. Select the tenant and project where you want to run the model. Use a project in a region offering the H100 configuration below.

In **Administration → IAM**, check that you have the `editor` role. In **Administration → Limits → Quotas**, check that the project has room for one H100 VM and a network allocation. If access or quota is missing, have your administrator enable it before continuing.

## 4. Create the model Endpoint

Choose **one** route: the console below, the expandable **CLI** instructions, or **an agent with Nebius skills/MCP**. All use the same model and return to step 5. Do not create a second Endpoint if you already completed another route.

### Option A: Web console (recommended)

In the sidebar, open **Serverless AI → Endpoints → Create endpoint**. Choose **Custom** and enter:

| Setting | Value |
| --- | --- |
| Name | `photo-video-embeddings` |
| Image path | `vllm/vllm-openai:v0.19.1` |
| Container port | `8000`, protocol `HTTP` |
| Authentication | Enable **Token** authentication |
| Computing resources | **With GPU**; **Regular** VM |
| Platform | `gpu-h100-sxm` (NVIDIA H100) |
| Preset | `1gpu-16vcpu-200gb` (1 GPU) |
| Container disk size | **500 GiB** |
| Network | Select `default-subnet`, or the subnet assigned by your administrator |
| IP address type | **Private IP**; access the model through its managed HTTPS URL |

Paste this entire line into **Entrypoint command**:

```text
python3 -m vllm.entrypoints.openai.api_server --model Qwen/Qwen3-VL-Embedding-8B --runner pooling --trust-remote-code --max-model-len 8192 --host 0.0.0.0 --port 8000
```

New projects include [a default network and subnet](https://docs.nebius.com/vpc/overview#default-virtual-networks-resources), so no separate network creation is needed for the default setup. Leave the default **16 GiB shared memory** unchanged. No private registry credentials, extra environment variables or mounted volumes are needed.

**Copy and securely save the generated authentication token before creating the Endpoint.** You will put this token in `.env` in step 5; it is not a general Nebius account API key.

Review the settings and displayed cost, then click **Create endpoint**. Creation starts the Endpoint; you do not need a second start command. Wait until its state is **Running**. The model may still be loading; step 7 checks that it can actually respond.

Open the Endpoint details and copy the managed **`https://` URL** under **Network → Public endpoints** for port 8000. Save the Endpoint name so you can stop it later.

*These settings follow the [official Endpoint configuration](https://docs.nebius.com/serverless/endpoints/manage#how-to-create-an-endpoint) and [Qwen3-VL template](https://github.com/nebius/serverless-ai-cookbook/blob/main/templates/endpoint-qwen3-vl-embedding/README.md).*

<details>
<summary><strong>Option B: Create the Endpoint with the CLI</strong></summary>

**Install and sign in.** This route uses the [official Nebius CLI](https://docs.nebius.com/cli/install), version **0.12.277 or newer**. If needed, install it:

```bash
curl -sSL https://artifacts.nebius.cloud/cli/install.sh | bash
```

Restart Terminal to load the CLI, then return to your recipe directory:

```bash
cd ~/Downloads/nebius-serverless-cookbooks-main/photo-video-ai-search
source .venv/bin/activate
export AI_AGENT="${AI_AGENT:-codex}"
nebius version
nebius profile create
```

If `nebius version` reports an older release, run `nebius update` yourself before continuing. For a new profile, choose a name such as `media-search`; keep `api.nebius.cloud`, `federation` authentication and `auth.nebius.com`. Sign in in the browser that opens, then select the same tenant and project as step 3. A compatible existing profile can be reused instead of creating another.

**Set the resource IDs.** Copy your project ID from the console's project selector. Find `default-subnet` under **Networking → Virtual Networks → Subnets** and copy its ID. Replace both values below with those real IDs:

```bash
export PROJECT_ID=project-REPLACE_WITH_YOUR_ID
export SUBNET_ID=vpcsubnet-REPLACE_WITH_YOUR_ID
```

**Save a token locally.** Generate the Endpoint token and write it directly into your existing `.env`, without printing it:

```bash
export MEDIA_SEARCH_ENDPOINT_TOKEN="$(python3 -c 'import secrets; print(secrets.token_urlsafe(32))')"
python3 -c 'import os; from dotenv import set_key; set_key(".env", "EMBEDDING_API_KEY", os.environ["MEDIA_SEARCH_ENDPOINT_TOKEN"]); os.chmod(".env", 0o600)'
```

**Create once.** This command creates a billable regular H100 Endpoint with the same settings as Option A, using that saved token:

```bash
nebius ai endpoint create \
  --parent-id "$PROJECT_ID" \
  --name photo-video-embeddings \
  --image vllm/vllm-openai:v0.19.1 \
  --platform gpu-h100-sxm \
  --preset 1gpu-16vcpu-200gb \
  --subnet-id "$SUBNET_ID" \
  --container-port 8000/http \
  --disk-size 500Gi \
  --shm-size 16Gi \
  --auth token \
  --token "$MEDIA_SEARCH_ENDPOINT_TOKEN" \
  --container-command python3 \
  --args '-m vllm.entrypoints.openai.api_server --model Qwen/Qwen3-VL-Embedding-8B --runner pooling --trust-remote-code --max-model-len 8192 --host 0.0.0.0 --port 8000' \
  --async \
  --format jsonpath='{.metadata.id}'
unset MEDIA_SEARCH_ENDPOINT_TOKEN
```

The token is already saved in `.env`. The output is limited to a resource ID; use the lookup below to identify the Endpoint and its URL.

To check state and get the managed URL without displaying credentials:

```bash
nebius ai endpoint get-by-name \
  --parent-id "$PROJECT_ID" --name photo-video-embeddings \
  --format jsonpath='{.metadata.id}{"\n"}{.status.state}{"\n"}{.status.public_endpoints[0]}{"\n"}'
```

If the URL is not assigned yet, wait and repeat this read command. Do not repeat `create`. Save the Endpoint ID for cleanup. Once it is running and has a `https://` URL, **continue at step 5**; your token is already in `.env`. Step 7 checks model readiness.

</details>

<details>
<summary><strong>Option C: Ask an agent using Nebius skills or MCP</strong></summary>

First complete the **CLI installation and sign-in** instructions in Option B, but skip its create command. Both agent approaches use your authenticated local Nebius CLI. Open this recipe directory in an agent with terminal access, or use the MCP credential handoff described below.

**Choose Nebius skills.** Install the [official skills](https://github.com/nebius/skills):

```bash
brew install node
npx skills add nebius/skills
```

In the installer, select your agent and the `nebius-cloud-basics` and `nebius-serverless-endpoints` skills. Restart the agent session if needed so it can discover them.

**Or connect the operational MCP (beta).** The [official Nebius MCP server](https://github.com/nebius/mcp-server) requires Python 3.13+ for its own runtime; the gallery keeps its Python 3.12 environment. Install its tools:

```bash
brew install uv
uv python install 3.13
```

Add this local server in your MCP client's server settings (for clients accepting `mcpServers` JSON, use this configuration):

```json
{
  "mcpServers": {
    "nebius": {
      "command": "uvx",
      "args": [
        "--python", "3.13",
        "--refresh-package", "nebius-mcp-server",
        "nebius-mcp-server@git+https://github.com/nebius/mcp-server@main"
      ],
      "env": {
        "SAFE_MODE": "true"
      }
    }
  }
}
```

If the client cannot find `uvx`, use the full path printed by `command -v uvx` as the configuration’s `command`. Its environment must also be able to find `nebius` (check `command -v nebius`). Restart or reconnect the client. Ask it to list `nebius_profiles` and check that `nebius_cli_help` and `nebius_cli_execute` are available. Keep safe mode enabled. The separate `docs.nebius.com/mcp` server only searches documentation; it cannot deploy this model.

**Keep credentials local.** The operational MCP returns CLI output to the agent. Use output projections such as `--format jsonpath='{.metadata.id}'` or `--format jsonpath='{.status.state}'` for Endpoint reads, and never retrieve tokens through MCP. For creation and private token capture, use the agent's local terminal with credential output suppressed, or run Option B's token-generation and create commands yourself; they save the token in `.env`. An MCP-only agent can prepare the exact create command, then monitor the resource after that handoff.

Paste this prompt after choosing one of the approaches above:

```text
Follow this cookbook using nebius-cloud-basics and nebius-serverless-endpoints,
if installed, or the connected Nebius operational MCP. Confirm my project and
check for an existing photo-video-embeddings Endpoint before creating one.

Use the exact settings from step 4: Qwen/Qwen3-VL-Embedding-8B,
vllm/vllm-openai:v0.19.1, pooling runner, trust-remote-code, context 8192,
HTTP port 8000, regular gpu-h100-sxm / 1gpu-16vcpu-200gb,
500 GiB disk, 16 GiB shared memory and token authentication.

Show the deployment command and estimated cost. Ask for approval of paid
creation/start and a bounded sample test unless I have already approved them.
Deploy once. Keep tokens out of chat, tool output and logs; use a local terminal
for private credential capture, or give me Option B's command to run myself.
Do not pass credential-bearing output through MCP or disable its safe mode.

Help me save the URL and token in local .env, then follow steps 6–8 for
readiness, sample ingestion and the gallery. Report what worked, the Endpoint
ID/URL/state and the scoped stop action. Stop at the approved time limit or
when I finish testing; never leave paid compute running without telling me.
```

Whichever route you choose, **return to step 5** with the Endpoint's managed HTTPS URL and saved token, then follow the same database, readiness and gallery steps. If your agent cannot run a required action, use Option A or B; no additional Markdown guide is required.

</details>

## 5. Connect the app to your Endpoint

Back in the recipe terminal, open the local configuration file:

```bash
nano .env
```

Replace these two values with the URL and token you saved. **CLI users:** your token is already set; replace only `EMBEDDING_BASE_URL`:

```dotenv
EMBEDDING_BASE_URL=https://your-managed-endpoint-host
EMBEDDING_API_KEY=your-generated-endpoint-token
```

Use the base HTTPS URL **without `/v1`**. Leave the other settings unchanged. In nano, save with **Ctrl+O**, press **Enter**, then exit with **Ctrl+X**. The app reads `.env` automatically; do not commit or share it.

## 6. Start the vector database

```bash
docker compose up -d qdrant
curl --fail http://127.0.0.1:6333/collections
```

The second command should return JSON with `"status":"ok"`. If the service is still starting, wait a few seconds and repeat the `curl` command. If it keeps failing, run `docker compose logs qdrant` and check Docker is running.

Qdrant stores the search vectors locally. Docker keeps them in a named volume between runs.

## 7. Check the model and index the sample

```bash
python3 -m media_search check-endpoint --timeout 900
```

This waits up to 15 minutes and makes one text embedding request. Continue once it reports `"ready": true` and `"dimensions": 4096`. If it fails, check the URL, token and the Endpoint's startup logs before indexing anything.

Now create and index the sample:

```bash
python3 scripts/make_sample_media.py --output sample_media
python3 -m media_search ingest sample_media
```

On an empty collection, the ingestion summary should be:

```json
{"indexed": 5, "skipped": 0, "failed_sources": 0, "collection_points": 5}
```

The sample contains three images and a 12-second animation, split into two searchable clips. Ingestion sends prepared images and clips to your Endpoint and stores their embeddings in Qdrant.

Run the sample generator only once. If `sample_media` already exists, reuse it by running just the ingestion command; indexed items are skipped.

## 8. Open the gallery and search

```bash
python3 -m media_search serve
```

With the server running, open **[http://127.0.0.1:8080](http://127.0.0.1:8080)** on the same computer. On a fresh collection, you should see **five items: three images and two video clips**.

- Select **Photos**, type **red circle**, and click **Search**.
- Select **Video clips**, type **a moving red circle**, and click **Search**.
- Play a returned clip to inspect it.

The app sends each search description to the model, then finds matching vectors in Qdrant. `127.0.0.1` is your own computer, not a hosted public demo. These synthetic samples test the pipeline; real-photo search quality needs separate evaluation.

## 9. Stop the resources when you finish

1. Press **Ctrl+C** in the gallery terminal.
2. Stop local Qdrant:

```bash
docker compose down
```

3. In the Nebius console, return to **Serverless AI → Endpoints**. Find **photo-video-embeddings**, open its action menu, choose **Stop**, and confirm. Wait until the state is **Stopped**.

If you used the CLI, you can stop it from Terminal instead. Replace the placeholder with the ID saved during creation:

```bash
export ENDPOINT_ID=aiendpoint-REPLACE_WITH_YOUR_ID
export AI_AGENT="${AI_AGENT:-codex}"
nebius ai endpoint stop --id "$ENDPOINT_ID"
nebius ai endpoint get --id "$ENDPOINT_ID" --format jsonpath='{.status.state}'
```

Wait until the check reports `STOPPED`. An agent can perform this same scoped stop after your authorization.

Closing the gallery does **not** stop the GPU. Stopping the Endpoint stops its compute and boot-disk charges; [separately mounted storage has its own billing](https://docs.nebius.com/serverless/pricing-quotas). This recipe does not mount extra cloud storage.

Your local `data/` folder and Qdrant volume retain the media and vectors. Keep both. When you return, start this same Endpoint from its console action menu, run `docker compose up -d qdrant`, repeat the readiness check in step 7, and start the gallery again. In a new terminal, first return to the recipe directory and run `source .venv/bin/activate`.

## Optional: search your own media

While the Endpoint and Qdrant are running, open another terminal in the recipe directory:

```bash
source .venv/bin/activate
python3 -m media_search ingest /absolute/path/to/my-media
```

Refresh the gallery afterward. Start with up to **20 images or short videos**; videos must be at most **120 seconds**. Keep the input folder separate from `data/`. Audio is not searched.

## If something goes wrong

| Problem | Check |
| --- | --- |
| Docker cannot connect | Open Docker Desktop and wait for it to finish starting. |
| Endpoint creation is blocked | Check project permissions, H100 capacity/quota and subnet availability; do not create duplicate Endpoints. |
| Model check returns 401/403 | Use the Endpoint's generated token in `.env`, not your account login token. |
| Model check times out | Inspect Endpoint logs; verify the image, full entrypoint command, port 8000 and managed HTTPS URL. |
| Ingestion fails | Read its reported error. Once fixed, rerun ingestion; completed items are skipped. |
| Gallery is empty | Confirm ingestion reported five collection points and you started the app from the recipe directory. |

Optional depth: [technical reference](docs/REFERENCE.md), [Endpoint settings reference](docs/ENDPOINT.md), [live test results](LIVE-TEST.md), and [local validation](VALIDATION.md). None is needed to follow the default console-and-local-app path above.
