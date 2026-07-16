## Why

使用者累積大量手機錄音(會議、靈感、學習筆記),目前完全依賴手動聽錄音、整理重點、再貼進 Notion,耗時且容易遺漏或拖延。需要一個自動化 Agent,從錄音檔產生到系統性歸檔進 Notion 的整個流程都自動完成,只保留必要的人工檢視。

## What Changes

- 新增本機排程程式,掃描手機錄音 App 同步到本機的雲端硬碟資料夾,用「連續兩次掃描檔案大小/修改時間不變」判斷雲端同步已完成,避免處理下載到一半的音檔
- 新增本地狀態追蹤(JSON/SQLite),記錄每個錄音檔的處理狀態(未處理/成功/失敗待重試),避免重複處理同一檔案
- 新增手動觸發入口(可雙擊執行的批次腳本),與排程呼叫同一套處理邏輯與狀態追蹤,不需要等待排程週期
- 整合本地端 faster-whisper(large-v3 模型,GPU 加速)做語音轉逐字稿,錄音內容不上傳雲端、不需額外的語音轉文字 API 費用
- 新增結構化模組:輸入逐字稿後,直接呼叫 Claude API 判斷標題、摘要、重點、行動項目、分類標籤;寫入 Notion 則使用 `notion-client` 搭配 Notion Internal Integration Token 呼叫官方 API 建立頁面(實作階段驗證 Claude Agent SDK + Notion MCP 在無人值守排程場景下的 OAuth 可重用性有風險,改採此更可預測的方案,詳見 design.md)
- 新增單一 Notion 筆記資料庫的屬性結構:日期、來源檔名、分類標籤(multi-select)、狀態(select:待處理/已整理/已完成);完整逐字稿以 Toggle 收合區塊保留在頁面內容中,避免資訊遺失
- 新增一次性 setup 腳本,透過 Notion MCP 自動建立上述筆記資料庫並設定四個屬性 schema,使用者不需手動在 Notion 介面建立資料庫或逐一設定屬性選項

## Capabilities

### New Capabilities

- `recording-ingestion`: 掃描同步資料夾、確認雲端同步完成、去重與重試狀態追蹤,並提供排程與手動雙入口觸發處理
- `local-transcription`: 使用本地 faster-whisper 將錄音檔轉換成逐字稿,不依賴雲端語音轉文字服務
- `notion-note-sync`: 透過 Claude API 將逐字稿結構化(標題/摘要/重點/行動項目/分類標籤),並透過 `notion-client` 寫入 Notion 筆記資料庫

### Modified Capabilities

(none - 全新專案,沒有既有能力被修改)

## Impact

- Affected specs: `recording-ingestion` (new), `local-transcription` (new), `notion-note-sync` (new)
- Affected code:
  - New:
    - src/watcher.py
    - src/state_store.py
    - src/transcribe.py
    - src/notion_agent.py
    - src/setup_notion_database.py
    - src/main.py
    - run_now.bat
    - requirements.txt
    - config/.env.example
