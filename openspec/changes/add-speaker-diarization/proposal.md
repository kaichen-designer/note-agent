## Why

多人訪談/會議錄音經過現有流程轉錄後,逐字稿是一整段連續文字,沒有標記「誰說了什麼」。使用者需要在整理訪談重點與行動項目時,能區分訪問者與受訪者(或多位與會者)的發言,而不是只能靠語意猜測。README 的已知限制已預留此擴充方向(若語者歸屬造成困擾,評估加入 pyannote/WhisperX),現在有實際的 1.5 小時訪談需求,值得動手做。

## What Changes

- 新增本機語者分離(speaker diarization)能力:轉錄流程改用 WhisperX(內部仍以 faster-whisper 做語音辨識,額外加上詞級時間對齊與 pyannote.audio 語者分離),為逐字稿的每個語句片段標註語者(語者 A / 語者 B / ...)。
- 語者分離預設關閉,需在 `.env` 設定 `SPEAKER_DIARIZATION_ENABLED=true` 並提供 `HUGGINGFACE_TOKEN`(pyannote 的語者分離模型是 gated model,需先在 Hugging Face 接受授權條款並產生 token)才會啟用,不影響現有使用者的預設行為。
- 語者分離失敗(例如缺 token、模型下載失敗、pyannote 執行期錯誤)時,轉錄步驟 SHALL 自動退回成不含語者標記的純逐字稿,不讓整個轉錄工作失敗。
- 轉錄進度檔新增 `diarizing` 階段,`progress.bat` 的即時進度顯示需能呈現這個階段而不是顯示「狀態不明」。
- 語者分離的推論(對齊、分離模型執行)全程在本機執行,只有模型權重會在第一次使用時從 Hugging Face 下載;錄音音檔本身不會上傳到任何外部服務,與現有「本地轉錄不外流音檔」的設計原則一致。

## Non-Goals (optional)

（本 change 會產出 design.md,Non-Goals 記錄於 design.md 的 Goals/Non-Goals 段落,此處留空)

## Capabilities

### New Capabilities

- `speaker-diarization`: 本機語者分離能力 —— 在轉錄流程中識別錄音裡的不同語者,將逐字稿片段標註語者標籤;預設關閉,可透過環境變數啟用;分離失敗時優雅退回純逐字稿,不影響轉錄成功與否;並在轉錄進度檔/檢視器中反映新增的處理階段。

### Modified Capabilities

(none)

## Impact

- Affected specs: speaker-diarization(新增)
- Affected code:
  - New:
    - src/diarize.py
    - tests/test_diarize.py
  - Modified:
    - src/_transcribe_worker.py
    - src/transcribe.py
    - src/main.py
    - src/show_progress.py
    - requirements-transcribe.txt
    - config/.env.example
    - README.md
  - Removed: (none)
