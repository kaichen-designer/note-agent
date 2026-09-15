# 錄音筆記 Agent

自動將手機錄音轉換成結構化筆記並歸檔到 Notion 的本地端 AI Agent。

錄音 → 上傳 Google Drive → 自動轉錄(本機 GPU)→ Claude 整理 → Notion 筆記,全程無需人工介入。

## 整體流程

```
iPhone 語音備忘錄錄音
   │  手動分享上傳(語音備忘錄 → 分享 → 雲端硬碟)
   ▼
Google Drive「Notion Meeting Note Agent Recording」資料夾
   │  Google Drive for Desktop 自動同步到本機 G:\我的雲端硬碟\...
   ▼
排程輪詢(Windows 工作排程器,每 15 分鐘)或手動觸發(run_now.bat)
   │  連續兩次掃描檔案大小/時間不變 → 確認雲端同步完成(避免處理半個檔案)
   ▼
狀態檢查(data/state.json:已成功的跳過、失敗的重試、超過 3 次的標記人工處理)
   ▼
本機 GPU 轉錄:faster-whisper large-v3 + VAD 靜音過濾
   │  獨立 Python 3.11 虛擬環境(.venv-transcribe),錄音內容不上傳雲端
   │  即時進度寫入 data/transcribe_progress.json(progress.bat 可看進度條)
   ▼
Claude API 結構化(claude-sonnet-5,強制 tool-call 回傳固定 JSON)
   │  產出:標題/摘要/重點/行動項目/分類標籤(會議・靈感・學習・其他)
   ▼
notion-client 寫入 Notion「錄音筆記Agent」資料庫
   │  屬性:標題、日期、來源檔名、分類標籤(multi-select)、狀態(select,預設「已整理」)
   │  內容:摘要 → 重點條列 → 行動項目 → Toggle 收合的完整逐字稿
   ▼
音檔自動歸檔到「已處理」子資料夾(同步回雲端與手機)
```

## 專案結構

| 檔案 | 職責 |
|---|---|
| `src/main.py` | 單一進入點:掃描→轉錄→結構化→寫入→歸檔;單一實例鎖防併發 |
| `src/watcher.py` | 資料夾掃描、兩次掃描穩定性檢查、重試清單 |
| `src/state_store.py` | 本地狀態追蹤(JSON):去重、失敗重試計數、逐字稿保留 |
| `src/transcribe.py` | 以子行程呼叫轉錄虛擬環境,錯誤不外拋 |
| `src/_transcribe_worker.py` | 在 .venv-transcribe 內執行 faster-whisper,回報進度 |
| `src/notion_agent.py` | Claude 結構化 + Notion 頁面建立(容錯解析、截斷防護) |
| `src/setup_notion_database.py` | 一次性:建立/補齊 Notion 資料庫 schema |
| `src/show_progress.py` + `progress.bat` | 即時轉錄進度條 |
| `run_now.bat` | 手動立即執行一輪(與排程共用同一邏輯) |
| `config/.env.example` | 設定範本(實際設定在 `.env`,不進版控) |
| `openspec/` | Spectra 規格與變更紀錄(specs = 現行規格,changes/archive = 開發史) |

## 關鍵設計決策(為什麼這樣做)

1. **排程輪詢而非即時監控**:雲端同步是多步驟寫入,檔案事件觸發時可能還在下載中;輪詢搭配「兩次掃描穩定才處理」天生免疫此問題,且無常駐程序維運負擔
2. **本地 faster-whisper 而非雲端 STT**:RTX 3500 Ada (12GB VRAM) 跑 large-v3 綽綽有餘;免費、錄音內容不出本機
3. **獨立轉錄虛擬環境**:主環境 Python 3.14 太新,ctranslate2 無相容套件,轉錄跑在 Python 3.11 的 .venv-transcribe,主程式以子行程呼叫
4. **Notion 寫入用 Internal Integration Token 而非 MCP**:MCP 的 OAuth 連線掛在互動式 session 上,無人值守排程腳本無法可靠重用;Integration Token 是靜態金鑰,完全免驗證負擔
5. **結構化交給 Claude 自主判斷**:分類標籤限定固定清單(在 prompt 的 tool schema 中以 enum 約束),但內容判斷交給模型;寫入 Notion 的動作由確定性程式碼執行
6. **逐字稿永遠保留**:頁面裡收在 Toggle 區塊;Notion 寫入失敗時保留在狀態檔,重試不需重新轉錄

## 實戰中發現並修復的問題(教訓紀錄)

