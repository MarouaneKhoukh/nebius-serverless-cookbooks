# Validation record

Updated **3 November 2026**. The current browser-connected demo passed **37 Node checks**, a real H200 connection/generation journey, and the creation/relevance refinements below. The unchanged persistent Python/Qdrant implementation previously passed **68 checks and 13 subtests** against real local Qdrant. Earlier Python browser, RTX and search-only results are preserved below as historical evidence.

## Spot H200 startup test: 3 November 2026

A separate Spot H200 Endpoint was created successfully with the same two-model runtime, a 500 GiB disk and a **$2 per GPU-hour cap**. Two startup attempts ended with **Preempted** before both model APIs became ready. **No Spot inference was performed**, and the demo was not switched to Spot. The final check at **10:21:46 UTC** found Spot **STOPPED**. The regular H200 remained **RUNNING** and unchanged; both regular model health/identity checks passed at **10:22:19 UTC**. [Sanitized evidence](docs/evidence/spot-endpoint-2026-11-03.json).

The calculator quote at **10:00:58 UTC on 3 November 2026**, before tax, was **$1.40/hour** Spot compute plus approximately **$0.05/hour** for the disk, versus **$5.40/hour** regular compute plus the same disk: approximately **$1.45 versus $5.45/hour**, or **73% lower** at that observation. This is a dated estimate, not a guaranteed current price, invoice or measured saving per image. The cap applies to GPU compute; disk is additional. This run demonstrates successful Spot provisioning and the interruption risk, not working Spot generation or reliable startup. Account-specific resource identifiers are redacted from the public evidence.

## Search and creation as core features

The current interface is branded **Search + Create**, with a primary **Create an image** action available before a search. Both Qwen and FLUX are required for the complete demo. The initial form connects the collection/search stage; the first creation action connects FLUX. The status distinguishes **Search ready · Creation not connected** from **Search + creation ready**. The former optional-generation section was removed from the initial form, and the README requires both model URLs and the complete generation flow.

All **37 Node checks passed**, including the new direct-creation journey: a description chosen before setup survives collection connection/indexing and leads to FLUX connection and editable prompt review, without a text-search embedding or premature generation. Cancellation, a new search and disconnect clear the pending creation request. Changing search connection settings retains and re-verifies an already configured FLUX connection.

The actual updated browser followed that journey using **a handmade ceramic teapot on a wooden table**. The first model connection retained all **five** saved photos and showed the partial-setup status. The FLUX check succeeded, the status became **Search + creation ready**, and review opened with the original description. Review was cancelled; no image was generated or saved in this check. A subsequent **coffee** search still returned Coffee beans and the saved barista image. [Browser evidence](docs/evidence/core-search-create-2026-11-02.json) · [Current interface](docs/media/search-create-core.png) · [Partial setup](docs/media/search-create-partial-setup.png).

This verifies the revised entry point and model connections; it does not claim a new generation run. The earlier successful H200 generation/Add/Discard evidence below remains separate. No cloud resource lifecycle or GPU runtime was changed.

## Simpler creation journey

The connected demo now asks **Want to create an image of “football”?** inside the no-match state, with **Yes, create an image** and **No, keep searching**. It requests the generation connection only after yes, and only when FLUX is missing. The focused form uses the search token by default, accepts an optional separate token, and verifies only the FLUX model list through `/api/connect-generation`. It preserves the current query, embedding connection and indexed vectors, then opens editable prompt review. Generation still requires **Approve and generate**; Add/Discard remains separate.

The real browser check reconnected search and retained all **five** photos. **No** dismissed the question without opening an Endpoint form. **Yes** opened only the generation form. Cancelling it preserved **Ready · 5 photos** and the football no-match result. Entering the existing H200's port-8001 URL passed the real model check and opened the prompt **football**, with no generated preview and the count still five. After cancelling review, choosing yes again skipped setup because generation was connected. Review was cancelled again; the final page shows the no-match choice with both model APIs connected. **Zero generation requests, collection changes or cloud resource mutations** occurred in this check. [Browser evidence](docs/evidence/creation-journey-2026-11-02.json).

