"""One analysis of a comment section, from link to report.

    code        fetch_thread -> analyze_sentiment -> find_groups (MCP tools; no model involved)
    Investigator one per candidate group, in parallel, each in a fresh context, with read-only MCP tools.
                 Makes the case that the group acts together (Finding).
    Defense      one per Finding, in parallel: the strongest innocent reading, and a verdict (Generator/Critic).
    Reporter     the headline and summary for the whole section.

The statistics find candidates; the agents read the evidence and argue both sides; code decides the
thread's verdict from their structured outputs. Every agent has the groups_not_people output guardrail.
A failed agent costs its group the review, not the run: the group is still shown with its signal score.

Models are Gemini on Vertex AI through LiteLLM, as in Project 2. MODEL and CHECK_MODEL override them.
"""

from __future__ import annotations

import asyncio
import json
import os
import re
import sys
import time
import uuid
from pathlib import Path

import litellm
from agents import Agent, ModelSettings, RunHooks, Runner
from agents.exceptions import OutputGuardrailTripwireTriggered
from agents.extensions.models.litellm_model import LitellmModel
from agents.mcp import MCPServerStdio, create_static_tool_filter

from . import prompts
from .guardrails import accusations, groups_not_people, scrub
from .logs import save_run, setup as setup_logging
from .schemas import Defense, Finding, Summary

log = setup_logging()
litellm.suppress_debug_info = True
ROOT = Path(__file__).resolve().parent.parent

MODEL = LitellmModel(model=os.environ.get("MODEL", "vertex_ai/gemini-3.6-flash"), api_key="unused")
SMALL_MODEL = LitellmModel(model=os.environ.get("SMALL_MODEL", "vertex_ai/gemini-3.5-flash-lite"), api_key="unused")

MAX_COMMENTS = int(os.environ.get("MAX_COMMENTS", 1000))
MAX_INVESTIGATED = int(os.environ.get("MAX_INVESTIGATED", 4))  # groups that get an Investigator and a Defense
MIN_SCORE = float(os.environ.get("MIN_SCORE", 0.35))  # below this signal score, a group is listed but not investigated
AGENT_TURNS = 8
# The tools agents may call. fetch_thread, find_groups and report_data stay with the code.
AGENT_TOOLS = ["thread_overview", "get_group", "get_account"]


def settings(agent: str, effort: str = "", timeout: int = 60) -> ModelSettings:
    """A timeout of a few times the usual call, one LiteLLM retry. <AGENT>_EFFORT overrides the reasoning effort."""
    effort = os.environ.get(f"{agent}_EFFORT", effort)
    return ModelSettings(include_usage=True, extra_args={
        "vertex_location": os.environ.get("VERTEX_LOCATION", "global"), "timeout": timeout, "num_retries": 1,
        **({"reasoning_effort": effort} if effort else {})})


def radar_server() -> MCPServerStdio:
    """radar-mcp as a subprocess. The env is passed on whole: the MCP client otherwise drops YOUTUBE_API_KEY."""
    return MCPServerStdio(
        params={"command": sys.executable, "args": ["-m", "radar_mcp.server"], "cwd": str(ROOT), "env": dict(os.environ)},
        name="radar", cache_tools_list=True, client_session_timeout_seconds=240,
        tool_filter=create_static_tool_filter(allowed_tool_names=AGENT_TOOLS))


class RadarError(Exception):
    """A failure to show the user as is, like comments being turned off."""


async def call(server: MCPServerStdio, tool: str, args: dict) -> dict:
    """Call an MCP tool from code and return its JSON result."""
    result = await server.call_tool(tool, args)
    text = "".join(getattr(c, "text", "") for c in result.content)
    if result.is_error:
        raise RadarError(re.sub(r"^Error executing tool \w+: ", "", text) or f"{tool} failed")
    if isinstance(result.structured_content, dict):
        return result.structured_content
    return json.loads(text)


class Usage(RunHooks):
    def __init__(self):
        self.by_agent: dict[str, dict] = {}

    async def on_llm_end(self, context, agent, response):
        name = re.sub(r" G\d+$", "", agent.name)
        mine = self.by_agent.setdefault(name, {"input": 0, "output": 0, "calls": 0})
        mine["calls"] += 1
        usage = getattr(response, "usage", None)
        if usage:
            mine["input"] += getattr(usage, "input_tokens", 0) or 0
            mine["output"] += getattr(usage, "output_tokens", 0) or 0

    def total(self) -> dict:
        return {k: sum(a[k] for a in self.by_agent.values()) for k in ("input", "output", "calls")}


