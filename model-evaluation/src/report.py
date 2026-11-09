"""Export an inspectable support-backlog result from verified saved predictions."""

from __future__ import annotations

from collections import Counter
import csv
import html
import io
import json
from pathlib import Path
import xml.etree.ElementTree as ET

from baseline import NAME as BASELINE_NAME


TITLE = "Classify a Support Backlog with Qwen"
FIELDS = ["id", "prompt", "expected", "predicted", "response", "valid", "truncated",
          "input_tokens", "output_tokens", "batch_id", "baseline_predicted", "correct",
          "baseline_correct", "needs_review", "review_reasons"]


def _json(path: Path, value) -> None:
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False, default=str) + "\n", encoding="utf-8")


def _csv(path: Path, records: list) -> None:
    stream = io.StringIO(newline="")
    writer = csv.DictWriter(stream, fieldnames=FIELDS, extrasaction="ignore")
    writer.writeheader()
    writer.writerows(records)
    path.write_text(stream.getvalue(), encoding="utf-8")


def _metrics(records: list, labels: list, *, baseline: bool = False) -> dict:
    records = [row for row in records if row["expected"]]
    if not records:
        return {"rows": 0, "correct": 0, "accuracy": None, "macro_f1": None, "per_class": {}}
    counts = {label: {"tp": 0, "fp": 0, "fn": 0, "support": 0} for label in labels}
    correct = 0
    for row in records:
        expected = row["expected"]
        predicted = row["baseline_predicted"] if baseline else (row["predicted"] if row["valid"] and not row["truncated"] else None)
        counts[expected]["support"] += 1
        if expected == predicted:
            correct += 1
            counts[expected]["tp"] += 1
        else:
            counts[expected]["fn"] += 1
            if predicted in counts:
                counts[predicted]["fp"] += 1
    per_class = {}
    for label, value in counts.items():
        tp, fp, fn = value["tp"], value["fp"], value["fn"]
        precision = tp / (tp + fp) if tp + fp else 0.0
        recall = tp / (tp + fn) if tp + fn else 0.0
        f1 = 2 * precision * recall / (precision + recall) if precision + recall else 0.0
        per_class[label] = {**value, "precision": precision, "recall": recall, "f1": f1}
    return {"rows": len(records), "correct": correct,
            "accuracy": correct / len(records) if records else None,
            "macro_f1": sum(row["f1"] for row in per_class.values()) / len(labels) if records and labels else None,
            "per_class": per_class}


def _logo(path: Path) -> str:
    """Keep the bundled artwork inline; reject active or external SVG content."""
    value = path.read_text(encoding="utf-8")
    tree = ET.fromstring(value)
    allowed_tags = {"svg", "g", "path", "rect", "circle", "ellipse", "line", "polyline", "polygon", "title", "desc"}
    allowed_attributes = {"width", "height", "viewBox", "fill", "fill-rule", "clip-rule", "d", "x", "y", "x1", "x2", "y1", "y2", "cx", "cy", "r", "rx", "ry", "points", "transform", "opacity", "stroke", "stroke-width", "stroke-linecap", "stroke-linejoin", "role", "aria-label"}
    if tree.tag.rsplit("}", 1)[-1] != "svg":
        raise ValueError("Logo must be SVG artwork")
    for element in tree.iter():
        if element.tag.rsplit("}", 1)[-1] not in allowed_tags:
            raise ValueError("Logo contains unsupported SVG elements")
        for key, content in element.attrib.items():
            if key not in allowed_attributes or "url(" in content.lower():
                raise ValueError("Logo contains active or external SVG attributes")
    return value


def _escape(value) -> str:
    return html.escape(str(value), quote=True)


def _percent(value) -> str:
    return "Not available" if value is None else f"{value:.1%}"


def _table(headers: list, rows: list) -> str:
    return "<div class='table-wrap'><table><thead><tr>" + "".join("<th>" + _escape(header) + "</th>" for header in headers) + "</tr></thead><tbody>" + "".join("<tr>" + "".join("<td>" + _escape(cell) + "</td>" for cell in row) + "</tr>" for row in rows) + "</tbody></table></div>"


