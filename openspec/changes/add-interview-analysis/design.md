## Context

現有管線（[main.py](../../../src/main.py)、[watcher.py](../../../src/watcher.py)、[transcribe.py](../../../src/transcribe.py)、[notion_agent.py](../../../src/notion_agent.py)）是單一資料夾、單一輸出格式的無人值守腳本：排程任務與手動觸發都呼叫同一個 `main()`，掃描 `WATCH_FOLDER_PATH`，用兩次掃描比對判斷檔案是否已從雲端同步完成，本地跑 faster-whisper 轉錄，再交給 Claude 整理成「摘要/重點/行動項目」寫入 Notion，逐字稿全文以折疊 toggle 附上。

`_transcribe_worker.py` 內部其實已經有 whisper 切出的逐句 `segment_records`（含 `start`/`end` 秒數），但 `_assemble_transcript` 目前把它們接成一整段純文字後即捨棄時間戳，只在有語者分離時保留 `[語者 X]` 標籤。語者分離本身（`SPEAKER_DIARIZATION_ENABLED`、`diarize_segments()`）已經是另一個獨立進行中的 change（`add-speaker-diarization`，16/17 完成）交付的能力，會輸出帶 `speaker` 欄位（如 `SPEAKER_00`）的 labeled segments，但只用於組出純文字逐字稿裡的 `[語者 X]` 前綴，不會保留到任何結構化資料裡。

本次變更要新增訪談分析：使用者把訪談 mp4 丟進另一個雲端同步資料夾，系統要用不同的分析角度（痛點/亮點/訪談摘要/使用習慣）整理，且每個分析點要能標記出對應到逐字稿裡的哪個時間點/原句，寫進 Notion。

第一輪實作（`INTERVIEW_WATCH_FOLDER_PATH` 分流、`--keep-segments` 時間戳保留、訪談 structuring、Notion quote block）已經在真實環境跑過兩支訪談影片驗證成功。跑完後發現兩個問題，促成這次 ingest 的追加範圍：
1. 部分分析點的時間戳消失（詳見下方「時間戳容錯比對」決策）——已修正。
2. 逐字稿完全沒有標示是哪位受訪者講的話，只有 `[MM:SS]`——這是原本 Non-Goals 明確列為「留待後續 change」的項目，使用者實際看到結果後要求這次一併處理。

## Goals / Non-Goals

**Goals:**

- 讓訪談影片與會議錄音各自套用不同的 Claude structuring 邏輯與 Notion 頁面格式，且兩條路徑共用既有的穩定性偵測、去重、重試、歸檔機制。
- 讓訪談分析的每個痛點/亮點/使用習慣條目都能回溯到逐字稿裡實際講出這句話的時間點與原句。
- 訪談資料夾沒有待處理檔案時，會議資料夾的掃描與處理完全不受影響，不需要額外的「目前是訪談模式還是會議模式」狀態機。
- 當語者分離（`SPEAKER_DIARIZATION_ENABLED`）與訪談時間戳保留（`--keep-segments`）同時啟用時，逐字稿與 Notion 頁面上的時間戳引用要同時標示語者（例如 `[19:56][語者 A]`），不只是時間戳；未啟用語者分離時，行為維持原本只有 `[MM:SS]` 的格式不變。

**Non-Goals:**

- 不做「Claude Code 對話主動推播通知」——待處理篇數提示只寫進 pipeline log，維持現有無人值守腳本的架構，不新增通知管道（Windows 通知/Email/webhook）。
- 不新增獨立的 Notion 資料庫；訪談頁面寫入與會議共用的同一個 `NOTION_DATABASE_ID`，只新增一個分類標籤選項。
- 不支援「同一個資料夾內用檔名或副檔名判斷訪談 vs 會議」；只支援兩個獨立設定的資料夾路徑。
- 不重新設計語者辨識邏輯本身；語者標籤完全借用 `add-speaker-diarization` change 既有的 `diarize_segments()`/`_format_diarized_transcript()` 產出的字母命名規則（語者 A/B/C...），本次只負責把這個既有結果「傳遞」進 `--keep-segments` 的 segments 清單與訪談頁面，不改動語者辨識演算法或字母指派規則本身。

## Decisions

### 用獨立資料夾（而非檔名規則或狀態機）區分訪談與會議

新增 `INTERVIEW_WATCH_FOLDER_PATH` 設定，與 `WATCH_FOLDER_PATH` 平行存在。`main.py` 對兩個資料夾各自呼叫 `get_files_to_process`（沿用 [watcher.py](../../../src/watcher.py) 既有函式，只是傳入不同的 `watch_folder`/`snapshot_path`/`StateStore`），分流到既有的 `process_file`（會議）或新增的 `process_interview_file`（訪談）。

