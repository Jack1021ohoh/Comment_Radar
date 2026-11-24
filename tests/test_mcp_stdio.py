"""radar-mcp over real stdio, the way app.py runs it. The thread comes from a cache file, so nothing reaches YouTube."""

import asyncio
import json

from agent.pipeline import AGENT_TOOLS, RadarError, call, radar_server
from tests import synthetic


def test_tools_over_stdio(monkeypatch, tmp_path):
    t = synthetic.thread(synthetic.organic_thread(), synthetic.scam_reply_chain())
    (tmp_path / "youtube_abcdefghijk.json").write_text(json.dumps(t), encoding="utf-8")
    monkeypatch.setenv("CACHE_DIR", str(tmp_path))

    async def main():
        server = radar_server()
        await server.connect()
        try:
            visible = {tool.name for tool in await server.list_tools()}
            fetched = await call(server, "fetch_thread", {"url": "https://youtu.be/abcdefghijk"})
            sentiment = await call(server, "analyze_sentiment", {"thread_id": fetched["thread_id"]})
            groups = await call(server, "find_groups", {"thread_id": fetched["thread_id"]})
            group = await call(server, "get_group", {"thread_id": fetched["thread_id"], "group_id": "G1"})
            try:
                await call(server, "fetch_thread", {"url": "https://bsky.app/profile/x/post/y"})
                error = None
            except RadarError as e:
                error = str(e)
            return visible, fetched, sentiment, groups, group, error
        finally:
            await server.cleanup()

    visible, fetched, sentiment, groups, group, error = asyncio.run(main())
    assert error == "Only YouTube video links are supported so far."  # the user sees the reason, not a crash message
    assert visible == set(AGENT_TOOLS)  # agents can't fetch or pull the whole report
    assert fetched["cached"] and fetched["comments_fetched"] == len(t["comments"])
    assert sentiment["model"] == "vader" and sentiment["distribution"]["n"] == len(t["comments"])
    assert len(groups["groups"]) == 1 and groups["groups"][0]["accounts"] == 6
    assert len(group["accounts"]) == 6 and all(a["account"].startswith("acct_") for a in group["accounts"])
