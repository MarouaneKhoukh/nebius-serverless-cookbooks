# Recorded Python documentation retrieval

These files came from indexing the 55-document Python 3.13.9 corpus with Qwen3-Embedding-0.6B on Nebius Serverless AI, then running the twelve FAQ source checks.

- `retrieval-checks.html` and `retrieval-checks.json`: Qwen and BM25 rankings, returned passages and source-level results for every question.
- `search.html` and `search.json`: the recorded “How do I copy a file?” search.
- `index-manifest.json`: the original index's completeness, model and corpus fingerprint.
- `corpus-source.json` and `queries.json`: pinned source files, questions and attribution.
- `DATA_LICENSE` and `DATA_SOURCE.md`: retained Python documentation license and provenance.

The full 2,138-vector collection and per-chunk working files are not included in this lightweight report sample. It is not a loadable vector index. Run the cookbook to create `vectors.jsonl`, `metadata.jsonl` and the complete saved collection locally.

These twelve source checks are not a blind benchmark or exhaustive relevance judgments. An alternative returned document can also be relevant. No GPU cost or general quality advantage is inferred from these counts.
