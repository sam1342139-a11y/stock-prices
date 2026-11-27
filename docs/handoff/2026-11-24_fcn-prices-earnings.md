# 交接：FCN 晨間用的資料檔（收盤價檢查、法說會、新聞初篩、台股財報、週報、email 通知）

狀態：**程式完成，等合併後實跑**（使用者 11/24 晚上指示在同一個對話做完）　｜　建立：2026-11-24

## 目的
降低 FCN 晨間更新的 AI 用量：把晨間 Claude 每天自己做的檢查、搜尋、整理，改成 GitHub Actions 程式產生檔案，晨間只讀結果。

## 原則（使用者指定）
- **只新增檔案**。`latest.json`、`macro/`、`regime/`、`fx/`、`tw-models/latest/after_market.json` 等現有檔案的格式、路徑、更新時間都不改。
- 不放任何客戶或持倉資料。FCN 系統本身（晨間排程、FCN 頁面）不動；晨間由使用者用測試版驗證後才接上。
- 輸出 JSON 照規則要有 `generated_at_utc`、`problems`、`sources`；抓不到不估算，寫進 problems。
- 26 檔＝`latest.json` 的 prices：AAPL AMAT AMD ARM ASML ASX AVGO AMZN CRWD GOOG INTC KLAC LITE MSFT MU NVDA SNDK SOXX SPCX SPY TSLA TSM ENTG NBIS BE SOXL。

## 建議分批
- 申請單 1：一（收盤價檢查）＋六（email 通知）
- 申請單 2：二（法說會行事曆）＋四（台股財報）
- 申請單 3：三（新聞初篩）＋五（週一週報）

## 進度（2026-11-24 夜）
- 六項程式都寫好，欄位說明在 `docs/FCN_FEEDS.md`。
- 來源實測（在 GitHub Actions 上跑）：
  - 國泰世華牌告匯率：**抓得到**，放在 `fcn/prices_checked.json` 的 `fx`
  - Nasdaq 財報日曆：抓得到（Twelve Data 財報日曆要付費方案，不用）
  - 公開資訊觀測站：舊網址被安全頁擋，改用 `mopsov.twse.com.tw` 可以抓
  - 鉅亨網 API、中央社 RSS、CNBC RSS、MarketWatch RSS：抓得到；Yahoo RSS 404 不用
  - 台股財報：FinMind（已有金鑰）
- **待辦**：合併後跑至少 3 個交易日，把結果補在下面「實跑結果」；之後由使用者安排晨間測試版接上。

## 實跑結果
### 2026-11-24 試跑（在 GitHub Actions 上跑分支程式，沒有存檔）
- `fcn/prices_checked.json`：status ok；終值修正 24 檔（11/20，都在 0.5% 內）；請留意 2 檔（NVDA +31.5%、SOXL +39.9%，11/23）；匯率 USD 32.85、AUD 21.78、JPY 0.2044（牌告 23:08）
- `news/raw.json`：360 則（11/23 06:00～11/24 23:08），106 則有標到持有標的；movers 20 檔（11/20→11/23 大漲日）
- `earnings/calendar.json`：33 筆。台股季度法說會判斷正確：2330 10/15、2303 10/28、3711 10/29、2454 10/30、2317 11/12；其餘是券商論壇。美股只查到 CRWD 11/23、AVGO 12/10、MU 12/18；其他美股在 70 天內 Nasdaq 還沒列日期，寫在 problems
- `earnings/tw_financials.json`：6 家都有 8 季資料，problems 空；2330 2026Q3 存貨週轉 78.4 天（季增 −8.4%）、單季營業現金流 9,198 億（已和年初累計數核對）
- 已知限制：2382 廣達的季度說明會是「受券商邀請」舉辦，會被歸成券商論壇

### 合併後的實跑（11/25、11/26 兩個早上，11/27 檢查）
| 檔案 | 實際完成時間（台灣） | 結果 |
|---|---|---|
| `fcn/prices_checked.json` | 11/26 06:44、11/27 06:44 | 兩天都 ok；11/26 美股感恩節休市，asof 維持 11/25；mismatch 0；匯率每天都抓到（11/27 USD 32.87、AUD 21.73）；`splits` 列 SOXX、SNDK，還原價各 111 天 |
| `news/raw.json` | 11/26 07:13、11/27 07:14 | 11/27：173 則，27 則標到持有標的，movers 1 檔；problems 空 |
| `news/tw_stocks.json` | 11/27 07:14 | 33 檔＋0050 已累積 27 則 |
| `earnings/calendar.json` | 11/26 07:13、11/27 07:17 | 34 筆；這兩天 recent 都是空的（沒有剛召開的法說會）；18 檔美股 70 天內 Nasdaq 還沒列日期 |
| `earnings/tw_financials.json` | 11/27 07:17 | 6 家，problems 空 |

- **時間問題**：GitHub 排程這兩天都延遲約 55～60 分鐘。收盤價、總經、匯率、燈號主排程在 06:41～06:52 完成，趕得上晨間 07:15；但新聞／法說會／財報（原本 06:20）拖到 07:13～07:17，**卡在晨間讀取時間**。已改成 05:20 主排程＋06:20 備援（申請單見 README 索引）。
- email 通知：這兩天沒有需要寄信的狀況（沒有失敗、沒有轉色、沒有 mismatch）。