def _html(summary: dict, records: list, logo: str) -> str:
    baseline = summary["baseline"]
    model = summary["metrics"]
    if not model["rows"]:
        comparison = "No expected labels were supplied for these saved requests, so accuracy and F1 are not available."
    elif baseline["complete"]:
        comparison = f"The CPU baseline scored {_percent(baseline['accuracy'])} accuracy and {_percent(baseline['macro_f1'])} macro F1 on the same {model['rows']} labelled requests."
    else:
        comparison = f"Baseline predictions cover {baseline['covered_rows']} of {len(records)} completed requests. A complete same-row comparison is not available."
    entries = []
    for row in records:
        status = "invalid" if not row["valid"] or row["truncated"] else ("unscored" if row["correct"] is None else ("correct" if row["correct"] else "mistake"))
        entries.append("<tr data-review='" + ("1" if row["needs_review"] else "0") + "' data-status='" + status
                       + "' data-mistake='" + ("1" if row["correct"] is False else "0") + "'>"
                       + "<td>" + _escape(row["id"]) + "</td><td class='request'>" + _escape(row["prompt"]) + "</td>"
                       + "<td>" + _escape(row["expected"] or "not provided") + "</td><td>" + _escape(row["predicted"] or "invalid")
                       + "<small>Raw output: " + _escape(row["response"]) + "</small></td>"
                       + "<td>" + _escape(row["baseline_predicted"] or "unavailable") + "</td>"
                       + "<td>" + _escape(row["review_reasons"] or "—") + "</td></tr>")
    per_class = [[label, item["support"], _percent(item["precision"]), _percent(item["recall"]), _percent(item["f1"])] for label, item in model["per_class"].items()]
    label_counts = [[label, summary["label_counts"]["expected"].get(label, 0), summary["label_counts"]["predicted"].get(label, 0)] for label in summary["labels"]]
    confusions = [[item["expected"], item["predicted"], item["count"]] for item in summary["confusions"][:20]]
    config = {key: summary[key] for key in ("model", "image", "dataset", "prompting", "contract_hash", "attempts", "timing", "cost")}
    return """<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>""" + TITLE + """</title><style>
:root{font:16px/1.55 system-ui,sans-serif;color:#202923;background:#f7f7ef}body{margin:0;padding:28px}main{max-width:1250px;margin:auto}header{display:flex;align-items:center;gap:24px;flex-wrap:wrap;border-bottom:1px solid #d6ddce;padding-bottom:22px}header svg{width:140px;height:auto}h1{font-size:clamp(28px,4vw,42px);line-height:1.15;margin:32px 0 12px}h2{margin-top:32px}p{max-width:1000px}a{color:#264523}nav{display:flex;gap:20px;flex-wrap:wrap;margin:20px 0}.cards{display:grid;grid-template-columns:repeat(auto-fit,minmax(180px,1fr));gap:12px}.card{background:#e4f99a;padding:18px;border-radius:10px}.card strong{display:block;font-size:27px}.table-wrap{overflow:auto;max-height:480px;background:white;border:1px solid #d7ddcf;border-radius:9px}table{width:100%;border-collapse:collapse;font-size:14px}th,td{padding:12px;text-align:left;vertical-align:top;border-bottom:1px solid #e3e7de}th{position:sticky;top:0;background:#edf0e6;white-space:nowrap}.request{min-width:240px;max-width:440px}td small{display:block;color:#586151;margin-top:8px;white-space:pre-wrap}input,select{font:inherit;padding:10px;border:1px solid #a7b39d;border-radius:6px}input{min-width:240px;flex:1}.filters{display:flex;gap:16px;align-items:end;flex-wrap:wrap;margin:16px 0}.filters label{display:flex;flex-direction:column;gap:5px}pre{white-space:pre-wrap;overflow-wrap:anywhere;background:#edf0e6;padding:18px;border-radius:9px;font-size:13px}footer{margin:32px 0;color:#586151}[hidden]{display:none!important}
</style></head><body><main><header>""" + logo + "<strong>Powered by Nebius Serverless AI</strong></header><h1>" + TITLE + "</h1>" \
        + "<p>Inspect the saved intent predictions, compare them with a trained CPU baseline and review the requests that need attention.</p>" \
        + "<div class='cards'><div class='card'>Requests saved<strong>" + str(summary["completed"]) + " / " + str(summary["total"]) + "</strong></div>" \
        + "<div class='card'>Qwen accuracy<strong>" + _percent(model["accuracy"]) + "</strong></div>" \
        + "<div class='card'>Qwen macro F1<strong>" + _percent(model["macro_f1"]) + "</strong></div>" \
        + "<div class='card'>Requests to review<strong>" + str(summary["review_rows"]) + "</strong></div></div>" \
        + "<p>" + str(summary["remaining"]) + " requests remain; " + str(summary["scored"]) + " saved requests have expected labels. Invalid or truncated outputs count as incorrect only when an expected label is available. " + _escape(comparison) + "</p>" \
        + "<nav aria-label='Download results'><a href='predictions.csv' download>All predictions CSV</a><a href='review.csv' download>Review queue CSV</a><a href='mistakes.csv' download>Mistakes CSV</a><a href='summary.json'>Summary JSON</a></nav>" \
        + "<h2>Review the predictions</h2><p>The review queue includes incorrect labels, invalid or truncated output, and disagreements between Qwen and the CPU baseline. These flags help you inspect results; they are not confidence scores. Without gold labels on your own data, disagreement alone does not tell you which model is right.</p>" \
        + "<div class='filters'><label>Search requests or labels<input id='search' type='search' placeholder='Search the saved results'></label><label>Show<select id='view'><option value='all'>All completed requests</option><option value='review'>Needs review</option><option value='mistake'>Incorrect predictions</option><option value='invalid'>Invalid or truncated output</option></select></label><span id='visible' aria-live='polite'></span></div>" \
        + "<div class='table-wrap'><table id='predictions'><thead><tr><th>ID</th><th>Request</th><th>Expected intent</th><th>Qwen</th><th>CPU baseline</th><th>Review reasons</th></tr></thead><tbody>" + "".join(entries) + "</tbody></table></div>" \
        + "<h2>Label counts</h2>" + _table(["Intent", "Expected", "Predicted"], label_counts) \
        + "<h2>Largest confusions</h2><p>Up to 20 incorrect expected/predicted pairs, counted across saved requests.</p>" + _table(["Expected", "Predicted", "Requests"], confusions) \
        + "<h2>Results by intent</h2>" + _table(["Intent", "Support", "Precision", "Recall", "F1"], per_class) \
        + "<h2>Run details</h2><p>Timing and pricing fields below are recorded metadata. Missing measured cost is left empty; no billing total is inferred from model speed or a quoted hourly rate.</p><pre>" + _escape(json.dumps(config, ensure_ascii=False, indent=2, default=str)) + "</pre>" \
        + "<footer>" + _escape(BASELINE_NAME) + ". Both models are scored on the same saved requests when complete baseline predictions are available. This sample measures this dataset and configuration, not general support quality.</footer></main>" \
        + """<script>
const search = document.getElementById('search');
const view = document.getElementById('view');
const rows = Array.from(document.querySelectorAll('#predictions tbody tr'));
function filterRows() {
  const term = search.value.toLocaleLowerCase();
  let count = 0;
  for (const row of rows) {
    const mode = view.value;
    const match = mode === 'all' || (mode === 'review' && row.dataset.review === '1') || (mode === 'mistake' && row.dataset.mistake === '1') || (mode === 'invalid' && row.dataset.status === 'invalid');
    row.hidden = !(match && row.textContent.toLocaleLowerCase().includes(term));
    if (!row.hidden) count++;
  }
  document.getElementById('visible').textContent = count + ' of ' + rows.length + ' shown';
}
search.addEventListener('input', filterRows);
view.addEventListener('change', filterRows);
filterRows();
</script></body></html>
"""


