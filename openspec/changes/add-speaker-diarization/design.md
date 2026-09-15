## Context

現行轉錄流程(`src/_transcribe_worker.py`)在獨立的 `.venv-transcribe`(Python 3.11)裡直接呼叫 `faster_whisper.WhisperModel.transcribe()`,把回傳的逐段文字接成一整串,再用 OpenCC 轉成繁體,最後印出 `{"transcript": "..."}` JSON 給主環境的 `src/transcribe.py`(透過 subprocess 呼叫)。逐字稿是純文字,沒有語者資訊。

WhisperX 是在 faster-whisper 之上疊加「詞級時間對齊(wav2vec2 forced alignment)+ pyannote.audio 語者分離 + 語者指派」的整合套件,內部辨識引擎仍是 faster-whisper,因此可以在同一個 worker 行程、同一個 GPU 環境裡完成,不需要另開一個虛擬環境或呼叫外部服務。pyannote 的語者分離模型(`pyannote/speaker-diarization-3.1`)是 Hugging Face 上的 gated model,使用者需先在網頁上接受授權條款,並建立一組 HF token,worker 才能在本機下載模型權重(僅下載權重,不上傳音檔)。

## Goals / Non-Goals

**Goals:**

- 轉錄完成後,逐字稿的每個語句片段標註語者標籤(語者 A / 語者 B / ...),讓訪談/會議逐字稿能分辨是誰說的話
- 功能預設關閉,既有使用者的行為與輸出不受影響,需明確在 `.env` 啟用
- 語者分離失敗時,轉錄本身仍要成功(退化成純逐字稿),不能因為這個新步驟拖垮既有的轉錄可靠性
- 轉錄進度檢視器(`progress.bat`)在語者分離執行期間顯示有意義的狀態文字

**Non-Goals:**

- 不做語者真實姓名辨識,只標「語者 A/B/C...」通用標籤,不嘗試把聲紋對應到具體人名
- 不提供事後手動修正語者標籤的介面或工具
- 不支援即時(streaming)語者分離,僅限現有的離線批次轉錄流程
- 不新增「指定語者人數」等進階設定(min/max speakers),語者數由 pyannote 自動偵測;有需要再開新 change
- 不修改 Notion 資料庫 schema 或 `notion_agent.py` 的頁面屬性;語者標籤只是逐字稿文字內容的一部分,透過既有的「完整逐字稿」toggle 區塊呈現
- 不變更 Claude 結構化 prompt 的邏輯規則(行動項目負責人歸屬仍是既有的「逐字稿中有提到就寫進去」規則),語者標籤能不能幫助 Claude 判斷歸屬,是逐字稿內容品質的自然結果,不是本 change 要新增的規則

## Decisions

### 採用 WhisperX 整合對齊+分離,而非只用 pyannote.audio 疊加時間重疊對齊

WhisperX 內部本來就是 faster-whisper + wav2vec2 對齊 + pyannote 分離的整合流程,直接呼叫 `whisperx.load_model()` / `whisperx.align()` / `whisperx.diarize.DiarizationPipeline()` / `whisperx.assign_word_speakers()` 即可拿到「每個文字片段對應語者」的結果,對齊品質比自己用 whisper segment 時間戳跟 pyannote 語者時段做重疊比對(overlap heuristic)更準,而且是社群驗證過的標準做法,不需要自己重新實作對齊演算法。

### 語者分離邏輯獨立成 `src/diarize.py`,由 `_transcribe_worker.py` 呼叫

`_transcribe_worker.py` 目前只有一個 `main()` 函式,直接把語者分離邏輯塞進去會讓檔案職責混雜、難以獨立測試。拆成 `src/diarize.py` 提供一個函式(輸入:whisperx 對齊後的 segments + 音檔路徑 + HF token;輸出:標註語者標籤的 segments,或在失敗時丟出例外),`_transcribe_worker.py` 負責呼叫並處理例外退化。這個模組同樣活在 `.venv-transcribe` 環境內(whisperx/pyannote 依賴裝在 `requirements-transcribe.txt`),不會影響主環境。

### 語者分離預設關閉,以環境變數 `SPEAKER_DIARIZATION_ENABLED` 控制

