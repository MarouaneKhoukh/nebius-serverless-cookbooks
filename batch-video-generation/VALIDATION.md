# Validation

## Nebius run: November 9, 2026

All eight bundled VBench prompts produced downloadable MP4s on a **preemptible H100** Endpoint. [Saved gallery and clips](docs/sample-results/index.html) · [Output manifest](docs/sample-results/clips.csv) · [Machine-readable results](docs/sample-results/summary.json).

- Runtime: `vllm/vllm-omni:v0.24.0`, `Wan-AI/Wan2.1-T2V-1.3B-Diffusers`, one `gpu-h100-sxm`, preset `1gpu-16vcpu-200gb`, 500 GiB temporary disk.
- Settings: 832×480, **49 frames at 16 fps**, 20 inference steps, guidance 5.0, flow shift 3.0, boundary ratio 0.0. Each clip is **3.0625 seconds**. Per-prompt seeds are in the input CSV.
- Inputs: one unchanged prompt per VBench content category, selection seed 42, pinned revision `fd18b3d055cb0fc6f066ca90fe2c3c8cbb698490`. CSV SHA256: `40c6f386ddc9136f8bd2b529072c2ab25421f2ef8adf8105a37a71a24e3b4ba2`.

The first invocation used `--limit 2` and generated two clips. The next invocation generated six and reused two. A third invocation reported **Generated 0; reused 8**, without new generation requests. The completed downloads remain usable after the Endpoint stops.

The Endpoint received one stop request after the batch; the helper verified **STOPPED** successfully.

The result checker passed on both the original output and the public copy:

```bash
python3 scripts/check_results.py docs/sample-results
```

It verified all eight source/input joins and file hashes, then decoded **49 frames from every MP4** with FFmpeg. The exported gallery includes actual middle-frame posters. Original request caches remain private; published artifacts contain no account IDs, Endpoint addresses, auth tokens or signed download URLs.

The quoted rate for this run was **$0.80/hour for the H100 plus $0.048611/hour for the disk**, or **$0.848611/hour (about $0.85)** before tax. This is a changing hourly quote, not a measured bill or cost per clip; loading and idle time also use paid compute.

## What this establishes

The batch ran on preemptible compute, exported playable clips and reused completed work. It did **not** encounter a provider-initiated reclamation. Lost-request and ambiguous-request handling were checked with local fixtures, not a live GPU interruption.

This is an eight-prompt, single-seed generation batch. It does not run the complete VBench sampling/scoring protocol, establish general video quality or support a leaderboard comparison. Inspect prompt alignment and motion yourself before using these short previews.

## Offline checks

**29 checks passed**, covering source identity, deterministic selection, request/download handling, MP4 verification, completed-clip reuse, changed or corrupt results, lost requests, export manifests and the Endpoint helper. Fixture videos are separate from the generated Wan clips above.

```bash
python3 scripts/prepare_data.py --verify
python3 src/generate.py --check-input
python3 -m unittest discover -s tests -v
```
