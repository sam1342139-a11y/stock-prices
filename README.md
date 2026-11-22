# stock-prices（股票價格）

這是我的工作用專案：**每個交易日自動抓取美股收盤價**，提供給 FCN 程式讀取使用。

---

## 📂 目錄：每個檔案在做什麼

| 檔案 / 資料夾 | 用途 | 可以手動改嗎 |
|---|---|---|
| `README.md` | 就是這份說明文件（中文目錄） | 可以 |
| `latest.json` | **每日股價資料**，FCN 程式讀的就是這個檔案 | ❌ 不要改，系統會自動更新；**位置也不要移動**，否則 FCN 程式會讀不到 |
| `fetch_prices.py` | 抓股價的程式，從 Twelve Data 下載收盤價後寫進 `latest.json` | 要改請找 Claude |
| `.github/workflows/update-prices.yml` | 自動排程設定：決定**什麼時候**執行抓股價程式 | 要改請找 Claude |

> 未來新增功能時，每個功能會各放一個資料夾，例如 `fcn-monitor/`（FCN 燈號監控）、`macro/`（總經數據）、`briefing/`（晨間簡報），並在這張表裡補上說明。

---

## ⏰ 自動更新時間

- **台灣時間每週二到週六早上 06:30** 自動執行，也就是美股每個交易日收盤後。
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