All **37 Node checks passed**. New fixtures cover the generation-only model check, invalid URL/token/model and redirect handling, default/separate tokens, no re-index or repeated search on generation connection, explicit creation approval, retry/cancel and stale-response protection. A pending-search check prevents creation for the old query while a new embedding request is running. These fixtures use synthetic responses; the live check above independently verifies the real connection-to-review path. The earlier live Add/Discard run remains separate evidence; no new image was generated for this UI refinement.

## Search relevance correction

The old interface promoted rejected nearest neighbors into **Suggestions** when nothing qualified. A search for **football** therefore displayed city buildings and coffee beans despite their low scores. The old **0.35** visual cutoff also rejected useful synonyms such as **espresso**. Both interfaces now show qualifying matches only, or **No matching photos**. Rejected candidates are available as closed, scores-only diagnostics; they never fill the gallery. No model, embedding protocol or stored vector contract was changed.

A bounded real Endpoint run used **four image embeddings and twelve text embeddings**, with zero generation requests or cloud resource changes. Comparison used only image/text cosine, without titles or filenames. Image preparation used Pillow JPEG quality 86 as a close approximation of the browser canvas preprocessing; it was not byte-identical browser encoding.

| Query group | Observed visual retrieval |
| --- | --- |
| Coffee, espresso, coffee beans | Beans ranked first: **0.348**, **0.281**, **0.426** respectively |
| Mountain lake; a lake in the mountains | Lake ranked first: **0.408**, **0.416** |
| A city after dark; a duck wearing a scarf | Correct image ranked first: **0.360**, **0.467** |
| Football; soccer; a football match; dog; red car | Best scores were **0.136**, **0.125**, **0.157**, **0.111**, **0.080**; no qualifying image at the new default |

The **0.25** demo cutoff was selected from this same small sample. All seven positives qualified and all five absent-subject queries were rejected. This is a fitted sample and regression baseline, **not an independent benchmark or general accuracy guarantee**. The [raw evidence](docs/evidence/search-relevance-2026-11-02.json) and masked-metadata [regression fixture](tests/fixtures/search-relevance-scores.json) preserve that distinction. Larger collections require their own positive and absent-subject evaluation.

The actual updated browser was then reconnected to the existing H200 and re-indexed all **five** saved photos. **football** produced **zero result cards**; **coffee** showed Coffee beans first and the saved coffee-barista image; **espresso** showed the barista and Coffee beans, with the beans labelled **Visual match** rather than a filename match. The visual lake and city queries each returned only their intended photo; Back to collection restored all five. [Browser observations](docs/evidence/search-browser-2026-11-02.json). No image was generated or added during this correction. [No-match screenshot](docs/media/search-football-no-match.png) · [Synonym screenshot](docs/media/search-espresso-match.png).

New automated checks cover absent queries with distinct vectors, exact cutoff boundaries, a visual synonym without matching metadata, complete name evidence, no automatic generation, and returning to the collection. A limited-results regression also ensures a partially named rejected candidate cannot hide a qualifying visual match. The optional Python interface also exercises the actual search → empty → browse → synonym event journey. The full Python suite passed **68 tests and 13 subtests**, with one existing upstream Starlette deprecation warning; the hosted suite passed **28 Node checks**. These offline checks replay captured or synthetic responses and do not themselves establish model quality.

## Current browser-connected demo

The `hosted-demo/` app starts without an author's Endpoint credentials. Each visitor supplies the embedding and generation public URLs and Endpoint authentication for the complete demo. Search connects first; creation connects on the first creation action, using a separate token only when needed. Saved media lives in that browser's IndexedDB; vectors and credentials remain in tab memory. Search connection verifies the model and a 4096-dimensional probe, then re-embeds the collection. Creation connection verifies FLUX without re-indexing. The separate Python implementation below retains its persistent Qdrant collection.

