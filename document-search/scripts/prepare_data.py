#!/usr/bin/env python3
"""Download the licensed Python reference corpus and verify its pinned files."""
from pathlib import Path
import argparse
import json
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from corpus import prepare


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--output-dir", type=Path, default=Path("data/documents"))
    p.add_argument("--cache-dir", type=Path, default=Path(".state/corpus-cache"))
    a = p.parse_args()
    try:
        result = prepare(a.output_dir, a.cache_dir)
        print(json.dumps({"dataset": result["dataset"], "version": result["version"],
                          "documents": len(result["documents"]), "output": str(a.output_dir),
                          "archive_sha256": result["archive_sha256"]}, indent=2))
    except (OSError, ValueError, KeyError) as exc:
        print("Error:", str(exc), file=sys.stderr)
        raise SystemExit(1)


if __name__ == "__main__":
    main()
