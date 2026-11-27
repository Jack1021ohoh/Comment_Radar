# Comment Radar

Paste a YouTube video link. Comment Radar **watches the video**, reads every comment and the commenters' public profiles, and checks whether **new, fake-looking accounts steer the discussion**: whether they push one side of the story far more than established commenters do, or act together (copy-paste campaigns, promotion reply chains, bursts of brand-new accounts). An Investigator agent and a Defense agent argue each case before it reports. Every comment also gets a sentiment label from a machine-learning model, so you can see whether the groups sound different from everyone else.

It reports groups with evidence, never single people: accounts appear only as masked ids.

**Live app:** TODO (Cloud Run URL)

## Try it

> TODO: fill in once the demo videos are chosen and cached.

1. **A comment section with a promotion ring.** Paste `TODO`. You should see: "Coordinated activity found", a group of young accounts praising one "advisor" in a reply thread within minutes, and the group's comments far more positive than everyone else's.
2. **An ordinary livestream.** Paste `TODO`. Comments arrive in a burst, but no group holds up: the Defense points to the livestream, and the verdict is "No clear coordination found".
3. **TODO third task.**

A first run takes about 2 to 3 minutes and 100k to 160k Gemini tokens (most of it watching the video). A video analyzed before comes back instantly, so the videos above are analyzed once after each deploy.

## How it works

```
link ─► radar-mcp: fetch comments + profiles ─┬─► sentiment model ───────────────────┐
                                              └─► Watcher (Gemini watches the video)  │
                                                   └─► Labeler ×N: stance of each     │
                                                       sampled comment, in parallel   │
                                                                                      ▼
                    candidate groups: near-copies · reply rings · sides new accounts push
                                                                                      │
                        ┌──────────── one per group, in parallel ─────────────────────┘
                        ▼
                  Investigator ─► Defense ─► (guardrail) ─► verdict in code ─► Reporter ─► page
```

