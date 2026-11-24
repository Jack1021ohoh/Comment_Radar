# 留言雷達：政治留言區的「中立 / 主觀偏頗」資料可行性研究

> 查證日期：2026-11-23。標「需實測」的項目要等 T16 之後的測試跑完才算確定。
>
> 這份文件**取代** `sentiment-data-feasibility.md` 的資料來源選擇。那份推薦的 Hacker News 和 Steam 不是政治內容，這裡不再使用。那份的 YouTube 政策風險（0.1 節）、Perspective API 停止服務（0.2 節）、排除清單（1.6 節）、LLM 價格（3.2 節）仍然有效，這裡只引用、不重寫。
>
> ⚠️ 這份文件只是參考。DESIGN.md 必須自己手寫，請不要把句子貼過去。

**結論摘要：** 資料來源建議只用三個。**FCC ECFS** 的 17-108 號案（2017 年網路中立性意見徵集）放主力，原因是它同時有政治內容、留言全文、毫秒級時間戳，也有公開的協同證據：Pew 統計約 94% 的留言是重複送出的，紐約州檢察長也查出約 1,800 萬則假留言。**YouTube「News & Politics」影片**和 **Bluesky 政治貼文串**放產品 demo，評分者可以自己貼網址驗證。**Regulations.gov** 列為備選，因為留言全文要一則一則抓，每小時又只有 1,000 次。標註資料用 **CheckThat! 2025 主觀性**（新聞句子，SUBJ/OBJ）、**VAST**（NYT 讀者留言的立場，測試集有 431 則標了反諷）、**BABE**（新聞句子的偏頗用字）和 **PTC**（宣傳手法，含 Loaded Language）。另外自己標 300 則政治留言，這才是主要的 eval。模型方面，主觀性用 `GroNLP/mdebertav3-subjectivity-english`，偏頗用字用 `mediabiasgroup/roberta-babe-ft`，立場用 NLI zero-shot（`MoritzLaurer/deberta-v3-base-zeroshot-v2.0`）。三個都在 Cloud Run CPU 上跑。低信心和疑似反諷的留言再交給 LLM，依評分規則重判。**標註方式**是每則留言標三個欄位：`subj`（SUBJ/OBJ）、`stance`（對指定目標 FAVOR/AGAINST/NONE）、`loaded`（0/1）。「中立」定義為 OBJ 而且 `loaded=0`；「過度主觀偏頗」定義為 SUBJ 而且 `loaded=1`。

**這次查到的四件意外：**

