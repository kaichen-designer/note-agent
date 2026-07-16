## Why

實測 41 分鐘會議錄音在本機 GPU 上轉錄耗時約 37 分鐘,轉錄是整條管線的效能瓶頸。faster-whisper 內建 Silero VAD(語音活動偵測),開啟後可自動跳過靜音片段,對停頓多的會議錄音可節省約 20~40% 轉錄時間,同時減少靜音段的幻聽誤轉。

## What Changes

- 轉錄 worker 開啟 faster-whisper 內建的 `vad_filter`(Silero VAD),自動跳過靜音片段,使用內建預設 VAD 參數不另行調參
- 新增 `.env` 設定 `VAD_FILTER`(預設 true),可停用以因應 VAD 誤砍小聲說話的情境(例如遠距離收音)
- `main.py` 讀取設定並經由 `transcribe.py` 以 CLI 參數傳遞給轉錄 worker
- 進度顯示邏輯不變:VAD 過濾後 segment 仍保留原始時間軸,既有百分比計算照常有效

## Non-Goals

- 不調整 `beam_size`、`condition_on_previous_text` 等以準確度換速度的參數(使用者明確排除)
- 不引入獨立的 VAD 前處理管線或新套件
- 不修改進度顯示邏輯

## Capabilities

### New Capabilities

(none)

### Modified Capabilities

- `local-transcription`: 新增靜音跳過需求——轉錄預設啟用 VAD 靜音過濾,可經環境變數停用,時間戳保持原始時間軸

## Impact

- Affected specs: `local-transcription` (modified)
- Affected code:
  - Modified:
    - src/_transcribe_worker.py
    - src/transcribe.py
    - src/main.py
    - config/.env.example
    - tests/test_transcribe.py
