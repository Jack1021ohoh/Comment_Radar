"""Finds coordinated groups: accounts in one comment section that act together.

Pure functions over the fetched data, no network and no model calls, so they're cheap to test and tune.

    1. Link two accounts when there is direct evidence they act together:
         similar_text  their comments are near-copies (character n-gram cosine >= TEXT_SIMILARITY)
         reply_chain   both replied in the same thread within REPLY_WINDOW, and both accounts were young
    2. Accounts joined by links form a candidate group (connected components, at least MIN_GROUP accounts).
    3. Each group gets features and a score from `score_group`.

`score_group` is a hand-weighted baseline. It is the seam for a trained model: keep its input
(the features dict) and output (score from 0 to 1, plus the signals that drove it) and the rest
of the system won't notice the change.

Accounts are reported by a masked id (acct_1a2b3c), never by name: the radar reports groups, not people.
"""

from __future__ import annotations

import datetime as dt
import hashlib
import re
from collections import Counter, defaultdict

import numpy as np
from sklearn.feature_extraction.text import TfidfVectorizer

TEXT_SIMILARITY = 0.80  # near-copies score above this; ordinary comments on one topic rarely do
MIN_TEXT_CHARS = 20  # "nice video" is identical across thousands of real people
REPLY_WINDOW = dt.timedelta(minutes=60)
YOUNG_DAYS = 180  # an account this new when it commented
CREATED_WINDOW_DAYS = 14
BURST_WINDOW = dt.timedelta(minutes=60)
MIN_GROUP = 3
MAX_GROUPS = 10

# The baseline score: each feature is a share from 0 to 1, weighted by how much it says on its own.
WEIGHTS = {
    "text_similarity": 0.30,
    "burst": 0.20,
    "young_share": 0.20,
    "created_cluster": 0.15,
    "same_thread_share": 0.10,
    "sentiment_uniformity": 0.05,
}


def mask(author_id: str) -> str:
    return "acct_" + hashlib.sha256(author_id.encode()).hexdigest()[:6]


def parse_time(value: str | None) -> dt.datetime | None:
    if not value:
        return None
    try:
        return dt.datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def normalize(text: str) -> str:
    text = re.sub(r"https?://\S+", " URL ", text.lower())
    return re.sub(r"\s+", " ", text).strip()


class _Groups:
    """Union-find over account ids."""

    def __init__(self):
        self.parent: dict[str, str] = {}

    def find(self, a: str) -> str:
        self.parent.setdefault(a, a)
        while self.parent[a] != a:
            self.parent[a] = self.parent[self.parent[a]]
            a = self.parent[a]
        return a

    def join(self, a: str, b: str) -> None:
        self.parent[self.find(a)] = self.find(b)

    def components(self) -> list[set[str]]:
        out: dict[str, set[str]] = defaultdict(set)
        for a in self.parent:
            out[self.find(a)].add(a)
        return list(out.values())


def is_young(account: dict | None, at: dt.datetime | None) -> bool:
    created = parse_time((account or {}).get("created_at"))
    return bool(created and at and (at - created).days <= YOUNG_DAYS)


def densest_share(times: list[dt.datetime], window: dt.timedelta) -> float:
    """The largest share of these times that fall inside one window."""
    if not times:
        return 0.0
    ts = sorted(times)
    best, j = 0, 0
    for i in range(len(ts)):
        while ts[i] - ts[j] > window:
            j += 1
        best = max(best, i - j + 1)
    return best / len(ts)


def score_group(features: dict) -> tuple[float, list[dict]]:
    """Score from 0 to 1, and every signal with its contribution, largest first."""
    signals = [{"name": k, "value": round(features.get(k, 0.0), 3),
                "contribution": round(w * features.get(k, 0.0), 3)} for k, w in WEIGHTS.items()]
    signals.sort(key=lambda s: s["contribution"], reverse=True)
    return round(min(1.0, sum(s["contribution"] for s in signals)), 3), signals


def describe(signal: dict, features: dict) -> str:
    v = signal["value"]
    return {
        "text_similarity": f"their comments are {v:.0%} alike on average",
        "burst": f"{v:.0%} of their comments were posted within one hour",
        "young_share": f"{v:.0%} of the accounts were under {YOUNG_DAYS} days old when they commented",
        "created_cluster": f"{v:.0%} of the accounts were created within the same {CREATED_WINDOW_DAYS} days",
        "same_thread_share": f"{v:.0%} of their comments are in one reply thread",
        "sentiment_uniformity": f"{v:.0%} of their comments share one sentiment ({features.get('main_sentiment')})",
    }[signal["name"]]


