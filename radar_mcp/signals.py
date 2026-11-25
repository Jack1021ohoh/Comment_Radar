"""Finds coordinated groups: accounts in one comment section that act together.

Pure functions over the fetched data, no network and no model calls, so they're cheap to test and tune.

    1. Link two accounts when there is direct evidence they act together:
         similar_text  their comments are near-copies (character n-gram cosine >= TEXT_SIMILARITY)
         reply_chain   young accounts replying in one thread within REPLY_WINDOW, in a stretch of replies with
                       more young accounts than chance allows (binomial test against the section's young-comment
                       rate, p < REPLY_P_VALUE)
    2. Accounts joined by links form a candidate group (connected components, at least MIN_GROUP accounts).
    3. Opinion steering, when comments carry stance labels (which side of the video's subject they take):
       one stance per account, new accounts against established ones. A stance new accounts take far more
       often (Fisher's exact test, Bonferroni-corrected p < STANCE_P_VALUE, at least MIN_STANCE_LIFT times as
       often) is "pushed". New accounts pushing it, outside other groups, that also act together (created within
       STEER_CREATED_WINDOW of each other, or first posting within STEER_POST_WINDOW) form a steering group.
    4. Each group gets features and a score from `score_group`.

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
from scipy.stats import binom, fisher_exact
from sklearn.feature_extraction.text import TfidfVectorizer

TEXT_SIMILARITY = 0.80  # near-copies score above this; ordinary comments on one topic rarely do
MIN_TEXT_CHARS = 20  # "nice video" is identical across thousands of real people
REPLY_WINDOW = dt.timedelta(minutes=60)
# A busy thread of real viewers holds young accounts at the section's usual rate: a 500-reply thread at 4%
# has about 20. Linking all of them would make a group of strangers. Only a stretch of consecutive replies
# with more young accounts than chance allows is linked. Many stretches are tested, hence the strict p.
REPLY_P_VALUE = 0.001
MIN_YOUNG_RATE = 0.01  # floor for the section's rate, so one young account in a young-free section isn't "impossible"
YOUNG_DAYS = 180  # an account this new when it commented
CREATED_WINDOW_DAYS = 14
BURST_WINDOW = dt.timedelta(minutes=60)
MIN_GROUP = 3
MAX_GROUPS = 10
STANCE_P_VALUE = 0.01
MIN_STANCE_LIFT = 1.5
# A pushed side shows a lean among new accounts; a steering group needs more: accounts that act together.
STEER_CREATED_WINDOW = dt.timedelta(days=1)
STEER_POST_WINDOW = dt.timedelta(minutes=15)
# Stance labels besides the video's sides (S1, S2, ...). Only sides and off_topic are tested for steering:
# neutral isn't a position, and promotion is what the reply-chain and near-copy signals already catch.
OTHER_STANCES = ("off_topic", "promotion", "neutral")
TESTED_OTHER = ("off_topic",)

# The baseline score: each feature is a share from 0 to 1, weighted by how much it says on its own.
WEIGHTS = {
    "text_similarity": 0.30,
    "burst": 0.20,
    "young_share": 0.20,
    "created_cluster": 0.15,
    "same_thread_share": 0.10,
    "sentiment_uniformity": 0.05,
    "stance_push": 0.25,
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
        "stance_push": f"{v:.0%} of their labelled comments take a side that new accounts push here",
    }[signal["name"]]


def wilson(k: int, n: int, z: float = 1.96) -> tuple[float, float]:
    """95% confidence interval for a share k/n."""
    if not n:
        return 0.0, 0.0
    p = k / n
    centre, half = (p + z * z / (2 * n)) / (1 + z * z / n), z * ((p * (1 - p) / n + z * z / (4 * n * n)) ** 0.5) / (1 + z * z / n)
    return round(max(0.0, centre - half), 3), round(min(1.0, centre + half), 3)


def stance_comparison(comments: list[dict], accounts: dict[str, dict], stances: dict[str, str],
                      sides: list[dict]) -> dict:
    """Which side new accounts take, against established accounts. The unit is the account: each gets the
    stance most of its labelled comments take. New accounts are labelled in full; established accounts are a
    random sample, so their shares carry a confidence interval."""
    times = {c["id"]: parse_time(c.get("published_at")) for c in comments}
    by_author: dict[str, list[dict]] = defaultdict(list)
    for c in comments:
        if c["id"] in stances:
            by_author[c["author_id"]].append(c)
    stance_of, young = {}, {}
    for a, cs in by_author.items():
        stance_of[a] = Counter(stances[c["id"]] for c in cs).most_common(1)[0][0]
        first = min((times[c["id"]] for c in cs if times[c["id"]]), default=None)
        young[a] = is_young(accounts.get(a), first)
    new = [a for a in stance_of if young[a]]
    old = [a for a in stance_of if not young[a]]
    keys = [s["id"] for s in sides] + list(OTHER_STANCES)
    tested = [s["id"] for s in sides] + list(TESTED_OTHER)
    rows = []
    for key in keys:
        k1, k0 = sum(stance_of[a] == key for a in new), sum(stance_of[a] == key for a in old)
        n1, n0 = len(new), len(old)
        row = {"stance": key, "label": next((s["label"] for s in sides if s["id"] == key), key.replace("_", " ")),
               "new": {"accounts": k1, "of": n1, "share": round(k1 / n1, 3) if n1 else 0.0, "ci": wilson(k1, n1)},
               "established": {"accounts": k0, "of": n0, "share": round(k0 / n0, 3) if n0 else 0.0, "ci": wilson(k0, n0)},
               "tested": key in tested, "lift": None, "p_value": None, "pushed": False}
        if key in tested and n1 and n0:
            p1, p0 = k1 / n1, k0 / n0
            row["lift"] = round(p1 / p0, 2) if p0 else None
            p = fisher_exact([[k1, n1 - k1], [k0, n0 - k0]], alternative="greater")[1]
            row["p_value"] = float(min(1.0, p * len(tested)))  # Bonferroni over the stances tested
            row["pushed"] = bool(row["p_value"] < STANCE_P_VALUE and k1 >= MIN_GROUP
                                 and (p0 == 0 or p1 / p0 >= MIN_STANCE_LIFT))
        rows.append(row)
    return {"unit": "accounts", "new_accounts": len(new), "established_accounts": len(old), "rows": rows,
            "pushed": [r["stance"] for r in rows if r["pushed"]], "young_days": YOUNG_DAYS,
            "p_threshold": STANCE_P_VALUE, "min_lift": MIN_STANCE_LIFT,
            "_pushers": {r["stance"]: [a for a in new if stance_of[a] == r["stance"]] for r in rows if r["pushed"]}}


def find_groups(video: dict, comments: list[dict], accounts: dict[str, dict], sentiments: dict[str, str],
                stances: dict[str, str] | None = None, sides: list[dict] | None = None) -> dict:
    """Candidate groups, the thread's baseline rates, a timeline and sentiment by group membership.

    video: fetch_video's dict. comments: fetch_comments' dicts. accounts: channel id -> fetch_channels' dict.
    sentiments: comment id -> label. stances: comment id -> stance label (S1.., off_topic, promotion, neutral),
    for the comments that were labelled; sides: the video's sides, [{"id": "S1", "label": ...}].
    """
    stances = stances or {}
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

    # 1b. Young accounts crowding one reply thread
    young_of = {c["id"]: is_young(accounts.get(c["author_id"]), times[c["id"]]) for c in comments}
    young_rate = max(MIN_YOUNG_RATE, sum(young_of.values()) / len(comments)) if comments else MIN_YOUNG_RATE
    by_thread: dict[str, list[dict]] = defaultdict(list)
    for c in comments:
        if times[c["id"]]:
            by_thread[c["thread_id"]].append(c)
    for thread in by_thread.values():
        thread.sort(key=lambda c: times[c["id"]])
        young = [i for i, c in enumerate(thread) if young_of[c["id"]]]  # positions in the thread
        for x, i in enumerate(young):
            for y in range(x + 1, len(young)):
                j = young[y]
                if times[thread[j]["id"]] - times[thread[i]["id"]] > REPLY_WINDOW:
                    break
                # The stretch from reply i to reply j: j - i + 1 comments, y - x + 1 of them young.
                # P(at least that many young, if each comment is young at the section's rate)
                if binom.sf(y - x, j - i + 1, young_rate) < REPLY_P_VALUE:
                    for k in young[x + 1:y + 1]:
                        link(thread[i]["author_id"], thread[k]["author_id"], "reply_chain")

    # 3. Stances new accounts push
    stance = stance_comparison(comments, accounts, stances, sides or []) if stances else None
    pushed = set(stance["pushed"]) if stance else set()

    # 2-4. Groups and their features
    by_author: dict[str, list[dict]] = defaultdict(list)
    for c in comments:
        by_author[c["author_id"]].append(c)
    components = [(m, None) for m in links.components() if len(m) >= MIN_GROUP]
    linked = {a for m, _ in components for a in m}
    for key, pushers in (stance or {}).get("_pushers", {}).items():
        free = [a for a in pushers if a not in linked]
        first_post = {a: min((times[c["id"]] for c in comments if c["author_id"] == a and stances.get(c["id"]) == key
                              and times[c["id"]]), default=None) for a in free}
        created = {a: parse_time((accounts.get(a) or {}).get("created_at")) for a in free}
        together = _Groups()
        for i, a in enumerate(free):
            together.find(a)
            for b in free[i + 1:]:
                if ((created[a] and created[b] and abs(created[a] - created[b]) <= STEER_CREATED_WINDOW) or
                        (first_post[a] and first_post[b] and abs(first_post[a] - first_post[b]) <= STEER_POST_WINDOW)):
                    together.join(a, b)
        components += [(members, key) for members in together.components() if len(members) >= MIN_GROUP]
    groups = []
    for members, steering in components:
        cs = sorted((c for m in members for c in by_author[m] if not steering or stances.get(c["id"]) == steering),
                    key=lambda c: c.get("published_at") or "")
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
        labelled = [c for c in cs if c["id"] in stances]
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
            "stance_push": round(sum(stances.get(c["id"]) in pushed for c in labelled) / len(labelled), 3) if labelled else 0.0,
            "main_sentiment": main_sentiment,
            "steering_stance": steering,
            "no_upload_share": round(sum(1 for a in accs if a and a.get("video_count") == 0) / len(members), 3),
            "span_minutes": round((max(ts) - min(ts)).total_seconds() / 60, 1) if ts else None,
            "links": dict(kinds),
        }
        score, signals = score_group(features)
        for s in signals:
            s["text"] = describe(s, features)
        pattern = ("steering" if steering else
                   "reply_chain" if kinds["reply_chain"] > kinds["similar_text"] else
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
            "stances": dict(Counter(stances[c["id"]] for c in labelled)),
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
    if stance:
        stance.pop("_pushers")
    return {
        "groups": groups,
        "baseline": baseline,
        "stance": stance,
        "timeline": timeline(comments, times, groups),
        "sentiment": {
            "all": distribution_of([sentiments.get(c["id"]) for c in comments if sentiments.get(c["id"])]),
            "grouped": distribution_of([sentiments.get(c) for c in grouped_ids if sentiments.get(c)]),
            "organic": distribution_of([sentiments.get(c["id"]) for c in comments
                                        if c["id"] not in grouped_ids and sentiments.get(c["id"])]),
        },
        "settings": {"text_similarity": TEXT_SIMILARITY, "min_text_chars": MIN_TEXT_CHARS,
                     "reply_window_minutes": REPLY_WINDOW.total_seconds() / 60, "reply_p_value": REPLY_P_VALUE, "young_days": YOUNG_DAYS,
                     "created_window_days": CREATED_WINDOW_DAYS, "min_group": MIN_GROUP, "weights": WEIGHTS,
                     "stance_p_value": STANCE_P_VALUE, "min_stance_lift": MIN_STANCE_LIFT,
                     "steer_created_window_hours": STEER_CREATED_WINDOW.total_seconds() / 3600,
                     "steer_post_window_minutes": STEER_POST_WINDOW.total_seconds() / 60},
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
