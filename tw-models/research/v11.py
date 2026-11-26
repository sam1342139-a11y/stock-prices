"""Taiwan model v1.1 research: walk-forward (expanding window) validation + swing v1.1 candidates.

RESEARCH ONLY: does not touch tw-models/config.json, tw-models/latest/, the dashboard file or any daily schedule.
Rules are fixed in tw-models/research/config_v11.json before running.

  24 swing v1.1 variants = momentum {VAM21, VAM60-5} x low-vol filter {off, exclude top 30%}
                           x exit {monthly, 2xATR(20), v1.0 exit A} x red light {no new positions, v1.0 keep top 3}
  All rank on the first trading day of each month, 8 stocks equal weight; pool, costs, fills, flow and
  revenue factors are the v1.0 ones.
  Walk-forward: for each test year Y (2016..now) pick the variant with the best Sharpe on data up to Y-1
  (alternative pick: lowest daily-return standard deviation), then use that variant's returns in year Y.
  Fixed comparison groups: swing v1.0 (unchanged), 0050 (dividends reinvested), equal-weight pool (monthly),
  long v1.0 (diagnosis only).

Usage: python3 tw-models/research/v11.py      -> docs/RESEARCH_v1.1.md, docs/img/RESEARCH_v11.png,
                                                 tw-models/research/results_v11.json
"""
import datetime, itertools, json, math, os, sys, time
HERE = os.path.dirname(os.path.abspath(__file__))
TW = os.path.dirname(HERE)
ROOT = os.path.dirname(TW)
sys.path.insert(0, TW)
sys.path.insert(1, os.path.join(ROOT, "lib"))
import twdata as T
import backtest as B
import models as M

RC = json.load(open(os.path.join(HERE, "config_v11.json"), encoding="utf-8"))
CFG = T.config()
SC = CFG["swing"]


# ------------------------------------------------------------------ features
class R:
    """Per-code prefix sums of daily returns and squared returns (adjusted closes) for O(1) std."""
    _c = {}

    def __init__(self, code):
        s = T.prices(code)
        self.r1 = [0.0]
        self.r2 = [0.0]
        for i in range(1, len(s.close_adj)):
            a, b = s.close_adj[i - 1], s.close_adj[i]
            r = b / a - 1 if a else 0.0
            self.r1.append(self.r1[-1] + r)
            self.r2.append(self.r2[-1] + r * r)
        # true range on adjusted prices for ATR
        self.tr = [0.0]
        for i in range(len(s.close_adj)):
            h, l = s.high_adj[i], s.low_adj[i]
            pc = s.close_adj[i - 1] if i else s.close_adj[i]
            self.tr.append(self.tr[-1] + max(h - l, abs(h - pc), abs(l - pc)))

    @classmethod
    def of(cls, c):
        x = cls._c.get(c)
        if x is None:
            x = cls._c[c] = cls(c)
        return x

    def std(self, a, b):
        """std of daily returns at indices a..b (inclusive), each return = close[i]/close[i-1]-1."""
        n = b - a + 1
        if a < 1 or n < 2:
            return None
        s1 = self.r1[b] - self.r1[a - 1]
        s2 = self.r2[b] - self.r2[a - 1]
        var = (s2 - s1 * s1 / n) / (n - 1)
        return math.sqrt(var) if var > 0 else None

    def atr(self, i, n):
        return (self.tr[i + 1] - self.tr[i + 1 - n]) / n if i + 1 >= n else None


_RANK = {}


