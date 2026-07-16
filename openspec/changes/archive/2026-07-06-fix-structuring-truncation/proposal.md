## Problem

長錄音(約 40 分鐘)的筆記在 Notion 上缺少「重點」與「行動項目」區塊,只有標題、摘要與逐字稿。管線沒有記錄任何錯誤,狀態顯示成功。

## Root Cause

結構化呼叫的 `max_tokens=2048` 對長會議的中文輸出而言太小:模型先寫標題與長摘要,額度耗盡時輸出被硬截斷(`stop_reason=max_tokens`),重點/行動項目/分類標籤等後段欄位遺失。先前為修復 KeyError 崩潰而加入的容錯解析,將缺少的欄位靜默補為空值,導致殘缺結果被當成成功寫入,頁面缺區塊且無任何錯誤紀錄。已用當日逐字稿重現並確認 `stop_reason=max_tokens`、輸出正好 2048 tokens、tool input 只剩前三個欄位。

## Proposed Solution

- 將結構化呼叫的 `max_tokens` 提高至 8192,給長筆記足夠的輸出空間
- 檢查回應的 `stop_reason`:若為 `max_tokens` 則視為結構化失敗並拋出例外,由既有的失敗處理機制標記 failed 並重試,不再靜默接受截斷的殘缺結果(容錯解析保留,作為其他異常的最後防線)
- 在提示中約束輸出規模(摘要精簡、重點條列),降低再次逼近上限的機率
- 修復當日受影響的 Notion 頁面:以已取回的逐字稿重跑結構化,把缺少的「重點」與「行動項目」區塊補插入既有頁面(不重新轉錄、不重建頁面)

## Success Criteria

- 用當日 9392 字逐字稿重跑結構化,回應完整包含標題/摘要/重點/行動項目/分類標籤,且 `stop_reason` 不是 `max_tokens`
- 模擬 `stop_reason=max_tokens` 的回應時,`structure_note` 拋出例外而非回傳殘缺結果(單元測試)
- 受影響頁面補上「重點」與「行動項目」區塊,位置在摘要之後、逐字稿 Toggle 之前

## Impact

- Affected specs: `notion-note-sync`(新增截斷防護需求)
- Affected code:
  - Modified:
    - src/notion_agent.py
    - tests/test_notion_agent.py
