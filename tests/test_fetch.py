"""fetch_comments reads whole reply threads and says how much it read. A fake YouTube, no network."""

import asyncio

from radar_mcp import youtube


def snippet(cid: str) -> dict:
    return {"id": cid, "snippet": {"authorChannelId": {"value": f"UC_{cid}"}, "authorDisplayName": cid,
                                   "textDisplay": cid, "publishedAt": "2026-11-01T12:00:00Z", "likeCount": 0}}


def make_thread(tid: str, n_replies: int, inline: int = 5) -> dict:
    return {"id": tid, "snippet": {"topLevelComment": snippet(tid), "totalReplyCount": n_replies},
            "replies": {"comments": [snippet(f"{tid}.r{i}") for i in range(min(inline, n_replies))]}}


def fake_youtube(monkeypatch, pages: list[list[dict]]):
    """pages of comment threads; every thread's full replies are served 100 per page."""
    threads = {t["id"]: t for page in pages for t in page}

    async def get(client, endpoint, **params):
        if endpoint == "commentThreads":
            i = int(params.get("pageToken") or 0)
            return {"items": pages[i], **({"nextPageToken": str(i + 1)} if i + 1 < len(pages) else {})}
        tid, start = params["parentId"], int(params.get("pageToken") or 0)
        total = threads[tid]["snippet"]["totalReplyCount"]
        items = [snippet(f"{tid}.r{i}") for i in range(start, min(start + 100, total))]
        return {"items": items, **({"nextPageToken": str(start + 100)} if start + 100 < total else {})}

    monkeypatch.setattr(youtube, "_get", get)


def test_reads_every_reply_of_a_big_thread(monkeypatch):
    fake_youtube(monkeypatch, [[make_thread("a", 250), make_thread("b", 3)], [make_thread("c", 0)]])
    comments, coverage = asyncio.run(youtube.fetch_comments(None, "vid", 5000))
    assert sum(1 for c in comments if c["thread_id"] == "a") == 251
    assert len({c["id"] for c in comments}) == len(comments) == 251 + 4 + 1
    assert coverage == {"threads": 3, "all_threads": True, "replies": 253, "replies_expected": 253, "max_comments": 5000}


def test_stops_before_a_thread_that_would_not_fit(monkeypatch):
    fake_youtube(monkeypatch, [[make_thread("a", 10), make_thread("b", 50), make_thread("c", 0)]])
    comments, coverage = asyncio.run(youtube.fetch_comments(None, "vid", 30))
    assert {c["thread_id"] for c in comments} == {"a"}  # b would pass 30: it is left out, not cut
    assert coverage["threads"] == 1 and coverage["all_threads"] is False
    assert coverage["replies"] == coverage["replies_expected"] == 10
