## 1. 專案環境設定

- [x] 1.1 建立 `requirements.txt`,列出主流程所需套件(`anthropic`、`notion-client`、`python-dotenv`等),確保 `pip install -r requirements.txt` 可在一般環境成功安裝。驗證:在乾淨虛擬環境執行安裝指令,無錯誤結束
- [x] 1.2 [P] 建立獨立的本地轉錄虛擬環境(Python 3.11 或 3.12)並安裝 `faster-whisper`,對應設計文件「轉錄採用本地 faster-whisper(large-v3)而非雲端 Whisper API」的決策。驗證:在該虛擬環境執行 `python -c "import faster_whisper"` 不報錯
- [x] 1.3 [P] 建立 `config/.env.example`,列出 `WATCH_FOLDER_PATH`、`ANTHROPIC_API_KEY`、`NOTION_DATABASE_ID` 等必要設定項與說明註解。驗證:複製為 `.env` 並填入測試值後,主程式可正確讀取這些環境變數

## 2. Recording Ingestion(錄音偵測與去重)

- [x] 2.1 實作 `src/state_store.py`,提供讀寫本地狀態記錄(檔案識別、狀態pending/success/failed、最後嘗試時間、重試次數)的介面,支援 Duplicate Processing Prevention 需求。驗證:撰寫測試以相同檔案識別呼叫兩次寫入,確認狀態正確覆蓋且可查詢
- [x] 2.2 實作 `src/watcher.py` 的 Stable File Detection:掃描 `WATCH_FOLDER_PATH`,比對連續兩次掃描的檔案大小與修改時間,僅回傳穩定不變的檔案清單。驗證:用測試腳本模擬兩次掃描回傳不同大小與相同大小的情境,確認回傳結果符合穩定判斷邏輯
- [x] 2.3 在 `src/watcher.py` 整合 Failed File Retry With Limit:讀取 state_store 中狀態為 failed 且重試次數低於上限的檔案並加入待處理清單;達到上限的檔案標記為需人工介入且不再自動加入。驗證:建立一筆重試次數已達上限的測試資料,執行掃描後確認該檔案未被加入待處理清單
- [x] 2.4 實作 `src/main.py` 作為單一進入點,串接掃描、轉錄、結構化寫入、狀態更新,並建立 `run_now.bat` 呼叫同一支 `main.py`,實現 Dual Trigger Entry Points,對應設計文件「手動觸發與排程共用同一入口」的決策。驗證:分別用命令列與雙擊 `run_now.bat` 執行,確認兩者觸發完全相同的處理流程與輸出log

## 3. Local Transcription(本地端語音轉逐字稿)

- [x] 3.1 [P] 實作 `src/transcribe.py`,以子行程呼叫獨立轉錄虛擬環境中的 faster-whisper(large-v3, GPU加速)將音檔轉為逐字稿文字,實現 Local GPU-Accelerated Transcription 需求。驗證:提供一段已知內容的測試音檔,確認輸出逐字稿包含預期關鍵字
- [x] 3.2 在 `src/transcribe.py` 加入 Transcription Failure Handling:轉錄過程發生例外時(如毀損或不支援格式的音檔),回傳結構化錯誤而不拋出未捕捉例外,由呼叫端寫入 state_store 的 failed 狀態並繼續處理下一個檔案。驗證:提供一個毀損的測試音檔,確認 `main.py` 執行後該筆記錄狀態為 failed 且流程繼續處理其餘檔案

## 4. Notion Note Sync(Claude 結構化 + notion-client 寫入)

