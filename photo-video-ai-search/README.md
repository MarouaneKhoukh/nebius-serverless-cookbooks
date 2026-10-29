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

## 5. Connect the app to your Endpoint

Back in the recipe terminal, open the local configuration file:

```bash
nano .env
```

Replace these two values with the URL and token you just saved:

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

Optional depth: [technical reference and agent prompt](docs/REFERENCE.md), [CLI deployment alternative](docs/ENDPOINT.md), [live test results](LIVE-TEST.md), and [local validation](VALIDATION.md). None is needed to follow the default console-and-local-app path above.