def rank(d, mom_kind, low_vol):
    """v1.0 swing ranking with the momentum factor replaced by volatility-adjusted momentum, optional low-vol filter."""
    key = (d, mom_kind, low_vol)
    if key in _RANK:
        return _RANK[key]
    cand, mom, trend, flow, rev, vol60 = [], {}, {}, {}, {}, {}
    for c in M.universe_codes():
        f = M.F.of(c)
        s = f.s
        i = s.idx.get(d)
        if i is None or i < 65:
            continue
        if s.close[i] <= SC["min_price"] or (f.avg_lots(i, 20) or 0) <= SC["min_avg_volume_lots_20d"]:
            continue
        r = R.of(c)
        if mom_kind == "vam21":
            sd = r.std(i - 20, i)
            m = s.close_adj[i] / s.close_adj[i - 21] - 1 if sd else None
        else:
            sd = r.std(i - 59, i - 5)
            m = s.close_adj[i - 5] / s.close_adj[i - 60] - 1 if sd else None
        if m is None:
            continue
        cand.append(c)
        mom[c] = m / sd
        vol60[c] = r.std(i - 59, i) or 0
        m20, m60 = f.ma(i, 20), f.ma(i, 60)
        trend[c] = (s.close_adj[i] > m20) + (s.close_adj[i] > m60)
        ins = T.inst(c)
        net = sum((ins.get(s.dates[j], (0, 0, 0))[0] + ins.get(s.dates[j], (0, 0, 0))[1]) for j in range(i - 9, i + 1))
        vv = f.vs[i + 1] - f.vs[i - 9]
        flow[c] = net / vv if vv and ins else None
        rf = M.rev_features(c, d)
        rev[c] = None if rf is None else (1.0 if rf[0] > rf[1] else 0.0) + (0.5 if rf[2] else 0.0)
    if low_vol and cand:
        cut = sorted(vol60[c] for c in cand)[int(len(cand) * (1 - RC["low_vol_filter"]["exclude_top_pct"] / 100.0))
                                              if len(cand) > 1 else 0]
        cand = [c for c in cand if vol60[c] < cut] or cand
    w = SC["weights"]
    P = {"momentum": M.pct_rank({c: mom[c] for c in cand}), "trend": M.pct_rank({c: trend[c] for c in cand}),
         "flow": M.pct_rank({c: flow[c] for c in cand}), "revenue": M.pct_rank({c: rev[c] for c in cand})}
    score = {c: sum(w[k] * P[k][c] for k in P) for c in cand}
    out = sorted(cand, key=lambda c: -score[c])
    _RANK[key] = out
    return out


# ------------------------------------------------------------------ strategies
def v11_strategy(mom_kind, low_vol, exit_rule, red_rule, regime):
    cal = T.calendar()
    rank_days = M.first_of_month(cal)
    n_top = RC["top_n"]
    atr_stop = {}

    def strat(d, br):
        orders, selling = [], set()
        for c, p in br.pos.items():
            f = M.F.of(c)
            i = f.s.idx.get(d)
            if i is None:
                continue
            px = f.s.close_adj[i]
            if exit_rule == "atr2":
                if c not in atr_stop:  # first close after the fill: fix the stop from entry price and ATR(20) then
                    a = R.of(c).atr(i, RC["atr_days"])
                    atr_stop[c] = p["entry_px"] - RC["atr_mult"] * a if a else None
                if atr_stop.get(c) is not None and px < atr_stop[c]:
                    orders.append(B.Sell(c, 1.0, "跌破進場價 − 2×ATR")); selling.add(c)
            elif exit_rule == "v10":
                ea = SC["exit_a"]
                if px <= p["entry_px"] * (1 - ea["stop_loss_pct"] / 100):
                    orders.append(B.Sell(c, 1.0, "停損 −8%")); selling.add(c)
                elif px < f.ma(i, ea["ma_days"]):
                    orders.append(B.Sell(c, 1.0, "跌破 20 日均線")); selling.add(c)
                elif p["days"] >= ea["max_hold_days"]:
                    orders.append(B.Sell(c, 1.0, "持有滿 20 個交易日")); selling.add(c)
        for c in list(atr_stop):
            if c not in br.pos:
                del atr_stop[c]
        if d in rank_days:
            ranked = rank(d, mom_kind, low_vol)
            red = regime.get(d, {}).get("total", 0) >= 6
            n = SC["red_light_top_n"] if (red and red_rule == "v10_top3") else n_top
            keep = set(ranked[:n])
            for c in list(br.pos):
                if c not in keep and c not in selling:
                    orders.append(B.Sell(c, 1.0, "跌出前 %d 名" % n)); selling.add(c)
            if not (red and red_rule == "no_new_on_red"):
                held = [c for c in br.pos if c not in selling]
                slots = n - len(held)
                nav = br.nav(d)
                for c in ranked:
                    if slots <= 0:
                        break
                    if c in br.pos:
                        continue
                    orders.append(B.Buy(c, nav / n_top, "v1.1 第 %d 名" % (ranked.index(c) + 1)))
                    slots -= 1
        return orders
    return strat


