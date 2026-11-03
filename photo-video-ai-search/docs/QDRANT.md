[← Back to the cookbook](../README.md)

# Optional: a persistent Python + Qdrant gallery

Use this version to study ingestion or keep a gallery on a server. It is separate from the browser-connected demo: Qdrant stores vectors, `data/` stores media, and `.env` supplies the operator's Endpoint credentials.

## 1. Prepare Python and configuration

You need **Python 3.12**, Docker with Compose, and the running dual-model Endpoint from the [cookbook](../README.md). On macOS, install missing tools with `brew install python@3.12` and `brew install --cask docker-desktop`, then finish Docker Desktop setup.

Run from the extracted `photo-video-ai-search` directory:

```bash
python3.12 -m venv .venv
source .venv/bin/activate
python3 -m pip install -r requirements.txt
cp -n .env.example .env
chmod 600 .env
nano .env
```

Set these values in `.env`, keeping the supplied model IDs and 4096 embedding dimensions:

```dotenv
EMBEDDING_BASE_URL=https://YOUR_PORT_8000_MANAGED_HOST
EMBEDDING_API_KEY=YOUR_ENDPOINT_TOKEN
GENERATION_BASE_URL=https://YOUR_PORT_8001_MANAGED_HOST
GENERATION_API_KEY=YOUR_ENDPOINT_TOKEN
GENERATION_MODEL=black-forest-labs/flux-3-image-klein
```

Use managed HTTPS base URLs without `/v1`, and the Endpoint token, not your Nebius account key or Hugging Face token. Save with **Ctrl+O**, Enter, then **Ctrl+X**. Keep `.env` private; if it already exists, edit it rather than replacing it.

## 2. Check, index and open

```bash
docker compose up -d qdrant
curl --fail http://127.0.0.1:6333/collections
python3 -m media_search check-endpoint --timeout 1800
python3 -m media_search check-generation --timeout 1800
python3 -m media_search ingest examples/images
python3 -m media_search serve
```

Qdrant should return `"status":"ok"`. The embedding check should report `"ready": true` and `"dimensions": 4096`; the generation check verifies readiness without creating an image. Fresh ingestion should report **three collection points** and `"failed_sources": 0`. Re-ingestion skips unchanged photos.

Open **[http://127.0.0.1:8080](http://127.0.0.1:8080)** on this computer. Search for **coffee**, review and approve a creation prompt, then choose **Add to collection** or **Discard** on its unsaved preview. The app reads connection values from `.env`; it does not use the browser connection dialog from the Node demo.

To add your own photos, open another terminal in the cookbook directory:

```bash
source .venv/bin/activate
python3 -m media_search ingest /absolute/path/to/my-images
```

Start with up to 20 JPG, PNG or WebP files. Keep the input folder separate from `data/`. Back up both `data/` and the Qdrant volume: vectors alone do not contain image bytes.

## 3. Stop locally and stop the GPU

Press **Ctrl+C** in the server terminal, then run from the cookbook root:

```bash
docker compose down
```

This keeps saved data and stops Qdrant. **It does not stop paid compute.** Complete [Stop the GPU](../README.md#6-stop-the-gpu) separately.

## Optional: host this shared gallery on your domain

This route needs a **Linux CPU server**, Docker Compose, a domain pointing to that server, and open ports **80/443**. The server and domain have separate costs. Copy the complete cookbook to the server, then run from its root:

```bash
cp -n deploy/.env.example deploy/.env
chmod 600 deploy/.env
nano deploy/.env
```

Set `DOMAIN` (hostname only), `ACME_EMAIL`, both Endpoint URLs/tokens and a new random `QDRANT_API_KEY`. Set `DEMO_USERNAME` and `DEMO_PASSWORD` for a password-gated showcase. Review the [model's license](https://huggingface.co/black-forest-labs/flux-3-image-klein/blob/main/LICENSE.md) before public use.

```bash
docker compose --env-file deploy/.env -f deploy/public.compose.yaml up -d --build
docker compose --env-file deploy/.env -f deploy/public.compose.yaml logs --tail 50 caddy web
docker compose --env-file deploy/.env -f deploy/public.compose.yaml cp \
  examples/images web:/tmp/example-images
docker compose --env-file deploy/.env -f deploy/public.compose.yaml exec web \
  python3 -m media_search check-endpoint --timeout 1800
docker compose --env-file deploy/.env -f deploy/public.compose.yaml exec web \
  python3 -m media_search check-generation --timeout 1800
docker compose --env-file deploy/.env -f deploy/public.compose.yaml exec web \
  python3 -m media_search ingest /tmp/example-images
```

Open `https://YOUR_DOMAIN` and repeat the local search-and-create check. Caddy provides HTTPS; Qdrant stays inside the Compose network. Saved images are **shared by all visitors**; a shared password does not create private user collections. The defaults limit generation to 20 accepted requests per day and three per IP per hour, with 120 searches per hour. These limits do not replace production identity or moderation.

Take the web stack offline while retaining its volumes:

```bash
docker compose --env-file deploy/.env -f deploy/public.compose.yaml down
```

Do not add `--volumes` unless you intend to erase saved data. Back up media and Qdrant together while writes are paused. Interrupted generation is not resumed automatically; inspect its outcome before approving another attempt. Stop the GPU separately using [step 6](../README.md#6-stop-the-gpu).