def make_agents(server: MCPServerStdio) -> dict[str, Agent]:
    common = {"mcp_servers": [server], "output_guardrails": [groups_not_people]}
    return {
        "investigator": Agent(name="Investigator", instructions=prompts.INVESTIGATOR, model=MODEL,
                              model_settings=settings("INVESTIGATOR", "low", 60), output_type=Finding, **common),
        "defense": Agent(name="Defense", instructions=prompts.DEFENSE, model=MODEL,
                         model_settings=settings("DEFENSE", "low", 60), output_type=Defense, **common),
        "reporter": Agent(name="Reporter", instructions=prompts.REPORTER, model=SMALL_MODEL,
                          model_settings=settings("REPORTER", timeout=45), output_type=Summary,
                          output_guardrails=[groups_not_people]),
    }


async def run_agent(agent: Agent, prompt: str, hooks: Usage, name: str):
    """Run one agent. If its output trips the guardrail, ask once more; then scrub what's left."""
    agent = agent.clone(name=name)
    try:
        return (await Runner.run(agent, prompt, hooks=hooks, max_turns=AGENT_TURNS)).final_output
    except OutputGuardrailTripwireTriggered as e:
        flagged = e.guardrail_result.output.output_info.get("accusations", [])
        log.warning("%s: guardrail tripped on %s; asking for a rewrite", name, flagged)
        retry = (f"{prompt}\n\nYour last answer described single accounts as fake or bots ({'; '.join(flagged)}). "
                 "Describe what the group did instead.")
        try:
            return (await Runner.run(agent, retry, hooks=hooks, max_turns=AGENT_TURNS)).final_output
        except OutputGuardrailTripwireTriggered as e2:
            output = e2.guardrail_result.agent_output
            return output.model_copy(update={k: scrub(v) if isinstance(v, str) else
                                             [scrub(x) for x in v] if isinstance(v, list) else v
                                             for k, v in output.model_dump().items()})


def clamp(x: float) -> float:
    return round(max(0.0, min(1.0, float(x))), 2)


def verdict_of(groups: list[dict]) -> dict:
    """The thread's verdict, decided in code from the reviewed groups."""
    reviewed = [g for g in groups if g.get("status") in ("kept", "downgraded")]
    best = max((g["confidence"] for g in reviewed), default=0.0)
    if best >= 0.6:
        level, text = "coordinated", "Coordinated activity found"
    elif best >= 0.4:
        level, text = "possible", "Possible coordination, weak evidence"
    else:
        level, text = "none", "No clear coordination found"
    return {"level": level, "text": text, "top_confidence": best}


