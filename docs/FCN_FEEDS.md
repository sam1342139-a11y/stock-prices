# FCN 晨間用資料檔（docs/FCN_FEEDS.md）

> 目的：把 FCN 晨間更新裡 Claude 每天自己做的檢查、查詢，改成 GitHub Actions 程式先做好，晨間只讀結果，降低 AI 用量。
> 原則：只新增檔案，`latest.json` 等現有檔案的格式、路徑、更新時間都不變；不放任何客戶或持倉資料。

## 一、收盤價檢查檔 `fcn/prices_checked.json`
- **更新時間**：和 `latest.json` 同一個排程（`update-prices`，平日 22:30 UTC＝台灣 06:30 起），`latest.json` 抓完後立刻產生。
- **程式**：`fcn/check_prices.py`

| 欄位 | 說明 |
|---|---|
| `status` | `ok`／`fail`。`fail` 時**不要寫入價格** |
| `fail_reasons` | 失敗原因（中文），`ok` 時是空陣列 |
| `asof` | 這次價格的日期（美股交易日） |
| `fetched_at_utc` | `latest.json` 的抓價時間 |
| `compared_with` | 拿來比對終值的前一次：`asof`、`commit` |
| `prices` | 26 檔當日價格（暫定價，隔天以終值修正） |
| `corrections` | 終值修正清單：`ticker`、`date`、`old`（前一次暫定價）、`new`（終值） |
| `fill_days` | 前一次到這次之間，`history` 有、但沒被當作 asof 發布過的交易日：`date`、`prices` |
| `watch` | 單日漲跌超過 ±25% 的「請留意」：`ticker`、`date`、`prev_close`、`close`、`change_pct` |
| `history` | `latest.json` 的 history 原樣（約 6 個交易日） |
| `fx` | 國泰世華牌告即期買入：`date`、`time`、`source`、`USD`、`AUD`、`JPY`；抓不到為 `null`，原因在 `problems` |
| `generated_at_utc`、`problems`、`sources` | 共同欄位 |

**檢查規則**
1. 基本：`complete` 為 true、`problems` 空、剛好 26 檔且都是正數、`fetched_at_utc` 晚於 asof 當天 21:00 UTC。
2. 終值修正：這次 `history` 裡前一次 asof 那天的價格，和前一次的暫定價逐檔比。
   - 差 ≤0.01：一致，不列。
   - 差 >0.01 且 ≤0.5%：列入 `corrections`。
   - 差 >0.5%：`fail`。
   - 呈固定倍數（2、3、4、5、10…倍或其倒數，誤差 3% 內）：`fail`，寫「疑似拆合股」與倍數。
3. 單日漲跌超過 ±25%：列入 `watch`，不算失敗。

**晨間用法（建議）**：讀這個檔 → `status` 是 `ok` 才寫入 → 用 `corrections` 改前一天、`fill_days` 補缺的日子、`prices` 寫當天。

## 二、法說會行事曆 `earnings/calendar.json`
- **更新時間**：每天台灣 06:40（排程 `update-fcn-feeds`）；**程式**：`earnings/fetch_calendar.py`；**追蹤清單**：`earnings/watchlist.json`（要加代號就改這個檔）
- **範圍**：`latest.json` 的 26 檔＋台股 2330、2454、2317、2382、2303、3711。TSM＋2330、ASX＋3711 各合併成一筆；SPY、SOXX、SOXL 是 ETF，略過。
- **來源**：美股用 Nasdaq 財報行事曆（每天掃 3 天前到 10 週後）；台股用公開資訊觀測站「法人說明會一覽表」（上個月到下個月）。

| 欄位 | 說明 |
|---|---|
| `recent` | **最近 3 天內（含今天，台灣時間）已召開或已公布**的公司；晨間只在這裡有公司時才做研究 |
| `upcoming` | 今天之後的場次 |
| `all` | 全部場次 |
| 每筆 `ticker`、`name`、`market` | 代號（合併的寫成 `2330／TSM`）、名稱、美股／台股 |
| `period` | 美股：財報季末（如「財報季末 Oct/2026」）；台股：推估的季別（法說會月份的前一季） |
| `event` | `財報`（美股）、`法說會`、`受邀參加券商論壇`（台股；後者不是季度法說會，不列入 recent。判斷方式：季度法說會會上傳當天日期的新簡報，沒有新簡報或寫明受邀／參加的都算論壇） |
| `date`、`time` | **台灣日期**與時間；美股盤後公布的，台灣日期是隔天早上 |
| `confirmed` | `公司已公告`（台股，公開資訊觀測站）／`預估`（美股，Nasdaq 未標示是否公司確認） |
| `source` | 來源連結 |