- [x] 4.1 實作一次性 setup 腳本 `src/setup_notion_database.py`,使用 `notion-client`(以 `NOTION_API_KEY` Internal Integration Token 驗證)實現 Database Schema Provisioning:自動建立筆記資料庫並設定日期(date)、來源檔名(rich_text)、分類標籤(multi-select,固定清單)、狀態(select:待處理/已整理/已完成)四個屬性,執行完成後輸出資料庫 ID,對應設計文件「Notion 資料庫本身由一次性 setup 腳本自動建立,而非要求使用者手動在 Notion 介面設定」的決策。驗證:在尚未有資料庫的 Notion workspace 執行該腳本,確認新資料庫出現且四個屬性與其選項清單皆正確,並確認腳本輸出的資料庫 ID 可直接填入 `.env` 的 `NOTION_DATABASE_ID`
- [x] 4.2 驗證主流程(`main.py`)不會在每次排程或手動觸發時重複呼叫資料庫建立邏輯,確認 setup 腳本與主流程是各自獨立的進入點。驗證:在資料庫已存在的情況下執行 `run_now.bat` 多次,確認過程中沒有呼叫建立資料庫的 API,只有建立頁面的呼叫
- [x] 4.3 實作 `src/notion_agent.py` 的結構化部分,對應設計文件決策「結構化使用 Claude API 直接呼叫,Notion 寫入改用 `notion-client` + Internal Integration Token,而非 Agent SDK + Notion MCP」:呼叫 Claude API(`anthropic` 套件),將逐字稿、來源檔名、日期與固定分類標籤清單交給 Claude,實現 Agent-Driven Note Structuring:由 Claude 自行產生標題、摘要、重點、行動項目並選擇分類標籤,回傳結構化 JSON。驗證:提供一段測試逐字稿,確認回傳的 JSON 包含標題、摘要、重點、行動項目與一個屬於固定清單的分類標籤
- [x] 4.4 在 `src/notion_agent.py` 中用 `notion-client` 實現 Notion Page Creation With Required Properties:呼叫 Notion API 建立頁面時設定日期、來源檔名、分類標籤(multi-select)、狀態(select,預設「已整理」)四個屬性。驗證:執行後於 Notion 資料庫檢視新頁面,四個屬性皆有正確值
- [x] 4.5 在頁面內容產生邏輯中實現 Full Transcript Preserved In A Collapsed Section:用 `notion-client` 的 block API 將完整逐字稿放入 Toggle 收合區塊,對應設計文件「逐字稿以 Toggle 區塊收合保留在頁面內容中」的決策。驗證:開啟新建立的 Notion 頁面,確認逐字稿預設收合、展開後內容與轉錄結果一致
- [x] 4.6 實作 Notion Write Failure Handling:當 `notion-client` 寫入 Notion 失敗時(例如 Integration Token 失效或網路錯誤),`main.py` 將該筆記錄標記為 failed 但保留已產生的逐字稿,下次重試時不重新轉錄。驗證:模擬 Notion API 呼叫失敗(如提供無效的資料庫ID),確認狀態記錄為 failed,且下次成功重試時直接使用保留的逐字稿而非重新轉錄

## 5. 排程設定與端到端驗證

- [x] 5.1 設定 Windows 工作排程器,每 15-30 分鐘呼叫一次 `src/main.py`,對應設計文件「觸發方式採用排程輪詢而非即時監控」的決策。驗證:於工作排程器的執行紀錄中確認排程有按預期間隔觸發並成功結束
- [x] 5.2 端到端驗證單一資料庫寫入完整流程,對應「單一 Notion 資料庫,以屬性分類而非多資料庫」決策:放入一個測試音檔到 watch 資料夾,執行 `run_now.bat`,確認 Notion 資料庫出現一則新頁面且屬性與內容皆正確。驗證:人工檢視 Notion 頁面內容與屬性
- [x] 5.3 驗證 Duplicate Processing Prevention 端到端行為:對同一個已成功處理的檔案重複執行整個流程。驗證:確認 Notion 未產生重複頁面,且 state_store 記錄該檔案狀態仍為 success

## 6. 轉錄進度顯示(Transcription Progress Reporting)

- [x] 6.1 在 `src/_transcribe_worker.py` 實現 Transcription Progress Reporting 的寫入端:轉錄過程中逐段將來源檔名、音檔總長、已處理秒數、百分比寫入 `data/transcribe_progress.json`(含模型載入中/轉錄中/完成三種階段),`src/transcribe.py` 與 `src/main.py` 傳遞進度檔路徑。驗證:用測試音檔執行轉錄,確認進度檔內容隨轉錄推進更新且最終標記完成
- [x] 6.2 建立進度檢視器 `src/show_progress.py` 與可雙擊的 `progress.bat`:即時顯示目前轉錄中的檔案與進度條;無進行中轉錄時顯示閒置狀態而非過期進度。驗證:轉錄進行中開啟檢視器可看到百分比前進;轉錄結束後開啟顯示閒置狀態

## 7. 處理完成自動歸檔(Processed File Archiving)

- [x] 7.1 在 `src/main.py` 實現 Processed File Archiving:Notion 頁面建立成功後將音檔搬移到 watch 資料夾的「已處理」子資料夾(同名時加數字後綴);失敗的檔案留在原位;搬移失敗只記警告不影響成功狀態;確認 watcher 掃描不會撿到子資料夾內的檔案。驗證:單元測試涵蓋成功搬移、失敗不搬移、同名後綴三種情境,並確認既有掃描測試不受影響