**替代方案考量**：
- 同一資料夾 + 檔名關鍵字判斷（例如檔名含「訪談」）——被否決，因為使用者無法保證命名一致，誤判會把訪談當會議整理，或反之。
- 同一資料夾 + 全域「目前模式」狀態——被否決，因為需要額外的狀態儲存與復原邏輯（例如程式崩潰在切換模式的當下），且與現有「檔案層級 state，不含全域模式」的架構不一致。

### 訪談資料夾沿用現有 `AUDIO_EXTENSIONS`，不另外限制副檔名

訪談與會議的區分完全來自「檔案所在的資料夾設定」，不靠副檔名。訪談資料夾一樣套用 [main.py](../../../src/main.py) 現有的 `AUDIO_EXTENSIONS` 集合（含 `.mp4`/`.mkv`），維持單一份副檔名判斷邏輯。

### 逐句時間戳透過新增的 `preserve_segments` 旗標保留，預設關閉

`transcribe_file()` 與 worker 指令新增 `preserve_segments: bool = False` 參數；只有訪談路徑呼叫時傳 `True`。`TranscriptionResult` 新增 `segments: list[dict] | None` 欄位（每筆 `{start, end, text}`），worker 在旗標開啟時於 JSON payload 額外回傳這份清單，`_assemble_transcript` 拼接純文字的行為完全不變。

**替代方案考量**：一律回傳 segments（不加旗標）——被否決，因為每次轉錄都多一份輸出資料、多一次序列化成本，而會議路徑用不到，維持現狀效能與輸出格式比較保守。

### 新增 `src/interview_agent.py`，不擴充 `notion_agent.py`

訪談的 Claude structuring tool schema（訪談摘要/痛點/亮點/使用習慣，每點附時間戳與原句引用）與 Notion 頁面組裝邏輯（quote block、`[MM:SS]` 格式化）全部放在新模組，[notion_agent.py](../../../src/notion_agent.py) 完全不修改。

**替代方案考量**：在 `notion_agent.py` 內用 if/else 分支處理兩種 schema——被否決，兩種 schema 的欄位、prompt、頁面版型差異大，混在同一個模組會讓既有會議路徑的程式碼多出大量與它無關的分支，違反最小變更原則。

### 訪談與會議共用同一個 Notion 資料庫，新增「訪談」分類標籤

`notion_schema.py` 的 `CATEGORY_TAG_OPTIONS` 新增 `"訪談"`。訪談頁面寫入時複用既有的 `NOTION_DATABASE_ID`，不建立新資料庫。

### 訪談的掃描快照與處理狀態使用獨立檔案

新增 `data/interview_state.json`、`data/interview_scan_snapshot.json`，與既有 `data/state.json`、`data/scan_snapshot.json` 分開。避免兩個資料夾若剛好出現同名檔案時，`StateStore.make_file_id`（依檔名+mtime 組成）互相污染彼此的成功/失敗紀錄。

### 訪談待處理篇數達 2 篇以上時，在 log 特別標註

`main.py` 掃描完訪談資料夾、組出待處理清單後，若清單長度 `>= 2`，額外輸出一行 `log.info`（例如「本次有 N 篇訪談待分析」）；單篇待處理沿用現有的一般掃描日誌格式，不特別標註。

### 時間戳容錯比對：數字容忍誤差 + 引用文字比對雙重保險

真實環境驗證發現：`format_segments_with_timestamps()` 把每段的起始時間 floor 到整數秒顯示成 `[MM:SS]`，Claude 讀回來換算成秒數時，容易落在真實 segment 起始時間的「前一點點」（例如真實 1196.8 秒的段落顯示成 `19:56`，Claude 回報 1196.0 秒，正好落在該 segment 範圍之外），導致 `_valid_start_seconds` 誤判為「找不到」而捨棄時間戳。修正為兩層：
1. `_valid_start_seconds` 的比對範圍加上 ±2 秒容忍值，吸收這種顯示格式本身造成的捨入誤差。
2. 容忍值比對仍失敗時，改用「引用原句的文字」去比對逐字稿 segments 的文字內容（正規化掉空白與標點後做子字串比對），找到真正講出這句話的段落，取其起始時間；這比單純相信模型回報的數字更可靠，因為 quote 本來就要求是逐字稿的近逐字引用。
3. 兩種方式都比對不到時，才真正判定為無效時間戳，退化為「僅顯示原文引用」。