查不到日期的代號寫在 `problems`，不估算。

## 三、新聞初篩 `news/raw.json`
- **更新時間**：每天台灣 06:40；**程式**：`news/fetch_news.py`；**名稱對照**：`news/aliases.json`
- **來源**：鉅亨網（美股、台股、外匯）、中央社財經 RSS、CNBC（Top News、Markets）RSS、MarketWatch RSS
- **時間範圍**：前一個美股交易日（台灣 06:00 起）到產出時間；週一從上週五 06:00 起。

| 欄位 | 說明 |
|---|---|
| `items` | 每則：`title`、`url`、`source`、`published_tw`（台灣時間）；標題提到 26 檔的另有 `tickers`。**不存內文** |
| `movers` | 26 檔單日漲跌超過 5%：`ticker`、`date`、`prev_close`、`close`、`change_pct`（`latest.json` 最後兩天） |
| `window_tw`、`count`、`count_with_tickers` | 時間範圍與則數 |

## 四、台股財報數字 `earnings/tw_financials.json`
- **更新時間**：每天台灣 06:40；**程式**：`earnings/tw_financials.py`；**範圍**：`earnings/watchlist.json` 的 `tw`
- **來源**：FinMind（公開資訊觀測站申報的財報）
- 每家公司 `quarters`（最近 8 季）：`period`、`revenue`（營收）、`gross_margin_pct`（毛利率）、`operating_margin_pct`（營業利益率）、`eps`、`inventory`（存貨）、`cogs`（營業成本）、`operating_cash_flow`（單季營業現金流，由年初累計數相減）、`inventory_qoq_pct`／`inventory_yoy_pct`（存貨季增／年增）、`inventory_days`（存貨週轉天數＝存貨÷當季營業成本×當季天數，**計算值**）、`inventory_days_qoq_pct`（天數季增）
- `monthly_revenue`（最近 12 個月）：`month`、`revenue`、`yoy_pct`
- 金額單位：新台幣元。

## 五、週一台股模型週報 `tw-models/latest/weekly_report.md`
- **更新時間**：每週一台灣 06:10（排程 `weekly-report`）；**程式**：`tw-models/weekly_report.py`
- 內容照抄現有檔案：水位燈號、總分、參考水位、紅黃燈指標；長期名單 8 檔與下次換股日；波段名單（預估停損價）；七三組合下次再平衡日；模擬資金三組的淨值、累計報酬、上週報酬、相對 0050。
- 「上週報酬」「相對 0050」由程式依 `tw-models/paper/nav.csv` 計算（檔案本身沒有這兩項）。
- 任一來源檔的 `problems` 以「資料檢查未通過」開頭 → 開頭寫「⚠️ 資料檢查未通過」與原因；其他 `problems`（例如「最新交易日不是週五」）寫成「⚠️ 資料提醒」，避免把一般提醒誤標成檢查失敗。

## 六、email 通知（不用 AI）
- **程式**：`lib/notify.py`；**排程**：`.github/workflows/notify.yml`，在其他排程跑完後自動執行。
- **寄信條件**（一般日子沒事不寄）：
  - 任何排程失敗（同一個排程連續失敗只寄第一次）
  - 台股水位燈號（`overall_light`）轉色
  - 長期名單換股（列出換入、換出）
  - 美股市場風險燈號變差（綠→黃、黃→紅、綠→紅）
  - 任何輸出檔新出現「資料檢查未通過」
  - 美股收盤價檢查（`fcn/prices_checked.json`）轉為 `fail`
- **帳密**：沿用 GitHub 密鑰 `GMAIL_USER`、`GMAIL_APP_PASSWORD`。收件人預設寄給 `GMAIL_USER` 自己；要改可新增密鑰 `MAIL_TO`（多個用逗號隔開）。