1. **radar-mcp** reads the comment section from the YouTube Data API as whole reply threads (a comment and every reply under it), newest first, up to 3,000 comments, plus each commenter's channel (creation date, uploads, subscribers). See [How much of a section it reads](#how-much-of-a-section-it-reads).
2. A **sentiment model** (`cardiffnlp/twitter-roberta-base-sentiment-latest`, on CPU) labels every comment negative, neutral or positive.
3. **Watcher**: Gemini watches the first 10 minutes of the video (low resolution, about 55k tokens at most) and writes what it says and the 2 to 4 **sides** commenters take on it. **Labelers** (Gemini flash-lite, in parallel batches) give a stance to every comment by a new account (under 180 days old) and to a random sample of 600 other comments. Code then compares new and established accounts side by side: a side new accounts take far more often (Fisher's exact test, p < 0.01 after a Bonferroni correction, at least 1.5× as often) is **pushed**, and the new accounts pushing it become a candidate group.
4. **Signals** link two accounts when their comments are near-copies, or when young accounts crowd a stretch of one reply thread more than chance allows (a binomial test against the section's own rate of young accounts, p < 0.001). Linked accounts form candidate groups, each scored from 0 to 1.
5. For each strong candidate, an **Investigator** makes the case with the MCP tools, then a **Defense** looks for the innocent explanation (a premiere, a fan community, a popular phrase) and keeps, downgrades or dismisses it.
6. Code decides the verdict from their structured outputs; a **Reporter** writes the headline.
7. **Ask the radar**: follow-up questions in any language. An Analyst agent answers with the same MCP tools (it can search and count comments), so answers carry numbers from the data.

## How much of a section it reads

The unit is the **reply thread**, not the comment. Rings that bait viewers live in the replies: under one video in our tests, 20 new accounts promoted two "trading coaches" in 21 comments across two reply threads. Our first version read only the replies YouTube sends along with each thread (up to 5) and saw 6 of those 21 comments. Reading threads whole is what makes rings like this visible.

- **Up to 3,000 comments, the section is read in full.** Every thread, every reply. The baseline rates (young accounts, uploads, timing) are then exact for the section, with no sampling error, and a group is compared with the whole section it sits in.
- **Above 3,000, the newest threads are read whole and older ones are skipped.** The page says how much was read. Threads are never cut and never sampled at random: a ring sits in one thread, so a random sample of 30% of the comments keeps 3 or more of a 5-account ring only 16% of the time (binomial, n = 5, p = 0.3), and a group needs 3.
- **Why 3,000.** It is a time limit, not a statistical one: graders wait at most 5 minutes per task, and the sentiment model runs on a CPU (about 15 ms a comment on a laptop, slower on a small Cloud Run instance). At 3,000 a first run takes about 2 to 3 minutes. `MAX_COMMENTS` raises it, up to 10,000.

When a thread is busy, young accounts appear in it by chance. The radar tests each stretch of replies between two young accounts: if young accounts are, say, 4% of the section, 5 young accounts in 6 consecutive replies has a chance of about 1 in 1.7 million, while 2 in 20 happens 19% of the time. Because many stretches are tested, a link needs p < 0.001.

Stances are sampled, not read in full: every new account is labelled, but established accounts are a random sample of 600 comments, so their share of a side is within about ±4 points (95%). The page draws that interval. The unit is the account (each counts once, with the side most of its comments take), so one prolific commenter can't tip a side.

## Sentiment eval

A test set of 240 comments from 3 cached videos, stratified across non-English, promotion, possible sarcasm and general comments. Claude labelled them against written rules ([CRITERIA.md](evals/sentiment/CRITERIA.md): label the emotion shown, not the opinion; sarcasm and demands to punish count as negative). A human relabelled 71 of them, and those labels win. Human and Claude agree on 73% of comments, which sets a ceiling on how much any model can measurably improve.

| Model | Accuracy | Macro-F1 |
|---|---|---|
| VADER | 40.8% | 0.375 |
| twitter-roberta (default) | 75.4% | 0.743 |
| XLM-R, multilingual | 73.3% | 0.670 |
| Linear probe (mpnet + logistic regression) | 67.1% | 0.605 |
| XLM-R, fine-tuned on 1,000 comments | 75.4% | 0.734 |
| twitter-roberta, fine-tuned on 1,000 comments | 76.2% | 0.743 |
| **Routed**: roberta, XLM-R for non-Latin text | **77.5%** | **0.756** |

Fine-tuning didn't clearly help. Routing helps most on non-English comments (72% → 85% accuracy). Its gain over the default is +2.1 points, but the 95% CI is [0.0, +4.6] and McNemar's test gives p = 0.12, so it isn't significant. Routing costs about 4 ms more per comment. The default stays `transformer`; turn routing on with `SENTIMENT_BACKEND=routed`. SetFit was too slow to finish on a laptop.

Comment data and labels are not committed (YouTube data must be deleted after 30 days). To rebuild: `make_sheet.py` → label → `python -m evals.sentiment.evaluate transformer routed`.

## Course concepts

| Concept | Group | Where |
|---|---|---|
| Using your own MCP server | Coding Agents | [radar_mcp/server.py](radar_mcp/server.py); connected in [agent/pipeline.py](agent/pipeline.py) (`radar_server`) |
| Parallel fan-out | Multi-Agent | [agent/pipeline.py](agent/pipeline.py): `label_stances` (Labeler batches) and `review` (every group), each with `asyncio.gather` |
| Generator/Critic | Multi-Agent | Investigator and Defense: [agent/pipeline.py](agent/pipeline.py), [agent/prompts.py](agent/prompts.py) |
| Structured output | Tools | [agent/schemas.py](agent/schemas.py) |
| Guardrails | Tools | [agent/guardrails.py](agent/guardrails.py) (output), `check_url` in [app.py](app.py) (input) |
| Offline eval | Evaluation | `evals/sentiment/` (see [Sentiment eval](#sentiment-eval)) |

## Run it locally

Team setup, how to read a report, and what is left to do: [TEAM.md](TEAM.md).

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
- Request timeout 900 s; minimum and maximum instances 1. Finished reports are kept in memory, so one instance that never scales to zero keeps the grader videos instant. After each deploy, run the grader videos once and time a fresh run: it must finish well inside 5 minutes.
- Env: `VERTEXAI_PROJECT`, `VERTEX_LOCATION=global`; `YOUTUBE_API_KEY` from Secret Manager.
- The service account needs the Vertex AI User role.
