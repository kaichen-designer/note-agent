## 1. 設定與資料夾路由基礎建設

- [x] 1.1 在 `config/.env.example` 新增選填設定 `INTERVIEW_WATCH_FOLDER_PATH`，`main.py` 的 `_load_config` 讀取後：未設定時訪談管線整個跳過並記錄一行說明 log；設定成與 `WATCH_FOLDER_PATH` 相同路徑時，`main()` 以非零狀態碼中止並記錄錯誤（Independently Configured Interview Watch Folder requirement）。驗證：新增/更新 `tests/test_main_pipeline.py` 涵蓋「未設定」「設定成相同路徑」「設定成不同路徑」三種情境並通過。
- [x] 1.2 新增 `data/interview_state.json`、`data/interview_scan_snapshot.json` 兩個獨立路徑常數，`main.py` 對訪談資料夾建立獨立的 `StateStore` 實例並呼叫既有的 `watcher.get_files_to_process`，使訪談與會議的處理狀態完全分開（Independent Watch Folder Support / Interview Processing State Isolation requirement；設計決策「訪談的掃描快照與處理狀態使用獨立檔案」）。驗證：新增 `tests/test_watcher.py` 案例，讓會議與訪談兩個資料夾出現同名檔案，確認兩邊的成功/失敗/重試次數互不污染。
- [x] 1.3 訪談資料夾的檔案篩選沿用 `main.py` 既有的 `AUDIO_EXTENSIONS` 集合（含 `.mp4`/`.mkv`），不另外新增訪談專屬的副檔名白名單，訪談與會議的區分完全由資料夾路徑決定（設計決策「訪談資料夾沿用現有 `AUDIO_EXTENSIONS`，不另外限制副檔名」）。驗證：新增測試確認訪談資料夾中不受支援的副檔名（例如 `.txt`）與會議資料夾一樣被排除在待處理清單之外。

## 2. 逐句時間戳保留

- [x] 2.1 `TranscriptionResult`（`src/transcribe.py`）新增 `segments: list[dict] | None` 欄位，`transcribe_file()` 新增 `preserve_segments: bool = False` 參數並轉譯成 worker 指令列的 `--keep-segments` 旗標；不傳此參數時行為與現況完全相同（Segment Timestamp Preservation On Request requirement；設計決策「逐句時間戳透過新增的 `preserve_segments` 旗標保留，預設關閉」）。驗證：更新 `tests/test_transcribe.py`，確認 `preserve_segments=False` 時回傳的 `segments` 為 `None`，且組出的 worker 指令列與現況位元組相同。
- [x] 2.2 `src/_transcribe_worker.py` 在收到 `--keep-segments` 時，於輸出 JSON payload 額外回傳 `segments` 清單（每筆含 `start`/`end`/`text`），且時間戳落在原始（含 VAD 跳過靜音前）的音訊時間軸上。驗證：新增/更新測試針對 worker 輸出，確認開啟 VAD 與 `--keep-segments` 同時啟用時，`segments` 的 `start`/`end` 仍對應原始音訊時間軸。

## 3. 訪談結構化分析

- [x] 3.1 新增 `src/interview_agent.py`：定義 `InterviewFinding`、`InterviewNote` dataclass 與 `structure_interview()`，呼叫 Claude API 產出訪談摘要、痛點、亮點、使用者使用習慣，每個 finding 含引用原句（quote）與時間戳（start_seconds）（Interview-Specific Structured Analysis requirement；設計決策「新增 `src/interview_agent.py`，不擴充 `notion_agent.py`」——`notion_agent.py` 本身不被修改）。驗證：新增 `tests/test_interview_agent.py`，確認 tool schema 呼叫參數正確，且對缺欄位/格式錯誤的回應有容錯解析（比照 `notion_agent.py` 現有的 tolerant parser 模式）。
- [x] 3.2 `structure_interview()` 對 Claude 回傳的每個 finding 的 `start_seconds`，比對該檔案的原始 `segments` 清單做範圍校驗；超出所有 segment 範圍時，該 finding 輸出時保留 `quote` 但時間戳欄位為空（Timestamped Evidence For Each Finding requirement 的第二個情境）。驗證：新增測試案例餵入一個超出範圍的 `start_seconds`，確認解析後的 `InterviewFinding` 不含有效時間戳但 `quote` 文字仍保留。

