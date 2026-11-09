# Test results

Tested on 9 November 2026 in `eu-north1`.

| Component | Configuration |
| --- | --- |
| Deployment | Token-authenticated Serverless AI Endpoint, preemptible, following the market price |
| Image | `vllm/vllm-openai:v0.19.1` |
| Model | `Qwen/Qwen2.5-0.5B-Instruct` |
| GPU | One L40S, `gpu-l40s-a` / `1gpu-8vcpu-32gb` |
| Container disk | 500 GiB |
| Test set | 30 fictional support requests, ten per category |

## Evaluation and resume checks

The model classified **24 of 30 requests correctly (80%)**. Six answers were incorrect and none were invalid.

| Expected category | Correct |
| --- | --- |
| Billing | 9/10 |
| Technical | 10/10 |
| Account | 5/10 |

The client evaluated five examples with `--limit 5`, then a second process reused those predictions and evaluated the other 25. A third run reused all 30 answers and sent no new completion requests. The [predictions](docs/sample-results/predictions.csv), [mistakes](docs/sample-results/mistakes.csv) and [scores](docs/sample-results/scores.json) are included.

A shorter system prompt was selected after three checks on sample/training inputs. The 30-example test CSV was unchanged. This small synthetic set demonstrates the scoring workflow; it is not an independent model benchmark.

The resume test covered client-process restarts. GPU stop/start and provider-initiated preemption were not tested.

## Local checks

```bash
python3 -m unittest discover -s tests -v
```

All 14 tests passed, covering the sample data, scoring, invalid answers, partial evaluations, saved-result integrity, HTTP errors and HTML escaping. Python syntax and CLI help checks also passed. Local tests use fixtures; the score above comes from model predictions.

## Price comparison

The quoted hourly rates were $0.7492 for preemptible compute and $1.5484 for regular compute, plus $0.048611 for the 500 GiB disk in either case. Rounded totals were **$0.80/hour preemptible** and **$1.60/hour regular**, before tax.

These are configuration quotes from the test date. They are not measured evaluation costs. Rates can change, and startup, model loading and idle time are billable.

## Final resource state

The Endpoint was verified `STOPPED` after testing. The batch-inference cookbook used the same Endpoint. Local reports were retained; no storage bucket was created.
