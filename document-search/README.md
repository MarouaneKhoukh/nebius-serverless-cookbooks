---
title: Build a Resumable Search Index on a Preemptible VM
category: inference
type: cookbook
runtime: Nebius Compute VM
frameworks: [Transformers, PyTorch, S3]
keywords: [preemptible, embeddings, recovery, object-storage, qwen]
difficulty: intermediate
---

<img src="docs/brand/nebius-logo.svg" alt="Nebius" width="140">

# Build a Resumable Search Index on a Preemptible VM

Index **1,000 real documents**, save their embeddings and completion records in **Nebius Object Storage**, then search by meaning. First, finish the whole workload. In a **separate controlled interruption test**, save 600 complete documents, restart compute and the application, and finish the remaining 400.

The application and **Qwen3-Embedding-0.6B** run on a standalone GPU VM. Object Storage holds the authoritative results and progress outside that VM. The earlier [Serverless Endpoint recipe](ENDPOINT.md) remains separate: it indexes 55 Python documents from your computer.

Preemptible capacity suits work that can keep completed results and retry unfinished work. An interruption is possible, not inevitable. Nebius stops preemptible VMs without automatically restarting them. When capacity and pricing conditions allow, start compute and launch the application again. [VM lifecycle](https://docs.nebius.com/compute/virtual-machines/preemptible).

## What we index

A document here is one Wikipedia reference passage from **Databricks Dolly 15k**, not a full article. The pinned selection contains **1,000 distinct passages, 219,197 words and 1,367,367 UTF-8 text bytes**. Paragraph-aware chunking at 160 words produces **1,970 chunks**. Stable source-line IDs, hashes, source links and the **CC BY-SA 3.0** license travel with the input. Instructions are display titles; answers are excluded. [Selection and attribution](vm/data/SOURCE.md).

The worker saves and validates each chunk before marking its document complete. A document is complete only when all required chunks are durable. On resume it validates saved state and reuses completed work. Changed input, model revision, encoder settings or chunking requires a new output prefix. Use **one writer per prefix**.

## 1. Prepare the bucket and VM

You need a billing-enabled **eu-north1** project, permission and quota for one GPU VM, an internet-enabled subnet, SSH on your computer, and an Object Storage bucket in that project. On your computer, prepare an SSH key; choose another filename if this exists:

```bash
ssh-keygen -t ed25519 -f "$HOME/.ssh/document-search-vm"
cat "$HOME/.ssh/document-search-vm.pub"
```

In the [console](https://console.nebius.com), select your project. Under **Object Storage → Buckets**, create a private Standard bucket or reuse one you can write to. Use a dedicated prefix such as `document-search-video-01` and preserve unrelated objects.

For fresh S3 access, an administrator can create a service account and a group granting **`storage.object-editor` on this bucket**, then add the account to that group. Under the service account's **Access keys**, create an expiring S3 access key. Keep its ID and secret for the masked prompts below. Bucket creation requires separate bucket-management permissions. Nebius CLI OAuth sign-in does not supply S3 credentials. [Roles](https://docs.nebius.com/iam/authorization/roles), [access keys](https://docs.nebius.com/iam/service-accounts/access-keys).

Under **Compute → Virtual machines → Create virtual machine**, select:

- **Compute:** Pay-as-you-go, **Preemptible**, **L40S AMD** (`gpu-l40s-d`), **1 GPU / 16 vCPU / 96 GiB**, name `document-search-video`.
- **Pricing:** **Follows spot price**. L40S has **flat preemptible pricing**; this run does not demonstrate a changing spot price. The video's general price-policy explanation is separate: a cap on a dynamically priced platform limits its accepted GPU-hour rate, without guaranteeing capacity. Check the current full quote. [Compute pricing](https://docs.nebius.com/compute/resources/pricing), [pricing policies](https://docs.nebius.com/signup-billing/pricing-policy).
- **Boot disk:** Ubuntu 24.04 LTS for NVIDIA GPUs **CUDA 13**, **80 GiB network SSD**.
- **Network:** reuse your internet-enabled subnet, assign a public IPv4, and allow TCP 22 from your current public IP.
- **SSH:** username `cookbook`, your **public** key above. Review the quote, create the VM and record its ID.

Wait for **Running** and SSH initialization. Compare its host fingerprint from serial logs with the first SSH prompt. Copy the public IP and connect from your computer:

```bash
export VM_IP="YOUR_VM_PUBLIC_IP"
ssh -i "$HOME/.ssh/document-search-vm" "cookbook@$VM_IP"
```

## 2. Install and prepare on the VM

In the **VM's SSH terminal**, run:

```bash
git clone https://github.com/MarouaneKhoukh/nebius-serverless-cookbooks.git &&
cd nebius-serverless-cookbooks/document-search &&
python3 -m venv .venv &&
source .venv/bin/activate &&
python -m pip install -r vm/requirements.txt &&
nvidia-smi
```

If `venv` is unavailable, install it with `sudo apt-get update && sudo apt-get install -y python3-venv`, then rerun the venv and package-install commands from the cookbook folder. Use Ubuntu's Python 3.10–3.12. The public model needs no Hugging Face token; its exact revision is pinned in [vm/runtime.json](vm/runtime.json).

In that VM terminal, replace the bucket placeholder and enter your S3 key privately:

```bash
export S3_ENDPOINT_URL="https://storage.eu-north1.nebius.cloud"
export AWS_DEFAULT_REGION="eu-north1"
export RUN_ROOT="s3://YOUR_BUCKET/document-search-video-01"
read -rs -p "S3 access key ID: " AWS_ACCESS_KEY_ID; printf '\n'
read -rs -p "S3 secret access key: " AWS_SECRET_ACCESS_KEY; printf '\n'
export AWS_ACCESS_KEY_ID AWS_SECRET_ACCESS_KEY

python scripts/prepare_vm_data.py &&
python -m vm.cli upload-inputs --store "$RUN_ROOT/inputs"
```

Preparation verifies the source checksum and every selected passage, and reports its own elapsed time. Uploading saves the documents, pinned manifest, license and attribution outside the VM. Credentials live in this shell environment; enter them again in a fresh SSH session. Keep the bucket and `RUN_ROOT` when resuming.

## 3. Finish all 1,000 documents first

On the VM:

```bash
mkdir -p .state &&
python -m vm.cli index --store "$RUN_ROOT/success" --report .state/success.json &&
python -m vm.cli verify --store "$RUN_ROOT/success"
```

Expect **1,000 completed documents, 1,970 saved chunks, 0 remaining**. Model loading, saved-state scanning, embedding and saving are timed separately. No fixed runtime is promised. Repeating a complete run reuses every document without new document-embedding work.

Search the completed collection:

```bash
python -m vm.cli query --store "$RUN_ROOT/success" \
  --text "What happens in chess when a player has no legal moves but is not in check?" \
  --output-dir results-vm-search
```

The terminal prints passages and links to their exact source records. `results-vm-search/search.html` is a readable report labelled **Powered by Nebius Compute**. Scores express similarity, not answer confidence. View it from a **second terminal on your computer**:

```bash
scp -i "$HOME/.ssh/document-search-vm" -r \
  "cookbook@$VM_IP:nebius-serverless-cookbooks/document-search/results-vm-search" .
open results-vm-search/search.html
```

On Ubuntu with a desktop, use `xdg-open` instead of `open`.

## 4. Run the separate controlled 600 plus 400 scenario

Use a **new output prefix**, separate from the successful run. This command deliberately stops after 600 previously unfinished documents are durable:

```bash
python -m vm.cli index --store "$RUN_ROOT/recovery" \
  --stop-after-documents 600 --report .state/recovery-before.json &&
python -m vm.cli status --store "$RUN_ROOT/recovery"
```

Expect **600 complete documents, 400 remaining**, with **1,206 chunks saved**. This is a controlled application stop, not a provider preemption. In the console, stop **only this VM**, wait for **Stopped**, then start it when capacity and your pricing conditions permit. Measure restart time separately. Capacity is not guaranteed.

Copy its current public IP again; it can change. Reconnect with SSH. In the **new VM session**, activate the environment, repeat the credential and `RUN_ROOT` exports above, and restore the input from Object Storage:

```bash
cd nebius-serverless-cookbooks/document-search &&
source .venv/bin/activate &&
python -m vm.cli download-inputs --data data/restored-documents --store "$RUN_ROOT/inputs" &&
python -m vm.cli index --data data/restored-documents --store "$RUN_ROOT/recovery" \
  --report .state/recovery-after.json &&
python -m vm.cli verify --data data/restored-documents --store "$RUN_ROOT/recovery"
```

Expect **600 documents reused, 400 newly completed, 1,000 complete**: 1,206 chunks reused and 764 added. The application finds progress by reading and validating S3 chunk objects and completion markers under the same prefix. It does not read a local progress file. A replacement compatible VM can do the same after installing these dependencies and downloading the pinned input.

Attached network disks survive a normal stop, but processes and RAM do not. Keeping inputs, vectors and progress in Object Storage also lets this application recover without retaining the VM or its disk. [Stop/start behavior](https://docs.nebius.com/compute/virtual-machines/stop-start).

## 5. Interrupt an unfinished batch

This **third prefix** deliberately hard-exits after one verified chunk save, before its document completion marker. It returns exit code **75**:

```bash
python -m vm.cli index --store "$RUN_ROOT/unfinished-batch" --crash-after-saved-chunks 1
```

Inspect it and resume in a fresh process:

```bash
python -m vm.cli status --store "$RUN_ROOT/unfinished-batch" &&
python -m vm.cli index --store "$RUN_ROOT/unfinished-batch" --report .state/unfinished-resumed.json &&
python -m vm.cli verify --store "$RUN_ROOT/unfinished-batch"
```

Before resuming, expect **one saved chunk and no complete documents**. The worker must reuse that chunk and finish the collection. Embeddings computed but not saved before exit may run again. The first batch is computed normally; no delays are added. This controlled process failure is not a Nebius preemption.

## 6. Save results and clean up

Each output prefix holds immutable `run.json`, `chunks/` results and `documents/` completion markers. Timing records are in its sibling prefix, such as `success-measurements/`. Local `.state/*.json` files are report copies, not recovery state. Retain the input and result prefixes together.

After saving reports and measurements, stop this VM and verify **Stopped**. Delete its VM and test boot disk if no longer needed; check its public IP allocation and dedicated SSH credential were removed. A stopped VM can retain billable disks. Preserve reused networking and buckets. Revoke only an access key created for this recipe. Object Storage results remain until you deliberately remove the recipe's prefixes.

## Validation and the Endpoint alternative

```bash
python3 -m unittest discover -s tests -q
```

Offline tests cover fresh-process recovery, partial writes, corruption and incompatible settings with fixture embeddings. They do not establish GPU performance. Plain local `--store` paths are for tests; the VM lesson uses `s3://` Object Storage.

[VALIDATION.md](VALIDATION.md) separates offline checks, controlled tests and actual live execution. The earlier code and results remain in [ENDPOINT.md](ENDPOINT.md) and [ENDPOINT_VALIDATION.md](ENDPOINT_VALIDATION.md). Serverless branding applies only to that separate route.
