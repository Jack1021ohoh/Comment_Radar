from radar_mcp import signals
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
