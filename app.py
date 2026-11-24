"""Comment Radar: paste a YouTube link, find groups of accounts that act together in its comments.

    uv run app.py        then open http://localhost:8000

GET  /analyze?url=...   streams one analysis to the page as Server-Sent Events
POST /api/analyze       the same analysis as one JSON reply (for evals and scripts)

The radar's tools run in radar-mcp, an MCP server this app starts as a subprocess and keeps for its lifetime.
"""

import asyncio
import json
import os
import uuid
from contextlib import asynccontextmanager
from pathlib import Path

import uvicorn
from agents import set_tracing_disabled
from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

HERE = Path(__file__).parent
load_dotenv(HERE / ".env")  # before importing the agents, which read env vars

from agent.logs import setup as setup_logging  # noqa: E402
from agent.pipeline import analyze, radar_server  # noqa: E402
from radar_mcp.youtube import video_id_from_url  # noqa: E402

log = setup_logging()
set_tracing_disabled(True)  # traces would upload to OpenAI, and we're on Gemini

# Finished reports by video id, so a repeat (a grader retrying, a demo) is instant and spends nothing.
# In memory: Cloud Run should run one instance (--max-instances 1).
reports: dict[str, dict] = {}
MAX_REPORTS = 100
running = asyncio.Semaphore(int(os.environ.get("MAX_CONCURRENT", 3)))


@asynccontextmanager
async def lifespan(app: FastAPI):
    server = radar_server()
    await server.connect()
    app.state.radar = server
    log.info("radar-mcp connected")
    try:
        yield
    finally:
        await server.cleanup()


app = FastAPI(title="Comment Radar", lifespan=lifespan)
app.mount("/static", StaticFiles(directory=HERE / "static"), name="static")


@app.get("/")
def index():
    return FileResponse(HERE / "static" / "index.html", headers={"Cache-Control": "no-cache"})


@app.get("/healthz")
def healthz():
    return {"ok": True, "cached_reports": len(reports)}


def check_url(url: str) -> str:
    """The guardrail on input: only links the radar can read get through. Returns the video id."""
    video_id = video_id_from_url(url)
    if not video_id:
        raise HTTPException(400, "Paste a YouTube video link, like https://www.youtube.com/watch?v=...")
    return video_id


def remember(video_id: str, report: dict) -> None:
    if report.get("type") == "done":
        reports.pop(video_id, None)
        if len(reports) >= MAX_REPORTS:
            reports.pop(next(iter(reports)))
        reports[video_id] = report


@app.get("/analyze")
async def analyze_stream(url: str, fresh: bool = False):
    video_id = check_url(url)
    run_id = str(uuid.uuid4())
    queue: asyncio.Queue = asyncio.Queue()

    async def work():
        if not fresh and video_id in reports:
            queue.put_nowait({**reports[video_id], "cached": True})
            return
        async with running:
            report = await analyze(url, app.state.radar, queue.put_nowait, fresh=fresh, run_id=run_id)
        remember(video_id, report)
        queue.put_nowait(report)

    task = asyncio.create_task(work())

    async def events():
        try:
            yield f"data: {json.dumps({'type': 'start', 'run_id': run_id})}\n\n"
            while True:
                try:
                    event = await asyncio.wait_for(queue.get(), timeout=15)
                except asyncio.TimeoutError:
                    if task.done() and task.exception():
                        yield f"data: {json.dumps({'type': 'error', 'message': str(task.exception())})}\n\n"
                        break
                    yield ": keep-alive\n\n"  # proxies (Cloud Run) close idle streams
                    continue
                yield f"data: {json.dumps(event, default=str, ensure_ascii=False)}\n\n"
                if event["type"] in ("done", "error"):
                    break
        finally:
            task.cancel()  # the page closed the stream: stop spending tokens

    return StreamingResponse(events(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


class AnalyzeRequest(BaseModel):
    url: str
    fresh: bool = False


@app.post("/api/analyze")
async def analyze_json(request: AnalyzeRequest):
    """The whole report as JSON. Usually takes 30-90 seconds; a repeat of a recent link is instant."""
    video_id = check_url(request.url)
    if not request.fresh and video_id in reports:
        return {**reports[video_id], "cached": True}
    async with running:
        report = await analyze(request.url, app.state.radar, fresh=request.fresh)
    remember(video_id, report)
    return report


if __name__ == "__main__":
    uvicorn.run(app, host=os.environ.get("HOST", "127.0.0.1"), port=int(os.environ.get("PORT", 8000)))
