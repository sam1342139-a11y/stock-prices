# 系統設定說明（SETUP）

> 每次修改系統都要同步更新這份文件。最後更新：2026-11-24（水位燈號加整體燈號；波段停損價欄位說明）

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
| **台股模型資料＋水位燈號** | 平日 18:30（21:30、23:30 備援） | `tw-models/update_daily.py`、`fetch_us_market.py`、`regime_tw.py` | `tw-models/data/daily/`、`tw-models/latest/regime_tw.json` |
| **模擬資金追蹤** | 平日 18:30 排程內 | `tw-models/paper.py` | `tw-models/paper/latest.json`、`nav.csv`、`docs/PAPER.md` |
| **波段／長期名單** | 每週五 18:30 排程內（約 18:45 完成）；手動執行也會產生 | `tw-models/models.py --latest` | `tw-models/latest/swing.json`、`long.json`、`core_satellite.json` |

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

### 台股模型（tw-models/）
- **完整規則見 `docs/TW_MODELS.md`**；參數在 `tw-models/config.json`
- 歷史資料（2019 起，暖身資料 2014 起）：FinMind 一次性回補（證交所網站會封鎖雲端主機的大量抓取）；之後每日 18:30 用證交所 OpenAPI 累加
- **原始資料不公開**（FinMind 條款未明確允許公開轉載）：存在 GitHub Actions 快取，只公開計算結果與報告；回補排程 `tw-models-backfill` 每小時檢查一次，每次最多連續跑約 5.5 小時（18:20、21:20、23:20 前停下，不擋每日更新）
- 回測引擎 `tw-models/backtest.py`：隔天開盤成交、手續費 ×0.6 折、證交稅、滑價 0.1%、含息、樣本內 2019–2023／樣本外 2024～今分開報告
- 台股水位燈號 `tw-models/latest/regime_tw.json`：5 項指標、總分換「參考水位」（樣本外擇時效果與固定比例幾乎相同：97.6% vs 97.2%）；回測報告 `docs/BACKTEST_regime_tw.md`
- 選股模型 `tw-models/models.py`：D 波段（每週五名單、紅燈只列前 3 名）、E 長期（每季換股、同產業最多 3 檔）、F 舊篩選法（33 檔、每月前 8 名，只做回測）；回測報告 `docs/BACKTEST_swing.md`、`BACKTEST_long.md`、`BACKTEST_old_screen.md`、`BACKTEST_comparison.md`
- 後續回測 `tw-models/extra_backtests.py`：波段低換手版 `docs/BACKTEST_swing_lowturn.md`、0050 70%＋長期 30% 組合 `docs/BACKTEST_combo.md`（手動執行，不排程）
- 季報（`fin`）與除權息（`dividends`）在每個季報法定期限後（4/1、5/16、8/15、11/15）由回補排程自動重抓一次（約 2,440 次請求、5 小時左右），期間模型照常產生
- 驗收抽查：GitHub Actions → tw-models-spot-check → Run workflow

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
| `FINMIND_TOKEN` | FinMind API token（台股模型：每日市場層級資料） |

## Twelve Data 每日用量（免費方案上限 800 次／天、8 次／分鐘）
股價 4 次（26 檔分批）＋ 總經匯率 1 次 ＋ 匯率位置 4 次 ＋ 風險燈號 2 次 ≈ 11 次／天（財報日曆已停用）

## Claude 雲端環境「stock-prices」（只供 Claude 測試用）
- 個人環境，允許連線：`api.twelvedata.com`、`fred.stlouisfed.org`、`home.treasury.gov`、`cdn.cboe.com`、`cdn-api.cboe.com`、`openapi.twse.com.tw`、`www.twse.com.tw`、`mopsov.twse.com.tw`、`mops.twse.com.tw`、`api.finmindtrade.com`（另允許套件庫）
- 網路密鑰：Twelve Data API 金鑰、FinMind API token（由環境代為附加，不在程式中）
- 環境變數：無；設定指令碼：無（程式只用 Python 內建功能）

## 分工
- **Claude Code（雲端）**：寫程式、改 GitHub、設定自動排程；每次修改都開修改申請單，按 Merge 才生效
- **理專助手（claude.ai 專案）**：客戶相關工作（燈號網頁、客戶報告、圖卡）、新聞、財經日曆、**晨間簡報**（可讀取本存放庫的公開資料）
- 客戶姓名、持倉、貸款資料一律不進 GitHub

## 安全紀錄
- 2026-11-22：已用 git filter-repo 從所有歷史 commit 清除含客戶資料的 backfill 檔案並強制推送；確認無 fork。
  GitHub 的舊修改申請單（#1～#5）頁面可能仍保留舊 commit 的快取，需向 GitHub Support 申請清除。

## 待辦
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
- #8 停用財報日曆自動排程（改用財經M平方），保留手動執行；刪除 Claude Code 這邊的「晨間簡報」排程（改由專案負責）
- #9 台股模型第一階段：A 歷史資料、B 回測引擎、C 台股水位燈號；docs/TW_MODELS.md
- 台股模型第二階段：D 波段、E 長期、F 舊篩選法；季報資料；每週五名單
- 台股模型後續回測：波段低換手版、組合回測、成本占報酬比例；swing.json 加註「回測未勝過 0050，僅供觀察」
- 新增 core_satellite.json（0050 70%＋長期 30%）；regime_tw.json 的建議持股水位改為參考水位
- 驗收抽查通過（18 筆一致），規則凍結 v1.0；修正抽查程式的民國日期格式
- 新增模擬資金追蹤（七三組合、長期 100%、0050，各 100 萬元，從 2026-11-23 起）
- regime_tw.json 加整體燈號 overall_light；swing.json 停損價改名 stop_price_est 並說明實際以進場價計（只改輸出，不改規則）
