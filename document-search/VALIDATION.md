# Standalone VM validation

**Implemented and locally verified; live GPU/VM execution is pending.** No test VM or disk has been created. The video's runtime is not yet measured.

## What ran

**71 local checks passed** on macOS / Python 3.14.4: 31 existing Endpoint checks, 12 data checks, 18 durable-state checks, nine CLI checks and one real-corpus integration scenario. The latter runs each phase in a new Python subprocess and requires the prepared corpus:

```bash
python3 scripts/prepare_vm_data.py
python3 -m unittest discover -s tests -q
```

The pinned input is **1,000 distinct Dolly reference passages / 219,197 words / 1,367,367 UTF-8 bytes / 1,970 chunks**. Document lengths range from 80 to 3,681 words (median 158.5; p95 491). [Corpus record](docs/vm-results/corpus.json).

| Offline phase | Complete documents | Reused documents | New chunk embeddings | Saved chunks |
| --- | ---: | ---: | ---: | ---: |
| Successful run first | 1,000 | 0 | 1,970 | 1,970 |
| Separate controlled stop | 600 | 0 | 1,206 | 1,206 |
| Fresh-process resume | 1,000 | 600 | 764 | 1,970 |
| Resume unfinished batch | 1,000 | 0 | 1,969 | 1,970 |
| Repeat completed run | 1,000 | 1,000 | 0 | 1,970 |

These scenarios used **eight-dimensional fixture vectors and local files**, not Qwen, Object Storage or a GPU. Their timings are **not embedding benchmarks**. The unfinished-batch test exits after one verified chunk save, before a document marker; recovery reuses it. Checks also reject corruption, incomplete writes and incompatible data/model/chunk/encoder settings. [Executed recovery record](docs/vm-results/offline-recovery.json).

Cached corpus preparation took 0.147 seconds in one local run. This excludes source download, VM startup and model loading; it does not estimate the video's workload.

## Live execution still needed

A small non-sensitive object was successfully written and read in a dedicated Nebius Object Storage prefix. Bucket ownership was checked in the selected project. That verifies S3 access only. Full S3 indexing, GPU embeddings, the real chess search and a controlled VM stop/start remain unverified because CLI authentication expired during an approval delay. No actual preemption occurred.

Run the README scenarios in order on the same pinned Qwen revision, with native 1,024-dimensional output, float16, batches of 16 and 160-word chunks. Save real source-linked search results. Record preparation, VM startup/restart, model startup, scanning, embedding and saving separately. The CLI reports these application phases and hardware; measure VM/bootstrap time externally. Completed reruns skip model loading.

L40S has **flat preemptible pricing**; this configuration does not validate changing spot prices or a price-policy stop. [Pricing](https://docs.nebius.com/compute/resources/pricing), [VM lifecycle](https://docs.nebius.com/compute/virtual-machines/preemptible).

## Video alignment

The architecture and successful-first / separate 600-plus-400 story are implemented. “Documents” here means real reference passages. Controlled interruption must not be called provider preemption. No “few minutes” benchmark is claimed. The video/script and unrelated work remain unchanged. Earlier Endpoint evidence is preserved in [ENDPOINT_VALIDATION.md](ENDPOINT_VALIDATION.md) and does not validate this VM route.
