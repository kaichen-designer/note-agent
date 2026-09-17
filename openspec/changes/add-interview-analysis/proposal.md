## Why

目前的錄音管線只支援單一種輸出格式：把逐字稿整理成「摘要 / 重點 / 行動項目」寫進 Notion 會議筆記，逐字稿全文只以一整段折疊區塊附上，沒有段落層級的引用。使用者訪談的分析需求不同——需要「痛點、亮點、訪談摘要、使用者使用習慣」，而且每個分析點都要能回溯到逐字稿裡實際講出這句話的時間點，作為佐證。現有管線無法區分這兩種錄音類型，也沒有機制在逐字稿裡保留可引用的時間戳段落。

## What Changes

- 新增獨立的 `INTERVIEW_WATCH_FOLDER_PATH` 設定，平行於現有 `WATCH_FOLDER_PATH`，兩個資料夾各自維護獨立的掃描快照與處理狀態,互不影響。訪談資料夾沒有待處理檔案時，會議資料夾的處理完全不受影響——不需要額外的「模式切換」狀態機。
- 單次掃描若在訪談資料夾中發現多篇待處理影片，pipeline log 要明確標註待處理篇數（例如「本次有 3 篇訪談待分析」），方便使用者知道這次會產生多篇訪談分析。
- 本地轉錄步驟在被要求保留段落時間戳時，回傳帶 `start`/`end` 秒數的逐句片段（而不是只回傳現有拼接後的純文字），供訪談分析引用；這個行為只在訪談模式下啟用，不影響會議路徑既有的輸出格式與效能。
- 新增訪談專用的 Claude structuring 邏輯，產出「訪談摘要、痛點、亮點、使用者使用習慣」，且每一點都必須附帶它所引用的逐字稿時間戳與原句。
- 新增訪談專用的 Notion 頁面組裝邏輯：每個痛點/亮點/習慣條目下方掛一個引用區塊，格式為「[MM:SS]「使用者原話」」；分類標籤新增「訪談」選項。
- 主管線新增依來源資料夾分流的路由邏輯：來自 `WATCH_FOLDER_PATH` 的檔案走現有會議處理路徑，來自 `INTERVIEW_WATCH_FOLDER_PATH` 的檔案走新的訪談處理路徑，兩者共用既有的穩定性偵測、去重、失敗重試、成功歸檔邏輯。
- （真實環境驗證後追加）時間戳比對容忍 floor 捨入誤差，並在數字比對失敗時改用引用原句的文字去比對逐字稿段落，還原時間戳，取代原本純數字比對過於嚴格導致部分分析點遺失時間戳的問題。
- （真實環境驗證後追加）當語者分離（`SPEAKER_DIARIZATION_ENABLED`）與訪談時間戳保留同時啟用時，逐字稿與 Notion 引用區塊的時間戳一併標示語者（例如「[19:56][語者 A]」），沿用既有語者分離功能已產出的字母標籤，不重新設計語者辨識邏輯；未啟用語者分離時格式不變。

## Capabilities

### New Capabilities

- `interview-analysis`: 訪談影片的偵測、待處理篇數的 log 提示、訪談專用的 Claude 結構化分析（摘要/痛點/亮點/使用習慣)、以及帶時間戳引用的 Notion 頁面輸出。

### Modified Capabilities

- `recording-ingestion`: 從只支援單一 watch folder，擴充為支援第二個獨立設定、獨立狀態的 watch folder（訪談),兩者套用相同的穩定性偵測/去重/重試/歸檔規則但狀態互不共用。
- `local-transcription`: 新增「依呼叫端要求保留逐句時間戳」的能力，供訪談模式在結構化分析時引用原文段落時間點；會議路徑的既有純文字輸出行為不變。

## Impact

- Affected specs: `interview-analysis`（新增)、`recording-ingestion`（修改)、`local-transcription`（修改)
- Affected code:
  - New: `src/interview_agent.py`
  - Modified: `src/main.py`, `src/watcher.py`, `src/transcribe.py`, `src/_transcribe_worker.py`, `src/notion_schema.py`, `config/.env.example`
