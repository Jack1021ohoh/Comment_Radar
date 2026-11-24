# Comment Radar

Paste a YouTube video link. Comment Radar reads the comments and the commenters' public profiles, finds **groups of accounts that act together** (copy-paste campaigns, promotion reply chains, bursts of brand-new accounts), and has an Investigator agent and a Defense agent argue each case before it reports. Every comment also gets a sentiment label from a machine-learning model, so you can see whether the groups sound different from everyone else.

It reports groups with evidence, never single people: accounts appear only as masked ids.

**Live app:** TODO (Cloud Run URL)

## Try it

> TODO: fill in once the demo videos are chosen and cached.

1. **A comment section with a promotion ring.** Paste `TODO`. You should see: "Coordinated activity found", a group of young accounts praising one "advisor" in a reply thread within minutes, and the group's comments far more positive than everyone else's.
2. **An ordinary livestream.** Paste `TODO`. Comments arrive in a burst, but no group holds up: the Defense points to the livestream, and the verdict is "No clear coordination found".
3. **TODO third task.**

Each run takes about 30–90 seconds. A video analyzed before comes back instantly.

## How it works

```
link ─► radar-mcp (MCP server) ─► fetch comments + profiles ─► sentiment model ─► candidate groups
                                                                                      │
                        ┌──────────── one per group, in parallel ─────────────────────┘
                        ▼
                  Investigator ─► Defense ─► (guardrail) ─► verdict in code ─► Reporter ─► page
```

1. **radar-mcp** fetches up to 1,000 of the newest comments and replies from the YouTube Data API, plus each commenter's channel (creation date, uploads, subscribers).
2. A **sentiment model** (`cardiffnlp/twitter-roberta-base-sentiment-latest`, on CPU) labels every comment negative, neutral or positive.
3. **Signals** link two accounts when their comments are near-copies, or when both were young accounts replying in the same thread within an hour. Linked accounts form candidate groups, each scored from 0 to 1.
4. For each strong candidate, an **Investigator** makes the case with the MCP tools, then a **Defense** looks for the innocent explanation (a premiere, a fan community, a popular phrase) and keeps, downgrades or dismisses it.
5. Code decides the verdict from their structured outputs; a **Reporter** writes the headline.

## Course concepts

| Concept | Group | Where |
|---|---|---|
| Using your own MCP server | Coding Agents | [radar_mcp/server.py](radar_mcp/server.py); connected in [agent/pipeline.py](agent/pipeline.py) (`radar_server`) |
| Parallel fan-out | Multi-Agent | [agent/pipeline.py](agent/pipeline.py) (`review`, run for every group with `asyncio.gather`) |
| Generator/Critic | Multi-Agent | Investigator and Defense: [agent/pipeline.py](agent/pipeline.py), [agent/prompts.py](agent/prompts.py) |
| Structured output | Tools | [agent/schemas.py](agent/schemas.py) |
| Guardrails | Tools | [agent/guardrails.py](agent/guardrails.py) (output), `check_url` in [app.py](app.py) (input) |
| Offline eval | Evaluation | TODO `evals/` |

## Run it locally

```bash
uv sync                      # Python 3.11
cp .env.example .env         # set VERTEXAI_PROJECT and YOUTUBE_API_KEY
gcloud auth application-default login
uv run app.py                # http://localhost:8000
uv run --group dev pytest    # tests; they never call a model or YouTube
```

## Deploy

Cloud Run, continuous deployment from GitHub (Cloud Run > Create service > Continuously deploy from a repository > Cloud Build, Dockerfile). Settings:

- Memory 4 GiB, 2 vCPU (the sentiment model runs on CPU).
- Request timeout 900 s; maximum instances 1 (finished reports are kept in memory).
- Env: `VERTEXAI_PROJECT`, `VERTEX_LOCATION=global`; `YOUTUBE_API_KEY` from Secret Manager.
- The service account needs the Vertex AI User role.