def equal_weight_strategy():
    """Same pool as swing (price > 10, 20-day average volume > 1,000 lots), equal weight, monthly rebalance."""
    cal = T.calendar()
    days = M.first_of_month(cal)

    def strat(d, br):
        if d not in days:
            return []
        pool = []
        for c in M.universe_codes():
            f = M.F.of(c)
            i = f.s.idx.get(d)
            if i is None or i < 65:
                continue
            if f.s.close[i] > SC["min_price"] and (f.avg_lots(i, 20) or 0) > SC["min_avg_volume_lots_20d"]:
                pool.append(c)
        if not pool:
            return []
        # B.target_orders only acts on gaps > 2 percentage points; with ~700 names each weight is ~0.14%,
        # so rebalance here with a relative tolerance instead (trade when off target by more than 25%).
        nav, w = br.nav(d), 1.0 / len(pool)
        cur = br.weights(d)
        keep = set(pool)
        orders = [B.Sell(c, 1.0, "跌出等權股票池") for c in cur if c not in keep]
        orders += [B.Sell(c, 1 - w / x, "等權再平衡") for c, x in cur.items() if c in keep and x > w * 1.25]
        orders += [B.Buy(c, (w - cur.get(c, 0)) * nav, "等權再平衡") for c in pool if cur.get(c, 0) < w / 1.25]
        return orders
    return strat


def tracked(strategy):
    """Wraps a strategy to record cumulative sell notional per day (for per-year turnover)."""
    log = {}

    def strat(d, br):
        log[d] = br.sell_notional
        return strategy(d, br)
    return strat, log


def run(name, strategy, start, end, dl):
    t0 = time.time()
    s, log = tracked(strategy)
    r = B.run(s, start, end, delisted=dl)
    r["sell_log"] = log
    print("ran %-40s %5.0fs" % (name, time.time() - t0), flush=True)
    return r


# ------------------------------------------------------------------ metrics on daily returns
def daily_returns(curve):
    return [(curve[i][0], curve[i][1] / curve[i - 1][1] - 1) for i in range(1, len(curve))]


def stats(rets):
    if len(rets) < 2:
        return {}
    xs = [r for _, r in rets]
    nav, peak, mdd = 1.0, 1.0, 0.0
    yearly, ycur = {}, {}
    for d, r in rets:
        nav *= 1 + r
        peak = max(peak, nav)
        mdd = min(mdd, nav / peak - 1)
        ycur[d[:4]] = ycur.get(d[:4], 1.0) * (1 + r)
    n = len(xs)
    mean = sum(xs) / n
    sd = math.sqrt(sum((x - mean) ** 2 for x in xs) / (n - 1))
    years = n / 252.0
    return {"cagr_pct": round((nav ** (1 / years) - 1) * 100, 2), "total_pct": round((nav - 1) * 100, 2),
            "mdd_pct": round(mdd * 100, 2), "sharpe": round(mean / sd * math.sqrt(252), 2) if sd else 0,
            "std_daily_pct": round(sd * 100, 3), "yearly": {y: round((v - 1) * 100, 2) for y, v in sorted(ycur.items())}}


def turnover_by_year(r):
    """Sell notional in the year / average NAV in the year."""
    out, curve, log = {}, r["curve"], r["sell_log"]
    years = sorted({d[:4] for d, _ in curve})
    for y in years:
        ds = [d for d, _ in curve if d[:4] == y]
        navs = [v for d, v in curve if d[:4] == y]
        prev = [log[d] for d in log if d[:4] < y]
        start = max(prev) if prev else 0.0
        end = max([log[d] for d in log if d[:4] == y] or [start])
        out[y] = round((end - start) / (sum(navs) / len(navs)), 2) if navs else None
    return out


def walk_forward(results, first_year, last_year, by):
    """Per test year pick the variant with the best in-sample score (data up to the previous year-end)."""
    picks, stitched = {}, []
    for y in range(first_year, last_year + 1):
        best, best_v = None, None
        for k, r in results.items():
            ins = [x for x in daily_returns(r["curve"]) if x[0][:4] < str(y)]
            st = stats(ins)
            if not st:
                continue
            v = st["sharpe"] if by == "sharpe" else -st["std_daily_pct"]
            if best_v is None or v > best_v:
                best, best_v = k, v
        picks[y] = best
        stitched += [x for x in daily_returns(results[best]["curve"]) if x[0][:4] == str(y)]
    return picks, stitched


