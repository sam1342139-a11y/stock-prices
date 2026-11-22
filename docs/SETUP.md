# 系統設定說明（SETUP）

> 每次修改系統都要同步更新這份文件。最後更新：2026-11-22（停用財報日曆自動排程）

本存放庫 `sam1342139-a11y/stock-prices` 是**公開的**。
**只放市場公開資料，不放任何客戶或個人持股資料；不放密碼或 API 金鑰。**

## 共同規則
- **Claude 回覆給使用者的訊息一律用繁體中文**；程式碼與 commit 可用英文（完整工作規則見根目錄 `CLAUDE.md`）
- 只放市場公開資料，不放任何客戶或個人持股資料
- API 金鑰只從 GitHub Secrets 讀（程式透過環境變數取得）
- 檔名一律英文
- 每個輸出 JSON 都有 `generated_at_utc`、`problems`（抓不到的原因）、`sources`（來源名稱與網址）
- 抓不到不估算，寫進 `problems`
- 每支程式都能加 `--dry-run` 執行：輸出改寫到 `.dryrun/`（不進版控），不動正式檔案

## 系統架構

| 功能 | 執行時間（台灣） | 程式 | 輸出 |
|---|---|---|---|
| 每日美股收盤價 | 週二～六 06:30 | `fetch_prices.py` | `latest.json`（26 檔） |
| FCN 燈號監控 | 股價抓完後自動接著執行 | `fcn-monitor/monitor.py` | 寄 Email |
| 總經數據 | 週二～六 06:40 | `macro/fetch_macro.py` | `macro/macro.json` |
| **匯率位置** | 週二～六 06:45 | `fx/fetch_fx.py` | `fx/position.json`、`fx/history/*.csv` |
| 財報日曆 | **自動排程已停用**，只能手動執行 | `calendar/fetch_earnings.py` | `calendar/earnings.json` |
| **市場風險燈號** | 週二～六 07:00 | `regime/fetch_regime.py` | `regime/regime.json`、`regime/history.csv`、`regime/spy_history.csv` |
| **台股每日資料** | 平日 17:30（沒抓到最新日期，18:00 再試一次） | `tw/fetch_tw.py` | `tw/latest.csv`、`tw/revenue.csv`、`tw/meta.json` |
| 晨間簡報 | 週二～六 07:55（**目前暫停**） | Claude 排程任務「晨間簡報」 | 寄 Email |

排程設定都在 `.github/workflows/`。所有排程寫入 main 時都會「先合併最新版本再推送，失敗重試 5 次」，避免互相衝突。
共用工具在 `lib/common.py`。

## 各功能說明

### 台股每日資料（tw/）
- 來源：證交所 OpenAPI `STOCK_DAY_ALL`（日成交）、`BWIBBU_ALL`（本益比／殖利率／淨值比）、`T86`（三大法人）、`t187ap05_L`（月營收）
- `tw/latest.csv` 欄位：`code,name,date,close,volume,high,low,pe,dy,pb,foreign,trust,dealer`
  - 日期為西元 YYYY-MM-DD；`volume` 與法人買賣超單位為「張」
  - `foreign` = 外資及陸資買賣超（含外資自營商）；`dealer` = 自營商買賣超（自行買賣＋避險）
  - 檔案控制在 90KB（90,000 bytes）內：一般股票（4 碼）優先，其餘依成交金額由大到小，超過就省略，省略數量寫進 `problems`
  - 本益比資料日期與成交資料不同時，`pe/dy/pb` 留空
- `tw/revenue.csv`：`code,ym,revenue,yoy,ytd`，**只在每月 10～16 日更新**；`revenue`、`ytd`（累計營收）單位為千元，`yoy` 為去年同月增減 %
- 18:00 的重試加上 `--if-stale`：今天的資料已抓到就直接結束
- 手動補抓月營收：`python3 tw/fetch_tw.py --revenue`

### 財報日曆（calendar/earnings.json）
- **自動排程已停用**（2026-11-22）：財經日曆改用財經M平方，由專案那邊負責。要手動執行：GitHub → Actions → update-earnings → Run workflow
- 要恢復每天自動執行：在 `.github/workflows/update-earnings.yml` 加回 `schedule`（每天台灣 06:50）
- 標的：從 `fetch_prices.py` 的 `SYMBOLS` 讀出（不寫死）
- 來源：Twelve Data `/earnings_calendar`
- ⚠️ **目前 Twelve Data 方案不支援**（需要 Grow 以上），清單為空，原因寫在 `problems`。升級方案後不用改程式就會開始有資料
- 欄位：`symbol, company, date, time(bmo/amc/unknown), date_tw, confirmed, source`；另有 `next_7_days`、`next_14_days`
- `date_tw`：bmo（盤前）= 美國同一天；amc（盤後）= 美國日期的隔天；unknown 留 null