WhisperX 引入 `torch`/`torchaudio`/`pyannote.audio` 等較重的相依套件,且需要使用者額外去 Hugging Face 接受授權、產生 token 才能運作。比照現有 `VAD_FILTER` 的模式,新增功能不應該讓既有使用者在沒有設定新環境變數的情況下,行為或效能無預警改變。`main.py` 讀取 `SPEAKER_DIARIZATION_ENABLED`(預設 `false`)與 `HUGGINGFACE_TOKEN`,傳給 `transcribe_file()` 再傳給 worker 的命令列參數,與現有 `vad_filter` 的傳遞方式一致。

### 語者分離失敗時退化成純逐字稿,不讓轉錄整體失敗

現有 `local-transcription` 規格已經要求「轉錄失敗要記錄原因、不中斷其他檔案處理」,但語者分離是轉錄「之後」的加值步驟 —— 沒有語者標籤的逐字稿仍然是可用的成果。因此 `diarize.py` 拋出的例外(缺 token、模型下載失敗、GPU 記憶體不足跑不動額外的分離模型等)由 `_transcribe_worker.py` 捕捉,寫一筆警告到 progress 檔(不中斷),並回傳沒有語者標籤的逐字稿,讓整個轉錄步驟依然回傳成功。這比「語者分離失敗就整個轉錄失敗」更符合使用者預期:寧可拿到沒有語者標記的逐字稿,也不要因為一個加值功能失敗就要重跑一次耗時的轉錄。

### 語者標籤以純文字前綴方式寫入逐字稿字串,不改變逐字稿的資料型別

延續現有架構,`_transcribe_worker.py` 最終仍然印出 `{"transcript": "..."}` 這樣的單一字串 JSON,`transcribe.py`、`main.py`、`notion_agent.py` 的介面完全不用變動。語者標籤的呈現方式是把每個語句片段前面加上 `[語者 A] `、`[語者 B] ` 這樣的前綴,片段之間用換行分隔(未啟用語者分離時維持現有的無前綴純文字,行為不變)。這樣既有的 Notion 逐字稿 toggle 區塊、Claude 結構化 prompt 都不需要改介面,只是內容多了語者前綴。

## Implementation Contract

**行為(Behavior)**

- 當 `SPEAKER_DIARIZATION_ENABLED=true` 且 `HUGGINGFACE_TOKEN` 已設定時,轉錄完成後回傳的逐字稿字串,每個語句片段前面帶有 `[語者 A]`、`[語者 B]`(依偵測到的語者數自動增加字母)這樣的標籤前綴,片段間以換行分隔
- 當 `SPEAKER_DIARIZATION_ENABLED` 未設定或為 `false`(預設)時,逐字稿字串與現行行為完全一致(無語者前綴、無換行片段化的額外格式變動)
- 當語者分離已啟用但執行過程中發生任何例外(缺 token、模型下載失敗、pyannote 執行期錯誤等),轉錄步驟 SHALL 仍回傳成功,逐字稿內容退化為沒有語者前綴的純文字(等同關閉語者分離時的格式),並在 `data/pipeline.log` 留下警告訊息說明語者分離失敗的原因
- 轉錄進度檔(`data/transcribe_progress.json`)在語者分離執行期間,`phase` 欄位值為 `"diarizing"`;`progress.bat` 的 `_render()` 需新增對應分支顯示中文狀態文字(例如「語者分離中: {filename}」),而不是落入現有的「狀態不明」預設分支

**介面/資料形狀(Interface / data shape)**

- `src/diarize.py` 提供一個函式,簽章大致為:
  `diarize_segments(audio_path: str | Path, segments: list, hf_token: str, device: str) -> list`
  輸入是 whisperx 對齊後的 segment 列表(含 start/end/text),輸出是相同結構但每個 segment 多一個 `speaker` 欄位(字串,例如 `"SPEAKER_00"`);函式在任何失敗情況下 SHALL 拋出例外(不吞錯誤、不回傳空結果),由呼叫端(`_transcribe_worker.py`)決定如何退化
