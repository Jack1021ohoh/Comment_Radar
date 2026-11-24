# 留言雷達：加上情緒分析的資料可行性研究

> 這份文件補充 `comment-radar-proposal.md` 的第 3 節，只看「加上情緒分析」需要的資料、標註資料集和模型。
>
> 查證日期：2026-11-23。標「需實測」的項目要等 T10 之後的測試跑完才算確定。
>
> ⚠️ 這份文件只是參考。DESIGN.md 必須自己手寫，請不要把句子貼過去。

**結論摘要：** 建議新增兩個資料來源：**Hacker News**（Algolia API 一次拿到整串留言樹，Firebase API 補帳號建立時間）和 **Steam 使用者評論**（新版 `IUserReviewsService/GetAppReviews`，免 key，自帶「評論轟炸」過濾開關）。**Mastodon** 列為第三選擇。三者都免費，英文內容多，也都不需要審核。評估資料用 **TweetEval sentiment**（SemEval-2017 Task 4，3 類）測正負面，用 **GoEmotions**（Reddit 留言，27 種情緒 + neutral，Apache-2.0）測情緒。另外自己標 200 則 demo 平台的留言當主要 eval。模型主線是 `cardiffnlp/twitter-roberta-base-sentiment-latest` 加 `j-hartmann/emotion-english-distilroberta-base`，在 Cloud Run CPU 上跑，不花 API 費用。VADER 當 baseline。LLM（例如 `gpt-5-nano`）只處理立場和反諷這類難判的子集，估計每 1,000 則留言約 0.01–0.05 美元。

**這次查到的四件意外：**

