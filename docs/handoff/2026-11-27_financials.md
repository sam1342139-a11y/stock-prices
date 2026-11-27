# 交接：財報資料檔（格式同 CoreWeave 圖表頁）

狀態：**第一階段（台股）完成，等合併**；第二階段（美股，SEC）待做　｜　建立：2026-11-27

## 決定（理專助手申請、使用者同意）
- 追蹤清單另開 `financials/watchlist.json`（不動 FCN 晨間用的 `earnings/` 那份）：2330、2454、2317、2308、2382。
- 輸出 `financials/tw/<代號>.json`、`financials/us/<代號>.json`，`{rows, meta}`，一季一列由舊到新，至少 12 季，查不到填 null。欄位名稱照 CoreWeave 範本，另加 period_end、fiscal_label、inventory、receivables、cogs、total_liabilities、eps_diluted、revenue_qoq_pct、inventory_days、台股 monthly_revenue。
- 單位：美股百萬美元、台股百萬新台幣。兩階段各一張申請單。

## 第一階段（台股）
- `financials/tw_fetch.py`（FinMind 三表＋月營收），排程 `update-financials` 每天 18:50；手動執行可輸入代號臨時查詢。
- 試跑：5 檔都 16 季、problems 空；台積電 26Q3 現金流與月營收加總都和季數字一致。
- 台股限制：利息費用取自現金流量表調整項；`eps_diluted` 來源沒有（另給 `eps_basic`）；`op_lease`、`backlog` 為 null。

## 第二階段（美股）待做
- SEC companyfacts（data.sec.gov），先試 NVDA、CRWV；Q4 = 全年 − 前三季（標註計算值）；CRWV 上市較晚可能不足 12 季。
- SEC 要求的聯絡資訊用專案 GitHub 網址，不放個人資料。