## 4. 訪談 Notion 頁面輸出

- [x] 4.1 `src/interview_agent.py` 新增 `build_interview_page_children()` 與 `create_interview_page()`：每個痛點/亮點/使用習慣條目下方掛一個 quote block，內容格式為 `[MM:SS]「引用原句」`（`start_seconds` 無效時只顯示引用原句，不顯示時間戳前綴），並將頁面寫入既有 `NOTION_DATABASE_ID`（Timestamped Evidence For Each Finding requirement）。驗證：新增測試，比對產出的 Notion block 結構是否符合 spec 中「rendered finding」範例的巢狀結構（bulleted item + quote block）。
- [x] 4.2 [P] `src/notion_schema.py` 的 `CATEGORY_TAG_OPTIONS` 新增 `"訪談"` 選項，`create_interview_page()` 寫入頁面時將分類標籤屬性設為 `"訪談"`，寫入既有 `NOTION_DATABASE_ID` 而非另建資料庫（Interview Notion Page Category Tag requirement；設計決策「訪談與會議共用同一個 Notion 資料庫，新增「訪談」分類標籤」）。驗證：新增測試確認建立的頁面 properties 中分類標籤含 `"訪談"`，且既有會議分類邏輯（`notion_agent.py` 既有測試）不受影響。

## 5. 主管線路由與待處理篇數提示

- [x] 5.1 `main.py` 新增依來源資料夾分流的邏輯：來自 `WATCH_FOLDER_PATH` 的檔案沿用既有 `process_file`（會議），來自 `INTERVIEW_WATCH_FOLDER_PATH` 的檔案改呼叫新增的 `process_interview_file`（訪談），兩者共用既有的 pipeline lock、logging、`_load_config` 框架（設計決策「用獨立資料夾（而非檔名規則或狀態機）區分訪談與會議」）。驗證：更新 `tests/test_main_pipeline.py`，確認兩種來源的檔案各自觸發對應的結構化函式（`structure_note` vs `structure_interview`）與對應的 Notion 寫入函式。
- [x] 5.2 `main.py` 在訪談待處理清單長度為 1 時沿用既有的一般掃描 log 格式，長度達 2 篇以上時額外輸出一行包含待處理篇數的 log 訊息（Batch Interview Detection Logging requirement；設計決策「訪談待處理篇數達 2 篇以上時，在 log 特別標註」）。驗證：新增測試以擷取 log 輸出，分別驗證 1 篇與 3 篇待處理時的 log 內容差異。

## 6. 端對端驗證

- [x] 6.1 執行完整測試套件，確認第 1-5 節新增/修改的測試與既有會議管線測試（`tests/test_main_pipeline.py`、`tests/test_notion_agent.py`、`tests/test_watcher.py`、`tests/test_transcribe.py` 等）全數通過。驗證：`pytest` 執行結果全部 PASS，無既有測試被破壞。
- [x] 6.2 在本機將 `INTERVIEW_WATCH_FOLDER_PATH` 指向一個測試資料夾，放入兩支訪談 mp4，手動執行 `run_now.bat`，確認 Notion 資料庫新增兩頁分類標籤為「訪談」的頁面（各自含摘要、痛點、亮點、使用習慣與對應的時間戳引用），且會議資料夾中原有待處理檔案的處理結果不受影響。驗證：人工檢視 Notion 頁面內容與 `data/pipeline.log` 的掃描/篇數提示訊息。已於真實環境執行：兩支真實訪談 mp4（Simon、Rocco）成功處理，Notion 出現對應「訪談」分類頁面；過程中發現時間戳/語者標籤問題，促成第 7 節的追加修正。

## 7. 時間戳容錯比對與語者標籤整合

