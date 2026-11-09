#!/usr/bin/env python3
"""Run a held-out classification dataset and score predictions against labels."""

import argparse
import os
from pathlib import Path
import sys

from runner import Endpoint, LABELS, MODEL, RecipeError, brand_svg, load_rows, render_report, run_rows, saved_records, settings_for, write_csv, write_json


def score(records: list[dict], total: int) -> tuple[dict, list[dict]]:
    comparisons = [{**record, "predicted": record.get("label") or "invalid", "correct": bool(record.get("label") == record["expected"])} for record in records]
    correct = sum(record["correct"] for record in comparisons)
    matrix = {expected: {predicted: 0 for predicted in (*LABELS, "invalid")} for expected in LABELS}
    for record in comparisons:
        matrix[record["expected"]][record["predicted"]] += 1
    summary = {"total_examples": total, "evaluated_examples": len(comparisons), "remaining": total - len(comparisons), "complete": total == len(comparisons), "correct": correct, "incorrect": len(comparisons) - correct, "invalid_predictions": sum(record["predicted"] == "invalid" for record in comparisons), "accuracy": correct / len(comparisons) if comparisons else None, "confusion_matrix": matrix}
    return summary, comparisons


def write_outputs(directory: Path, records: list[dict], total: int, model: str) -> None:
    summary, comparisons = score(records, total)
    summary["model"] = model
    write_json(directory / "scores.json", summary)
    write_csv(directory / "predictions.csv", ["id", "prompt", "expected", "predicted", "response", "correct"], comparisons)
    write_csv(directory / "mistakes.csv", ["id", "prompt", "expected", "predicted", "response"], [record for record in comparisons if not record["correct"]])
    value = "n/a" if summary["accuracy"] is None else f"{summary['accuracy']:.1%}"
    scope = "complete" if summary["complete"] else "partial — resume before comparing"
    render_report(directory / "report.html", "Evaluate a Model on Your Own Examples", f"Accuracy: {value} · {summary['correct']} / {len(records)} correct · {total} total examples · {scope}", ["id", "prompt", "expected", "predicted", "correct"], comparisons)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, default=Path("data/evaluation.csv"))
    parser.add_argument("--output-dir", type=Path, default=Path("results"))
    parser.add_argument("--model", default=MODEL)
    parser.add_argument("--model-revision", default=os.environ.get("MODEL_REVISION", ""))
    parser.add_argument("--limit", type=int, help="Evaluate at most N unfinished examples")
    parser.add_argument("--readiness-timeout", type=float, default=900)
    args = parser.parse_args(argv)
    try:
        rows = load_rows(args.input, evaluation=True)
        brand_svg()
        endpoint = Endpoint.from_environment()
        endpoint.wait(args.model, deadline=args.readiness_timeout)
        try:
            records = run_rows(rows, args.output_dir, settings_for(args.model, args.model_revision), endpoint.complete, limit=args.limit)
        except RecipeError:
            records = saved_records(rows, args.output_dir)
            if records:
                write_outputs(args.output_dir, records, len(rows), args.model)
            raise
        write_outputs(args.output_dir, records, len(rows), args.model)
        summary, _ = score(records, len(rows))
        print(f"Evaluated {len(records)} / {len(rows)}. Accuracy: {summary['accuracy']:.1%}. Invalid responses count as incorrect.")
        print(f"Wrote {args.output_dir / 'scores.json'} and {args.output_dir / 'report.html'}")
        return 0
    except (RecipeError, OSError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
