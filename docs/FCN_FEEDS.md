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