async def analyze(url: str, server: MCPServerStdio, emit=lambda event: None, *, fresh: bool = False,
                  run_id: str | None = None) -> dict:
    """Analyze one link. emit(event) receives progress events for the page. Returns the report."""
    run_id = run_id or str(uuid.uuid4())
    started = time.time()
    hooks = Usage()
    record: dict = {"run_id": run_id, "url": url, "model": MODEL.model, "events": []}

    def step(name: str, status: str, **data) -> None:
        event = {"type": "step", "step": name, "status": status, "elapsed": round(time.time() - started, 1), **data}
        record["events"].append(event)
        emit(event)

    try:
        step("fetch", "start")
        thread = await call(server, "fetch_thread", {"url": url, "max_comments": MAX_COMMENTS, "refresh": fresh})
        thread_id = thread["thread_id"]
        step("fetch", "done", thread=thread)
        if thread["comments_fetched"] == 0:
            raise RadarError("This video has no comments to analyze.")

        step("sentiment", "start")
        sentiment = await call(server, "analyze_sentiment", {"thread_id": thread_id})
        step("sentiment", "done", sentiment=sentiment)

        step("signals", "start")
        found = await call(server, "find_groups", {"thread_id": thread_id})
        candidates = [g for g in found["groups"] if g["score"] >= MIN_SCORE][:MAX_INVESTIGATED]
        step("signals", "done", groups=found["groups"], baseline=found["baseline"])

        agents = make_agents(server)
        context = (f"Thread: {thread_id}\nVideo: {thread['title']!r} by {thread['channel']}, "
                   f"premiere or livestream: {thread['was_live_or_premiere']}\n"
                   f"Section baseline: {json.dumps(found['baseline'])}\n")

        async def review(group: dict) -> dict:
            gid = group["id"]
            out = {"group_id": gid}
            try:
                finding = await run_agent(agents["investigator"],
                                          f"{context}\nCandidate group:\n{json.dumps(group, ensure_ascii=False)}",
                                          hooks, f"Investigator {gid}")
                out["finding"] = finding.model_dump()
                emit({"type": "finding", "group_id": gid, "finding": out["finding"]})
                defense = await run_agent(agents["defense"],
                                          f"{context}\nCandidate group:\n{json.dumps(group, ensure_ascii=False)}\n\n"
                                          f"The Investigator's case:\n{finding.model_dump_json()}",
                                          hooks, f"Defense {gid}")
                out["defense"] = defense.model_dump()
                emit({"type": "defense", "group_id": gid, "defense": out["defense"]})
            except Exception as e:
                log.exception("run %s: review of %s failed", run_id[:8], gid)
                out["error"] = f"{type(e).__name__}: {str(e)[:200]}"
            return out

        step("investigate", "start", groups=[g["id"] for g in candidates])
        reviews = {r["group_id"]: r for r in await asyncio.gather(*(review(g) for g in candidates))}
        step("investigate", "done")

        data = await call(server, "report_data", {"thread_id": thread_id})
        groups = []
        for g in data["groups"]:
            r = reviews.get(g["id"], {})
            if "defense" in r:
                d = r["defense"]
                status = {"keep": "kept", "downgrade": "downgraded", "dismiss": "dismissed"}[d["verdict"]]
                confidence = clamp(min(d["confidence"], 0.29) if status == "dismissed" else d["confidence"])
            elif "finding" in r:
                status, confidence = "unreviewed", clamp(r["finding"]["confidence"])
            else:
                status = "not_investigated" if g["score"] < MIN_SCORE or g["id"] not in reviews else "review_failed"
                confidence = None
            groups.append({**g, "finding": r.get("finding"), "defense": r.get("defense"), "status": status,
                           "confidence": confidence})
        verdict = verdict_of(groups)

        step("report", "start")
        summary = None
        try:
            brief = {"video": {k: data["video"][k] for k in ("title", "channel_title", "was_live_or_premiere", "comment_count")},
                     "comments_analyzed": len(data["comments"]), "baseline": data["baseline"], "sentiment": data["sentiment"],
                     "verdict": verdict, "groups": [{k: g[k] for k in ("id", "n_accounts", "n_comments", "score", "status",
                                                                       "confidence", "finding", "defense")} for g in groups]}
            summary = (await run_agent(agents["reporter"], json.dumps(brief, ensure_ascii=False), hooks, "Reporter")).model_dump()
        except Exception:
            log.exception("run %s: reporter failed", run_id[:8])
        if not summary:
            n = sum(1 for g in groups if g["status"] in ("kept", "downgraded"))
            summary = {"headline": verdict["text"], "summary": f"{n} of {len(groups)} candidate groups held up after review."}
        step("report", "done")

        tokens = hooks.total()
        report = {
            "type": "done", "run_id": run_id, "url": url, "thread": thread, "video": data["video"],
            "verdict": verdict, "summary": summary, "groups": groups, "comments": data["comments"],
            "timeline": data["timeline"], "sentiment": data["sentiment"], "baseline": data["baseline"],
            "sentiment_model": data["sentiment_model"], "settings": data["settings"],
            "stats": {"seconds": round(time.time() - started, 1), "tokens": tokens, "by_agent": hooks.by_agent,
                      "model": MODEL.model},
        }
        record.update(status="done", verdict=verdict, summary=summary, reviews=reviews, stats=report["stats"],
                      groups=[{k: g[k] for k in ("id", "score", "status", "confidence", "n_accounts")} for g in groups])
        return report
    except RadarError as e:
        record.update(status="error", error=str(e))
        return {"type": "error", "run_id": run_id, "message": str(e)}
    except Exception as e:
        log.exception("run %s failed", run_id[:8])
        record.update(status="error", error=f"{type(e).__name__}: {e}")
        return {"type": "error", "run_id": run_id, "message": f"{type(e).__name__}: {str(e)[:300]}"}
    finally:
        record["seconds"] = round(time.time() - started, 1)
        save_run(record)
