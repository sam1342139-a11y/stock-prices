# macro/（總經數據）

每個交易日自動抓取美國主要總經指標與台幣匯率。

| 檔案 | 用途 |
|---|---|
| `fetch_macro.py` | 抓資料的程式 |
| `macro.json` | 抓下來的結果（系統自動更新，不要手動改） |

## 更新時間
台灣時間**週二到週六早上 06:40**（美股收盤後），由 `.github/workflows/update-macro.yml` 自動執行。
想立刻手動更新：GitHub 上方點 **Actions** → **update-macro** → **Run workflow**。

## 追蹤的指標

| 代號 | 指標 | 怎麼看 |
|---|---|---|
| DFF | 聯邦基金有效利率 | 美國聯準會政策利率的實際水準 |
| DGS2 | 美國 2 年期公債殖利率 | 反映市場對未來升降息的預期（來源：美國財政部） |
| DGS10 | 美國 10 年期公債殖利率 | 長期利率指標，影響股市估值（來源：美國財政部） |
| T10Y2Y | 10 年減 2 年利差 | 負值代表殖利率倒掛，常被視為衰退警訊 |
| VIXCLS | VIX 恐慌指數 | 20 以下偏平靜，30 以上代表市場恐慌（來源：CBOE） |
| CPIAUCSL | 美國 CPI | 每月公布；`yoy_pct` 欄位是年增率 |
| UNRATE | 美國失業率 | 每月公布 |
| DEXTAUS | 美元兌台幣（FRED） | 每週更新，比即時匯率晚幾天 |
| USDTWD | 美元兌台幣（Twelve Data） | 每日收盤匯率 |

## `macro.json` 欄位
每個指標都有：`name` 名稱、`date` 資料日期、`value` 最新值、`prev` 前一筆、`change` 變動、`history` 最近 30 筆，以及 `source` 實際資料來源。
`problems` 列出抓取失敗的指標，正常時是空的。

## 資料來源
- **DGS2、DGS10**：美國財政部 Daily Treasury Par Yield Curve（官方，前一交易日）
- **VIXCLS**：CBOE 官方 VIX 每日收盤歷史檔
- 以上三項官方來源抓不到時，**自動退回 FRED**，`source` 會顯示 `FRED`，原因記在 `problems`
- 其餘指標：FRED（美國聯準會聖路易分行，免金鑰）；USDTWD：Twelve Data