| Current check | Observed result |
| --- | --- |
| Browser before connection | The actual local app displayed three starter photos. Clicking **coffee** opened the Endpoint form; verifying both models and indexing resumed that query. **Coffee beans** appeared as a match. The existing token was read privately from the console’s visible **View code** example and entered without printing or recording it. |
| Real connection API | Through the same local Node proxy, the existing H200 served the expected Qwen3-VL and FLUX models and a valid normalized 4096-dimensional probe. A deliberately invalid token returned **401** with a sanitized message. |
| Real indexing and retrieval | All three bundled photos were embedded. **coffee → coffee beans**, **a lake in the mountains → mountain lake**, and **a city after dark → city at night** each ranked the expected photo **first**. |
| Real generation API | One explicitly approved FLUX request returned a decoded **1024×1024 PNG** in **11.4 seconds**. Its image embedding succeeded; a descriptive text/image pair had cosine **0.665135**. This is one observation, not a latency or quality benchmark. |
| Complete live browser journey | Three starter photos were indexed; **coffee** returned Coffee beans and the visual lake query returned Mountain lake. Uploading an actual generated test PNG increased the browser collection **3 → 4**. A real robot-barista generation stayed unsaved at **four** photos; explicit **Add to collection** increased it **4 → 5**, and **robot barista** then retrieved it first. A separate real violet-glass-pineapple preview was discarded; the count remained **five**. Reloading and reconnecting retained and re-indexed all five photos. |
| Bounded model calls | The separate recorded proxy run used **nine real embedding requests** (including the readiness probe) and **one real generation**. The browser journey additionally exercised real connection probes, indexing/re-indexing, text searches, one upload embedding, **two real generations**, and one generated-image save embedding. No browser collection image was written into the older Qdrant collection. |
| Hosted-app fixtures | **37 Node checks passed**, covering the proxy and browser state contracts. They include wrong models/dimensions, rejected tokens, URL/redirect restrictions, bounded input/output, the create-first generation connection flow, explicit generation approval, in-flight duplicate handling, private unsaved previews, Save/Discard, reconnect, IndexedDB failure, the 20-photo concurrency limit, disconnect-during-storage races, absent-query abstention and synonym/name retrieval. These fixtures establish no general semantic quality. |
| Persistent implementation | **68 Python checks and 13 subtests passed** against real local Docker Qdrant, including Python/browser ranking parity, captured positive/absent-query scores and the actual optional-interface empty/browse event journey. One existing upstream Starlette deprecation warning. |
| Hosting artifact | The standalone Worker was built and its ESM export validated. A deployment archive was packaged with the Site manifest and embedded public assets. It contains no visitor credential or model weights. |
| Publication | **Not published.** Automatic approval review rejected transferring the short-lived Sites repository credential into the official publisher's tool input. Explicit user approval is pending. No live public URL is claimed. |

The actual API and browser evidence is in [`docs/evidence/byo-endpoint-api-2026-11-02.json`](docs/evidence/byo-endpoint-api-2026-11-02.json). Current screenshots and recordings are documented in [capture provenance](docs/media/CAPTURE.md). The complete new-UI browser journey used the real H200 through the local proxy. A deployed-host origin check remains pending; local browser and API tests do not establish a successful public deployment.

Search combines Qwen's visual/text similarity with whole-word evidence from descriptive names. It does not relabel cosine values as confidence or present a fixed cutoff as a fact about whether a photo matches. A complete descriptive-name match or cosine at least **0.25** qualifies for display. Rejected candidates remain outside the gallery, including when no result qualifies.

Browser photos are device-local and do not sync across devices. Clearing site data removes them. Credentials are not persisted; refreshing requires reconnecting and re-indexing. Generation is synchronous and has no durable exactly-once guarantee across Worker instances; uncertain responses require explicit review and warn that another request may create another image. No shared GPU token, paid GPU resource, external CPU server or domain was created for visitors. The user's existing H200 Endpoint was not stopped or changed.

