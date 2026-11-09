"""A CPU word/bigram multinomial Naive Bayes comparison trained on train only."""

from __future__ import annotations

from collections import Counter, defaultdict
import math
import re


NAME = "Word + bigram multinomial Naive Bayes (CPU)"


def _features(text: str) -> Counter:
    words = re.findall(r"[a-z0-9]+(?:'[a-z0-9]+)?", text.lower())
    return Counter(["w:" + word for word in words]
                   + ["b:" + left + " " + right for left, right in zip(words, words[1:])])


def predict(train_rows: list, rows: list, labels: list) -> dict[str, str]:
    """Fit a Laplace-smoothed model, then predict without reading rows' gold labels.

    ``train_rows`` must be the dataset's training split. ``rows`` can contain an
    ``expected`` field for later scoring, but this function never reads it.
    Ties follow the supplied label order, so results are reproducible.
    """
    labels = list(labels)
    if not labels or len(set(labels)) != len(labels) or any(not isinstance(label, str) or not label for label in labels):
        raise ValueError("Supply distinct, non-empty string labels")
    if not train_rows:
        raise ValueError("The baseline requires a separate, non-empty training split")
    vocabulary = set()
    label_documents = Counter()
    label_features = defaultdict(Counter)
    label_totals = Counter()
    seen = set()
    for row in train_rows:
        row_id, text, label = row["id"], row["prompt"], row["expected"]
        if row_id in seen or label not in labels or not isinstance(text, str) or not text.strip():
            raise ValueError("Training rows need unique IDs, text and an allowed expected label")
        seen.add(row_id)
        features = _features(text)
        vocabulary.update(features)
        label_documents[label] += 1
        label_features[label].update(features)
        label_totals[label] += sum(features.values())
    if not vocabulary:
        raise ValueError("Training text contains no usable words")
    size = len(vocabulary)
    priors = {label: math.log((label_documents[label] + 1) / (len(train_rows) + len(labels))) for label in labels}
    denominators = {label: math.log(label_totals[label] + size) for label in labels}
    predictions = {}
    for row in rows:
        row_id, text = row["id"], row["prompt"]
        if row_id in predictions or not isinstance(text, str) or not text.strip():
            raise ValueError("Prediction rows need unique IDs and non-empty text")
        if row_id in seen:
            raise ValueError("Training and prediction row IDs overlap; use disjoint dataset splits")
        features = {feature: count for feature, count in _features(text).items() if feature in vocabulary}
        scores = {
            label: priors[label] + sum(
                count * (math.log(label_features[label][feature] + 1) - denominators[label])
                for feature, count in features.items()
            )
            for label in labels
        }
        predictions[row_id] = max(labels, key=scores.__getitem__)
    return predictions
