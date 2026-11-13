---
title: Save Your Progress on a Preemptible VM
category: inference
type: cookbook
runtime: Nebius Compute VM
frameworks: [Transformers, PyTorch, S3]
keywords: [preemptible, recovery, object-storage, embeddings]
difficulty: intermediate
---

# Save Your Progress on a Preemptible VM

Preemptible VMs cost less than regular capacity, but Nebius can stop them. Save each finished document to Object Storage as you go. After a stop, start the VM again and rerun the same index command. Documents already saved are skipped.

The example indexes **1,000 distinct Dolly reference passages** with Qwen3-Embedding-0.6B, producing **1,970 chunks**. [Data and license](vm/data/SOURCE.md).

## 1 Set up

Use a billing-enabled **eu-north1** project with GPU quota. In the [console](https://console.nebius.com), create or reuse a private Object Storage bucket and an S3 access key with `storage.object-editor` access to it. Your administrator can grant that role to a service account through a group; create its key under **IAM → Service accounts → Access keys**. [Access key instructions](https://docs.nebius.com/iam/service-accounts/access-keys).

On your computer, create an SSH key (choose another filename if this exists):

```bash
mkdir -p "$HOME/.ssh"
ssh-keygen -t ed25519 -f "$HOME/.ssh/document-search-vm"
cat "$HOME/.ssh/document-search-vm.pub"
```

Under **Compute → Virtual machines → Create virtual machine**, choose **Preemptible** and name it `document-index-demo`. An example configuration is **L40S AMD, 1 GPU / 16 vCPU / 96 GiB**, **Follows spot price**, **Ubuntu 24.04 GPU CUDA 13**, and an **80 GiB network SSD**. Use an internet-enabled subnet, a dynamic public IPv4, and SSH access on TCP 22 from your IP. Set SSH username `cookbook` with the public key above. Review the quote and create the VM.

Once **Running**, check its SSH fingerprint against the serial logs. Connect from your computer:

```bash
export VM_IP="YOUR_VM_PUBLIC_IP"
ssh -i "$HOME/.ssh/document-search-vm" "cookbook@$VM_IP"
```

In the **VM terminal**, install the worker:

```bash
git clone --branch codex/document-search-vm https://github.com/MarouaneKhoukh/nebius-serverless-cookbooks.git &&
cd nebius-serverless-cookbooks/document-search &&
python3 -m venv .venv &&
.venv/bin/python -m pip install -r vm/requirements.txt
```

If `venv` is missing, run `sudo apt-get update && sudo apt-get install -y python3-venv`, then repeat the venv and install commands. Use Python 3.10–3.12.

Save only non-secret settings, replacing `YOUR_BUCKET`. Use a fresh prefix for this run:

```bash
cat > .env.vm <<'ENV'
export S3_ENDPOINT_URL="https://storage.eu-north1.nebius.cloud"
export AWS_DEFAULT_REGION="eu-north1"
export RUN_ROOT="s3://YOUR_BUCKET/document-index-demo-01"
ENV
source vm/session.sh
python scripts/prepare_vm_data.py
```

`session.sh` activates Python, loads these settings and privately prompts for the two S3 credentials. Credentials stay in the shell environment, never in the file. The pinned input is saved at the default `data/vm-documents` path.

## 2 Run the indexer

In the VM terminal:

```bash
python -m vm.cli index --store "$RUN_ROOT/index" --max-new-documents 600
```

For this walkthrough, each invocation processes up to **600 new documents**. The first invocation saves 600 and leaves 400. Each finished document becomes one S3 object containing all its chunk embeddings; an unfinished document has no saved result.

## 3 Stop the VM partway

In the console, **Stop** this VM and wait for **Stopped**. This is a manual stop, not an actual preemption. The network disk retains your code and input; Object Storage retains the finished results.

## 4 Start it again and rerun

In the console, **Start** the VM. Copy its current public IP and reconnect with the SSH command from step 1. In the new VM terminal, run:

```bash
cd nebius-serverless-cookbooks/document-search
source vm/session.sh
python -m vm.cli index --store "$RUN_ROOT/index" --max-new-documents 600
```

After the credential prompts, you should see **“600 documents already saved, 400 to go”**. The same command finishes the remaining 400. The result is **1,000 complete documents / 1,970 chunks**. No input download or `--data` argument is needed after this stop/start.

## 5 Search the results

On the VM:

```bash
python -m vm.cli query --store "$RUN_ROOT/index" \
  --text "What happens in chess when a player has no legal moves but is not in check?"
```

Read the returned passages and source links in the terminal. To open the HTML report, use a **terminal on your computer**:

```bash
export VM_IP="YOUR_VM_CURRENT_PUBLIC_IP"
scp -i "$HOME/.ssh/document-search-vm" -r \
  "cookbook@$VM_IP:nebius-serverless-cookbooks/document-search/results-vm-search" .
open results-vm-search/search.html
```

On a Linux desktop, use `xdg-open` instead of `open`.

## What to do when your VM is preempted

- Start compute again when capacity is available. Nebius does not automatically restart a preemptible VM.
- Reconnect using its current IP, activate your environment and supply credentials.
- Rerun the same job with the same input, model settings and Object Storage prefix.
- Check how many documents were reused. Work on an unfinished document runs again.
- Keep one writer per prefix. If you change the input or model settings, use a new prefix.

The reusable pattern is in [vm/durable.py](vm/durable.py): list saved documents, skip them, compute the next document, then save its complete result. [Nebius VM lifecycle](https://docs.nebius.com/compute/virtual-machines/preemptible).

## Clean up

Stop the VM and verify **Stopped**. To remove it and its managed boot disk, use **Settings → Delete virtual machine → Delete VM and disks**. A stopped VM still has billable disks. Preserve reused buckets, networking and credentials; remove only this example's S3 prefix when you no longer need the results.

## Go further

For an uninterrupted run, choose a fresh prefix and omit the demo limit:

```bash
python -m vm.cli index --store "$RUN_ROOT/full-run"
python -m vm.cli verify --store "$RUN_ROOT/full-run"
```

To try a crash mid-document, this exits with code **75** during the seventeenth chunk. Rerun without the crash flag:

```bash
python -m vm.cli index --store "$RUN_ROOT/crash-test" --crash-after-chunks 17
python -m vm.cli index --store "$RUN_ROOT/crash-test"
python -m vm.cli verify --store "$RUN_ROOT/crash-test"
```

Only finished documents survive; the interrupted document is recomputed. See [VALIDATION.md](VALIDATION.md) for checks, measurement scope and remaining validation.
