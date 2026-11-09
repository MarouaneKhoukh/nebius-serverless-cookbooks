"""Evaluate the same held-out examples before/after LoRA; render a branded report."""

from __future__ import annotations

import argparse
import csv
import html
import json
from pathlib import Path

MODEL = "Qwen/Qwen2.5-0.5B-Instruct"
LABELS = {"billing", "technical", "account"}
SYSTEM_PROMPT = "Classify support tickets as billing, technical, or account. Return only the category."


def normalize(value: str) -> str:
    return value.strip().lower().strip('"\'`').strip().removesuffix(".").strip()


def read_examples(path: Path) -> list[dict]:
    with path.open(newline="", encoding="utf-8") as source:
        reader = csv.DictReader(source)
        if not {"id", "prompt", "expected"}.issubset(reader.fieldnames or []):
            raise ValueError("Test CSV requires id,prompt,expected columns")
        examples = list(reader)
    ids = set()
    for row in examples:
        if not row["id"] or row["id"] in ids or not row["prompt"].strip() or row["expected"] not in LABELS:
            raise ValueError("Test data has duplicate/empty IDs, empty prompts or invalid expected labels")
        ids.add(row["id"])
    if not examples:
        raise ValueError("Test CSV is empty")
    return examples


def score(examples: list[dict], answers: list[str]) -> dict:
    if len(examples) != len(answers):
        raise ValueError("Each example needs one prediction")
    rows = []
    for example, answer in zip(examples, answers):
        prediction = normalize(answer)
        rows.append({**example, "response": answer, "prediction": prediction,
                     "valid_label": prediction in LABELS,
                     "correct": prediction == example["expected"]})
    count = sum(row["correct"] for row in rows)
    return {"total": len(rows), "correct": count, "accuracy": count / len(rows),
            "invalid_predictions": sum(not row["valid_label"] for row in rows), "predictions": rows}


def evaluate(model_name: str, examples: list[dict], adapter: Path | None = None, revision: str | None = None) -> dict:
    import gc
    import torch
    from transformers import AutoModelForCausalLM, AutoTokenizer

    if not torch.cuda.is_available():
        raise RuntimeError("Run model evaluation inside the GPU Job")
    torch.manual_seed(42)
    tokenizer = AutoTokenizer.from_pretrained(model_name, revision=revision)
    tokenizer.padding_side = "left"
    if tokenizer.pad_token_id is None:
        tokenizer.pad_token = tokenizer.eos_token
    model = AutoModelForCausalLM.from_pretrained(model_name, revision=revision, torch_dtype=torch.bfloat16).to("cuda")
    if adapter is not None:
        from peft import PeftModel
        model = PeftModel.from_pretrained(model, str(adapter))
    model.eval()
    answers = []
    torch.cuda.reset_peak_memory_stats()
    for start in range(0, len(examples), 4):
        batch = examples[start:start + 4]
        texts = [tokenizer.apply_chat_template([
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": row["prompt"]},
        ], tokenize=False, add_generation_prompt=True) for row in batch]
        inputs = tokenizer(texts, padding=True, return_tensors="pt").to("cuda")
        with torch.inference_mode():
            outputs = model.generate(**inputs, do_sample=False, max_new_tokens=16,
                                     pad_token_id=tokenizer.pad_token_id)
        suffixes = outputs[:, inputs["input_ids"].shape[1]:]
        answers.extend(tokenizer.batch_decode(suffixes, skip_special_tokens=True))
    result = score(examples, answers)
    result.update({"model": model_name, "model_revision": revision, "adapter": adapter is not None,
                   "max_new_tokens": 16, "seed": 42,
                   "peak_allocated_bytes": torch.cuda.max_memory_allocated()})
    del model, tokenizer
    gc.collect()
    torch.cuda.empty_cache()
    return result


def render_report(before: dict, after: dict | None, summary: dict, logo: Path) -> str:
    escape = html.escape
    def percent(result):
        return f"{result['accuracy']:.1%} ({result['correct']}/{result['total']})" if result else "Pending resume"
    by_id = {row["id"]: row for row in after["predictions"]} if after else {}
    rows = "".join(
        f"<tr><td>{escape(row['prompt'])}</td><td>{escape(row['expected'])}</td>"
        f"<td>{escape(row['prediction'])}</td><td>{escape(by_id.get(row['id'], {}).get('prediction', 'Pending'))}</td></tr>"
        for row in before["predictions"]
    )
    return f"""<!doctype html><html lang="en"><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><title>Fine-Tune Qwen and Resume Saved Training</title>
<style>body{{margin:0;background:#f7f7f2;color:#232820;font:17px/1.5 system-ui,sans-serif}}main{{max-width:1150px;margin:40px auto;padding:0 24px}}header svg{{width:150px;height:auto}}header{{display:flex;gap:22px;align-items:center}}h1{{font-size:36px;line-height:1.15}}.cards{{display:flex;gap:16px;flex-wrap:wrap}}.card{{background:white;border:1px solid #d9ddcf;border-radius:16px;padding:22px;flex:1;min-width:190px}}strong{{display:block;font-size:27px}}table{{border-collapse:collapse;width:100%;background:white}}td,th{{text-align:left;padding:12px;border-bottom:1px solid #e0e3d9}}th{{background:#e4f894}}small{{color:#55604c}}.table{{overflow:auto}}footer{{padding:24px 0}}code{{background:#eef0e8;padding:2px 5px}}</style>
<main><header>{logo.read_text(encoding='utf-8')}<span>Powered by Nebius Serverless AI</span></header>
<h1>Fine-Tune Qwen and Resume Saved Training</h1>
<p>{escape(summary['model'])} · LoRA · Preemptible GPU Job</p><div class="cards">
<section class="card">Base model<strong>{percent(before)}</strong></section>
<section class="card">Fine-tuned adapter<strong>{percent(after)}</strong></section>
<section class="card">Training progress<strong>{summary['global_step']} / {summary['max_steps']} steps</strong><small>Restored from step {summary['resumed_from_step']}</small></section></div>
<p>{'Training completed.' if summary['completed'] else 'Controlled stop after a durable checkpoint. Start a new Job to resume.'} The recovery exercise uses a planned checkpoint stop. Scores cover only the included example requests.</p>
<h2>Results on the Test Examples</h2><div class="table"><table><thead><tr><th>Support request</th><th>Expected</th><th>Before</th><th>After</th></tr></thead><tbody>{rows}</tbody></table></div>
<footer>Powered by Nebius Serverless AI</footer></main></html>"""


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--before", type=Path, required=True)
    parser.add_argument("--after", type=Path)
    parser.add_argument("--summary", type=Path, required=True)
    parser.add_argument("--logo", type=Path, required=True)
    parser.add_argument("--output", type=Path, default=Path("report.html"))
    args = parser.parse_args()
    args.output.write_text(render_report(json.loads(args.before.read_text()),
        json.loads(args.after.read_text()) if args.after else None,
        json.loads(args.summary.read_text()), args.logo), encoding="utf-8")


if __name__ == "__main__":
    main()