1. **YouTube 政策可能不允許「情緒分數」**：開發者政策禁止用 API 資料「產生新的或衍生的資料或指標」。政策指南更直接把「估計觀眾對某個頻道的滿意或不滿」列為不可接受的指標。這跟原提案的假設有衝突，見 [0.1](#01-youtube-政策風險原提案沒有提到)。
2. **Perspective API 2026/12/31 停止服務**：2026 年 2 月後已經不收新的使用申請，現在申請不到。
3. **Steam 舊的 `appreviews` 端點已經淘汰**：今天實測會 302 轉到首頁，要改用新版端點。
4. **Reddit `.json` 端點**：今天從一般住家 IP 呼叫也回 403。

---

## 目錄

0. [先處理的風險](#0-先處理的風險)
1. [額外的留言資料來源](#1-額外的留言資料來源)
2. [情緒、情感、立場的標註資料集](#2-情緒情感立場的標註資料集)
3. [模型和 API：成本與速度](#3-模型和-api成本與速度)
4. [建議的可行性測試](#4-建議的可行性測試)
5. [查證來源](#5-查證來源)

狀態標記沿用原提案：

| 標記 | 意思 |
|---|---|
| ✅ 已查證 | 官方文件確認，或今天實際呼叫成功 |
| 🧪 需實測 | 文件說可以，但沒從 Cloud Run 測過，或數字是我們估的 |
| 📨 需申請 | 要寄信或填表，等對方回覆 |
| ❔ 未證實 | 只有第三方的說法，或官方頁面沒寫 |

---

## 0. 先處理的風險

### 0.1 YouTube 政策風險（原提案沒有提到）

| 條文 | 內容 | 狀態 |
|---|---|---|
| 開發者政策 III.E.4.h | API Client 不得「access or use API Data to create new or derived data or metrics」。如果在 API 資料旁邊顯示自己算的資料，要清楚標示「不是 YouTube 的資料」 | ✅ [原文](https://developers.google.com/youtube/terms/developer-policies)，頁面最後更新 2026-11-06 |
| 政策指南「Unacceptable metrics」 | 範例包括 “Estimate viewer satisfaction or dissatisfaction with a particular YouTube channel”，還有 “Calculate and assign custom ‘scores’ to channels” | ✅ [原文](https://developers.google.com/youtube/terms/developer-policies-guide)，最後更新 2026-09-14 |
| 政策 III.L | 從 2026-06-01 起，衍生指標的額外許可只開放給「通過稽核、有分析用途、並且申請過」的開發者 | ✅ 同上 |

**意思是：** 對 YouTube 留言算「這個頻道的觀眾滿意度」幾乎就是範例裡禁止的事。原提案的協同分數如果被解讀成「給頻道打分」，也有類似風險。這一點跟原提案 3.2 節「YouTube ✅ 已查證」的結論有落差，要補進風險表。

**我們的解讀（❔，不是法律意見）：**

- 對**單則留言**做文字分類，並標示「這是 Comment Radar 自己的分析，不是 YouTube 的資料」，風險比較低。
- 不要產生頻道層級的「滿意度」或排名。
- 情緒分析的主要 demo 改用 Bluesky、Hacker News 和 Steam。YouTube 只顯示「可疑群組和一般留言者的情緒差異」這類比較，並且加上標示。

### 0.2 Perspective API 停止服務

- 官方公告：服務「will remain active until December 31, 2026」，2026 年 2 月後「no longer accept any new requests」。✅ [perspectiveapi.com](https://perspectiveapi.com/)
- 我們現在申請不到，所以不要用。替代方案見 [3.3](#33-毒性偵測perspective-的替代)。

---

## 1. 額外的留言資料來源

### 1.1 總覽和排名

排名依據：適不適合做「留言區情緒 + 協同偵測」、英文內容多不多、免不免費、能不能從 Cloud Run 呼叫。

| 排名 | 管道 | 文字 / 時間 / 作者 / 回覆結構 | 帳號資料 | 驗證 | 費用和限制 | 機房 IP | 狀態 |
|:---:|---|---|---|---|---|---|---|
| 1 | **Hacker News** | ✅ / ✅ / ✅ / ✅ 完整樹狀 | 建立時間、karma | 不用 | 免費；Algolia 每個 IP 每小時 10,000 次；Firebase「目前沒有速率限制」 | 🧪 | ✅ |
| 2 | **Steam 評論** | ✅ / ✅ / ✅ steamid / ❌ 只有回覆數 | 評論數、遊玩時數、最後遊玩時間 | 不用 | 免費；Steam Web API 每天 100,000 次；匿名呼叫共用較低限額 | 🧪 | ✅ |
| 3 | **Mastodon** | ✅ / ✅ / ✅ / ✅ | 建立日期（只到日）、`bot` 旗標、貼文數、追蹤數 | 公開免登入；登入後可拿更多 | 每個 IP 每 5 分鐘 300 次；未登入最多 60 則回覆 | 🧪 | ✅ |
| 4 | Lemmy | ✅ / ✅ / ✅ / ✅ `path` | 建立時間、`bot_account` | 公開讀取免登入 | 免費；lemmy.world 設定為每 60 秒 999 次 | 🧪 | ✅ |
| 5 | Stack Exchange | ✅ / ✅ / ✅ / 部分（`reply_to_user`） | 聲望 | 免 key 每天 300 次；有 key 每天 10,000 次 | 每個 IP 每秒超過 30 次會被封鎖 | 🧪 | ✅ |
| 6 | Apple App Store RSS | ✅ / ✅ / 名字 / ❌ | 幾乎沒有 | 不用 | 每個 app 最多 10 頁 × 50 則 | 🧪 | 🧪 沒有官方文件 |
| 7 | Disqus | ✅ / ✅ / ✅ / ✅ | ❔ | 要申請 public key | Basic 帳號每小時 1,000 次 | 🧪 | ✅ |
| 8 | GitHub issues 和 discussions | ✅ / ✅ / ✅ / 部分 | 建立時間 | 免登入每小時 60 次；用 PAT 每小時 5,000 次 | 免費 | ✅ | ✅ |
| 9 | YouTube 直播聊天 | 只有直播中 | 同 YouTube | API key | 每次 5 單位；直播結束後回 `liveChatEnded` | ✅ | ✅ |
| 10 | Twitch 聊天 | 只有直播中 | 少 | 要登入 | 官方建議走 EventSub | — | ✅ |
| 排除 | Reddit、X、Threads、TikTok、Google Play、Telegram | 見 [1.6](#16-再確認一次的排除清單) | | | | | |

### 1.2 推薦 #1：Hacker News　✅ 已查證

- **拿到什麼**：
  - Algolia 的 `items/{id}` 一次回傳整串留言樹。每則留言有 `author`、`created_at`、`text`、`parent_id` 和 `children`。✅ 今天實測成功
  - Firebase 的 `user/{id}` 回傳 `created`（Unix 時間）、`karma` 和 `submitted`。[官方 repo](https://github.com/HackerNews/API) ✅
- **費用和限制**：
  - 兩個 API 都免費、免 key。
  - Firebase API 的 README 寫「There is currently no rate limit」。
  - Algolia 的官方頁面寫「limiting the number of API requests from a single IP to 10,000 per hour」。這段文字在頁面的 JS 原始碼裡，[HN Search API](https://hn.algolia.com/api)。
- **條款**：YC 的使用條款禁止 scraping，「except as Y Combinator expressly authorizes」，也禁止買賣 upvote 和留言。[YC Legal](https://www.ycombinator.com/legal/)。官方 API 是被授權的取用方式，**不要爬 HTML**。
- **機房 IP**：Algolia API 回應的標頭是 `server: Google Frontend`，看起來本身就架在 Google 上。沒看到封鎖雲端 IP 的說法，但要用 T10 實測。🧪
- **適合的原因**：
  - 爭議文章底下的英文討論，情緒和立場分歧明顯，評分者也看得懂。
  - 帳號建立時間可以直接拿來做「新帳號群聚」訊號。
- **缺點**：
  - 投票資料拿不到，所以投票部隊看不到。
  - 被版主標成 `dead` 的留言可能缺少內容。

**怎麼取得：**

1. 不用註冊。打開任一篇 HN 文章，網址 `item?id=` 後面的數字就是 `$HN_STORY_ID`。
2. 呼叫 Algolia 的 `items` 端點，拿到整棵留言樹。
3. 把樹攤平，收集不重複的 `author`。
4. 用 Firebase 的 `user` 端點平行抓帳號資料，並發數設 10 以內。

```bash
curl "https://hn.algolia.com/api/v1/items/$HN_STORY_ID"
```

```bash
curl "https://hacker-news.firebaseio.com/v0/user/$HN_USER.json"
```

```python
import httpx, asyncio

async def fetch_hn(story_id: int):
    async with httpx.AsyncClient(timeout=30) as c:
        tree = (await c.get(f"https://hn.algolia.com/api/v1/items/{story_id}")).json()
        rows, stack = [], [tree]
        while stack:
            n = stack.pop()
            if n.get("type") == "comment" and n.get("text"):
                rows.append({"id": n["id"], "author": n["author"], "parent": n["parent_id"],
                             "ts": n["created_at_i"], "text": n["text"]})
            stack.extend(n.get("children", []))
        sem = asyncio.Semaphore(10)
        async def user(u):
            async with sem:
                return u, (await c.get(f"https://hacker-news.firebaseio.com/v0/user/{u}.json")).json()
        users = dict(await asyncio.gather(*[user(u) for u in {r["author"] for r in rows}]))
        return rows, users
```

### 1.3 推薦 #2：Steam 使用者評論　✅ 已查證

- **舊端點已經淘汰**：官方文件寫「`store.steampowered.com/appreviews/<appid>?json=1` is deprecated」。今天實測會 302 轉到 Steam 首頁。網路上大部分教學還在用舊端點，**不能照抄**。[GetReviews 頁](https://partner.steamgames.com/doc/store/getreviews)
- **新端點**：`GET https://api.steampowered.com/IUserReviewsService/GetAppReviews/v1/`，參數放在 `input_json`。官方寫「This method does not require a key」。[IUserReviewsService](https://partner.steamgames.com/doc/webapi/IUserReviewsService) ✅ 今天實測回 200。
- **拿到什麼**：
  - 評論本身：全文、`timestamp_created`、`voted_up`（推薦或不推薦，等於現成的正負面標籤）、`votes_up`、`comment_count`、`refunded`。
  - 作者：`author.steamid`、`num_reviews`、`playtime_at_review`、`last_played`。
  - 篩選條件：可以依日期區間和遊玩時數篩選。
  - 和舊版的差異：新版**不再回傳 `num_games_owned`**。
- **評論轟炸開關**：`filter_offtopic_activity` 預設會把離題的「Review Bombs」濾掉，傳 `false` 就能拿回來。這是 Steam 官方認定的協同負評，對「情緒 + 協同」正好是現成的案例。
- **限制**：
  - 每頁最多 100 則。
  - 匿名回應可能有最多 10 分鐘的快取。
  - 沒有 key 的呼叫共用比較低的限額，超過會回 429。
  - 整個 Steam Web API 每天上限 100,000 次。[API Terms](https://steamcommunity.com/dev/apiterms)
- **條款注意**：API Terms 寫「只在使用者要求時才取得該使用者的資料」。所以**不要**另外用 `GetPlayerSummaries` 去抓評論者的個人檔案，只用評論回應裡附的 `author` 欄位。❔ 這是我們的解讀。
- **今天抽樣看到的現象**：最近兩則 CS2 評論都是一句很籠統的好評。兩個作者都只寫過 1 則評論，總遊玩時數接近，`last_played` 完全一樣。這只是觀察，**不代表已確認是協同**，可以留給 T11 檢查。

**怎麼取得：**

1. 不用註冊。在 Steam 商店網址 `store.steampowered.com/app/<APPID>/` 找到 `APPID`。
2. 第一頁的 `cursor` 傳 `*` 或不傳。之後把回應的 `cursor` 帶到下一頁，記得 URL 編碼。
3. 想看評論轟炸期間，就設 `date_range_start`、`date_range_end`（兩個都要設），並把 `filter_offtopic_activity` 設成 `false`。

```bash
curl -G "https://api.steampowered.com/IUserReviewsService/GetAppReviews/v1/" \
  --data-urlencode 'input_json={"appid":730,"filter":1,"num_per_page":100,"languages":["english"],"filter_offtopic_activity":false}'
```

```python
import httpx, json

def steam_reviews(appid: int, limit: int = 1000):
    url = "https://api.steampowered.com/IUserReviewsService/GetAppReviews/v1/"
    cursor, out = "*", []
    while len(out) < limit:
        q = {"appid": appid, "filter": 1, "num_per_page": 100, "languages": ["english"],
             "cursor": cursor, "filter_offtopic_activity": False}
        r = httpx.get(url, params={"input_json": json.dumps(q)}, timeout=30)
        r.raise_for_status()
        resp = r.json()["response"]
        if not resp.get("reviews"):
            break
        out += resp["reviews"]
        cursor = resp["cursor"]
    return out[:limit]
```

### 1.4 推薦 #3：Mastodon　✅ 已查證

- **端點**：`GET /api/v1/statuses/:id/context`
  - 官方文件：公開貼文「limited to 40 ancestors and 60 descendants with a maximum depth of 20」。
  - 用 `read:statuses` 的 user token 可以拿到 4,096 則、不限深度。4.0.0 版開始限制未登入的請求。[文件](https://docs.joinmastodon.org/methods/statuses/#context)
  - 今天實測：mastodon.social 一則有 64 則回覆的貼文，未登入時回 59 則，符合上限。
- **帳號資料**：`created_at`（3.4.0 起只精確到當天午夜）、`bot`、`statuses_count`、`followers_count`、`last_status_at`。[Account](https://docs.joinmastodon.org/entities/Account/) ✅
- **速率限制**：每個帳號和每個 IP 都是「300 times within 5 minutes」。[Rate limits](https://docs.joinmastodon.org/api/rate-limits/) ✅ 回應標頭也看得到 `x-ratelimit-limit: 300`。
- **每個站台規定不同**：
  - 站台可以開 `AUTHORIZED_FETCH` 或 `DISALLOW_UNAUTHENTICATED_API_ACCESS`，兩者預設都關閉。[設定說明](https://docs.joinmastodon.org/admin/config/)
  - mastodon.social 的公開時間軸未登入時回 422，今天實測確認。
  - 研究指出許多站台的規則明確禁止收集研究資料（[Lisker & Mihaljević 2025](https://arxiv.org/html/2505.07606v1)）。用之前要先看該站台的規則。❔
- **其他限制**：
  - 貼文 ID 只在該站台有效，要在原本的站台查。
  - 跨站台的回覆可能不完整。4.5 版會在背景補抓，並回傳 `Mastodon-Async-Refresh` 標頭。
- **適合的原因**：資料結構和 Bluesky 很像，可以共用程式。缺點是熱門貼文的回覆量比 Bluesky 少很多。

**怎麼取得：**

1. 從網址 `https://<instance>/@user/<STATUS_ID>` 取出站台和貼文 ID。
2. 先不登入呼叫 `context`，60 則以內就夠用。
3. 需要更多時，在該站台登入 → 偏好設定 → Development → New application，scope 只勾 `read:statuses`，複製 access token。放進 Cloud Run 的 Secret Manager，不要寫進 repo。

```bash
curl "https://mastodon.social/api/v1/statuses/$STATUS_ID/context"
```

```bash
curl -H "Authorization: Bearer $MASTO_TOKEN" "https://mastodon.social/api/v1/statuses/$STATUS_ID/context"
```

### 1.5 備選管道

| 管道 | 重點 | 怎麼取得 | 為什麼沒有排前面 |
|---|---|---|---|
| **Lemmy** | `GET /api/v3/comment/list?post_id=…` 回傳 `path`（回覆樹）、`published`，以及作者的 `published` 和 `bot_account`。✅ 今天在 lemmy.world 實測成功，伺服器版本 0.19.21 | 免登入。速率限制依 IP 計算，[官方文件](https://join-lemmy.org/docs/contributors/04-api.html)沒寫數字；lemmy.world 的 `/api/v3/site` 顯示一般請求每 60 秒 999 次 | 社群小，熱門討論的留言量少 |
| **Stack Exchange** | `/2.3/posts/{ids}/comments` 有 `owner.reputation`、`creation_date`、`reply_to_user`，內容是 CC BY-SA 4.0。✅ 實測成功 | 免 key 每天 300 次（實測 `quota_max: 300`）；在 Stack Apps 註冊 key 後每天 10,000 次。每個 IP 每秒超過 30 次會被封鎖。[Throttle](https://api.stackexchange.com/docs/throttle) | 留言以技術討論為主，情緒訊號弱 |
| **Apple App Store RSS** | `itunes.apple.com/us/rss/customerreviews/page=N/id=APPID/sortby=mostrecent/json` 今天還能用：每頁 50 則，第 11 頁回 400，所以最多 500 則 | 免登入。**Apple 沒有正式文件**，隨時可能關閉。官方的 App Store Connect API 只能看自己團隊的 app（❔ 文件頁沒讀到內容） | 只有評分、標題、內文和名字，沒有帳號資料，協同訊號太弱 |
| **Disqus** | `threads/listPosts.json` 寫「Requires authentication: no」，但要帶 public `api_key`，每次最多 100 則。[文件](https://disqus.com/api/docs/threads/listPosts/) | 到 disqus.com/api 註冊 application，拿 public key。Basic 帳號「restricted to 1,000 requests per hour」 | 要先知道該網站的 forum shortname；作者帳號欄位沒查證 ❔ |
| **GitHub** | issues 和 discussions 的留言，作者有 `created_at` | 用 fine-grained PAT。未登入每小時 60 次，PAT 每小時 5,000 次。[Rate limits](https://docs.github.com/en/rest/using-the-rest-api/rate-limits-for-the-rest-api) | 英文多，但情緒和「留言區民意」的故事不合 |
| **YouTube 直播聊天** | `liveChatMessages.list` 每次 5 單位，`maxResults` 200–2000 | 跟原本的 API key 共用額度 | 直播結束後回 `liveChatEnded`，沒辦法事後分析。[文件](https://developers.google.com/youtube/v3/live/docs/liveChatMessages/list) |
| **Twitch 聊天** | 官方說「The preferred method … is through EventSub」，IRC 是舊介面 | 要登入；EventSub 要實況主授權 `channel:bot`。[文件](https://dev.twitch.tv/docs/chat/) | 只有即時訊息，沒有歷史紀錄 |

### 1.6 再確認一次的排除清單

和原提案 3.6 節的結論**一致**，以下是補上的新證據：

| 管道 | 現況 | 狀態 |
|---|---|---|
| **Reddit** | 2025-11-11 在 r/redditdev 公告 Responsible Builder Policy：開發者、研究者、版主都要「request approval before gaining access」，自助申請 API key 關閉。官方說研究者走申請工單，目標 7 天內回覆。今天從住家 IP 呼叫 `.json` 端點也回 403。官方說明頁 support.reddithelp.com 對我們的抓取工具回 403，以上內容只從鏡像站和搜尋摘要讀到 | ❔ 政策原文沒讀到；📨 要走申請 |
| **X** | 按量付費：讀一則貼文 0.005 美元、讀一個帳號 0.010 美元，每月上限 300 萬則貼文。頁面沒提到免費方案。[Pricing](https://docs.x.com/x-api/getting-started/pricing) | ✅ 和原提案一致 |
| **Threads** | 沒通過審核前，keyword search「is performed only on posts owned by the authenticated user」，每個使用者每 24 小時 2,200 次查詢。能不能讀別人貼文的回覆，文件沒寫清楚。[Keyword search](https://developers.facebook.com/docs/threads/keyword-search) | ✅ / ❔ |
| **TikTok Research API** | 有留言端點 `/v2/research/video/comment/list/`（每次最多 100 則）。美國的學術機構符合資格，但要附研究計畫、倫理審查和經費揭露。[資格](https://developers.tiktok.com/products/research-api/)、[留言端點](https://developers.tiktok.com/doc/research-api-specs-query-video-comments) | 📨 12/9 前來不及 |
| **Google Play** | 官方 Reply to Reviews API 只能看自己 app 的評論，而且只限「created or modified within the last week」。[文件](https://developers.google.com/android-publisher/reply-to-reviews)。`google-play-scraper` 這類套件（MIT）是爬網頁，Google 服務條款禁止「using automated means to access content … in violation of the machine-readable instructions」。[Google ToS](https://policies.google.com/terms?hl=en) | ✅ 排除 |
| **Telegram** | 要用手機號碼申請 `api_id`。官方說用非官方客戶端登入的帳號「automatically put under observation」，濫用會「banned forever」。[文件](https://core.telegram.org/api/obtaining_api_id) | ✅ 排除：帳號風險高，英文內容也不好驗證 |

---

## 2. 情緒、情感、立場的標註資料集

### 2.1 總表

| 資料 | 大小（實際查到的切分） | 標籤 | 領域 | 授權 | 狀態 |
|---|---|---|---|---|---|
| **TweetEval sentiment**（= SemEval-2017 Task 4） | train 45,615 / val 2,000 / test 12,284 | negative、neutral、positive | 推文 | repo 寫「released without any restrictions but restrictions may apply to individual tasks」，HF 卡片標 `unknown` | ✅ |
| **TweetEval emotion**（SemEval-2018 Task 1） | 3,257 / 374 / 1,421 | anger、joy、optimism、sadness | 推文 | 同上 | ✅ |
| **TweetEval stance**（= SemEval-2016 Task 6） | 5 個主題：abortion、atheism、climate、feminist、hillary。例如 climate 是 355 / 40 / 169 | none、against、favor | 推文 | 同上 | ✅ |
| TweetEval irony 和 hate | irony 2,862 / 955 / 784；hate 9,000 / 1,000 / 2,970 | 二元 | 推文 | 同上 | ✅ |
| **GoEmotions** | simplified 版 43,410 / 5,426 / 5,427；raw 版 211,225 筆標註；README 寫 58,009 則 | 27 種情緒 + neutral，多標籤 | **Reddit 留言** | HF 卡片標 Apache-2.0 | ✅ |
| Sentiment140 | 訓練 1,600,000 則（用表情符號自動標）；人工標註測試集 498 則（負 177、中性 139、正 182） | 0 / 2 / 4 | 推文（2009） | Stanford 頁面沒寫授權 ❔ | ✅ 今天實際下載確認 |
| SST-2 | 67,349 / 872 / 1,821（test 沒有標籤） | 二元 | 影評句子 | HF 標 `unknown` | ✅ |
| IMDb | 25,000 / 25,000，另有 50,000 則沒標註 | 二元 | 長篇影評 | HF 標 `other` | ✅ |
| Yelp Polarity | 560,000 / 38,000 | 二元 | 店家評論 | 來源是 Yelp Open Dataset，官方寫「intended for educational use」 | ✅ / ❔ |
| Amazon Reviews 2023（McAuley Lab） | 5.7 億則評論、33 個類別，1996/5 到 2023/9 | 1–5 星（可當弱標籤） | 商品評論 | 官網沒寫授權 ❔ | ✅ |
| `cardiffnlp/tweet_sentiment_multilingual` | 英文 1,839 / 324 / 870 | 3 類 | 8 種語言的推文，**沒有中文** | HF 沒標 ❔ | ✅ |
| SenTube（LREC 2014） | 論文說約 35k 則標註的 YouTube 留言（平板、汽車主題） | 資訊類型 + 正負面 | **YouTube 留言** | 沒找到授權；後續論文說放在 iKernels 專案頁，但沒確認還在不在 | ❔ |
| Chinese EmoBank / CVAT | CVAT 2016 版 2,009 句，EmoBank 版 2,969 則 | valence-arousal 連續值 | 網路文本；第三方說相關詞典是繁體，文本本身是不是繁體**沒有查證** | 沒找到公開下載連結 | 📨 / ❔ |

連結：[TweetEval repo](https://github.com/cardiffnlp/tweeteval)、[GoEmotions](https://github.com/google-research/google-research/tree/master/goemotions)、[Sentiment140 zip](https://cs.stanford.edu/people/alecmgo/trainingandtestdata.zip)、[Amazon Reviews 2023](https://amazon-reviews-2023.github.io/)、[Yelp Open Dataset](https://business.yelp.com/data/resources/open-dataset/)、[SenTube 論文](https://aclanthology.org/L14-1188/)、[CVAT 論文](https://aclanthology.org/N16-1066/)。HF 切分大小是用 `datasets-server` 的 `/info` 查的。

**要小心的地方：**

- **Kaggle 上的「YouTube comments sentiment」資料集**大多沒有論文、沒有標註流程，也沒有授權說明，常常是用 VADER 或 TextBlob 自動標的。拿來 eval 等於拿模型測模型。**不要用**。
- **`datasets` 4.0 移除了 loading script**：release notes 寫「Remove scripts altogether」，`trust_remote_code` 也不再支援。`stanfordnlp/sentiment140` 和 `cardiffnlp/tweet_sentiment_multilingual` 的 repo 裡都只有 `.py` 腳本，**新版 `load_dataset` 會失敗**。要改用原始 zip，或讀 HF 自動轉好的 parquet 檔。[Release 4.0.0](https://github.com/huggingface/datasets/releases/tag/4.0.0)

### 2.2 下載方式

```python
from datasets import load_dataset

sent = load_dataset("cardiffnlp/tweet_eval", "sentiment")
emo = load_dataset("cardiffnlp/tweet_eval", "emotion")
stance = load_dataset("cardiffnlp/tweet_eval", "stance_climate")
goemo = load_dataset("google-research-datasets/go_emotions", "simplified")
sst2 = load_dataset("stanfordnlp/sst2")
imdb = load_dataset("stanfordnlp/imdb")
yelp = load_dataset("fancyzhx/yelp_polarity")
```

Sentiment140 直接下載原始 zip：

```bash
curl -LO https://cs.stanford.edu/people/alecmgo/trainingandtestdata.zip
```

多語版改讀 parquet 檔（🧪 網址是從 HF parquet API 查到的，沒有實際載入過）：

```python
from datasets import load_dataset
base = "https://huggingface.co/api/datasets/cardiffnlp/tweet_sentiment_multilingual/parquet/english"
ml = load_dataset("parquet", data_files={"test": f"{base}/test/0.parquet"})
```

Amazon Reviews 2023 從[官網](https://amazon-reviews-2023.github.io/)下載單一類別的 `.jsonl`。HF 上的版本可能依賴 loading script，🧪 需實測。

### 2.3 有沒有「情緒 × 協同帳號」的資料集？

**沒有找到公開、直接可用的。** 相關研究都建立在 X 的資訊操作封存檔上，論文頁面也沒說有釋出資料：

| 研究 | 內容 | 資料 |
|---|---|---|
| [Dey, Luceri, Ferrara 2024](https://arxiv.org/abs/2402.05873) | 約 350 萬則加薩衝突推文。和協同帳號互動後，一般使用者的情緒表達變得更兩極 | 頁面沒說有釋出 ❔ |
| [Shafin & Ahmed 2025](https://arxiv.org/abs/2505.07212) | 中國、伊朗、俄羅斯國家級帳號約 200 萬則推文的情緒和仇恨言論比較：俄羅斯偏負面，中國偏正面、中性 | 用的是 Twitter 公開的國家級帳號資料；論文本身沒說有釋出 ❔ |

**實際做法：** 用原提案的 X IO 封存檔（如果拿得到）或 Collusion Scam 資料，加上我們自己的情緒模型，自己算「協同群組和一般帳號的情緒差異」。這兩篇論文可以引用在 DESIGN.md 的動機段落（記得自己寫）。

### 2.4 建議的 eval 組合

1. **主要 eval：自建 200 則**。HN、Steam、Bluesky、YouTube 各 50 則，兩人各自標 negative / neutral / positive 加情緒，算 Cohen’s kappa。這是唯一跟 demo 同一個領域的資料。
2. **正負面基準**：TweetEval sentiment test（12,284 則），跟 cardiffnlp 模型卡上的分數對照，確認我們的流程沒寫錯。
3. **情緒基準**：GoEmotions test（5,427 則），把 27 類對應到 Ekman 6 類加 neutral，再測 j-hartmann 模型。
4. **Steam 弱標籤**：`voted_up` 當正負面的弱標籤，免費又大量。但「不推薦 + 正面語氣」的反諷很多，正好可以當錯誤分析的素材。
5. **繁中**（加分項）：寫信向 CVAT 或 Chinese EmoBank 的作者申請，📨。拿不到不影響主線，因為 demo 全部是英文。

---

## 3. 模型和 API：成本與速度

### 3.1 選項比較（以 1,000 則短留言計）

| 選項 | 輸出 | 授權和大小 | 每 1,000 則的費用 | Cloud Run CPU 速度 | 狀態 |
|---|---|---|---|---|---|
| **`cardiffnlp/twitter-roberta-base-sentiment-latest`** | neg / neu / pos | CC BY 4.0；約 501 MB；用約 1.24 億則推文預訓練，再用 TweetEval 微調 | 0 | 估計 20–60 秒（2–4 vCPU，batch 32） | ✅ 規格 / 🧪 速度 |
| **`j-hartmann/emotion-english-distilroberta-base`** | anger、disgust、fear、joy、neutral、sadness、surprise | 模型卡**沒寫授權** ❔；約 329 MB；訓練資料約 2 萬筆，評估準確率 66% | 0 | distil 版，估計比上一個快約一倍 | ✅ / 🧪 |
| `SamLowe/roberta-base-go_emotions` | GoEmotions 28 類 | MIT；約 499 MB；有 ONNX 版 | 0 | 同 roberta-base | ✅ / 🧪 |
| **VADER** | compound 分數，±0.05 是正負面門檻 | MIT；純規則、很小 | 0 | 1 秒以內（❔ 估計） | ✅ |
| Google Cloud Natural Language `analyzeSentiment` | score + magnitude，句子層級 | — | 每次請求至少算 1 個單位（1,000 字元以內）。每月前 5,000 單位免費；再往上是 1.00 美元 ❔（頁面寫「Price per 1,000-character unit」，但依舊慣例應該是每 1,000 單位 1 美元，要用 billing 實測確認）。**每則留言各送一次的話，每月只能免費跑 5 個任務** | 網路延遲為主 | ✅ / ❔ |
| LLM（`gpt-5-nano` 等） | 情緒、立場、反諷、理由，一次全包 | — | 見 3.2 | 平行呼叫，估計 10–30 秒 | ✅ 價格 / ❔ 速度 |

**Cloud Run 的上限：** 每個實例最多 8 vCPU、32 GiB 記憶體，請求逾時最長 60 分鐘。[Quotas](https://docs.cloud.google.com/run/quotas) ✅。在 5 分鐘內跑完沒問題，真正的風險是**冷啟動**：兩個模型加起來約 830 MB，要在建 image 時就放進去，不要在啟動時下載。可以考慮 ONNX Runtime 加速。上表的速度都是估計值，T12 會量出實際數字。

### 3.2 LLM 分類的成本估算

假設：

- 1,000 則英文留言，每則平均約 50 tokens（❔ 估計值，T12 會實測）。
- 每次請求放 50 則，共 20 次請求。每次的指令約 300 tokens。
- 輸入約 56k tokens。
- 每則輸出約 20 tokens 的 JSON，例如 `{"id":…,"s":"neg","e":"anger","stance":"against"}`，輸出約 20k tokens。

| 模型 | 價格（每 100 萬 tokens，輸入 / 輸出） | 每 1,000 則 |
|---|---|---|
| `gpt-5-nano` | 0.05 / 0.40 美元 | 約 0.011 美元，另加推理 tokens（❔ 要把 reasoning effort 設最低） |
| `gpt-4o-mini` | 0.15 / 0.60 美元 | 約 0.020 美元 |
| Gemini 2.5 Flash-Lite | 0.10 / 0.40 美元（有免費額度） | 約 0.014 美元 |
| Gemini 3.1 Flash-Lite | 0.25 / 1.50 美元（有免費額度） | 約 0.044 美元 |

價格來源：[OpenAI pricing](https://developers.openai.com/api/docs/pricing)、[Gemini pricing](https://aistudio.google.com/docs/pricing)。Batch API 都打五折，但要等比較久，不適合 5 分鐘的限制。

**結論：** 錢不是問題，每個任務幾分錢。真正的問題是**可重現性**和**eval**。LLM 標籤每次跑可能不一樣。原提案「LLM 不負責算數字」的分工也適用在這裡：主線用本機模型，LLM 只處理本機模型低信心的子集，或立場這種本機模型做不到的任務。

### 3.3 毒性偵測：Perspective 的替代

| 選項 | 說明 | 狀態 |
|---|---|---|
| ~~Perspective API~~ | 2026/12/31 停止服務，2 月後就不收新申請 | ✅ 排除 |
| OpenAI Moderation（`omni-moderation-latest`） | 官方寫「The moderation endpoint is free to use」，有 13 類，包括 harassment 和 hate。[文件](https://developers.openai.com/api/docs/guides/moderation) | ✅ |
| Google Cloud NL Text Moderation | 每 100 字元算 1 單位，每月前 50,000 單位免費 | ✅ |
| `cardiffnlp/twitter-roberta-base-hate-latest` | CC BY 4.0，在本機跑 | ✅ |

### 3.4 建議的組合和 MCP 工具

在原提案的 `radar-mcp` 加一個工具：

| 工具 | 輸入 | 輸出 |
|---|---|---|
| `score_sentiment` | `thread_id` | 每則留言的 sentiment 和 emotion；整串的分布；每 10 分鐘的情緒時間線；**可疑群組和其他留言者的情緒比較**（例如用 Mann–Whitney U 檢定） |

最後一項是賣點：「這群可疑帳號的正面比例是 92%，其他留言者只有 41%」。這比單純畫情緒圓餅圖更能支撐協同判斷，也可以交給辯護律師 agent 反駁，例如「新遊戲上市本來就一面倒好評」。

```python
from transformers import pipeline

sent = pipeline("text-classification", model="cardiffnlp/twitter-roberta-base-sentiment-latest",
                truncation=True, max_length=128)
emo = pipeline("text-classification", model="j-hartmann/emotion-english-distilroberta-base",
               truncation=True, max_length=128)

def score(texts: list[str]):
    return list(zip(sent(texts, batch_size=32), emo(texts, batch_size=32)))
```

---

## 4. 建議的可行性測試

延續原提案的 T1–T9。

### T10 · 從 Cloud Run 呼叫三個新來源

1. 在 T2 的最小 Cloud Run 服務裡，加上 1.2–1.4 節的 curl 指令（HN 兩個端點、Steam、Mastodon）。
2. 每個端點連續呼叫 20 次，記錄狀態碼和延遲。

**通過標準：** 從 Cloud Run 呼叫全部回 200，沒有 403 或 429。

### T11 · Steam 評論轟炸案例

1. 找一個 Steam 商店頁標示過「off-topic review activity」的遊戲。
2. 用同一段日期區間抓兩次：`filter_offtopic_activity` 設 `true` 一次、設 `false` 一次，比較兩次的差異。
3. 看差異的那批評論在時間爆發、文字相似度和 `num_reviews` 上是不是群聚。

**通過標準：** 找到至少 1 個案例，`false` 那次多出 ≥ 100 則評論，而且負面比例明顯比較高。這個案例可以變成 README 的第四個任務。

### T12 · Cloud Run 上的速度和冷啟動

1. 把兩個 Hugging Face 模型放進 image，部署成 2 vCPU / 4 GiB。
2. 送 1,000 則 HN 留言，記錄冷啟動時間和推論時間。
3. 同一批留言再用 VADER 和 `gpt-5-nano` 各跑一次，記錄時間和 token 用量。

**通過標準：**
- 冷啟動加推論在 90 秒內。
- LLM 每 1,000 則低於 0.05 美元。

沒通過的話，改用 ONNX 或升到 4 vCPU。

### T13 · 模型在 demo 領域的準確度

1. 用 2.4 節的自建 200 則跑 cardiffnlp、VADER、LLM 三種方法。
2. 用 TweetEval test 確認 cardiffnlp 的分數跟模型卡接近。

**通過標準：**
- 自建集上的 macro-F1 ≥ 0.65。
- 兩位標註者的 kappa ≥ 0.6。
- 列出最常見的 3 種錯誤，例如反諷、加密貨幣詐騙的「感謝文」被判成正面。

### T14 · 情緒能不能幫忙分辨協同群組

1. 拿 T4 的詐騙案例和 Collusion Scam 資料，比較協同群組和一般留言者的情緒分布。
2. 把「群組內情緒一致度」加進 T9 評分模型的特徵，看偽陽性率不變的情況下，抓到率有沒有提升。

**通過標準：** 抓到率有提升，或者至少能說明為什麼沒有。兩種結果都可以寫進 DESIGN.md。

### T15 · YouTube 政策確認

1. 讀完開發者政策 III.E.4.h 和政策指南的「Unacceptable metrics」段落，兩人各自寫下解讀。
2. 決定 YouTube 的情緒結果要怎麼呈現：只顯示單則分類和群組比較，加上「這是 Comment Radar 的分析」標示，不給頻道打分。
3. 如果有疑問，問助教，或在 DESIGN.md 的 Risks 段落說明。

**通過標準：** 寫好一段呈現規則，並在 12/1 提案前定案。

---

## 5. 查證來源

**政策與風險**
- [YouTube API Services 開發者政策](https://developers.google.com/youtube/terms/developer-policies)
- [YouTube 開發者政策指南](https://developers.google.com/youtube/terms/developer-policies-guide)
- [Perspective API](https://perspectiveapi.com/)
- [Google 服務條款](https://policies.google.com/terms?hl=en)

**資料來源**
- [Hacker News Firebase API](https://github.com/HackerNews/API)
- [HN Search API（Algolia）](https://hn.algolia.com/api)
- [Y Combinator Legal](https://www.ycombinator.com/legal/)
- [Steam GetReviews（已淘汰）](https://partner.steamgames.com/doc/store/getreviews)
- [Steam IUserReviewsService](https://partner.steamgames.com/doc/webapi/IUserReviewsService)
- [Steam Web API Terms](https://steamcommunity.com/dev/apiterms)
- [Mastodon statuses/context](https://docs.joinmastodon.org/methods/statuses/#context)
- [Mastodon Account 實體](https://docs.joinmastodon.org/entities/Account/)
- [Mastodon 速率限制](https://docs.joinmastodon.org/api/rate-limits/)
- [Mastodon 站台設定](https://docs.joinmastodon.org/admin/config/)
- [Lisker & Mihaljević 2025：Mastodon 研究的資料倫理](https://arxiv.org/html/2505.07606v1)
- [Lemmy API 說明](https://join-lemmy.org/docs/contributors/04-api.html)
- [Stack Exchange 速率限制](https://api.stackexchange.com/docs/throttle)
- [Stack Exchange 驗證](https://api.stackexchange.com/docs/authentication)
- [Disqus API](https://disqus.com/api/docs/)
- [Disqus threads/listPosts](https://disqus.com/api/docs/threads/listPosts/)
- [GitHub REST API 速率限制](https://docs.github.com/en/rest/using-the-rest-api/rate-limits-for-the-rest-api)
- [YouTube liveChatMessages.list](https://developers.google.com/youtube/v3/live/docs/liveChatMessages/list)
- [YouTube 額度表](https://developers.google.com/youtube/v3/determine_quota_cost)
- [Twitch Chat](https://dev.twitch.tv/docs/chat/)
- [Threads keyword search](https://developers.facebook.com/docs/threads/keyword-search)
- [Threads 回覆](https://developers.facebook.com/docs/threads/retrieve-and-manage-replies/replies-and-conversations)
- [TikTok Research API](https://developers.tiktok.com/products/research-api/)
- [TikTok 留言端點](https://developers.tiktok.com/doc/research-api-specs-query-video-comments)
- [X API 價格](https://docs.x.com/x-api/getting-started/pricing)
- [Google Play Reply to Reviews API](https://developers.google.com/android-publisher/reply-to-reviews)
- [google-play-scraper（Python）](https://github.com/JoMingyu/google-play-scraper)
- [Telegram api_id](https://core.telegram.org/api/obtaining_api_id)
- Reddit Responsible Builder Policy：[說明頁](https://support.reddithelp.com/hc/en-us/articles/42728983564564-Responsible-Builder-Policy)（對抓取工具回 403，沒讀到原文）、[r/redditdev 公告](https://www.reddit.com/r/redditdev/comments/1oug31u/introducing_the_responsible_builder_policy_new/)（只從鏡像站讀到）

**資料集**
- [TweetEval](https://github.com/cardiffnlp/tweeteval)
- [GoEmotions](https://github.com/google-research/google-research/tree/master/goemotions)
- [Sentiment140](https://cs.stanford.edu/people/alecmgo/trainingandtestdata.zip)
- [Amazon Reviews 2023](https://amazon-reviews-2023.github.io/)
- [Yelp Open Dataset](https://business.yelp.com/data/resources/open-dataset/)
- [SenTube（LREC 2014）](https://aclanthology.org/L14-1188/)
- [CVAT（NAACL 2016）](https://aclanthology.org/N16-1066/)
- [Hugging Face datasets 4.0.0 release notes](https://github.com/huggingface/datasets/releases/tag/4.0.0)
- [Dey et al. 2024：協同帳號與情緒](https://arxiv.org/abs/2402.05873)
- [Shafin & Ahmed 2025：國家級影響力行動的情緒](https://arxiv.org/abs/2505.07212)

**模型與 API**
- [cardiffnlp/twitter-roberta-base-sentiment-latest](https://huggingface.co/cardiffnlp/twitter-roberta-base-sentiment-latest)
- [j-hartmann/emotion-english-distilroberta-base](https://huggingface.co/j-hartmann/emotion-english-distilroberta-base)
- [SamLowe/roberta-base-go_emotions](https://huggingface.co/SamLowe/roberta-base-go_emotions)
- [cardiffnlp/twitter-roberta-base-hate-latest](https://huggingface.co/cardiffnlp/twitter-roberta-base-hate-latest)
- [VADER](https://github.com/cjhutto/vaderSentiment)
- [Google Cloud Natural Language 價格](https://cloud.google.com/natural-language/pricing)
- [OpenAI API 價格](https://developers.openai.com/api/docs/pricing)
- [OpenAI Moderation](https://developers.openai.com/api/docs/guides/moderation)
- [Gemini API 價格](https://aistudio.google.com/docs/pricing)
- [Cloud Run 配額與限制](https://docs.cloud.google.com/run/quotas)