def export_results(output_dir: Path, rows: list, records: list, metadata: dict, logo_path: Path) -> dict:
    """Write reports for completed IDs; never infer results for unfinished rows."""
    output_dir = Path(output_dir)
    expected = {}
    for row in rows:
        if row["id"] in expected:
            raise ValueError("Input row IDs must be unique")
        expected[row["id"]] = row
    labels = list(metadata.get("labels") or sorted({row["expected"] for row in rows if row["expected"]}))
    if not labels:
        raise ValueError("Supply the full allowed labels in metadata when input has no expected labels")
    if len(set(labels)) != len(labels) or any(row["expected"] and row["expected"] not in labels for row in rows):
        raise ValueError("Labels must be unique and cover every expected intent")
    baseline_predictions = metadata.get("baseline_predictions") or {}
    supplied = {}
    for record in records:
        row_id = record["id"]
        if row_id in supplied or row_id not in expected:
            raise ValueError("Saved predictions must have unique IDs from this input")
        row = expected[row_id]
        if record.get("prompt", row["prompt"]) != row["prompt"] or record.get("expected", row["expected"]) != row["expected"]:
            raise ValueError("Saved prediction does not match its input row")
        predicted = record.get("predicted")
        valid = bool(record.get("valid", False)) and predicted in labels
        truncated = bool(record.get("truncated", False))
        correct = valid and not truncated and predicted == row["expected"] if row["expected"] else None
        baseline = baseline_predictions.get(row_id)
        baseline = baseline if baseline in labels else None
        reasons = []
        if not valid:
            reasons.append("invalid output")
        if truncated:
            reasons.append("truncated output")
        if correct is False:
            reasons.append("gold label mismatch")
        if valid and baseline is not None and predicted != baseline:
            reasons.append("model/baseline disagreement")
        supplied[row_id] = {**record, "id": row_id, "prompt": row["prompt"], "expected": row["expected"],
                            "predicted": predicted, "response": record.get("response", ""),
                            "valid": valid, "truncated": truncated, "baseline_predicted": baseline,
                            "correct": correct, "baseline_correct": baseline == row["expected"] if baseline is not None and row["expected"] else None,
                            "needs_review": bool(reasons), "review_reasons": "; ".join(reasons)}
    joined = [supplied[row["id"]] for row in rows if row["id"] in supplied]
    model_metrics = _metrics(joined, labels)
    coverage = sum(row["baseline_predicted"] is not None for row in joined)
    baseline_complete = bool(joined) and coverage == len(joined)
    baseline_metrics = _metrics(joined, labels, baseline=True) if baseline_complete else {"rows": 0, "correct": None, "accuracy": None, "macro_f1": None, "per_class": {}}
    confusions = Counter((row["expected"], row["predicted"] if row["valid"] and not row["truncated"] else ("<truncated>" if row["truncated"] else "<invalid>")) for row in joined if row["correct"] is False)
    cost = metadata.get("cost")
    cost = dict(cost) if isinstance(cost, dict) else {}
    cost.setdefault("measured_total_usd", None)
    timing = metadata.get("timing", metadata.get("timings", {}))
    summary = {
        "schema": 1, "title": TITLE, "total": len(rows), "input_rows": len(rows),
        "completed": len(joined), "remaining": len(rows) - len(joined), "complete": len(joined) == len(rows),
        "scored": model_metrics["rows"], "unlabelled": sum(not row["expected"] for row in joined),
        "correct": model_metrics["correct"], "accuracy": model_metrics["accuracy"], "macro_f1": model_metrics["macro_f1"],
        "invalid_labels": sum(not row["valid"] for row in joined), "truncated": sum(row["truncated"] for row in joined),
        "review_rows": sum(row["needs_review"] for row in joined), "mistakes": sum(row["correct"] is False for row in joined),
        "baseline_disagreements": sum(row["valid"] and row["baseline_predicted"] is not None and row["predicted"] != row["baseline_predicted"] for row in joined),
        "labels": labels, "metrics": model_metrics,
        "baseline": {"name": BASELINE_NAME, "covered_rows": coverage, "complete": baseline_complete, **baseline_metrics},
        "label_counts": {"expected": dict(sorted(Counter(row["expected"] for row in joined if row["expected"]).items())), "predicted": dict(sorted(Counter(row["predicted"] for row in joined if row["valid"] and not row["truncated"]).items()))},
        "confusions": [{"expected": expected_label, "predicted": predicted, "count": count} for (expected_label, predicted), count in sorted(confusions.items(), key=lambda item: (-item[1], item[0]))],
        "model": metadata.get("model"), "image": metadata.get("image"), "dataset": metadata.get("dataset"),
        "prompting": metadata.get("prompting"),
        "contract_hash": metadata.get("contract_hash"), "attempts": metadata.get("attempts", []), "timing": timing, "cost": cost,
        "input_tokens": sum(row.get("input_tokens") or 0 for row in joined), "output_tokens": sum(row.get("output_tokens") or 0 for row in joined),
        "review_note": "Review flags identify gold mismatches, invalid/truncated output or baseline disagreements; they are not confidence scores.",
    }
    logo = _logo(Path(logo_path))
    output_dir.mkdir(parents=True, exist_ok=True)
    _csv(output_dir / "predictions.csv", joined)
    _csv(output_dir / "review.csv", [row for row in joined if row["needs_review"]])
    _csv(output_dir / "mistakes.csv", [row for row in joined if row["correct"] is False])
    _json(output_dir / "summary.json", summary)
    (output_dir / "report.html").write_text(_html(summary, joined, logo), encoding="utf-8")
    return summary
