## 1. 相依套件與設定文件

- [x] 1.1 在 `requirements-transcribe.txt` 新增 `whisperx`(含其 `torch`/`torchaudio`/`pyannote.audio` 相依),支援「採用 WhisperX 整合對齊+分離,而非只用 pyannote.audio 疊加時間重疊對齊」的設計決策 —— 驗證:在 `.venv-transcribe` 執行 `pip install -r requirements-transcribe.txt` 成功安裝且 `python -c "import whisperx"` 不報錯
- [x] 1.2 在 `config/.env.example` 新增 `SPEAKER_DIARIZATION_ENABLED`(預設 `false`)與 `HUGGINGFACE_TOKEN` 兩個變數並附上說明註解(需先到 Hugging Face 接受 pyannote gated model 授權條款),對應「語者分離預設關閉,以環境變數 `SPEAKER_DIARIZATION_ENABLED` 控制」的設計決策 —— 驗證:檢視 `config/.env.example` 內容包含這兩個變數與完整中文說明
- [x] 1.3 更新 `README.md` 的「已知限制與未來方向」段落,移除語者分離的舊限制描述,改為說明新功能的啟用方式、一次性 Hugging Face token 設定步驟,以及「語者標籤為自動偵測、可能有誤」的誠實註記 —— 驗證:檢視 `README.md` 對應段落內容已更新且與 `.env.example` 的變數名稱一致

## 2. src/diarize.py 語者分離模組(TDD)

- [x] 2.1 在 `tests/test_diarize.py` 撰寫失敗測試:涵蓋 `diarize_segments()` 成功時對每個輸入 segment 標註 `speaker` 欄位(依偵測到語者的出現順序決定標籤)、以及底層 whisperx/pyannote 呼叫拋出例外時 `diarize_segments()` 原樣往外拋出例外(不吞錯誤),對應 Local Speaker Diarization 與 Diarization Failure Falls Back To Plain Transcript 規格 —— 驗證:`pytest tests/test_diarize.py` 執行,兩個測試因 `src/diarize.py` 尚未實作而失敗(ImportError 或 AttributeError)
- [x] 2.2 實作 `src/diarize.py` 的 `diarize_segments(audio_path, segments, hf_token, device)`,呼叫 `whisperx.diarize.DiarizationPipeline` 與 `whisperx.assign_word_speakers()` 取得每個 segment 的語者標籤,對應「語者分離邏輯獨立成 `src/diarize.py`,由 `_transcribe_worker.py` 呼叫」的設計決策 —— 驗證:`pytest tests/test_diarize.py` 全數通過

## 3. `_transcribe_worker.py` 整合語者分離與前綴組裝

- [x] 3.1 在 `tests/test_transcribe.py`(或既有涵蓋 worker 邏輯的測試檔)撰寫失敗測試:啟用語者分離且 `diarize_segments()` 回傳成功結果時,worker 組裝出的逐字稿字串包含依語者出現順序對應的 `[語者 A]`/`[語者 B]` 前綴、片段間以換行分隔,對應 Local Speaker Diarization 規格與「語者標籤以純文字前綴方式寫入逐字稿字串,不改變逐字稿的資料型別」的設計決策 —— 驗證:`pytest tests/test_transcribe.py` 執行,測試因尚未實作而失敗
- [x] 3.2 在同一測試檔撰寫失敗測試:未啟用語者分離時,worker 產生的逐字稿字串與現行格式完全一致(無前綴、無新增換行),對應 Local Speaker Diarization 規格中「Diarization disabled preserves existing plain-text transcript」情境 —— 驗證:`pytest tests/test_transcribe.py` 執行,測試因尚未實作而失敗
- [x] 3.3 在同一測試檔撰寫失敗測試:啟用語者分離但 `diarize_segments()` 拋出例外時,worker 捕捉例外、回傳不含語者前綴的純逐字稿,且成功旗標/回傳值等同轉錄成功,對應 Diarization Failure Falls Back To Plain Transcript 規格與「語者分離失敗時退化成純逐字稿,不讓轉錄整體失敗」的設計決策 —— 驗證:`pytest tests/test_transcribe.py` 執行,測試因尚未實作而失敗
- [x] 3.4 修改 `src/_transcribe_worker.py`:讀取新的 `--diarize` 命令列旗標與 `HUGGINGFACE_TOKEN` 環境變數,在既有 faster-whisper 轉錄取得 segments 後呼叫 `diarize_segments()`,成功時組裝帶語者前綴的逐字稿、失敗時記錄警告並回退純逐字稿,完成 3.1~3.3 對應的行為 —— 驗證:`pytest tests/test_transcribe.py` 與 `pytest tests/test_diarize.py` 全數通過
- [x] 3.5 修改 `src/_transcribe_worker.py` 在執行語者分離步驟時寫入 `phase="diarizing"` 的進度負載(比照既有 `_write_progress` 呼叫模式),對應 Diarization Progress Reporting 規格 —— 驗證:`pytest tests/test_progress_reporting.py` 新增/擴充的測試通過,斷言語者分離期間進度檔的 `phase` 欄位為 `"diarizing"`

