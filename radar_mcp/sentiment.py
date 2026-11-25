"""Sentiment of each comment: negative, neutral or positive.

Two backends behind one function, `classify`:

    transformer  a Hugging Face model (SENTIMENT_MODEL, default cardiffnlp/twitter-roberta-base-sentiment-latest),
                 trained on tweets, so it suits short comments. Runs on CPU. The default.
    vader        a word list with rules. Instant and dependency-light; the baseline to beat, and what tests use.

SENTIMENT_BACKEND picks one. To try a better model, change SENTIMENT_MODEL or add a backend here:
everything else only sees `classify`'s output.

    uv run python -m radar_mcp.sentiment --preload   # download the model (the Docker build does this)
    uv run python -m radar_mcp.sentiment "I love it" "This is a scam"
"""

from __future__ import annotations

import contextlib
import logging
import os
import sys
import threading

log = logging.getLogger("radar")

LABELS = ("negative", "neutral", "positive")
DEFAULT_MODEL = "cardiffnlp/twitter-roberta-base-sentiment-latest"
BATCH = 32
MAX_TOKENS = 64  # comments past this are cut; the start carries the tone (99.7% the same labels as 128, 24% faster)

_lock = threading.Lock()
_classifier = None


def backend() -> str:
    return os.environ.get("SENTIMENT_BACKEND", "transformer").strip().lower()


def model_name() -> str:
    return os.environ.get("SENTIMENT_MODEL", DEFAULT_MODEL) if backend() == "transformer" else "vader"


def _normalize(label: str) -> str:
    label = label.lower()
    return {"label_0": "negative", "label_1": "neutral", "label_2": "positive",
            "neg": "negative", "neu": "neutral", "pos": "positive"}.get(label, label)


def _load():
    global _classifier
    with _lock:
        if _classifier is not None:
            return _classifier
        if backend() == "vader":
            from vaderSentiment.vaderSentiment import SentimentIntensityAnalyzer
            _classifier = ("vader", SentimentIntensityAnalyzer())
        else:
            log.info("loading sentiment model %s", model_name())
            # In the MCP server stdout is the protocol channel: anything a library prints there breaks it.
            with contextlib.redirect_stdout(sys.stderr):
                from transformers import pipeline
                pipe = pipeline("text-classification", model=model_name(), top_k=None, truncation=True,
                                max_length=MAX_TOKENS, device=-1)
            _classifier = ("transformer", pipe)
        return _classifier


def classify(texts: list[str]) -> list[dict]:
    """One {"label", "score", "scores"} per text, in order. score is the chosen label's probability
    (transformer) or the size of VADER's compound score."""
    if not texts:
        return []
    kind, clf = _load()
    out = []
    if kind == "vader":
        for t in texts:
            c = clf.polarity_scores(t)["compound"]
            label = "positive" if c >= 0.05 else "negative" if c <= -0.05 else "neutral"
            out.append({"label": label, "score": round(abs(c), 3), "scores": {"compound": round(c, 3)}})
        return out
    cleaned = [t.strip()[:1000] or "." for t in texts]
    # Each distinct text once, shortest first: a batch is padded to its longest text, so batching
    # similar lengths together runs about 2.4x faster on a real comment section.
    unique = sorted(set(cleaned), key=len)
    by_text = {}
    for text, result in zip(unique, clf(unique, batch_size=BATCH)):
        scores = {_normalize(r["label"]): round(float(r["score"]), 4) for r in result}
        label = max(scores, key=scores.get)
        by_text[text] = {"label": label, "score": scores[label], "scores": scores}
    return [dict(by_text[t]) for t in cleaned]


def distribution(labels: list[str]) -> dict:
    n = len(labels)
    return {lab: (round(labels.count(lab) / n, 3) if n else 0.0) for lab in LABELS} | {"n": n}


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, stream=sys.stderr)
    args = sys.argv[1:]
    if args[:1] == ["--preload"]:
        _load()
        print(f"loaded {backend()} / {model_name()}")
    else:
        for text, r in zip(args, classify(args)):
            print(f"{r['label']:>8}  {r['score']:.2f}  {text}")
