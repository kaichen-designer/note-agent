## 1. 加入 .mkv 副檔名支援

- [x] 1.1 在 src/main.py 的 `AUDIO_EXTENSIONS` 常數加入 `.mkv`，實現 Video Container Recording Support 需求中「Stable MKV file is included for processing」的行為：掃描到穩定的 `.mkv` 檔案時會被納入待處理清單。驗證方式：在 WATCH_FOLDER_PATH 放入一個 `.mkv` 測試檔並執行兩次 `python src/main.py`（第一次建立快照、第二次判定穩定），確認第二次執行的 log 顯示該檔案被列入「本次掃描待處理」並進入轉錄流程，而非被忽略。

## 2. 驗證既有規則對 .mkv 同樣生效

- [x] 2.1 驗證 faster-whisper 能直接解碼 `.mkv` 音軌並輸出逐字稿，不需另外抽取音軌。驗證方式：以一個含語音內容的小型 `.mkv` 檔案手動執行 `python src/_transcribe_worker.py <mkv路徑> large-v3`，確認輸出的 JSON 含有非空的 `transcript` 欄位且不含 `error` 欄位。
- [x] 2.2 驗證成功處理的 `.mkv` 檔案會依 Video Container Recording Support 需求中「Successfully processed MKV file is archived」情境被歸檔。驗證方式：執行完整 pipeline 成功處理一個 `.mkv` 測試檔後，確認該檔案出現在監控資料夾的 已處理 子資料夾中，且 data/state.json 對應紀錄的 status 為 success。
- [x] 2.3 驗證 Video Container Recording Support 需求中「Unsupported video container remains excluded」情境：在監控資料夾放入一個 `.mov` 測試檔並執行 `python src/main.py`，確認該檔案未出現在 data/state.json 的處理紀錄中、未被搬移到 已處理 子資料夾，且未觸發轉錄。
