# Earlier search-only GPU test

This test, recorded on 29 October 2026, covers the previous Qwen-only gallery with images and video. The current search-and-create app is covered in [VALIDATION.md](VALIDATION.md).

## Configuration

- Qwen/Qwen3-VL-Embedding-8B, served by `vllm/vllm-openai:v0.19.1`, with an 8192-token context limit.
- One regular H100, 500 GiB disk and token-authenticated managed HTTPS.
- Local Python 3.12.14, FFmpeg 8.1.1 and Docker Qdrant 1.20.0 with a persistent named volume.
- Ten successful embedding requests: five text, three image and two video. Each response contained 4096 dimensions.

## Results

Ingestion saved three images and two clips. Repeating ingestion skipped all five items and made no additional embedding requests.

| Query | Filter | First result | Cosine similarity |
| --- | --- | --- | --- |
| red circle | Images | Synthetic red circle | 0.415 |
| blue square | Images | Synthetic blue square | 0.463 |
| green triangle | Images | Synthetic green triangle | 0.481 |
| a moving red circle | Videos | Clip covering 0–8 seconds | 0.544 |

The image and thumbnail requests succeeded. Video byte-range requests returned HTTP 206, and playback of the eight- and four-second clips was observed in the browser. Full results are in [LIVE-TEST.json](LIVE-TEST.json).

The Endpoint was stopped after testing, and a separate state check confirmed `STOPPED`. The reviewed hourly quote was approximately $4.55 before tax, including the 500 GiB disk; no invoice was measured.

These checks establish the request format, small-sample ingestion, filtered retrieval and media playback. The synthetic shapes contain printed labels. This test does not establish real-photo quality, unfiltered cross-modal retrieval, scale, maximum gateway payload size or recovery of the current two-model deployment.
