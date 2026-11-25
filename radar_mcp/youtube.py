"""YouTube Data API v3: one video, its comments, and the channels of the people who wrote them.

Read-only, with an API key (YOUTUBE_API_KEY). Every list call costs 1 quota unit of the project's
10,000 a day: one per 100 threads, one per 100 replies of a thread with more than YouTube sends inline,
and one per 50 commenters. A 3,500-comment video costs about 120.

The unit of reading is the reply thread: a top-level comment and every reply under it. Threads are read
whole, newest first, until the next one would pass max_comments. A thread is never cut, because a ring
that baits people in the replies is only visible with all of its replies.
"""

from __future__ import annotations

import asyncio
import os
import re
from urllib.parse import parse_qs, urlparse

import httpx

API = "https://www.googleapis.com/youtube/v3"
VIDEO_ID = re.compile(r"^[A-Za-z0-9_-]{11}$")
REPLY_FETCH_CONCURRENCY = 8


class YouTubeError(Exception):
    """A failure the user should see, in plain words."""


def api_key() -> str:
    key = os.environ.get("YOUTUBE_API_KEY") or os.environ.get("YT_KEY") or ""
    if not key:
        raise YouTubeError("YOUTUBE_API_KEY is not set.")
    return key


def video_id_from_url(url: str) -> str | None:
    """The 11-character video id in any common YouTube link, or a bare id. None if it isn't one."""
    url = (url or "").strip()
    if VIDEO_ID.match(url):
        return url
    if "://" not in url:
        url = "https://" + url
    parsed = urlparse(url)
    host = (parsed.hostname or "").lower().removeprefix("www.").removeprefix("m.").removeprefix("music.")
    parts = [p for p in parsed.path.split("/") if p]
    candidate = None
    if host == "youtu.be" and parts:
        candidate = parts[0]
    elif host in ("youtube.com", "youtube-nocookie.com"):
        if parsed.path == "/watch":
            candidate = (parse_qs(parsed.query).get("v") or [None])[0]
        elif len(parts) >= 2 and parts[0] in ("shorts", "live", "embed", "v"):
            candidate = parts[1]
    return candidate if candidate and VIDEO_ID.match(candidate) else None


async def _get(client: httpx.AsyncClient, endpoint: str, **params) -> dict:
    r = await client.get(f"{API}/{endpoint}", params={**params, "key": api_key()})
    if r.status_code == 200:
        return r.json()
    try:
        reason = r.json()["error"]["errors"][0]["reason"]
    except (ValueError, KeyError, IndexError, TypeError):
        reason = ""
    messages = {
        "commentsDisabled": "Comments are turned off for this video.",
        "quotaExceeded": "The YouTube API quota is used up for today. It resets at midnight Pacific time.",
        "videoNotFound": "That video doesn't exist or isn't public.",
        "keyInvalid": "The YouTube API key is not valid.",
        "forbidden": "YouTube refused the request.",
    }
    raise YouTubeError(messages.get(reason, f"YouTube API error {r.status_code} {reason}".strip()))


def _comment(item: dict, thread_id: str, parent_id: str | None) -> dict:
    s = item["snippet"]
    return {
        "id": item["id"],
        "thread_id": thread_id,
        "parent_id": parent_id,
        "author_id": (s.get("authorChannelId") or {}).get("value"),
        "author_name": s.get("authorDisplayName", ""),
        "text": s.get("textOriginal") or s.get("textDisplay") or "",
        "published_at": s.get("publishedAt"),
        "like_count": s.get("likeCount", 0),
    }


def iso_seconds(value: str | None) -> int | None:
    """ISO 8601 duration ("PT1H2M3S", "P1DT2H") to seconds."""
    m = re.fullmatch(r"P(?:(\d+)D)?(?:T(?:(\d+)H)?(?:(\d+)M)?(?:(\d+)S)?)?", value or "")
    if not m or not value or value == "P":
        return None
    d, h, mi, s = (int(x or 0) for x in m.groups())
    return ((d * 24 + h) * 60 + mi) * 60 + s


async def fetch_video(client: httpx.AsyncClient, video_id: str) -> dict:
    data = await _get(client, "videos", part="snippet,statistics,liveStreamingDetails,contentDetails", id=video_id)
    if not data.get("items"):
        raise YouTubeError("That video doesn't exist or isn't public.")
    item = data["items"][0]
    s, stats = item["snippet"], item.get("statistics", {})
    live = item.get("liveStreamingDetails") or {}
    return {
        "id": video_id,
        "url": f"https://www.youtube.com/watch?v={video_id}",
        "title": s.get("title", ""),
        "description": (s.get("description") or "")[:2000],
        "duration_seconds": iso_seconds((item.get("contentDetails") or {}).get("duration")),
        "channel_id": s.get("channelId"),
        "channel_title": s.get("channelTitle", ""),
        "published_at": s.get("publishedAt"),
        "category_id": s.get("categoryId"),
        "view_count": int(stats.get("viewCount", 0)),
        "comment_count": int(stats.get("commentCount", 0)),
        # A premiere or a livestream gathers comments in a burst on its own, which isn't coordination.
        "was_live_or_premiere": bool(live),
        "live_started_at": live.get("actualStartTime") or live.get("scheduledStartTime"),
    }


