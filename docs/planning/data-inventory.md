# 資料清單 Data Inventory

> 2026-11-24 版。列出專案需要的每一份資料：它是什麼、拿來做什麼、怎麼取得。
> 申請 key 的詳細步驟和 key 的存放方式，見本檔最後的「附錄：key 的申請」。出處見 [political-data-feasibility.md](political-data-feasibility.md)。

**優先順序：** 🔴 必要　🟡 建議　⚪ 選配

---

## 0. 總表

| # | 資料 | 類型 | 用途 | 優先 | 要申請嗎 |
|---|---|---|---|:---:|---|
| D1 | YouTube 政治影片留言 | 即時 API | 產品 demo 的主要輸入 | 🔴 | YouTube API key |
| D2 | Bluesky 政治貼文回覆 | 即時 API | 產品 demo 的第二個輸入；追蹤關係 | 🔴 | 不用（翻頁搜尋才要帳號） |
| D3 | FCC 17-108 意見留言 | API | 協同偵測的標準答案 | 🔴 | api.data.gov key |
| D4 | 自建標註集（300 則） | 我們自己做 | **主要 eval**：三個欄位的準確度 | 🔴 | 不用 |
| D5 | VAST | 標註資料集 | 立場：評估；要微調時的訓練資料 | 🔴 | 不用 |
| D6 | CheckThat! 2025 Task 1 | 標註資料集 | 主觀性：評估 | 🔴 | 不用 |
| D7 | BABE | 標註資料集 | 偏頗用字：評估 | 🟡 | 不用 |
| D8 | TweetEval stance | 標註資料集 | 立場：第二個評估集 | 🟡 | 不用 |
| D9 | PTC（SemEval-2020 Task 11） | 標註資料集 | 偏頗用字：補充評估 | ⚪ | 不用 |
| D10 | P-Stance | 標註資料集 | 立場：額外訓練資料 | ⚪ | 不用 |
| D11 | Civil Comments | 標註資料集 | 煽動 / 侮辱的輔助訊號 | ⚪ | 不用 |
| D12 | Regulations.gov 意見留言 | API | FCC 的備案 | ⚪ | 和 D3 共用 key |
| D13 | Polis vTaiwan | 公開檔案 | 簡報的台灣故事素材 | ⚪ | 不用 |
| M1 | 4 個 Hugging Face 模型 | 模型權重 | 逐則分類 | 🔴 | 不用 |
| M2 | LLM API | API | 重判低信心和反諷的留言；agents | 🔴 | OpenAI key（或課堂提供的 key） |

**授權提醒：** 所有資料只用在課堂專題，README 要註明出處。標 NC 的不能商用。

---

## 1. 產品用的即時資料

### D1 · YouTube 政治影片留言　🔴

| | |
|---|---|
| **是什麼** | YouTube「News & Politics」類影片底下的留言和回覆，以及留言者頻道的建立日期、訂閱數、影片數 |
| **用來做什麼** | 評分者貼網址後，agent 即時抓的資料。逐則分類 + 協同偵測都用它 |
| **格式** | JSON（API 回應） |
| **額度** | 每天 10,000 單位；一支 1,000 則留言的影片約 50 單位 |
| **限制** | API 資料 30 天內要更新或刪除；不能做頻道層級的分數 |

**怎麼取得：**

1. 申請 YouTube API key（見附錄 A）。
2. 事先挑 3–5 支 demo 影片，記下 `videoId`。
3. 抓留言和帳號資料：

```bash
# 找候選影片（美國熱門的新聞與政治類）
curl "https://www.googleapis.com/youtube/v3/videos?part=snippet,statistics&chart=mostPopular&videoCategoryId=25&regionCode=US&maxResults=50&key=$YT_KEY"

# 留言（每頁 100 則，用 nextPageToken 翻頁）
curl "https://www.googleapis.com/youtube/v3/commentThreads?part=snippet,replies&videoId=$VIDEO_ID&maxResults=100&order=time&key=$YT_KEY"

# 留言者頻道（一次 50 個 ID）
curl "https://www.googleapis.com/youtube/v3/channels?part=snippet,statistics&id=$ID1,$ID2&key=$YT_KEY"
```

