# Test results

Tested on 9 November 2026 in `eu-north1`, using a public benchmark rather than production support logs.

## Configuration

| Component | Tested configuration |
| --- | --- |
| Deployment | Finite Serverless AI Job on one preemptible L40S |
| Hardware | `gpu-l40s-d` / `1gpu-16vcpu-96gb`; 48 GB GPU memory, 16 vCPUs, 96 GiB host RAM |
| Temporary disk / timeout | 100 GiB / one hour per Job |
| Model | `Qwen/Qwen3-4B-Instruct-2507`, revision `cdbee75f17c01a7cc42f958dc650907174af0554` |
| Runtime image | `vllm/vllm-openai:v0.19.1` |
| Installed runtime | Python 3.12.13, vLLM 0.19.1, PyTorch 2.10.0+cu129, Transformers 5.5.4 |
| Generation | BF16; batch size 64; seed 42; temperature 0; 32 output tokens; constrained intent labels |
| Serving limits | Context 8,192 tokens; 16 concurrent sequences; GPU memory utilization 0.75 |
| Dataset | BANKING77, revision `57ec275d8078af65b7731c2a98be812d844a6d6b`; 3,080 test requests and 77 intents |

Frozen recipe hash: `497f00b05864f775226416903e967a2a0ee59055f9d5ce323bd8bb5ea73cb118`. Exports retain the input checksum, prompt, examples, configuration and contract.

## Quality checks

After inspecting the first pilot's errors, we revised the prompt once: one original training example per intent, without updating Qwen's weights. Both pilots used the same 128 requests.

| Approach | Correct / 128 | Accuracy |
| --- | --- | --- |
| Qwen, intent names only | 87 | 68.0% |
| Qwen, one training example per intent | 100 | 78.1% |
| CPU word/bigram Naive Bayes | 106 | 82.8% |

The revised pilot had **zero invalid labels and zero truncated outputs**. Qwen improved but did not beat the baseline. Qwen used 77 prompt examples; Naive Bayes fitted all 10,003 training examples. Their supervision budgets differ.

The prompt revision makes this an exploratory comparison, not a blind benchmark. The official test split has 3,079 unique normalized texts and six rows overlapping training. Splits are preserved; test labels are used only for scoring. Exports retain the CC BY 4.0 license and attribution.

## Full run

| Approach | Correct / 3,080 | Accuracy | Macro F1 |
| --- | --- | --- | --- |
| Qwen, one training example per intent | 2,340 | 76.0% | 75.3% |
| CPU word/bigram Naive Bayes | 2,420 | 78.6% | 77.7% |

All **3,080 distinct input IDs** have one prediction in the prepared order. Qwen had **zero invalid labels and zero truncated outputs**, with 740 incorrect predictions. The review queue contains 1,143 requests; 1,090 predictions differ from the baseline.

The CPU baseline scored higher and also completed the full local fit and prediction in about 1.2 seconds. For this dataset it is the practical starting point. This test does not establish a quality or cost advantage for the GPU approach.

The [verified result archive](docs/sample-results/result.zip), [predictions](docs/sample-results/predictions.csv), [mistakes](docs/sample-results/mistakes.csv) and [summary](docs/sample-results/summary.json) retain the observed output rather than hand-written examples.

## Recovery and runtime

The revised pilot deliberately exited after saving two batches, 128 requests, to Object Storage. A fresh Job reused those **128 rows** and generated the remaining **2,952 rows in 47 batches**. The retained 128 prediction records were compared field by field with the pilot export and matched exactly. The final archive passed `scripts/check_result.py --require-resume`, including input joins, order, checksums, provenance and license checks. This tests planned resumption. After the complete final archive was published, the platform reported `Preempted` and the resumed Job became `FAILED`. The archive still validated with all 3,080 rows. No new GPU was launched because no work remained. This establishes preservation of an already exported result; it does not establish recovery from a natural mid-batch reclaim.

Cold startup took about **eight minutes before the worker began**. Model loading then took **197.0 seconds**; two-batch generation took **5.26 seconds**. The **204.54-second** worker timer excludes provisioning, image pull and export; it is not billable duration.

The resumed worker spent **197.02 seconds loading the model** and **39.97 seconds generating its remaining batches**. Across the two exported worker attempts, generation took **45.23 seconds**, while worker time was **447.33 seconds**, excluding provisioning, image pull and export. Restarting repeats the cold start and model load.

An initial Intel L40S allocation failed for lack of capacity and was canceled. AMD L40S allocation succeeded. The allocation failure was not preemption.

## Pricing

The calculator quoted **$0.8836/hour** for the tested preemptible VM and **$1.8172/hour** for its regular counterpart. The 100 GiB disk added **$0.0097222/hour** in either case: approximately **$0.89/hour versus $1.83/hour**, before tax and retained Object Storage.

L40S is an exception to dynamic Spot pricing: Nebius bills preemptible L40S instances at the current flat rate. This experiment demonstrates preemptible batch execution and recovery, **not dynamic bidding or price-policy priority**. See the L40S footnote on [Nebius pricing](https://nebius.com/prices).

These are hourly quotes, not an invoice or measured experiment savings. Cold starts, retries and repeated model loading affect total cost. No billed total is claimed.

## Final resource state

The capacity-failed Intel allocation was verified `CANCELLED`; the zero-shot and revised pilots were `COMPLETED`. The resumed Job ended `FAILED` with reason code `Preempted` after exporting all results. Its underlying VM was subsequently absent from the Compute API (`NotFound`), confirming that GPU was released. The shared results bucket was retained; unrelated resources were left untouched.

## Local checks

The 94 offline checks passed, including a post-run launcher fix to display the safe `Preempted` reason and direct readers to validate an existing export before resubmission. The GPU worker and its frozen recipe hash were unchanged. Coverage includes input validation, prompt/test-label separation, durable batch integrity, fresh-worker reuse, incompatible-run rejection, launcher behavior and archive validation. These do not measure model quality or natural preemption.

```bash
python3 -m unittest discover -s tests -v
```
