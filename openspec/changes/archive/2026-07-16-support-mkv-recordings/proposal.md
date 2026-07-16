## Why

目前監控資料夾僅依副檔名（`.m4a` `.mp3` `.wav` `.aac` `.ogg` `.flac` `.wma` `.mp4`）判斷是否為可處理的錄音檔。部分裝置或錄影 App 會把錄音內容以 `.mkv` 影片容器格式同步到 Google Drive 監控資料夾，這類檔案目前不在支援清單內，掃描器會直接忽略它們，永遠不會被轉錄、結構化或寫入 Notion。

## What Changes

- 將 `.mkv` 加入可處理的錄音副檔名清單，使監控/轉錄流程能一併抓取 Google Drive 同步資料夾中的 `.mkv` 檔案。
- `.mkv` 檔沿用既有的兩階段穩定偵測、轉錄、結構化、Notion 寫入、失敗重試、成功歸檔等既有規則，不新增任何專屬於 `.mkv` 的特殊處理路徑。

## Non-Goals

- 不新增從 mkv 額外抽取/轉檔音軌的前處理步驟：faster-whisper 底層解碼器可直接讀取 mkv 容器中的音訊軌，不需要另外呼叫 ffmpeg 抽取成獨立音檔。
- 不擴充支援其他影片容器格式（如 .mov、.avi、.webm），此變更僅新增 .mkv。
- 不新增 Google Cloud Storage 或 Google Drive API 的直接串接；監控機制仍是本機的 Google Drive for Desktop 同步資料夾（`WATCH_FOLDER_PATH`），不涉及雲端 API 呼叫。

## Capabilities

### New Capabilities

(none)

### Modified Capabilities

- `recording-ingestion`: 新增需求，將 `.mkv` 影片容器檔案視為可處理的錄音檔案類型，比照既有音訊格式套用相同的偵測、處理與歸檔規則

## Impact

- Affected specs: recording-ingestion
- Affected code:
  - Modified: src/main.py（`AUDIO_EXTENSIONS` 常數）
  - New: (none)
  - Removed: (none)
