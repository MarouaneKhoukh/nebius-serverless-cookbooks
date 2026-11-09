# Test results

Tested on 9 November 2026 in `eu-north1`.

| Component | Configuration |
| --- | --- |
| Deployment | Token-authenticated Serverless AI Endpoint, preemptible, following the market price |
| Image | `vllm/vllm-openai:v0.19.1` |
| Model | `Qwen/Qwen2.5-0.5B-Instruct` |
| GPU | One L40S, `gpu-l40s-a` / `1gpu-8vcpu-32gb` |
| Container disk | 500 GiB |

## Batch and resume checks

All 12 sample requests produced saved responses with valid category labels. The client processed three requests with `--limit 3`, then a second process reused those answers and completed the other nine. A third run reused all 12 answers and sent no new completion requests.

The [responses](docs/sample-results/responses.csv) and [summary](docs/sample-results/summary.json) are included. Valid labels do not imply correct classifications; the evaluation cookbook measures accuracy separately.

The system prompt was checked on three sample/training inputs before this run. The test covered client-process restarts. It did not include a GPU stop/start or a provider-initiated preemption.

## Local checks

```bash
python3 -m unittest discover -s tests -v
```

All 11 tests passed, covering CSV validation, saved-result integrity, interrupted responses, HTTP errors and HTML escaping. Python syntax and CLI help checks also passed. The local tests use fixtures; the sample results above came from the model.

## Price comparison

The quoted hourly rates were $0.7492 for preemptible compute and $1.5484 for regular compute, plus $0.048611 for the 500 GiB disk in either case. Rounded totals were **$0.80/hour preemptible** and **$1.60/hour regular**, before tax.

These are configuration quotes from the test date. They are not measured run costs. Rates can change, and startup, model loading and idle time are billable.

## Final resource state

The Endpoint was verified `STOPPED` after testing. The evaluation cookbook used the same Endpoint. Local results were retained; no storage bucket was created.
