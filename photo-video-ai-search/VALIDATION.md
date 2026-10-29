# Validation record

Checked **29 October 2026**. The local checks below and a later **successful bounded Nebius GPU test** have completed. See [`LIVE-TEST.md`](LIVE-TEST.md) for the real model results and confirmed STOPPED resource state. The original offline-authoring evidence is preserved below.

## Environment

- macOS arm64; Python **3.12.14** in a clean virtual environment.
- Runtime versions are pinned in `requirements-lock.txt`; test versions in `requirements-dev.txt`. Both the complete test install and the reader's runtime manifest resolved successfully from checksum-verified PyPI wheels. `python3 -m pip check` reported no broken requirements in the clean environment.
- FFmpeg/ffprobe **8.1.1** with `libx264`.
- Real local **Qdrant 1.20.0**, official macOS arm64 release binary. Its SHA-256 matched the release's published `531904e822050790bb8c1da6705f801ee48b91eb4c229d0d605ff06f6331b20a` digest. Bound to a loopback test port with telemetry disabled.
- Headless Chromium through Playwright, desktop 1440 pixels wide and mobile 390 pixels wide.

The Docker daemon was not running. The Compose configuration parsed successfully, but the `qdrant/qdrant:v1.20.0` container itself was **not executed**. Database behavior below used the real same-version native service, not a substitute database or a mocked Qdrant API.

## Automated checks

Run from this recipe directory after installing `requirements-dev.txt`:

```bash
python3 -m pytest -q
```

This runs the offline checks and skips the optional local-service test. With a running local Qdrant explicitly selected:

```bash
QDRANT_TEST_URL=http://127.0.0.1:6333 python3 -m pytest -q
```

The authoring run used an isolated loopback test port instead of the reader's default port. The final suite reported **20 passed**. It emitted one Starlette deprecation warning for its HTTPX-based test client. No check made a real model request.

| Check | Actual result |
| --- | --- |
| Image normalization | EXIF orientation applied, RGB JPEG output bounded to 1024 pixels, metadata omitted, transparency placed on white, thumbnails bounded, identical content reused |
| Input failures | Invalid image, file/pixel/duration limits, and intentional later-clip conversion failure rejected without partially published media |
| Native video preparation | Real 12-second video with audio became silent H.264 clips at 0–8 and 8–12 seconds; checked 2 fps, dimensions, pixel format, timestamps and file sizes |
| Embedding protocol | HTTP fixtures checked shared text/image/video chat format, continuation flags, actual base64 bytes, eight-frame video request, dimension/finite/norm validation and sanitized error reporting |
| Disk-backed Qdrant client | State reopened from disk; known explicit vectors ranked correctly, type filters worked and incompatible embedding contracts were rejected |
| Native Qdrant HTTP service | Collection creation/upserts, reconnect, known-vector ranking, type filtering, 2→4→5 pagination with no duplicate IDs, and schema mismatch protection passed |
| Repeat ingestion | Same media skipped without re-embedding; changed bytes created a new point; overlapping input/output directories rejected; Endpoint failure stopped the remaining batch |
| Local API | Gallery, query validation, fixture-vector retrieval, media URLs and HTTP byte-range playback passed; cached browsing worked without an embedding token while search returned a configuration error |
| Static/configuration files | Python compilation, JavaScript syntax, Bash syntax and `docker compose config --quiet` passed |
| Endpoint command helper | Default printing, placeholder rejection and shell quoting checked without calling the Nebius CLI |

## Complete local wiring check

The actual CLI, real FFmpeg preprocessing, native Qdrant service and gallery were run together with a **loopback HTTP embedding fixture**. The fixture returns deterministic test vectors; it does not load Qwen and its rankings have no semantic meaning.

The generated sample contained three synthetic images and a 12-second synthetic animation. Actual first ingestion:

```json
{"indexed": 5, "skipped": 0, "failed_sources": 0, "collection_points": 5}
```

Actual repeated ingestion:

```json
{"indexed": 0, "skipped": 5, "failed_sources": 0, "collection_points": 5}
```

The fixture received three image requests and two video requests for initial indexing. Repeating ingestion added no embedding requests. A text readiness probe and a browser search also exercised the HTTP client. These counts describe wiring, not paid inference, latency, cost or search quality.

