# stock-prices（股票價格）

這是我的工作用專案：**每個交易日自動抓取美股收盤價**，提供給 FCN 程式讀取使用。

---

## 📂 目錄：每個檔案在做什麼

| 檔案 / 資料夾 | 用途 | 可以手動改嗎 |
|---|---|---|
| `README.md` | 就是這份說明文件（中文目錄） | 可以 |
| `CLAUDE.md` | Claude 的工作規則（一律用繁體中文回覆、不放客戶資料等） | 可以 |
| `latest.json` | **每日股價資料**，FCN 程式讀的就是這個檔案 | ❌ 不要改，系統會自動更新；**位置也不要移動**，否則 FCN 程式會讀不到 |
| `fetch_prices.py` | 抓股價的程式，從 Twelve Data 下載收盤價後寫進 `latest.json` | 要改請找 Claude |
| `.github/workflows/update-prices.yml` | 自動排程設定：決定**什麼時候**執行抓股價程式 | 要改請找 Claude |
| `macro/` | **總經數據**：利率、公債殖利率、VIX、CPI、失業率、美元兌台幣，每日自動更新，詳見資料夾內的 README | 要改請找 Claude |
| `.github/workflows/update-macro.yml` | 總經數據的自動排程 | 要改請找 Claude |
| `fcn-monitor/` | **FCN 每日燈號監控**：算出每檔商品離敲出、敲入的距離，寄 Email 通知；商品條件存在 GitHub 密鑰，詳見資料夾內的 README | 要改請找 Claude |
| `.github/workflows/fcn-monitor.yml` | FCN 燈號監控的自動排程（每日股價抓完後接著執行） | 要改請找 Claude |
| `tw/` | **台股每日資料**（證交所上市全市場）：收盤、成交量、本益比、殖利率、三大法人、月營收 | ❌ 系統自動更新 |
| `calendar/` | **財報日曆**：26 檔美股的財報日期。**自動排程已停用**（改用財經M平方的財經日曆），只能手動執行 | 要改請找 Claude |
| `fx/` | **匯率位置**：美元、澳幣、日圓兌台幣與澳幣兌美元，在近 1／3／5 年的高低位置 | ❌ 系統自動更新 |
| `regime/` | **市場風險燈號**：7 項指標的綠／黃／紅燈號與總分，規則見 `docs/REGIME.md` | ❌ 系統自動更新 |
| `tw-models/` | **台股模型**：歷史資料、回測引擎、台股水位燈號、波段名單（每週五）、長期名單（每季），規則見 `docs/TW_MODELS.md`；最新名單在 `tw-models/latest/`（swing.json、long.json、core_satellite.json） | ❌ 系統自動更新 |
| `lib/` | 各程式共用的小工具 | 要改請找 Claude |
| `docs/SETUP.md` | **完整系統設定說明**（排程、資料來源、密鑰名稱、待辦），每次修改都會更新 | 要改請找 Claude |
| `docs/REGIME.md` | 市場風險燈號的計分規則 | 要改請找 Claude |
| `docs/DATA_CHECKS.md` | 資料合理性檢查的規則（數字異常時不發布、開 issue 通知） | 要改請找 Claude |
| `docs/TW_MODELS.md` | 台股模型的完整規則 | 要改請找 Claude |
| `docs/PAPER.md` | **模擬資金追蹤**（七三組合、長期、0050 各 100 萬元，每個交易日更新） | ❌ 程式產生 |
| `docs/BACKTEST_quantstats.md` | **進階績效指標**：七三組合、長期、0050 的月報酬熱力圖、索提諾值、最長回撤天數等 | ❌ 程式產生 |
| `docs/BACKTEST_*.md` | 各模型回測報告（手機好讀，含淨值曲線圖） | ❌ 程式產生 |

> 未來新增功能時，每個功能會各放一個資料夾，並在這張表裡補上說明。晨間簡報、新聞、財經日曆由「理專助手」專案負責。

---

## ⏰ 自動更新時間

- **台灣時間每週二到週六早上**：06:30 美股股價 → 06:40 總經數據 → 06:45 匯率位置 → 07:00 市場風險燈號
- **台股**：平日 17:30（沒抓到當天資料，18:00 再試一次）
- 完整時間表見 `docs/SETUP.md`。
- 想立刻手動更新：GitHub 上方點 **Actions** → 左邊點 **update-prices** → 右邊點 **Run workflow**。
- 美國假日休市時沒有新資料，`latest.json` 會維持前一個交易日的價格。

---

## 📈 追蹤的股票（共 26 檔）

AAPL、AMAT、AMD、ARM、ASML、ASX、AVGO、AMZN、CRWD、GOOG、INTC、KLAC、LITE、MSFT、MU、NVDA、SNDK、SOXX、SPCX、SPY、TSLA、TSM、ENTG、NBIS、BE、SOXL

要新增或刪除股票，請找 Claude 修改 `fetch_prices.py`。

---

## 📄 `latest.json` 裡面有什麼

| 欄位 | 意思 |
|---|---|
| `complete` | `true` 表示 26 檔都抓成功；`false` 表示有缺漏，這時 `prices` 會是空的 |
| `asof` | 價格日期（美東時間的交易日） |
| `fetched_at_utc` | 抓取時間（UTC，台灣時間要再加 8 小時） |
| `problems` | 如果有抓失敗的股票，會列在這裡 |
| `prices` | 最新一天每檔股票的收盤價 |
| `history` | 最近幾個交易日的收盤價（只保留 26 檔都有資料的日期） |

---

## 🔑 需要的設定

- **`TWELVEDATA_KEY`**：Twelve Data 的 API 金鑰，存放位置在 GitHub → Settings → Secrets and variables → Actions。
- 這個金鑰**絕對不要**直接寫在任何檔案裡，因為這個專案是公開的。

---

## ⚠️ 重要提醒

這個專案是**公開的**，任何人都看得到。**請勿放入客戶姓名、帳號、持倉等個人資料。**

---

## 📝 修改紀錄

每一次修改都有一張「修改申請單」（Pull Request），裡面用中文寫了改了什麼、為什麼改。
查看方式：GitHub 上方點 **Pull requests** → 點 **Closed**，就能看到所有歷史修改。
