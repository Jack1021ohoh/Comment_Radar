"""The pipeline end to end, with the MCP tools run in-process on a made-up thread and fake agents."""

import asyncio
import json
from types import SimpleNamespace

import pytest
from agents import Runner
from agents.exceptions import OutputGuardrailTripwireTriggered
from mcp.server.mcpserver.exceptions import ToolError

from agent import pipeline
from agent.schemas import Defense, Finding, StanceLabel, StanceLabels, Summary
from radar_mcp import server, store
from tests import synthetic

URL = "https://www.youtube.com/watch?v=abcdefghijk"


class InProcess:
    """Stands in for MCPServerStdio: same call_tool, no subprocess."""

    async def call_tool(self, name, arguments):
        try:
            return await server.mcp.call_tool(name, arguments)
        except ToolError as e:  # over stdio, the server turns this into an is_error result
            return SimpleNamespace(is_error=True, content=[SimpleNamespace(text=str(e))], structured_content=None)


BRIEF = {"summary": "A news report on a market story.", "claims": ["The board reversed itself."],
         "sides": [{"id": "S1", "label": "It is corrupt", "description": "The deal is corrupt."},
                   {"id": "S2", "label": "It is fine", "description": "The deal makes sense."}],
         "source": "video", "watched_seconds": 600, "duration_seconds": 900}


@pytest.fixture(autouse=True)
def fake_watch(monkeypatch):
    """The Watcher, without a model: a fixed brief."""
    async def watch(video, comments):
        return BRIEF, {"input": 1000, "output": 100}

    monkeypatch.setattr(pipeline, "watch", watch)


def label(prompt: str) -> StanceLabels:
    """The fake Labeler: S1 for comments that say "corrupt", neutral otherwise."""
    lines = prompt.split("Comments:\n", 1)[1].splitlines()
    return StanceLabels(labels=[StanceLabel(n=int(l.split(".", 1)[0]), stance="S1" if "corrupt" in l.lower() else "neutral")
                                for l in lines if l.strip()])


@pytest.fixture
def scam_thread():
    store._threads.clear()
    store.put(synthetic.thread(synthetic.organic_thread(), synthetic.scam_reply_chain(), synthetic.copy_paste_group()))
    yield
    store._threads.clear()


def fake_agents(monkeypatch, verdicts: dict[str, str], accuse: bool = False):
    seen = []

    async def run(agent, prompt, **kwargs):
        seen.append(agent.name)
        gid = agent.name.split()[-1]
        if agent.name.startswith("Labeler"):
            return SimpleNamespace(final_output=label(prompt))
        if agent.name.startswith("Investigator"):
            headline = "acct_1a2b3c is a bot." if accuse else "Six new accounts praised one advisor within 15 minutes."
            out = Finding(group_id=gid, pattern="promotion_reply_chain", purpose="promote_or_scam", headline=headline,
                          evidence=["6 accounts", "all under 30 days old"], likely_purpose="promote a scam", confidence=0.8)
        elif agent.name.startswith("Defense"):
            v = verdicts.get(gid, "keep")
            out = Defense(group_id=gid, innocent_explanation="Fans of the channel", holds_up=v == "dismiss", verdict=v,
                          confidence={"keep": 0.8, "downgrade": 0.5, "dismiss": 0.6}[v], reason="numbers")
        else:
            out = Summary(headline="Coordinated replies found", summary="Two groups.")
        return SimpleNamespace(final_output=out)

    monkeypatch.setattr(Runner, "run", run)
    return seen


def test_full_run(monkeypatch, scam_thread):
    seen = fake_agents(monkeypatch, {"G2": "dismiss"})
    events = []
    report = asyncio.run(pipeline.analyze(URL, InProcess(), events.append))
    assert report["type"] == "done", report
    assert [g["id"] for g in report["groups"]] == ["G1", "G2"]
    status = {g["id"]: (g["status"], g["confidence"]) for g in report["groups"]}
    assert status["G1"] == ("kept", 0.8)
    assert status["G2"] == ("dismissed", 0.29)  # a dismissed group can't keep a high confidence
    assert report["verdict"]["level"] == "coordinated"
    assert sorted(s for s in seen if not s.startswith("Labeler")) == ["Defense G1", "Defense G2", "Investigator G1", "Investigator G2", "Reporter"]
    assert {e["step"] for e in events if e["type"] == "step"} == {"fetch", "sentiment", "watch", "stance", "signals", "investigate", "report"}
    assert report["brief"]["sides"][0]["label"] == "It is corrupt"
    assert report["stance"]["pushed"] == []  # nobody here says "corrupt"
    assert report["sentiment"]["grouped"]["n"] == 11
    assert all("author_name" not in c and "author_id" not in c for c in report["comments"])
    json.dumps(report)  # the page gets it as JSON


