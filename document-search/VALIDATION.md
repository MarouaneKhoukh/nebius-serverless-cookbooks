# Test results

Tested on 9 November 2026 in `eu-north1`.

| Component | Configuration |
| --- | --- |
| Deployment | Token-authenticated Serverless AI Endpoint, preemptible, following the market price |
| Image | `vllm/vllm-openai:v0.19.1` |
| Model | `Qwen/Qwen3-Embedding-0.6B`, pooling runner |
| GPU | One L40S, `gpu-l40s-a` / `1gpu-8vcpu-32gb` |
| Container disk | 500 GiB |
| Input | Six fictional documents, producing six chunks |

## Indexing and search checks

All six chunks produced finite, normalized **1,024-dimensional** vectors with matching metadata IDs. The client first indexed two chunks using `--limit-chunks 2`. A second process reused them and indexed the other four. A third run reused all six and sent no new document-embedding requests.

Three searches returned the expected document first:

| Query | First result | Cosine similarity |
| --- | --- | --- |
| Can I claim back the cost of a work trip? | `travel-expenses.txt` | 0.5618 |
| May I work from home? | `remote-work.txt` | 0.5652 |
| How do I reset my password? | `account-access.txt` | 0.7237 |

The [saved results](docs/sample-results/) include vectors, metadata, the completed manifest, query results and HTML reports. The final report shows the password-reset search. These examples check the small sample collection; they do not establish general retrieval quality. Cosine similarity is not a relevance probability.

The resume test covered client-process restarts. GPU stop/start and provider-initiated preemption were not tested.

## API compatibility

The pinned vLLM runtime rejects a `dimensions: 1024` override for this model with HTTP 400. The client omits that field and checks the model's native 1,024-dimensional output instead.

## Local checks

```bash
python3 -m unittest discover -s tests -v
```

All 13 tests passed, covering chunk identity and size, API response validation, vector dimensions and normalization, saved-result matching, partial batches, aligned exports, query handling and HTML escaping. Syntax and CLI help checks also passed. Local test vectors are fixtures; the saved sample results above came from Qwen.

## Price comparison

The quoted hourly rates were $0.7492 for preemptible compute and $1.5484 for regular compute, plus $0.048611 for the 500 GiB disk in either case. Rounded totals were **$0.80/hour preemptible** and **$1.60/hour regular**, before tax.

These are configuration quotes from the test date, not measured embedding costs. Rates can change, and startup, model loading and idle time are billable.

## Final resource state

The Endpoint was verified `STOPPED` after testing. Local vectors, metadata and reports were retained; no storage bucket was created.