**替代方案考量**：只加大數字容忍值（不做文字比對）——被否決，真實資料顯示部分時間戳是模型整個猜錯（不是單純捨入誤差的小範圍偏移），數字容忍值治標不治本；文字比對能處理數字完全錯誤但引用文字忠實的情況。

### 語者標籤透過既有的 `diarize_segments()` 命名規則合併進 `--keep-segments` 的 segments 清單

`_transcribe_worker.py` 目前在 `--diarize` 啟用時，只把 labeled segments（含 `speaker` 欄位）格式化成純文字 `[語者 X] ...` 字串（`_format_diarized_transcript`），沒有保留到任何結構化輸出。本次修改：當 `--diarize` 與 `--keep-segments` 同時啟用時，`--keep-segments` 回傳的 segments 清單裡每一筆也帶上同一套 `diarize_segments()` 算出的 `speaker` 字母標籤（與純文字逐字稿裡的 `[語者 X]` 標籤完全一致，同一次呼叫、同一份 labeled_segments，不重新呼叫 diarization）；只有 `--diarize` 未啟用、或 diarization 失敗降級時，segments 維持現狀（無 `speaker` 欄位）。

`interview_agent.format_segments_with_timestamps()` 在 segment 有 `speaker` 欄位時，輸出 `[MM:SS][語者 A] 文字`；沒有時維持現有的 `[MM:SS] 文字`，向下相容。`InterviewFinding` 新增選填欄位 `speaker: str | None`，由 `_valid_start_seconds`/`_find_start_seconds_by_quote` 命中的那個 segment 帶出；Notion quote block 格式相應變成 `[MM:SS][語者 A]「引用原句」`（無語者資訊時維持 `[MM:SS]「引用原句」`）。

**替代方案考量**：
- 在 `interview_agent.py` 端重新跑一次語者比對（例如拿 timestamp 去反查另一份語者資料）——被否決，`_transcribe_worker.py` 當下就有完整的 labeled_segments，直接合併進 payload 最直接，不需要引入第二套比對邏輯。
- 逐字稿全文（Notion 折疊區塊裡的「完整逐字稿」）是否也要用 `[MM:SS][語者 X]` 逐行呈現——沿用，因為 `format_segments_with_timestamps()` 本來就同時是「餵給 Claude 的輸入」與「折疊區塊顯示內容」的共用函式，語者標籤自然一併套用，不需要額外邏輯。

## Implementation Contract

**行為（Behavior）**：
- Operator 在 `.env` 設定 `INTERVIEW_WATCH_FOLDER_PATH` 後，執行 `main.py`（排程或 `run_now.bat`）會同時掃描會議與訪談兩個資料夾。
- 訪談資料夾本次掃描到 2 篇以上待處理檔案時，pipeline log（[data/pipeline.log](../../../data/pipeline.log)）會出現一行明確標註篇數的訊息。
- 每篇成功處理的訪談，會在既有 `NOTION_DATABASE_ID` 資料庫新增一個分類標籤為「訪談」的頁面，內容包含：訪談摘要段落，以及「痛點」「亮點」「使用者使用習慣」三個 `heading_3` 區塊，每個區塊下每一條分析點皆搭配一個 quote block。
- `INTERVIEW_WATCH_FOLDER_PATH` 未設定時，訪談管線整個不執行，只記錄一行 info log 說明訪談模式未啟用；會議管線行為與現況完全相同。
- 當 `SPEAKER_DIARIZATION_ENABLED=true` 且該次訪談轉錄成功套用語者分離時，quote block 與逐字稿折疊區塊的每一行都會多帶一個 `[語者 X]` 標籤（例如 `[19:56][語者 A]「引用原句」`）；未啟用語者分離時，格式維持 `[MM:SS]「引用原句」` 不變。

