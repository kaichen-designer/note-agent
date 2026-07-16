## Context

全新專案,目前僅有 Spectra 鷹架,沒有既有程式碼。需求已透過 `/spectra-discuss` 討論收斂:錄音來源是手機錄音 App 同步到本機的雲端硬碟資料夾;轉錄使用本地 faster-whisper;結構化使用 Claude API,Notion 寫入使用 `notion-client` + Internal Integration Token(原提案的 Claude Agent SDK + Notion MCP 方案,在實作階段驗證後因無人值守排程場景下的 OAuth 可重用性風險而改採此方案,詳見 Decisions)。使用者機器規格:Intel i7-13800H、64GB RAM、NVIDIA RTX 3500 Ada(12GB VRAM)、已安裝 Python 3.11 與 3.14,足以支撐本地端 large-v3 模型的 GPU 加速推論。

## Goals / Non-Goals

**Goals:**

- 建立錄音檔到 Notion 筆記的端到端自動化管線
- 轉錄完全在本機執行,不依賴雲端語音轉文字 API,錄音內容不外流
- Notion 寫入透過 Agent 自主判斷結構化內容(標題/摘要/重點/行動項目/分類),不手刻固定的資料轉換程式碼
- 排程觸發與手動觸發共用同一套處理邏輯與狀態追蹤,避免雙重維護

**Non-Goals:**

- 不做即時檔案監控(watcher daemon)。雲端同步來源存在「檔案未完成同步」的問題,常駐監控在 Windows 上的維運成本也高於排程輪詢
- 不做長音檔自動切割/分段處理的完整方案,本次僅記錄為已知限制
- 不做 Notion 分類標籤的動態學習或自訂管理介面,本次分類標籤為固定清單
- 不支援多雲端硬碟/多資料夾來源組態,本次僅支援單一 watch 資料夾路徑

## Decisions

### 觸發方式採用排程輪詢而非即時監控

雲端同步用戶端寫入檔案是多步驟過程(建立暫存檔→下載中→完成後才改名/寫入完成)。用檔案系統事件式監控(例如 watchdog)偵測到「檔案建立」時,音檔可能還在下載中,會讀到不完整的內容。排程輪詢搭配「連續兩次掃描檔案大小與修改時間皆不變」的穩定性檢查,可以自然規避此問題。此外,常駐監控程序在 Windows 上需要以服務或「開機啟動並於當機時自動重啟」的方式維運,生命週期管理與除錯成本較高;排程輪詢每次執行後即結束,可直接透過工作排程器的執行紀錄追蹤是否正常運作。

替代方案:即時監控(watchdog daemon)。除非錄音來源改為「本機直接錄音落地」(沒有雲端同步這一層),否則此方案的即時性優勢會被同步未完成的風險與常駐維運成本抵銷,故不採用。

### 手動觸發與排程共用同一入口

手動觸發的需求只是「現在立刻執行一次」,處理邏輯與排程觸發完全相同(掃描→狀態檢查→轉錄→結構化寫入→更新狀態),沒有必要另建一套程式碼路徑。提供一支可雙擊執行的批次腳本呼叫同一支主程式即可達成,不增加維護面。

替代方案:另建互動式 CLI 參數或圖形介面。對目前需求是過度設計,不採用。

### 轉錄採用本地 faster-whisper(large-v3)而非雲端 Whisper API

使用者機器搭載 NVIDIA RTX 3500 Ada(12GB VRAM),GPU 加速下可流暢運行 large-v3 模型,準確度與雲端 API 相當,且完全免費、錄音內容不需上傳第三方伺服器。

替代方案:OpenAI Whisper API。需額外付費且逐字稿內容會上傳雲端;基於使用者硬體條件與隱私考量不採用。

風險:使用者環境為 Python 3.14.2,`faster-whisper` 與其依賴的 `ctranslate2` 可能尚無相容的預編譯套件,需另建較舊版本(3.11 或 3.12)的 Python 虛擬環境執行轉錄模組,詳見風險章節。

### 結構化使用 Claude API 直接呼叫,Notion 寫入改用 `notion-client` + Internal Integration Token,而非 Agent SDK + Notion MCP

