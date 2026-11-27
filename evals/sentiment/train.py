"""Train sentiment models on train_pool.csv and save them under models/.

    uv run --with sentencepiece --with accelerate python -m evals.sentiment.train full
    uv run --with sentencepiece --with sentence-transformers python -m evals.sentiment.train probe
    uv run --with sentencepiece --with setfit python -m evals.sentiment.train setfit

Test on the 240 held-out comments with evals/sentiment/evaluate.py (full) or this script's own report (probe, setfit).
"""
import csv, json, os, random, sys, time
from pathlib import Path

import numpy as np

HERE = Path(__file__).parent
OUT = Path("models")
LABELS = ["negative", "neutral", "positive"]
BASE = os.environ.get("BASE_MODEL", "cardiffnlp/twitter-xlm-roberta-base-sentiment")  # e.g. cardiffnlp/twitter-roberta-base-sentiment-latest
NAME = os.environ.get("OUT_NAME", "sentiment-xlmr-ft")
SEED = 0


def load():
    rows = [r for r in csv.DictReader(open(HERE / "train_pool.csv")) if r["label"]]
    random.Random(SEED).shuffle(rows)
    # stratified 10% validation split
    val, train, seen = [], [], {l: 0 for l in LABELS}
    for r in rows:
        quota = round(0.1 * sum(x["label"] == r["label"] for x in rows))
        (val if seen[r["label"]] < quota else train).append(r)
        seen[r["label"]] += r in val
    test = [r for r in csv.DictReader(open(HERE / "labels.csv")) if r["final"]]
    return train, val, test


def macro_f1(gold, pred):
    f = []
    for l in LABELS:
        tp = sum(g == p == l for g, p in zip(gold, pred))
        pr, rc = tp / max(1, pred.count(l)), tp / max(1, gold.count(l))
        f.append(2 * pr * rc / (pr + rc) if pr + rc else 0)
    return sum(f) / 3


def report(name, test, pred):
    gold = [r["final"] for r in test]
    print(f"\n{name}: test accuracy {np.mean([g == p for g, p in zip(gold, pred)]):.1%}  macro-F1 {macro_f1(gold, pred):.3f}")
    (HERE / "results").mkdir(exist_ok=True)
    json.dump({"model": name, "pred": pred}, open(HERE / "results" / f"{name}.json", "w"))


def weights(train):
    n = np.array([sum(r["label"] == l for r in train) for l in LABELS], float)
    return (n.sum() / (3 * n)).tolist()


def full(train, val, test):
    import torch
    from torch.utils.data import Dataset
    from transformers import AutoModelForSequenceClassification, AutoTokenizer, Trainer, TrainingArguments

    tok = AutoTokenizer.from_pretrained(BASE)
    model = AutoModelForSequenceClassification.from_pretrained(
        BASE, num_labels=3, id2label=dict(enumerate(LABELS)), label2id={l: i for i, l in enumerate(LABELS)})
    w = torch.tensor(weights(train))

    class DS(Dataset):
        def __init__(self, rows): self.enc, self.y = tok([r["text"] for r in rows], truncation=True, max_length=64), [LABELS.index(r["label"]) for r in rows]
        def __len__(self): return len(self.y)
        def __getitem__(self, i): return {k: v[i] for k, v in self.enc.items()} | {"labels": self.y[i]}

    class WeightedTrainer(Trainer):
        def compute_loss(self, model, inputs, return_outputs=False, **kw):
            y = inputs.pop("labels"); out = model(**inputs)
            loss = torch.nn.functional.cross_entropy(out.logits, y, weight=w.to(out.logits.device))
            return (loss, out) if return_outputs else loss

    def metrics(p):
        pred = [LABELS[i] for i in p.predictions.argmax(-1)]; gold = [LABELS[i] for i in p.label_ids]
        return {"macro_f1": macro_f1(gold, pred)}

    from transformers import DataCollatorWithPadding
    args = TrainingArguments(output_dir=str(OUT / "ckpt"), num_train_epochs=4, learning_rate=2e-5, per_device_train_batch_size=16,
                             per_device_eval_batch_size=64, weight_decay=0.01, warmup_steps=23, eval_strategy="epoch",
                             save_strategy="epoch", load_best_model_at_end=True, metric_for_best_model="macro_f1",
                             save_total_limit=1, logging_steps=20, seed=SEED, report_to=[])
    t = time.time()
    tr = WeightedTrainer(model=model, args=args, train_dataset=DS(train), eval_dataset=DS(val),
                         data_collator=DataCollatorWithPadding(tok), compute_metrics=metrics)
    tr.train()
    print(f"trained in {time.time() - t:.0f}s; best val macro-F1 {tr.state.best_metric:.3f}")
    tr.save_model(OUT / NAME); tok.save_pretrained(OUT / NAME)
    print(f"saved models/{NAME}")


def probe(train, val, test):
    from sentence_transformers import SentenceTransformer
    from sklearn.linear_model import LogisticRegression
    enc = SentenceTransformer("sentence-transformers/paraphrase-multilingual-mpnet-base-v2")
    X = lambda rows: enc.encode([r["text"] for r in rows], batch_size=64)
    t = time.time()
    clf = LogisticRegression(max_iter=2000, class_weight="balanced", C=1.0).fit(X(train + val), [r["label"] for r in train + val])
    print(f"trained in {time.time() - t:.0f}s")
    report("probe-mpnet-logreg", test, list(clf.predict(X(test))))


def setfit(train, val, test):
    from datasets import Dataset
    from setfit import SetFitModel, Trainer, TrainingArguments
    model = SetFitModel.from_pretrained("sentence-transformers/paraphrase-multilingual-mpnet-base-v2", labels=LABELS)
    ds = Dataset.from_dict({"text": [r["text"] for r in train + val], "label": [LABELS.index(r["label"]) for r in train + val]})
    t = time.time()
    Trainer(model=model, args=TrainingArguments(batch_size=16, num_epochs=1, num_iterations=3, seed=SEED), train_dataset=ds).train()
    print(f"trained in {time.time() - t:.0f}s")
    pred = model.predict([r["text"] for r in test])
    report("setfit-mpnet", test, [p if isinstance(p, str) else LABELS[int(p)] for p in pred])


if __name__ == "__main__":
    train, val, test = load()
    print(f"train {len(train)}  val {len(val)}  test {len(test)}")
    {"full": full, "probe": probe, "setfit": setfit}[sys.argv[1]](train, val, test)
