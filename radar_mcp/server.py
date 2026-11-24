"""radar-mcp: Comment Radar's tools as an MCP server.

Fetching, sentiment, coordination signals and lookups all live here, so any MCP client can use the
radar: our agents, Claude Desktop, or the MCP Inspector.

    uv run python -m radar_mcp.server                               # stdio (what app.py starts)
    uv run python -m radar_mcp.server --http --port 8001            # Streamable HTTP at /mcp
    npx @modelcontextprotocol/inspector uv run python -m radar_mcp.server

Typical order: fetch_thread -> analyze_sentiment -> find_groups, then thread_overview, get_group and
get_account to look closer. Every tool after fetch_thread takes the thread_id it returned.

Accounts appear only as masked ids (acct_1a2b3c). Names never leave this server.
"""

from __future__ import annotations

import argparse
import asyncio
import datetime as dt
import logging
import os
import sys

from mcp.server.mcpserver import MCPServer
from mcp.server.mcpserver.exceptions import ToolError

from . import sentiment, signals, store, youtube

logging.basicConfig(level=logging.INFO, stream=sys.stderr,  # stdout is the MCP channel: never print to it
                    format="%(asctime)s %(levelname)s radar-mcp %(message)s")
log = logging.getLogger("radar")
# httpx logs every request URL at INFO, and YouTube's URLs carry the API key.
for noisy in ("httpx", "httpcore"):
    logging.getLogger(noisy).setLevel(logging.WARNING)

DEFAULT_MAX_COMMENTS = int(os.environ.get("MAX_COMMENTS", 1000))
MAX_TEXT = 300  # characters of a comment shown to a model

mcp = MCPServer(
    name="comment-radar",
    instructions=(
        "Tools for finding groups of accounts that act together in a comment section. Start with fetch_thread, "
        "then analyze_sentiment and find_groups. Groups are candidates with evidence, not verdicts: an innocent "
        "explanation (a premiere, a fan community, a popular phrase) can produce the same signals."
    ),
)


def resolve(url: str) -> tuple[str, str]:
    """(platform, id) for a link the radar can read. New platforms go here."""
    video_id = youtube.video_id_from_url(url)
    if video_id:
        return "youtube", video_id
    raise ToolError("Only YouTube video links are supported so far.")


def _thread(thread_id: str) -> dict:
    thread = store.get(thread_id)
    if thread is None:
        raise ToolError(f"Unknown thread_id {thread_id!r}. Call fetch_thread first.")
    return thread


def _masks(thread: dict) -> dict[str, str]:
    """masked id -> channel id, for this thread's commenters."""
    return {signals.mask(c["author_id"]): c["author_id"] for c in thread["comments"] if c.get("author_id")}


def _age_days(account: dict | None, at: str | None) -> int | None:
    created, when = signals.parse_time((account or {}).get("created_at")), signals.parse_time(at)
    return (when - created).days if created and when else None


def _comment_view(c: dict, thread: dict) -> dict:
    return {
        "id": c["id"],
        "account": signals.mask(c["author_id"]) if c.get("author_id") else None,
        "published_at": c.get("published_at"),
        "is_reply": bool(c.get("parent_id")),
        "thread": c["thread_id"],
        "likes": c.get("like_count", 0),
        "sentiment": (thread.get("sentiment") or {}).get(c["id"]),
        "text": c["text"][:MAX_TEXT],
    }


def _account_view(masked: str, channel_id: str, thread: dict) -> dict:
    account = thread["accounts"].get(channel_id)
    mine = [c for c in thread["comments"] if c.get("author_id") == channel_id]
    first = min((c.get("published_at") or "" for c in mine), default=None)
    return {
        "account": masked,
        "created_at": (account or {}).get("created_at"),
        "age_days_at_first_comment": _age_days(account, first),
        "subscriber_count": (account or {}).get("subscriber_count"),
        "video_count": (account or {}).get("video_count"),
        "country": (account or {}).get("country"),
        "comments_here": len(mine),
        "profile_found": account is not None,  # False: the channel is gone or hidden
    }


