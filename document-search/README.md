---
title: Save Your Progress with Preemptible Serverless Jobs
category: inference
type: cookbook
runtime: Nebius Serverless Job
frameworks: [Transformers, PyTorch, S3]
keywords: [preemptible, recovery, object-storage, embeddings]
difficulty: intermediate
---

# Save Your Progress with Preemptible Serverless Jobs

Preemptible GPUs let you use spare capacity at lower rates, but work can be interrupted when that capacity is reclaimed. Save each finished document to Object Storage as you go. If a Job stops, submit another Job with the same settings and storage location. It skips the saved documents and finishes what remains.

This example builds a searchable index of **1,000 distinct Dolly reference passages**, using Qwen3-Embedding-0.6B. They produce **1,970 chunks**. Serverless handles the GPU environment and releases compute when each Job finishes; you manage no VM or SSH connection. [Data and license](worker/data/SOURCE.md).

## 1 Set up

Run all commands below **on your computer**, from the cookbook folder. You need a billing-enabled **eu-north1** project with L40S GPU quota, an internet-enabled subnet and the [Nebius CLI](https://docs.nebius.com/cli/install) (0.12.305 or newer).

```bash
git clone https://github.com/MarouaneKhoukh/nebius-serverless-cookbooks.git
cd nebius-serverless-cookbooks/document-search
nebius profile create
```

Each Job downloads worker files from `MarouaneKhoukh/nebius-serverless-cookbooks` at `RECIPE_REF` (default `main`); local worker edits are not uploaded, so publish changes and set `RECIPE_REF` to their branch or commit when testing (for a fork, update the repository URL in `scripts/run_job.py`).

Complete the CLI sign-in and select your project. In the [console](https://console.nebius.com), prepare:

- A private **Object Storage bucket**. Create an [S3 access key](https://docs.nebius.com/iam/service-accounts/access-keys) for a service account with `storage.object-editor` access to that bucket.
- A **SecretStash secret**: open **Cryptography → SecretStash → Create secret**, name it `document-index-s3`, and add two text entries: `AWS_ACCESS_KEY_ID` and `AWS_SECRET_ACCESS_KEY`, containing that access key's ID and secret (use **Add pair** for the second entry). Copy the secret's `mbsec-…` ID. Keep the values out of your code and terminal commands. [SecretStash instructions](https://docs.nebius.com/mysterybox/secrets/create).
- Your **project ID** and **subnet ID**, available on their console pages.

Your account needs permission to create Jobs and read the secret payload (`mysterybox.payload-viewer`, included in `admin`). Save these non-secret settings locally. Replace every `YOUR_…` value and use a fresh bucket prefix. When repeating this guide, choose new Job names too:

```bash
cat > .env <<'ENV'
export NEBIUS_PROJECT_ID="YOUR_PROJECT_ID"
export NEBIUS_SUBNET_ID="YOUR_SUBNET_ID"
export S3_SECRET_ID="YOUR_SECRET_ID"
export RUN_ROOT="s3://YOUR_BUCKET/document-index-demo-01"
ENV
source .env
```

The launcher uses one preemptible **L40S AMD GPU**, an 80 GiB temporary disk, no automatic retries and a **one-hour timeout per Job**. Review the current [price](https://nebius.com/prices) before submitting. Setup, model download and execution all use billable compute.

## 2 Save the first 600 documents

Validate the configuration, then submit:

```bash
JOB_NAME=document-index-first bash scripts/submit.sh --dry-run &&
JOB_NAME=document-index-first bash scripts/submit.sh --async
```

In **Serverless AI → Jobs**, open `document-index-first` and its **Logs**. Expect roughly **five minutes** for provisioning and the image pull before **Running**, based on our tests; application logs may be empty during that wait. Wait for **Completed** before continuing. The log should end with **600 new, 0 reused, 400 remaining**. Each saved document is one object containing all its chunk embeddings.

This deliberate pause after 600 documents is a controlled interruption test, not an actual Nebius preemption. The Job ends and releases its compute. Its temporary disk is discarded; the finished results and run settings remain under `$RUN_ROOT/index` in Object Storage.

## 3 Resume in a new Job

If you closed your terminal, return to this cookbook folder and run `source .env` first. Submit the same workload under a new Job name:

```bash
JOB_NAME=document-index-resume bash scripts/submit.sh --async
```

The new container downloads the same pinned input and model. It reads saved progress and prints **“600 documents already saved, 400 to go.”** It should finish with **400 new, 600 reused, 0 remaining**: **1,000 complete documents / 1,970 chunks**.

There are no credentials to re-enter: Serverless injects them from SecretStash into each Job.

## 4 Search the index

The completed Job automatically runs this query:

> What is stalemate in chess?

Read the ranked passages and source links in its **Logs**. In **Object Storage → your bucket → document-index-demo-01 → outputs**, download `search.html` and open it in your browser for a readable report. `search.json` contains the same results; the other JSON files record each attempt's counts and timings. The bucket stays private.

## 5 Finish

Check both Jobs are **Completed**, not still starting or running. Completed Jobs no longer use compute. Cancel any unfinished test under **Serverless AI → Jobs → ⋯ → Cancel**. Keep the results, or delete only this run's bucket prefix and temporary secret when you no longer need them. Preserve shared buckets and credentials.

## When a Job is preempted

- Wait for the previous attempt to reach a terminal state.
- Submit a new Job with a new name and the **same** input, model settings and `RUN_ROOT`.
- Check the log's reused and remaining counts. An unfinished document is recomputed.
- Use one active Job per prefix. Changed input or model settings require a fresh prefix.

The pattern lives in [worker/durable.py](worker/durable.py): list saved documents, skip them, compute the next document, then save its complete result. A run manifest refuses incompatible settings. [Serverless Job lifecycle](https://docs.nebius.com/serverless/lifecycle).

## Go further

For an uninterrupted run, use a separate output location and remove the 600-document cap (`0` means no cap):

```bash
JOB_NAME=document-index-full RUN_ROOT="$RUN_ROOT/full-run" \
  MAX_NEW_DOCUMENTS=0 bash scripts/submit.sh --async
```

Wait for **Completed** and check **1,000 new, 0 reused, 0 remaining**.

To test a crash during an unfinished document, use another prefix. This attempt deliberately exits with code **75** during the seventeenth computed chunk:

```bash
JOB_NAME=document-index-crash RUN_ROOT="$RUN_ROOT/crash-test" \
  MAX_NEW_DOCUMENTS=0 CRASH_AFTER_CHUNKS=17 bash scripts/submit.sh --async
```

Wait for **Failed**, then submit without the crash flag:

```bash
JOB_NAME=document-index-crash-resume RUN_ROOT="$RUN_ROOT/crash-test" \
  MAX_NEW_DOCUMENTS=0 bash scripts/submit.sh --async
```

The new Job reuses only fully saved documents. Check **Completed**, **1,000 documents / 1,970 chunks**, and the reused count in its log. See [VALIDATION.md](VALIDATION.md) for actual execution results and timing scope.

For the separate Serverless Endpoint route, see [ENDPOINT.md](ENDPOINT.md).
