---
title: Generate a Video Dataset with Wan
category: inference
type: cookbook
runtime: Nebius Serverless AI Endpoint
frameworks: [vLLM-Omni]
keywords: [preemptible, video-generation, wan, vbench, batch-processing]
difficulty: intermediate
---

<img src="docs/brand/nebius-logo.svg" alt="Nebius" width="140">

# Generate a Video Dataset with Wan

Generate 200 video clips with Wan2.1-T2V-1.3B from published VBench prompts, which are used to test video-generation models. The batch covers eight content categories, with 25 prompts per category. You’ll get a review gallery and a manifest linking every clip to its prompt, seed and settings, ready to compare generation settings or model versions.

Nebius Serverless AI hosts Wan behind an authenticated Endpoint. Your computer sends the prompts and downloads each finished clip. We’ll use a preemptible GPU for lower rates when available. Each finished clip is saved on your computer, so completed downloads survive if the GPU is reclaimed.

![Example clips from the earlier eight-prompt test run](docs/media/result.jpg)

Powered by Nebius Serverless AI

[Saved clips and manifests](docs/sample-results) · [Recorded test runs](VALIDATION.md)

## 1. Set up

You need macOS or Ubuntu, Git, Python 3.10+, and a billing-enabled Nebius project in eu-north1 with quota for one preemptible H100. No local GPU is needed.

Get the recipe and keep using this folder for the commands below:

```bash
git clone https://github.com/MarouaneKhoukh/nebius-serverless-cookbooks.git &&
cd nebius-serverless-cookbooks/batch-video-generation &&
pwd
```

