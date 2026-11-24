# 交接：台股儀表板排程改用 GitHub Actions

狀態：**待開工**（請在新對話執行）　｜　建立：2026-11-24

## 背景
- 台股儀表板是 claude.ai 上的「Data」類型頁面，資料存在頁面自己的資料庫（ArtifactData）。網址請向使用者確認，或在 claude.ai 的 artifact 清單找「台股」。
- 現在由 **Claude 排程**「台股儀表板更新」在平日 19:20、23:20（台北）執行（可用 list_triggers 找到）。它做三件事：
  1. 從 GitHub 組出公開資料檔 `tw_dashboard.json`（水位燈號、名單、模擬資金、33 檔評分、盤後籌碼），上傳成頁面的檔案，再把 13 個 file dataset 指向新檔。
  2. 從證交所 OpenAPI（STOCK_DAY_ALL）抓持股、觀察股的收盤價，寫進資料庫 `data/tw/stocks`。
  3. 依帳本算帳戶快照，寫進 `data/tw/history`。
- 這三件每天都用 AI 執行，用量大。

## 使用者的決定（2026-11-24）
1. 改成 GitHub Actions 做；只把 GitHub 做不到的部分留給 Claude。
2. **帳戶快照不能只在打開頁面時記**：GitHub 要保留每日收盤價歷史（公開資料），頁面打開時依帳本和歷史收盤價**把沒打開的日子補算回來**。
3. **新舊並行**：新做法完成後，先和現在的 19:20／23:20 Claude 排程並行幾天；資料一致、使用者同意後，才停用舊排程。
4. **不能影響 FCN 晨間更新**：`tw-models/latest/after_market.json` 等晨間會讀的檔案，格式、路徑、更新時間都不改。
5. 試試儀表板能不能**直接讀 GitHub 上的檔案**（例如 raw.githubusercontent.com）。可以的話就把 AI 排程整個拿掉，並把結果告訴使用者。

## 建議做法
1. **GitHub Actions（`update-tw-models` 裡加一步）**
   - 產生 `tw-models/latest/tw_dashboard.json`（目前在 Claude 排程裡組，改成程式組）。
   - 新增每日收盤價歷史：全部上市股票（或 33 檔＋常用 ETF），只放公開收盤價，例如 `tw-models/latest/closes.json`（近一年，日期 × 代號）。不能寫入哪幾檔是持股。
   - 輸出 JSON 照規則都要有 `generated_at_utc`、`problems`、`sources`，並加進 `sanity.py` 的結構檢查。
2. **頁面**
   - 收盤價改讀上面的公開檔案，不再讀資料庫 `data/tw/stocks`（並行期間兩邊都留）。
   - 新增補算：打開頁面時找出 `data/tw/history` 缺的交易日，用帳本＋歷史收盤價逐日算出快照並寫回。
   - 照頁面「一個寫入者」規則：圖表用 data-draw、計算用 dash.calc。
3. **測試頁面能不能直接讀 GitHub**：把一個 file dataset 的 source 指到 raw.githubusercontent.com 的網址試讀。
   - 可以：13 個 file dataset 全改指 GitHub，Claude 排程可以全部停掉。
   - 不行：Claude 每天只剩一步，把 GitHub 產生的 `tw_dashboard.json` 上傳並更新 dataset 網址（一個批次）。
4. 並行幾天，比對新舊兩邊的收盤價和快照，結果給使用者看，同意後才停用舊排程。

## 完成的定義
- GitHub 每天自動產生 `tw_dashboard.json` 和收盤價歷史，並通過資料檢查。
- 頁面在沒打開幾天後再打開，快照會自動補齊。
- 晨間會讀的檔案沒有任何變動。
- 回報使用者：改了什麼、能不能直接讀 GitHub、還剩什麼要 Claude 做。
- 更新本交接與 `docs/SETUP.md`。

## 注意
- 帳本、持股、成本、快照只在頁面資料庫，**絕對不進 GitHub**。
- FCN 系統不要動。