### D2 · Bluesky 政治貼文回覆　🔴

| | |
|---|---|
| **是什麼** | 政治人物、記者貼文底下的回覆串；回覆者的個人資料；帳號之間的追蹤關係 |
| **用來做什麼** | demo 的第二個平台。追蹤關係可以找出「互相追蹤的封閉小圈圈」，這是 YouTube 沒有的訊號 |
| **格式** | JSON（API 回應） |
| **限制** | 不登入搜尋只能拿第一頁；從 Cloud Run 呼叫會不會被擋要測（T16） |

**怎麼取得：**

1. 讀取不用 key。只有要翻頁搜尋時，才需要申請帳號和 App Password（見附錄 B）。
2. 貼文網址 `bsky.app/profile/{handle}/post/{rkey}` 要先把 handle 換成 DID：

```bash
curl "https://public.api.bsky.app/xrpc/com.atproto.identity.resolveHandle?handle=$HANDLE"

# 整串回覆
curl "https://public.api.bsky.app/xrpc/app.bsky.feed.getPostThread?uri=at://$DID/app.bsky.feed.post/$RKEY&depth=6"

# 回覆者資料（一次最多 25 個）
curl "https://public.api.bsky.app/xrpc/app.bsky.actor.getProfiles?actors=$H1&actors=$H2"

# 追蹤清單
curl "https://public.api.bsky.app/xrpc/app.bsky.graph.getFollows?actor=$HANDLE&limit=100"

# 找政治貼文（未登入只有第一頁）
curl "https://api.bsky.app/xrpc/app.bsky.feed.searchPosts?q=congress&sort=top&lang=en&limit=25"
```

### D3 · FCC 17-108 意見留言　🔴

| | |
|---|---|
| **是什麼** | 2017 年美國 FCC 網路中立性公開意見徵集的留言。約 2,170 萬則，Pew 統計約 94% 是重複送出的 |
| **用來做什麼** | **協同偵測的標準答案**：同一個模板、短時間大量送出的留言就是已知的協同群組。也是評分者任務 3 的素材 |
| **格式** | JSON：留言全文、送出時間（毫秒）、署名 |
| **額度** | 每把 key 每小時 1,000 次，每次最多 1,000 則 |
| **限制** | 署名可能是被冒用的真人姓名：**只存雜湊值，不顯示** |

**怎麼取得：**

1. 申請 api.data.gov key（見附錄 C）。
2. 抓 3 個已知模板，各 1,000 則（T17）：

```bash
curl "https://publicapi.fcc.gov/ecfs/filings?api_key=$DATA_GOV_KEY&proceedings.name=17-108&q=%22unprecedented%20regulatory%20power%22&limit=1000&sort=date_received,ASC"
```

3. 再隨機抽 2,000 則當對照組：不帶 `q`，用 `offset` 跳著抓。

---

## 2. 評估和訓練用的資料

### D4 · 自建標註集（300 則）　🔴

| | |
|---|---|
| **是什麼** | 我們自己標的政治留言：YouTube 100 則、Bluesky 100 則、FCC 100 則（含模板留言和獨特留言） |
| **用來做什麼** | **最重要的 eval。** 前 100 則調門檻和 LLM 評分規則，後 200 則只用來算最終分數，**絕不拿來訓練** |
| **格式** | CSV |
| **限制** | YouTube 留言全文受 30 天規定限制，見下方 |

**怎麼做：**

1. 從 D1、D2、D3 抓留言，每串先寫下 `target`，例如 “the federal minimum-wage increase”。
2. 先兩人一起試標 30 則，討論分歧，寫好標註指引。
3. 兩人各自標完 300 則，算 Cohen’s kappa。目標：`subj`、`stance` ≥ 0.6，`loaded` ≥ 0.5。
4. 分歧由第三人決定。

**欄位：**

```text
id, platform, source_id, target, text, subj, stance, loaded, loaded_spans, sarcasm, annotator
```

