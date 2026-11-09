---
title: Fine-Tune Qwen on Real Banking Questions
category: training
type: cookbook
runtime: Nebius Serverless AI Job
frameworks: [Axolotl, PEFT]
keywords: [preemptible, fine-tuning, qwen, lora, checkpoint, banking77]
difficulty: intermediate
---

<img src="docs/brand/nebius-logo.svg" alt="Nebius" width="140">

# Fine-Tune Qwen on Real Banking Questions

Train a LoRA adapter for **77 banking intents** using real, human-authored BANKING77 questions. Save training state after 50 steps, restore it in a fresh Job and finish at step 100. Compare the base model and adapter on the same 308 test questions, then download the adapter and report.

**Nebius Serverless AI runs Axolotl on a cloud GPU.** Preemptible GPUs offer lower-priced capacity that Nebius can reclaim. Full checkpoints in Object Storage let another Job continue from saved training progress.

The bounded default uses **1,540 training questions: 20 per intent**, plus **308 test questions: four per intent**. These are selected from the original train/test splits; the loader excludes shared normalized text. With effective batch 16, 100 steps are about one pass over the selected training set.

## What you need

- macOS or Ubuntu, Git and Python **3.10+**. No local GPU, Docker or extra local Python packages.
- A billing-enabled Nebius project in **eu-north1**, permission to create Jobs and use Object Storage, and quota for one **preemptible H100**.

## 1. Get the files and sign in

```bash
git clone https://github.com/MarouaneKhoukh/nebius-serverless-cookbooks.git
cd nebius-serverless-cookbooks/fine-tuning-with-checkpoints
```

Run all commands from this directory. Install the Nebius CLI if needed:

```bash
curl -sSL https://artifacts.nebius.cloud/cli/install.sh | bash
```