### 匯率位置（fx/position.json）
- 貨幣：USD/TWD、AUD/TWD、JPY/TWD（以 100 日圓計）、AUD/USD；來源 Twelve Data 日收盤
- 第一次抓 5 年歷史存在 `fx/history/<PAIR>.csv`，之後每天補最近幾天
- 只保留週一～五；當天 K 棒要到 UTC 22:00（約紐約收盤）後才算完成
- 每個貨幣：最新值與日期、近 1／3／5 年百分位／最高／最低／平均、近 20／60 個交易日漲跌幅、一句白話（以近 3 年百分位判斷：<20 偏低、20～40 略低、40～60 中間、60～80 略高、≥80 偏高）

### 市場風險燈號（regime/）
- 7 項指標，每項 0／1／2 分，總分 0～3 綠、4～6 黃、7 以上紅
- **完整規則見 `docs/REGIME.md`**

### 總經數據（macro/）
- DGS2、DGS10：美國財政部 Daily Treasury Par Yield Curve；VIX：CBOE 官方。抓不到才退回 FRED，`source` 欄位註明來源
- 其餘：FRED；USDTWD：Twelve Data

### FCN 燈號監控（fcn-monitor/）
- 商品條件放在 GitHub 密鑰 `FCN_PRODUCTS`（只有商品代號與條件，**不含客戶姓名**）
- 燈號規則與「FCN 持股燈號追蹤」網頁一致（歐式 KI、到期停止監控、換股追蹤）
- 商品有變動時：先更新燈號網頁，再請 Claude「同步 FCN 密鑰」，把產生的內容貼回 GitHub

## GitHub 密鑰（只列名稱，值不記錄）
位置：GitHub → stock-prices → Settings → Secrets and variables → Actions

| 名稱 | 用途 |
|---|---|
| `TWELVEDATA_KEY` | Twelve Data API 金鑰（股價、匯率、SPY／SOXX、財報日曆） |
| `FCN_PRODUCTS` | FCN 商品條件，不含客戶姓名 |
| `GMAIL_USER` | 寄信用的 Gmail 帳號 |
| `GMAIL_APP_PASSWORD` | Gmail 應用程式密碼 |

## Twelve Data 每日用量（免費方案上限 800 次／天、8 次／分鐘）
股價 4 次（26 檔分批）＋ 總經匯率 1 次 ＋ 匯率位置 4 次 ＋ 風險燈號 2 次 ≈ 11 次／天（財報日曆已停用）

## Claude 雲端環境「stock-prices」（只供 Claude 測試用）
- 個人環境，允許連線：`api.twelvedata.com`、`fred.stlouisfed.org`、`home.treasury.gov`、`cdn.cboe.com`、`cdn-api.cboe.com`、`openapi.twse.com.tw`、`www.twse.com.tw`（另允許套件庫）
- 網路密鑰：Twelve Data API 金鑰（由環境代為附加，不在程式中）
- 環境變數：無；設定指令碼：無（程式只用 Python 內建功能）

## 分工
- **Claude Code（雲端）**：寫程式、改 GitHub、設定自動排程；每次修改都開修改申請單，按 Merge 才生效
- **國泰世華助手（claude.ai 專案）**：客戶相關工作（燈號網頁、客戶報告、圖卡）、新聞與財報解讀
- 客戶姓名、持倉、貸款資料一律不進 GitHub

## 安全紀錄
- 2026-11-22：已用 git filter-repo 從所有歷史 commit 清除含客戶資料的 backfill 檔案並強制推送；確認無 fork。
  GitHub 的舊修改申請單（#1～#5）頁面可能仍保留舊 commit 的快取，需向 GitHub Support 申請清除。

## 待辦
- 晨間簡報：需在 claude.ai 為排程任務加上 Gmail 連接器，再由 Claude 重新啟用並測試（新聞改由專案負責）
- 燈號網頁與 GitHub 股價尚未自動同步（網頁股價需手動更新，更新時覆蓋最近 5 天）
- 建議更換一次 Gmail 應用程式密碼
- 向 GitHub Support 申請清除舊修改申請單的快取

## 修改紀錄
- #1 移除含客戶資料的 backfill 檔案，新增中文目錄
- #2 新增總經數據
- #3 新增 FCN 每日燈號監控
- #4 燈號信改為手機好讀的 HTML 版
- #5 總經：公債殖利率改抓財政部、VIX 改抓 CBOE；排程改為 06:40
- #6 第一階段：台股每日資料、財報日曆、匯率位置、市場風險燈號；新增 docs/SETUP.md、docs/REGIME.md
- #7 新增 CLAUDE.md：Claude 工作規則（一律繁體中文回覆、資料安全、修改流程）
- #8 停用財報日曆自動排程（改用財經M平方），保留手動執行
