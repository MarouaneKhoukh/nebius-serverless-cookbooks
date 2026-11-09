---
title: Generate Video Clips from a List of Prompts
category: inference
type: cookbook
runtime: Nebius Serverless AI Endpoint
frameworks: [vLLM-Omni, Wan]
keywords: [preemptible, video-generation, batch, resume]
difficulty: beginner
---

<img src="docs/brand/nebius-logo.svg" alt="Nebius" width="145">

# Generate Video Clips from a List of Prompts

Give Wan three text prompts and save three short MP4 previews. You'll build a Python tool that generates each clip, downloads it and puts the results in a local video gallery.

Nebius Serverless AI runs the video model on a cloud GPU, so you don't need to set up a GPU server. You'll create an **Endpoint**, a model API you call over HTTPS. Your computer submits prompts and saves the clips.

**Preemptible instances give you a way to do more with your GPU budget.** They provide GPU capacity at a changing market price that can be lower than the regular rate. The trade-off is that a run can be interrupted. This cookbook saves every finished clip on your computer, so the next run reuses those videos and generates only the unfinished ones.

For example, during this experiment, this setup was priced at about **$0.84/hour on preemptible compute, compared with $4.55/hour on regular compute**. Prices can change.

![Three saved Wan video previews](docs/media/result.jpg)

**Powered by Nebius Serverless AI**

Watch the recorded samples: [paper boat](docs/sample-results/paper-boat.mp4), [mountain lake](docs/sample-results/mountain-lake.mp4), [red ball](docs/sample-results/red-ball.mp4). These are small **17-frame previews**. After cloning, open `docs/sample-results/index.html` to play them without starting a GPU.

## What you need

