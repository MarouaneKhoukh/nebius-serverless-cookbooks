# Validation

## Live Serverless execution

On **November 13, 2026**, five fresh **preemptible Serverless Jobs** exercised indexing and recovery through Nebius Object Storage. Each used one **NVIDIA L40S** and `pytorch/pytorch:2.7.1-cuda12.6-cudnn9-runtime`; the runtime reported PyTorch **2.7.1+cu126** and CUDA **12.6**.

The executed source was commit [`3e602fb0877de0b0c6ed72ab199201b4d83ece32`](https://github.com/MarouaneKhoukh/nebius-serverless-cookbooks/tree/3e602fb0877de0b0c6ed72ab199201b4d83ece32/document-search), supplied through `RECIPE_REF`. This PR is not merged yet; the README's `main` default is intended for use after merge.

**Qwen3-Embedding-0.6B** was pinned to revision `97b0c614be4d77ee51c0cef4e5f07c00f9eb65b3`, using float16, last-token pooling, normalized **1,024-dimensional** vectors, batches of **16** and **160-word** chunks. The pinned input contains **1,000 distinct Dolly reference passages**, **219,197 words**, **1,367,367 UTF-8 text bytes** and **1,970 chunks**. These are passages, not full articles. [Corpus record](docs/job-results/corpus.json).

| Live attempt | Documents complete | Documents reused | Documents newly saved | Chunks reused | Chunks newly saved |
| --- | ---: | ---: | ---: | ---: | ---: |
| First Job, limited to 600 new documents | 600 | 0 | 600 | 0 | 1,206 |
| New Job, same prefix and limit | 1,000 | 600 | 400 | 1,206 | 764 |
| Separate uninterrupted full run | 1,000 | 0 | 1,000 | 0 | 1,970 |
| Fresh Job after the controlled crash | 1,000 | 10 | 990 | 15 | 1,955 |

The second container prepared the same pinned input, read the saved document results from Object Storage and skipped all 600 completed documents. Both reports have the same run fingerprint. One complete result object makes each document reusable; unfinished documents have no result object and must run again. These were deliberately separate attempts, not an observed provider preemption. [First report](docs/job-results/live/first-600.json), [resume report](docs/job-results/live/resume-400.json).

The optional crash test exited with code **75** after **17 computed chunks**. Reading the actual S3 results afterward confirmed **10 complete documents containing 15 saved chunks**; the unfinished document had no saved result. A new Job reused those results and completed **990 documents / 1,955 chunks**. The separate uninterrupted run also completed all 1,000 documents. [Full run](docs/job-results/live/full-run.json), [crash readback](docs/job-results/live/crash-after-stop.json), [crash resume](docs/job-results/live/crash-resume-990.json).

## Measured phases

Seconds measured inside the containers, rounded to two decimal places:

| Phase | First 600 | Remaining 400 | Full 1,000 | Crash resume 990 |
| --- | ---: | ---: | ---: | ---: |
| Source and Python dependency setup | 11.31 | 10.16 | 10.62 | 10.23 |
| Pinned data preparation | 0.84 | 1.07 | 0.89 | 0.84 |
| Model startup | 37.97 | 39.18 | 36.82 | 37.80 |
| Embedding | 12.74 | 8.44 | 20.60 | 20.56 |
| Saving complete document results | 5.52 | 3.64 | 9.60 | 9.38 |
| State scanning | 0.05 | 2.91 | 0.04 | 0.09 |
| Index application total | 56.55 | 54.45 | 67.46 | 68.22 |

The index total includes model startup, embedding, saving, scanning and small application overheads. It excludes source/dependency setup, data preparation, the later search and output uploads. The abrupt-crash attempt produced no final index report; its log records only **10.45 seconds of setup** and **1.14 seconds of data preparation** before indexing. No complete model, embedding or saving timing is claimed for that attempt. [Crash log](docs/job-results/live/crash-log.txt).

Creation to first observed **Running** ranged from **279.209 to 331.459 seconds** across these attempts. Those coarse status polls include observation delay and can include work already performed; they are not exact provisioning, image-pull or cold-start benchmarks. [Lifecycle observations](docs/job-results/live/lifecycle.json). All timings describe these executions, not runtime promises.

L40S has **flat preemptible pricing**. The required `--follows-spot-price` setting is not evidence of a changing market price or a pricing-policy stop. [Compute pricing](https://docs.nebius.com/compute/resources/pricing).

## Search result

The completed Job queried: **“What happens in chess when a player has no legal moves but is not in check?”** The stalemate passage was **rank 3**, similarity **0.6506**, and explains that stalemate results in a draw. The first two hits were check/checkmate passages. Source links and the ranked passages are preserved in [search.json](docs/job-results/live/search.json) and the [HTML report](docs/job-results/live/search.html). This is one executed query, not a retrieval benchmark.

## Local checks

**67 local tests passed**, including the unchanged Endpoint tests:

```bash
python3 -m unittest discover -s tests
```

Recovery tests use the real passages with deterministic fixture embeddings, local storage and fresh Python processes. They verify the 600/400 resume, reuse of completed documents after a mid-document crash, and refusal to mix changed input or model settings. Bootstrap tests mock downloads, package installation, model execution and storage; they check the document limit, report uploads, complete-only search and the controlled crash exit code. S3 fake-client tests cover safe provider error codes, including `AccessDenied` and `NoSuchBucket`, without credential-bearing details.

The separate input-transfer commands were removed. Each new Job prepares the same pinned public input and writes its finished results directly to Object Storage. No actual Nebius preemption was demonstrated.

## Cleanup

All five Jobs reached terminal states: **four Completed** and the controlled crash **Failed**, with **zero active instances** and no remaining test compute. The temporary secret was deleted; its metadata lookup returned `NotFound`. The existing S3 access key, bucket and durable results were retained. [Cleanup record](docs/job-results/live/cleanup.json).