The real Qdrant process was stopped and restarted against the same workspace storage. Its five fixture points remained after restart. This checks native database persistence; it does not establish Docker-volume behavior on every host.

## Browser checks

Actual browser checks passed for:

- Five gallery cards, three full-image links and two playable clips with durations **4 and 8 seconds**.
- Server-side photo/video filters, fixture search rendering, useful 503-error display and clearing back to browsing.
- Load-more pagination forced to two items per page: **2→4→5**, then a hidden final-page button; filtered image browsing **2→3**.
- Desktop and mobile layouts without horizontal overflow; no page JavaScript errors.

The original offline screenshot used synthetic media and mocked embeddings. On 29 October 2026, `preview.png` was replaced with an authentic branded capture of the gallery after the separately documented live test. The current screenshot and `docs/media/gallery-tour.mp4` show previously indexed synthetic media, filtering and actual playback; they show no fresh inference. See `LIVE-TEST.md` for real search observations and `docs/media/CAPTURE.md` for capture provenance.

## Source review and original live-check plan

The [Nebius template](https://github.com/nebius/serverless-ai-cookbook/tree/main/templates/endpoint-qwen3-vl-embedding), [Qwen model card](https://huggingface.co/Qwen/Qwen3-VL-Embedding-8B), [pinned vLLM example](https://github.com/vllm-project/vllm/blob/v0.19.1/examples/pooling/embed/vision_embedding_online.py), pinned vLLM request/media implementations and current Nebius Endpoint/lifecycle/pricing docs were reviewed. Source compatibility is separate from live execution evidence.

At first authoring, the following checks remained. The later bounded sample run is recorded in [`LIVE-TEST.md`](LIVE-TEST.md); representative-media evaluation, maximum payload size and scale checks remain open:

1. Verify the exact deployment flags against the installed Nebius CLI, permissions, quota, capacity and current pricing; create or select the intended Endpoint only with authorization.
2. Pull the pinned vLLM image, load the model on the selected H100, confirm managed HTTPS/token authentication and complete the text readiness probe.
3. Successfully embed one real image and one short native video through the managed gateway, confirming 4096 finite values and accepted frame/payload settings. The application has an 8-MiB input cap; actual gateway limits remain unmeasured.
4. Index representative, permissioned photos/videos and inspect meaningful text-query rankings. Synthetic shapes and fixture embeddings establish no real retrieval quality. Record actual queries, expected media, returned ranks and failures before making quality claims.
5. Confirm repeated ingestion, application/Qdrant restarts and live query behavior, then stop the scoped GPU Endpoint and check its actual resource state.

No cloud account inspection, credential issuance, real inference, provisioning, publication or paid call occurred during cookbook authoring. The temporary local gallery, fixture and native database processes were stopped after validation. No cloud resource was created by this work.


## Follow-up run on the user’s machine

On 29 October 2026, at the user's request, Docker Desktop 28.5.1 was started and the actual `qdrant/qdrant:v1.20.0` Compose container was pulled and run with its named volume. A project-local `.venv` was installed from the pinned dependencies. All **20 tests passed** against Docker Qdrant, and the gallery was started at **http://127.0.0.1:8080**. A browser check confirmed the real empty-collection state. Three synthetic images and two native clips were prepared locally, without creating fixture vectors in the live collection.

Nebius sign-in was refreshed by the user. Read-only Endpoint inspection found vision generation models rather than Qwen3-VL Embedding. The exact proposed H100 deployment passed CLI dry-run validation with the project's explicit default subnet. No GPU resource was created and no real model request was made during this initial local setup. The subsequent approved GPU test is recorded below and in `LIVE-TEST.md`; `RUN-STATUS.md` records the final state. Local Docker/database/gallery processes remain running for the user to browse stored results.


## Live GPU validation completed

The user separately approved a new H100 Endpoint and a bounded 10-request test. Real text, image and native-video embeddings succeeded, all three filtered image queries ranked their expected sample first, and the browser video search ranked the expected clip first. Re-ingestion made zero new embedding calls. The Endpoint was stopped and its STOPPED state confirmed. See [`LIVE-TEST.md`](LIVE-TEST.md) and [`LIVE-TEST.json`](LIVE-TEST.json) for evidence and limits. The normal gallery and Docker database remain running locally; the temporary port-8081 test app was stopped.