def _group_summary(g: dict, thread: dict) -> dict:
    by_id = {c["id"]: c for c in thread["comments"]}
    return {
        "id": g["id"],
        "pattern": g["pattern"],
        "score": g["score"],
        "accounts": g["n_accounts"],
        "comments": g["n_comments"],
        "first_at": g["first_at"],
        "last_at": g["last_at"],
        "top_signals": [s["text"] for s in g["signals"][:3]],
        "sentiment": g["sentiment"],
        "sample_comments": [by_id[cid]["text"][:200] for cid in g["comment_ids"][:3]],
    }


@mcp.tool()
async def fetch_thread(url: str, max_comments: int = DEFAULT_MAX_COMMENTS, refresh: bool = False) -> dict:
    """Fetch a post's comments and the commenters' public profiles. Returns a thread_id for the other tools.
    url: a YouTube video link. max_comments: newest comments and replies to read (up to 2000).
    refresh: fetch again even if this thread was fetched in the last 30 days."""
    platform, item_id = resolve(url)
    thread_id = f"{platform}:{item_id}"
    thread = None if refresh else store.get(thread_id)
    cached = thread is not None
    if thread is None:
        try:
            data = await youtube.fetch_thread(item_id, max(1, min(max_comments, 2000)))
        except youtube.YouTubeError as e:
            raise ToolError(str(e)) from e
        thread = {"thread_id": thread_id, "platform": platform, "fetched_at": dt.datetime.now(dt.timezone.utc).isoformat(),
                  **data}
        store.put(thread)
    v = thread["video"]
    log.info("thread %s: %d comments, %d accounts (cached=%s)", thread_id, len(thread["comments"]),
             len(thread["accounts"]), cached)
    return {
        "thread_id": thread_id,
        "platform": platform,
        "title": v["title"],
        "channel": v["channel_title"],
        "published_at": v["published_at"],
        "was_live_or_premiere": v["was_live_or_premiere"],
        "comment_count_on_platform": v["comment_count"],
        "comments_fetched": len(thread["comments"]),
        "accounts": len({c["author_id"] for c in thread["comments"] if c.get("author_id")}),
        "fetched_at": thread["fetched_at"],
        "cached": cached,
    }


@mcp.tool()
async def analyze_sentiment(thread_id: str) -> dict:
    """Label every comment in the thread negative, neutral or positive with the sentiment model.
    Returns the overall distribution; labels are stored for find_groups and the other tools."""
    thread = _thread(thread_id)
    if not thread.get("sentiment") or thread.get("sentiment_model") != sentiment.model_name():
        results = await asyncio.to_thread(sentiment.classify, [c["text"] for c in thread["comments"]])
        thread = store.update(thread_id, sentiment={c["id"]: r["label"] for c, r in zip(thread["comments"], results)},
                              sentiment_model=sentiment.model_name())
    labels = list(thread["sentiment"].values())
    return {"thread_id": thread_id, "model": thread["sentiment_model"], "distribution": sentiment.distribution(labels)}


@mcp.tool()
async def find_groups(thread_id: str) -> dict:
    """Find candidate groups of accounts that act together (near-copy comments, young accounts replying
    together) and score each from 0 to 1. Run analyze_sentiment first so groups carry sentiment."""
    thread = _thread(thread_id)
    result = await asyncio.to_thread(signals.find_groups, thread["video"], thread["comments"], thread["accounts"],
                                     thread.get("sentiment") or {})
    store.update(thread_id, analysis=result)
    return {
        "thread_id": thread_id,
        "groups": [_group_summary(g, thread) for g in result["groups"]],
        "baseline": result["baseline"],
        "sentiment": result["sentiment"],
    }