async def fetch_comments(client: httpx.AsyncClient, video_id: str, max_comments: int) -> tuple[list[dict], dict]:
    """Whole reply threads, newest first, up to max_comments comments in all.

    Returns (comments, coverage). coverage says how much of the section was read: threads read, whether
    that is every thread, and replies read against the replies YouTube counts for those threads.
    """
    threads: list[dict] = []
    size = 0  # comments in the threads taken so far, counting every reply
    complete, page_token = False, None
    while True:
        params = {"part": "snippet,replies", "videoId": video_id, "maxResults": 100, "order": "time",
                  "textFormat": "plainText"}
        if page_token:
            params["pageToken"] = page_token
        data = await _get(client, "commentThreads", **params)
        full = False
        for thread in data.get("items", []):
            n = 1 + thread["snippet"].get("totalReplyCount", 0)
            if threads and size + n > max_comments:
                full = True
                break
            threads.append(thread)
            size += n
        page_token = data.get("nextPageToken")
        if not page_token and not full:
            complete = True
        if full or not page_token:
            break

    comments: list[dict] = []
    partial: list[dict] = []  # threads whose replies didn't all come inline (YouTube sends up to 5)
    for thread in threads:
        comments.append(_comment(thread["snippet"]["topLevelComment"], thread["id"], None))
        replies = (thread.get("replies") or {}).get("comments", [])
        if thread["snippet"].get("totalReplyCount", 0) > len(replies):
            partial.append(thread)
        else:
            comments += [_comment(r, thread["id"], thread["id"]) for r in replies]

    gate = asyncio.Semaphore(REPLY_FETCH_CONCURRENCY)

    async def replies_of(thread: dict) -> list[dict]:
        pages = -(-thread["snippet"]["totalReplyCount"] // 100)
        async with gate:
            return await fetch_replies(client, thread["id"], max_pages=pages)

    for replies in await asyncio.gather(*(replies_of(t) for t in partial)):
        comments += replies

    expected = sum(t["snippet"].get("totalReplyCount", 0) for t in threads)
    coverage = {
        "threads": len(threads),
        "all_threads": complete,
        "replies": sum(1 for c in comments if c["parent_id"]),
        "replies_expected": expected,
        "max_comments": max_comments,
    }
    return comments, coverage


async def fetch_replies(client: httpx.AsyncClient, thread_id: str, max_pages: int = 1) -> list[dict]:
    """Every reply in one thread, 100 per page."""
    out, page_token = [], None
    for _ in range(max(1, max_pages)):
        params = {"part": "snippet", "parentId": thread_id, "maxResults": 100, "textFormat": "plainText"}
        if page_token:
            params["pageToken"] = page_token
        data = await _get(client, "comments", **params)
        out += [_comment(r, thread_id, thread_id) for r in data.get("items", [])]
        page_token = data.get("nextPageToken")
        if not page_token:
            break
    return out


async def fetch_channels(client: httpx.AsyncClient, channel_ids: list[str]) -> dict[str, dict]:
    """Public profile facts for each commenter's channel, 50 per call."""
    ids = sorted({c for c in channel_ids if c})
    batches = [ids[i:i + 50] for i in range(0, len(ids), 50)]
    results = await asyncio.gather(*(_get(client, "channels", part="snippet,statistics", id=",".join(b),
                                          maxResults=50) for b in batches))
    accounts = {}
    for data in results:
        for item in data.get("items", []):
            s, stats = item["snippet"], item.get("statistics", {})
            hidden = stats.get("hiddenSubscriberCount", False)
            accounts[item["id"]] = {
                "id": item["id"],
                "created_at": s.get("publishedAt"),
                "country": s.get("country"),
                "subscriber_count": None if hidden else int(stats.get("subscriberCount", 0)),
                "video_count": int(stats.get("videoCount", 0)),
                "view_count": int(stats.get("viewCount", 0)),
            }
    return accounts


async def fetch_thread(video_id: str, max_comments: int) -> dict:
    """Everything the radar needs about one video, in one go."""
    async with httpx.AsyncClient(timeout=30) as client:
        video = await fetch_video(client, video_id)
        comments, coverage = await fetch_comments(client, video_id, max_comments)
        accounts = await fetch_channels(client, [c["author_id"] for c in comments])
    return {"video": video, "comments": comments, "accounts": accounts, "coverage": coverage}
