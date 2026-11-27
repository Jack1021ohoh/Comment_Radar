"""Build a labelling sheet from cached threads: a stratified sample with the current model's guess filled in.

    uv run python -m evals.sentiment.make_sheet            # -> evals/sentiment/to_label.csv
"""
import csv, glob, json, random, re
from radar_mcp import sentiment

N, SEED = 240, 0
PROMO = re.compile(r"\b(whats?app|telegram|invest|trading|coach|profit|\$\d|mrs\.?|mr\.?\s+\w+ helped|recommend)", re.I)
SARC = re.compile(r"(\byeah right\b|\bsure\b|\bgreat job\b|\bwow\b|🙄|😂|🤡|/s\b|\bthanks? (biden|trump|obama)\b)", re.I)

rows = []
for f in sorted(glob.glob("data/cache/*.json")):
    d = json.load(open(f))
    vid = d.get("thread_id") or f
    for c in d["comments"]:
        t = c["text"].strip()
        if 3 <= len(t) <= 600:
            kind = ("non_english" if not t.isascii() and sum(ch.isascii() for ch in t) / len(t) < 0.6
                    else "promo" if PROMO.search(t) else "sarcasm?" if SARC.search(t) else "general")
            rows.append({"id": c["id"], "video": vid, "kind": kind, "text": t})

random.seed(SEED)
quota = {"non_english": 40, "promo": 40, "sarcasm?": 50}
sample = []
for k, q in quota.items():
    pool = [r for r in rows if r["kind"] == k]
    sample += random.sample(pool, min(q, len(pool)))
rest = [r for r in rows if r not in sample]
sample += random.sample(rest, N - len(sample))
random.shuffle(sample)

preds = sentiment.classify([r["text"] for r in sample])
with open("evals/sentiment/to_label.csv", "w", newline="") as fh:
    w = csv.DictWriter(fh, ["id", "kind", "model_guess", "label", "text"])
    w.writeheader()
    for r, p in zip(sample, preds):
        w.writerow({"id": r["id"], "kind": r["kind"], "model_guess": p["label"], "label": "", "text": r["text"]})
print({k: sum(r["kind"] == k for r in sample) for k in list(quota) + ["general"]}, "->", len(sample), "rows")
