"""Sample training comments from data/cache/, excluding the test set and near-copies of it.

    uv run python -m evals.sentiment.make_train      # -> evals/sentiment/train_pool.csv
"""
import csv, glob, json, random, re
from pathlib import Path

HERE = Path(__file__).parent
N, SEED = 1000, 1


def norm(t):
    return re.sub(r"[\W_]+", " ", re.sub(r"@\S+", "", t.lower())).strip()


test = list(csv.DictReader(open(HERE / "labels.csv")))
test_ids = {r["id"] for r in test}
test_norm = {norm(r["text"]) for r in test}
seen, rows = set(), []
for f in sorted(glob.glob("data/cache/*.json")):
    for c in json.load(open(f))["comments"]:
        t = c["text"].strip()
        n = norm(t)
        if not (3 <= len(t) <= 400) or c["id"] in test_ids or n in test_norm or n in seen:
            continue
        seen.add(n)
        rows.append({"id": c["id"], "video": Path(f).stem, "text": t})
random.seed(SEED)
sample = random.sample(rows, N)
with open(HERE / "train_pool.csv", "w", newline="") as fh:
    w = csv.DictWriter(fh, ["id", "video", "label", "text"]); w.writeheader()
    w.writerows({**r, "label": ""} for r in sample)
print(len(rows), "candidates ->", N)
