# Validation

## Real input and observed results

The account-free evaluator was run on the bundled checksum-pinned prediction export from preemptible Nebius Serverless AI Jobs using Qwen3-4B-Instruct-2507. Source commit, URL, byte length and SHA-256 are recorded in `data/reference.json`. No new GPU was rented to rescore existing predictions.

All 3,080 input IDs, question text and expected labels were verified against the export's input/run contract. The evaluator reproduced:

| Method | Correct | Accuracy | Macro F1 |
| --- | --- | --- | --- |
| Qwen, 77 training examples in prompt | 2,340 / 3,080 | 76.0% | 75.3% |
| CPU word/bigram Naive Bayes, 10,003 training examples | 2,420 / 3,080 | 78.6% | 77.7% |

The paired comparison found 1,937 questions both models got right, 403 correct only for Qwen, 483 correct only for the CPU baseline and 257 both got wrong. Neither model produced an invalid label in this export. CSVs and the report in `docs/sample-results/` are generated from those actual predictions.

The official test split contains one duplicate normalized text and six rows with normalized text also present in training. The original splits are retained in this reference run. This is an exploratory published-benchmark comparison, not a new blind production evaluation. Different supervision budgets also prevent an equal-label-budget claim. [Dataset source](data/SOURCE.md).

## What ran where

Qwen inference and durable 128-row reuse across fresh preemptible Jobs were tested in the source batch-inference recipe. After the full result archive was saved, the platform reported `Preempted`; all 3,080 results remained valid. Those original results are reused here instead of repeating paid inference.

The optional fresh-prediction Job route carries the same proven worker, runtime, model and data pin in a self-contained directory. That copied route has source/payload checks; it has not been separately launched as a new evaluation Job. Scoring and paired comparison were executed locally on the actual export.

## Offline checks

Nine standard-library checks passed, covering actual reference score reproduction, macro F1, label case/punctuation, invalid/truncated outputs, candidate/input alignment, unknown/duplicate IDs, explicit subset comparisons, corrupt source-license rejection and raw-output independence from HTML. Syntax checks and the fresh-prediction payload size/integrity check passed.

No new model inference was requested during these checks.

## Cost and resource state

This evaluator performs no cloud calls and creates no cloud resources by default. The original source inference Jobs are terminal and their GPU was released. Hourly GPU quotes do not measure scoring costs or establish a quality/cost advantage for Qwen.
