# Validation

## Current execution scope

This simplified implementation has **not been rerun on a Nebius GPU VM**. The previous temporary VM was deleted; no new cloud resources were created. GPU startup, embedding, Object Storage saving and VM restart timings have not been measured for this revision.

## Local checks

The pinned corpus was prepared again using the current data code: **1,000 distinct passages, 219,197 words, 1,367,367 UTF-8 text bytes and 1,970 chunks**. Its source revision, stable IDs and manifest remain unchanged.

```bash
python3 scripts/prepare_vm_data.py
python3 -m unittest discover -s tests
```

**62 tests passed** on the current code, including the unchanged Endpoint tests.

Recovery checks use the real passages with deterministic fixture embeddings, local storage and a fresh Python process for each phase. They are not GPU or cloud benchmarks. They cover resuming finished documents, restarting an unfinished document, and refusing changed data or model settings.

| Current offline scenario | Saved documents | Reused documents | Newly saved chunks |
| --- | ---: | ---: | ---: |
| First invocation with a limit of 600 new documents | 600 | 0 | 1,206 |
| Same command in a fresh process | 1,000 | 600 | 764 |
| Resume after crashing mid-document | 1,000 | 10 | 1,955 |
| Repeat a completed run | 1,000 | 1,000 | 0 |

The crash left 10 complete documents containing 15 saved chunks. The unfinished document had no result object and was recomputed. [Current offline results](docs/vm-results/offline-recovery.json).

The session helper was checked with dummy credentials: it loads non-secret settings, activates the environment and prompts privately without writing or echoing credentials. README shell examples passed Bash syntax checks.

## Scope of the simpler pattern

One complete document is one JSON result object. Saving the object successfully makes the document reusable; unfinished documents are recomputed. A run manifest prevents mixing different input, model or chunk settings. Use one writer per prefix.

The S3 adapter's request behavior is checked with a fake client, not live Object Storage. The former per-chunk objects, completion markers and repeated read-backs are gone. Any storage-time improvement remains unmeasured on Nebius.

Earlier GPU records under [live/](docs/vm-results/live/) belong to the previous implementation and are historical only.
