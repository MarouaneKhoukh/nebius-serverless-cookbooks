"""Evaluate the same held-out examples before/after LoRA; render a branded report."""

from __future__ import annotations

import argparse
from collections import Counter
import csv
import html
import json
from pathlib import Path

MODEL = "Qwen/Qwen3-4B-Instruct-2507"
_source = Path(__file__).resolve().parent
_root = _source.parent if (_source.parent / "config").is_dir() else _source
LABELS = tuple(json.loads((_root / ("data/categories.json" if (_root / "data").is_dir() else "categories.json")).read_text()))
from data_prep import system_prompt
SYSTEM_PROMPT = system_prompt(LABELS)


def normalize(value: str) -> str:
    return value.strip().strip('"\'`').strip().removesuffix(".").strip()


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
    per_intent = {}
    for label in LABELS:
        tp=sum(r["expected"]==label and r["prediction"]==label for r in rows)
        fp=sum(r["expected"]!=label and r["prediction"]==label for r in rows)
        fn=sum(r["expected"]==label and r["prediction"]!=label for r in rows)
        precision=tp/(tp+fp) if tp+fp else 0.0
        recall=tp/(tp+fn) if tp+fn else 0.0
        per_intent[label]={"support":tp+fn,"precision":precision,"recall":recall,
                           "f1":2*precision*recall/(precision+recall) if precision+recall else 0.0}
    confusions=Counter((r["expected"],r["prediction"]) for r in rows if not r["correct"])
    return {"total": len(rows), "correct": count, "accuracy": count / len(rows),
            "macro_f1":sum(v["f1"] for v in per_intent.values())/len(LABELS),
            "per_intent":per_intent,
            "confusions":[{"expected":a,"predicted":b,"count":n} for (a,b),n in confusions.most_common(20)],
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
    for start in range(0, len(examples), 16):
        batch = examples[start:start + 16]
        texts = [tokenizer.apply_chat_template([
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": row["prompt"]},
        ], tokenize=False, add_generation_prompt=True) for row in batch]
        inputs = tokenizer(texts, padding=True, return_tensors="pt").to("cuda")
        if inputs["input_ids"].shape[1] + 32 > 1024:
            raise ValueError("An evaluation prompt exceeds the configured 1024-token sequence budget")
        with torch.inference_mode():
            outputs = model.generate(**inputs, do_sample=False, max_new_tokens=32,
                                     pad_token_id=tokenizer.pad_token_id)
        suffixes = outputs[:, inputs["input_ids"].shape[1]:]
        answers.extend(tokenizer.batch_decode(suffixes, skip_special_tokens=True))
        print(json.dumps({"event":"evaluation_progress","adapter":adapter is not None,
                          "completed":len(answers),"total":len(examples)}),flush=True)
    result = score(examples, answers)
    result.update({"model": model_name, "model_revision": revision, "adapter": adapter is not None,
                   "max_new_tokens": 32, "seed": 42,
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
<style>
*{{box-sizing:border-box}}
body{{margin:0;background:#f7f7f2;color:#232820;font:17px/1.5 system-ui,sans-serif}}
main{{max-width:1150px;margin:40px auto;padding:0 24px}}
header svg{{width:150px;height:auto;flex-shrink:0}}
header{{display:flex;gap:22px;align-items:center;flex-wrap:wrap}}
h1{{font-size:36px;line-height:1.15}}
.cards{{display:flex;gap:16px;flex-wrap:wrap}}
.card{{background:white;border:1px solid #d9ddcf;border-radius:16px;padding:22px;flex:1 1 220px;min-width:0}}
strong{{display:block;font-size:27px;overflow-wrap:anywhere}}
table{{border-collapse:collapse;width:100%;table-layout:fixed;background:white}}
td,th{{text-align:left;padding:12px;border-bottom:1px solid #e0e3d9;vertical-align:top;overflow-wrap:anywhere}}
th{{background:#e4f894;width:22%}}th:first-child{{width:34%}}
small{{color:#55604c}}.table{{max-width:100%}}
footer{{padding:24px 0}}code{{background:#eef0e8;padding:2px 5px;overflow-wrap:anywhere}}
@media(max-width:600px){{main{{margin:24px auto;padding:0 12px}}h1{{font-size:29px}}.cards{{gap:10px}}.card{{padding:16px}}strong{{font-size:25px}}td,th{{padding:8px 6px;font-size:13px}}}}
</style>
<main><header>{logo.read_text(encoding='utf-8')}<span>Powered by Nebius Serverless AI</span></header>
<h1>Fine-Tune Qwen and Resume Saved Training</h1>
<p>{escape(summary['model'])} · LoRA · Preemptible GPU Job</p><div class="cards">
<section class="card">Base model<strong>{percent(before)}</strong></section>
<section class="card">Fine-tuned adapter<strong>{percent(after)}</strong></section>
<section class="card">Training progress<strong>{summary['global_step']} / {summary['max_steps']} steps</strong><small>Restored from step {summary['resumed_from_step']}</small></section></div>
<p>{'Training completed.' if summary['completed'] else 'Controlled stop after a durable checkpoint. Start a new Job to resume.'} The recovery exercise uses a planned checkpoint stop. Scores cover the selected BANKING77 benchmark subset, not production banking logs.</p>
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
