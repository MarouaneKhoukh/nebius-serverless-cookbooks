# Validation

## Observed result

Two fresh **preemptible H100 Serverless AI Jobs** completed the real BANKING77 experiment on November 9, 2026. Both Jobs reached `COMPLETED` and released their GPU and temporary disk. The first deliberately stopped after publishing a full checkpoint at step 50. The second restored that checkpoint and completed step 100.

| Same 308 selected test questions | Correct | Accuracy | Macro F1 | Invalid answers |
| --- | --- | --- | --- | --- |
| Base Qwen3-4B-Instruct-2507 | 199 / 308 | 64.6% | 62.4% | 3 |
| LoRA adapter after 100 steps | 256 / 308 | 83.1% | 82.1% | 0 |

The model revision, system prompt, label list, test questions and greedy 32-token generation settings were identical before and after training. Evaluation used Transformers in BF16, batch 16. This controlled before/after comparison differs from the first cookbook's few-shot prompt and full test split; those scores should not be treated as the same experiment.

The actual lightweight report, predictions, data provenance and checkpoint evidence are in [docs/sample-results](docs/sample-results/). Adapter weights and full recovery checkpoints are run artifacts rather than committed preview files.

## Data and training scope

The loader selected **1,540 training questions** (20 per intent) and **308 test questions** (four per intent) from BANKING77's original splits, using seed 42. It excluded six source training rows whose normalized text appears in the official test split, plus four duplicate training texts, before sampling. Selected train/test normalized text overlap is zero. Exact source IDs, hashes and exclusion counts are saved in the result provenance.

The full source split contains 10,003 training questions. This run trained the balanced selection, not all source rows. Effective batch was 16; 100 optimizer steps finished at trainer epoch **1.0311688312**, approximately one pass over that selection. All 1,540 tokenized sequences were retained; lengths ranged from 435 to 505 tokens under the 1,024-token limit. Runtime logs show nonzero assistant training tokens and finite losses/gradients.

LoRA rank 8 updated **5,898,240 of 4,028,366,336 parameters** (0.1464%). Training logs reported peak allocated GPU memory of approximately **15.4 GiB**. This validates the tested H100 configuration; another GPU was not tested.

BANKING77 is a public human-authored benchmark, not production bank logs. Four test questions per intent make per-intent scores noisy. One seed and one bounded training schedule do not establish general quality, optimal hyperparameters or production performance. The test selection preceded inference and was not chosen from model scores. [Dataset attribution and license](data/SOURCE.md).

## Exact recovery evidence

- Original training session: `0c33f1600d47`, `resumed_from_step: 0`, checkpoint/global step **50**, `completed: false`.
- Fresh session: `c38020d885f8`, `resumed_from_step: 50`, final checkpoint `checkpoint-100-ec7bacfe01c9`, global step **100**, `completed: true`.
- Run contract SHA-256: `596258799d99d7e1b1b143634ce7c2cc1f7661266e449708801f9132e707babd`.
- The durable checkpoint proof records the adapter, optimizer, scheduler, RNG, trainer state, tokenizer and file hashes. The fresh Job verified the saved contract and restored a full-state checkpoint.
- `scripts/check_result.py --require-resume` passed on the downloaded 22,037,082-byte final ZIP; its 23 members passed ZIP CRC checks. The adapter and all 308 before/after input joins were verified. The original ZIP SHA-256 is `2f5559c93fc7e3e03100f159b0ccba09941c0638eefc926e74c7b904a5e1dbe0`.

This was a **planned stop across separate Jobs**. Natural mid-step preemption and recovery from it were not exercised. The tests establish this restoration path, not that no work will be lost between checkpoints.

## Integration and offline checks

The evaluation cookbook consumed the actual before/after CSVs and matched all 308 IDs. It reproduced 64.6% → 83.1%, with 195 questions both got right, 61 correct only after training, four correct only before training and 48 both missed.

21 standard-library checks passed after the real-data change. They cover deterministic data selection and separation, native label case/punctuation, invalid-label scoring, complete checkpoint validation, partial/corrupt checkpoint fallback, path safety, payload integrity, scoped CLI state and ambiguous-submit protection. Python syntax compilation passed. The compressed payload fits the CLI's total encrypted-file limit; source data is downloaded and checksum-verified on the VM rather than injected.

The tested worker payload hash was `11a88723b792af107eb08f0285dc0bff1dea2ed4639795c64f0c9a3a2aa37645`. The runtime reported Axolotl `0.16.0.dev0`, PyTorch `2.9.1+cu128`, Transformers `5.3.0` and PEFT `0.18.1`.

After the run, report-only CSS was adjusted to wrap long labels on narrow screens and the public preview was rendered again from the saved actual JSON. This presentation change made no model requests and changed no training or scoring settings. The original result ZIP was preserved.

## Cost and retained data

Training-stage wall time reported by the worker was approximately 155 seconds in the first Job and 162 seconds after restoration. These numbers exclude provisioning, image/model downloads and the base evaluation; they are not billable-duration or total-cost measurements. Check current preemptible pricing before running. Model loading and restarts consume paid compute time.

Both test Jobs are terminal. Object Storage remains available and billed separately until its objects are removed.
