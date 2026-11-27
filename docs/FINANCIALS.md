# 財報資料檔（docs/FINANCIALS.md）

> 給財報圖表頁用的季度財報數字（格式同 CoreWeave 圖表頁）。只有公開財報數字，不含任何客戶或持倉資料。

## 檔案
- 台股：`financials/tw/<代號>.json`（第一階段）
- 美股：`financials/us/<代號>.json`（第二階段，SEC 資料，另開申請單）
- 追蹤清單：`financials/watchlist.json`（和 FCN 晨間用的 `earnings/watchlist.json` 分開）
- 程式：`financials/tw_fetch.py`；排程：`update-financials`，每天台灣 18:50

**臨時查詢**：GitHub → Actions → update-financials → Run workflow，在「臨時查詢的台股代號」輸入（例如 `2603 2002`），跑完就會有 `financials/tw/2603.json`，不會改到追蹤清單。

## 格式
每檔一個 JSON：`{"rows": [...], "meta": [...]}`，一季一列、由舊到新，目前 16 季。查不到的欄位是 `null`，不會填 0。

### rows（和 CoreWeave 範本同名）
| 欄位 | 說明 |
|---|---|
| `quarter` | 例 `"26Q3"` |
| `revenue`、`gross`、`op_income`、`net_income` | 營收、毛利、營業利益、稅後淨利（合併） |
| `interest` | 利息費用（台股取自現金流量表調整項，換成單季） |
| `ocf` | 營業現金流（單季） |
| `capex` | 資本支出（單季、正數；取得不動產廠房設備） |
| `da` | 折舊＋攤銷（單季） |
| `debt` | 短期借款＋短期票券＋一年內到期長期負債＋長期借款＋應付公司債（帳面值） |
| `cash`、`equity`、`assets`、`ppe` | 現金及約當現金、權益總額、資產總額、不動產廠房設備 |
| `op_lease`、`backlog` | 台股來源沒有，`null` |

### 計算值
| 欄位 | 公式 |
|---|---|
| `fcf` | ocf − capex |
| `gross_margin_pct`、`op_margin_pct`、`net_margin_pct` | 三率（%，小數一位） |
| `revenue_yoy_pct`、`revenue_qoq_pct` | 營收年增、季增（%） |
| `debt_to_equity` | debt ÷ equity（權益 ≤ 0 為 null） |
| `interest_to_op_income` | interest ÷ op_income（營業利益 ≤ 0 為 null） |
| `inventory_days` | inventory ÷ cogs × 91 |

### 新增欄位
`period_end`（季底日期）、`fiscal_label`（例 `"FY26Q3"`；台股與日曆年相同）、`inventory`（存貨）、`receivables`（應收帳款，含關係人）、`cogs`（營業成本）、`total_liabilities`（負債總額）、`eps_diluted`（台股來源只有基本 EPS，為 null）、`eps_basic`（基本 EPS，元）、`monthly_revenue`（該季三個月的月營收，百萬元）。

### 單位
台股百萬新台幣（小數一位）；EPS 為元。

### meta
`[{label: 程式檔名, value: 程式全文, type: "code", lang: "python"}, {label: "資料來源"}, {label: "注意"}, {label: "problems"}, {label: "更新時間"}]`

## 範例（2330，26Q3 那一列，單位百萬新台幣）
```json
{"quarter":"26Q3","period_end":"2026-09-30","fiscal_label":"FY26Q3","revenue":1494243.3,"gross":992378.7,"cogs":501864.6,"op_income":876445.2,"interest":3159.9,"net_income":763340.8,"eps_diluted":null,"eps_basic":29.43,"ocf":919775.5,"capex":443206.0,"da":220203.6,"debt":1031579.2,"cash":3621894.0,"equity":7043227.4,"assets":10052887.5,"total_liabilities":3009660.1,"ppe":4526488.4,"op_lease":null,"backlog":null,"inventory":427753.4,"receivables":483557.0,"monthly_revenue":[467580.5,514805.3,511857.4],"fcf":476569.5,"gross_margin_pct":66.4,"op_margin_pct":58.7,"net_margin_pct":51.1,"revenue_yoy_pct":50.9,"revenue_qoq_pct":17.6,"debt_to_equity":0.15,"interest_to_op_income":0.004,"inventory_days":77.6}
```
