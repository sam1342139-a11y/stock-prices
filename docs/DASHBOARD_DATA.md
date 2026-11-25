# 股票交易助手：儀表板資料檔（docs/DASHBOARD_DATA.md）

> 由 `tw-models/build_dashboard.py` 組成一個 JSON 檔，儀表板排程（平日 19:20、23:20）上傳到股票交易助手頁面。
> 只有公開市場資料，**不含任何持股、觀察清單、帳本**。頁面由理專助手負責，工程師只負責這個資料檔。

## 檔案結構（最上層）
| 段落 | 來源檔 | 更新時間（台灣） | 內容 |
|---|---|---|---|
| `regime` | `tw-models/latest/regime_tw.json` | 交易日 18:30 | 台股水位燈號 |
| `paper`、`nav` | `tw-models/paper/` | 交易日 18:30 | 模擬資金 |
| `swing`、`long`、`core` | `tw-models/latest/` | 週五（長期每季） | 波段、長期名單、七三組合 |
| `screen` | `tw-models/latest/old_screen.json` | 交易日 18:30 | 33 檔觀察名單（四個條件評分） |
| `after_market` | `tw-models/latest/after_market.json` | 交易日 18:30 | 盤後籌碼 |
| **`stock_analysis`** | `tw-models/latest/stock_analysis.json` | 交易日 18:30 | **33 檔大型股＋0050 個股分析（新）** |
| **`stock_news`** | `news/tw_stocks.json` | 每天 06:20 | **33 檔＋0050 近 7 天新聞標題（新）** |
| **`us_regime`** | `regime/regime.json` | 週二～六 06:05 | **美股市場風險燈號（新）** |
| `closes` | `tw/closes/*.csv` | 交易日 17:30 | 上市全部證券每日收盤價（自 2026-10-01） |

- 每一段都有 `generated_at_utc`、`problems`、`sources`（`closes` 除外，它是由 CSV 組成）。`problems` 不是空的就代表該段有缺漏，頁面應該顯示提醒。
- 大小：不含 `closes` 約 450 KB；`closes` 每多一個交易日約多 8 KB。

## `stock_analysis`
- `date`：資料日期；`codes`：34 個代號（固定公開名單）；`stocks`：`{代號: 個股物件}`。

| 欄位 | 說明 |
|---|---|
| `code`、`name`、`date`、`close` | 代號、名稱、資料日期、收盤價 |
| `chart.dates`／`close`／`ma60`／`ma240` | 近一年（約 250 個交易日）收盤價與 60／240 日均線，四個陣列一一對應 |
| `ma60`、`ma240` | 最新一天的均線 |
| `high_52w`、`high_52w_date`、`low_52w`、`low_52w_date` | 52 週高低與日期 |
| `fib_levels` | 黃金分割位置：`ratio` 0（52 週高點）、0.236、0.382、0.5、0.618、0.786、1（52 週低點）對應的 `price` |
| `fib_position_pct` | 目前收盤從 52 週高點回落了高低差的幾 %（0 = 在高點、100 = 在低點） |
| `pe`、`pe_5y_percentile` | 本益比、在近 5 年每日本益比中的百分位（越高越貴；只算正值） |
| `dividend_yield_pct`、`pb` | 殖利率（%）、股價淨值比 |
| `monthly_revenue` | 近 24 個月：`month`、`revenue`（元）、`yoy_pct`（年增率 %） |
| `quarters` | 近 8 季：`period`（如 2026Q3）、`eps`、`gross_margin_pct`、`operating_margin_pct`、`net_margin_pct`（0050 沒有） |
| `institutional_20d` | 近 20 個交易日：`date`、`foreign_lots`（外資，張）、`trust_lots`（投信，張） |
| `foreign_20d_lots`、`trust_20d_lots` | 20 日合計 |
| `news` | 近 7 天新聞標題：`title`、`url`、`source`、`published_tw`（組檔時從 `stock_news` 併入） |

均線與 52 週高低用還原權息價計算後換回目前價位，除權息不會造成假跌破。

### 範例（2330，陣列只列前幾筆）
```json
{
 "code": "2330",
 "name": "台積電",
 "date": "2026-11-20",
 "close": 2000.0,
 "chart": {
  "dates": [
   "2025-11-10",
   "2025-11-11",
   "…"
  ],
  "close": [
   1475.0,
   1465.0,
   "…"
  ],
  "ma60": [
   1318.2,
   1322.69,
   "…"
  ],
  "ma240": [
   1096.31,
   1098.17,
   "…"
  ]
 },
 "ma60": 2392.24,
 "ma240": 2102.78,
 "high_52w": 2590.0,
 "high_52w_date": "2026-10-06",
 "low_52w": 1358.31,
 "low_52w_date": "2025-11-24",
 "fib_levels": [
  {
   "ratio": 0,
   "price": 2590.0
  },
  {
   "ratio": 0.236,
   "price": 2299.32
  },
  {
   "ratio": 0.382,
   "price": 2119.5
  },
  {
   "ratio": 0.5,
   "price": 1974.16
  },
  {
   "ratio": 0.618,
   "price": 1828.82
  },
  {
   "ratio": 0.786,
   "price": 1621.89
  },
  {
   "ratio": 1,
   "price": 1358.31
  }
 ],
 "fib_position_pct": 47.9,
 "pe": 20.36,
 "pe_5y_percentile": 38.0,
 "dividend_yield_pct": 1.1,
 "pb": 7.41,
 "monthly_revenue": [
  {
   "month": "2026-09",
   "revenue": 511857399000.0,
   "yoy_pct": 54.65
  },
  {
   "month": "2026-10",
   "revenue": 586890319000.0,
   "yoy_pct": 59.71
  },
  "…（共 24 個月）"
 ],
 "quarters": [
  {
   "period": "2026Q3",
   "eps": 29.43,
   "gross_margin_pct": 66.41,
   "operating_margin_pct": 58.65,
   "net_margin_pct": 51.09
  },
  "…（共 8 季）"
 ],
 "institutional_20d": [
  {
   "date": "2026-11-19",
   "foreign_lots": -8635,
   "trust_lots": 1579
  },
  {
   "date": "2026-11-20",
   "foreign_lots": -11863,
   "trust_lots": -3848
  },
  "…（共 20 天）"
 ],
 "foreign_20d_lots": -184038,
 "trust_20d_lots": 40063,
 "news": [
  {
   "title": "（範例）台積電……",
   "url": "https://news.cnyes.com/news/id/…",
   "source": "鉅亨網 台股",
   "published_tw": "2026-11-25 14:05"
  }
 ]
}
```

## `us_regime`
即 `regime/regime.json`：7 項指標（VIX、SPY 相對 200 日均線、10 年減 3 個月利差、高收益債利差、12 個月衰退機率、Sahm 規則、SOXX 相對 SPY），每項 0 綠／1 黃／2 紅，總分 0～3 綠、4～6 黃、7 以上紅。規則見 `docs/REGIME.md`。

## `stock_news`
即 `news/tw_stocks.json`：`by_code`（`{代號: [新聞]}`）、`names`、`keep_days`（7）。來源是鉅亨網台股與中央社財經，用公司名稱或代號比對標題，可能有少數誤判。