def label(k):
    mom, lv, ex, red = k
    return "・".join([{"vam21": "VAM21", "vam60_5": "VAM60-5"}[mom], "篩低波動" if lv else "不篩",
                      {"monthly": "月換股出場", "atr2": "2×ATR 停損", "v10": "v1.0 出場"}[ex],
                      {"no_new_on_red": "紅燈不開新倉", "v10_top3": "紅燈留前 3"}[red]])


# ------------------------------------------------------------------ main
def main():
    start, end = RC["start"], T.calendar()[-1]
    first, last = RC["test_from_year"], int(end[:4])
    dl = T.delisted()
    reg = M.regime_map()
    grid = list(itertools.product(["vam21", "vam60_5"], [False, True], ["monthly", "atr2", "v10"], ["no_new_on_red", "v10_top3"]))
    assert len(grid) == RC["grid_size"] == 24
    res = {}
    for k in grid:
        res[k] = run(label(k), v11_strategy(*k, reg), start, end, dl)
    fixed = {
        "波段 v1.0（不調參數）": run("swing v1.0", M.swing_strategy(CFG, "A", True, reg), start, end, dl),
        "0050（含息）": run("0050", lambda d, br: [B.Buy("0050", br.cash * 0.999, "0050")] if not br.pos else [], start, end, dl),
        "等權大盤（同股票池）": run("equal weight", equal_weight_strategy(), start, end, dl),
        "長期 v1.0（診斷）": run("long v1.0", M.long_strategy(CFG), start, end, dl),
    }
    oos_from = "%d-01-01" % first
    picks, stitched = walk_forward(res, first, last, "sharpe")
    picks_alt, stitched_alt = walk_forward(res, first, last, "lowest_std")
    tov = {k: turnover_by_year(r) for k, r in res.items()}
    tov_fixed = {k: turnover_by_year(r) for k, r in fixed.items()}
    roll_tov = {y: tov[picks[y]].get(str(y)) for y in picks}
    roll_alt_tov = {y: tov[picks_alt[y]].get(str(y)) for y in picks_alt}
    out = {
        "generated_at_utc": datetime.datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S"), "problems": [],
        "sources": [{"name": "FinMind（tw-models 快取的歷史資料）", "url": "https://api.finmindtrade.com/api/v4/data"}],
        "period": [start, end], "test_years": [first, last], "combinations_tested": len(grid),
        "rolling_sharpe": {"picks": {y: label(k) for y, k in picks.items()}, "stats": stats(stitched),
                           "turnover_by_year": roll_tov},
        "rolling_lowest_std": {"picks": {y: label(k) for y, k in picks_alt.items()}, "stats": stats(stitched_alt),
                               "turnover_by_year": roll_alt_tov},
        "fixed": {n: {"stats": stats([x for x in daily_returns(r["curve"]) if x[0] >= oos_from]),
                      "turnover_by_year": tov_fixed[n]} for n, r in fixed.items()},
        "variants": {label(k): {"stats": stats([x for x in daily_returns(r["curve"]) if x[0] >= oos_from]),
                                "avg_turnover": round(sum(v for y, v in tov[k].items() if v is not None and int(y) >= first) /
                                                      max(1, sum(1 for y, v in tov[k].items() if v is not None and int(y) >= first)), 2)}
                     for k, r in res.items()},
    }
    json.dump(out, open(os.path.join(HERE, "results_v11.json"), "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    curves = {"v1.1 滾動（夏普挑選）": stitched, "v1.1 滾動（最低標準差挑選）": stitched_alt}
    for n, r in fixed.items():
        curves[n] = [x for x in daily_returns(r["curve"]) if x[0] >= oos_from]
    chart(curves, os.path.join(ROOT, "docs", "img", "RESEARCH_v11.png"))
    report(out, grid)
    print("done")


def chart(curves, path):
    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
        from matplotlib import font_manager
        for f in font_manager.findSystemFonts():
            if "wqy" in f.lower() or ("noto" in f.lower() and "cjk" in f.lower()):
                font_manager.fontManager.addfont(f)
                plt.rcParams["font.family"] = font_manager.FontProperties(fname=f).get_name()
                break
        plt.rcParams["axes.unicode_minus"] = False
    except Exception:
        return
    fig, ax = plt.subplots(figsize=(7.5, 4.2), dpi=150)
    for n, rets in curves.items():
        nav, xs, ys = 1.0, [], []
        for d, r in rets:
            nav *= 1 + r
            xs.append(datetime.date.fromisoformat(d)); ys.append(nav)
        ax.plot(xs, ys, label=n, linewidth=1.6 if "v1.1" in n else 1.0)
    ax.set_yscale("log")
    ax.set_title("樣本外淨值（%s 起，對數刻度）" % min(r[0][0] for r in curves.values() if r)[:4], fontsize=10)
    ax.legend(fontsize=7, loc="upper left")
    ax.grid(alpha=0.3)
    fig.tight_layout()
    os.makedirs(os.path.dirname(path), exist_ok=True)
    fig.savefig(path)
    plt.close(fig)


def report(o, grid):
    rs, ra = o["rolling_sharpe"], o["rolling_lowest_std"]
    fx = o["fixed"]
    e = fx["0050（含息）"]["stats"]; v10 = fx["波段 v1.0（不調參數）"]["stats"]
    s = rs["stats"]
    avg = lambda d: round(sum(v for v in d.values() if v is not None) / max(1, sum(1 for v in d.values() if v is not None)), 2)
    oos_years = [str(y) for y in range(o["test_years"][0], o["test_years"][1] + 1)]
    v10_tov = avg({y: v for y, v in fx["波段 v1.0（不調參數）"]["turnover_by_year"].items() if y in oos_years})
    L = ["# 台股模型 v1.1 研究（滾動式驗證＋波段改版）", "",
         "> **只做研究，不改正式規則。** v1.0 的設定、每日名單、儀表板資料檔、排程都沒有動。模型依公開資料與固定規則產生，回測不代表未來，非投資建議。", "",
         "## 先講清楚",
         "- **總共測了 %d 組參數組合**（另有 4 個固定對照組，不調參數）。規則都在跑之前寫進 `tw-models/research/config_v11.json`，跑完沒有改。" % o["combinations_tested"],
         "- 驗證方法：**滾動式（擴張視窗）**。每年年初只用「前一年底以前」的資料挑出夏普值最高的一組，拿它跑這一年；%s～%s 每年一段，接成一條樣本外淨值。" % tuple(o["test_years"]),
         "- 另外列「改挑標準差最低的一組」當對照，主要結論看夏普值這條。",
         "- 期間：%s ～ %s。法人買賣超資料從 2019 年才有，2016～2018 年的測試期少了「籌碼」因子。" % tuple(o["period"]),
         "", "## 結論", "",
         "| | v1.1 滾動 | 0050 含息 | 波段 v1.0 |", "|---|---|---|---|",
         "| 年化報酬 | %s%% | %s%% | %s%% |" % (s.get("cagr_pct"), e.get("cagr_pct"), v10.get("cagr_pct")),
         "| 最大回撤 | %s%% | %s%% | %s%% |" % (s.get("mdd_pct"), e.get("mdd_pct"), v10.get("mdd_pct")),
         "| 夏普值 | %s | %s | %s |" % (s.get("sharpe"), e.get("sharpe"), v10.get("sharpe")),
         "| 平均年週轉率 | %s 倍 | — | %s 倍 |" % (avg(rs["turnover_by_year"]), v10_tov), "",
         "- **有沒有贏 0050**：%s（年化 %s%% 對 %s%%，夏普 %s 對 %s）。" % ("贏" if s.get("cagr_pct", -1e9) > e.get("cagr_pct", 1e9) else "**沒有，還是輸**", s.get("cagr_pct"), e.get("cagr_pct"), s.get("sharpe"), e.get("sharpe")),
         "- **有沒有贏 v1.0**：%s（年化 %s%% 對 %s%%，夏普 %s 對 %s）。" % ("贏" if s.get("sharpe", -1e9) > v10.get("sharpe", 1e9) else "**沒有**", s.get("cagr_pct"), v10.get("cagr_pct"), s.get("sharpe"), v10.get("sharpe")),
         "- **換手率**：v1.1 平均每年 %s 倍，v1.0 %s 倍。**最大回撤**：v1.1 %s%%，v1.0 %s%%。" % (avg(rs["turnover_by_year"]), v10_tov, s.get("mdd_pct"), v10.get("mdd_pct")),
         "", "![樣本外淨值](img/RESEARCH_v11.png)", "",
         "## 每年挑到的組合（夏普值挑選）", "", "| 年 | 挑到的組合 | 當年報酬 | 當年週轉率 |", "|---|---|---|---|"]
    for y, p in rs["picks"].items():
        L.append("| %s | %s | %s%% | %s 倍 |" % (y, p, s["yearly"].get(str(y)), rs["turnover_by_year"].get(y)))
    L += ["", "## 對照組（%s 起）" % o["test_years"][0], "", "| 組別 | 年化 | 最大回撤 | 夏普 | 平均年週轉 |", "|---|---|---|---|---|"]
    rows = [("v1.1 滾動（夏普挑選）", s, avg(rs["turnover_by_year"])), ("v1.1 滾動（最低標準差挑選）", ra["stats"], avg(ra["turnover_by_year"]))]
    rows += [(n, v["stats"], avg({y: t for y, t in v["turnover_by_year"].items() if y in oos_years}) if "0050" not in n else None) for n, v in fx.items()]
    for n, st, t in rows:
        L.append("| %s | %s%% | %s%% | %s | %s |" % (n, st.get("cagr_pct"), st.get("mdd_pct"), st.get("sharpe"), "—" if t is None else "%s 倍" % t))
    L += ["", "## 逐年報酬（%%）", "", "| 年 | v1.1 滾動 | 0050 | 波段 v1.0 | 等權大盤 | 長期 v1.0 |", "|---|---|---|---|---|---|"]
    for y in oos_years:
        L.append("| %s | %s | %s | %s | %s | %s |" % (y, s["yearly"].get(y), e["yearly"].get(y), v10["yearly"].get(y),
                                                fx["等權大盤（同股票池）"]["stats"]["yearly"].get(y), fx["長期 v1.0（診斷）"]["stats"]["yearly"].get(y)))
    L += ["", "「等權大盤」和 0050 的差距，大致就是「沒有重壓台積電」造成的落差。", "",
          "## 參數敏感度（24 組各自 %s 起的成績）" % o["test_years"][0], "", "| 組合 | 年化 | 最大回撤 | 夏普 | 平均年週轉 |", "|---|---|---|---|---|"]
    for n, v in sorted(o["variants"].items(), key=lambda x: -x[1]["stats"].get("sharpe", 0)):
        L.append("| %s | %s%% | %s%% | %s | %s 倍 |" % (n, v["stats"].get("cagr_pct"), v["stats"].get("mdd_pct"), v["stats"].get("sharpe"), v["avg_turnover"]))
    L += ["", "### 各選項的平均夏普值", "", "| 選項 | 平均夏普 |", "|---|---|"]
    for dim, opts in (("動能", ["VAM21", "VAM60-5"]), ("低波動", ["篩低波動", "不篩"]), ("出場", ["月換股出場", "2×ATR 停損", "v1.0 出場"]), ("紅燈", ["紅燈不開新倉", "紅燈留前 3"])):
        for op in opts:
            xs = [v["stats"].get("sharpe", 0) for n, v in o["variants"].items() if op in n.split("・")]
            L.append("| %s：%s | %s |" % (dim, op, round(sum(xs) / len(xs), 2) if xs else "—"))
    L += ["", "注意：這張表是 24 組「事後」的成績，挑最好的一組來看會偏樂觀；公平的成績是上面的滾動結果。", "",
          "## 規則說明",
          "- 股票池、成本、成交（隔天開盤含滑價）、籌碼與營收因子都和 v1.0 相同；每月第一個交易日排名，持有前 8 名等權。",
          "- 動能：VAM21 = 近 21 日報酬 ÷ 近 21 日日報酬標準差；VAM60-5 = 近 60 日報酬（扣最近 5 日）÷ 同期標準差。",
          "- 篩低波動：先排除近 60 日波動度最高的 30% 再排名。",
          "- 出場：月換股出場 = 只在換股日跌出前 8 名才賣；2×ATR = 另外收盤跌破「進場價 − 2×ATR(20)」就賣；v1.0 出場 = 另外照 v1.0 出場 A（−8%、破 20 日線、滿 20 日）。",
          "- 紅燈：不開新倉 = 水位總分 ≥ 6 時不買新股，已持有照出場規則；留前 3 = v1.0 規則。",
          "- 波段 v1.0 對照組照 v1.0 原樣（每週換股、出場 A、紅燈留前 3）。長期 v1.0 只做診斷，規則沒改。",
          "- " + T.survivorship_note(), ""]
    with open(os.path.join(ROOT, "docs", "RESEARCH_v1.1.md"), "w", encoding="utf-8") as f:
        f.write("\n".join(L))


if __name__ == "__main__":
    main()
