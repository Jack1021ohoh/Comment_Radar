# CLAUDE.md

Guidance for Claude Code (and teammates) working in this repo.

Comment Radar finds groups of accounts that act together in a YouTube comment section. Paste a link; an MCP server fetches and scores the comments, agents argue each candidate group, and the page shows the evidence. Vocabulary is in [GLOSSARY.md](GLOSSARY.md).

## Commands

```bash
uv sync                                    # install (Python 3.11)
uv run app.py                              # web app on http://localhost:8000
uv run --group dev pytest                  # all tests; never call a model or YouTube
uv run python -m radar_mcp.server          # the MCP server alone (stdio)
npx @modelcontextprotocol/inspector uv run python -m radar_mcp.server   # try its tools by hand
uv run python -m radar_mcp.sentiment "I love it" "This is a scam"       # try the sentiment model
```

Running the agents needs `.env` (copy `.env.example`) and `gcloud auth application-default login`. There is no Gemini API key: `api_key="unused"` in `agent/pipeline.py` is intentional, because Vertex AI uses Google credentials.

## Work rules

- `DESIGN.md` must be written by hand, by the team. Never write or edit it.
- Use the OpenAI Agents SDK (`agents`, installed as `openai-agents`) for agent features rather than writing your own.
- Vertex AI credits and YouTube quota (10,000 units a day; a 1,000-comment video costs about 50) are limited. Check changes with the tests first. Ask before running real analyses in a loop.
- `tests/conftest.py` blocks model calls and sets `SENTIMENT_BACKEND=vader`, so `pytest` is free and fast. `tests/synthetic.py` builds made-up comment sections with known groups.

## Architecture

`app.py` starts `radar-mcp` as a subprocess (`agent/pipeline.py:radar_server`) and keeps it for the app's lifetime. `agent/pipeline.py:analyze` runs one analysis:

1. Code calls MCP tools: `fetch_thread` → `analyze_sentiment` → `find_groups`.
2. For each group with score ≥ `MIN_SCORE` (top `MAX_INVESTIGATED`), in parallel: Investigator → Defense. Both are agents with the read-only MCP tools in `AGENT_TOOLS` and structured output (`agent/schemas.py`).
3. Code sets each group's status and confidence from the Defense verdict, and the thread's verdict (`verdict_of`).
4. Reporter writes the headline. Code calls `report_data` for everything the page draws.

A failed agent costs its group the review, not the run. Every agent has the `groups_not_people` output guardrail; a trip gets one rewrite, then `scrub`.

### radar_mcp (MCP owner)

- `server.py`: the tools. Anticipated failures raise `ToolError` so the client sees the message; any other exception reaches the client only as "Error executing tool <name>".
- `resolve(url)` maps a link to a platform. A new platform needs a fetcher module like `youtube.py` that returns the same `{"video", "comments", "accounts"}` shape, and a branch in `resolve` and `fetch_thread`.
- `store.py`: threads in memory plus `data/cache/`. YouTube data older than 30 days is deleted, not served (developer policy).
- Names never leave the server: tools return masked ids (`signals.mask`).
- Never print to stdout in the server: it is the MCP channel. Log to stderr.

### Signals and ML (ML owner)

- `signals.py:find_groups`: links accounts (`similar_text`, `reply_chain`), groups them, computes features. Thresholds are the constants at the top.
- `signals.py:score_group` is the seam for a trained model: features dict in, score 0-1 and signal contributions out. Keep that contract and nothing else changes.
- `sentiment.py:classify` is the seam for the sentiment model: texts in, `{"label", "score", "scores"}` out. `SENTIMENT_MODEL` swaps the Hugging Face model; the Dockerfile preloads it at build.

## Coupling that spans files

- **Event stream:** events passed to `emit` in `pipeline.py` (`step`, `finding`, `defense`, `done`, `error`) are handled by `handle()` in `static/app.js`. `done` and `error` end the stream in `app.py`.
- **Report shape:** the `done` report in `pipeline.py` and `report_data` in `server.py` are drawn by `render*` in `static/app.js`. `Finding`/`Defense` fields are shown there too.
- **Statuses and patterns:** group `status` values in `pipeline.py` and `pattern` values in `signals.py` / `schemas.Pattern` have labels in `STATUS` / `PATTERNS` in `static/app.js`.
- **Agent tools:** `AGENT_TOOLS` in `pipeline.py` lists what agents may call; the prompts in `prompts.py` name those tools.
- **Env vars and import order:** `pipeline.py` reads env vars at import, so `app.py` calls `load_dotenv` first.

## Runtime

- Finished reports are kept in memory by video id (`reports` in `app.py`), so Cloud Run must run one instance.
- Logs: `logs/radar.log` and stderr. Each analysis saves a JSON record to `logs/runs/` (off on Cloud Run).
- The page escapes everything from the server with `esc()`: comment text is written by strangers.