def test_downgraded_only_is_possible(monkeypatch, scam_thread):
    fake_agents(monkeypatch, {"G1": "downgrade", "G2": "dismiss"})
    report = asyncio.run(pipeline.analyze(URL, InProcess()))
    assert report["verdict"]["level"] == "possible"


def test_failed_agent_keeps_the_group(monkeypatch, scam_thread):
    async def broken(agent, prompt, **kwargs):
        raise TimeoutError("model timed out")

    monkeypatch.setattr(Runner, "run", broken)
    report = asyncio.run(pipeline.analyze(URL, InProcess()))
    assert report["type"] == "done"
    assert {g["status"] for g in report["groups"]} == {"review_failed"}
    assert report["verdict"]["level"] == "none"
    assert report["summary"]["headline"]  # the code writes one when the Reporter fails


def test_guardrail_scrubs_accusation(monkeypatch, scam_thread):
    fake_agents(monkeypatch, {}, accuse=True)
    real_run = Runner.run

    async def guarded(agent, prompt, **kwargs):
        result = await real_run(agent, prompt, **kwargs)
        for g in agent.output_guardrails:
            check = await g.guardrail_function(None, agent, result.final_output)
            if check.tripwire_triggered:
                raise OutputGuardrailTripwireTriggered(SimpleNamespace(
                    output=check, agent_output=result.final_output, guardrail=g, agent=agent))
        return result

    monkeypatch.setattr(Runner, "run", guarded)
    report = asyncio.run(pipeline.analyze(URL, InProcess()))
    headline = report["groups"][0]["finding"]["headline"]
    assert "bot" not in headline and "acct_1a2b3c" not in headline


def test_not_youtube(scam_thread):
    report = asyncio.run(pipeline.analyze("https://bsky.app/profile/x/post/y", InProcess()))
    assert report["type"] == "error"
    assert "YouTube" in report["message"]


def test_search_comments(scam_thread):
    async def main():
        tid, mcp = "youtube:abcdefghijk", InProcess()
        await pipeline.call(mcp, "find_groups", {"thread_id": tid})
        words = await pipeline.call(mcp, "search_comments", {"thread_id": tid, "query": "working FAMILIES"})
        g1 = await pipeline.call(mcp, "search_comments", {"thread_id": tid, "group": "G1", "limit": 2})
        outside = await pipeline.call(mcp, "search_comments", {"thread_id": tid, "group": "none"})
        return words, g1, outside
    words, g1, outside = asyncio.run(main())
    assert words["matches"] == 5 and words["by_group"] == {"G2": 5}
    assert g1["matches"] == 6 and len(g1["comments"]) == 2
    assert outside["matches"] == 60 and set(outside["by_group"]) == {"none"}


def test_report_has_every_account_for_the_plot(monkeypatch, scam_thread):
    fake_agents(monkeypatch, {})
    report = asyncio.run(pipeline.analyze(URL, InProcess()))
    accounts = {a["account"]: a for a in report["accounts"]}
    assert len(accounts) == 60 + 6 + 5
    scam = [a for a in accounts.values() if a["group"] == "G1"]
    assert len(scam) == 6 and all(a["age_days"] < 30 for a in scam)
    assert all(a["age_days"] > 365 for a in accounts.values() if a["group"] is None)


def test_follow_up_question(monkeypatch, scam_thread):
    fake_agents(monkeypatch, {})
    report = asyncio.run(pipeline.analyze(URL, InProcess()))
    prompts = []

    async def analyst(agent, prompt, **kwargs):
        prompts.append(prompt)
        return SimpleNamespace(final_output="G1 is promoting an advisor called Jane Doe.")

    monkeypatch.setattr(Runner, "run", analyst)
    history = [{"question": "Is it real?", "answer": "Two groups held up."}]
    out = asyncio.run(pipeline.ask("Who is being promoted?", report, history, InProcess()))
    assert out["answer"].startswith("G1 is promoting")
    assert "Question: Who is being promoted?" in prompts[0] and "Q: Is it real?" in prompts[0]
    assert '"comments": [' not in prompts[0]  # the comment list isn't pasted in; the agent searches it


def test_steering_group_is_investigated(monkeypatch):
    store._threads.clear()
    store.put(synthetic.thread(synthetic.organic_thread(300), synthetic.steering_wave(15)))
    seen = fake_agents(monkeypatch, {})
    report = asyncio.run(pipeline.analyze(URL, InProcess()))
    store._threads.clear()
    assert report["stance"]["pushed"] == ["S1"]
    steering = [g for g in report["groups"] if g["pattern"] == "steering"]
    assert len(steering) == 1 and steering[0]["status"] == "kept"
    assert f"Investigator {steering[0]['id']}" in seen
    assert report["stats"]["by_agent"]["Watcher"]["input"] == 1000