@mcp.tool()
def thread_overview(thread_id: str) -> dict:
    """The video's facts and the whole comment section's baseline rates, to judge whether a group's signals
    are unusual here: e.g. if 40% of all commenters have young accounts, a young group means less."""
    thread = _thread(thread_id)
    v = thread["video"]
    analysis = thread.get("analysis") or {}
    return {
        "thread_id": thread_id,
        "title": v["title"],
        "channel": v["channel_title"],
        "published_at": v["published_at"],
        "was_live_or_premiere": v["was_live_or_premiere"],
        "live_started_at": v.get("live_started_at"),
        "views": v["view_count"],
        "comment_count_on_platform": v["comment_count"],
        "comments_fetched": len(thread["comments"]),
        "first_comment_at": min((c.get("published_at") or "" for c in thread["comments"]), default=None),
        "last_comment_at": max((c.get("published_at") or "" for c in thread["comments"]), default=None),
        "baseline": analysis.get("baseline"),
        "sentiment": analysis.get("sentiment"),
        "groups": [{"id": g["id"], "score": g["score"], "accounts": g["n_accounts"]} for g in analysis.get("groups", [])],
    }


@mcp.tool()
def get_group(thread_id: str, group_id: str) -> dict:
    """One candidate group in full: every signal with its value, each account's public profile facts,
    and every comment the group wrote here (time, text, sentiment, which reply thread)."""
    thread = _thread(thread_id)
    groups = {g["id"]: g for g in (thread.get("analysis") or {}).get("groups", [])}
    if group_id not in groups:
        raise ToolError(f"No group {group_id!r} in {thread_id}. Groups: {', '.join(groups) or 'none'}.")
    g = groups[group_id]
    masks = _masks(thread)
    by_id = {c["id"]: c for c in thread["comments"]}
    return {
        "id": g["id"],
        "pattern": g["pattern"],
        "score": g["score"],
        "signals": g["signals"],
        "features": g["features"],
        "accounts": [_account_view(m, masks[m], thread) for m in g["accounts"]],
        "comments": [_comment_view(by_id[cid], thread) for cid in g["comment_ids"]],
    }


@mcp.tool()
def get_account(thread_id: str, account: str) -> dict:
    """One commenter (by masked id, e.g. acct_1a2b3c): public profile facts and every comment it wrote in this thread."""
    thread = _thread(thread_id)
    masks = _masks(thread)
    if account not in masks:
        raise ToolError(f"No account {account!r} in {thread_id}.")
    mine = [c for c in thread["comments"] if c.get("author_id") == masks[account]]
    return {**_account_view(account, masks[account], thread), "comments": [_comment_view(c, thread) for c in mine]}


@mcp.tool()
def report_data(thread_id: str) -> dict:
    """Everything a results page needs: the video, every comment (masked), groups, timeline and sentiment
    comparison. Large; meant for the app, not for a model's context."""
    thread = _thread(thread_id)
    analysis = thread.get("analysis") or {}
    group_of = {cid: g["id"] for g in analysis.get("groups", []) for cid in g["comment_ids"]}
    comments = []
    for c in sorted(thread["comments"], key=lambda c: c.get("published_at") or ""):
        view = _comment_view(c, thread)
        view["text"] = c["text"][:2000]
        view["group"] = group_of.get(c["id"])
        comments.append(view)
    masks = _masks(thread)
    return {
        "thread_id": thread_id,
        "video": thread["video"],
        "fetched_at": thread["fetched_at"],
        "sentiment_model": thread.get("sentiment_model"),
        "comments": comments,
        "groups": [{**{k: v for k, v in g.items() if k != "comment_ids"},
                    "account_profiles": [_account_view(m, masks[m], thread) for m in g["accounts"]]}
                   for g in analysis.get("groups", [])],
        "baseline": analysis.get("baseline"),
        "timeline": analysis.get("timeline"),
        "sentiment": analysis.get("sentiment"),
        "settings": analysis.get("settings"),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Comment Radar MCP server")
    parser.add_argument("--http", action="store_true", help="serve Streamable HTTP instead of stdio")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8001)
    args = parser.parse_args()
    if args.http:
        mcp.run("streamable-http", host=args.host, port=args.port)
    else:
        mcp.run()


if __name__ == "__main__":
    main()
