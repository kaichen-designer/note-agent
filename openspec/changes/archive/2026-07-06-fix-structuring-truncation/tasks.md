## 1. 截斷防護(Truncated Structuring Output Rejection)

- [x] 1.1 在 `src/notion_agent.py` 實現 Truncated Structuring Output Rejection:`max_tokens` 提高至 8192;`structure_note` 檢查回應 `stop_reason`,為 `max_tokens` 時拋出例外(由既有失敗處理標記 failed 並保留逐字稿重試);提示中加入輸出規模約束(摘要精簡、重點條列)。驗證:單元測試以 mock 回應模擬 stop_reason=max_tokens 確認拋出例外、模擬正常回應確認照常解析(Complete response is parsed normally)
- [x] 1.2 用當日 9392 字實際逐字稿重跑結構化,確認回應完整包含五個欄位且 stop_reason 不是 max_tokens;將缺少的「重點」與「行動項目」區塊補插入受影響的 Notion 頁面(摘要之後、逐字稿 Toggle 之前)。驗證:人工檢視該頁面兩個區塊出現且內容合理
