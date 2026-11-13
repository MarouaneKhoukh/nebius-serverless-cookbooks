# Standalone VM validation

**Verified live on Nebius on November 13, 2026:** a complete 1,000-document run, a separate 600/400 recovery across a VM stop/start, an unfinished-batch failure and resume, and a source-linked semantic search. These were controlled tests, not actual provider preemptions.

## Live environment and input

One standalone **preemptible L40S AMD VM** in eu-north1: `gpu-l40s-d`, `1gpu-16vcpu-96gb`, 80 GiB SSD, Ubuntu 24.04 GPU image, Python 3.12.3. The observed GPU was NVIDIA L40S with 47,665,709,056 bytes of memory; the driver was 580.173.02. PyTorch was 2.7.1+cu126 and Transformers 4.51.3.

The test reused existing networking, an SSH credential, a bucket and S3 access. Fresh IAM account/key creation was reviewed against the linked documentation, not performed during this run.

The application used **Qwen/Qwen3-Embedding-0.6B** at revision `97b0c614be4d77ee51c0cef4e5f07c00f9eb65b3`: float16, last-token pooling, normalized 1,024-dimensional vectors, batches of 16 and paragraph-aware 160-word chunks. Inputs, embedding objects and document completion markers were stored in Nebius Object Storage, outside the VM. Separate prefixes held the successful, recovery and unfinished-batch runs.

The pinned Dolly selection contains **1,000 distinct reference passages / 219,197 words / 1,367,367 UTF-8 text bytes / 1,970 chunks**. These are passage-documents, not full Wikipedia articles. Document lengths: 80–3,681 words, median 158.5, p95 491; 433–21,189 text bytes, median 969, p95 3,088. [Provenance and license](vm/data/SOURCE.md), [corpus record](docs/vm-results/corpus.json), [live configuration and checks](docs/vm-results/live/summary.json).

## Executed results

| Live phase | Complete documents | Documents reused | Chunks reused | Chunks newly saved |
| --- | ---: | ---: | ---: | ---: |
| Full successful run first | 1,000 | 0 | 0 | 1,970 |
| Separate controlled stop at 600 | 600 | 0 | 0 | 1,206 |
| Fresh process after VM restart | 1,000 | 600 | 1,206 | 764 |
| Unfinished batch, before resume | 10 | — | 17 saved | — |
| Unfinished batch, fresh-process resume | 1,000 | 10 | 17 | 1,953 |
| Repeat an already complete run | 1,000 | 1,000 | 1,970 | 0 |

The console confirmed **Stopped**, then **Running**, and SSH returned a different Linux boot ID. A new process downloaded all four input files into a fresh local directory from Object Storage before resuming. It reused the saved 600 documents and completed the remaining 400. Recovery used the S3 run descriptor, chunk objects and completion markers, not a local progress file.

The unfinished-batch test hard-exited with code **75** after the 17th verified chunk save. Ten earlier documents remained complete; the next document had two of six chunks saved and no completion marker. A fresh process reused those 17 chunks and finished all 1,000 documents. Computed but unsaved work was eligible to run again. Every completed collection passed a separate integrity scan. Repeating the complete successful run loaded no model and made no new document embeddings.

The real query was: **“What happens in chess when a player has no legal moves but is not in check?”** The stalemate passage was **rank 3**, similarity **0.6505**, and says that stalemate results in a draw. The first two hits were chunks from a related check/checkmate passage. Results retain exact source-record links. This is one retrieval example, not a retrieval-quality benchmark. [Saved results](docs/vm-results/live/search.json), [readable HTML report](docs/vm-results/live/search.html), [stalemate source](https://huggingface.co/datasets/databricks/databricks-dolly-15k/blob/bdd27f4d94b9c1f951818a7da7fd7aeea5dbff1a/databricks-dolly-15k.jsonl#L6).

## Measured time

Seconds from this execution, rounded to two decimal places:

| Application phase | Model startup | Embedding | Saving | State scans | Application total |
| --- | ---: | ---: | ---: | ---: | ---: |
| Full successful run, cold model download | 77.88 | 6.83 | 60.67 | 12.72 | 160.28 |
| Separate first 600, warm model cache | 3.14 | 4.17 | 36.39 | 7.78 | 52.83 |
| Remaining 400 after VM restart | 37.30 | 3.87 | 24.00 | 22.10 | 88.20 |
| Resume unfinished batch | 3.12 | 6.65 | 62.83 | 13.48 | 88.31 |

Model startup includes imports and model initialization, including download when needed; embedding time excludes that measured startup. Saving includes writes, read-back validation and document markers. Scans validate existing/final state. Totals also include preparation inside the application and other small overheads. Separate `verify` commands add their own scan time. Small-object durability checks dominate much of this workload; these numbers are not a general GPU throughput benchmark.

Other measured phases:

- Source download, pinned corpus preparation and verification on the VM: **0.906 seconds**. Uploading the four prepared input files: **2.061 seconds**.
- Clone, virtual environment and pinned package installation: **231 seconds**.
- VM creation request to observed SSH host key: **73.97 seconds**. This observed interval includes console/operator work and polling; it is not pure boot time.
- Controlled stop request to observed **Stopped**: **46.73 seconds**. Restart request to observed SSH readiness: **57.82 seconds**. These include UI/polling overhead and are not capacity guarantees.
- Restoring inputs from Object Storage after restart: **1.468 seconds**. The VM retained its disk and downloaded model files, but processes and RAM were new; model startup was measured again.

[Raw live reports](docs/vm-results/live/) retain the exact counts, settings and timings. L40S uses **flat preemptible pricing**; this run does not validate changing spot prices, a pricing-policy stop or a natural capacity reclaim. [Compute pricing](https://docs.nebius.com/compute/resources/pricing), [VM lifecycle](https://docs.nebius.com/compute/virtual-machines/preemptible).

## Offline checks

**71 local checks passed** on macOS / Python 3.14.4: 31 existing Endpoint checks, 12 data checks, 18 durable-state checks, nine CLI checks and one real-corpus integration scenario. The scenario launches each phase in a new subprocess over the same 1,000 real passages. It covers both first-chunk failure and failure with completed documents already present. CLI checks also verified the report attribution after its footer update.

```bash
python3 scripts/prepare_vm_data.py
python3 -m unittest discover -s tests -q
```

Offline recovery used **eight-dimensional fixture vectors and local files**, not Qwen or Object Storage. Checks reject corrupt/missing results and incompatible data, model, chunking and encoder settings. [Offline recovery record](docs/vm-results/offline-recovery.json). Its timings are not embedding benchmarks.

## Scope and video alignment

The cookbook reproduces the video's standalone-VM, durable-storage, successful-first and separate 600-plus-400 recovery workflow. The 1,000 documents are licensed reference passages. The test interruptions must be described as controlled; L40S does not demonstrate dynamic price changes. No delay was added to stretch the example, and no earlier runtime estimate was reused as a benchmark.

The video/script and unrelated recipes remain unchanged. The earlier Endpoint route and evidence remain separate in [ENDPOINT.md](ENDPOINT.md) and [ENDPOINT_VALIDATION.md](ENDPOINT_VALIDATION.md); they do not validate the VM implementation. Cleanup status is recorded in [live/cleanup.json](docs/vm-results/live/cleanup.json).
