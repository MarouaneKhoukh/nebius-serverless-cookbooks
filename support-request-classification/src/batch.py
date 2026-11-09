#!/usr/bin/env python3
"""CSV prompts → CSV responses; reruns reuse completed local records."""

import argparse
import os
from pathlib import Path
import sys

from runner import Endpoint, MODEL, RecipeError, brand_svg, load_rows, render_report, run_rows, saved_records, settings_for, write_csv, write_json


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, default=Path("data/prompts.csv"))
    parser.add_argument("--output-dir", type=Path, default=Path("results"))
    parser.add_argument("--model", default=MODEL)
    parser.add_argument("--model-revision", default=os.environ.get("MODEL_REVISION", ""))
    parser.add_argument("--limit", type=int, help="Process at most N unfinished rows; rerun without this flag to continue")
    parser.add_argument("--readiness-timeout", type=float, default=900)
    args = parser.parse_args(argv)
    try:
        rows = load_rows(args.input)
        brand_svg()  # Fail before paid inference if the result artifact cannot be built.
        endpoint = Endpoint.from_environment()
        endpoint.wait(args.model, deadline=args.readiness_timeout)
        settings = settings_for(args.model, args.model_revision)
        try:
            records = run_rows(rows, args.output_dir, settings, endpoint.complete, limit=args.limit)
        except RecipeError:
            # The authoritative per-row files are already durable; export their current state.
            records = saved_records(rows, args.output_dir)
            if records:
                write_csv(args.output_dir / "responses.csv", ["id", "prompt", "response", "label"], records)
            raise
        summary = {"input_rows": len(rows), "completed": len(records), "remaining": len(rows) - len(records), "invalid_labels": sum(record.get("label") is None for record in records), "model": args.model}
        write_csv(args.output_dir / "responses.csv", ["id", "prompt", "response", "label"], records)
        write_json(args.output_dir / "summary.json", summary)
        render_report(args.output_dir / "report.html", "Classify Support Requests with Qwen", f"{len(records)} / {len(rows)} requests saved · {summary['remaining']} remaining · {args.model}", ["id", "prompt", "response", "label"], records)
        print(f"Wrote {args.output_dir / 'responses.csv'} and {args.output_dir / 'report.html'}")
        return 0
    except (RecipeError, OSError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
