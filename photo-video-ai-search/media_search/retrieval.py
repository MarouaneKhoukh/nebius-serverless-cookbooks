"""Combine visual similarity with descriptive names without inventing confidence.

Qwen cosine similarity is a ranking signal, not a calibrated yes/no answer. A
photo named ``coffee beans`` should remain an explicit name match for ``coffee``
even when its image/text cosine is just below a configured display heuristic.
The image vectors and their raw scores are deliberately left unchanged.
"""

from collections.abc import Iterable, Mapping
import math
from pathlib import PurePosixPath
import re
import unicodedata
from urllib.parse import unquote


# These are search wrappers, not visual concepts. In particular, negations,
# colors and objects stay in the query: "coffee without milk" must not become
# an exact name match for a picture simply called "coffee".
_WRAPPERS = frozenset({
    "a", "an", "the", "of", "for", "some", "my", "me", "please", "show",
    "find", "search", "looking", "look", "image", "images", "photo", "photos",
    "picture", "pictures", "photograph", "photographs",
})
_WORDS = re.compile(r"[^\W_]+", re.UNICODE)
NAME_BOOST = 0.15


def _singular(word: str) -> str:
    """Handle common labels (beans/cities), without substring or fuzzy matches."""
    if len(word) > 4 and word.endswith("ies"):
        return word[:-3] + "y"
    if len(word) > 3 and word.endswith("s") and not word.endswith(("ss", "us", "is")):
        return word[:-1]
    return word


def terms(text: object) -> frozenset[str]:
    if not isinstance(text, str):
        return frozenset()
    text = unicodedata.normalize("NFKC", text).casefold()
    return frozenset(_singular(word) for word in _WORDS.findall(text)
                     if word not in _WRAPPERS)


def _name_terms(item: Mapping) -> frozenset[str]:
    # A local file path/URL/extension is not descriptive metadata. Only the
    # decoded basename contributes alongside the human-readable title.
    source = item.get("source_name")
    basename = PurePosixPath(unquote(source).replace("\\", "/")).stem if isinstance(source, str) else ""
    return terms(item.get("title")) | terms(basename)


def _finite_score(value: object) -> float | None:
    if type(value) in {int, float} and math.isfinite(value):
        return float(value)
    return None


def rank_results(query: str, items: Iterable[Mapping], *, semantic_threshold: float = 0.25,
                 limit: int | None = None) -> dict:
    """Annotate and rank retrieved candidates; never mutate saved metadata.

    Ranking is raw cosine + at most 0.15 for query-word coverage in a title or
    filename. A ``named`` match covers every meaningful query word. A
    ``semantic`` match exceeds the configurable cosine heuristic; neither label
    asserts visual certainty. Other candidates remain available as ``related``.
    All raw scores are preserved for diagnostics, and are never percentages.
    The default cutoff separates the positive and absent queries in the bundled
    four-image sample evaluation. It is not a universal relevance guarantee.

    This operates on the supplied candidate set. Callers should retrieve a
    wider pool than the displayed page before applying the requested limit.
    """
    if not math.isfinite(semantic_threshold) or not -1 <= semantic_threshold <= 1:
        raise ValueError("Semantic threshold must be a finite cosine between -1 and 1.")
    if limit is not None and limit < 1:
        raise ValueError("Result limit must be positive.")
    query_terms = terms(query)
    ranked = []
    for original in items:
        item = dict(original)
        score = _finite_score(item.get("score"))
        matched = query_terms & _name_terms(item)
        coverage = len(matched) / len(query_terms) if query_terms else 0.0
        named = bool(query_terms) and query_terms <= _name_terms(item)
        match_type = ("named" if named else "semantic" if score is not None
                      and score >= semantic_threshold else "related")
        # A missing/invalid score is not promoted over valid vector results.
        # Its name evidence can still be inspected; normal vector candidates
        # always carry an actual finite score from Qdrant.
        ranking_score = (score if score is not None else -1.0) + NAME_BOOST * coverage
        item.update(match_type=match_type, matched_terms=sorted(matched),
                    metadata_coverage=coverage, semantic_score=score,
                    ranking_score=ranking_score)
        ranked.append(item)
    # Qualifying matches get limited slots before rejected diagnostic candidates.
    # Python's stable sort preserves vector order for exact ties.
    ranked.sort(key=lambda item: (item["match_type"] != "related", item["ranking_score"]),
                reverse=True)
    if limit is not None:
        ranked = ranked[:limit]
    matched_items = [item for item in ranked if item["match_type"] != "related"]
    basis = ("named" if any(item["match_type"] == "named" for item in matched_items)
             else "semantic" if matched_items else "related" if ranked else "empty")
    return {"items": ranked, "match_found": bool(matched_items), "match_basis": basis,
            "matched_count": len(matched_items),
            "best_score": max((item["semantic_score"] for item in ranked
                               if item["semantic_score"] is not None), default=None)}