**介面 / 資料結構（Interface / data shape）**：
- `TranscriptionResult`（[transcribe.py](../../../src/transcribe.py)）新增欄位 `segments: list[dict] | None`，每個 dict 為 `{"start": float, "end": float, "text": str}`，當轉錄同時啟用 `--diarize` 時額外帶 `"speaker": str`。
- `transcribe_file(..., preserve_segments: bool = False)` 新增參數；worker 指令列新增對應的 `--keep-segments` 旗標。
- `src/interview_agent.py` 公開：
  - `InterviewFinding` dataclass：`insight: str`（分析文字）、`quote: str`（引用原句）、`start_seconds: float | None`、`speaker: str | None`（無語者資訊時為 `None`）。
  - `InterviewNote` dataclass：`summary: str`、`pain_points: list[InterviewFinding]`、`highlights: list[InterviewFinding]`、`usage_habits: list[InterviewFinding]`。
  - `structure_interview(transcript_with_timestamps: str, source_filename: str, recording_date: str, api_key: str, segments: list[dict]) -> InterviewNote`。
  - `format_segments_with_timestamps(segments: list[dict]) -> str`：`speaker` 欄位存在時輸出 `[MM:SS][語者 X] 文字`，不存在時輸出 `[MM:SS] 文字`。
  - `create_interview_page(note: InterviewNote, transcript: str, source_filename: str, recording_date: str, database_id: str, notion_api_key: str) -> NotionWriteResult`（重用 [notion_agent.py](../../../src/notion_agent.py) 既有的 `NotionWriteResult` dataclass）。
- `notion_schema.CATEGORY_TAG_OPTIONS`（[notion_schema.py](../../../src/notion_schema.py)）新增 `"訪談"`；`notion_schema.MEETING_CATEGORY_TAG_OPTIONS` 供會議 structuring 的 enum/fallback 使用，排除訪談專用標籤，避免共用清單汙染會議分類。
- `.env` / `config/.env.example` 新增選填設定 `INTERVIEW_WATCH_FOLDER_PATH`。

**失敗模式（Failure modes）**：
- 訪談檔案的轉錄/結構化/Notion 寫入失敗時，沿用既有 `StateStore` 的 failed/retry/needs_manual_intervention 機制，但寫入獨立的 `data/interview_state.json`，重試計數與會議檔案互不影響。
- `INTERVIEW_WATCH_FOLDER_PATH` 未設定：視為「訪談模式未啟用」，不是錯誤，不拋例外、不中斷會議管線。
- `WATCH_FOLDER_PATH` 與 `INTERVIEW_WATCH_FOLDER_PATH` 設定成同一個路徑：視為設定錯誤，`main()` 啟動時檢查並直接以非零狀態碼中止，log 明確說明兩個路徑不可相同，避免同一批檔案被兩條管線重複處理。
- Claude 回傳的 `start_seconds` 若數字容忍比對與引用文字比對都對不上任何真實 segment（模型幻覺時間戳）：該筆 finding 仍寫入 Notion，但時間戳與語者標籤都退化為「僅顯示原文引用」，不會讓整篇訪談處理失敗。
- 語者分離失敗（例如 Hugging Face token 失效）：沿用既有 Diarization Failure Falls Back To Plain Transcript 行為，`--keep-segments` 的 segments 清單同樣不帶 `speaker` 欄位，訪談分析退化為純時間戳格式，不會因為語者分離失敗而讓訪談處理失敗。

**驗收標準（Acceptance criteria）**：
- 單元測試：`watcher.get_files_to_process` 對兩個獨立資料夾/獨立 state 呼叫時，彼此的 processed/failed 狀態不互相污染。
- 單元測試：`transcribe_file(preserve_segments=True)` 回傳的 `segments` 落在原始音訊時間軸上（與既有 VAD 時間軸保證一致）；`preserve_segments=False`（會議路徑既有呼叫方式）時 `segments` 為 `None`，且拼接後的 `transcript` 字串與目前行為位元組相同。
- 單元測試：`interview_agent` 的 tool schema 解析對缺欄位/格式錯誤有容錯（比照 [notion_agent.py:114-168](../../../src/notion_agent.py:114) 現有的 tolerant parser 模式）。
- 單元測試：`create_interview_page` 產出的 Notion block 結構中，每個分析條目下確實掛了一個內容含 `[MM:SS]` 格式時間戳與引用原句的 quote block。
- 單元測試：`main.py` 在訪談待處理清單長度 `>= 2` 時，log 輸出內容包含待處理篇數。
- 單元測試：`_valid_start_seconds` 對「floor 捨入造成的些微誤差」給予容忍；`_find_start_seconds_by_quote` 能用引用文字比對回真實 segment 的起始時間；兩者都對不上時仍正確退化為 `None`。
- 單元測試：`_transcribe_worker.py` 在 `--diarize` 與 `--keep-segments` 同時啟用時，回傳的 segments 每筆帶有與純文字逐字稿一致的 `speaker` 標籤；只有 `--keep-segments`（無 `--diarize`）時 segments 不含 `speaker` 欄位。
- 單元測試：`format_segments_with_timestamps` 對有/無 `speaker` 欄位的 segment 分別輸出 `[MM:SS][語者 X] 文字` 與 `[MM:SS] 文字`。
- 手動驗證：在 `INTERVIEW_WATCH_FOLDER_PATH` 丟兩支 mp4，執行 `run_now.bat`，確認 Notion 資料庫新增兩頁「訪談」分類頁面，且會議資料夾中原本待處理的檔案處理結果不受影響。（已於真實環境完成，見 Context）