- [x] 7.1 `_valid_start_seconds` 對 segment 的 `[start, end]` 範圍比對加上 ±2 秒容忍值，吸收 `format_segments_with_timestamps` 把起始時間 floor 到整數秒顯示造成的捨入誤差；容忍值比對仍失敗時，新增 `_find_start_seconds_by_quote()` 用引用原句的文字（正規化空白/標點後做子字串比對）去比對逐字稿 segments 的文字內容，取得該段落的起始時間；兩者都比對不到時才真正退化為 `None`（設計決策「時間戳容錯比對：數字容忍誤差 + 引用文字比對雙重保險」）。驗證：`tests/test_interview_agent.py` 新增案例涵蓋「floor 捨入造成的些微誤差仍判定有效」「數字完全錯誤但引用文字比對成功還原時間戳」「兩者都失敗時仍正確退化為 None」三種情境並通過。
- [x] 7.2 `src/_transcribe_worker.py` 在 `--diarize` 與 `--keep-segments` 同時啟用且 diarization 成功時，讓 `--keep-segments` 回傳的 segments 清單每筆額外帶上 `speaker` 欄位，值與同一次 `diarize_segments()` 呼叫產出、用於純文字逐字稿 `[語者 X]` 前綴的字母標籤完全一致（同一份 labeled_segments，不重新呼叫 diarization）；只有 `--diarize` 未啟用、或 diarization 失敗降級時，segments 不帶 `speaker` 欄位（Segment Speaker Labels When Diarization Enabled requirement；設計決策「語者標籤透過既有的 `diarize_segments()` 命名規則合併進 `--keep-segments` 的 segments 清單」）。驗證：新增/更新 `tests/test_progress_reporting.py` 案例，確認 `_build_result_payload`/worker 組裝邏輯在兩旗標同時啟用且 diarization 成功時，segments 每筆含與純文字逐字稿一致的 `speaker` 值；只有 `--keep-segments`（無 `--diarize`）或 diarization 失敗時，segments 不含 `speaker` 欄位。
- [x] 7.3 `src/interview_agent.py` 的 `format_segments_with_timestamps()` 在 segment 有 `speaker` 欄位時輸出 `[MM:SS][語者 X] 文字`，沒有時維持現有的 `[MM:SS] 文字`；`InterviewFinding` 新增選填欄位 `speaker: str | None`，由比對命中的那個 segment 帶出；`build_interview_page_children()`/`_finding_blocks()` 產出的 quote block 相應變成 `[MM:SS][語者 X]「引用原句」`（無語者資訊時維持 `[MM:SS]「引用原句」`）（Speaker-Labeled Timestamped Evidence requirement）。驗證：`tests/test_interview_agent.py` 新增案例涵蓋「segment 有 speaker 欄位時逐字稿/quote block 帶語者前綴」「無 speaker 欄位時維持現有格式」兩種情境並通過。
- [x] 7.4 執行完整測試套件，確認第 7 節新增/修改的測試與既有全部測試（含第 1-6 節）皆通過，且未破壞任何既有測試。驗證：`pytest` 執行結果全部 PASS。

## 8. 結構化輸出污染偵測(真實環境驗證後追加)

- [x] 8.1 `structure_interview()` 在解析 tool-call 回傳前，偵測 `summary` 欄位是否混入其他欄位未正確解析的原始 JSON 片段(例如 `"usage_habits":[`)，偵測到時拋出錯誤讓該筆錄音標記失敗並保留逐字稿重試，而不是把污染文字寫進 Notion 頁面(Corrupted Summary Rejection requirement；正式環境案例：Nathan 訪談頁面的摘要區塊尾端出現字面上的 `","usage_habits":[{...}]`，對應的「使用者使用習慣」區塊則整段消失)。驗證：`tests/test_interview_agent.py` 新增案例涵蓋「summary 混入 JSON 片段時拋出錯誤」「正常長度 summary 照常解析」兩種情境並通過。
- [x] 8.2 執行完整測試套件，確認第 8 節新增測試與既有全部測試皆通過。驗證：`pytest` 執行結果全部 PASS(135 個測試)。
