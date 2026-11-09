#!/usr/bin/env python3
"""Prepare a checksum-verified BANKING77 test CSV without a GPU."""

from __future__ import annotations

import argparse
import csv
import os
from pathlib import Path
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from dataset import DatasetError, load_dataset


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--limit", type=int, default=0, help="Test rows to prepare; 0 means all 3,080")
    parser.add_argument("--seed", type=int, default=42, help="Deterministic shuffle seed")
    parser.add_argument("--output", type=Path, default=Path("data/input.csv"))
    parser.add_argument("--cache-dir", type=Path, default=Path(".state/data"))
    args = parser.parse_args(argv)
    temporary = None
    try:
        rows, labels, provenance, _train_rows = load_dataset(args.cache_dir, args.limit, args.seed)
        if args.output.is_symlink():
            raise DatasetError("Output CSV must not be a symlink")
        args.output.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile("w", encoding="utf-8", newline="", dir=args.output.parent, prefix=".prepared-", delete=False) as stream:
            temporary = Path(stream.name)
            writer = csv.DictWriter(stream, fieldnames=["id", "prompt", "expected"], lineterminator="\n")
            writer.writeheader()
            writer.writerows(rows)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, args.output)
        temporary = None
        print(f"Prepared {len(rows)} test rows across the {len(labels)}-intent taxonomy: {args.output}")
        print(f"BANKING77 revision: {provenance['revision']}; shuffle seed: {args.seed}")
        print(f"Input SHA-256: {provenance['input_sha256']}")
        print("Training rows are separate and are not included in this CSV. Attribution: data/SOURCE.md; CC BY 4.0: data/LICENSE.")
        return 0
    except (DatasetError, OSError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


if __name__ == "__main__":
    raise SystemExit(main())