1. **YouTube `search.list` 的計費方式改了**：從 2026-06-01 起有獨立的額度桶，「100 calls per day」，每次算 1 單位。很多教學還寫每次 100 單位，已經過時。[search.list](https://developers.google.com/youtube/v3/docs/search/list)、[Revision history](https://developers.google.com/youtube/v3/revision_history) ✅
2. **FCC 的假留言今天還查得到**：實測從 17-108 號案搜尋 “unprecedented regulatory power”，一次就拿到 1,000 則**內容完全相同**的留言，全部在 2017-05-08 13:00:03 到 13:00:21 的 18 秒內送出。API 回報同一句話總共有 818,978 筆符合。✅ 實測
3. **Bluesky 搜尋未登入只能拿第一頁**：`api.bsky.app` 的 `searchPosts` 第一頁回 200，但帶 `cursor` 翻頁就回 403；`public.api.bsky.app` 則是直接回 403。✅ 今天實測（住家 IP）
4. **Regulations.gov 列表不含留言全文**：要對每則留言各呼叫一次明細端點，再加上每小時 1,000 次的上限，5 分鐘內抓不完一個大案子，只能事先快取。

---

## 目錄

0. [任務定義](#0-任務定義)
1. [政治留言資料來源](#1-政治留言資料來源)
2. [標註資料集](#2-標註資料集)
3. [模型與成本](#3-模型與成本)
4. [可行性測試](#4-可行性測試)
5. [查證來源](#5-查證來源)

狀態標記沿用前兩份文件：

| 標記 | 意思 |
|---|---|
| ✅ 已查證 | 官方文件確認，或今天實際呼叫成功 |
| 🧪 需實測 | 文件說可以，但沒從 Cloud Run 測過，或數字是我們估的 |
| 📨 需申請 | 要寄信或填表，等對方回覆 |
| ❔ 未證實 | 只有第三方的說法，或官方頁面沒寫 |

---

## 0. 任務定義

### 0.1 三個任務

| 任務 | 問的問題 | 輸出 | 參考定義 |
|---|---|---|---|
| (a) 主觀性 | 這則留言是在陳述事實，還是在表達意見？ | `SUBJ` / `OBJ` | CheckThat! 的定義：句子內容「based on or influenced by personal feelings, tastes, or opinions」就算主觀。[GroNLP 模型卡引用 Antici et al. 2023](https://huggingface.co/GroNLP/mdebertav3-subjectivity-english) |
| (b) 立場 | 對指定目標（例如某法案、某政治人物）是支持、反對，還是都沒有？ | `FAVOR` / `AGAINST` / `NONE` | SemEval-2016 Task 6（TweetEval 的 stance 子集用的是 `none`、`against`、`favor`）。[TweetEval](https://github.com/cardiffnlp/tweeteval) |
| (c) 偏頗用字 | 有沒有用帶情緒、貼標籤或誇大的字眼？ | `loaded` 0/1，可以選擇附上字詞範圍 | BABE 的 lexical bias（[論文](https://arxiv.org/abs/2209.14557)）；PTC 的 `Loaded_Language`、`Name_Calling,Labeling`、`Exaggeration,Minimisation`（[Zenodo](https://zenodo.org/records/3952415)） |

**黨派傾向（左 / 中 / 右）不放進主線。** 現有模型都是用整篇新聞訓練的，例如 `bucketresearch/politicalBiasBERT` 的模型卡寫「Paper and repository coming soon」，參考的是 Baly et al. 2020 的新聞文章資料。拿來判斷短留言的可信度低，而且很容易被看成在「點名誰是哪一黨」。[模型卡](https://huggingface.co/bucketresearch/politicalBiasBERT) ✅

### 0.2 標註方式（每則留言）

| 欄位 | 值 | 規則 |
|---|---|---|
| `target` | 文字 | 每串留言只設一個目標，由標註者事先決定，例如 “FCC repeal of net neutrality”。這樣立場才有比較基準 |
| `subj` | `SUBJ` / `OBJ` | 留言的主要主張是意見，就標 SUBJ。只引用事實、提問或轉述，就標 OBJ |
| `stance` | `FAVOR` / `AGAINST` / `NONE` | 只看對 `target` 的立場。罵對方陣營但沒提到目標的留言，標 NONE |
| `loaded` | 0 / 1 | 有貼標籤、侮辱、誇大或煽動恐懼的字眼就標 1，並把那幾個字複製到 `loaded_spans` |
| `sarcasm` | 0 / 1 | 只拿來做錯誤分析，不放進模型輸出 |

**由欄位推出的兩個結論：**

- `neutral` = `subj=OBJ` 而且 `loaded=0`。
- `overly_biased` = `subj=SUBJ` 而且 `loaded=1`。
- 有立場但用字克制的留言（SUBJ、`loaded=0`）**不算偏頗**。這是正常的意見表達，報告裡要分開呈現。

### 0.3 跟協同偵測怎麼結合

做法沿用前一份文件 T14 的想法，但比較的對象從情緒換成這三個欄位：把「可疑協同群組」和「一般留言者」的 `stance` 分布、`overly_biased` 比例並排列出，再用卡方檢定比較。FCC 的案例很適合：同一個模板的 1,000 則留言，立場會 100% 一致。

---

## 1. 政治留言資料來源

### 1.1 排名

| 排名 | 來源 | 政治 | 英文 | 免費 | 留言全文 / 作者 / 時間 | Cloud Run | 協同的標準答案 | 狀態 |
|:---:|---|:---:|:---:|:---:|---|:---:|---|:---:|
| 1 | **FCC ECFS**（17-108 號案） | ✅ | ✅ | ✅ 要 key | ✅ 列表直接附全文 / 署名（可能是被冒用的名字）/ 毫秒 | 🧪 | ✅ Pew 和紐約州檢察長的報告 | ✅ 實測 |
| 2 | **YouTube News & Politics** | ✅ | ✅ | ✅ | ✅ / ✅ / ✅ | ✅ 用 key | ❌ | ✅ |
| 3 | **Bluesky 政治貼文串** | ✅ | ✅ | ✅ | ✅ / ✅ / ✅，另外有追蹤關係 | 🧪 | ❌ | ✅ 實測 |
| 4 | Regulations.gov | ✅ | ✅ | ✅ 要 key | 全文要一則一則抓 / 常被隱藏 / 看到的那筆只到日期 | 🧪 | 部分：機關會標示 mass mail campaign | ✅ 實測 |
| 5 | Polis openData | ✅ | 部分 | ✅ CC BY 4.0 | ✅ / 匿名 ID / ✅ | ✅ 靜態檔 | ❌ | ✅ 實測 |
| 6 | Mastodon 主題標籤 | ✅ | ✅ | ✅ | ✅ / ✅ / ✅ | 🧪 | ❌ | ✅ |

**為什麼 FCC 排第一：** 我們找到的來源裡，只有它同時有政治內容、留言全文，又有權威機構公開認定的大規模協同造假。這可以當作評分模型的正例，也是 demo 的第一個任務。缺點是它不是「留言區」，而是政府的意見徵集，而且是 2017 年的舊資料。

### 1.2 FCC ECFS　✅ 已查證（API 實測）

**拿到什麼：**

- `GET https://publicapi.fcc.gov/ecfs/filings` 的列表回應直接附 `text_data`（留言全文）、`filers[].name`、`date_received`（精確到毫秒）和 `express_comment`。✅ 今天實測
- `limit=1000` 可以一次拿 1,000 筆。✅ 今天實測
- 回應裡的 `aggregations` 會給符合條件的總數，例如 `proceedings_name` 的 `doc_count`。

**協同的標準答案：**

| 來源 | 內容 | 狀態 |
|---|---|---|
| [Pew Research 2017](https://www.pewresearch.org/internet/2017/11/29/public-comments-to-the-federal-communications-commission-about-net-neutrality-contain-many-inaccuracies-and-duplicates/) | 分析 2,170 萬則留言：約 94% 被重複送出，只有 6% 是獨一無二的。有 9 次在同一秒湧入超過 75,000 則，最大的一批是 7/19 的 475,482 則。57% 用了重複或臨時的 email。前 7 名的留言佔 38%，其中 6 則反對網路中立 | ✅ |
| [紐約州檢察長 2021](https://ag.ny.gov/press-release/2021/attorney-general-james-issues-report-detailing-millions-fake-comments-revealing)（[報告 PDF](https://ag.ny.gov/sites/default/files/reports/oag-fakecommentsreport.pdf)） | 2,200 多萬則留言裡近 1,800 萬則是假的。寬頻業者資助的活動產生約 850 萬則，一名 19 歲學生用程式送出約 770 萬則支持網路中立的假留言 | ❔ 今天 `ag.ny.gov` 的 DNS 查詢失敗，原文沒讀到，數字只來自搜尋摘要 |

**怎麼取得：**

1. 到 [api.data.gov/signup](https://api.data.gov/signup/) 申請 key。FCC 舊版開發者頁寫「register for a free API key from https://api.data.gov」（[UNT 封存](https://webarchive.library.unt.edu/web/20201218044726/https://www.fcc.gov/reports-research/developers)）。現行頁面改指向 `fcc.gov/ecfs/help/public_api`，但 fcc.gov 對我們的抓取工具回 403，所以沒讀到。❔
2. 先用 `DEMO_KEY` 試。今天回應標頭是 `x-ratelimit-limit: 10`，比 api.data.gov 文件寫的「30 requests per IP address per hour」還低。[api.data.gov 手冊](https://api.data.gov/docs/developer-manual/)
3. 一般 key 的預設上限是「1,000 requests per hour」（同上）。
4. 用 `proceedings.name` 指定案號，用 `q` 搜全文。

```bash
curl "https://publicapi.fcc.gov/ecfs/filings?api_key=$FCC_KEY&proceedings.name=17-108&q=%22unprecedented%20regulatory%20power%22&limit=1000&sort=date_received,ASC"
```

```python
import httpx

def ecfs(proceeding: str, q: str | None, key: str, limit: int = 1000, offset: int = 0):
    p = {"api_key": key, "proceedings.name": proceeding, "limit": limit,
         "offset": offset, "sort": "date_received,ASC"}
    if q:
        p["q"] = q
    r = httpx.get("https://publicapi.fcc.gov/ecfs/filings", params=p, timeout=60)
    r.raise_for_status()
    return [{"id": f["id_submission"], "ts": f["date_received"],
             "text": f.get("text_data") or "",
             "filer": (f.get("filers") or [{}])[0].get("name")} for f in r.json()["filing"]]
```

**注意：**

- **署名可能是被冒用的真人名字。** 紐約州檢察長的報告重點就是冒名。所以只存名字的雜湊值，畫面上不顯示名字。這也符合原提案「不點名個人」的原則。
- `offset` 的上限沒有查到，🧪。
- FCC 的 API 使用條款沒讀到，❔。

### 1.3 YouTube：找政治影片　✅ 已查證

政策限制沿用 `sentiment-data-feasibility.md` 0.1 節和 T15：只做**單則留言**的分類，標示「這是 Comment Radar 的分析」，**不給頻道打分**。立場標籤的風險比情緒更高，因為容易被解讀成「這個頻道的觀眾都反對某人」，所以 T15 的呈現規則也要涵蓋立場。

| 方法 | 額度 | 說明 |
|---|---|---|
| `videos.list?chart=mostPopular&videoCategoryId=25&regionCode=US` | 1 單位 | `videoCategoryId`「can only be used in conjunction with the chart parameter」。[文件](https://developers.google.com/youtube/v3/docs/videos/list) ✅。`25` 代表 News & Politics 是社群的共識，官方頁面沒寫，要用 `videoCategories.list` 確認 ❔ |
| 新聞頻道的 uploads 播放清單：`channels.list?part=contentDetails` → `playlistItems.list` | 各 1 單位 | 最省額度，也最好重現。適合事先挑好 5–10 個主流新聞頻道 |
| `search.list?type=video&videoCategoryId=25&q=…` | 1 單位，但每天只能呼叫 100 次 | 2026-06-01 起有獨立的額度桶。用 `videoCategoryId` 時「must also set the type parameter's value to video」。[文件](https://developers.google.com/youtube/v3/docs/search/list) ✅ |

各方法的額度見[額度表](https://developers.google.com/youtube/v3/determine_quota_cost)。

```bash
curl "https://www.googleapis.com/youtube/v3/videos?part=snippet,statistics&chart=mostPopular&videoCategoryId=25&regionCode=US&maxResults=50&key=$YT_KEY"
```

```bash
curl "https://www.googleapis.com/youtube/v3/channels?part=contentDetails&forHandle=@$NEWS_HANDLE&key=$YT_KEY"
```

```bash
curl "https://www.googleapis.com/youtube/v3/playlistItems?part=contentDetails&playlistId=$UPLOADS_ID&maxResults=50&key=$YT_KEY"
```

抓留言的方式和 T1 相同（`commentThreads.list`，每次 1 單位）。

### 1.4 Bluesky：找政治貼文　✅ 已查證（住家 IP）

| 做法 | 今天的結果 |
|---|---|
| `api.bsky.app/xrpc/app.bsky.feed.searchPosts?q=congress&sort=top&lang=en` | 第一頁 200，回 25 則和一個 `cursor`。✅ |
| 同上，帶 `cursor` 翻第二頁 | **403**。✅ 實測。這跟[回報](https://github.com/bluesky-social/bsky-docs/issues/332)的現象一致 |
| `public.api.bsky.app` 的 `searchPosts` | 403，跟原提案的紀錄相同 |
| 主題標籤 `q=%23politics` | 200 |
| `getPostThread` 抓一位美國眾議員貼文的回覆 | `public.api.bsky.app` 回 200，抓到 85 則，`replyCount` 是 83 |
| `getProfile` 的 `verification` 欄位 | 有。例如一位國會議員的帳號回 `verifiedStatus: "valid"`，簽發者是 `bsky.app` |

**適合政治題目的原因：** 搜尋 “congress” 的熱門結果裡就有國會議員本人和政治記者的貼文，回覆數可以到上百則，而且有追蹤關係可以用。

**怎麼取得：**

1. 先用 `searchPosts` 的第一頁（`sort=top`、`lang=en`）找候選貼文。也可以事先選好幾個有驗證標章的政治人物或記者帳號，用 `getAuthorFeed` 抓他們的貼文。
2. 用 `getPostThread` 抓回覆，用 `getProfiles` 抓帳號資料。這兩步和原提案的 T2、T3 相同。
3. 需要翻頁時，就用 App Password 登入走 PDS。這是原提案的備案。
4. 用列表和 starter pack 找政治帳號（`app.bsky.graph.getList`、`getStarterPack`）的做法沒有測過，🧪。

```bash
curl "https://api.bsky.app/xrpc/app.bsky.feed.searchPosts?q=congress&sort=top&lang=en&limit=25"
```

### 1.5 Regulations.gov　✅ 已查證（API 實測）

**拿到什麼：**

- `GET https://api.regulations.gov/v4/comments?filter[docketId]=…`：列表只有標題、日期和 ID，**沒有全文**。`meta.totalElements` 會給總數，例如 EPA-HQ-OAR-2021-0317 有 3,578 則。✅ 實測
- `GET /v4/comments/{id}`：回傳 `comment`（全文）、`receiveDate`、`duplicateComments`、`trackingNbr`。名字和所在地是否公開由各機關決定，email、電話「never public」。[GSA 文件](https://open.gsa.gov/api/regulationsgov/) ✅
- 我們看到的那一筆，`receiveDate` 是 `2023-02-13T05:00:00Z`，只到日期，所以時間爆發的訊號很弱。❔ 只看了一筆
- `duplicateComments` 欄位的定義在官方文件裡找不到，❔

**限制：**

- 大案子的翻頁方式：每次 `page[size]=250`，翻 20 頁共 5,000 則，再用 `filter[lastModifiedDate][ge]` 接下一批。官方註明這個參數「is in beta and may be removed」。[GSA 文件](https://open.gsa.gov/api/regulationsgov/)
- 每抓一則全文就是一次呼叫，一般 key 每小時 1,000 次，所以 **demo 要事先快取**。另一個選擇是網站上的 bulk download，會用 email 寄 CSV 連結。[GSA 部落格](https://www.gsa.gov/blog/2022/10/27/bulk-data-download-is-here-on-regulationsgov)。CSV 裡有沒有全文，文章沒寫，❔
- 很多留言的內文只寫「見附件」，實際內容在 PDF 裡。

**協同的線索：**

- EPA 對大量重複的留言，只公開「one representative sample comment along with the total comment count」。[EPA](https://www.epa.gov/dockets/commenting-epa-dockets) ✅。也就是說，重複的留言在 API 裡大多**看不到**，這點跟 FCC 不同。
- GAO 發現各機關的公開方式不一致，民眾可能「draw inaccurate conclusions about who commented」。[GAO-19-483](https://www.gao.gov/products/gao-19-483) ✅
- ACUS Recommendation 2021-1 是處理大量、電腦生成和冒名留言的官方建議，可以引用在 DESIGN.md 的背景段落。[ACUS](https://acus.gov/node/12335)

**怎麼取得：**

1. 到 [open.gsa.gov/api/regulationsgov](https://open.gsa.gov/api/regulationsgov/) 或 [api.data.gov/signup](https://api.data.gov/signup/) 申請 GET 用的 key。只讀資料不需要「commenting API」那種要驗證身分的 key。
2. key 放在 `X-Api-Key` 標頭。

```bash
curl -H "X-Api-Key: $REGS_KEY" "https://api.regulations.gov/v4/comments?filter%5BdocketId%5D=$DOCKET_ID&page%5Bsize%5D=250&sort=lastModifiedDate,documentId"
```

```bash
curl -H "X-Api-Key: $REGS_KEY" "https://api.regulations.gov/v4/comments/$COMMENT_ID"
```

### 1.6 Polis openData（台灣加分項）　✅ 已查證

- GitHub `compdemocracy/openData`，README 寫「All Polis data is licensed CC By 4.0」，要依指定格式標示出處。[repo](https://github.com/compdemocracy/openData) ✅
- `vtaiwan.uberx`：vTaiwan 的 UberX 討論。197 則**繁體中文**留言、105 位留言者、1,921 位投票者。`comments.csv` 的欄位有 `timestamp`、`author-id`、`agrees`、`disagrees`、`moderated`、`comment-body`。✅ 今天下載確認
- 英文的對話：`american-assembly.bowling-green` 有 896 則留言、403 位留言者；`canadian-electoral-reform` 有 174 則。
- **用途**：當作創辦人故事的素材，也可以當繁中的小型測試集。資料量太小，而且沒有協同標註，不適合主線。

```bash
curl -LO "https://raw.githubusercontent.com/compdemocracy/openData/master/vtaiwan.uberx/comments.csv"
```

### 1.7 Mastodon（簡述）

- `GET /api/v1/timelines/tag/politics` 在 mastodon.social 和 journa.host 未登入都回 200。✅ 今天實測
- 未登入時，`context` 最多只拿得到 60 則回覆，這是前一份文件 1.4 節的結論。每個站台的規則也不同，所以只當備選。

### 1.8 查過但沒放進來的

- **Reddit、X、Threads、TikTok、Facebook**：理由見前一份文件的 1.6 節，沒有新變化。
- **新聞網站留言**：Disqus 要知道網站的 shortname，作者欄位也沒有查證（見前一份文件 1.5 節）。
- **EU「Have your say」、英國政府諮詢、C-SPAN**：沒有找到官方的公開留言 API，❔，所以不推薦。

---

## 2. 標註資料集

### 2.1 總表

| 資料 | 任務 | 大小（實際查到的切分） | 領域 | 授權 | 怎麼下載 | 狀態 |
|---|---|---|---|---|---|---|
| **CheckThat! 2025 Task 1（英文）** | 主觀性 | train 830 / dev 462 / dev_test 484 / test 300（test 是 OBJ 215、SUBJ 85） | 新聞句子 | CC BY-NC-SA 4.0（資料夾附授權檔） | 官方 GitLab 的 TSV | ✅ 實際下載 |
| **VAST**（Allaway & McKeown，EMNLP 2020，哥大） | 立場 | train 13,477 / dev 2,062 / test 3,006；test 有 431 則 `Sarc=1` | 論文寫「comments collected from The New York Times ‘Room for Debate’ section」 | repo 沒有標授權 ❔ | GitHub 的 CSV | ✅ 實際下載 |
| **TweetEval stance**（SemEval-2016 Task 6） | 立場 | hillary 620/69/295；abortion 587/66/280；另有 atheism、climate、feminist | 推文 | HF 標 `unknown` | HF parquet | ✅ |
| P-Stance（ACL Findings 2021） | 立場 | 21,574 則推文，目標是 Trump、Biden、Bernie | 推文 | repo 是 MIT；資料放在 Google Drive | Drive 連結 | ✅ / 🧪 沒有下載 |
| **BABE** | 偏頗用字 | 論文寫 3,700 句；HF 版是 train 3,121 / test 1,000 ❔ 兩者對不上 | 新聞句子，有 `label_opinion` 和 `biased_words` | GitHub repo 是 AGPL-3.0；HF 卡片沒標 | HF parquet | ✅ |
| MBIC | 偏頗用字 | 1,700 句，群眾標註 | 新聞句子 | 包含在 BABE 的 repo 裡 | `final_labels_MBIC` | ✅ |
| **PTC**（SemEval-2020 Task 11） | 宣傳手法 | 371 篇訓練文章、75 篇 dev；訓練集有 6,129 個手法標註，其中 `Loaded_Language` 1,149 個、`Name_Calling,Labeling` 590 個 | 新聞文章（字詞範圍標註） | Zenodo 標 CC BY 4.0，公開 | Zenodo 1.1 MB | ✅ 實際下載 |
| SemEval-2023 Task 3 | 說服手法、框架 | — | 多語新聞 | ❔ | 要註冊並通過審核 | 📨 |
| Wiki Neutrality Corpus | 主觀偏頗（含改寫） | 論文寫 180,000 組句子對 | 維基百科的編輯紀錄 | 程式碼是 MIT，資料授權沒寫 ❔ | Dropbox 鏡像，109.6 MB | ✅ 連結可用 |
| SemEval-2019 Task 4 | 極端黨派 | — | 整篇新聞 | HF 標 CC BY 4.0 | HF 版本靠 loading script，`datasets` 4.0 會失敗 | ⚠️ |
| Civil Comments | 毒性、侮辱、身分攻擊 | 1,804,874 / 97,320 / 97,320 | **新聞網站留言** | CC0 | HF parquet | ✅ |

各資料的出處：CheckThat 的 [GitLab](https://gitlab.com/checkthat_lab/clef2025-checkthat-lab/-/tree/main/task1)、[總覽論文](https://ceur-ws.org/Vol-4038/paper_51.pdf)；VAST 的 [repo](https://github.com/emilyallaway/zero-shot-stance)、[論文](https://arxiv.org/abs/2010.03640)；[P-Stance](https://github.com/chuchun8/PStance)；BABE 的 [repo](https://github.com/Media-Bias-Group/Neural-Media-Bias-Detection-Using-Distant-Supervision-With-BABE)、[HF](https://huggingface.co/datasets/mediabiasgroup/BABE)；[PTC](https://zenodo.org/records/3952415)；[SemEval-2023 Task 3](https://propaganda.math.unipd.it/semeval2023task3/)；WNC 的 [repo](https://github.com/rpryzant/neutralizing-bias)、[論文](https://arxiv.org/abs/1911.09709)；[Civil Comments](https://huggingface.co/datasets/google/civil_comments)。

**領域落差：** 主觀性和偏頗用字的資料幾乎都是**新聞句子**，跟短的社群留言差很多。留言更口語，常常沒頭沒尾，反諷也多。這就是為什麼一定要自己標一份。VAST 是我們找到最接近「政治留言」的標註資料，因為它就是讀者留言。

### 2.2 下載方式

```python
import csv
import pandas as pd
from datasets import load_dataset

babe = load_dataset("mediabiasgroup/BABE")                      # parquet，datasets 4.0 可以載
hillary = load_dataset("cardiffnlp/tweet_eval", "stance_hillary")
civil = load_dataset("google/civil_comments", split="test")

ct = pd.read_csv("https://gitlab.com/checkthat_lab/clef2025-checkthat-lab/-/raw/main/task1/data/english/test_en_labeled.tsv",
                 sep="\t", quoting=csv.QUOTE_NONE)
vast = pd.read_csv("https://raw.githubusercontent.com/emilyallaway/zero-shot-stance/master/data/VAST/vast_test.csv")
```

```bash
curl -L "https://zenodo.org/records/3952415/files/datasets-v2.tgz?download=1" -o ptc.tgz
```

```bash
curl -L "https://www.dropbox.com/s/qol3rmn0rq0dfhn/bias_data.zip?dl=1" -o wnc.zip
```

VAST 的 `label` 是 0/1/2，論文寫的類別是 pro、con、neutral，但數字和類別怎麼對應要對照程式碼確認，🧪。

### 2.3 建議的 eval 組合

| 任務 | 公開基準 | 用途 |
|---|---|---|
| 主觀性 | CheckThat! 2025 英文 test（300 則） | 確認模型和流程沒寫錯 |
| 立場 | VAST test（3,006 則），另外單獨算 `Sarc=1` 的 431 則；TweetEval `stance_hillary` | VAST 最接近留言。反諷子集用來量化模型的弱點 |
| 偏頗用字 | BABE test（1,000 則）；PTC 的 `Loaded_Language` 句子 | 新聞領域的上限參考 |
| 協同 × 立場 | FCC 17-108 的模板群組 vs 隨機抽樣（見 T17） | 我們的核心賣點 |

**自建集（主要 eval）：** 300 則。

- YouTube 政治影片 100 則、Bluesky 100 則、FCC 和 Regulations.gov 100 則。FCC 那份要包含模板留言和獨特留言。
- 每串留言先寫下 `target`。

**標註一致度：**

1. 先試標 30 則，討論分歧後修改標註指引。
2. 兩人各自標全部 300 則。`subj`、`stance`、`loaded` 各算一次 Cohen’s kappa。
3. 目標是 `subj` 和 `stance` 的 kappa ≥ 0.6，`loaded` ≥ 0.5。偏頗本來就比較主觀，BABE 的論文也強調要用受過訓練的專家標註。
4. 分歧的部分由第三人決定，並把例子寫進指引。
5. 達不到目標的欄位，報告裡要標成「低一致度」，這本身就是 DESIGN.md 的好素材。

---

## 3. 模型與成本

### 3.1 選項（以 1,000 則短留言計）

| 任務 | 模型 | 授權和大小 | 已知表現 | Cloud Run CPU 速度 | 狀態 |
|---|---|---|---|---|---|
| 主觀性 | **`GroNLP/mdebertav3-subjectivity-english`** | 模型卡沒寫授權 ❔（基底 mDeBERTa-v3 是 MIT）；權重 1,113 MB | CheckThat! 2023 第三名，macro F1 0.77、SUBJ F1 0.79。訓練資料是新聞句子 | 估計 40–90 秒（4 vCPU、batch 32、max_length 128） | ✅ 規格 / 🧪 速度 |
| 偏頗用字 | **`mediabiasgroup/roberta-babe-ft`** | CC BY-NC 4.0（課堂用可以）；499 MB | 模型卡自己警告「may over-flag emotionally charged wording」；BABE 論文的最佳模型 macro F1 是 0.804 | 估計 20–60 秒 | ✅ / 🧪 |
| 偏頗用字（不建議） | `d4data/bias-detection-model` | 沒寫授權；只有 TF 權重 268 MB | 模型卡寫驗證準確率只有 62% | — | ✅ 排除 |
| 立場 | **`MoritzLaurer/deberta-v3-base-zeroshot-v2.0`**（NLI） | MIT；369 MB，另有 ONNX 版 | 沒有政治立場的官方數字。每則留言要配 3 個假設句，所以等於跑 3,000 次 | 估計 1.5–4 分鐘，**可能超過 5 分鐘的預算** | ✅ / 🧪 |
| 立場（較準、較慢） | `deberta-v3-large-zeroshot-v2.0` | MIT；870 MB | — | 在 CPU 上大概太慢 | ✅ / 🧪 |
| 反諷旗標 | `cardiffnlp/twitter-roberta-base-irony` | 卡片沒寫授權 ❔；499 MB | 用 TweetEval irony 訓練 | 估計 20–60 秒 | ✅ / 🧪 |
| 三項一起 | LLM 加評分規則（例如 `gpt-5-nano`） | — | 要用自建集來量 | 平行呼叫，估計 10–30 秒 | 🧪 |
| 黨派傾向（不建議） | `bucketresearch/politicalBiasBERT` | MIT；433 MB | 模型卡沒有評估數字 | — | ✅ 不放主線 |

模型資訊來源：[GroNLP](https://huggingface.co/GroNLP/mdebertav3-subjectivity-english)、[roberta-babe-ft](https://huggingface.co/mediabiasgroup/roberta-babe-ft)、[d4data](https://huggingface.co/d4data/bias-detection-model)、[zeroshot-v2.0](https://huggingface.co/MoritzLaurer/deberta-v3-base-zeroshot-v2.0)、[irony](https://huggingface.co/cardiffnlp/twitter-roberta-base-irony)、[politicalBiasBERT](https://huggingface.co/bucketresearch/politicalBiasBERT)。大小是用 HF API 查到的權重檔大小。

**Cloud Run 的注意事項：** 三個主線模型加起來約 2 GB（fp32），要在建 image 時就放進去，並設 4 vCPU、8 GiB。冷啟動和速度都沿用 T12 的方法量測。GroNLP 的 `config.json` 沒有 `id2label`，所以 `LABEL_0` 和 `LABEL_1` 哪個是 SUBJ，要用 CheckThat 的資料確認，🧪。

### 3.2 建議的分工

1. 三個本機模型跑全部留言：主觀性、偏頗用字、反諷旗標。
2. 立場只在本機跑「目標明確」的那串。目標由使用者輸入，或由 agent 從影片標題擬出來，再讓使用者確認。
3. **LLM 只重判以下兩種留言：** 本機模型信心低於門檻的，以及反諷分數高的。把定義、正例和反例寫成評分規則，輸出 JSON：`{"id":…,"subj":"SUBJ","stance":"AGAINST","loaded":1,"spans":["…"],"sarcasm":1}`。

### 3.3 LLM 成本估算

假設：

- 1,000 則留言，每則約 50 tokens。
- 每次請求放 25 則，評分規則約 600 tokens，所以輸入約 75k tokens。
- 每則輸出約 40 tokens，輸出約 40k tokens。

| 模型 | 價格（每 100 萬 tokens，輸入 / 輸出） | 每 1,000 則 |
|---|---|---|
| `gpt-5-nano` | 0.05 / 0.40 美元 | 約 0.02 美元，另加推理 tokens |
| `gpt-4o-mini` | 0.15 / 0.60 美元 | 約 0.035 美元 |
| Gemini 2.5 Flash-Lite | 0.10 / 0.40 美元 | 約 0.024 美元 |

價格沿用前一份文件 3.2 節（同一天查的）。只重判 20% 的話，費用再除以 5。

### 3.4 反諷是最大的弱點

- 政治留言常常用反話，例如 “Great job, Congress, another brilliant idea”。字面上是正面，實際上是反對。NLI 和以新聞訓練的模型都很容易判錯立場，也會把它當成「沒有偏頗用字」。
- VAST 的作者也把 sarcasm 列為「challenging linguistic phenomena」之一（[論文](https://arxiv.org/abs/2010.03640)）。我們可以直接用 VAST test 裡 431 則 `Sarc=1` 的資料，量出反諷造成的準確率落差。
- **對策：** 反諷旗標高的留言送給 LLM，報告上標「可能是反諷，判斷信心低」。不要假裝做得到。

### 3.5 毒性和煽動

Perspective API 已經不能用（前一份文件 0.2 節）。「煽動」可以用 OpenAI Moderation（免費）或 Civil Comments 訓練的模型當補充訊號，但不能取代 `loaded`：罵人和「用字偏頗」是兩回事。

---

## 4. 可行性測試

延續 T1–T15。T12（Cloud Run 速度）、T14（群組比較）、T15（YouTube 政策）的方法直接沿用，下面只寫新增的部分。

### T16 · 從 Cloud Run 呼叫四個政治來源

1. 在 T2 的最小 Cloud Run 服務裡，呼叫以下四種端點，每種各 10 次：
   - ECFS
   - Regulations.gov 的列表和明細
   - Bluesky `searchPosts`（第一頁和翻頁）
   - YouTube 的 `videos.list?chart=mostPopular&videoCategoryId=25`
2. 用 `videoCategories.list?regionCode=US` 確認 25 是 News & Politics（1 單位）。

**通過標準：**

- ECFS、Regulations.gov 和 YouTube 都回 200。
- 記下 `x-ratelimit-limit` 的值。
- 確認 Bluesky 從機房 IP 呼叫第一頁是否也回 200。如果是 403，政治貼文改成事先挑好、事先快取。

### T17 · FCC 模板群組當協同的標準答案

1. 用 1.2 節的指令抓 3 個已知的模板，各 1,000 則。
2. 從 17-108 號案另外隨機抽 2,000 則。
3. 對這 5,000 則跑原提案的協同訊號：文字相似、同一秒送出、署名的模式。

**通過標準：**

- 模板群組的召回率 ≥ 0.9。
- 隨機樣本裡被誤判成群組的比例要記錄下來。這是另一組偽陽性底線，可以跟 T7 比較。
- 名字只存雜湊值。

### T18 · 自建 300 則和標註一致度

1. 依 2.3 節的分配收集留言，先試標 30 則再修改指引。
2. 兩人各自標完全部 300 則。

**通過標準：**

- `subj` 和 `stance` 的 kappa ≥ 0.6，`loaded` ≥ 0.5。
- 12/1 提案前至少完成試標，並定好指引。

### T19 · 模型準確度

1. 在 CheckThat! test、VAST test、BABE test 和自建集上，分別跑 3.1 節的模型和 LLM 評分規則。

**通過標準：**

- 主觀性：CheckThat test 的 macro F1 ≥ 0.70。
- 自建集的三個欄位 macro F1 都 ≥ 0.60。
- 列出 VAST 的 `Sarc=1` 子集和其他資料的 F1 落差。
- 沒達標的欄位改成全部交給 LLM，或在報告裡標成「實驗性」。

### T20 · 速度（沿用 T12）

1. 把三個本機模型放進同一個 image，用 1,000 則政治留言測速。
2. 另外量 NLI 立場和 LLM 重判 20% 的時間。

**通過標準：**

- 全部加起來 ≤ 120 秒。
- 沒達標就改用 ONNX，或把立場整個交給 LLM。

### T21 · 協同群組 vs 一般留言者（沿用 T14）

1. 用 T17 的 FCC 資料和 T4 的 YouTube / Bluesky 案例，比較兩組的 `stance` 分布和 `overly_biased` 比例，用卡方檢定。

**通過標準：**

- 產出一張可以放進 README 的比較表。
- 有差異就寫進 demo；沒差異也要說明原因，例如模板留言的用字其實很「中立」。

YouTube 部分的呈現規則要先通過 T15 的檢查，而且規則要涵蓋立場標籤。

---

## 5. 查證來源

**政策與背景**
- [YouTube API Services 開發者政策](https://developers.google.com/youtube/terms/developer-policies)（見前一份文件 0.1 節）
- [Pew Research 2017：FCC 網路中立性留言分析](https://www.pewresearch.org/internet/2017/11/29/public-comments-to-the-federal-communications-commission-about-net-neutrality-contain-many-inaccuracies-and-duplicates/)
- [紐約州檢察長新聞稿 2021](https://ag.ny.gov/press-release/2021/attorney-general-james-issues-report-detailing-millions-fake-comments-revealing)（今天 DNS 失敗，沒讀到原文）
- [紐約州檢察長報告 PDF](https://ag.ny.gov/sites/default/files/reports/oag-fakecommentsreport.pdf)（同上）
- [GAO-19-483](https://www.gao.gov/products/gao-19-483)
- [ACUS Recommendation 2021-1](https://acus.gov/node/12335)
- [EPA：如何對 EPA 案卷留言](https://www.epa.gov/dockets/commenting-epa-dockets)

**資料來源**
- [Regulations.gov API（GSA）](https://open.gsa.gov/api/regulationsgov/)
- [api.data.gov 開發者手冊](https://api.data.gov/docs/developer-manual/)
- [api.data.gov 註冊](https://api.data.gov/signup/)
- [Regulations.gov bulk download（GSA 部落格）](https://www.gsa.gov/blog/2022/10/27/bulk-data-download-is-here-on-regulationsgov)
- [FCC 開發者頁（UNT 封存，2020）](https://webarchive.library.unt.edu/web/20201218044726/https://www.fcc.gov/reports-research/developers)
- [FCC 開發者頁（現行，對我們的工具回 403）](https://www.fcc.gov/reports-research/developers)
- [YouTube search.list](https://developers.google.com/youtube/v3/docs/search/list)
- [YouTube videos.list](https://developers.google.com/youtube/v3/docs/videos/list)
- [YouTube 額度表](https://developers.google.com/youtube/v3/determine_quota_cost)
- [YouTube API Revision history](https://developers.google.com/youtube/v3/revision_history)
- [Bluesky searchPosts 403 回報](https://github.com/bluesky-social/bsky-docs/issues/332)
- [Polis openData](https://github.com/compdemocracy/openData)

**資料集**
- [CheckThat! 2025 Task 1 GitLab](https://gitlab.com/checkthat_lab/clef2025-checkthat-lab/-/tree/main/task1)
- [CheckThat! 2025 Task 1 總覽論文](https://ceur-ws.org/Vol-4038/paper_51.pdf)
- [VAST repo](https://github.com/emilyallaway/zero-shot-stance)
- [VAST 論文](https://arxiv.org/abs/2010.03640)
- [TweetEval](https://github.com/cardiffnlp/tweeteval)
- [P-Stance](https://github.com/chuchun8/PStance)
- [BABE 論文](https://arxiv.org/abs/2209.14557)
- [BABE GitHub repo](https://github.com/Media-Bias-Group/Neural-Media-Bias-Detection-Using-Distant-Supervision-With-BABE)
- [BABE HF](https://huggingface.co/datasets/mediabiasgroup/BABE)
- [PTC（SemEval-2020 Task 11）Zenodo](https://zenodo.org/records/3952415)
- [SemEval-2023 Task 3](https://propaganda.math.unipd.it/semeval2023task3/)
- [Wiki Neutrality Corpus repo](https://github.com/rpryzant/neutralizing-bias)
- [WNC 論文](https://arxiv.org/abs/1911.09709)
- [SemEval-2019 Task 4（HF）](https://huggingface.co/datasets/SemEvalWorkshop/hyperpartisan_news_detection)
- [Civil Comments](https://huggingface.co/datasets/google/civil_comments)

**模型**
- [GroNLP/mdebertav3-subjectivity-english](https://huggingface.co/GroNLP/mdebertav3-subjectivity-english)
- [mediabiasgroup/roberta-babe-ft](https://huggingface.co/mediabiasgroup/roberta-babe-ft)
- [d4data/bias-detection-model](https://huggingface.co/d4data/bias-detection-model)
- [MoritzLaurer/deberta-v3-base-zeroshot-v2.0](https://huggingface.co/MoritzLaurer/deberta-v3-base-zeroshot-v2.0)
- [cardiffnlp/twitter-roberta-base-irony](https://huggingface.co/cardiffnlp/twitter-roberta-base-irony)
- [bucketresearch/politicalBiasBERT](https://huggingface.co/bucketresearch/politicalBiasBERT)
- LLM 價格：見 `sentiment-data-feasibility.md` 3.2 節（[OpenAI](https://developers.openai.com/api/docs/pricing)、[Gemini](https://aistudio.google.com/docs/pricing)）
