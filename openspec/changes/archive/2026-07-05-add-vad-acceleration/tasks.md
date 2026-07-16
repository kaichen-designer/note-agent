## 1. VAD 靜音過濾(Silence Skipping Via Voice Activity Detection)

- [x] 1.1 實現 Silence Skipping Via Voice Activity Detection 的參數鏈:`config/.env.example` 加入 `VAD_FILTER=true` 與說明註解;`src/main.py` 的 `_load_config()` 讀取 `VAD_FILTER`(預設 true)並傳給 `transcribe_file()`;`src/transcribe.py` 的 `transcribe_file()` 新增 `vad_filter` 參數並以 CLI 參數傳給 worker;`src/_transcribe_worker.py` 解析參數並在 `model.transcribe()` 帶入 `vad_filter`。驗證:單元測試確認 worker 命令組裝在啟用/停用兩種情境下正確傳遞旗標
- [x] 1.2 實測 VAD enabled by default 與 VAD disabled via environment variable 兩情境:用 `tests/fixtures/test_speech.wav`(tiny model)分別以預設(VAD開)與 `VAD_FILTER=false` 各跑一次轉錄,確認兩者皆成功產出逐字稿且包含預期關鍵字,並確認進度檔 percent 最終為 100 且未超過 100(Progress reporting remains valid with VAD)。驗證:兩次轉錄皆 success 且逐字稿含 "budget meeting" 關鍵字