Open a new terminal and return here. Use CLI **0.12.303+**; run `nebius update` if yours is older. Copy your project ID from the [console](https://console.nebius.com), replace the placeholder and complete browser sign-in:

```bash
export AI_AGENT="${AI_AGENT:-cookbook}"
nebius version
export PROJECT_ID="YOUR_PROJECT_ID"
nebius profile create cookbook --parent-id "$PROJECT_ID"
nebius profile activate cookbook
nebius iam whoami
```

Already signed in to this project? Activate that profile instead of creating `cookbook`.

Choose a **subnet**, the Job's network, with outbound internet access for model downloads. Copy its `metadata.id`:

```bash
nebius vpc subnet list --parent-id "$PROJECT_ID" --format json
export SUBNET_ID="YOUR_SUBNET_ID"
```

If none exists, create a network and subnet:

```bash
export NETWORK_ID="$(nebius vpc network create --parent-id "$PROJECT_ID" --name cookbook-network --format jsonpath='{.metadata.id}')"
export SUBNET_ID="$(nebius vpc subnet create --parent-id "$PROJECT_ID" --name cookbook-subnet --network-id "$NETWORK_ID" --format jsonpath='{.metadata.id}')"
```

New networks have a default internet route. Use an approved subnet if your company manages networking.

## 2. Inspect the data and choose storage

```bash
python3 scripts/prepare_data.py
```

This downloads checksum-verified BANKING77 sources and writes `data/prepared/train.jsonl`, `test.csv` and `provenance.json`. Original question text, label spelling and source IDs are retained. The Job prepares the same files on its VM; you don't upload these local copies.

Create a private bucket in this project with a unique name, or reuse an existing bucket's ID:

```bash
python3 scripts/job.py create-bucket \
  --project-id "$PROJECT_ID" --name "YOUR_UNIQUE_BUCKET_NAME" --yes

export BUCKET_ID="YOUR_BUCKET_ID"
export RUN_ID="banking77-lora"
```

Replace `YOUR_BUCKET_ID` with the returned ID. Keep the bucket and run ID for resumption. Retained storage is billed separately; use a new run ID when inputs or settings change.

## 3. Train to the first checkpoint

The configuration uses **Qwen/Qwen3-4B-Instruct-2507**, pinned revision `cdbee75f17c01a7cc42f958dc650907174af0554`, the existing Axolotl image, one **H100**, a **500 GiB temporary disk** and a **one-hour timeout per Job**. The public model needs no Hugging Face token. LoRA settings are in `config/train.yaml`; dataset selection is in `config/data.json`.

Check the current H100 rate under **Serverless AI → Jobs → Create job → Preemptible**. The helper follows the changing spot price without a cap; model loading and restarts use paid time. To use a cap, create a [pricing policy](https://docs.nebius.com/signup-billing/manage-pricing-policy) for `gpu-h100-sxm` and add `--spot-pricing-policy-id "YOUR_POLICY_ID"` to both submit commands. A cap doesn't guarantee capacity.

```bash
python3 scripts/job.py submit \
  --project-id "$PROJECT_ID" --subnet-id "$SUBNET_ID" \
  --bucket-id "$BUCKET_ID" --run-id "$RUN_ID" \
  --stop-after-step 50 --dry-run

python3 scripts/job.py submit \
  --project-id "$PROJECT_ID" --subnet-id "$SUBNET_ID" \
  --bucket-id "$BUCKET_ID" --run-id "$RUN_ID" \
  --stop-after-step 50 --yes

python3 scripts/job.py wait --timeout 3600
python3 scripts/job.py logs --tail 30
```

Keep the Job ID. The first Job evaluates the base model, trains and publishes a full checkpoint at step **50**, then exits deliberately. Look for `checkpoint_published` and `recipe_finished` with `completed: false`. Training still has 50 steps left.

## 4. Restore in a fresh Job

```bash
python3 scripts/job.py resume --dry-run
python3 scripts/job.py resume --yes
python3 scripts/job.py wait --timeout 3600
python3 scripts/job.py logs --tail 30
```

Keep `.state/job.json`, the original files, inputs and configuration. Resume keeps the same bucket/run and restores the adapter, optimizer, scheduler, random-generator and trainer state. Look for `resumed_from_step: 50`, `global_step: 100` and `completed: true`.

After an actual interruption, wait for the old Job to be terminal before resubmitting. An unfinished checkpoint may be skipped, so some work can repeat. If no valid checkpoint exists, use a new run ID and submit again. A wait timeout alone doesn't stop compute.

## 5. Download the adapter and inspect results

In **Object Storage → your bucket → your run ID**, download `result.zip` to Downloads. Validate and extract into a new directory:

```bash
python3 scripts/check_result.py "$HOME/Downloads/result.zip" --require-resume
python3 -m zipfile -e "$HOME/Downloads/result.zip" results
```

Open **`results/report.html`**. Check **100/100 steps**, restoration from **step 50**, and before/after predictions on the same 308 questions. Raw scores and per-intent metrics are in `before.json` and `after.json`; the corresponding CSVs work with your own analysis or UI. The adapter is in `results/adapter/`. Full recovery checkpoints remain in the bucket.

![The actual BANKING77 before-and-after scores and restored checkpoint](docs/media/result.jpg)

**Powered by Nebius Serverless AI**

The [recorded run](docs/sample-results/) improved from **199/308 correct (64.6%)** before training to **256/308 (83.1%)** afterward. Invalid answers fell from three to zero. These are results from this small published-benchmark subset, not an estimate of production performance.

See [validation notes](VALIDATION.md) for the measured outcome and exact recovery evidence. The result ZIP also includes the source data, license, selection IDs, configuration and checkpoint proof. A planned stop tests recovery; it does not establish reliability under natural preemption.

## 6. Check that compute has stopped

```bash
python3 scripts/job.py status
```

Check both Job IDs after the recovery test with `status --job-id YOUR_JOB_ID`. To cancel an active Job:

```bash
python3 scripts/job.py cancel --job-id YOUR_JOB_ID --yes
python3 scripts/job.py status --job-id YOUR_JOB_ID
```

Verify `CANCELLED` or another terminal state. Keep the bucket while needed; later remove only this run's files or its dedicated bucket in the console.

## Run with an agent

Install the [Nebius skills](https://github.com/nebius/skills#install) for an agent with terminal access and the signed-in CLI, then paste:

```text
Run fine-tuning-with-checkpoints from
https://github.com/MarouaneKhoukh/nebius-serverless-cookbooks.
Use nebius-cloud-basics, nebius-serverless-jobs and
nebius-serverless-data-secrets in project <PROJECT_ID>,
subnet <SUBNET_ID> and bucket <BUCKET_ID>.
Follow config/train.yaml and config/data.json. Show the current price
and confirm before launching unapproved compute. Train to step 50,
restore in a fresh Job and finish at step 100. Download result.zip,
check --require-resume, inspect all 308 before/after predictions and
verify both Jobs are terminal. Keep credentials private.
```

For a different training size, edit `config/data.json` before starting a new run. `train_per_intent: 0` uses all eligible distinct source training texts; increase the training schedule accordingly. The 77-intent taxonomy remains fixed.

Data: [BANKING77 by PolyAI](data/SOURCE.md), [CC BY 4.0](data/LICENSE). Local checks: `python3 -m unittest discover -s tests -v`.
