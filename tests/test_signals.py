import datetime as dt

from radar_mcp import signals
from radar_mcp.signals import find_groups, mask
from tests import synthetic


def run(t: dict, sentiments: dict | None = None) -> dict:
    return signals.find_groups(t["video"], t["comments"], t["accounts"], sentiments or {})


def test_organic_section_has_no_groups():
    result = run(synthetic.thread(synthetic.organic_thread()))
    assert result["groups"] == []
    assert result["baseline"]["grouped_comment_share"] == 0


def test_finds_scam_reply_chain_and_template_group():
    scam, tpl = synthetic.scam_reply_chain(), synthetic.copy_paste_group()
    result = run(synthetic.thread(synthetic.organic_thread(), scam, tpl))
    found = {frozenset(g["accounts"]): g for g in result["groups"]}
    scam_accounts = frozenset(signals.mask(a) for a in scam[1])
    tpl_accounts = frozenset(signals.mask(a) for a in tpl[1])
    assert set(found) == {scam_accounts, tpl_accounts}
    assert found[scam_accounts]["pattern"] == "reply_chain"
    assert found[tpl_accounts]["pattern"] == "copy_paste"
    assert found[tpl_accounts]["features"]["text_similarity"] > 0.8
    assert found[scam_accounts]["features"]["young_share"] == 1.0
    assert all(g["score"] >= 0.5 for g in result["groups"])
    assert [g["id"] for g in result["groups"]] == ["G1", "G2"]


def test_creator_replies_are_not_a_group():
    t = synthetic.thread(synthetic.organic_thread())
    for i, c in enumerate(t["comments"][:5]):
        c["author_id"] = "UC_creator"  # the video's own channel answering viewers
        c["text"] = "Thanks so much for watching, glad it helped you out!"
    assert run(t)["groups"] == []


def test_short_identical_comments_are_ignored():
    t = synthetic.thread(synthetic.organic_thread())
    for c in t["comments"][:10]:
        c["text"] = "first!"
    assert run(t)["groups"] == []


def test_sentiment_split_between_grouped_and_organic():
    t = synthetic.thread(synthetic.organic_thread(), synthetic.copy_paste_group())
    sentiments = {c["id"]: ("negative" if c["id"].startswith("tpl") else "neutral") for c in t["comments"]}
    result = run(t, sentiments)
    assert result["sentiment"]["grouped"]["negative"] == 1.0
    assert result["sentiment"]["organic"]["negative"] == 0.0
    assert result["groups"][0]["features"]["sentiment_uniformity"] == 1.0


def test_timeline_counts_every_comment():
    t = synthetic.thread(synthetic.organic_thread(), synthetic.copy_paste_group())
    tl = run(t)["timeline"]
    assert sum(b["total"] for b in tl["bins"]) == len(t["comments"])
    assert len(tl["bins"]) <= signals.MAX_BINS
    assert sum(sum(b["groups"].values()) for b in tl["bins"]) == 5


def test_names_never_appear():
    t = synthetic.thread(synthetic.organic_thread(), synthetic.scam_reply_chain())
    text = str(run(t))
    assert "Person 1" not in text and "UC_org_1" not in text


def test_busy_thread_of_real_viewers_is_not_a_group():
    """A 200-reply thread with young accounts at the section's usual rate (5%) links no one."""
    comments, accounts = synthetic.organic_thread(400)
    for i, c in enumerate(comments[:200]):
        c.update(thread_id="hot", parent_id="hot", published_at=synthetic._iso(synthetic.T0 + dt.timedelta(seconds=15 * i)))
    for i in range(0, 400, 20):  # every 20th account is young: 10 in the hot thread, 10 elsewhere
        accounts[comments[i]["author_id"]]["created_at"] = synthetic._iso(synthetic.T0 - dt.timedelta(days=30))
    result = find_groups(synthetic.VIDEO, comments, accounts, {})
    assert result["groups"] == []


def test_young_accounts_crowding_a_busy_thread_are_a_group():
    """The same busy thread, plus 6 young accounts piling on within 3 minutes (the pace of the rings seen on
    YouTube): they stand out. Spread thinly over a busy thread, age alone wouldn't show them; text has to."""
    comments, accounts = synthetic.organic_thread(400)
    for i, c in enumerate(comments[:200]):
        c.update(thread_id="hot", parent_id="hot", published_at=synthetic._iso(synthetic.T0 + dt.timedelta(seconds=15 * i)))
    for i in range(0, 400, 20):
        accounts[comments[i]["author_id"]]["created_at"] = synthetic._iso(synthetic.T0 - dt.timedelta(days=30))
    ring, ring_accounts = synthetic.scam_reply_chain(6, start=synthetic.T0 + dt.timedelta(minutes=20))
    for i, c in enumerate(ring):
        c.update(thread_id="hot", parent_id="hot",
                 published_at=synthetic._iso(synthetic.T0 + dt.timedelta(minutes=20, seconds=30 * i)))
    result = find_groups(synthetic.VIDEO, comments + ring, {**accounts, **ring_accounts}, {})
    ring_ids = {mask(a) for a in ring_accounts}
    assert any(ring_ids <= set(g["accounts"]) for g in result["groups"])


SIDES = [{"id": "S1", "label": "It is corrupt"}, {"id": "S2", "label": "It is fine"}]


def corrupt_stances(comments):
    return {c["id"]: "S1" if "corrupt" in c["text"] else "neutral" for c in comments}


def test_new_accounts_pushing_one_side_are_a_steering_group():
    t = synthetic.thread(synthetic.organic_thread(300), synthetic.steering_wave(15))
    result = find_groups(t["video"], t["comments"], t["accounts"], {}, corrupt_stances(t["comments"]), SIDES)
    s1 = next(r for r in result["stance"]["rows"] if r["stance"] == "S1")
    assert result["stance"]["pushed"] == ["S1"]
    assert s1["new"]["accounts"] == 15 and s1["established"]["accounts"] == 0 and s1["p_value"] < 0.01
    steering = [g for g in result["groups"] if g["pattern"] == "steering"]
    assert len(steering) == 1 and steering[0]["n_accounts"] == 15
    assert steering[0]["features"]["stance_push"] == 1.0


def test_new_accounts_sharing_the_crowd_view_are_not_steering():
    """Half of everyone says "corrupt", new accounts included: a popular view, not a push."""
    comments, accounts = synthetic.organic_thread(300)
    wave, wave_accounts = synthetic.steering_wave(16)
    for c in comments[::2]:
        c["text"] += " corrupt"
    for c in wave[::2]:
        c["text"] = c["text"].replace("corrupt", "fine")
    all_comments, all_accounts = comments + wave, {**accounts, **wave_accounts}
    result = find_groups(synthetic.VIDEO, all_comments, all_accounts, {}, corrupt_stances(all_comments), SIDES)
    assert result["stance"]["pushed"] == []
    assert not [g for g in result["groups"] if g["pattern"] == "steering"]
