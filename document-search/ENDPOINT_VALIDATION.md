# Validation

Tested on 9 November 2026 in `eu-north1` using the real Python documentation corpus.

| Component | Recorded configuration |
| --- | --- |
| Deployment | Preemptible Serverless AI Endpoint |
| Model | `Qwen/Qwen3-Embedding-0.6B`, native 1,024-dimensional output |
| Runtime | `vllm/vllm-openai:v0.19.1`, pooling runner |
| Compute | One L40S, `gpu-l40s-a` / `1gpu-8vcpu-32gb` |
| Temporary disk | 500 GiB |
| Input | 55 Python 3.13.9 reference documents, 2,138 chunks of up to 160 words |
| API batches | 16 document chunks per request |

The serving configuration names the model without pinning its weights revision. Recorded vectors therefore describe this deployment, rather than promising bit-for-bit equality across future model updates.

## Corpus and query provenance

The official plain-text archive SHA-256 is `2522c3aee3c6617e99f7db5e43356471108739e35fe8a97b5d10da33832ff141`. The selected source documents total 2,304,869 bytes. Preparation verified the archive, individual files and retained PSF license against [the source manifest](data/source.json). A second preparation run downloaded the official archive into an empty cache, verified the same checksum and prepared all 55 documents successfully.

The twelve questions are original text from the Python Library and Extension FAQ. FAQ answers are excluded from the indexed corpus. Expected reference modules were curated from those answers and restricted to this collection. These are source-level diagnostic checks, not independently judged passage relevance or generated-answer scores. Different retrieved reference documents can also be useful.

## Indexing and reuse

The first client process saved **64 chunks**. A fresh process reused those records and embedded the remaining **2,074**, producing **2,138 complete vectors**. All vectors were finite, normalized and 1,024-dimensional, with aligned source metadata.

The offline result checker passed against the actual prepared documents and complete saved index, including every input ID, source-text join, vector/metadata export order, corpus fingerprint, retained license and twelve query-check records.

A third client run reused all **2,138 chunks**, reported zero remaining work and sent no new document-embedding requests.

Index fingerprint: `aaf68ca7adc224b3273334539aa51e161c49adf209fb5f03e69f2e438de7af78`.

This tested continuation across client processes. It did not test recovery from an actual GPU reclaim or GPU stop/start during indexing.

## Retrieval checks

| Method | Expected source first | Expected source within five chunks |
| --- | --- | --- |
| Qwen embedding similarity | 9/12 | 11/12 |
| BM25, CPU | 8/12 | 10/12 |

Both methods searched the same 2,138 chunks. The question “How do I copy a file?” returned `library/shutil.txt` first with Qwen. For “Is there an equivalent to C's onexit() in Python?”, Qwen returned `library/atexit.txt` first.

The binary-data question illustrates the limits of this scoring: the expected reference list names `struct` and `array`, while both methods returned the also-useful `io` reference first. The reported counts are source-check results, not a general accuracy score.

The local BM25 index and twelve checks took about **0.20 seconds on the author's Mac**. This is local CPU time, not a cloud or billing measurement. No cloud embedding-throughput measurement is claimed.

The [recorded reports](docs/sample-results/) include every query's returned passages and provenance. Their table wrapping was adjusted offline after the run; vectors, ranked results and metrics were unchanged. The full vector working directory was retained locally; the public repository contains a lightweight report sample.

## Offline checks

The **31 offline checks pass**. They cover archive/document checksums, retained license, cache reuse, unsafe paths, changed inputs, native vector validation, API response ordering, partial-batch recovery, source-level scoring, export alignment, HTML escaping and offline report rendering without changing saved vectors or results. Fixture vectors are separate from the actual model results above.

```bash
python3 -m unittest discover -s tests -q
```

## Pricing and final resource state

The calculator quoted **$0.7492/hour** for the preemptible VM and **$1.5484/hour** for its regular counterpart. A 500 GiB network SSD disk added **$0.048611/hour** in either case: approximately **$0.80/hour versus $1.60/hour**, before tax.

These are configuration quotes, not measured indexing costs or invoices. Model loading, idle time and interruptions affect the total. L40S currently has a flat preemptible rate; this test does not demonstrate dynamic spot-price bidding. [Nebius pricing](https://nebius.com/prices).

The Endpoint was verified **STOPPED** at the end of testing. Local vectors and reports were retained separately from its GPU and temporary disk.