def find_groups(video: dict, comments: list[dict], accounts: dict[str, dict], sentiments: dict[str, str]) -> dict:
    """Candidate groups, the thread's baseline rates, a timeline and sentiment by group membership.

    video: fetch_video's dict. comments: fetch_comments' dicts. accounts: channel id -> fetch_channels' dict.
    sentiments: comment id -> label.
    """
    creator = video.get("channel_id")
    comments = [c for c in comments if c.get("author_id") and c["author_id"] != creator]
    times = {c["id"]: parse_time(c.get("published_at")) for c in comments}
    links = _Groups()
    edge_kinds: dict[frozenset, Counter] = defaultdict(Counter)

    def link(a: str, b: str, kind: str) -> None:
        if a != b:
            links.join(a, b)
            edge_kinds[frozenset((a, b))][kind] += 1

    # 1a. Near-copies by different accounts
    texts = [normalize(c["text"]) for c in comments]
    long_ix = [i for i, t in enumerate(texts) if len(t) >= MIN_TEXT_CHARS]
    sim_of: dict[str, int] = {}  # comment id -> row in X
    X = None
    if len(long_ix) >= 2:
        X = TfidfVectorizer(analyzer="char_wb", ngram_range=(3, 5), sublinear_tf=True).fit_transform(
            [texts[i] for i in long_ix])
        sim_of = {comments[i]["id"]: row for row, i in enumerate(long_ix)}
        S = (X @ X.T).tocoo()
        for r, c, v in zip(S.row, S.col, S.data):
            if r < c and v >= TEXT_SIMILARITY:
                link(comments[long_ix[r]]["author_id"], comments[long_ix[c]]["author_id"], "similar_text")

    # 1b. Young accounts replying together in one thread
    by_thread: dict[str, list[dict]] = defaultdict(list)
    for c in comments:
        by_thread[c["thread_id"]].append(c)
    for thread in by_thread.values():
        young = [c for c in thread if is_young(accounts.get(c["author_id"]), times[c["id"]])]
        for i, a in enumerate(young):
            for b in young[i + 1:]:
                ta, tb = times[a["id"]], times[b["id"]]
                if ta and tb and abs(ta - tb) <= REPLY_WINDOW:
                    link(a["author_id"], b["author_id"], "reply_chain")

    # 2-3. Groups and their features
    by_author: dict[str, list[dict]] = defaultdict(list)
    for c in comments:
        by_author[c["author_id"]].append(c)
    groups = []
    for members in links.components():
        if len(members) < MIN_GROUP:
            continue
        cs = sorted((c for m in members for c in by_author[m]), key=lambda c: c.get("published_at") or "")
        ts = [times[c["id"]] for c in cs if times[c["id"]]]
        accs = [accounts.get(m) for m in members]

        rows = [sim_of[c["id"]] for c in cs if c["id"] in sim_of]
        authors_of_rows = [c["author_id"] for c in cs if c["id"] in sim_of]
        text_similarity = 0.0
        if X is not None and len(rows) >= 2:
            sub = (X[rows] @ X[rows].T).toarray()
            different = np.array([[a != b for b in authors_of_rows] for a in authors_of_rows])
            if different.any():
                text_similarity = float(sub[different].mean())

        first_comment = {m: min((times[c["id"]] for c in by_author[m] if times[c["id"]]), default=None) for m in members}
        created = sorted(d for d in (parse_time((a or {}).get("created_at")) for a in accs) if d)
        created_cluster = densest_share(created, dt.timedelta(days=CREATED_WINDOW_DAYS)) * len(created) / len(members)
        labels = [sentiments.get(c["id"]) for c in cs if sentiments.get(c["id"])]
        main_sentiment, main_count = Counter(labels).most_common(1)[0] if labels else (None, 0)
        kinds = Counter()
        for pair, k in edge_kinds.items():
            if pair <= members:
                kinds.update(k)

        features = {
            "text_similarity": round(text_similarity, 3),
            "burst": round(densest_share(ts, BURST_WINDOW), 3),
            "young_share": round(sum(is_young(accounts.get(m), first_comment[m]) for m in members) / len(members), 3),
            "created_cluster": round(created_cluster, 3),
            "same_thread_share": round(Counter(c["thread_id"] for c in cs).most_common(1)[0][1] / len(cs), 3),
            "sentiment_uniformity": round(main_count / len(labels), 3) if labels else 0.0,
            "main_sentiment": main_sentiment,
            "no_upload_share": round(sum(1 for a in accs if a and a.get("video_count") == 0) / len(members), 3),
            "span_minutes": round((max(ts) - min(ts)).total_seconds() / 60, 1) if ts else None,
            "links": dict(kinds),
        }
        score, signals = score_group(features)
        for s in signals:
            s["text"] = describe(s, features)
        pattern = ("reply_chain" if kinds["reply_chain"] > kinds["similar_text"] else
                   "copy_paste" if kinds["similar_text"] else "mixed")
        groups.append({
            "accounts": sorted(mask(m) for m in members),
            "comment_ids": [c["id"] for c in cs],
            "n_accounts": len(members),
            "n_comments": len(cs),
            "first_at": cs[0].get("published_at"),
            "last_at": cs[-1].get("published_at"),
            "pattern": pattern,
            "score": score,
            "features": features,
            "signals": signals,
            "sentiment": distribution_of(labels),
        })
    groups.sort(key=lambda g: (g["score"], g["n_accounts"]), reverse=True)
    groups = groups[:MAX_GROUPS]
    for i, g in enumerate(groups, 1):
        g["id"] = f"G{i}"

    grouped_ids = {cid for g in groups for cid in g["comment_ids"]}
    all_times = [t for t in times.values() if t]
    authors = list(by_author)
    first_by_author = {a: min((times[c["id"]] for c in by_author[a] if times[c["id"]]), default=None) for a in authors}
    baseline = {
        "comments": len(comments),
        "accounts": len(authors),
        "young_share": round(sum(is_young(accounts.get(a), first_by_author[a]) for a in authors) / len(authors), 3) if authors else 0.0,
        "no_upload_share": round(sum(1 for a in authors if (accounts.get(a) or {}).get("video_count") == 0) / len(authors), 3) if authors else 0.0,
        "densest_hour_share": round(densest_share(all_times, BURST_WINDOW), 3),
        "reply_share": round(sum(1 for c in comments if c.get("parent_id")) / len(comments), 3) if comments else 0.0,
        "grouped_comment_share": round(len(grouped_ids) / len(comments), 3) if comments else 0.0,
    }
    return {
        "groups": groups,
        "baseline": baseline,
        "timeline": timeline(comments, times, groups),
        "sentiment": {
            "all": distribution_of([sentiments.get(c["id"]) for c in comments if sentiments.get(c["id"])]),
            "grouped": distribution_of([sentiments.get(c) for c in grouped_ids if sentiments.get(c)]),
            "organic": distribution_of([sentiments.get(c["id"]) for c in comments
                                        if c["id"] not in grouped_ids and sentiments.get(c["id"])]),
        },
        "settings": {"text_similarity": TEXT_SIMILARITY, "min_text_chars": MIN_TEXT_CHARS,
                     "reply_window_minutes": REPLY_WINDOW.total_seconds() / 60, "young_days": YOUNG_DAYS,
                     "created_window_days": CREATED_WINDOW_DAYS, "min_group": MIN_GROUP, "weights": WEIGHTS},
    }