## 4. 進度檢視器與主流程配置透傳

- [x] 4.1 在 `tests/test_progress_reporting.py` 撰寫失敗測試:`show_progress._render()` 收到 `phase="diarizing"` 的負載時,回傳包含檔名的中文狀態文字,而不是落入預設的「狀態不明」分支,對應 Diarization Progress Reporting 規格 —— 驗證:`pytest tests/test_progress_reporting.py` 執行,測試因尚未實作而失敗
- [x] 4.2 修改 `src/show_progress.py` 的 `_render()` 新增 `diarizing` 分支,顯示「語者分離中: {filename}」等狀態文字 —— 驗證:`pytest tests/test_progress_reporting.py` 全數通過
- [x] 4.3 [P] 在 `tests/test_transcribe.py` 撰寫/擴充失敗測試:`transcribe_file()` 新增的 `diarization_enabled` 與 `hf_token` 參數會正確組裝進 worker 呼叫命令(`--diarize` 旗標)與環境變數,對應「`src/transcribe.py` 的 `transcribe_file()` 新增 `diarization_enabled`/`hf_token` 參數」的設計決策 —— 驗證:`pytest tests/test_transcribe.py` 執行,測試因尚未實作而失敗
- [x] 4.4 [P] 在 `tests/test_main_pipeline.py` 撰寫/擴充失敗測試:`_load_config()` 讀取 `SPEAKER_DIARIZATION_ENABLED`/`HUGGINGFACE_TOKEN`,且啟用旗標為真但 token 為空時,啟動階段拋出設定錯誤並終止(不進入檔案處理迴圈),對應 Local Speaker Diarization 規格中的「Enabling diarization without a Hugging Face token is a configuration error」情境 —— 驗證:`pytest tests/test_main_pipeline.py` 執行,測試因尚未實作而失敗
- [x] 4.5 修改 `src/transcribe.py` 的 `build_worker_command()`/`transcribe_file()` 與 `src/main.py` 的 `_load_config()`/`process_file()`,完成 4.3、4.4 對應的參數透傳與設定檢查行為 —— 驗證:`pytest tests/test_transcribe.py` 與 `pytest tests/test_main_pipeline.py` 全數通過

## 5. 整體驗證

- [x] 5.1 執行完整測試套件確認沒有既有測試因本次變更而迴歸失敗 —— 驗證:`pytest` 於專案根目錄執行,全數通過
- [ ] 5.2 依 design.md 的驗收標準,以一段已知雙語者的錄音手動跑一次(啟用 `SPEAKER_DIARIZATION_ENABLED` 與有效 `HUGGINGFACE_TOKEN`),確認 Notion 頁面逐字稿 toggle 區塊出現 `[語者 A]`/`[語者 B]` 前綴且與實際發言者大致對應;再關閉功能重跑同一份錄音,確認逐字稿格式與變更前完全一致 —— 驗證:人工比對兩次執行產生的 Notion 頁面內容差異

## 6. 會議管線永不做語者分離(需求變更後追加)

- [x] 6.1 `src/main.py` 的 `process_file()`(會議路徑)呼叫 `transcribe_file()` 時不再傳入 `diarization_enabled`/`hf_token`,一律使用函式預設值(不啟用),即使 `SPEAKER_DIARIZATION_ENABLED=true` 也不影響會議資料夾(`WATCH_FOLDER_PATH`)的錄音;`process_interview_file()`(訪談路徑)不受影響,仍依 `config["speaker_diarization_enabled"]` 決定(Meeting Recordings Never Use Diarization requirement)。驗證:`tests/test_main_pipeline.py` 新增 `MeetingDiarizationDisabledTests`,確認即使 config 裡 `speaker_diarization_enabled=True`,`process_file()` 呼叫 `transcribe_file()` 時 `diarization_enabled` 仍為 False。
- [x] 6.2 更新 `config/.env.example` 的 `SPEAKER_DIARIZATION_ENABLED` 註解,說明此設定只影響訪談資料夾,不需要為了會議另外開關。驗證:檢視 `.env.example` 對應段落內容已更新。
- [x] 6.3 執行完整測試套件,確認第 6 節新增測試與既有全部測試皆通過。驗證:`pytest` 執行結果全部 PASS(136 個測試)。
