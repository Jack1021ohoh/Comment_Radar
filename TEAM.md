# Team guide: how to use Comment Radar, and what is left

Status on 2026-11-24: the base works end to end on YouTube (fetch, sentiment, watching the video, stances,
groups, Investigator and Defense, report, follow-up questions). 40 tests pass. What's missing is below,
by owner. Deadline: repo URL on Courseworks by **Wed 12/9, 11:59pm**; presentation on 12/10.

## 1. Run it on your machine

```bash
git clone https://github.com/Jack1021ohoh/Comment_Radar.git && cd Comment_Radar
uv sync                                  # Python 3.11; first run downloads torch
cp .env.example .env                     # then fill in the values below
gcloud auth application-default login    # Gemini runs on Vertex AI with your Google login, no API key
uv run app.py                            # http://localhost:8000
uv run --group dev pytest                # 40 tests, free: they never call Gemini or YouTube
```

`.env` needs:

| Variable | What |
|---|---|
| `VERTEXAI_PROJECT` | Your own GCP project with Vertex AI enabled. The prototype used `agentic-ai-4995`; switch to yours. |
| `VERTEX_LOCATION` | `global` |
| `YOUTUBE_API_KEY` | A YouTube Data API v3 key (Google Cloud console > APIs & Services > Credentials). Never commit it. |

Close memory-hungry apps before a run. On a 16 GB Mac with swap full, the sentiment step went from 45 s to almost 5 minutes.

## 2. Use it

1. Paste a YouTube video link and press **Scan comments**. A first run takes about 2 to 3 minutes and 100k to 160k Gemini tokens.
2. Leave **"Fetch the comments again"** unticked to reuse saved data (comments are kept 30 days in `data/cache/`, finished reports until the server restarts). Tick it only when the video got new comments or the fetch code changed.
3. Read the report top to bottom; each section answers one question:

| Section | Question it answers |
|---|---|
| 1 Verdict | Are fake-looking accounts steering or gaming this comment section? |
| 2 The video and its sides | What the video says (Gemini watched the first 10 minutes), and which side new accounts take against established ones. A red "Pushed by new accounts" tag means a side passed the statistical test. |
| 3 Groups | Each group of accounts acting together: the Investigator's evidence, the Defense's innocent reading, and the ruling. |
| 4 How they stand out | Every account is a dot. Closer to the centre = newer account; clockwise = order of first comment. A cluster of coloured dots near the centre = new accounts that showed up together. |
| 5 Tone | Sentiment of group comments vs everyone else (ML model). |
| 6 Timing | Comments over time, with group posts marked. |
| 7 Ask | Follow-up questions in any language; an agent searches the comments before answering. |
| All comments | Every comment with its tone, side and group; filter to check evidence. |

Videos tested so far (good grader-task candidates once re-run on the deployed app):

| Video | What it shows |
|---|---|
| CNN, Jensen Huang reinstated: `https://www.youtube.com/watch?v=hQiUMK-QDjU` | A promotion/scam ring: 20 new accounts praising two "trading coaches" in reply threads. Kept at 95%. No side pushed. |
| CNN, ~700K Russian soldiers killed: `https://www.youtube.com/watch?v=4_RV_5-nZFg` | Opinion steering: new accounts post off-topic 19% vs 5% (p = 0.006); 4 accounts created within 21 minutes posted within 38 seconds. |
| Fox News, Dems take control of Congress: `https://www.youtube.com/watch?v=gcR_uANqXFs` | Nothing found, correctly: both sides argue, new and established accounts split the same way. |

## 3. What is left

### Everyone

