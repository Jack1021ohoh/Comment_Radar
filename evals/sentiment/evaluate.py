"""Score sentiment models on the hand-labelled set (labels.csv, column `final`).

    uv run python -m evals.sentiment.evaluate vader transformer:cardiffnlp/twitter-xlm-roberta-base-sentiment
    (run from the repo root; `transformer` alone = the current default model)
"""
import csv, importlib, os, sys, time
from collections import Counter
from pathlib import Path

HERE = Path(__file__).parent
LABELS = ("negative", "neutral", "positive")


def run(spec, rows):
    backend, _, model = spec.partition(":")
    os.environ["SENTIMENT_BACKEND"] = backend
    if model: os.environ["SENTIMENT_MODEL"] = model
    else: os.environ.pop("SENTIMENT_MODEL", None)
    from radar_mcp import sentiment
    importlib.reload(sentiment)
    sentiment.classify(["warm up"])
    t = time.perf_counter()
    preds = [p["label"] for p in sentiment.classify([r["text"] for r in rows])]
    secs = time.perf_counter() - t
    gold = [r["final"] for r in rows]
    acc = sum(p == g for p, g in zip(preds, gold)) / len(rows)
    f1s = []
    for lab in LABELS:
        tp = sum(p == g == lab for p, g in zip(preds, gold))
        prec = tp / max(1, preds.count(lab)); rec = tp / max(1, gold.count(lab))
        f1s.append(2 * prec * rec / (prec + rec) if prec + rec else 0)
    by_kind = {k: sum(p == r["final"] for p, r in zip(preds, rows) if r["kind"] == k) / n
               for k, n in Counter(r["kind"] for r in rows).items()}
    errs = Counter((g, p) for g, p in zip(gold, preds) if g != p).most_common(3)
    return {"model": sentiment.model_name(), "acc": acc, "macro_f1": sum(f1s) / 3, "ms_per_comment": 1000 * secs / len(rows),
            "by_kind": by_kind, "top_errors": errs}


if __name__ == "__main__":
    rows = [r for r in csv.DictReader(open(HERE / "labels.csv")) if r.get("final")]
    print(f"{len(rows)} labelled comments")
    for spec in sys.argv[1:] or ["vader", "transformer"]:
        m = run(spec, rows)
        kinds = "  ".join(f"{k} {v:.0%}" for k, v in sorted(m["by_kind"].items()))
        print(f"\n{m['model']}\n  accuracy {m['acc']:.1%}   macro-F1 {m['macro_f1']:.3f}   {m['ms_per_comment']:.1f} ms/comment")
        print(f"  {kinds}\n  most common errors (gold -> predicted): {m['top_errors']}")
