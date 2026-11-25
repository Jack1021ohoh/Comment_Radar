"""Made-up comment sections with known answers, for tests. No network."""

from __future__ import annotations

import datetime as dt
import random

T0 = dt.datetime(2026, 11, 1, 12, 0, tzinfo=dt.timezone.utc)
VIDEO = {"id": "abcdefghijk", "url": "https://www.youtube.com/watch?v=abcdefghijk", "title": "Markets this week",
         "channel_id": "UC_creator", "channel_title": "Some Channel", "published_at": T0.isoformat(),
         "category_id": "25", "view_count": 50000, "comment_count": 120, "was_live_or_premiere": False,
         "live_started_at": None}

ORGANIC = [
    "Great breakdown, the part about bond yields finally made sense to me",
    "I disagree with the take on inflation, wages have not kept up at all",
    "Can you do a follow-up on housing prices in smaller cities?",
    "The chart at 4:12 is mislabeled I think, should be 2025 not 2024",
    "Watching from Canada, our situation is pretty similar honestly",
    "This channel never misses. Subscribed last year and still learning",
    "Not sure about the conclusion, feels a bit too optimistic to me",
    "My grandfather always said to buy land, maybe he was right after all",
    "Audio is a little quiet in the second half, otherwise great video",
    "Interesting how nobody talks about the energy costs side of this",
]
VOCAB = ("market rates housing wages rent budget savings loan bank stock fund policy vote senate tax energy oil gas "
         "price grocery coffee school college debt credit job hiring layoffs factory farm weather city town river "
         "bridge road transit bus train airport travel hotel summer winter family kids parents friend neighbor "
         "teacher doctor nurse hospital insurance pension retire garden kitchen recipe bread soup music guitar movie "
         "book chapter author story history museum science math physics chemistry engine car truck bike repair "
         "phone laptop screen battery cable signal radio podcast video audio editing chart graph table number "
         "really maybe honestly clearly strange funny weird great awful decent solid shaky curious doubtful").split()


def _iso(t: dt.datetime) -> str:
    return t.isoformat().replace("+00:00", "Z")


def organic_thread(n_accounts: int = 60, seed: int = 0) -> tuple[list[dict], dict[str, dict]]:
    """Real-looking comments: old accounts, spread over two days, varied text."""
    rng = random.Random(seed)
    comments, accounts = [], {}
    for i in range(n_accounts):
        aid = f"UC_org_{i}"
        accounts[aid] = {"id": aid, "created_at": _iso(T0 - dt.timedelta(days=rng.randint(400, 4000))),
                         "subscriber_count": rng.randint(0, 300), "video_count": rng.choice([0, 0, 0, 2, 15]),
                         "view_count": 0, "country": None}
        # Each person writes their own sentence: a few of the stock lines would be near-copies.
        text = ORGANIC[i] if i < len(ORGANIC) else " ".join(rng.sample(VOCAB, 12))
        cid = f"org{i}"
        comments.append({"id": cid, "thread_id": cid, "parent_id": None, "author_id": aid, "author_name": f"Person {i}",
                         "text": text, "published_at": _iso(T0 + dt.timedelta(minutes=rng.randint(0, 2880))),
                         "like_count": rng.randint(0, 40)})
    return comments, accounts


def scam_reply_chain(n: int = 6, start: dt.datetime | None = None) -> tuple[list[dict], dict[str, dict]]:
    """A promotion ring: one new account praises an "advisor", new accounts pile on in the replies within minutes."""
    start = start or T0 + dt.timedelta(hours=20)
    praise = ["She really helped me grow my portfolio, highly recommend her",
              "I started with her last month and already see results, thank you",
              "Wow I thought I was the only one she helped, amazing woman",
              "Her strategy is the real deal, my family is so grateful",
              "Same here, best decision I ever made this year honestly",
              "Can confirm, she is legit and very patient with beginners"]
    comments, accounts = [], {}
    top_id = "scam_top"
    for i in range(n):
        aid = f"UC_scam_{i}"
        accounts[aid] = {"id": aid, "created_at": _iso(start - dt.timedelta(days=20 + i)), "subscriber_count": 0,
                         "video_count": 0, "view_count": 0, "country": None}
        if i == 0:
            comments.append({"id": top_id, "thread_id": top_id, "parent_id": None, "author_id": aid, "author_name": "x",
                             "text": "I made $20k in two months thanks to my advisor Mrs. Jane Doe, look her up",
                             "published_at": _iso(start), "like_count": 50})
        else:
            comments.append({"id": f"scam_r{i}", "thread_id": top_id, "parent_id": top_id, "author_id": aid,
                             "author_name": "x", "text": praise[i % len(praise)],
                             "published_at": _iso(start + dt.timedelta(minutes=3 * i)), "like_count": 5})
    return comments, accounts


def copy_paste_group(n: int = 5, start: dt.datetime | None = None) -> tuple[list[dict], dict[str, dict]]:
    """Near-identical template comments from old-looking accounts, posted in a burst."""
    start = start or T0 + dt.timedelta(hours=30)
    variants = ["This policy is a DISASTER for working families. Share this before they delete it!",
                "This policy is a disaster for working families. Share this before they delete it!!",
                "This policy is a DISASTER for working families - share this before they delete it",
                "this policy is a disaster for working families, share this before they delete it!",
                "This policy is a DISASTER for working families. Share before they delete it!"]
    comments, accounts = [], {}
    for i in range(n):
        aid = f"UC_tpl_{i}"
        accounts[aid] = {"id": aid, "created_at": _iso(T0 - dt.timedelta(days=900 + i)), "subscriber_count": 3,
                         "video_count": 0, "view_count": 0, "country": None}
        cid = f"tpl{i}"
        comments.append({"id": cid, "thread_id": cid, "parent_id": None, "author_id": aid, "author_name": "x",
                         "text": variants[i % len(variants)], "published_at": _iso(start + dt.timedelta(minutes=2 * i)),
                         "like_count": 1})
    return comments, accounts


def thread(*parts: tuple[list[dict], dict[str, dict]]) -> dict:
    comments, accounts = [], {}
    for c, a in parts:
        comments += c
        accounts |= a
    return {"thread_id": "youtube:abcdefghijk", "platform": "youtube",
            "fetched_at": dt.datetime.now(dt.timezone.utc).isoformat(), "video": dict(VIDEO),
            "comments": comments, "accounts": accounts}


def steering_wave(n: int = 15, start: dt.datetime | None = None, seed: int = 7) -> tuple[list[dict], dict[str, dict]]:
    """New accounts that all push one side ("corrupt"), each in their own words, as top-level comments two minutes apart."""
    rng = random.Random(seed)
    start = start or T0 + dt.timedelta(hours=10)
    comments, accounts = [], {}
    for i in range(n):
        aid = f"UC_wave_{i}"
        accounts[aid] = {"id": aid, "created_at": _iso(start - dt.timedelta(days=rng.randint(5, 40))), "subscriber_count": 0,
                         "video_count": 0, "view_count": 0, "country": None}
        cid = f"wave{i}"
        comments.append({"id": cid, "thread_id": cid, "parent_id": None, "author_id": aid, "author_name": "x",
                         "text": " ".join(rng.sample(VOCAB, 8)) + " this is corrupt " + " ".join(rng.sample(VOCAB, 4)),
                         "published_at": _iso(start + dt.timedelta(minutes=2 * i)), "like_count": 0})
    return comments, accounts
