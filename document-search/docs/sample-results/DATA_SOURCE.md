# Python documentation corpus

The collection contains **55 standard-library reference documents from Python 3.13.9**, published by the Python Software Foundation and contributors.

- Official source: [Python 3.13.9 plain-text documentation](https://docs.python.org/ftp/python/doc/3.13.9/python-3.13.9-docs-text.zip).
- Corresponding CPython release commit: `8183fa5e3f78ca6ab862de7fb8b14f3d929421e0` (`v3.13.9`).
- Archive SHA-256: `2522c3aee3c6617e99f7db5e43356471108739e35fe8a97b5d10da33832ff141`.
- License: Python Software Foundation License Version 2. Documentation examples are additionally available under the Zero-Clause BSD license. The [upstream license and notices](https://docs.python.org/release/3.13.9/license.html) are retained in the recipe’s `data/LICENSE` and copied to prepared data and results as `DATA_LICENSE`.

`source.json` pins the archive size, SHA-256, exact member names, document hashes and original URLs. `scripts/prepare_data.py` verifies these before writing the corpus. Text is taken from the official plain-text export; surrounding whitespace is trimmed and a final newline is added. No document claims to be a Nebius policy. The generated files are deliberately outside Git; a fresh checkout downloads the same pinned corpus.

## Retrieval checks

`queries.json` contains **12 original questions from the Python Library and Extension FAQ**, not invented customer conversations. The pinned FAQ is [available in CPython](https://github.com/python/cpython/blob/8183fa5e3f78ca6ab862de7fb8b14f3d929421e0/Doc/faq/library.rst). FAQ answer text is **excluded** from the indexed corpus.

Expected source documents were selected from standard-library modules named in those FAQ answers, restricted to this collection. A hit means that at least one expected reference document appears among the retrieved chunks. These checks are not exhaustive relevance judgments, a blind benchmark or a score for generated answers. A different returned document may also be useful. Read the retrieved passages, and evaluate your own queries before choosing a search method.

BM25 and Qwen use the same chunks and the same source-level checks. The CPU baseline is included so that the recipe does not assume a GPU model is the best answer for every query.

## Reusing this corpus

Retain the PSF notices, license and this account of the changes when redistributing passages or reports. `source.json` identifies the original material. Neither Python nor the PSF endorses this cookbook.
