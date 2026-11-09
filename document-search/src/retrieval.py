"""A transparent lexical baseline and source-level retrieval checks."""
from __future__ import annotations

from collections import Counter
import json
import math
from pathlib import Path
import re


def terms(text: str) -> list[str]:
    return re.findall(r"[a-z][a-z0-9_]+", text.lower())


class BM25:
    """Standard BM25 over the same chunks used by the embedding search."""
    def __init__(self, records: list[dict], *, k1: float = 1.5, b: float = 0.75):
        if not records:
            raise ValueError("The collection has no chunks.")
        self.records, self.k1, self.b = records, k1, b
        self.counts = [Counter(terms(record["text"])) for record in records]
        self.lengths = [sum(count.values()) for count in self.counts]
        self.average = sum(self.lengths) / len(self.lengths) or 1.0
        frequencies = Counter(term for count in self.counts for term in count)
        self.idf = {term: math.log(1 + (len(records) - count + 0.5) / (count + 0.5))
                    for term, count in frequencies.items()}

    def search(self, query: str, *, top_k: int = 5) -> list[dict]:
        query_terms = set(terms(query))
        scored = []
        for record, counts, length in zip(self.records, self.counts, self.lengths):
            normalizer = self.k1 * (1 - self.b + self.b * length / self.average)
            score = sum(self.idf.get(term, 0) * counts[term] * (self.k1 + 1)
                        / (counts[term] + normalizer)
                        for term in query_terms if counts[term])
            scored.append({**{key: record[key] for key in
                              ("id", "source", "chunk_index", "text", "source_url", "title") if key in record},
                           "score": score})
        return sorted(scored, key=lambda record: (-record["score"], record["id"]))[:top_k]


def load_queries(path: Path, sources: set[str]) -> tuple[list[dict], dict]:
    document = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(document, dict) or not isinstance(document.get("queries"), list):
        raise ValueError("Query file needs an object with a queries array.")
    result, seen = [], set()
    for row in document["queries"]:
        if not isinstance(row, dict) or not isinstance(row.get("id"), str) or not row["id"] or row["id"] in seen:
            raise ValueError("Query IDs must be nonempty and unique.")
        if not isinstance(row.get("text"), str) or not row["text"].strip() or len(row["text"].split()) > 500:
            raise ValueError("Queries need nonempty text of at most 500 words.")
        expected = row.get("expected_sources")
        if (not isinstance(expected, list) or not expected
                or any(not isinstance(value, str) or value not in sources for value in expected)):
            raise ValueError("Each query needs expected sources present in this corpus.")
        result.append(row)
        seen.add(row["id"])
    if not result:
        raise ValueError("No query checks were supplied.")
    return result, {key: value for key, value in document.items() if key != "queries"}


def source_metrics(matches: list[dict], expected: list[str]) -> dict:
    ranks = [i + 1 for i, item in enumerate(matches) if item["source"] in expected]
    first = min(ranks) if ranks else None
    return {"hit_at_1": first == 1, "hit_at_k": bool(ranks),
            "reciprocal_rank_at_k": 1 / first if first else 0.0}


def aggregate(rows: list[dict], key: str, top_k: int) -> dict:
    return {"queries": len(rows), "top_k": top_k,
            "hit_at_1": sum(row[key]["hit_at_1"] for row in rows) / len(rows),
            "hit_at_k": sum(row[key]["hit_at_k"] for row in rows) / len(rows),
            "mean_reciprocal_rank_at_k": sum(row[key]["reciprocal_rank_at_k"] for row in rows) / len(rows),
            "scoring_unit": "expected source document, not a graded answer or passage"}
