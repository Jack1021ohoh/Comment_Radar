"""One analysis of a comment section, from link to report.

    code        fetch_thread -> analyze_sentiment, and in parallel:
    Watcher      Gemini watches the video (first WATCH_SECONDS): summary, claims, and the sides commenters take.
    Labeler      labels the stance of every new account's comment and a random sample of the rest, in parallel batches.
    code        save_stances -> find_groups (MCP tools): near-copies, reply rings, and sides new accounts push.
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
import random
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
from .schemas import Defense, Finding, StanceLabels, Summary
from .video import watch

log = setup_logging()
litellm.suppress_debug_info = True
ROOT = Path(__file__).resolve().parent.parent

MODEL = LitellmModel(model=os.environ.get("MODEL", "vertex_ai/gemini-3.6-flash"), api_key="unused")
SMALL_MODEL = LitellmModel(model=os.environ.get("SMALL_MODEL", "vertex_ai/gemini-3.5-flash-lite"), api_key="unused")

MAX_COMMENTS = int(os.environ.get("MAX_COMMENTS", 3000))  # keeps a first run well inside the graders' 5 minutes
MAX_INVESTIGATED = int(os.environ.get("MAX_INVESTIGATED", 4))  # groups that get an Investigator and a Defense
MIN_SCORE = float(os.environ.get("MIN_SCORE", 0.35))  # below this signal score, a group is listed but not investigated
AGENT_TURNS = 8
# The tools agents may call. fetch_thread, find_groups and report_data stay with the code.
AGENT_TOOLS = ["thread_overview", "get_group", "get_account", "search_comments"]
MAX_HISTORY = 6  # earlier questions and answers a follow-up sees
LABEL_BATCH = 60  # comments per Labeler call
LABEL_CONCURRENCY = 6
WATCH_SAMPLE = 80  # comments the Watcher sees, so the sides match what people argue about


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
        name="radar", cache_tools_list=True, client_session_timeout_seconds=600,
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
        name = re.sub(r" G?\d+$", "", agent.name)
        mine = self.by_agent.setdefault(name, {"input": 0, "output": 0, "calls": 0})
        mine["calls"] += 1
        usage = getattr(response, "usage", None)
        if usage:
            mine["input"] += getattr(usage, "input_tokens", 0) or 0
            mine["output"] += getattr(usage, "output_tokens", 0) or 0

    def add(self, name: str, tokens: dict) -> None:
        """Usage of a model call made outside the Agents SDK (the Watcher)."""
        mine = self.by_agent.setdefault(name, {"input": 0, "output": 0, "calls": 0})
        mine["calls"] += 1
        mine["input"] += tokens.get("input", 0)
        mine["output"] += tokens.get("output", 0)

    def total(self) -> dict:
        return {k: sum(a[k] for a in self.by_agent.values()) for k in ("input", "output", "calls")}


def make_agents(server: MCPServerStdio) -> dict[str, Agent]:
    common = {"mcp_servers": [server], "output_guardrails": [groups_not_people]}
    return {
        "investigator": Agent(name="Investigator", instructions=prompts.INVESTIGATOR, model=MODEL,
                              model_settings=settings("INVESTIGATOR", "low", 60), output_type=Finding, **common),
        "defense": Agent(name="Defense", instructions=prompts.DEFENSE, model=MODEL,
                         model_settings=settings("DEFENSE", "low", 60), output_type=Defense, **common),
        "labeler": Agent(name="Labeler", instructions=prompts.LABELER, model=SMALL_MODEL,
                         model_settings=settings("LABELER", timeout=60), output_type=StanceLabels),
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
            if isinstance(output, str):
                return scrub(output)
            return output.model_copy(update={k: scrub(v) if isinstance(v, str) else
                                             [scrub(x) for x in v] if isinstance(v, list) else v
                                             for k, v in output.model_dump().items()})


async def label_stances(agent: Agent, brief: dict, comments: list[dict], hooks: Usage) -> dict[str, str]:
    """comment id -> stance, for the comments the Labeler could label. A failed batch is skipped."""
    sides = brief["sides"]
    allowed = {s["id"] for s in sides} | {"off_topic", "promotion", "neutral"}
    head = (f"The video: {brief['summary']}\nSides:\n" + "\n".join(f"{s['id']}: {s['label']}. {s['description']}" for s in sides)
            + "\nOther labels: off_topic, promotion, neutral\n\nComments:\n")
    gate = asyncio.Semaphore(LABEL_CONCURRENCY)

    async def one(i: int, batch: list[dict]) -> dict[str, str]:
        def line(n: int, c: dict) -> str:
            reply = f"[reply to: {c['reply_to']}] " if c.get("reply_to") else ""
            return f"{n}. {reply}{c['text']}".replace("\n", " ")

        lines = "\n".join(line(n, c) for n, c in enumerate(batch))
        async with gate:
            try:
                out = (await Runner.run(agent.clone(name=f"Labeler {i}"), head + lines, hooks=hooks, max_turns=1)).final_output
            except Exception:
                log.exception("labeling batch %d failed", i)
                return {}
        labels = {}
        for lab in out.labels:
            stance = lab.stance.strip()
            stance = stance.upper() if re.fullmatch(r"[sS]\d", stance) else stance.lower().replace(" ", "_")
            if 0 <= lab.n < len(batch) and stance in allowed:
                labels[batch[lab.n]["id"]] = stance
        return labels

    batches = [comments[i:i + LABEL_BATCH] for i in range(0, len(comments), LABEL_BATCH)]
    out: dict[str, str] = {}
    for labels in await asyncio.gather(*(one(i, b) for i, b in enumerate(batches))):
        out.update(labels)
    return out


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

        agents = make_agents(server)

        async def read_tone() -> None:
            step("sentiment", "start")
            sentiment = await call(server, "analyze_sentiment", {"thread_id": thread_id})
            step("sentiment", "done", sentiment=sentiment)

        async def read_sides() -> None:
            """Watch the video, then label stances. Any failure skips the steering check, not the run."""
            if thread.get("stances_ready"):
                return  # this copy of the thread was labelled before
            step("watch", "start", seconds=min(thread.get("duration_seconds") or 600, 600))
            try:
                sample = await call(server, "stance_sample", {"thread_id": thread_id})
                texts = [c["text"] for c in random.Random(thread_id).sample(sample["comments"], min(WATCH_SAMPLE, len(sample["comments"])))]
                brief, tokens = await watch(thread, texts)
                hooks.add("Watcher", tokens)
            except Exception as e:
                log.exception("run %s: watching the video failed", run_id[:8])
                step("watch", "failed", error=f"{type(e).__name__}: {str(e)[:200]}")
                return
            step("watch", "done", brief=brief)
            step("stance", "start", comments=len(sample["comments"]), new=sample["new_labelled"],
                 sampled=sample["established_sampled"])
            stances = await label_stances(agents["labeler"], brief, sample["comments"], hooks)
            saved = await call(server, "save_stances", {"thread_id": thread_id, "brief": brief, "stances": stances})
            step("stance", "done", saved=saved)

        await asyncio.gather(read_tone(), read_sides())

        step("signals", "start")
        found = await call(server, "find_groups", {"thread_id": thread_id})
        candidates = [g for g in found["groups"] if g["score"] >= MIN_SCORE][:MAX_INVESTIGATED]
        step("signals", "done", groups=found["groups"], baseline=found["baseline"], stance=found.get("stance"))

        overview = await call(server, "thread_overview", {"thread_id": thread_id})
        brief_text = json.dumps({k: (overview.get("video_brief") or {}).get(k) for k in ("summary", "claims", "sides")},
                                ensure_ascii=False) if overview.get("video_brief") else "not available"
        context = (f"Thread: {thread_id}\nVideo: {thread['title']!r} by {thread['channel']}, "
                   f"premiere or livestream: {thread['was_live_or_premiere']}\n"
                   f"What the video says: {brief_text}\n"
                   f"Section baseline: {json.dumps(found['baseline'])}\n"
                   f"Sides new accounts take vs established accounts: {json.dumps(found.get('stance'), ensure_ascii=False)}\n")

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
                     "what_the_video_says": data.get("brief"), "sides_new_accounts_take": data.get("stance"),
                     "comments_analyzed": len(data["comments"]), "coverage": data.get("coverage"), "baseline": data["baseline"], "sentiment": data["sentiment"],
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
            "verdict": verdict, "summary": summary, "groups": groups, "comments": data["comments"], "accounts": data["accounts"],
            "coverage": data.get("coverage"), "brief": data.get("brief"), "stance": data.get("stance"), "timeline": data["timeline"], "sentiment": data["sentiment"], "baseline": data["baseline"],
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


# --- Follow-up questions about a finished report ---


def report_brief(report: dict) -> dict:
    """What the Analyst needs from a report, without the comment list (it searches that with a tool)."""
    v = report["video"]
    return {
        "video": {"title": v["title"], "channel": v["channel_title"], "published_at": v["published_at"],
                  "was_live_or_premiere": v["was_live_or_premiere"], "comments_on_youtube": v["comment_count"]},
        "comments_analyzed": len(report["comments"]), "coverage": report.get("coverage"),
        "what_the_video_says": report.get("brief"), "sides_new_accounts_take": report.get("stance"),
        "verdict": report["verdict"], "summary": report["summary"],
        "baseline": report["baseline"], "sentiment": report["sentiment"],
        "groups": [{"id": g["id"], "status": g["status"], "confidence": g["confidence"], "signal_score": g["score"],
                    "accounts": g["n_accounts"], "comments": g["n_comments"], "first_at": g["first_at"],
                    "last_at": g["last_at"], "signals": [s["text"] for s in g["signals"]],
                    "finding": g.get("finding"), "defense": g.get("defense")} for g in report["groups"]],
    }


async def ask(question: str, report: dict, history: list[dict], server: MCPServerStdio) -> dict:
    """Answer one follow-up question about a report. history: earlier [{"question", "answer"}], oldest first."""
    hooks = Usage()
    started = time.time()
    analyst = Agent(name="Analyst", instructions=prompts.ANALYST, model=MODEL, model_settings=settings("ANALYST", "low", 60),
                    mcp_servers=[server], output_guardrails=[groups_not_people])
    earlier = "\n\n".join(f"Q: {h['question']}\nA: {h['answer']}" for h in history[-MAX_HISTORY:]) or "none"
    prompt = (f"Thread: {report['thread']['thread_id']}\n\nReport:\n{json.dumps(report_brief(report), ensure_ascii=False)}\n\n"
              f"Earlier in this conversation:\n{earlier}\n\nQuestion: {question}")
    answer = await run_agent(analyst, prompt, hooks, "Analyst")
    return {"answer": str(answer), "seconds": round(time.time() - started, 1), "tokens": hooks.total()}
