# Build AI Search for Your Photos and Videos

Type a description and find matching photos or video clips in your own gallery. **Qwen3-VL Embedding** runs on Nebius Serverless AI; the gallery and **Qdrant** run on your computer.

**Powered by Nebius Serverless AI**

## See it in action

![Browse photos and play video clips in the gallery](docs/media/gallery-tour.gif)

[Watch the 12-second recording](docs/media/gallery-tour.mp4) · [Screenshot](preview.png)

*This recording shows browsing and playback of synthetic media previously indexed with real model inference. It does not show a new AI search.*

## What you need

- Python **3.12+**.
- Docker running, with Docker Compose.
- FFmpeg and ffprobe installed, with the `libx264` encoder.
- A Nebius Serverless AI Endpoint serving **Qwen/Qwen3-VL-Embedding-8B**, plus its URL and token. [Create an Endpoint](docs/ENDPOINT.md) if you need one.

The Endpoint is billable while running. It is needed to index media and run new searches.

## 1. Get the code

```bash
git clone https://github.com/MarouaneKhoukh/nebius-serverless-cookbooks.git
cd nebius-serverless-cookbooks/photo-video-ai-search
python3 -m venv .venv
source .venv/bin/activate
python3 -m pip install -r requirements.txt
cp .env.example .env
```

Run the remaining commands from this same directory.

## 2. Connect your Endpoint

Open `.env` and set these two values:

```dotenv
EMBEDDING_BASE_URL=https://your-managed-endpoint-host
EMBEDDING_API_KEY=your-endpoint-token
```

Copy the managed HTTPS URL from **Public endpoints**, without adding `/v1`. Keep the other settings unchanged. Your token stays on the backend; do not commit `.env`.

## 3. Start Qdrant and check the model

```bash
docker compose up -d qdrant
curl --fail http://127.0.0.1:6333/collections
python3 -m media_search check-endpoint --timeout 900
```

If Qdrant is still starting, wait a few seconds and repeat the `curl` check. The model check waits for loading, makes one text embedding request, and should report `ready: true` and `dimensions: 4096`.

## 4. Add sample media and open the gallery

```bash
python3 scripts/make_sample_media.py --output sample_media
python3 -m media_search ingest sample_media
python3 -m media_search serve
```

Open **[http://127.0.0.1:8080](http://127.0.0.1:8080)**. You should see **five items**: three images and two video clips.

Try **“red circle”** with the **Photos** filter, or **“a moving red circle”** with **Video clips**. Play a clip to inspect the result.

The sample generator creates local shapes and a short animation. Run it once; to use the existing sample again, just repeat the ingestion command. Already indexed items are skipped.

## 5. Search your own media

In another terminal, activate `.venv` from the recipe directory and run:

```bash
python3 -m media_search ingest /absolute/path/to/my-media
```

Refresh the gallery when ingestion finishes. Start with up to **20 images or short videos**; videos must be at most **120 seconds**. Keep your input folder separate from `data/`. Images and video clips are sent to your Endpoint for embedding; audio is not searched. [Supported formats and limits](docs/REFERENCE.md#media-limits).

## When you’re done

Press **Ctrl+C** to stop the gallery, then stop local Qdrant:

```bash
docker compose down
```

**Stop your GPU Endpoint in the Nebius console to stop its running charges.** [CLI stop/start commands](docs/ENDPOINT.md#stop-or-restart-your-endpoint).

Your local `data/` folder and Qdrant volume retain the indexed collection. Keep both if you want to use it again. New searches require the Endpoint to be running.

## Need help?

- [Endpoint setup](docs/ENDPOINT.md)
- [Troubleshooting, implementation details, and agent prompt](docs/REFERENCE.md)
- [Live test results](LIVE-TEST.md) and [local validation](VALIDATION.md)

The sample pipeline was tested with real text, image, and video embeddings. Search quality on representative photos and videos still needs evaluation.
