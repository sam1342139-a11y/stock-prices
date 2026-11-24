# 交接：FCN 晨間用的資料檔（收盤價檢查、法說會、新聞初篩、台股財報、週報、email 通知）

狀態：**待開工**（請在新對話執行；項目多，可分兩到三個申請單）　｜　建立：2026-11-24

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
