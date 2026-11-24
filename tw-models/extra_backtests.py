"""Follow-up backtests requested 2026-11-23 (docs/TW_MODELS.md "D～F 後續回測").

1) Swing low-turnover versions: grid over
     exit A/B x (a) monthly ranking x (b) top-20 buffer x (c) 20-day minimum hold x red-light rule
   run IN-SAMPLE ONLY; the version with the highest in-sample Sharpe is chosen (rule fixed before running),
   then that one version is run out-of-sample once.
2) Portfolio: 0050 70% + long list 30%, rebalanced quarterly; vs long 100% and 0050 100% (both periods, fixed rules).

Usage: python3 tw-models/extra_backtests.py [--swing] [--combo]   (no flag = both)
"""
import itertools, json, os, sys
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(1, os.path.join(os.path.dirname(HERE), "lib"))
import common as C
import twdata as T
import backtest as B
import models as M

SELECT_BY = "sharpe"  # chosen before running: highest in-sample Sharpe


def label(v):
    exit_rule, freq, buf, mh, red = v
    bits = ["出場" + exit_rule, "每月" if freq == "month" else "每週"]
    if buf:
        bits.append("前%d名緩衝" % buf)
    if mh:
        bits.append("最少持有%d日" % mh)
    if red:
        bits.append("紅燈前3")
    return "・".join(bits)


def swing():
    cfg = T.config()
    reg = M.regime_map()
    dl = T.delisted()
    per = B.periods()
    s_in, e_in = per["in_sample"]
    grid = list(itertools.product(["A", "B"], ["week", "month"], [0, 20], [0, 20], [False, True]))
    rows = []
    res_in = {}
    for v in grid:
        r = B.run(M.swing_strategy(cfg, v[0], v[4], reg, freq=v[1], buffer=v[2], min_hold=v[3]), s_in, e_in, delisted=dl)
        m = B.metrics(r)
        res_in[v] = r
        rows.append({"version": label(v), "exit": v[0], "freq": v[1], "buffer": v[2], "min_hold": v[3], "red_rule": v[4],
                     **{k: m[k] for k in ("total_return_pct", "cagr_pct", "max_drawdown_pct", "sharpe", "trades",
                                          "annual_turnover_x", "costs_ntd", "cost_share_pct")}})
        print(label(v), m["total_return_pct"], m["sharpe"], m["annual_turnover_x"], flush=True)
    b0050_in = B.benchmark_0050(s_in, e_in)
    best = max(grid, key=lambda v: B.metrics(res_in[v])[SELECT_BY])
    # out-of-sample: run once, only for the chosen version (plus the original A/B for reference, already reported)
    s_out, e_out = per["out_of_sample"]
    variants = {"低換手版：" + label(best): {"in_sample": res_in[best],
                                         "out_of_sample": B.run(M.swing_strategy(cfg, best[0], best[4], reg, freq=best[1], buffer=best[2], min_hold=best[3]), s_out, e_out, delisted=dl)}}
    for ex in ("A", "B"):
        v = (ex, "week", 0, 0, False)
        variants["原版出場" + ex] = {"in_sample": res_in[v],
                                  "out_of_sample": B.run(M.swing_strategy(cfg, ex, False, reg), s_out, e_out, delisted=dl)}
    variants["0050"] = {"in_sample": b0050_in, "out_of_sample": B.benchmark_0050(s_out, e_out)}
    notes = [
        "低換手的三種做法：(a) 每月第一個交易日重排（原本每週）；(b) 持有中的股票只要還在前 20 名就不換（取消「持有滿 20 日」出場）；(c) 最少持有 20 個交易日（停損、30% 回落全賣、紅燈規則除外）。",
        "樣本內共測 %d 種組合（出場 A／B × a × b × c × 紅燈規則），**事先訂好以樣本內夏普值最高者為最佳版**，之後才對這一版跑一次樣本外。" % len(grid),
        "成本占報酬比例 = （手續費＋證交稅＋滑價）÷ 扣成本前的獲利；扣成本前沒有獲利時不計算。",
        "注意：測了 %d 種組合再挑最好的，樣本內成績本身會偏樂觀，樣本外才是比較公平的檢驗。" % len(grid),
        T.survivorship_note(),
    ]
    B.write_report("swing_lowturn", "D. 波段低換手版", variants, notes, [], M.SOURCES)
    # grid table (in-sample only) appended to the markdown + json
    C.write_json("tw-models/reports/swing_lowturn_grid.json", {
        "period": [s_in, e_in], "select_by": SELECT_BY, "chosen": label(best), "rows": rows,
        "benchmark_0050": {k: B.metrics(b0050_in)[k] for k in ("total_return_pct", "max_drawdown_pct", "sharpe")}}, [], M.SOURCES)
    L = ["", "## 樣本內全部組合（2019–2023）", "",
         "依夏普值排序；**粗體**為選中的版本。0050 同期：總報酬 %s%%、最大回撤 %s%%、夏普值 %s。" % (
             B.metrics(b0050_in)["total_return_pct"], B.metrics(b0050_in)["max_drawdown_pct"], B.metrics(b0050_in)["sharpe"]), "",
         "| 版本 | 總報酬 | 最大回撤 | 夏普值 | 年週轉率 | 成本占報酬比例 |", "|---|---|---|---|---|---|"]
    for r in sorted(rows, key=lambda x: -x["sharpe"]):
        name = "**%s**" % r["version"] if r["version"] == label(best) else r["version"]
        L.append("| %s | %s%% | %s%% | %s | %s 倍 | %s |" % (name, r["total_return_pct"], r["max_drawdown_pct"], r["sharpe"],
                                                         r["annual_turnover_x"], "—" if r["cost_share_pct"] is None else "%s%%" % r["cost_share_pct"]))
    with open(C.out_path("docs/BACKTEST_swing_lowturn.md"), "a", encoding="utf-8") as f:
        f.write("\n".join(L) + "\n")
    print("chosen:", label(best))
    return best