- macOS or Ubuntu, Git and Python **3.10+**. No local GPU or extra Python packages.
- A Nebius account with billing enabled and a project in **eu-north1**. A project holds your cloud resources and their permissions.
- Permission and quota to run **one preemptible H100 GPU**. Quota is your account's resource allowance; check **Quotas** in the console if deployment is refused.
- FFmpeg and `ffprobe`, installed below, to check the downloaded videos. The macOS instructions require [Homebrew](https://brew.sh/).

## 1. Get the files and install FFmpeg

```bash
git clone https://github.com/MarouaneKhoukh/nebius-serverless-cookbooks.git
cd nebius-serverless-cookbooks/batch-video-generation
python3 --version
```

Run the remaining commands from this directory.

On macOS with Homebrew:

```bash
brew install ffmpeg
```

On Ubuntu:

```bash
sudo apt-get update
sudo apt-get install -y ffmpeg
```

Check that both tools are available:

```bash
ffmpeg -version
ffprobe -version
```

## 2. Sign in to Nebius

The Nebius CLI creates and manages your Endpoint from the terminal. If it isn't installed:

```bash
curl -sSL https://artifacts.nebius.cloud/cli/install.sh | bash
```

Open a new terminal after installation and return to this cookbook's directory. Use CLI **0.12.303 or newer**; run `nebius update` if yours is older.

In the [Nebius console](https://console.nebius.com), select your eu-north1 project and copy its project ID. Replace the **entire** `YOUR_PROJECT_ID` value:

If you already have a signed-in CLI profile for this project, use its name in place of `cookbook` and skip `profile create`. Otherwise, create the `cookbook` profile:

```bash
nebius version
export NEBIUS_PROJECT_ID="YOUR_PROJECT_ID"
export AI_AGENT="${AI_AGENT:-cookbook}"
nebius profile create cookbook --parent-id "$NEBIUS_PROJECT_ID"
nebius profile activate cookbook
nebius iam whoami
```

Complete the browser sign-in when prompted.

Choose a **subnet**, the network your Endpoint will use. List the project's subnets and replace `YOUR_SUBNET_ID` with a subnet's `metadata.id`. It must allow outbound internet access to download the model.

```bash
nebius vpc subnet list --parent-id "$NEBIUS_PROJECT_ID" --format json
export NEBIUS_SUBNET_ID="YOUR_SUBNET_ID"
```

<details>
<summary>If your project has no subnet</summary>

Create a network and subnet in the same project:

```bash
export NEBIUS_NETWORK_ID="$(nebius vpc network create --parent-id "$NEBIUS_PROJECT_ID" --name cookbook-network --format jsonpath='{.metadata.id}')"
export NEBIUS_SUBNET_ID="$(nebius vpc subnet create --parent-id "$NEBIUS_PROJECT_ID" --name cookbook-subnet --network-id "$NEBIUS_NETWORK_ID" --format jsonpath='{.metadata.id}')"
```

New networks have a default internet route. If your company manages the network, ask for an approved subnet instead. [Network setup](https://docs.nebius.com/vpc/networking/isolation) · [Default routing](https://docs.nebius.com/vpc/routing/overview)

</details>

## 3. Start the video model

The supplied configuration runs **Wan2.1-T2V-1.3B** through vLLM-Omni on one H100, with a 500 GiB temporary disk. The model is public; no Hugging Face token is needed.

Check the current rate under **Serverless AI → Endpoints → Create endpoint → Preemptible** before launching. The deployment script uses **Follow Spot price** by default, which accepts the changing price without a maximum. Model loading and idle time are billed too. You'll stop the Endpoint after downloading the clips.

<details>
<summary>Set a maximum GPU price</summary>

A pricing policy sets a maximum **per GPU hour**. A higher maximum can improve allocation priority when demand for the same GPU platform is high. You pay the current market rate while it stays within your limit. Capacity can still be reclaimed. [How allocation works](https://docs.nebius.com/signup-billing/pricing-policy#capacity-allocation)

1. Check the [current price and recent history](https://docs.nebius.com/signup-billing/spot-prices). Choose a maximum within your budget, with room for price increases. A limit below the current rate blocks startup.
2. In **Billing → Pricing → Pricing policy → Create pricing policy**, enter a name using letters/numbers, select your project and **`gpu-h100-sxm`**, and enter that maximum. Create the policy and copy its ID.
3. Add `--spot-pricing-policy-id "YOUR_POLICY_ID"` to both `create` commands below, replacing the whole placeholder. The deployment script will use that policy.

Choose the policy before launching. Before changing its maximum, stop the Endpoints using it and wait for any Jobs using it to finish, or cancel them.

A tight limit can cause more interruptions as prices rise. **Follow Spot price** accepts price changes without a cap, including prices above regular rates. A GPU price limit does not cap the total cost of a run or its storage.

[Policy setup](https://docs.nebius.com/signup-billing/manage-pricing-policy) · [Pricing options](https://docs.nebius.com/signup-billing/pricing-policy)

</details>

```bash
python3 scripts/endpoint.py create \
  --project-id "$NEBIUS_PROJECT_ID" \
  --subnet-id "$NEBIUS_SUBNET_ID" \
  --name cookbook-video-spot --dry-run

python3 scripts/endpoint.py create \
  --project-id "$NEBIUS_PROJECT_ID" \
  --subnet-id "$NEBIUS_SUBNET_ID" \
  --name cookbook-video-spot --yes

python3 scripts/endpoint.py wait --timeout 1800
```

The first command previews the deployment; the second creates it. Wait for the model API to be ready before continuing. The deployment script passes the API address and authentication token to the client. If loading fails, check the Endpoint logs and stop it while diagnosing the problem.

<details>
<summary>Ask an agent to run it instead</summary>

Install the [Nebius agent skills](https://github.com/nebius/skills#install) for your coding agent, then paste the prompt below. The agent needs terminal access and the CLI sign-in from step 2. Skills are optional for the CLI instructions above.

```text
Run this cookbook in Nebius project <MY_PROJECT_ID> using
nebius-cloud-basics and nebius-serverless-endpoints. Follow README.md and
config/endpoint.json. Show the current price and confirm the deployment
before creating a preemptible H100 Endpoint. Wait for Wan, generate the
three sample clips and check that they play. Verify that rerunning the
client reuses the completed clips. Stop this cookbook's Endpoint and verify
STOPPED. Keep authentication tokens private.
```

</details>

## 4. Generate the clips

```bash
python3 src/generate.py --check-input

python3 scripts/endpoint.py run -- \
  python3 src/generate.py --input data/prompts.csv --output results
```

The tool submits each prompt, waits for the video, downloads it and checks it with FFmpeg. Expect **three completed clips**.

Open `results/index.html` in your browser. The MP4s, their prompts and settings, and `summary.json` are saved in `results/` on your computer. The gallery plays those local files; it isn't a publicly hosted website.

## 5. Stop the Endpoint

```bash
python3 scripts/endpoint.py stop
```

Wait for `STOPPED`. This releases the GPU and temporary disk; your downloaded clips remain. The Endpoint stays running and billable until you stop it, even after the videos finish.

## If the GPU is reclaimed

Keep the same input, settings and results directory. Completed clips are reused. A clip that was still being generated must start again if its server-side request was lost.

After confirming the Endpoint was interrupted, restart it and continue:

```bash
python3 scripts/endpoint.py start
python3 scripts/endpoint.py wait --timeout 1800
python3 scripts/endpoint.py run -- \
  python3 src/generate.py --input data/prompts.csv --output results --retry-lost
python3 scripts/endpoint.py stop
```

`--retry-lost` permits a new paid request for a missing video request. If only your local script stopped, rerun the original command first: it can continue waiting for a request still running on the server. Restarting the local script alone doesn't stop the cloud GPU.

<details>
<summary>Change the prompts or try resuming</summary>

Edit `data/prompts.csv`, keeping unique filename-safe IDs and integer seeds. Use a new results directory when changing prompts, seeds, the model or generation settings.

For longer previews, add `--frames 33` or `--frames 49` and choose a new `--output` directory. Valid frame counts follow `4n+1`; longer videos need more GPU work. The provided configuration uses the Wan template's `flow_shift=3.0` and `boundary_ratio=0.0` settings.

To try client resumption, run step 4 with `--output results-resume --limit 1`, then repeat it without `--limit 1`. The second run reuses the first clip. Stop the Endpoint afterwards.

Rebuild the gallery from saved clips without making model requests:

```bash
python3 src/generate.py --input data/prompts.csv --output results --report-only
```

</details>

<details>
<summary>Troubleshooting and test results</summary>

- **Sign-in or API 401/403 error:** check your CLI profile and the Endpoint's token-authentication setting.
- **Quota exceeded:** request a higher allowance in the console.
- **No capacity:** try again when preemptible H100 GPUs become available.
- **`RUNNING` but the API isn't ready:** use the wait command; check Endpoint logs if it times out.
- **Missing video request:** after a confirmed Endpoint interruption, use `--retry-lost` as above.
- **Video check fails:** inspect the file and local disk space. The tool keeps it out of the completed results until it passes.
- **Generation fails:** check the prompt and Endpoint logs before retrying.

The recorded run generated three playable clips and reused them on a later client run. Natural GPU preemption was not observed. [Validation and recorded prices](VALIDATION.md) · [Recorded gallery](docs/sample-results/index.html)

Run local checks with `python3 -m unittest discover -s tests -v`.

</details>

[Serverless AI](https://docs.nebius.com/serverless/overview) · [Preemptible instances](https://docs.nebius.com/compute/virtual-machines/preemptible) · [Endpoint stop/start](https://docs.nebius.com/serverless/maintenance/stop-start) · [Wan template](https://github.com/nebius/serverless-ai-cookbook/tree/main/templates/endpoint-wan21-t2v-1-3b) · [Wan model](https://huggingface.co/Wan-AI/Wan2.1-T2V-1.3B-Diffusers)