Install FFmpeg, which includes `ffprobe`. On macOS with [Homebrew](https://brew.sh/), run `brew install ffmpeg`. On Ubuntu:

```bash
sudo apt-get update
sudo apt-get install -y ffmpeg
```

Check the tools and bundled prompts without calling a model:

```bash
ffmpeg -version
ffprobe -version
python3 scripts/prepare_data.py --verify
python3 src/generate.py --check-input
```

Expect **200 prompts** and **49 frames at 832×480**. The selection uses 25 published prompts per VBench content category. Their [source selection and Apache 2.0 license](data/SOURCE.md) are included. This recipe generates clips; it doesn’t calculate a VBench score.

Install the [Nebius CLI](https://docs.nebius.com/cli/install) if needed:

```bash
curl -sSL https://artifacts.nebius.cloud/cli/install.sh | bash
```

If installation needs a new terminal, return to the folder printed by `pwd`. Use CLI 0.12.303 or newer; run `nebius update` if yours is older. Copy your project ID from the [console](https://console.nebius.com): project selector → ⋯ → Copy project ID. Replace `YOUR_PROJECT_ID`, then sign in:

```bash
nebius version
export NEBIUS_PROJECT_ID="YOUR_PROJECT_ID"
nebius profile create cookbook --parent-id "$NEBIUS_PROJECT_ID" &&
nebius profile activate cookbook &&
nebius iam whoami
```

If you already have a profile for this project, activate it with `nebius profile activate YOUR_PROFILE_NAME` instead of creating `cookbook`. You still need the `NEBIUS_PROJECT_ID` export above.

Choose a subnet with outbound internet access for model downloads. Copy its `vpcsubnet-…` ID from the list:

```bash
nebius vpc subnet list --parent-id "$NEBIUS_PROJECT_ID" --format json
export NEBIUS_SUBNET_ID="YOUR_SUBNET_ID"
```

<details>
<summary>If your project has no subnet</summary>

Create a network and subnet with the default internet route:

```bash
export NEBIUS_NETWORK_ID="$(nebius vpc network create --parent-id "$NEBIUS_PROJECT_ID" --name cookbook-network --format jsonpath='{.metadata.id}')"
export NEBIUS_SUBNET_ID="$(nebius vpc subnet create --parent-id "$NEBIUS_PROJECT_ID" --name cookbook-subnet --network-id "$NEBIUS_NETWORK_ID" --format jsonpath='{.metadata.id}')"
```

</details>

Save these non-secret settings for another terminal:

```bash
cat > .env <<ENV
export NEBIUS_PROJECT_ID="$NEBIUS_PROJECT_ID"
export NEBIUS_SUBNET_ID="$NEBIUS_SUBNET_ID"
ENV
```

If you open a new terminal, return to this cookbook folder and run `source .env`.

## 2. Start Wan

The [configuration](config/endpoint.json) uses vLLM-Omni 0.24.0, one H100 and a 500 GiB temporary disk. Wan is public, so you don’t need a Hugging Face token.

Check the current rate under Serverless AI → Endpoints → Create endpoint → Preemptible. The default follows the spot market price without a cap, which can rise above the regular rate. You also pay for compute used to pull the image, load the model and keep the Endpoint idle.

To set a price ceiling, create a policy for `gpu-h100-sxm` under Billing → Pricing → Pricing policy. Add `--spot-pricing-policy-id "YOUR_POLICY_ID"` to both create commands below. A cap limits the price you accept; it doesn’t guarantee capacity. [Pricing policies](https://docs.nebius.com/signup-billing/manage-pricing-policy).

The first command checks the configuration; the second creates the Endpoint. The last waits for Wan to be ready:

```bash
python3 scripts/endpoint.py create \
  --project-id "$NEBIUS_PROJECT_ID" --subnet-id "$NEBIUS_SUBNET_ID" \
  --name cookbook-video-generation --dry-run &&
python3 scripts/endpoint.py create \
  --project-id "$NEBIUS_PROJECT_ID" --subnet-id "$NEBIUS_SUBNET_ID" \
  --name cookbook-video-generation --yes &&
python3 scripts/endpoint.py wait --timeout 1800
```

GPU allocation, the image pull and model loading can take time. Proceed when it prints **Model API ready**. A wait timeout leaves the Endpoint running or provisioning: inspect its logs and stop unused compute while diagnosing.

The helper keeps the Endpoint selection in `.state/` and passes the URL and token privately to the generation command.

## 3. Generate and view the clips

Submit all 200 prompts, then check the downloaded files:

```bash
python3 scripts/endpoint.py run -- \
  python3 src/generate.py --input data/prompts.csv --output results-vbench-200 &&
python3 scripts/check_results.py results-vbench-200
```

With a new output folder, expect **Generated 200; reused 0**. The checker should report **"completed": 200** and **"decode_passed": true**. Each clip has 49 frames at 16 fps, about 3.06 seconds, at 832×480. These are short previews you can inspect for prompt alignment and motion.

Open the gallery on macOS:

```bash
open results-vbench-200/index.html
```

On Ubuntu with a desktop, run `xdg-open results-vbench-200/index.html`. You should see **200 of 200 clips saved**. Play them and follow the source links to compare each result with its original prompt.

Your `results-vbench-200` folder contains the MP4s, `clips.csv`, a JSON record per clip and the input provenance. On an automated runner, keep this folder on persistent storage. The videos are ordinary files you can use in your own project; the gallery is a preview. Rerunning the same generation command while Wan is ready should report **Generated 0; reused 200**.

### Try your own prompts

Keep the Endpoint running. Create a CSV from this same cookbook folder, replacing the descriptions with your own:

```bash
cat > data/my-prompts.csv <<'CSV'
id,prompt,seed
coffee,"Steam rising from a cup of coffee in soft morning light",42
coast,"A slow aerial shot of waves breaking along a rocky coastline",43
CSV
```

Use unique IDs made from letters, numbers, hyphens or underscores, starting with a letter or number. Seeds must be integers from 0 to 2147483647. Put descriptions containing commas inside double quotes. The client accepts up to 1,000 prompts per CSV; split larger catalogs into separate batches and output folders.

Check the CSV, generate into a new output folder and validate the clips:

```bash
python3 src/generate.py --input data/my-prompts.csv --check-input &&
python3 scripts/endpoint.py run -- \
  python3 src/generate.py --input data/my-prompts.csv --output results-custom &&
python3 scripts/check_results.py results-custom
```

Open the gallery on macOS:

```bash
open results-custom/index.html
```

On Ubuntu with a desktop, run `xdg-open results-custom/index.html`. If you change prompts, seeds or generation settings, use a new output folder.

## 4. Stop the Endpoint

When you’re done, stop it and check the state:

```bash
python3 scripts/endpoint.py stop
python3 scripts/endpoint.py status
```

Expect **STOPPED**. The GPU and temporary disk are released; your downloaded clips remain. Closing the gallery or generation script doesn’t stop the Endpoint. Keep shared networking in place.

## What if generation is interrupted?

**Finished clips are saved on your computer, outside the Endpoint.** Keep the whole output folder, including its JSON records and `.pending` directory, along with the helper’s `.state/` folder.

If only the client stopped, rerun the original command first. It can continue polling an existing request and will skip completed downloads. After the GPU is reclaimed, a request may be lost. Check the Endpoint and old request before allowing another paid generation with `--retry-lost`:

```bash
python3 scripts/endpoint.py start &&
python3 scripts/endpoint.py wait --timeout 1800 &&
python3 scripts/endpoint.py run -- \
  python3 src/generate.py --input data/prompts.csv --output results-vbench-200 --retry-lost &&
python3 scripts/check_results.py results-vbench-200
python3 scripts/endpoint.py stop
python3 scripts/endpoint.py status
```

Keep the input, settings and output folder unchanged. Use one generation process per folder. If preemptible capacity is unavailable, wait before trying to start again. Finish by checking STOPPED.

### Try it yourself

Use a new folder for this optional 20-then-180 test. Start the Endpoint again if you followed step 4:

```bash
python3 scripts/endpoint.py start &&
python3 scripts/endpoint.py wait --timeout 1800 &&
python3 scripts/endpoint.py run -- \
  python3 src/generate.py --input data/prompts.csv --output results-resume-test --limit 20
```

Expect **Generated 20; reused 0**. Now rerun without the limit:

```bash
python3 scripts/endpoint.py run -- \
  python3 src/generate.py --input data/prompts.csv --output results-resume-test &&
python3 scripts/check_results.py results-resume-test
python3 scripts/endpoint.py stop
python3 scripts/endpoint.py status
```

Expect **Generated 180; reused 20** and 200 valid clips, then STOPPED. Here the client stops on purpose after 20 downloads; this is not a real preemption.

## Go further

To use the full catalog of 100 prompts per VBench category:

```bash
python3 scripts/prepare_data.py --per-category 100 --output data/full-catalog.csv
```

This creates 800 inputs and `data/full-catalog.source.json`, without launching compute. Use that CSV in the generation command with a new output folder; more clips mean more paid inference.

For quota errors, check Quotas in the console. For capacity or model errors, inspect Endpoint logs and stop unused compute. Local checks are separate from GPU execution:

```bash
python3 -m unittest discover -s tests
```

Our [recorded test runs](VALIDATION.md) separate local checks from GPU execution.

## Run with an agent

With the [Nebius skills installed](https://github.com/nebius/skills#install), share this cookbook and ask:

```text
Run batch-video-generation in MarouaneKhoukh/nebius-serverless-cookbooks
with nebius-cloud-basics and nebius-serverless-endpoints in my selected
project and subnet, within my approved GPU budget. Use config/endpoint.json
on preemptible compute and check the current rate before launching.
Verify the bundled VBench prompts and wait for Model API ready. Generate
all 200 clips without a limit, and require scripts/check_results.py to
pass with 200 decoded clips. Inspect the gallery, then stop this Endpoint
and confirm STOPPED.
If generation or validation fails, report the failure rather than success.
Keep credentials private and preserve my saved results and other resources.
```
