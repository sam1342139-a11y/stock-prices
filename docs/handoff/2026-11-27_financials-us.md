# 交接：財報資料檔第二階段（美股）— 暫停

狀態：**程式寫好、還沒試跑成功，沒開申請單**　｜　分支 `claude/quirky-fermat-h74byi`　｜　2026-11-27

## 已完成（只在分支上，正式版沒動）
- `financials/us_fetch.py`：SEC companyfacts → `financials/us/<代號>.json`，格式同台股；Q2/Q3/Q4 用年初累計相減，相減的欄位列在 `derived_fields`；EPS 不相減（沒單季就留空）；`fiscal_label` 用公司會計年度。用假資料測過邏輯正確。
- `update-financials.yml` 加美股步驟與「臨時查詢的美股代號」欄；`watchlist.json` 的 us 加 NVDA、CRWV。
- 暫時用的 `probe-sources.yml`（改 us_fetch.py 推上分支就會試跑），合併前要刪。

## 卡住的地方
- SEC（www.sec.gov、data.sec.gov）回 403：開發環境被擋；GitHub Actions 也被擋，User-Agent 試過「專案網址」和「機器人通用信箱＋網址」都不行。
- 可能原因：SEC 擋 GitHub Actions 的網段，或要真實聯絡信箱。

## 下一步（擇一，請使用者決定）
1. 用 Twelve Data（已連線、有財報端點）取代 SEC，或只在 SEC 失敗時備援。
2. 使用者提供一個可公開的聯絡信箱給 SEC（放 GitHub Secrets，不寫進檔案）再試。
3. 先不做美股。
- 注意：這個分支的 `update-financials.yml` 若在 SEC 不通時合併，美股步驟每天會失敗（台股不受影響，但會收到失敗通知），所以不通之前**不要合併**。
