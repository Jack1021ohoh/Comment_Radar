"""Sentiment of each comment: negative, neutral or positive.

Two backends behind one function, `classify`:

    transformer  a Hugging Face model (SENTIMENT_MODEL, default cardiffnlp/twitter-roberta-base-sentiment-latest),
                 trained on tweets, so it suits short comments. Runs on CPU. The default.
    vader        a word list with rules. Instant and dependency-light; the baseline to beat, and what tests use.
    routed       the transformer for most comments, and a multilingual model (SENTIMENT_MULTILINGUAL_MODEL, default
                 cardiffnlp/twitter-xlm-roberta-base-sentiment) for comments written mostly in non-Latin letters
                 (Russian, Chinese, Japanese...), which the English model calls neutral. On the 240-comment eval
                 (evals/sentiment) it scores 77.5% vs 75.4%: it fixed 6 of the 11 routed comments and broke 1.

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
DEFAULT_MULTILINGUAL = "cardiffnlp/twitter-xlm-roberta-base-sentiment"
BATCH = 32
MAX_TOKENS = 64  # comments past this are cut; the start carries the tone (99.7% the same labels as 128, 24% faster)

_lock = threading.Lock()
_classifier = None


def backend() -> str:
    return os.environ.get("SENTIMENT_BACKEND", "transformer").strip().lower()


def _main_model() -> str:
    return os.environ.get("SENTIMENT_MODEL", DEFAULT_MODEL)


def _multilingual_model() -> str:
    return os.environ.get("SENTIMENT_MULTILINGUAL_MODEL", DEFAULT_MULTILINGUAL)


def model_name() -> str:
    kind = backend()
    if kind == "vader":
        return "vader"
    if kind == "routed":
        return f"{_main_model()} + {_multilingual_model()} (non-Latin)"
    return _main_model()


def non_latin(text: str) -> bool:
    """True when most letters are outside A-Z (Cyrillic, CJK, Arabic...). Emoji, digits and accents on
    Latin letters barely count: 'café' stays Latin."""
    letters = [c for c in text if c.isalpha()]
    return bool(letters) and sum(not c.isascii() for c in letters) / len(letters) > 0.5


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
        elif backend() == "routed":
            _classifier = ("routed", (_pipeline(_main_model()), _pipeline(_multilingual_model())))
        else:
            _classifier = ("transformer", _pipeline(_main_model()))
        return _classifier


def _pipeline(model: str):
    log.info("loading sentiment model %s", model)
    # In the MCP server stdout is the protocol channel: anything a library prints there breaks it.
    with contextlib.redirect_stdout(sys.stderr):
        from transformers import pipeline
        return pipeline("text-classification", model=model, top_k=None, truncation=True,
                        max_length=MAX_TOKENS, device=-1)


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
    if kind == "routed":
        main, multilingual = clf
        by_text = _run(main, [t for t in cleaned if not non_latin(t)]) | _run(multilingual, [t for t in cleaned if non_latin(t)])
    else:
        by_text = _run(clf, cleaned)
    return [dict(by_text[t]) for t in cleaned]


def _run(pipe, texts: list[str]) -> dict:
    """text -> result. Each distinct text once, shortest first: a batch is padded to its longest text, so
    batching similar lengths together runs about 2.4x faster on a real comment section."""
    unique = sorted(set(texts), key=len)
    by_text = {}
    if not unique:
        return by_text
    for text, result in zip(unique, pipe(unique, batch_size=BATCH)):
        scores = {_normalize(r["label"]): round(float(r["score"]), 4) for r in result}
        label = max(scores, key=scores.get)
        by_text[text] = {"label": label, "score": scores[label], "scores": scores}
    return by_text


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