## 一、收盤價檢查檔 `fcn/prices_checked.json`
- 跟 `latest.json` 同一個 Actions 產出（`.github/workflows/update-prices.yml`）。新增步驟，不改 latest.json 本身。
- 前一天的暫定價：從 git 歷史取前一版 latest.json，或另存 `fcn/prices_prev.json`。
- 檢查：
  1. 基本：complete 為 true、problems 空、剛好 26 檔且都 > 0、fetched_at_utc 晚於 asof 當天 21:00 UTC。
  2. 終值修正：今天的 history 和前一天的暫定價逐檔比對。差 ≤0.01 一致；>0.01 且 ≤0.5% 為終值修正（列代號、日期、舊值、新值）；任一檔 >0.5% 或呈固定倍數（疑似拆合股）→ fail，寫代號與倍數。
  3. 單日漲跌超過 ±25% 列入 watch。
  4. 缺的交易日若 history 有，列在 fill_days。
- 欄位：status（ok／fail）、fail_reasons、asof、prices、corrections、fill_days、watch、fx、generated_at_utc、problems、sources。
- 匯率試驗：國泰世華牌告 https://www.cathaybk.com.tw/cathaybk/personal/product/deposit/currency-billboard/ 即期買入 USD／AUD／JPY 與牌告時間。Actions 抓得到放 fx；抓不到（擋海外 IP、要 JS 等）就 fx = null 並寫 problems，回報使用者「繼續由 Claude 抓」。

## 二、法說會行事曆 `earnings/calendar.json`（每天）
- 設定檔 `earnings/watchlist.json`（使用者可加代號；四也共用）。
- 涵蓋：26 檔＋台股 2330、2454、2317、2382、2303、3711。TSM＋2330 合併、ASX＋3711 合併；ETF（SPY、SOXX、SOXL）略過。
- 每筆：ticker、name、market、period（如 2026Q4）、event（法說會／財報）、date、time（台灣時間）、confirmed（公司已公告／預估）、source。
- 台股來源：公開資訊觀測站法說會公告。美股來源需評估（Twelve Data 已有金鑰，先看 earnings 端點免費方案能否用，注意每日 800 次上限）。
- 查不到日期寫 problems，不要猜。
- `recent`：最近 3 天內（含今天，台灣時間）已召開或已公布的公司。晨間只在 recent 有公司時才做研究。

## 三、新聞初篩 `news/raw.json`（每天台灣 07:00 前）
- 收集前一個美股交易日到今天早上的新聞**標題**：鉅亨網（美股盤後、台股、匯率）、中央社財經；英文 RSS 來源自行評估（例如 Reuters／CNBC 有公開 RSS 者）。
- 每則只存：title、url、source、published（台灣時間）。**不存內文**。
- 標題提到 26 檔（代號或公司名，需建中英文名稱對照）的加 `tickers`。
- `movers`：26 檔單日漲跌超過 5% 的代號與漲跌幅（用 latest.json 最後兩天）。
- 先確認各來源有 RSS 或公開 API、Actions 連得到；連不到的寫 problems。

## 四、台股財報數字 `earnings/tw_financials.json`
- 範圍：2330、2454、2317、2382、2303、3711（可由 watchlist 增加）。
- 來源：公開資訊觀測站（或證交所 OpenAPI 的財報資料集，較穩定可優先評估）。已有 FinMind token，季報資料是否可用也可評估（台股模型已在用）。
- 每季：營收、毛利率、營業利益率、EPS、存貨、營業成本、營業現金流；保留最近 8 季。
- 程式先算：存貨季增／年增 %、存貨週轉天數（存貨÷當季營業成本×當季天數，標註「計算值」）、天數季增 %。
- 月營收：單月營收、年增率。
- 查不到的寫 problems。

## 五、週一台股模型週報 `tw-models/latest/weekly_report.md`（週一台灣 07:00 前）
- 照抄現有檔案、不重算：regime_tw.json（overall_light、總分、參考水位、紅黃燈指標，註明「回測擇時效果不明顯，僅供參考」）；long.json 8 檔（代號、名稱、一句上榜原因）與下次換股日；swing.json（標註「回測未勝過 0050，僅供觀察」，停損價寫「預估停損價」）；core_satellite.json 下次再平衡日；paper/latest.json 三組最新淨值、累計報酬、上週報酬、相對 0050 差距（檔案沒有的不自己算）。
- 任一來源檔 problems 不為空 → 開頭寫「⚠️ 資料檢查未通過」與原因。不加買賣建議。
- 注意：台股模型的 workflow 是平日晚上跑，週一早上要另加排程（週一 06:xx 台灣）。

## 六、email 通知（Actions 直接寄，不用 AI）
- 已有密鑰 `GMAIL_USER`、`GMAIL_APP_PASSWORD`（FCN 燈號信在用），沿用；帳密不寫進程式或檔案。收件人用 GMAIL_USER 本身或新增密鑰。
- 寄信條件（一般日子沒事不寄）：
  - 台股水位燈號（overall_light）轉色
  - 長期名單換股
  - 美股市場風險燈號（regime/regime.json）變差
  - 任何資料檢查未通過，或任何 Actions 失敗
- 做法建議：共用 `lib/notify.py`（smtplib），在各 workflow 失敗時以 `if: failure()` 呼叫；轉色比較用 git 前一版檔案。

## 七、待確認
- 晨間排程能否用 curl／git 直接下載 GitHub 的 JSON：工程師無法替那個排程的環境驗證。建議晨間測試版加一步 `curl -s https://raw.githubusercontent.com/sam1342139-a11y/stock-prices/main/latest.json` 試一次；成功就不用再用網頁讀取工具讀兩次核對。

## 完成的定義
- 各檔每天（週報每週一）自動產出，跑至少 3 個交易日，結果寫進本交接。
- 更新 `docs/SETUP.md`、`README.md` 目錄，開申請單。
- 回報使用者：檔案路徑、欄位說明、幾天的結果、匯率能否由 Actions 抓、哪些來源抓不到。
