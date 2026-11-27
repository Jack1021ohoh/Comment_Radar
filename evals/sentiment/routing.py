"""Try routing: non-English comments to the multilingual model, the rest to the current English model.

    uv run --with sentencepiece python -m evals.sentiment.routing
"""
import csv, contextlib, random, sys
from pathlib import Path

from transformers import pipeline

HERE = Path(__file__).parent
EN, XLM = "cardiffnlp/twitter-roberta-base-sentiment-latest", "cardiffnlp/twitter-xlm-roberta-base-sentiment"
LABELS = ("negative", "neutral", "positive")


def non_english(t: str) -> bool:
    letters = [c for c in t if c.isalpha()]
    return bool(letters) and sum(not c.isascii() for c in letters) / len(letters) > 0.5


def predict(model, texts):
    with contextlib.redirect_stdout(sys.stderr):
        pipe = pipeline("text-classification", model=model, truncation=True, max_length=64, device=-1)
    return [r["label"].lower() for r in pipe(texts, batch_size=32)]


def f1(gold, pred):
    out = []
    for l in LABELS:
        tp = sum(g == p == l for g, p in zip(gold, pred)); pr, rc = tp / max(1, pred.count(l)), tp / max(1, gold.count(l))
        out.append(2 * pr * rc / (pr + rc) if pr + rc else 0)
    return sum(out) / 3


rows = [r for r in csv.DictReader(open(HERE / "labels.csv")) if r["final"]]
texts, gold = [r["text"] for r in rows], [r["final"] for r in rows]
en, xlm = predict(EN, texts), predict(XLM, texts)
routed = [x if non_english(t) else e for t, e, x in zip(texts, en, xlm)]
print(f"{sum(map(non_english, texts))} of {len(texts)} comments routed to XLM")
for name, p in [("current (English)", en), ("XLM only", xlm), ("routed", routed)]:
    print(f"{name:18} accuracy {sum(a == b for a, b in zip(p, gold)) / len(gold):.1%}  macro-F1 {f1(gold, p):.3f}")

# paired comparison routed vs current: bootstrap CI of the accuracy difference, and exact McNemar
diff = [(r == g) - (e == g) for r, e, g in zip(routed, en, gold)]
random.seed(0)
boots = sorted(sum(random.choices(diff, k=len(diff))) / len(diff) for _ in range(5000))
b, c = diff.count(1), diff.count(-1)
from math import comb
p = min(1, 2 * sum(comb(b + c, k) for k in range(min(b, c) + 1)) / 2 ** (b + c)) if b + c else 1
print(f"routed - current: {sum(diff) / len(diff):+.1%}  95% CI [{boots[125]:+.1%}, {boots[4875]:+.1%}]  "
      f"fixed {b}, broke {c}, McNemar p = {p:.2f}")
hu = [i for i, r in enumerate(rows) if r.get("human_label")]
print(f"on your {len(hu)} labels: current {sum(en[i] == gold[i] for i in hu)}/{len(hu)}  routed {sum(routed[i] == gold[i] for i in hu)}/{len(hu)}")