- [ ] **DESIGN.md, written by hand by the team.** No AI: it is checked with Pangram. At most 1,000 words, the 6 required sections. Claude must not write or edit it.
- [ ] **README "Try it":** replace the TODO grader tasks with 3 videos and what a grader should see. Re-run them on the deployed app first; findings can change as comments change.
- [ ] **README concepts table:** "Offline eval" is still TODO. Either build it (see ML) or remove the row. Graders check that every concept named is used. The other 5 (own MCP server, parallel fan-out, Generator/Critic, structured output, guardrails) are done.
- [ ] **submission.json:** add `deploy_url` once deployed. Authors are set.
- [ ] **GitHub collaborators:** add `codeboi07`, `bhuvighosh3`, `nniishhh`, `x` (Settings > Collaborators), if the repo is private.
- [ ] **Presentation (12/10):** 4 minutes plus 1 of questions, live demo, startup pitch style. Keep a finished report open in another tab in case a live run is slow.

### Cloud Run deployment

- [ ] Cloud Run > Create service > Continuously deploy from a repository (Cloud Build, `Dockerfile`). Settings in the README's Deploy section: 4 GiB, 2 vCPU, request timeout 900 s, **minimum and maximum instances 1** (reports live in memory; one instance that never scales to zero keeps grader videos instant).
- [ ] Env vars `VERTEXAI_PROJECT`, `VERTEX_LOCATION=global`; `YOUTUBE_API_KEY` from Secret Manager. The service account needs the Vertex AI User role.
- [ ] **Time a fresh run on Cloud Run** (tick "Fetch again") on the largest grader video. Graders wait at most 5 minutes per task. If it's close, lower `MAX_COMMENTS` (default 3,000) or raise the CPU.
- [ ] After each deploy, run the 3 grader videos once so they are cached.
- [ ] Use a new YouTube API key for the deployment, restricted to the YouTube Data API (the prototype key was shared in chat).
- [ ] Keep the service running until grades are released.

### ML (sentiment and scoring)

- [ ] **Known sentiment errors** (`cardiffnlp/twitter-roberta-base-sentiment-latest`): misreads sarcasm, labels Chinese and other non-English comments neutral, labels promotional comments neutral. Try `cardiffnlp/twitter-xlm-roberta-base-sentiment` (multilingual) via `SENTIMENT_MODEL`; the seam is `classify` in `radar_mcp/sentiment.py`. Keep it fast: sentiment is the slowest step.
- [ ] **Offline eval** (`evals/`): a hand-labelled set (e.g. 200 comments from the cached videos) to measure sentiment accuracy and the Labeler's stance accuracy, plus the synthetic threads in `tests/synthetic.py` for group detection. This is what fills the README's "Offline eval" row.
- [ ] Optional: replace the hand weights in `signals.py:score_group` with a trained model. Keep its contract (features in, score and signal contributions out).
- [ ] Known limit to report: steering by old or bought accounts isn't caught (only new vs established is compared), and a ring spread thinly through a very busy thread isn't caught by account age alone.

### MCP server

- [ ] **Cross-video lookup:** the same scam script ("Adriana Mcgrath") and 3 of the same accounts appeared under two different channels' videos. A tool that finds a masked account or a phrase across cached threads would show campaigns, not just one section.
- [ ] More platforms: Bluesky first (a fetcher like `youtube.py` returning `{"video", "comments", "accounts"}`, plus a branch in `resolve`). Meta has no usable API.
- [ ] Show it working outside our app: connect `uv run python -m radar_mcp.server` to Claude Desktop or the MCP Inspector, and add a screenshot or short note to the README. Good for the "Using your own MCP server" concept.
- [ ] Keep the rules in `CLAUDE.md`: anticipated failures raise `ToolError`, nothing printed to stdout, names never leave the server.

## 4. Costs to watch

- Gemini: about 100k to 160k tokens per new video (watching the video is about 58k, labelling stances about 45k). A follow-up question is about 12k. Re-opening an analyzed video is free.
- YouTube: 10,000 quota units a day; a 3,000-comment video costs about 100.
- `WATCH_SECONDS=300` in `.env` halves the video cost if credits run low.

Where things are: [README.md](README.md) (for graders), [CLAUDE.md](CLAUDE.md) (architecture and code seams), [GLOSSARY.md](GLOSSARY.md) (terms).
