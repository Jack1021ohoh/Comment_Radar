# 執行步驟 Roadmap

> 2026-11-24 版。從今天到 12/10 報告，每一步要做什麼、做完的標準是什麼。
> 相關文件：[project-brief.md](project-brief.md)（做什麼）、[data-inventory.md](data-inventory.md)（資料和 key）、[prototype.html](prototype.html)（畫面）。
> 組員代號 A / B / C，請自己對應。

---

## 總覽

| 階段 | 日期 | 目標 | 做完的標準 |
|---|---|---|---|
| 0 · 開工 | 11/24–11/25 | repo、分工、key | 三個 key 都能用 |
| 1 · 資料取得 | 11/24–11/27 | 所有資料抓到、存好 | Cloud Run 上呼叫得到每個來源；demo 案例已快取 |
| 2 · 標註和 baseline | 11/26–11/30 | 有標準答案、有第一版分數 | 300 則標完；每個模型都有分數；決定用哪些模型 |
| 3 · 做核心功能 | 12/1–12/5 | agent 能跑完整流程 | 線上網址貼網址 → 5 分鐘內出報告 |
| 4 · eval 和改進 | 12/4–12/7 | 量化成效、改到最好 | eval 一鍵跑完；hill-climbing 紀錄 |
| 5 · 交件 | 12/7–12/9 | README、DESIGN.md、submission.json | 12/9 23:59 前繳交 |
| 6 · 報告 | 12/10 | 4 分鐘 demo + 1 分鐘問答 | 有一份已經跑完的結果當備用 |

---

## 階段 0 · 開工（11/24–11/25）

1. **確認組員人數** → 決定要用幾個課程概念：3 人至少 5 個，4 人至少 6 個，而且要跨 2 個類別。
2. **走一般作業路線，不用 Moonshot。** 我們的專案是部署在 Cloud Run 的 agent，符合一般規定，不需要在 12/1 前提 Moonshot。YouTube 政策有疑問的話，在 Ed 開私訊問助教。
3. **建 GitHub repo**（private 可以）：
   - Settings → Collaborators → 加入 `codeboi07`、`bhuvighosh3`、`nniishhh`、`x`。
   - 先放空的 `README.md`、`submission.json`、`.gitignore`（含 `.env`、`data/raw/`）。