def combo():
    cfg = T.config()
    dl = T.delisted()
    res = {"0050 70%＋長期 30%": {}, "長期 100%": {}, "0050": {}}
    for p, (s, e) in B.periods().items():
        res["0050 70%＋長期 30%"][p] = B.run(M.combo_strategy(cfg, 0.7), s, e, delisted=dl)
        res["長期 100%"][p] = B.run(M.long_strategy(cfg), s, e, delisted=dl)
        res["0050"][p] = B.benchmark_0050(s, e)
    notes = [
        "組合：0050 占 70%、長期名單占 30%（8 檔平分），每季（1、4、7、10 月 15 日後第一個交易日）再平衡回 70／30；權重偏離不到 2 個百分點的部位不調整。",
        "組合與長期 100% 都從第一個換股日（約 1 月 16 日）才開始投入，期初約兩週為現金；0050 100% 第一天就買進。",
        "規則事先固定，樣本內、樣本外各跑一次，沒有調整參數。",
        T.survivorship_note(),
    ]
    B.write_report("combo", "組合：0050 70%＋長期 30%", res, notes, [], M.SOURCES)


def quantstats_report():
    """Advanced figures (quantstats) for the core-satellite comparison; report only, rules unchanged."""
    import qs_report as Q
    cfg = T.config()
    dl = T.delisted()
    groups = {"0050 70%＋長期 30%": lambda s, e: B.run(M.combo_strategy(cfg, 0.7), s, e, delisted=dl),
              "長期 100%": lambda s, e: B.run(M.long_strategy(cfg), s, e, delisted=dl),
              "0050": lambda s, e: B.benchmark_0050(s, e)}
    names = list(groups)
    L = ["# 進階績效指標（quantstats）", "", "> 模型依公開資料與固定規則產生，回測不代表未來，非投資建議。", "",
         "用開源套件 quantstats（Apache-2.0）重新計算七三組合、長期名單和 0050 的回測績效。**只用來看報告和交叉驗證，模型規則沒有改（v1.0）。**", "",
         "- 夏普值、索提諾值：日報酬、無風險利率 0、乘 √252，和 `backtest.py` 的算法一樣。",
         "- 最長回撤天數：從前高到重新站回前高的日曆天數（還沒回到前高的就算到最後一天）。",
         "- 單日風險值（95%）：歷史上 95% 的交易日，單日虧損不會超過這個數字。",
         "- 月報酬熱力圖：紅色是上漲、綠色是下跌（台股習慣）。", ""]
    check = []
    for per, (s, e) in B.periods().items():
        res, curves = {}, {}
        for n in names:
            r = groups[n](s, e)
            curves[n] = r["curve"]
            res[n] = Q.metrics(r["curve"])
            own = B.metrics(r)
            check.append((per, n, own["sharpe"], res[n]["sharpe"], own["max_drawdown_pct"], res[n]["mdd_pct"], own["total_return_pct"], res[n]["total_pct"]))
        L += ["## " + B.PERIOD_ZH[per], "", "期間：%s ～ %s" % (s, e), ""] + Q.table_md(names, res) + [""]
        for n in ("0050 70%＋長期 30%", "0050"):
            slug = "combo" if n != "0050" else "0050"
            rel = "docs/img/QS_%s_%s.png" % (slug, per)
            if Q.heatmap(curves[n], os.path.join(os.path.dirname(HERE), rel), "%s 月報酬（%%）— %s" % (n, B.PERIOD_ZH[per].split("（")[0])):
                L += ["**%s 月報酬熱力圖**" % n, "", "![%s](img/%s)" % (slug, os.path.basename(rel)), ""]
    L += ["## 交叉驗證：我們的回測引擎 vs quantstats", "", "兩邊各自計算同一條淨值曲線，數字應該一致；不一致代表有一邊算錯。", "",
          "| 期間 | 組合 | 夏普值（引擎）| 夏普值（quantstats）| 最大回撤（引擎）| 最大回撤（quantstats）| 總報酬（引擎）| 總報酬（quantstats）|", "|---|---|---|---|---|---|---|---|"]
    bad = 0
    for per, n, s1, s2, d1, d2, t1, t2 in check:
        ok = abs(s1 - s2) <= 0.02 and abs(d1 - d2) <= 0.05 and abs(t1 - t2) <= 0.05
        bad += not ok
        L.append("| %s | %s | %s | %s | %s%% | %s%% | %s%% | %s%% |%s" % (B.PERIOD_ZH[per].split("（")[0], n, s1, s2, d1, d2, t1, t2, "" if ok else " ⚠️ 不一致"))
    L += ["", "結果：%s" % ("全部一致。" if not bad else "有 %d 列不一致，需要查原因。" % bad), ""]
    with open(os.path.join(os.path.dirname(HERE), "docs", "BACKTEST_quantstats.md"), "w", encoding="utf-8") as f:
        f.write("\n".join(L))
    print("quantstats report written; mismatches:", bad)


if __name__ == "__main__":
    args = sys.argv[1:]
    if "--qs" in args:
        quantstats_report()
        sys.exit(0)
    if "--swing" in args or not args:
        swing()
    if "--combo" in args or not args:
        combo()
