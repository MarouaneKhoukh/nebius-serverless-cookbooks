# Validation

## Live resume check: November 18, 2026

A resumed Wan batch reused 54 saved clips and generated three more, ending with 57 of the 200 inputs complete and 143 remaining. It reported `Generated 3; reused 54`. [Resume evidence](docs/resume-results/summary.json) · [Clip records](docs/resume-results/clips.csv).

| New clips | Reused clips | Completed | Remaining |
| ---: | ---: | ---: | ---: |
| 3 | 54 | 57 | 143 |

The hashes of all 54 original MP4s and completion records were unchanged. The shipped per-clip helpers decoded all 57 saved videos, with 49 frames each. `scripts/check_results.py` requires a complete 200-item batch, so this partial-set validation is not a full-batch checker pass.

The serving API address had changed. A probe without `--retry-lost` correctly refused a new generation for the unfinished request. The flagged invocation explicitly allowed replacement of that lost request for the 55th input, then saved the 55th–57th clips. The completed 54 clips were skipped.

The full 200-clip GPU run and the 20/180 exercise remain unverified live. These results do not establish a 200-clip duration, cost or long-run model stability.

## Runtime and measurements

- Runtime: `vllm/vllm-omni:v0.24.0`, `Wan-AI/Wan2.1-T2V-1.3B-Diffusers`, one preemptible H100, `gpu-h100-sxm`, preset `1gpu-16vcpu-200gb`, 500 GiB temporary disk.
- Generation: 832×480, 49 frames at 16 fps, 20 inference steps, guidance 5.0, flow shift 3.0 and boundary ratio 0.0. Each clip is 3.0625 seconds.
- Input: 200 distinct VBench prompts, 25 per category, with recorded generation seeds. Revision `fd18b3d055cb0fc6f066ca90fe2c3c8cbb698490`; CSV SHA256 `f38cf4cb4cb1b1deb18955567f17abe289157e2636a808776b275f41648ffbd6`. [Source and license](data/SOURCE.md).

| Measurement | Wall-clock seconds |
| --- | ---: |
| Endpoint creation to Model API ready | 395.37 |
| Unflagged resume probe | 1.01 |
| Resume command: 3 new, 54 reused | 49.83 |
| Resume command divided by 3 new clips | 16.61 |

Durations use `time.time()`. The Endpoint was already warm for the resume command; that time includes client checks, polling, downloads, per-clip validation and gallery export. Its average per new clip includes checking the saved set and is not a standalone model-throughput measurement.

The November 18 quote was USD 2.37/hour for the GPU plus USD 0.048611/hour for the disk: USD 2.418611/hour before tax. The GPU price cap was USD 2.50/hour, with disk charges additional. This is a quoted hourly rate, not an invoice or per-clip cost.

The original Endpoint was already STOPPED. The Endpoint used for this resume check was stopped and confirmed STOPPED at 2026-11-18T09:48:48.939942+00:00. Clips, records and galleries remain on the client’s disk.

## Other live attempts

On November 17, an earlier attempt saved 54 clips before the client connection failed after the Mac entered clamshell sleep. Its Endpoint was stopped and verified STOPPED. No provider preemption was established. Those saved files form the unchanged starting set for the resume check above.

A separate fresh attempt stopped after 26 completed clips. Those outputs are preserved separately and are excluded from the resume counts and timings.

## Local checks

33 tests passed with `python3 -m unittest discover -s tests`. They cover source selection, request/download handling, validation, reuse, corrupt or changed results, lost and ambiguous requests, exports and the Endpoint helper. The default input verifies as 200 distinct prompts, 25 per category.

A local API simulation used fixture-video bytes to exercise these paths:

| Local fixture run | New requests | Reused | Completed |
| --- | ---: | ---: | ---: |
| Full default batch | 200 | 0 | 200 |
| Unchanged rerun | 0 | 200 | 200 |
| Controlled limit | 20 | 0 | 20 |
| Resume from saved files | 180 | 20 | 200 |

The fixture clips were temporary test files, not Wan outputs. The live resume check above is separate from these simulations. No VBench quality score is calculated.

## Historical eight-clip run: November 9, 2026

An earlier eight-prompt selection generated two clips, then six while reusing two, then reported `Generated 0; reused 8`. Its full result checker verified source/input joins and hashes and decoded 49 frames from every MP4. The preemptible H100 Endpoint was stopped and verified STOPPED; no provider-initiated reclamation occurred. [Historical gallery](docs/sample-results/index.html) · [Manifest](docs/sample-results/clips.csv) · [Settings and counts](docs/sample-results/summary.json).

That run used the same image/model and generation settings, with an earlier eight-row input. Its quoted rate was USD 0.848611/hour before tax. Neither that historical price nor the eight-clip timings supplies a measurement for the current 200-clip default.
