[← Back to the cookbook](../README.md)

# Host the demo people connect to their Endpoint

The primary hosted experience is **`hosted-demo/`**. It starts disconnected, asks each visitor for their Nebius Endpoint connection, and keeps that visitor's saved gallery in their browser. Publishing the app does not publish an author's GPU credentials or make an author's collection public.

The [README](../README.md#7-publish-the-connected-demo) includes the complete Sites-agent publishing handoff. The source also includes a separate Python/Qdrant implementation for an operator-managed shared gallery; that is an optional deployment with different storage and ownership.

## Connected demo architecture

| Location | Responsibility |
| --- | --- |
| Visitor's browser | Interface, connection form, saved photos/metadata in IndexedDB, vectors and token in page memory |
| Hosted JavaScript Worker | Serves the app and proxies bounded requests to validated Nebius inference URLs |
| Visitor's Nebius Endpoint | Qwen embedding, FLUX generation and required companion models |

The Worker needs HTTPS access to the managed inference APIs. It does not run Qwen, FLUX, Python, FFmpeg or Qdrant. The GPU is paid for and controlled through the Nebius project used by the visitor. The web-hosting audience/sign-in policy and Endpoint token authentication are separate.

A static frontend by itself is insufficient. The current model gateway does not provide the browser CORS contract required for direct cross-origin authenticated calls. Serve the frontend and proxy on the same HTTPS origin instead of asking readers to disable browser protections or embedding the author's token in JavaScript.

## Local preview

With Node.js **22 or newer**, run from the cookbook root:

```bash
cd hosted-demo
node server.mjs
```

Open **http://127.0.0.1:8085** on that computer. No Python, Docker or `.env` model token is required for this connected interface. The visitor enters an already running compatible Endpoint in the form. The README includes creation steps for readers who do not have one.

The loopback URL is a local preview, not a link other people can open. Its browser storage is also separate from the eventual hosted origin. A preview test does not establish that the published site's access policy or HTTPS proxy works.

## Sites publication

Use the Sites plugin and its installed skill in a compatible agent. Open the cookbook and give the agent the [README publishing handoff](../README.md#7-publish-the-connected-demo). This is the supported publication route supplied with the recipe; a Cloudflare account or hand-written deployment credentials are not required by that agent workflow.

The publication must include the supplied application assets and its server proxy, not just a screenshot or static gallery. From the cookbook root, the source checks are:

```bash
node --test hosted-demo/tests/*.test.mjs
```

Build the Worker from its own directory:

```bash
cd hosted-demo
node scripts/build.mjs
```

The build packages static assets with the standalone Worker. `server.mjs` is the portable local Node entrypoint, not the hosted Worker entrypoint. The Sites agent uses the generated Worker with the Sites Worker ESM source/package/publication workflow and records the actual deployment URL after a successful native deployment result.

For a new Site, the agent creates one identity and persists it in the deployment working copy's `.openai/hosting.json`. For updates, it must reuse that identity rather than create another Site. The downloadable cookbook does not carry an author's personal Site ID, source write credential or Endpoint token. Do not copy local `.env`, runtime data, gallery databases or private working files into the deployed source.

Confirm the hosting audience deliberately. A verified owner-private deployment is usable by its owner and authorized visitors, but is not a publicly accessible demo. If the hosting service cannot provide the intended audience, report that limitation. Never present an authentication redirect or a private Site URL as evidence that arbitrary readers can use the app.

After publication, check the deployed URL as a visitor:

1. Start disconnected; submit **coffee** and confirm the connection form retains it.
2. Enter a wrong token and confirm a clear failure without a fake connected state.
3. Enter the correct embedding URL/token. Wait for model checks and photo indexing; confirm the search resumes and **coffee beans** appears as a match. The status must show that creation still needs its connection rather than presenting the complete demo as ready.
4. Search **espresso** and confirm it finds coffee beans by visual similarity. Search **football** against the starter collection and confirm **No matching photos**, zero result cards and a create-or-keep-searching choice. With generation disconnected, **No, keep searching** must not ask for a generation Endpoint. **Yes, create an image** must ask for its port-8001 URL, preserve the working search and open prompt review after connection, without re-indexing or generating. Review/edit the prompt and cancel it. Confirm no generation began.
5. Approve a generation; inspect its unsaved preview. Confirm Add persists and makes it searchable, while Discard on an unsaved preview leaves the gallery unchanged.
6. Reload: saved images should remain, the token should be requested again, and reconnect should re-index before search. Check another browser profile has a separate collection and no saved connection.

Use an already authorized Endpoint and inference scope for live checks. Deploying the web app itself does not require starting, replacing or stopping a GPU resource. Record actual browser and inference checks in [validation](../VALIDATION.md); an uploaded bundle or health response alone does not prove the journey works.

## Connection and credential boundary

The connection form asks for:

| Field | Value |
| --- | --- |
| Embedding URL | Token-protected managed public HTTPS base URL for port 8000; no `/v1` |
| Endpoint token | The token protecting that inference Endpoint, not an account API key or `HF_TOKEN` |
| Generation URL | Required for image creation; managed public HTTPS base URL for port 8001, copied explicitly at the creation step |
| Generation token, optional | Only needed when it differs from the embedding token |

Find the managed URLs in **Serverless AI → Endpoints → your Endpoint → Overview → Public endpoints**. Use the Endpoint token saved at creation. For an existing Endpoint, **Overview → View code** displays a CLI example containing `--token`: copy only that value, without quotes, directly into the connection form. **Do not run the displayed Endpoint creation command**, publish the example, or capture the token in media. The existing Endpoint's Settings page is not needed to retrieve these connection values.

Both connections are required for the complete search-and-create demo. The first form connects Qwen; the creation action connects FLUX. The model checks expect `Qwen/Qwen3-VL-Embedding-8B` with 4096-dimensional embeddings and `black-forest-labs/flux-3-image-klein` for image creation. A different model with an OpenAI-shaped API is not automatically compatible.

Tokens live in page memory and accompany requests to this app's same-origin server proxy. HTTPS protects browser-to-host and host-to-Endpoint transport. The host therefore handles a visitor's credentials while forwarding their requests; use a host you trust. The app does not persist those credentials in IndexedDB, include them in URLs, configure them as shared Site environment variables, or return them in connection responses. Keep request-body logging, analytics capture of connection fields and error-body forwarding disabled.

The proxy accepts only validated Nebius-managed HTTPS base URLs and the operations implemented by this recipe. Retain URL validation, redirect rejection, bounded request/response handling, timeouts and safe errors. Do not turn it into a general URL fetcher, accept localhost/private-IP targets, forward arbitrary paths/headers, or echo upstream errors that may contain credentials, prompts or images.

Connecting, disconnecting and publishing never invoke Nebius resource creation or lifecycle APIs. Only the selected Endpoint's inference APIs are used. Disconnect clears page connection state; it does not stop a billable GPU. The reader must stop compute explicitly through the README's scoped console or CLI instructions.

## Gallery ownership and limits

Saved image bytes and metadata are kept in **IndexedDB for this browser profile and web origin**, with a **20-image cap**. Vectors are recomputed into page memory on every connection. Tokens and unsaved previews are never saved with that collection.

The demo has no hosted Qdrant, shared saved gallery, account-based synchronization or server backup for visitor collections. Moving from localhost to the deployed URL starts with that origin's separate collection. Another device or browser will not see the saved images. Browser storage can be cleared or evicted, so retain independent copies of important output.

Every connection re-embeds saved photos through the newly connected Endpoint. This avoids silently mixing embeddings from different inference connections. Re-indexing has real inference work; it is not a dummy loading animation. Endpoint availability, token validity, model compatibility and GPU contention can still fail.

FLUX generation requires a reviewed, explicit approval. The preview remains unsaved until **Add to collection**, which makes an embedding call before storage. Discard does not index it. The hosted generation call is synchronous and has no durable exactly-once ledger: a lost response may leave the actual GPU operation completed or running. Do not automatically retry a generation after an ambiguous failure; another explicit approval can generate another image.

## Separate option: a persistent shared Qdrant gallery

The original Python implementation remains useful when an operator wants a server-owned gallery and Qdrant. It uses **`deploy/public.compose.yaml`**, not the browser-connected Worker. The [README's optional deployment block](../README.md#8-optional-build-the-persistent-python--qdrant-version) includes configuration, startup and starter-image ingestion commands.

| Location | Persistent shared version |
| --- | --- |
| Nebius GPU Endpoint | Same model runtime |
| Linux CPU host | Caddy, FastAPI, Qdrant, saved media and SQLite request ledger |
| Browser | Calls operator's web API; operator's Endpoint token stays server-side |

This option needs an existing Linux CPU server, Docker Compose, a domain/DNS and reachable ports **80/443**. The host and domain have separate costs. Caddy handles HTTPS; the Compose network keeps Qdrant and the internal web port private. Do not expose Qdrant publicly.

Copy `deploy/.env.example` to private `deploy/.env`. Set the domain, certificate email, both managed API URLs/tokens and a separate random `QDRANT_API_KEY`. A nonempty `DEMO_PASSWORD` enables the optional shared HTTP Basic gate with `DEMO_USERNAME`. This gate does not provide separate private user collections. Saved generated images become visible to all visitors after their owner chooses Add; unsaved previews remain session-owned.

The service uses one Python process and a bounded generation queue. SQLite persists job accounting and budgets: defaults are 20 accepted generations per day, three per IP per hour, and 120 searches per hour. These are small-demo safeguards, not a production moderation, identity or queue system. Restarting the web service marks interrupted jobs failed rather than resuming an unknown model operation.

The named volumes retain media/state, Qdrant, Caddy certificates and Caddy configuration. Back up media and Qdrant together while writes are quiescent. A database snapshot without the matching media files cannot restore previews. Protect backups because prompts and unsaved previews can be included. Take the web stack offline without deleting its data:

```bash
docker compose --env-file deploy/.env -f deploy/public.compose.yaml down
```

Do not add `--volumes` unless erasing its saved data is intentional. This command does not stop the GPU; use the separate scoped Endpoint stop instructions when the approved session ends.

## License and output handling

FLUX 3 Image Klein uses its [FLUX Kommunity License](https://huggingface.co/black-forest-labs/flux-3-image-klein/blob/main/LICENSE.md). Review the actual operator's applicable terms before exposing the model publicly; calling the application a free demo does not by itself determine eligibility. Human model access and acceptance remain required.

The supplied runtime keeps upstream prompt expansion and content checks. The approval screen shows the app-submitted prompt; the prompt upsampler may expand it internally. Generated previews and saved cards stay labelled. A classifier, preview approval and request limits are not a guarantee against undesirable output or a complete public-service moderation system.
