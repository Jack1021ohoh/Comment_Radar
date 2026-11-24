"""YouTube Data API v3: one video, its comments, and the channels of the people who wrote them.

Read-only, with an API key (YOUTUBE_API_KEY). Every list call costs 1 quota unit of the project's
10,000 a day. A 1,000-comment video costs about 50: ~10 pages of comment threads, up to
MAX_REPLY_FETCHES reply pages, and one channels call per 50 commenters.
"""

from __future__ import annotations

import asyncio
import os
import re
from urllib.parse import parse_qs, urlparse

import httpx

API = "https://www.googleapis.com/youtube/v3"
VIDEO_ID = re.compile(r"^[A-Za-z0-9_-]{11}$")
# Threads whose replies don't all come with the thread. Reply chains are where promotion rings live,
# so the busiest ones get their full replies, up to this many.
MAX_REPLY_FETCHES = 20


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


async def fetch_video(client: httpx.AsyncClient, video_id: str) -> dict:
    data = await _get(client, "videos", part="snippet,statistics,liveStreamingDetails", id=video_id)
    if not data.get("items"):
        raise YouTubeError("That video doesn't exist or isn't public.")
    item = data["items"][0]
    s, stats = item["snippet"], item.get("statistics", {})
    live = item.get("liveStreamingDetails") or {}
    return {
        "id": video_id,
        "url": f"https://www.youtube.com/watch?v={video_id}",
        "title": s.get("title", ""),
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


async def fetch_comments(client: httpx.AsyncClient, video_id: str, max_comments: int) -> list[dict]:
    """The newest comments and replies, up to max_comments in all."""
    comments: list[dict] = []
    partial: list[tuple[int, str]] = []  # (missing replies, thread id)
    page_token = None
    while len(comments) < max_comments:
        params = {"part": "snippet,replies", "videoId": video_id, "maxResults": 100, "order": "time",
                  "textFormat": "plainText"}
        if page_token:
            params["pageToken"] = page_token
        data = await _get(client, "commentThreads", **params)
        for thread in data.get("items", []):
            top = thread["snippet"]["topLevelComment"]
            comments.append(_comment(top, thread["id"], None))
            replies = (thread.get("replies") or {}).get("comments", [])
            comments += [_comment(r, thread["id"], thread["id"]) for r in replies]
            missing = thread["snippet"].get("totalReplyCount", 0) - len(replies)
            if missing > 0:
                partial.append((missing, thread["id"]))
        page_token = data.get("nextPageToken")
        if not page_token:
            break

    partial.sort(reverse=True)
    full = await asyncio.gather(*(fetch_replies(client, tid) for _, tid in partial[:MAX_REPLY_FETCHES]))
    have = {c["id"] for c in comments}
    for replies in full:
        comments += [r for r in replies if r["id"] not in have]
    return comments[:max_comments]


async def fetch_replies(client: httpx.AsyncClient, thread_id: str, max_pages: int = 2) -> list[dict]:
    out, page_token = [], None
    for _ in range(max_pages):
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
        comments = await fetch_comments(client, video_id, max_comments)
        accounts = await fetch_channels(client, [c["author_id"] for c in comments])
    return {"video": video, "comments": comments, "accounts": accounts}
