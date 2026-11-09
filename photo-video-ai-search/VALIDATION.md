# Test results

Recorded checks cover the browser demo, shared-GPU runtime and optional Python/Qdrant implementation. The latest live results below are from 3 November 2026. They are small acceptance tests, not general quality or performance benchmarks.

## Automated checks

| Component | Recorded result |
| --- | --- |
| Browser app and relay | 78 Node checks passed, including connection failures, retrieval, prompt review, generation errors and explicit saving. |
| GPU runtime | 19 offline checks passed for the gateways, supervision and telemetry. |
| Python/Qdrant implementation | 68 checks and 13 subtests passed against local Docker Qdrant. One upstream Starlette deprecation warning remained. |
| Web image and HTTPS configuration | The web container built and served locally. Caddy configuration validation passed. The optional Caddy/Compose public host was not deployed. |

Run the browser checks from this cookbook directory:

```bash
node --test hosted-demo/tests/*.test.mjs
```

For the Python implementation, install `requirements-dev.txt` in its virtual environment and run `python3 -m pytest -q`. Set `QDRANT_TEST_URL=http://127.0.0.1:6333` to include the local-service test. These automated checks use test responses; real inference is recorded separately below.

## Browser demo

The app was published at [nebius-serverless-search-create.vercel.app](https://nebius-serverless-search-create.vercel.app). Public page, asset and health requests returned HTTP 200. Invalid destination URLs, cross-origin requests and invalid Endpoint tokens returned 422, 403 and 401 respectively.

Through the Vercel relay:

- A green ceramic teapot request returned a valid 1024×1024 PNG in 12.11 seconds.
- The single-word prompt `football` was declined by the model. After adding the editable photo-brief flow, its default football draft produced a valid 1024×1024 PNG in 14.49 seconds. A separate ball-on-grass description succeeded in 11.82 seconds.
- The initial refusal did not identify which upstream content check caused it. The updated runtime reports a safe stage label when available; that runtime diagnostic change was checked offline, not installed into the already running test Endpoint.

These are individual generation observations. A complete hosted browser search → generation → save → retrieval test and broader prompt evaluation remain open. See the [hosted generation results](docs/evidence/hosted-generation-2026-11-03.json) and [football-brief results](docs/evidence/football-photo-brief-2026-11-03.json).

The local browser app completed the full H200 journey with real Qwen3-VL and FLUX inference: connect, index the three starter photos, search, review a prompt, generate an unsaved preview, add it, and retrieve it later. A separate generated preview was discarded without changing the collection. Reloading and reconnecting retained five saved photos. Credentials remained in page memory. [Connection and browser results](docs/evidence/byo-endpoint-api-2026-11-02.json) · [Creation flow](docs/evidence/creation-journey-2026-11-02.json) · [Direct creation](docs/evidence/core-search-create-2026-11-02.json)

## Search behavior

A real-model check compared four images with twelve text queries, using visual embeddings without filename boosts:

| Query | Highest-ranked result | Cosine similarity |
| --- | --- | --- |
| coffee | Coffee beans | 0.348 |
| espresso | Coffee beans | 0.281 |
| a lake in the mountains | Mountain lake | 0.416 |
| a city after dark | City at night | 0.360 |
| football / soccer / a football match / dog / red car | No result above the 0.25 display threshold | Highest score: 0.157 |

The threshold was selected using this small sample. It is a display heuristic, not a calibrated relevance probability. The browser check also confirmed that rejected candidates stayed outside the gallery and that descriptive-name matching worked alongside visual similarity. [Recorded scores](docs/evidence/search-relevance-2026-11-02.json) · [Browser results](docs/evidence/search-browser-2026-11-02.json)

## GPU execution and packaging

The two-model runtime uses Qwen3-VL Embedding 8B, FLUX 3 Image Klein and its prompt upsampler, with serialized inference on one GPU. Pinned source/model revisions are in [endpoint/versions.json](endpoint/versions.json).

| Run | Result |
| --- | --- |
| Regular H200 | Real embedding, generation, review, Add and Discard checks completed through the local app. [Results](docs/evidence/review-flow-h200-2026-11-02.json) |
| RTX PRO 6000 Blackwell | Two real 1024×1024 generations completed. Both generated images ranked first on later searches. Sampled whole-GPU memory peaked at 82,689 MiB, approximately 80.75 GiB. The Endpoint was stopped after the test. [Results](docs/evidence/rtx-shared-gpu-2026-11-02.json) |
| Preemptible H200 | Creation succeeded with a $2/GPU-hour limit, but two startup attempts were preempted before both models became ready. No preemptible inference was performed. The Endpoint finished stopped. [Results](docs/evidence/spot-endpoint-2026-11-03.json) |
| Earlier Qwen-only H100 | Text, image and video embeddings, Qdrant ingestion and retrieval completed. This covered the previous search-only version. [Results](LIVE-TEST.md) |

The custom GPU image built, passed import/version checks and was pushed to a registry. The live two-model tests booted the public vLLM base image with the cookbook sources injected at startup. **The packaged custom image still needs its own registry-pull and GPU-boot test.**

The RTX memory result is a sampled whole-device maximum, not an allocator high-water mark. It does not establish room for another model, concurrent inference or larger inputs. The successful test requests were serialized. [Initial RTX run](docs/evidence/rtx-first-acceptance-2026-11-02.json) · [Photo-library check](docs/evidence/rtx-library-check-2026-11-02.json)

## Pricing record

The preemptible H200 quote on 3 November 2026 was approximately $1.45/hour including a 500 GiB disk, compared with $5.45/hour for the regular configuration, before tax. This was an hourly quote; it does not establish measured cost per image. Prices change, and the two preemptible startup attempts did not reach inference.

## Remaining checks

- Boot the packaged GPU image from the registry and exercise both model APIs.
- Complete the search, generation, save and retrieval journey through the hosted browser origin.
- Evaluate representative photo collections, longer sessions, larger payloads and concurrent visitors.
- Verify persistent-volume recovery and HTTPS operation for the optional Caddy/Compose deployment.

[Preview provenance](docs/media/CAPTURE.md) · [Deployment limits](hosted-demo/DEPLOY.md) · [Earlier search-only test data](LIVE-TEST.json)