## Earlier Python approval and review workflow: H200

Qwen3-VL Embedding and FLUX 3 Image Klein ran on Endpoint `REDACTED_H200_ENDPOINT_ID` in project `REDACTED_PROJECT_ID`. Only the local gallery was restarted for this change; the GPU Endpoint was left running as explicitly requested. A final safe identity/project/state read confirmed **RUNNING**. This was not a public-domain deployment.

| Check | Observed result |
| --- | --- |
| Short-query retrieval | **coffee** ranked the supplied **coffee beans** image first at **0.346449**. The old **0.35** display cutoff hid it. Ranked results now remain visible, with weaker results labelled; no model, embedding protocol or stored vectors were changed. |
| Search and Cancel | Searching and opening/cancelling prompt review left the generation ledger at **five jobs**, with no new generation. |
| Prompt approval | The browser changed the original dragon-teapot query to a longer editable description, then explicitly chose **Approve and generate**. The approved app input is recorded in the evidence. FLUX's internal prompt upsampler may expand it. |
| Private preview | A real generated image reached `ready`; the gallery still contained **eight images**. It was not embedded or indexed before Save. Anonymous preview access returned **403**; a different valid session returned **404**. |
| Explicit Add | **Add to collection** embedded/indexed the teapot and increased the count **8 → 9**. A later real text search ranked it **first**, with UI similarity **0.527** (rounded). |
| Explicit Discard | A second real generated preview was discarded. The private file was removed, no vector was added, and the collection remained at **nine images**. |
| Existing data | All five legacy automatically saved jobs and their gallery images remained intact. |
| Automated checks | **46 passed, 13 subtests passed** against real local Docker Qdrant; one existing upstream Starlette deprecation warning. Fixtures cover approval requirements, ownership/CSRF, private staging, idempotent generation and Save, retryable indexing and legacy records. They do not establish model quality. |
| Frontend checks | JavaScript syntax and fixture event-flow checks passed for edited prompt submission, duplicate clicks, preview preservation across searches, Save retry and Discard. Definite request rejections allow review/cancel; uncertain failures retain the same approval UUID for manual retry. |

The main README's **18-second** walkthrough uses actual browser captures of prompt review, generation, the unsaved preview, explicit Add and later retrieval. Waiting periods are shortened. Its poster is the unaltered unsaved-preview capture. See [capture provenance](docs/media/CAPTURE.md).

Sanitized live evidence is in [`docs/evidence/review-flow-h200-2026-11-02.json`](docs/evidence/review-flow-h200-2026-11-02.json). The small-library results are smoke tests, not calibrated relevance, latency or production-capacity benchmarks. The runtime used the same public-base/source-injection approach described below; this does not prove the separately published custom image's GPU boot path. Public hosting, larger-library quality and durable recovery of unsaved sessions remain unverified. Browser sessions are in memory; save or discard previews before leaving the session.

## Historical real shared-GPU run: RTX PRO 6000 Blackwell

The earlier automatic-generation edition completed two real FLUX generations and ended with five saved images. Its scoped RTX Endpoint was verified **STOPPED at 13:39:11 UTC (14:39:11 Europe/Berlin)** after that bounded run. This stopped state does not describe the current H200 Endpoint.

The test used Nebius Endpoint `REDACTED_RTX_ENDPOINT_ID`. Qwen3-VL Embedding and FLUX 3 Image Klein—including its separate prompt upsampler—ran on the same GPU with the cookbook's serialized gateways. The GPU reported **97,887 MiB** total memory.

**Deployment distinction:** the custom image passed its local build/import checks and was successfully pushed to a private registry, but was not the image booted for this GPU run. The live Endpoint booted the public `vllm/vllm-openai:v0.19.1` base, received the cookbook Endpoint sources as injected files, and installed the frozen **204-package** FLUX environment at startup. The verified push digest is `sha256:17f6d08f155237bd8bfbb871a09f5752986096de06c363bfb05e78767e010185`. This validates image publication and the source/runtime/model integration on the actual GPU separately; it does not establish the custom registry image's pull-and-GPU-boot path.