**範圍界線（Scope boundaries）**：
- In scope：上述新增/修改的模組（`interview_agent.py`、`main.py` 路由邏輯、`transcribe.py`/`_transcribe_worker.py` 的 `preserve_segments` 與語者標籤合併、`notion_schema.py` 的分類標籤、`.env.example` 的新設定、時間戳容錯比對）。
- Out of scope：獨立 Notion 資料庫、任何形式的主動通知推播（Windows 通知/Email/webhook/Claude Code 對話喚醒）、重新設計語者辨識演算法本身（沿用 `add-speaker-diarization` change 既有輸出）。

## Risks / Trade-offs

- [Risk] Whisper 切出的 segment 過短/破碎，導致單一 segment 的引用原句讀起來不完整 → Mitigation：`structure_interview` 的 prompt 要求 Claude 在需要時合併鄰近時間相近的 segment 文字組成完整引用句，但 `start_seconds` 一律取第一個被引用 segment 的起始時間。
- [Risk] `preserve_segments` 參數若被誤用在會議路徑，可能意外改變既有輸出格式或增加不必要的效能開銷 → Mitigation：預設值為 `False`，且單元測試明確覆蓋「會議路徑呼叫不傳此參數時行為與現況位元組相同」。
- [Risk] 使用者不慎把 `WATCH_FOLDER_PATH` 與 `INTERVIEW_WATCH_FOLDER_PATH` 設成同一個路徑，導致同一批檔案被兩條管線搶著處理、產生重複筆記 → Mitigation：`main()` 啟動時檢查兩者不可相同，相同則 fail fast 並中止本次執行。
- [Risk] Claude 產生的時間戳與逐字稿實際 segment 對不上（幻覺） → Mitigation：寫入 Notion 前先用容忍誤差比對、再用引用文字比對兩層機制嘗試還原，對不上的 finding 降級為「僅顯示原文，不顯示時間戳/語者」而非讓整筆處理失敗。
- [Risk] 引用文字比對（子字串匹配）在逐字稿裡有大量重複用語時可能匹配到錯誤的段落 → Mitigation：優先信任數字容忍比對（範圍更精確），文字比對只在數字比對完全失敗時當備援；可接受的風險，因為結果最差情況只是時間戳指向另一個講相近內容的段落，不會顯示明顯錯誤的資訊。
- [Risk] 語者分離的字母指派（語者 A/B）是依「該語者在這次轉錄裡第一次出現的順序」決定，同一支影片重新轉錄若 whisper 切分段落方式不同，字母指派可能跟前一次不一致 → Mitigation：這是既有 `add-speaker-diarization` change 的既有行為，不在本次變更範圍內處理；重新處理同一支訪談時字母標籤可能與前次不同，屬已知限制。

## Migration Plan

- `INTERVIEW_WATCH_FOLDER_PATH` 為選填設定，未設定時所有既有行為（會議管線）完全不變，無需資料遷移。
- 部署步驟：更新 `.env` 加入 `INTERVIEW_WATCH_FOLDER_PATH` 指向雲端同步的訪談資料夾本機路徑；如需語者標籤，另外設定 `SPEAKER_DIARIZATION_ENABLED=true` 與 `HUGGINGFACE_TOKEN`（既有設定，非本次新增）。
- 回滾：從 `.env` 移除 `INTERVIEW_WATCH_FOLDER_PATH` 即可完全停用訪談管線，不影響既有會議筆記與資料。
- 已成功處理過的訪談檔案會被歸檔到「已處理」子資料夾，且 `data/interview_state.json` 記錄為 success；若要用本次修正（時間戳容錯比對、語者標籤）重新產生已經處理過的訪談頁面，需要手動把檔案從「已處理」移回訪談資料夾根目錄，並清除 `data/interview_state.json` 裡對應檔案的紀錄，否則掃描時會因為已標記成功而被跳過。

## Open Questions

- notion-client 寫入 page 時對 multi-select 屬性帶入資料庫尚未定義過的新選項名稱（「訪談」）是否會自動建立該選項——已在真實環境驗證解決：未重新執行 `setup_notion_database.py`，Notion API 在頁面寫入時自動建立了「訪談」這個 multi-select 選項，不需要額外的 schema migration 步驟。