4. **各自開始手寫 DESIGN.md 的草稿。** 規定要「Start it before you build」，而且不能用 AI，老師會用 Pangram 檢查。
5. **申請 key**，照 [data-inventory.md 附錄](data-inventory.md#附錄key-的申請) 做：

| 誰 | 做什麼 |
|---|---|
| A | YouTube API key（附錄 A）、Google Cloud 專案、billing |
| B | Bluesky 帳號 + App Password（附錄 B） |
| 每個人 | 自己的 api.data.gov key（附錄 C）、本機 `.env` |
| C | OpenAI key（附錄 E），或確認課堂有沒有提供 |

**做完的標準：** 附錄裡的三個測試指令在每個人的電腦上都回 200。

---

## 階段 1 · 資料取得（11/24–11/27）

### 1.1 先把 Cloud Run 和持續部署設好（A）

越早設好越好。之後每次 push 都會自動部署，也能測從 Cloud Run 呼叫 API 會不會被擋。

1. repo 裡放一個最小的服務：一個 `/health` 端點，加上一個呼叫 D1、D2、D3 的 `/probe` 端點。
2. Cloud Run → **Create service** → **Continuously deploy from a repository** → **Set up with Cloud Build** → 連 GitHub、選 repo、branch `^main$`、build type 選 **Dockerfile**。
3. 把 key 放進 Secret Manager，掛成環境變數（[data-inventory.md 附錄](data-inventory.md#key-放哪裡)）。
4. 跑 **T16**：從 Cloud Run 呼叫 YouTube、Bluesky、FCC，各 10 次。

**做完的標準：** 三個來源從 Cloud Run 都回 200。Bluesky 被擋的話，改成事先抓好並快取。

### 1.2 下載標註資料集（C）

1. 寫 `scripts/download_datasets.sh`，把 [data-inventory.md](data-inventory.md) 裡 D5、D6、D7、D8 的下載指令集中在一起。
2. 打開每份資料，確認三件事：
   - VAST 的 `label` 0/1/2 分別對應 pro、con、neutral 的哪一個。
   - GroNLP 主觀性模型的 `LABEL_0`、`LABEL_1` 哪個是 SUBJ（拿 CheckThat 的資料跑幾句就知道）。
   - CheckThat! 2025 test 有沒有和 2023 的訓練資料重疊。
3. 每份資料寫三行筆記：欄位、筆數、要拿來測什麼。

**做完的標準：** 一個指令就能把所有資料下載到 `data/`。

### 1.3 找 demo 案例並馬上快取（A、B）

留言隨時可能被刪，**找到就立刻抓下來存檔**。

| 案例 | 要找什麼 | 用在哪裡 | 誰 |
|---|---|---|---|
| YouTube 有協同 | 3–5 支政治影片，底下有大量相似的模板留言 | 評分者任務 1 | A |
| YouTube 沒協同 | 1–2 支直播聽證會或首播，留言自然暴增 | 評分者任務 2（測誤判） | A |
| Bluesky | 2–3 則政治人物或記者的貼文，回覆 50 則以上 | 第二個平台 | B |
| FCC | 3 個已知模板各 1,000 則 + 隨機 2,000 則（T17） | 評分者任務 3、協同的標準答案 | B |

每個案例存：網址、抓取時間、原始 JSON（放 `data/raw/`）、一張截圖。

**做完的標準：** 至少 8 個案例已經存檔。

---

## 階段 2 · 標註和 baseline（11/26–11/30）

### 2.1 自建標註集（全員）

1. 寫標註指引：`subj`、`stance`、`loaded`、`sarcasm` 的定義，每個欄位附 3 個正例、3 個反例。
2. 三人一起試標 30 則，討論分歧，修改指引。
3. 從 1.3 的案例抽 300 則：YouTube 100、Bluesky 100、FCC 100。每串先寫好 `target`。
4. 兩人各自標完 300 則，算 Cohen’s kappa。目標：`subj`、`stance` ≥ 0.6，`loaded` ≥ 0.5。
5. 第三人決定分歧的部分。
6. **切成兩份：** 前 100 則用來調整，後 200 則鎖起來，只在最後算分數時使用。

YouTube 留言只存 ID 和標籤，跑 eval 時再重抓全文（30 天規定）。

### 2.2 跑第一版分數（C）

1. 在本機跑 4 個模型（[data-inventory.md M1](data-inventory.md#m1--hugging-face-模型)），對 VAST test、CheckThat! test 和自建的前 100 則算 macro F1。
2. 協同偵測先用最簡單的規則：時間爆發 + 文字相似。
   - 在 FCC 資料上算抓到率（T17）。
   - 在「沒協同」的影片上算誤判率（T7）。
3. 把所有數字記在 `eval/results.md`。這是 hill-climbing 的起點，也是 DESIGN.md 的素材。

### 2.3 速度測試（A）

在 Cloud Run（4 vCPU / 8 GiB）上用 1,000 則留言跑 4 個模型，記下冷啟動時間和每個模型的時間（T20）。

### 2.4 決策點（11/30）

| 問題 | 如果是 | 如果不是 |
|---|---|---|
| 立場模型的 F1 ≥ 0.6，而且夠快？ | 保留 NLI | 用 VAST train 微調一個立場分類器，或把立場全部交給 LLM |
| 主觀性、偏頗用字的 F1 ≥ 0.6？ | 保留本機模型 | 該欄位改由 LLM 判斷，或在報告上標「實驗性」 |
| 1,000 則能在 2 分鐘內跑完？ | 照原計畫 | 留言上限改成 500，或改用 ONNX |
| 規則版協同偵測的誤判率 ≤ 5%？ | 先用規則 | 加入帳號年齡、追蹤圈的特徵再測 |

**做完的標準：** 每個問題都有答案，寫進 `eval/results.md`。

---

## 階段 3 · 做核心功能（12/1–12/5）

照 [project-brief.md 第 3 節](project-brief.md#3-實際運行怎麼做) 的流程做。每天至少 push 一次，讓線上版本一直保持可用。

| 步驟 | 內容 | 對應的課程概念 | 誰 |
|---|---|---|---|
| 3.1 | **MCP server**（`radar_mcp/`）：`fetch_thread`、`get_accounts`、`classify_comments`、`score_coordination`、`compare_groups`。先用 stdio，用 MCP Inspector 逐一測試 | Using your own MCP Server | A |
| 3.2 | **分類流程**：4 個本機模型 → 低信心和反諷的交給 LLM，輸出固定 JSON | Structured output | C |
| 3.3 | **Orchestrator + 調查員**：每個可疑群組派一個調查員，同時執行 | Parallel fan-out | B |
| 3.4 | **辯護律師 agent**：替每個群組找無辜的解釋，證據不夠就降級 | Generator/Critic | B |
| 3.5 | **Guardrail**：擋掉點名個人、頻道分數、顯示 FCC 署名 | Guardrails | C |
| 3.6 | **網頁**：照 [prototype.html](prototype.html) 做，換成真的資料 | — | A |
| 3.7 | **資料庫**：快取抓過的資料和分析結果（Cloud Run 的檔案系統是暫時的） | — | A |

**12/3 中間檢查：** 用線上網址跑完一次評分者任務 1。跑不完就先砍功能（見最後的「落後時先砍什麼」）。

**做完的標準：** 從線上網址貼一支 demo 影片，5 分鐘內出現完整報告。

---

## 階段 4 · eval 和改進（12/4–12/7）

1. **寫 `eval/run_eval.py`**，一個指令跑完：
   - 自建的後 200 則：三個欄位的 macro F1。
   - VAST test：立場 F1，以及反諷子集的落差。
   - CheckThat! test：主觀性 F1。
   - FCC：協同的抓到率。
   - 「沒協同」的影片：誤判率。
2. **Hill-climbing：** 每改一次門檻、評分規則或模型，就重跑一次 eval，記一行：

| 日期 | 改了什麼 | 前 | 後 | 留下嗎 |
|---|---|---|---|---|
| 12/4 | 例：LLM 評分規則加入反諷例子 | stance F1 0.58 | 0.64 | ✅ |

   調整只能用前 100 則，後 200 則最後才跑。

3. **群組比較（T21）：** 協同群組和一般留言者的立場分布、偏頗比例，做卡方檢定，產出一張可以放進 README 的表。
4. **選配，有時間再做：**
   - 中文實驗性支援（中文留言交給 LLM）。
   - Tracing（Langfuse 等），多一個課程概念。

**做完的標準：** `eval/results.md` 有最終數字和至少 3 行 hill-climbing 紀錄。

---

## 階段 5 · 交件（12/7–12/9）

| 項目 | 內容 | 檢查方式 |
|---|---|---|
| `README.md` | 專案說明 + 線上網址；3 個評分者任務（確切步驟 + 會看到什麼）；每個課程概念和程式碼檔案的對照 | 找一個沒參與的人照著做一次 |
| `DESIGN.md` | **自己手寫**：User story、Design、Evaluation、Token cost、Metrics、Risks 六節 | `wc -w DESIGN.md` ≤ 1,000 |
| `submission.json` | `deploy_url` + 每個組員的 UNI | JSON 格式正確 |
| 協作者 | 4 個帳號都已加入 | Settings → Collaborators |
| 線上服務 | 用無痕視窗跑 3 個評分者任務，每個都在 5 分鐘內完成 | 計時 |
| 冷啟動 | 評分期間把 Cloud Run 的最少實例設成 1，避免模型載入太久 | Cloud Run 設定 |

DESIGN.md 的素材都在 `eval/results.md` 和 hill-climbing 紀錄裡。Risks 那節要寫「最不確定會不會成功的地方，以及結果如何」，例如反諷、YouTube 政策、Bluesky 被擋。

**12/9 23:59 前：** 由一位組員在 Courseworks 繳交 repo 網址。服務要一直開到成績公布。

---

## 階段 6 · 報告（12/10）

1. 4 分鐘，Shark Tank 風格：
   - 痛點：台灣的經驗，加上 FCC 2,000 萬則留言裡大部分是假的。
   - 現場 demo。
   - 成效數字。
   - 風險。
2. 開一個分頁放**已經跑完的結果**，現場跑太慢就切過去。
3. 錄一支備用影片，以防現場網路出問題。

---

## 落後時先砍什麼

由上往下砍，越上面越不重要：

1. 中文支援、tracing
2. Bluesky 的追蹤圈
3. 偏頗用字模型（改由 LLM 判斷）
4. 立場的本機模型（改由 LLM 判斷）
5. 辯護律師 agent（改成單一 agent 寫報告）

**絕對不能砍：** 線上可以用、3 個評分者任務跑得完、eval 數字、手寫的 DESIGN.md。

---

## 每天的檢查清單

- [ ] 今天 push 了嗎？線上版本還能用嗎？
- [ ] 新抓的 demo 案例存檔了嗎？
- [ ] 改了東西有重跑 eval 並記一行嗎？
- [ ] 有沒有 key 或 `.env` 被誤 commit？