| Accepted check | Actual result |
| --- | --- |
| Managed API authentication | Both roles returned **401 without authentication** and **200 with the Endpoint token**. |
| Model identities | `Qwen/Qwen3-VL-Embedding-8B` and `black-forest-labs/flux-3-image-klein` were returned by their respective model APIs. |
| Generation | **Two succeeded jobs**, each producing one real **1024×1024** image. The first used the acceptance harness; the second used the actual browser UI. |
| First generation operation | **43.7092 s** in the serialized gateway. The observed web job took **50.229 s**, including save/embed/index and harness status polling. |
| Second generation operation | **19.8432 s** in the serialized gateway. This was a later operation in the same loaded runtime. |
| Generated-image retrieval | Both images ranked **first** on subsequent real text searches: **0.6995379** and **0.66394484** cosine similarity. The second observed search took **0.8112 s**. |
| Sampled startup memory peak | **73,509 MiB** whole-GPU memory used. |
| Sampled session memory peak | **82,689 MiB**, about **80.75 GiB**, from **1,298 samples** through the final check. |
| Memory at final observation | **15,198 MiB free**, about **14.84 GiB**; telemetry was available, not stale, with no recorded telemetry errors. |
| Final gallery | **Five images:** three supplied real photos and two generated images. |
| Cleanup | One scoped stop mutation; `STOPPED` verified at **2026-11-02T13:39:11.312314Z**. The deadline guard exited; the Endpoint configuration was preserved in its stopped state. |

Sanitized consolidated evidence, pinned revisions and relative runtime-source fingerprints are in [`docs/evidence/rtx-shared-gpu-2026-11-02.json`](docs/evidence/rtx-shared-gpu-2026-11-02.json). The smaller [first-pass record](docs/evidence/rtx-first-acceptance-2026-11-02.json) describes the initial empty-library test only. No Endpoint/Hugging Face tokens, private filesystem paths, raw startup logs or model weights are bundled.

**Measurement limits:** gateway durations include inference and boundary telemetry, not pure model-kernel time. Two observations are not a latency distribution or throughput benchmark. The memory figure is the maximum **sampled whole-device** value, approximately once per second plus operation boundaries—not a CUDA allocator high-water mark or a guarantee that no shorter spike occurred. The remaining memory does not establish capacity for another model, larger images, concurrent inference or larger workloads. All embedding/generation work was serialized.

### Photo-library and saved-result checks

The first no-match test started with an empty collection, created one image, saved it, embedded it with Qwen and retrieved it. The three supplied Pexels photos were then ingested in **2.632 s**, growing the collection **1 → 4**. Repeat ingestion reported **0 indexed, 3 skipped** in **0.042 s**. All four text searches returned the expected image first:

| Image | Cosine similarity | Observed request duration |
| --- | --- | --- |
| Coffee beans | 0.569435 | 0.794 s |
| Mountain lake | 0.5874336 | 0.813 s |
| City at night | 0.44402227 | 0.803 s |
| First generated image | 0.6995379 | 0.799 s |

This follow-up submitted no generation job. Its sanitized evidence is in [`docs/evidence/rtx-library-check-2026-11-02.json`](docs/evidence/rtx-library-check-2026-11-02.json). The later browser generation added the fifth image; a final text search retrieved it first. Cosine scores are rankings, not confidence percentages. This small library is not a general retrieval benchmark, and full host/database recovery was not tested in this session.

### Historical RTX browser preview

The earlier **24-second** walkthrough is retained as `docs/media/search-create-rtx-autosave.gif`, its MP4 counterpart and an actual full-page screenshot. It shows the older automatic-generation and saving flow. The main README now uses the current H200 approval/review capture described above. Both assemble actual browser frames with waits shortened; neither demonstrates real-time generation speed. See [capture provenance](docs/media/CAPTURE.md).