**YouTube 的 30 天規定：** 標註檔只存留言 ID 和我們的標籤，跑 eval 時再用 ID 重抓全文。被刪掉的留言就從 eval 裡移除，並記下數量。

### D5 · VAST　🔴

| | |
|---|---|
| **是什麼** | 哥大 Allaway & McKeown 的立場資料集（EMNLP 2020）。內容是紐約時報「Room for Debate」的讀者留言，每則標了對某個議題的 pro / con / neutral |
| **量** | train 13,477 / dev 2,062 / test 3,006；test 有 431 則標了反諷 |
| **用來做什麼** | 1. 立場的評估（test）<br>2. 量化反諷造成的準確率落差（`Sarc=1` 子集）<br>3. 如果 NLI 立場模型太慢，用 train 微調一個較快的立場分類器 |
| **授權** | repo 沒有標授權 ❔，微調前要確認 |
| **注意** | `label` 欄位是 0/1/2，對應哪個類別要看程式碼確認 |

**怎麼取得：** 不用申請，直接下載。

```bash
mkdir -p data/vast && cd data/vast
for s in train dev test; do
  curl -LO "https://raw.githubusercontent.com/emilyallaway/zero-shot-stance/master/data/VAST/vast_$s.csv"
done
```

Repo：[github.com/emilyallaway/zero-shot-stance](https://github.com/emilyallaway/zero-shot-stance)。`vast_test.csv` 已經確認存在；`train`、`dev` 的檔名是照同樣規則推的，抓不到就到 repo 的 `data/VAST/` 資料夾看實際檔名。

### D6 · CheckThat! 2025 Task 1（英文）　🔴

| | |
|---|---|
| **是什麼** | CLEF CheckThat! Lab 的主觀性資料集。新聞句子，標 SUBJ（意見）或 OBJ（事實） |
| **量** | train 830 / dev 462 / dev_test 484 / test 300 |
| **用來做什麼** | 主觀性模型的評估。目標 macro F1 ≥ 0.70 |
| **授權** | CC BY-NC-SA 4.0 |
| **注意** | 主觀性模型是用 2023 年版訓練的，要確認 2025 test 沒有重疊，不然分數會灌水 |

**怎麼取得：** 不用申請。

```bash
curl -L -o data/checkthat/test_en_labeled.tsv --create-dirs \
  "https://gitlab.com/checkthat_lab/clef2025-checkthat-lab/-/raw/main/task1/data/english/test_en_labeled.tsv"
```

train 和 dev 在同一個資料夾：[GitLab task1/data/english](https://gitlab.com/checkthat_lab/clef2025-checkthat-lab/-/tree/main/task1)。讀檔時用 `pd.read_csv(..., sep="\t", quoting=csv.QUOTE_NONE)`。

### D7 · BABE　🟡

| | |
|---|---|
| **是什麼** | Media Bias Group 的偏頗用字資料集。新聞句子，由專家標註是否偏頗，並標出偏頗的字詞 |
| **量** | HF 版 train 3,121 / test 1,000 |
| **用來做什麼** | 偏頗用字模型的評估 |
| **授權** | GitHub repo 是 AGPL-3.0；HF 卡片沒標 |
| **注意** | 偏頗用字模型 `roberta-babe-ft` 就是用 BABE 訓練的，分數會偏高，只能當參考 |

**怎麼取得：** 不用申請。

```python
from datasets import load_dataset
babe = load_dataset("mediabiasgroup/BABE")
```

### D8 · TweetEval stance　🟡

| | |
|---|---|
| **是什麼** | SemEval-2016 Task 6 的立場資料，推文。5 個議題：abortion、atheism、climate、feminist、hillary |
| **量** | 每個議題約 900 則（例如 hillary 620 / 69 / 295） |
| **用來做什麼** | 立場的第二個評估集，主要用政治相關的 `stance_hillary` 和 `stance_abortion` |

**怎麼取得：** 不用申請。

```python
from datasets import load_dataset
hillary  = load_dataset("cardiffnlp/tweet_eval", "stance_hillary")
abortion = load_dataset("cardiffnlp/tweet_eval", "stance_abortion")
```

### D9 · PTC（SemEval-2020 Task 11）　⚪

| | |
|---|---|
| **是什麼** | 宣傳手法資料集。新聞文章，標出 `Loaded_Language`（1,149 個）、`Name_Calling,Labeling`（590 個）等字詞位置 |
| **用來做什麼** | 偏頗用字的補充評估；也可以當 LLM 評分規則裡的正例 |
| **授權** | CC BY 4.0 |

```bash
curl -L "https://zenodo.org/records/3952415/files/datasets-v2.tgz?download=1" -o data/ptc.tgz
```

### D10 · P-Stance　⚪

| | |
|---|---|
| **是什麼** | 21,574 則關於 Trump、Biden、Sanders 的推文，標支持或反對 |
| **用來做什麼** | 只有要微調立場模型、VAST 又不夠時才用 |
| **授權** | repo 是 MIT |

**怎麼取得：** 到 [github.com/chuchun8/PStance](https://github.com/chuchun8/PStance)，從 README 的 Google Drive 連結下載。

### D11 · Civil Comments　⚪

| | |
|---|---|
| **是什麼** | 新聞網站的真實留言，約 180 萬則，標了毒性、侮辱、身分攻擊 |
| **用來做什麼** | 「煽動」的輔助訊號。注意：罵人和偏頗用字是兩回事，不能取代 `loaded` |
| **授權** | CC0 |

```python
from datasets import load_dataset
civil = load_dataset("google/civil_comments", split="test")
```

---

## 3. 備案和加分素材

### D12 · Regulations.gov　⚪

| | |
|---|---|
| **是什麼** | 美國聯邦法規的公開意見留言 |
| **用來做什麼** | FCC 的備案 |
| **限制** | 列表沒有全文，要一則一則抓；每小時 1,000 次；很多時間只到日期 |

```bash
curl -H "X-Api-Key: $DATA_GOV_KEY" "https://api.regulations.gov/v4/comments?filter%5BdocketId%5D=$DOCKET_ID&page%5Bsize%5D=250"
curl -H "X-Api-Key: $DATA_GOV_KEY" "https://api.regulations.gov/v4/comments/$COMMENT_ID"
```

### D13 · Polis vTaiwan　⚪

| | |
|---|---|
| **是什麼** | vTaiwan 的 UberX 公共討論：197 則繁體中文留言、105 位留言者 |
| **用來做什麼** | 簡報開場的台灣故事素材；不放進主線 |
| **授權** | CC BY 4.0 |

```bash
curl -L -o data/polis/vtaiwan_uberx_comments.csv --create-dirs \
  "https://raw.githubusercontent.com/compdemocracy/openData/master/vtaiwan.uberx/comments.csv"
```

---

## 4. 模型和 LLM

### M1 · Hugging Face 模型　🔴

| 任務 | 模型 | 大小 | 授權 |
|---|---|---|---|
| 主觀性 | `GroNLP/mdebertav3-subjectivity-english` | 1.1 GB | 沒標 ❔ |
| 偏頗用字 | `mediabiasgroup/roberta-babe-ft` | 499 MB | CC BY-NC 4.0 |
| 立場 | `MoritzLaurer/deberta-v3-base-zeroshot-v2.0` | 369 MB | MIT |
| 反諷 | `cardiffnlp/twitter-roberta-base-irony` | 499 MB | 沒標 ❔ |

**怎麼取得：** 不用申請。在 Dockerfile 裡建 image 時就下載，不要等容器啟動才抓：

```dockerfile
RUN python -c "from transformers import pipeline; \
  [pipeline('text-classification', model=m) for m in [ \
  'GroNLP/mdebertav3-subjectivity-english', \
  'mediabiasgroup/roberta-babe-ft', \
  'cardiffnlp/twitter-roberta-base-irony']]; \
  pipeline('zero-shot-classification', model='MoritzLaurer/deberta-v3-base-zeroshot-v2.0')"
```

從 Cloud Build 下載被限速的話，加上 `HF_TOKEN`（見附錄 D）。

### M2 · LLM API　🔴

| | |
|---|---|
| **用來做什麼** | 重判低信心和疑似反諷的留言（約 20%）；調查員和辯護律師 agent |
| **費用** | 重判每 1,000 則約 0.02 美元（`gpt-5-nano`） |

**怎麼取得：** 見附錄 E。課堂有提供 key 就用課堂的。

---

## 5. 建議的 repo 資料夾

```text
data/
  raw/            # API 抓下來的原始 JSON（.gitignore，不進 repo）
  gold/           # D4 自建標註集：只存 ID 和標籤，可以進 repo
  vast/           # D5
  checkthat/      # D6
  ptc/            # D9
  polis/          # D13
scripts/
  download_datasets.sh   # 把上面所有下載指令集中在這裡
```

`.gitignore` 至少要有：`.env`、`data/raw/`、大型資料集檔案。

---

## 附錄：key 的申請

### A. YouTube API key

1. [console.cloud.google.com](https://console.cloud.google.com/) → 上方專案選單 → **New Project** → 名稱 `comment-radar` → **Create**。學校帳號建不了就改用個人 Gmail。
2. **APIs & Services → Library** → 搜尋 `YouTube Data API v3` → **Enable**。
3. **APIs & Services → Credentials → + Create credentials → API key** → 複製。
4. 編輯這個 key：**API restrictions → Restrict key** → 只勾 YouTube Data API v3；**Application restrictions → None** → **Save**。
5. 測試：`curl "https://www.googleapis.com/youtube/v3/videoCategories?part=snippet&regionCode=US&key=$YT_KEY"`，要看到 `"id": "25"`、`"title": "News & Politics"`。

額度以專案計算，每個組員可以各建一個專案。

### B. Bluesky 帳號 + App Password

1. [bsky.app](https://bsky.app) → **Sign up**，開專案專用帳號。要求驗證 email 就先去信箱驗證。
2. **Settings → Privacy and security → App passwords → Add App Password** → 名稱 `comment-radar` → 不勾 direct messages → **Create** → 複製（只顯示一次）。
3. 測試：

```bash
curl -X POST https://bsky.social/xrpc/com.atproto.server.createSession \
  -H "Content-Type: application/json" \
  -d "{\"identifier\":\"$BSKY_HANDLE\",\"password\":\"$BSKY_APP_PASSWORD\"}"
```

回應有 `accessJwt` 就成功。程式裡登入一次後重複使用 session，不要每次都重新登入。

### C. api.data.gov key（FCC、Regulations.gov 共用）

1. [api.data.gov/signup](https://api.data.gov/signup/) → 填姓名、email，勾同意條款 → **Sign up**。key 會顯示在畫面上，也會寄到信箱。
2. 測試：`curl -s -D - -o /dev/null "https://publicapi.fcc.gov/ecfs/filings?api_key=$DATA_GOV_KEY&proceedings.name=17-108&limit=5"`，要看到 `200` 和 `x-ratelimit-limit: 1000`。

每把 key 每小時 1,000 次，每個組員各申請一把。

### D. Hugging Face token（選配）

[huggingface.co/settings/tokens](https://huggingface.co/settings/tokens) → **Create new token** → 類型 **Read** → 複製，存成 `HF_TOKEN`。

### E. OpenAI key

[platform.openai.com](https://platform.openai.com) → **Settings → Billing** 先儲值 → **API keys → Create new secret key** → 複製（只顯示一次）。

### key 放哪裡

- **本機：** repo 根目錄的 `.env`，並加進 `.gitignore`。**絕對不要 commit。**

```bash
YT_KEY=
BSKY_HANDLE=
BSKY_APP_PASSWORD=
DATA_GOV_KEY=
OPENAI_API_KEY=
HF_TOKEN=
```

- **Cloud Run：** 用 Secret Manager。

```bash
printf "%s" "$YT_KEY" | gcloud secrets create yt-key --data-file=-
gcloud run services update comment-radar --update-secrets=YT_KEY=yt-key:latest
```

其他 key 照同樣方式建立。
