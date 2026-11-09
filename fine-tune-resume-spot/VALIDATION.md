# Test results

Tested on 9 November 2026 in `eu-north1` using two separate preemptible Serverless AI Jobs.

| Component | Configuration |
| --- | --- |
| Image | `docker.io/axolotlai/axolotl:main-20260309-py3.11-cu128-2.9.1` |
| Model | `Qwen/Qwen2.5-0.5B-Instruct` |
| Model revision | `7ae557604adf67be50417f59c2c2f167def9a775` |
| GPU per Job | One H100, `gpu-h100-sxm` / `1gpu-16vcpu-200gb` |
| Storage and memory | 500 GiB temporary disk, 16 GiB shared memory |
| Job settings | One-hour timeout, following the market price |
| Dataset | 120 training examples and 30 separate test examples |
| Runtime | Axolotl `0.16.0.dev0`, PyTorch `2.9.1+cu128`, Transformers `5.3.0`, PEFT `0.18.1` |

The launcher used its compressed payload. The training, configuration and test-file hashes match the saved run contract. The test CSV is the same one used in the evaluation cookbook.

## Checkpoint recovery

1. The first Job trained to step **10**, published a complete checkpoint and ended at the planned boundary.
2. The recovery archive contained 23 files, including adapter weights, optimizer, scheduler, RNG and trainer state. The saved trainer step was 10.
3. A new Job restored step **10**, saved checkpoints at steps **20** and **30**, and finished the original 30-step schedule.
4. The final `result.zip` included the adapter, predictions, report, configuration and recovery records. It was downloaded through the console and passed `scripts/check_result.py --require-resume`.

This tested a planned checkpoint stop followed by recovery in a new Job. Provider-initiated preemption was not observed.

## Before and after fine-tuning

Both evaluations used the same 30 test examples, model revision, system prompt and generation settings: seed 42 and a maximum of 16 new tokens.

| Model | Correct | Accuracy | Invalid answers |
| --- | --- | --- | --- |
| Base model | 24/30 | 80.0% | 0 |
| LoRA adapter | 28/30 | 93.3% | 0 |

The [saved results](docs/sample-results/) include the predictions, report, run contract and checkpoint record. Adapter and checkpoint binaries are not included in the repository. These scores describe the included synthetic examples, not general model quality.

The Axolotl commands took approximately 54.1 seconds in the first Job and 64.5 seconds in the resumed Job. Those timers exclude provisioning, image pull and the separate evaluations, so they are not billable-duration measurements.

## Local checks

```bash
python3 -m unittest discover -s tests -v
python3 -m compileall -q src scripts
python3 src/train.py --help
```

All 20 tests passed on Python 3.14.4 for macOS. They cover full-state checkpoint restoration, incomplete/corrupt checkpoints, run matching, path validation, dataset separation, scoring and the CLI launcher's payload and resubmission handling. Syntax and help checks passed.

## Price comparison

The quoted H100 rate was $0.79/hour for preemptible compute. Adding $0.048611/hour for the 500 GiB disk gave a rounded total of **$0.84/hour**, compared with **$4.55/hour** for the regular configuration, before tax.

These are configuration quotes from the test date, not measured training costs. Rates can change, and provisioning and model loading are billable.

## Final resource state

Both Jobs reached `COMPLETED`. The bucket and its checkpoints were retained and continue to have a separate storage lifecycle.