## Local checks and image build

The implementation uses the vLLM 0.19.1 embedding environment and an isolated official FLUX 3 reference environment, with a prompt upsampler, two HTTP gateways and a shared inference lock. Source/model revisions are in `endpoint/versions.json`.

| Check on 2 November | Evidence |
| --- | --- |
| Automated Python checks | Final suite after telemetry changes: **41 passed, 13 subtests**, covering the app, real local Docker Qdrant and Endpoint runtime/telemetry checks. One upstream Starlette test-client deprecation warning. The earlier authoring run had **33 passed**. These automated tests made no real model calls; live inference is recorded above. |
| Search → generate → index → search | Offline fixtures exercised the actual API, worker, image preparation, Qdrant writes, provenance and subsequent retrieval. Duplicate submissions did not generate twice; weak-match and historical video-only behavior were checked. These checks are separate from the live result above. |
| Public-demo boundaries | Session/CSRF/origin checks, job ownership, persistent generation budgets, optional password protection including Unicode credentials, private data paths and sanitized model-error messages were checked. |
| Web container | Built and started `deploy/web.Dockerfile` on local macOS arm64 Docker. Verified HTTP status/gallery, authentic logo, unprivileged UID 10001 and private-data boundary. Its uniquely named test collection, container and volume were removed. No model calls. |
| Public deployment configuration | Compose parsed using fake credentials. The actual Caddy 2.10.2 container validated the Caddyfile without opening public ports. No domain, certificate issuance or public deployment was tested. |
| Browser before the GPU test | Real gallery/API with clearly labelled offline services completed no-match generation, saved-result display, repeat-search retrieval and historical video-only exclusion. Mobile layout had no horizontal overflow at 390 px. The current interface is image-only. |
| Historical RTX preview provenance | The real-run `search-create-rtx-autosave.gif`/`.mp4` walkthrough and JPG show the second RTX generation and retrieval with pauses shortened. The older offline `search-create-preview.jpg` also remains historical. Current approval/review captures are documented above. See `docs/media/CAPTURE.md`. |
| Custom GPU base image | Built/import-checked `nebius-media-search-flux3:local` as **linux/amd64**, local image ID `sha256:21830496c3b490a59f9c6916ed7dd421bf2c92106641e49503c978ff45c7d4df`. Imports/version assertions passed for isolated FLUX, PyTorch **2.11.0 / CUDA 13.0**, and embedding **vLLM 0.19.1**. |
| Runtime source-overlay publication | Built `nebius-media-search-flux3:metrics` from that checked local base with the updated Endpoint sources, then successfully pushed this overlay image to the private registry: digest `sha256:17f6d08f155237bd8bfbb871a09f5752986096de06c363bfb05e78767e010185`. Neither custom image was GPU-booted; the live test used the public-base bootstrap described above. |
| Bundled photos | All three JPEGs matched the previously checked Pexels source hashes, decoded successfully and matched their recorded dimensions. Source/author/license attribution is in `examples/SOURCES.md`. No new download was needed. |

Model access, license conditions and GPU availability remain operator requirements. This repository contains the current cookbook and demo source. The independently published custom image has not been verified through a registry pull and GPU boot, and no deployed public app is claimed.

### Remaining deployment and workload checks

1. Verify the independently published custom image's registry pull-and-GPU-boot route. The source-injected bootstrap run is not that packaging test.
2. Deploy and test the intended public domain/HTTPS CPU host, persistent-volume recovery, request limits and optional password. Local gallery access is not a public-site launch.
3. Evaluate representative queries, threshold quality, output/content handling, larger inputs and public-load behavior separately. Two serialized generations do not establish production capacity or moderation quality.

The records below describe the earlier search-only version and remain historical.

---

## Historical authoring and Qwen-only execution: 29 October 2026

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