def distribution_of(labels: list[str]) -> dict:
    n = len(labels)
    return {lab: (round(labels.count(lab) / n, 3) if n else 0.0) for lab in ("negative", "neutral", "positive")} | {"n": n}


BIN_CHOICES = [5, 15, 60, 180, 360, 1440, 10080]  # minutes
MAX_BINS = 72


def timeline(comments: list[dict], times: dict, groups: list[dict]) -> dict:
    """Comments per time bin, and how many of them came from each group. Bins grow until there are at most MAX_BINS."""
    ts = [t for t in times.values() if t]
    if not ts:
        return {"bin_minutes": 0, "bins": []}
    start, end = min(ts), max(ts)
    span = (end - start).total_seconds() / 60
    size = next((b for b in BIN_CHOICES if span / b <= MAX_BINS), int(span // MAX_BINS) + 1)
    n = int(span // size) + 1
    group_of = {cid: g["id"] for g in groups for cid in g["comment_ids"]}
    bins = [{"start": (start + dt.timedelta(minutes=i * size)).isoformat(), "total": 0, "groups": {}} for i in range(n)]
    for c in comments:
        t = times[c["id"]]
        if not t:
            continue
        b = bins[int((t - start).total_seconds() / 60 // size)]
        b["total"] += 1
        if c["id"] in group_of:
            b["groups"][group_of[c["id"]]] = b["groups"].get(group_of[c["id"]], 0) + 1
    return {"bin_minutes": size, "bins": bins}