- `_transcribe_worker.py` 新增一個把「speaker 標籤的 segment 列表」轉成「帶 `[語者 X]` 前綴的單一逐字稿字串」的組裝邏輯:`SPEAKER_00` → `語者 A`、`SPEAKER_01` → `語者 B`,以此類推(依首次出現順序對應字母,不依賴 pyannote 標籤數字本身的順序意義)
- `src/transcribe.py` 的 `transcribe_file()` 新增 `diarization_enabled: bool = False` 與 `hf_token: str | None = None` 兩個參數,透傳給 worker 命令列(比照現有 `vad_filter` → `--no-vad` 的做法,新增類似 `--diarize` 旗標 + token 透過環境變數而非命令列參數傳給 worker,避免 token 出現在行程命令列/記錄檔裡)
- `src/main.py` 的 `_load_config()` 新增讀取 `SPEAKER_DIARIZATION_ENABLED`(布林,預設 false)與 `HUGGINGFACE_TOKEN`(字串,可為空,但若 `SPEAKER_DIARIZATION_ENABLED=true` 且此值為空,視為設定錯誤,啟動時 SHALL 報錯並終止,比照現有必要設定缺漏的檢查方式)

**驗收標準(Acceptance criteria)**

- `tests/test_diarize.py`:針對 `diarize_segments()` 的單元測試,涵蓋成功標註語者、以及輸入/呼叫失敗時確實拋出例外(mock pyannote/whisperx 呼叫,不需要真的下載模型或跑 GPU)
- 既有 `tests/test_transcribe.py`、`tests/test_progress_reporting.py` 需擴充涵蓋:`transcribe_file()` 新增參數的透傳行為、`show_progress._render()` 對 `diarizing` phase 的輸出文字
- 手動驗證(需要真實 HF token 與 GPU,非自動化測試):對一段已知有兩位語者的錄音,啟用 `SPEAKER_DIARIZATION_ENABLED` 跑一次,確認 Notion 頁面的逐字稿 toggle 區塊出現 `[語者 A]`/`[語者 B]` 前綴且與實際發言者大致對應;關閉功能後跑同一份錄音,確認逐字稿格式與 change 之前完全一致

**範圍邊界(Scope boundaries)**

- **In scope**:worker 端的語者分離執行與失敗退化、逐字稿文字前綴組裝、進度檔新增 phase 與檢視器顯示、新環境變數的讀取與必要性檢查、`requirements-transcribe.txt` 新增相依套件、`.env.example` 與 README 文件更新
- **Out of scope**:Notion 資料庫 schema 或頁面屬性變更、Claude 結構化 prompt 邏輯變更、語者姓名辨識、事後手動修正語者、指定語者人數上限/下限等進階設定、任何 UI(這是純命令列/排程流程)

## Risks / Trade-offs

- [新增 `torch`/`torchaudio`/`pyannote.audio` 等較重依賴,`.venv-transcribe` 安裝體積與時間增加,且需要相容的 CUDA 版本] → 功能預設關閉,只有明確啟用的使用者需要承擔這個安裝成本;`requirements-transcribe.txt` 更新時保留現有 faster-whisper 版本相容性,若 whisperx 對 ctranslate2/faster-whisper 版本有特定要求,以 whisperx 官方相容矩陣為準
- [pyannote gated model 需要使用者手動到 Hugging Face 接受條款、生成 token,屬於一次性人工設定,容易漏掉或搞錯] → README 新增明確的設定步驟說明(需接受哪些模型的授權條款、token 存放位置);`main.py` 在 `SPEAKER_DIARIZATION_ENABLED=true` 但缺 token 時明確報錯,不要讓使用者跑到轉錄中途才發現設定不完整
- [語者分離會增加每個錄音的處理時間(對齊 + 分離模型推論),90 分鐘訪談的實際耗時未知] → 沿用現有 `LOCK_STALE_SECONDS`(4 小時)機制已经能容忍較長的單次執行;若之後發現耗時嚴重影響排程週期,可再開 change 討論非同步/背景處理
- [pyannote 自動偵測語者數在雜訊多、聲音重疊的錄音中可能誤判語者數量或錯亂標籤] → 這是模型本身的已知限制,不在本 change 解決範圍內;README 的限制說明需誠實註明「語者標籤為自動偵測、可能有誤,非逐字精準保證」