| 問題 | 根因 | 修復 |
|---|---|---|
| 手動+排程同時執行,重複處理同一檔案 | 狀態只在處理完成後寫入,擋不住執行中的競態 | 單一實例鎖(pipeline.lock),第二個實例直接跳過 |
| run_now.bat 執行中關閉視窗導致轉錄中斷 | 子行程隨主控台一起被殺 | 排程改用 pythonw 無視窗執行;失敗自動重試機制兜底 |
| 筆記缺「重點/行動項目」但無錯誤(一) | max_tokens=2048 太小,長中文輸出被截斷 | 提高到 8192,且截斷視為失敗觸發重試,不靜默接受 |
| 筆記缺「重點/行動項目」但無錯誤(二) | 模型把清單欄位輸出成 `<item>` 標籤字串而非陣列 | 解析器支援拆標籤與多行文字 |
| 長會議轉錄過慢(41分鐘音檔跑37分鐘) | 逐段解碼含大量靜音與低信心重解 | VAD 靜音過濾(同檔案降至 8 分鐘);GPU 勿多工搶佔 |
| ctranslate2 找不到 CUDA DLL | pip 版 cuBLAS/cuDNN 不在系統搜尋路徑,且編譯模組不認 add_dll_directory | worker 啟動時把 nvidia/*/bin 加進 PATH |

## 日常操作

- **正常使用**:錄音 → 分享到 Drive 資料夾 → 等 15 分鐘排程自動處理(什麼都不用做)
- **立刻處理**:雙擊 `run_now.bat`(執行中勿關視窗;若排程正在跑會自動跳過)
- **看轉錄進度**:雙擊 `progress.bat`
- **查執行紀錄**:`data/pipeline.log`
- **調整排程間隔**:工作排程器 → RecordingNoteAgent → 觸發程序
- **關閉 VAD**(小聲說話被誤判漏轉時):`.env` 改 `VAD_FILTER=false`
- **修改分類標籤**:`src/notion_schema.py` 的 `CATEGORY_TAG_OPTIONS`(Notion 資料庫選項需同步增加)
- **某檔案卡在「需人工介入」**:修好問題後刪除 `data/state.json` 中該筆記錄,下輪自動重跑

## 設定需求(.env)

| 變數 | 說明 |
|---|---|
| `WATCH_FOLDER_PATH` | 雲端同步資料夾的本機路徑 |
| `ANTHROPIC_API_KEY` | Claude API 金鑰(console.anthropic.com,需儲值,與訂閱分開計費) |
| `NOTION_API_KEY` | Notion Internal Integration Token(notion.so/my-integrations,免費;資料庫頁面需 Connect 給該 integration) |
| `NOTION_DATABASE_ID` | 筆記資料庫 ID(由 setup_notion_database.py 產生) |
| `WHISPER_MODEL_SIZE` | 預設 large-v3 |
| `VAD_FILTER` | 預設 true |
| `MAX_RETRY_COUNT` | 預設 3 |
| `SPEAKER_DIARIZATION_ENABLED` | 語者分離開關,預設 `false`(見下方「語者分離」說明) |
| `HUGGINGFACE_TOKEN` | `SPEAKER_DIARIZATION_ENABLED=true` 時才需要,語者分離模型下載用 |

## 語者分離(標註逐字稿裡「誰說的話」)

多人討論的逐字稿預設沒有語者標記。需要分辨語者的錄音(例如訪談)可以手動開啟:

1. 到 [pyannote/speaker-diarization-3.1](https://huggingface.co/pyannote/speaker-diarization-3.1) 與 [pyannote/segmentation-3.0](https://huggingface.co/pyannote/segmentation-3.0) 登入 Hugging Face 帳號並接受授權條款(一次性,兩個都要接受)
2. 到 [huggingface.co/settings/tokens](https://huggingface.co/settings/tokens) 建立一組 token(read 權限即可),填入 `.env` 的 `HUGGINGFACE_TOKEN`
3. 把 `.env` 的 `SPEAKER_DIARIZATION_ENABLED` 改成 `true`,跑一次 `run_now.bat` 處理要分析的錄音,跑完想關掉再改回 `false`

啟用後,逐字稿裡每個語句片段會加上 `[語者 A]`、`[語者 B]` 這樣的前綴(依語者第一次開口的順序編號),**不是真實姓名**——語者分離只能判斷「這句和上一句是不是同一個人講的」,無法識別身分,標籤也是自動偵測,可能因為聲音重疊、背景雜訊等因素而誤判或錯亂,不保證逐字精準。

這個開關是「執行當下」生效,不是針對單一檔案:如果開著的時候 watch 資料夾還有其他待處理的錄音,那些也會一起套用語者分離,並不會自動只挑訪談檔案。

## 已知限制與未來方向

- **語者分離不含身分辨識**:標籤只有「語者 A/B/C...」,無法對應到真實姓名,行動項目的負責人歸屬仍靠上下文推測(細節見上方「語者分離」說明)
- **語音備忘錄需手動分享上傳**:Apple 不開放自動同步到第三方;可考慮 iOS 捷徑做一鍵錄音+上傳
- **超長音檔未切割**:1 小時以上的錄音理論上可跑,但時間與記憶體未實測;必要時再開 change
- **成本**:轉錄免費(本地);Claude 結構化每篇約 $0.01~0.05 美元;Notion API 免費;語者分離同樣在本地執行,免費,但會延長處理時間

## 開發流程紀錄

本專案採 Spectra 規格驅動開發,完整開發史在 `openspec/changes/archive/`:

- `2026-07-05-recording-to-notion-agent`:主體(21 任務,3 capabilities、13 條需求)
- `2026-07-05-add-vad-acceleration`:VAD 靜音過濾加速
- `2026-07-06-fix-structuring-truncation`:結構化截斷防護與解析容錯

現行規格:`openspec/specs/`(recording-ingestion / local-transcription / notion-note-sync)