實作階段(task 4.3)實際驗證後發現:本專案原本可用的 Notion MCP 連線,是掛在這個互動式 Claude Code session 上的帳號層級 Connector(OAuth),沒有專案層級的 `.mcp.json` 可以複製。要讓排程/手動觸發的**無人值守背景腳本**重複使用這條連線,需要先完成一次獨立的 Notion 遠端 MCP OAuth 授權流程,而這個流程能否被無人值守的排程腳本順利重放(重用已快取的 token)缺乏把握,且此驗證步驟需要瀏覽器互動,無法在開發過程中自動化確認。

改採 `notion-client` Python 套件搭配 Notion Internal Integration Token:使用者到 notion.so/my-integrations 申請一組 token(約2分鐘,無 OAuth 瀏覽器流程),並將目標資料庫分享給該 integration,之後所有讀寫都是直接、確定性的 API 呼叫,對「排程執行、沒人在場」這個場景完全免驗證負擔。結構化這一步(標題/摘要/重點/行動項目/分類標籤)改為直接呼叫 Claude API(`anthropic` 套件的一般文字/JSON 產生請求),不需要 Agent SDK 的工具呼叫(tool-use)迴圈,因為已經沒有 MCP 工具需要呼叫——Claude 依然自主決定結構化內容,只是「寫入 Notion」這個動作交由確定性的 Python 程式碼執行,而非讓 Agent 自己呼叫寫入工具。

替代方案(原本的主方案,已否決):Claude Agent SDK + Notion MCP。優點是不需要使用者另外管理一組 Notion API 金鑰,但如上述,對無人值守的排程場景而言,OAuth 連線的可重用性是未經驗證且無法在開發階段確認的風險,故改採更成熟、可預測的 Internal Integration Token 方案。

### 單一 Notion 資料庫,以屬性分類而非多資料庫

使用者偏好簡單維護,單一資料庫搭配屬性篩選(日期、來源檔名、分類標籤 multi-select、狀態 select)已足夠支援檢視與篩選需求,避免多資料庫之間頁面移轉與交叉引用的額外複雜度。

### 逐字稿以 Toggle 區塊收合保留在頁面內容中

保留原始資訊避免遺漏,同時保持頁面預設閱讀體驗乾淨,僅在需要覆核細節時展開。

### Notion 資料庫本身由一次性 setup 腳本自動建立,而非要求使用者手動在 Notion 介面設定

建立資料庫這件事可以透過 `notion-client` 呼叫 Notion API 完成,不需要使用者手動在 Notion 網頁介面新增資料庫、逐一設定屬性與選項,降低第一次上手的設定門檻與人為設定錯誤的風險(例如漏設某個 multi-select 選項)。此步驟設計為**一次性 setup 腳本**,而非讓每次排程/手動觸發的主流程都去檢查資料庫是否存在——資料庫結構建立後不會頻繁變動,每次執行都檢查只會增加不必要的延遲與 API 呼叫次數。

替代方案:讓主流程(`main.py`)每次執行時都先檢查資料庫是否存在、不存在才建立。不採用,因為這會讓核心處理流程多一層「檢查資料庫」的職責與延遲,而資料庫只需要建立一次。

## Implementation Contract

**Behavior**:使用者將錄音檔同步到設定的本機資料夾後,系統會在下一次排程執行(或使用者雙擊手動觸發批次腳本)時,自動偵測到已完成同步的新檔案、產生逐字稿、透過 Agent 結構化並在 Notion 指定資料庫建立一則新頁面,頁面含日期、來源檔名、分類標籤、狀態屬性,以及 AI 摘要、重點、行動項目與收合的完整逐字稿內容。已成功處理過的檔案不會被重複處理。

**Interface / data shape**:

- 設定檔(依 `config/.env.example` 建立 `.env`):`WATCH_FOLDER_PATH`(雲端同步資料夾的本機路徑)、`ANTHROPIC_API_KEY`(供 Claude API 結構化逐字稿使用)、`NOTION_API_KEY`(Notion Internal Integration Token)、`NOTION_DATABASE_ID`(由一次性 setup 腳本建立資料庫後產生,填回 `.env`),以及本地轉錄所需的 Python 執行環境路徑
- 狀態追蹤資料(本地 JSON 或 SQLite),每筆記錄至少包含:檔案識別(檔名加修改時間或內容 hash)、處理狀態(pending/success/failed)、最後嘗試時間、失敗原因(如有)、失敗重試次數
- 單一進入點程式,無參數執行即完整跑一輪「掃描→穩定性確認→轉錄→結構化寫入→更新狀態」,排程與手動觸發呼叫同一個入口
- Notion 頁面屬性 schema:日期(date)、來源檔名(rich_text)、分類標籤(multi_select,固定清單:會議、靈感、學習、其他)、狀態(select:待處理、已整理、已完成;新建頁面預設為「已整理」)

**Failure modes**:

- 轉錄失敗(例如音檔損毀或格式不支援):該筆記錄標記為 failed 並附上錯誤原因,不中斷整體執行流程,下次排程或手動觸發時依重試次數上限重試
- Notion 寫入失敗(例如 Notion API 呼叫失敗或 Integration Token 失效):同樣標記為 failed,並保留已完成的逐字稿內容,避免因寫入失敗而遺失轉錄成果,下次執行時重試寫入而不重新轉錄
- 單一檔案失敗達重試次數上限後,狀態轉為需人工介入,不再自動重試,避免無限重試同一個壞檔案消耗資源

**Acceptance criteria**:

- 手動放入一個測試音檔到 watch 資料夾,執行手動觸發批次腳本後,Notion 資料庫出現一則新頁面,四個屬性與頁面內容(摘要/重點/行動項目/收合逐字稿)皆正確
- 對同一個已成功處理的檔案重複執行整個流程,確認不會產生重複頁面
- 模擬一個轉錄失敗案例(例如提供損毀音檔),確認該筆記錄狀態正確標記為 failed,且不會導致整個執行流程中斷或影響其他檔案的處理

**Scope boundaries**:

- In scope:單一 watch 資料夾、單一 Notion 資料庫、排程與手動雙觸發入口共用同一邏輯、本地端轉錄、Agent 自主結構化與寫入、失敗重試與狀態追蹤
- Out of scope:即時監控 daemon、長音檔自動切割/分段處理、多資料夾或多資料庫來源管理、Notion 分類標籤的動態管理介面

## Risks / Trade-offs

- [使用者環境 Python 3.14.2 過新,faster-whisper/ctranslate2 可能無相容的預編譯套件] → 已確認使用者機器已另外安裝 Python 3.11,直接用該版本建立轉錄虛擬環境,主程式以子行程方式呼叫該環境
- [ctranslate2 的 GPU 執行需要 cuBLAS/cuDNN 動態連結庫,系統未安裝完整 CUDA Toolkit 時預設找不到] → 已在轉錄虛擬環境額外安裝 `nvidia-cublas-cu12`、`nvidia-cudnn-cu12` 這兩個 pip 套件取得對應 DLL,並在 `_transcribe_worker.py` 啟動時把這兩個套件底下的 `nvidia/*/bin` 目錄加進 `PATH` 環境變數(而非 `os.add_dll_directory`,因為 ctranslate2 的 CUDA 載入發生在編譯後的擴充模組內部,不會遵循 Python 層級註冊的 DLL 搜尋目錄,只有 `PATH` 對它有效)
- [排程輪詢存在 15-30 分鐘的偵測延遲] → 已知取捨,對筆記整理場景可接受,不視為缺陷
- [過長的錄音檔可能造成本地轉錄耗時過久或記憶體不足] → 本次不處理自動切割,先以人工留意錄音長度作為暫行做法,音檔切割留待後續 change 處理

## Migration Plan

全新專案,無既有資料需要遷移。首次啟用前需完成:安裝相依套件(含另建的本地轉錄虛擬環境)、到 notion.so/my-integrations 建立 Internal Integration 並取得 `NOTION_API_KEY`、執行一次性 setup 腳本自動建立 Notion 筆記資料庫並設定四個屬性 schema、將產生的資料庫 ID 填入 `.env`、於 Windows 工作排程器設定排程任務。

## Open Questions

- 分類標籤的固定清單最終要包含哪些選項,是否需要使用者確認完整清單?
- 失敗重試的次數上限與重試間隔策略?
