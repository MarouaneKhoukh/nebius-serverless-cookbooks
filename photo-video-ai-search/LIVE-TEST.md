# Live Nebius test: passed

On **29 October 2026**, this cookbook was run on the user's Mac with a real Nebius Serverless AI H100 Endpoint. It returned real text, image and native-video embeddings, stored five items in Docker Qdrant, and completed the bounded retrieval checks. The Endpoint was **stopped successfully** after testing.

## Environment and scope

- Endpoint: a new resource created only for this approved test. Account-specific resource identifiers are omitted from the published evidence.
- Serving image: `vllm/vllm-openai:v0.19.1`; model: `Qwen/Qwen3-VL-Embedding-8B`; context limit: 8192.
- GPU: regular `gpu-h100-sxm`, `1gpu-16vcpu-200gb`; 500-GiB disk; token-authenticated managed HTTPS access.
- Local Python 3.12.14, pinned dependencies, FFmpeg 8.1.1; real `qdrant/qdrant:v1.20.0` Docker service and persistent named volume.
- Create submitted **14:09:03 CET**; confirmed stopped **14:18:53 CET**. These are lifecycle timestamps, not measured GPU utilization or an invoice.
- Exactly **10 successful embedding requests**: 5 text, 3 image and 2 video. Every response contained **4096 dimensions**. Credentials were kept in process memory and excluded from saved evidence.

## Ingestion and retrieval

Initial sample ingestion indexed **3 images + 2 clips = 5 points**. The clips cover **0–8 seconds** and **8–12 seconds** of the sample animation. Repeating ingestion skipped all five and made **zero additional embedding requests**.

| Query | Filter | First result | Cosine score | Check |
| --- | --- | --- | --- | --- |
| red circle | Images | synthetic_red_circle.png | 0.415 | Pass |
| blue square | Images | synthetic_blue_square.png | 0.463 | Pass |
| green triangle | Images | synthetic_green_triangle.png | 0.481 | Pass |
| a moving red circle | Videos | Clip 0–8 seconds | 0.544 | Pass |

The video query was submitted through the gallery UI. It ranked the red-circle clip above the 8–12 second green-triangle clip, whose displayed score was **0.312**. Video scores above are rounded values observed in the UI; full precision image scores and machine-readable checks are retained in [`LIVE-TEST.json`](LIVE-TEST.json).

All five thumbnails and all three prepared images returned HTTP 200. Both video byte-range checks returned HTTP 206. The browser loaded durations of 8 and 4 seconds and actual playback was observed.

The live browser test used a temporary loopback app at port 8081 with the credential held in memory. That process was stopped after validation. The normal gallery remains at **http://127.0.0.1:8080/** with the five stored items; Docker Qdrant and prepared media remain local.

## What the result establishes

The model/API request format, real base64 image/video decoding, 4096-dimensional output, Qdrant indexing, modality-filtered retrieval, repeat-ingestion skipping, local previews and playback worked for the shipped small sample. The 20 automated local tests also passed against Docker Qdrant before this run.

This is a smoke test, not a general media-search benchmark. The synthetic shapes contain printed labels, the searches used image/video filters, and the uploaded assets are tiny. It does not establish unfiltered cross-modal ranking quality, real-photo recall, audio understanding, precise moment detection, large-library performance, maximum gateway payload size or restart persistence of this Docker container. Earlier disk/native-service persistence checks remain documented separately in [`VALIDATION.md`](VALIDATION.md).

The temporary live-test wrapper blocked any further browser search after the approved 10-request budget. No extra embedding request was sent. That limit belonged to the test harness, not to the cookbook application.

## Resource state and cost

`endpoint stop` returned success, and a separate state check confirmed **STOPPED**. The Endpoint configuration remains for a deliberate later start; the GPU and endpoint disk are released. Starting it again resumes billing and requires model startup. New semantic searches need that running Endpoint and its token; browsing/playing stored media is local.

The reviewed list-rate estimate was approximately $4.55 per running hour before tax: $4.50/hour compute plus approximately $0.05/hour for standard 500-GiB network SSD storage. No billing invoice or project-specific discount was inspected. See [Compute pricing](https://docs.nebius.com/compute/resources/pricing) and [Serverless stopped-resource billing](https://docs.nebius.com/serverless/pricing-quotas).
