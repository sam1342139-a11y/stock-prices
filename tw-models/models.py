"""Stock-selection models: D swing, E long, F old screen. Rules: docs/TW_MODELS.md §D–§F.

Usage:
  python3 tw-models/models.py --backtest [--dry-run]   write reports + docs for swing / long / old_screen / comparison
  python3 tw-models/models.py --latest   [--dry-run]   write tw-models/latest/swing.json and long.json
No look-ahead: every feature at signal day d uses data dated <= d (revenue/financials by their `available` date);
orders fill at the next trading day's open (engine).
"""
import bisect, datetime, json, math, os, sys
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(1, os.path.join(os.path.dirname(HERE), "lib"))
import common as C
import twdata as T
import backtest as B

FOOTER = "模型依公開資料與固定規則產生，回測不代表未來，非投資建議。"
SOURCES = [{"name": "FinMind（歷史股價、本益比、法人、月營收、除權息、季報）", "url": "https://api.finmindtrade.com/api/v4/data"},
           {"name": "證交所 OpenAPI（每日累加）", "url": "https://openapi.twse.com.tw/"}]


# ---------------------------------------------------------------- features
class F:
    """Per-code cached arrays with prefix sums for fast moving averages."""
    _cache = {}

    def __init__(self, code):
        s = T.prices(code)
        self.s = s
        self.cs = [0.0]
        for v in s.close_adj:
            self.cs.append(self.cs[-1] + v)
        self.vs = [0.0]
        for v in s.volume:
            self.vs.append(self.vs[-1] + v)

    @classmethod
    def of(cls, code):
        f = cls._cache.get(code)
        if f is None:
            f = cls._cache[code] = cls(code)
        return f

    def ma(self, i, n):
        return (self.cs[i + 1] - self.cs[i + 1 - n]) / n if i + 1 >= n else None

    def avg_lots(self, i, n):
        return (self.vs[i + 1] - self.vs[i + 1 - n]) / n / 1000 if i + 1 >= n else None


def rev_features(code, d):
    """(avg yoy last 3 months, avg yoy last 12 months, latest-month-is-12m-high, latest yoy) using rows available <= d."""
    rows = [(ym, v) for ym, v, av in T.revenue(code) if av and av <= d and v]
    if len(rows) < 24:
        return None
    m = dict(rows)
    yms = [ym for ym, _ in rows]

    def yoy(ym):
        y, mo = int(ym[:4]), ym[5:]
        prev = m.get("%04d-%s" % (y - 1, mo))
        return m[ym] / prev - 1 if prev else None
    last12 = yms[-12:]
    ys = [yoy(x) for x in last12]
    if any(v is None for v in ys):
        return None
    a3, a12 = sum(ys[-3:]) / 3, sum(ys) / 12
    high = m[yms[-1]] >= max(m[x] for x in last12)
    return a3, a12, high, ys[-1]


def pct_rank(values):
    """{key: percentile 0..1} (higher value -> higher rank). None values get 0."""
    ok = sorted((v, k) for k, v in values.items() if v is not None)
    n = len(ok)
    out = {k: 0.0 for k in values}
    for r, (v, k) in enumerate(ok):
        out[k] = r / (n - 1) if n > 1 else 1.0
    return out


def universe_codes():
    return [r["code"] for r in T.universe() if r["code"] != "0050"]


INFO = None


def info(code):
    global INFO
    if INFO is None:
        INFO = {r["code"]: r for r in T.universe()}
    return INFO.get(code, {})


# ---------------------------------------------------------------- D. swing
_SWING_CACHE, _LONG_CACHE = {}, {}


def swing_rank(d, cfg):
    if d not in _SWING_CACHE:
        _SWING_CACHE[d] = _swing_rank(d, cfg)
    return _SWING_CACHE[d]


def _swing_rank(d, cfg):
    sc = cfg["swing"]
    cand, mom, trend, flow, rev = [], {}, {}, {}, {}
    for c in universe_codes():
        f = F.of(c)
        s = f.s
        i = s.idx.get(d)
        if i is None or i < 65:
            continue
        if s.close[i] <= sc["min_price"] or (f.avg_lots(i, 20) or 0) <= sc["min_avg_volume_lots_20d"]:
            continue
        cand.append(c)
        mom[c] = s.close_adj[i - 5] / s.close_adj[i - 60] - 1
        m20, m60 = f.ma(i, 20), f.ma(i, 60)
        trend[c] = (s.close_adj[i] > m20) + (s.close_adj[i] > m60)
        ins = T.inst(c)
        net = sum((ins.get(s.dates[j], (0, 0, 0))[0] + ins.get(s.dates[j], (0, 0, 0))[1]) for j in range(i - 9, i + 1))
        vol = f.vs[i + 1] - f.vs[i - 9]
        flow[c] = net / vol if vol else None
        rf = rev_features(c, d)
        rev[c] = None if rf is None else (1.0 if rf[0] > rf[1] else 0.0) + (0.5 if rf[2] else 0.0)
    w = sc["weights"]
    P = {"momentum": pct_rank(mom), "trend": pct_rank(trend), "flow": pct_rank(flow), "revenue": pct_rank(rev)}
    raw = {"momentum": mom, "trend": trend, "flow": flow, "revenue": rev}
    score = {c: sum(w[k] * P[k][c] for k in P) for c in cand}
    ranked = sorted(cand, key=lambda c: -score[c])
    return ranked, score, P, raw


def last_of_week(cal):
    """Set of trading days that are the last trading day of their ISO week."""
    out = set()
    for a, b in zip(cal, cal[1:] + [None]):
        if b is None or datetime.date.fromisoformat(a).isocalendar()[:2] != datetime.date.fromisoformat(b).isocalendar()[:2]:
            out.add(a)
    return out


def first_of_month(cal):
    """Set of trading days that are the first trading day of their month."""
    return {b for a, b in zip([None] + cal[:-1], cal) if a is None or a[:7] != b[:7]}


def swing_strategy(cfg, exit_rule, red_rule, regime, freq="week", buffer=0, min_hold=0):
    """D swing. Low-turnover options (docs/TW_MODELS.md §D):
    freq "week" = rank on the last trading day of each week; "month" = rank on the first trading day of each month.
    buffer N > 0: no fixed 20-day time exit; on ranking days a holding is sold only if it fell out of the top N.
    min_hold N > 0: no exit before N trading days held, except stop-loss (A: -8%; B: 30% trailing) and the red-light rule."""
    sc = cfg["swing"]
    cal = T.calendar()
    rank_days = last_of_week(cal) if freq == "week" else first_of_month(cal)
    top_n = sc["top_n"]

    def strat(d, br):
        orders, selling = [], set()
        for c, p in br.pos.items():
            f = F.of(c)
            i = f.s.idx.get(d)
            if i is None:
                continue
            px = f.s.close_adj[i]
            young = min_hold and p["days"] < min_hold
            if exit_rule == "A":
                if px <= p["entry_px"] * (1 - sc["exit_a"]["stop_loss_pct"] / 100):
                    orders.append(B.Sell(c, 1.0, "停損 −8%")); selling.add(c)
                elif young:
                    continue
                elif px < f.ma(i, sc["exit_a"]["ma_days"]):
                    orders.append(B.Sell(c, 1.0, "跌破 20 日均線")); selling.add(c)
                elif not buffer and p["days"] >= sc["exit_a"]["max_hold_days"]:
                    orders.append(B.Sell(c, 1.0, "持有滿 20 個交易日")); selling.add(c)
            else:
                dd = px / p["peak"] - 1
                if dd <= -sc["exit_b"]["trail_all_pct"] / 100:
                    orders.append(B.Sell(c, 1.0, "從高點回落 30% 全賣")); selling.add(c)
                elif young:
                    continue
                elif dd <= -sc["exit_b"]["trail_half_pct"] / 100 and not p["half_sold"]:
                    orders.append(B.Sell(c, 0.5, "從高點回落 20% 賣一半")); p["half_sold"] = True
        if d in rank_days:
            ranked, score, _, _ = swing_rank(d, cfg)
            red = red_rule and regime.get(d, {}).get("total", 0) >= 6
            n = sc["red_light_top_n"] if red else top_n
            if red:
                keep = set(ranked[:n])
                for c in list(br.pos):
                    if c not in keep and c not in selling:
                        orders.append(B.Sell(c, 1.0, "水位紅燈，只持有前 3 名")); selling.add(c)
            elif buffer:
                keep = set(ranked[:buffer])
                for c, p in list(br.pos.items()):
                    if c not in keep and c not in selling and not (min_hold and p["days"] < min_hold):
                        orders.append(B.Sell(c, 1.0, "跌出前 %d 名" % buffer)); selling.add(c)
            held = [c for c in br.pos if c not in selling]
            slots = n - len(held)
            nav = br.nav(d)
            for c in ranked:
                if slots <= 0:
                    break
                if c in br.pos:
                    continue
                orders.append(B.Buy(c, nav / top_n, "波段名單第 %d 名" % (ranked.index(c) + 1)))
                slots -= 1
        return orders
    return strat


# ---------------------------------------------------------------- E. long
def rebalance_days(cfg):
    lc = cfg["long"]
    cal = T.calendar()
    out = []
    for y in range(int(cal[0][:4]), int(cal[-1][:4]) + 1):
        for m in lc["rebalance_months"]:
            k = bisect.bisect_right(cal, "%04d-%02d-%02d" % (y, m, lc["rebalance_day"]))
            if k < len(cal):
                out.append(cal[k])
    return sorted(set(out))


def yearly_cash_dividends(code, d):
    out = {}
    for r in T.dividends(code):
        if r["ex_date"] <= d and "息" in (r["kind"] or ""):
            try:
                out[int(r["ex_date"][:4])] = out.get(int(r["ex_date"][:4]), 0) + float(r["amount"] or 0)
            except ValueError:
                pass
    return out


def fin_rows(code):
    p = os.path.join(T.DATA, "fin", code + ".csv.gz")
    return T._read(p) if os.path.exists(p) else []


def long_rank(d, cfg):
    if d not in _LONG_CACHE:
        _LONG_CACHE[d] = _long_rank(d, cfg)
    return _LONG_CACHE[d]


def _long_rank(d, cfg):
    lc = cfg["long"]
    y = int(d[:4])
    five_ago = "%04d%s" % (y - 5, d[4:])
    cand, value, avgdy, stable, gmvol, revpos, risk = [], {}, {}, {}, {}, {}, {}
    for c in universe_codes():
        f = F.of(c)
        s = f.s
        i = s.idx.get(d)
        if i is None or not s.dates or s.dates[0] > five_ago:
            continue
        if (f.avg_lots(i, 60) or 0) <= lc["min_avg_volume_lots_60d"]:
            continue
        div = yearly_cash_dividends(c, d)
        if not all(div.get(yy, 0) > 0 for yy in range(y - 5, y)):
            continue
        cand.append(c)
        per = T.per(c)
        hist = [(dd, v) for dd, v in per.items() if five_ago <= dd <= d]
        cur = per.get(d) or (hist[-1][1] if hist else None)
        vals = []
        if cur:
            for k in (0, 2):  # PE, PB: percentile of current within own 5y (lower is better)
                xs = sorted(v[k] for _, v in hist if v[k] and v[k] > 0)
                if xs and cur[k] and cur[k] > 0:
                    vals.append(1 - bisect.bisect_right(xs, cur[k]) / len(xs))
        value[c] = sum(vals) / len(vals) if vals else None
        three_ago = "%04d%s" % (y - 3, d[4:])
        dys = [v[1] for dd, v in hist if dd >= three_ago and v[1] is not None]
        avgdy[c] = sum(dys) / len(dys) if dys else None
        stable[c] = 1.0 if div.get(y - 3, 0) <= div.get(y - 2, 0) <= div.get(y - 1, 0) else 0.0
        q = [r for r in fin_rows(c) if r["available"] <= d and r["revenue"] and r["gross_profit"]]
        if len(q) >= 4:
            gms = [float(r["gross_profit"]) / float(r["revenue"]) for r in q[-4:] if float(r["revenue"])]
            m = sum(gms) / len(gms)
            gmvol[c] = math.sqrt(sum((g - m) ** 2 for g in gms) / len(gms)) if gms else None
        else:
            gmvol[c] = None
        rf = rev_features(c, d)
        revpos[c] = None if rf is None else (1.0 if rf[1] > 0 else 0.0)
        j0 = max(0, i - 251)
        peak, mdd = s.close_adj[j0], 0.0
        for j in range(j0, i + 1):
            peak = max(peak, s.close_adj[j])
            mdd = min(mdd, s.close_adj[j] / peak - 1)
        risk[c] = mdd  # closer to 0 is better
    p_value = pct_rank(value)
    p_dy = pct_rank(avgdy)
    p_gm = pct_rank({c: (-v if v is not None else None) for c, v in gmvol.items()})
    p_risk = pct_rank(risk)
    factors = {}
    for c in cand:
        factors[c] = {
            "價值": p_value[c],
            "收益": (p_dy[c] + stable[c]) / 2,
            "品質": (p_gm[c] + (revpos[c] or 0)) / 2,
            "風險": p_risk[c],
        }
    score = {c: sum(v.values()) for c, v in factors.items()}
    ranked = sorted(cand, key=lambda c: -score[c])
    picks, per_ind = [], {}
    for c in ranked:
        ind = info(c).get("industry", "")
        if per_ind.get(ind, 0) >= lc["max_per_industry"]:
            continue
        picks.append(c)
        per_ind[ind] = per_ind.get(ind, 0) + 1
        if len(picks) >= lc["top_n"]:
            break
    extra = {c: {"avg_dy_3y": avgdy.get(c), "dividend_stable": stable.get(c), "gm_vol": gmvol.get(c),
                 "rev_yoy_12m_pos": revpos.get(c), "mdd_1y": risk.get(c)} for c in cand}
    return picks, ranked, score, factors, extra


def long_strategy(cfg):
    days = set(rebalance_days(cfg))
    cal = T.calendar()
    nxt = {a: b for a, b in zip(cal, cal[1:])}

    def strat(d, br):
        if nxt.get(d) not in days:
            return []
        picks, _, _, _, _ = long_rank(d, cfg)
        if not picks:
            return []
        w = 1.0 / len(picks)
        return B.target_orders(br, d, {c: w for c in picks}, "每季換股")
    return strat


def combo_strategy(cfg, w_etf=0.7):
    """0050 w_etf + long list (1 - w_etf), rebalanced to target weights on the long model's quarterly days."""
    days = set(rebalance_days(cfg))
    cal = T.calendar()
    nxt = {a: b for a, b in zip(cal, cal[1:])}

    def strat(d, br):
        if nxt.get(d) not in days:
            return []
        picks, _, _, _, _ = long_rank(d, cfg)
        tg = {"0050": w_etf}
        for c in picks:
            tg[c] = tg.get(c, 0) + (1 - w_etf) / len(picks)
        return B.target_orders(br, d, tg, "每季再平衡")
    return strat


# ---------------------------------------------------------------- F. old screen
def old_rank(d, cfg):
    oc = cfg["old_screen"]
    score, r20, detail = {}, {}, {}
    for c in oc["universe"]:
        s = T.prices(c)
        i = s.idx.get(d)
        if i is None or i < 20:
            continue
        rf = rev_features(c, d)
        pe = T.per(c).get(d, (None, None, None))
        conds = {
            "營收年增≥10%": bool(rf and rf[3] is not None and rf[3] * 100 >= oc["revenue_yoy_min_pct"]),
            "本益比<20": bool(pe[0] and 0 < pe[0] < oc["pe_max"]),
            "殖利率≥3%": bool(pe[1] and pe[1] >= oc["dividend_yield_min_pct"]),
            "近20日上漲": s.close_adj[i] > s.close_adj[i - 20],
        }
        score[c] = sum(conds.values())
        r20[c] = s.close_adj[i] / s.close_adj[i - 20] - 1
        detail[c] = conds
    ranked = sorted(score, key=lambda c: (-score[c], -r20[c]))
    return ranked[:oc["top_n"]], ranked, score, detail


def old_strategy(cfg):
    cal = T.calendar()
    month_end = {a for a, b in zip(cal, cal[1:] + [None]) if b is None or a[:7] != b[:7]}

    def strat(d, br):
        if d not in month_end:
            return []
        picks, _, _, _ = old_rank(d, cfg)
        w = 1.0 / len(picks) if picks else 0
        return B.target_orders(br, d, {c: w for c in picks}, "每月重排")
    return strat


# ---------------------------------------------------------------- run
def regime_map():
    import regime_tw as R
    return R.compute_all(T.config())


def backtest_all():
    cfg = T.config()
    reg = regime_map()
    dl = T.delisted()
    surv = T.survivorship_note()
    per = B.periods()
    res = {k: {} for k in ["swing_A", "swing_B", "swing_A_red", "swing_B_red", "long", "old_screen", "0050"]}
    for p, (s, e) in per.items():
        res["swing_A"][p] = B.run(swing_strategy(cfg, "A", False, reg), s, e, delisted=dl)
        res["swing_B"][p] = B.run(swing_strategy(cfg, "B", False, reg), s, e, delisted=dl)
        res["swing_A_red"][p] = B.run(swing_strategy(cfg, "A", True, reg), s, e, delisted=dl)
        res["swing_B_red"][p] = B.run(swing_strategy(cfg, "B", True, reg), s, e, delisted=dl)
        res["long"][p] = B.run(long_strategy(cfg), s, e, delisted=dl)
        res["old_screen"][p] = B.run(old_strategy(cfg), s, e, delisted=dl)
        res["0050"][p] = B.benchmark_0050(s, e)
        print("done", p, flush=True)
    common = ["訊號用當天收盤後資料，隔天開盤成交；手續費 ×0.6 折、證交稅（一般股 0.3%、ETF 0.1%）、滑價 0.1%；含息（還原權息價）；現金不計利息。",
              "樣本內（2019–2023）與樣本外（2024～今）各自從 100 萬元開始；規則在樣本內訂好後，未依樣本外結果調整。"]
    B.write_report("swing", "D. 波段（swing）", {
        "出場A（−8%停損/破20MA/滿20日）": res["swing_A"], "出場B（高點回落20%半/30%全）": res["swing_B"],
        "出場A＋紅燈只留前3": res["swing_A_red"], "出場B＋紅燈只留前3": res["swing_B_red"], "0050": res["0050"]},
        common + ["每週最後一個交易日收盤後排名，下一個交易日開盤進場；前 8 名等權重，有空位才補。", surv,
                  "全額交割股的歷史名單取不到，未排除（股價 > 10 元、20 日均量 > 1,000 張已排除大多數）。"], [], SOURCES)
    B.write_report("long", "E. 長期（long）", {"long": res["long"], "0050": res["0050"]},
                   common + ["1、4、7、10 月 15 日後第一個交易日開盤換股（前一個交易日收盤後選股）；前 8 名等權重，同產業最多 3 檔。", surv,
                             "現金股利以除權息結果中含「息」的事件判斷；權息合併事件的金額含股票股利，股利穩定判斷可能略有偏差。"], [], SOURCES)
    B.write_report("old_screen", "F. 舊篩選法", {"舊篩選法": res["old_screen"], "0050": res["0050"]},
                   common + ["33 檔固定股票池；4 個條件各 1 分，每月最後一個交易日收盤後重排，取前 8 名等權重（同分以近 20 日報酬高者優先）。",
                             "注意：股票池是「現在」挑出來的 33 檔大型股，回測期間早期也用同一份名單，本身就有後見之明，報酬可能高估。"], [], SOURCES)
    B.write_report("comparison", "五組比較（波段兩種出場、長期、舊篩選法、0050）", {
        "波段A": res["swing_A"], "波段B": res["swing_B"], "長期": res["long"], "舊篩選法": res["old_screen"], "0050": res["0050"]},
        common + [surv], [], SOURCES)
    return res


def reason_swing(P, raw, c):
    names = {"momentum": "動能", "trend": "趨勢", "flow": "籌碼", "revenue": "營收"}
    top = sorted(P, key=lambda k: -P[k][c])[:2]
    bits = []
    for k in top:
        if k == "momentum":
            bits.append("近 60 日（扣最近 5 日）漲 %.0f%%" % (raw[k][c] * 100))
        elif k == "trend":
            bits.append("站上 20 日與 60 日均線" if raw[k][c] == 2 else "站上 20 或 60 日均線")
        elif k == "flow":
            bits.append("投信外資近 10 日買超占成交量 %.1f%%" % ((raw[k][c] or 0) * 100))
        elif k == "revenue":
            bits.append("營收加速成長" if (raw[k][c] or 0) >= 1 else "營收創 12 個月新高")
    return "、".join(bits)


def write_latest():
    cfg = T.config()
    problems = []
    cal = T.calendar()
    d = cal[-1]
    n_fin = len([c for c in universe_codes() if os.path.exists(os.path.join(T.DATA, "fin", c + ".csv.gz"))])
    if n_fin < 0.8 * len(universe_codes()):
        problems.append("季報資料只有 %d／%d 檔（回補中），長期名單的「毛利率穩定」暫時不完整" % (n_fin, len(universe_codes())))
    if datetime.date.fromisoformat(d).weekday() != 4:
        problems.append("最新交易日 %s 不是週五，名單以最新交易日計算" % d)
    ranked, score, P, raw = swing_rank(d, cfg)
    reg = regime_map().get(d)
    red = bool(reg and reg["total"] >= 6)
    n = cfg["swing"]["red_light_top_n"] if red else cfg["swing"]["top_n"]
    prev = C.read_json("tw-models/latest/swing.json", {}) or {}
    prev_codes = [x["code"] for x in prev.get("list", [])]
    lst = []
    for k, c in enumerate(ranked[:n]):
        s = F.of(c).s
        i = s.idx[d]
        lst.append({"rank": k + 1, "code": c, "name": info(c).get("name"), "score": round(score[c], 3),
                    "reason": reason_swing(P, raw, c), "close": s.close[i],
                    "stop_price": round(s.close[i] * (1 - cfg["swing"]["exit_a"]["stop_loss_pct"] / 100), 2),
                    "ma20": round(sum(s.close[i - 19:i + 1]) / 20, 2)})
    cur = [x["code"] for x in lst]
    C.write_json("tw-models/latest/swing.json", {
        "date": d, "trade_on": "下一個交易日開盤", "regime_total": reg["total"] if reg else None,
        "red_light": red, "note": "水位紅燈（總分 ≥ 6）時只列前 3 名" if red else "前 %d 名等權重" % n,
        "caution": "回測未勝過 0050，僅供觀察",
        "stop_rule": "停損價 = 訊號日收盤 × 0.92（實際以進場價 −8% 計）；或收盤跌破 20 日均線；或持有滿 20 個交易日",
        "list": lst,
        "changes": {"new": [c for c in cur if c not in prev_codes], "dropped": [c for c in prev_codes if c not in cur]},
        "footer": FOOTER}, problems, SOURCES)
    # long: as of the latest rebalance signal day
    days = rebalance_days(cfg)
    sig = None
    for rd in days:
        k = cal.index(rd)
        if k > 0 and cal[k - 1] <= d:
            sig = cal[k - 1]
    picks, ranked_l, score_l, factors, extra = long_rank(sig, cfg)
    prevl = C.read_json("tw-models/latest/long.json", {}) or {}
    prev_l = [x["code"] for x in prevl.get("list", [])]
    L = []
    for k, c in enumerate(picks):
        top3 = sorted(factors[c], key=lambda f: -factors[c][f])[:3]
        e = extra[c]
        why = []
        for f in top3:
            if f == "價值":
                why.append("本益比／淨值比在自己近 5 年偏低")
            elif f == "收益":
                why.append("近 3 年平均殖利率 %.1f%%%s" % (e["avg_dy_3y"] or 0, "、股利穩定成長" if e["dividend_stable"] else ""))
            elif f == "品質":
                why.append("毛利率穩定" + ("、近 12 個月營收年增" if e["rev_yoy_12m_pos"] else ""))
            elif f == "風險":
                why.append("近 1 年最大跌幅 %.0f%%" % abs((e["mdd_1y"] or 0) * 100))
        L.append({"rank": k + 1, "code": c, "name": info(c).get("name"), "industry": info(c).get("industry"),
                  "score": round(score_l[c], 3), "top_factors": top3, "reason": "；".join(why)})
    cl = [x["code"] for x in L]
    C.write_json("tw-models/latest/long.json", {
        "signal_date": sig, "trade_on": [x for x in days if x > sig][0] if [x for x in days if x > sig] else None,
        "next_rebalance": "%s 月 %d 日後第一個交易日" % (next((m for m in cfg["long"]["rebalance_months"] if m > int(d[5:7]) or (m == int(d[5:7]) and int(d[8:]) <= cfg["long"]["rebalance_day"])), cfg["long"]["rebalance_months"][0]), cfg["long"]["rebalance_day"]),
        "rule": "每季（1、4、7、10 月 15 日後第一個交易日）換股；前 8 名等權重，同產業最多 3 檔；股利再投入",
        "list": L, "changes": {"new": [c for c in cl if c not in prev_l], "dropped": [c for c in prev_l if c not in cl]},
        "footer": FOOTER}, problems, SOURCES)
    write_core_satellite(cfg, d, sig, L, days, problems)
    print("swing", d, cur, "| long", sig, cl)


def next_rebalance_date(cfg, d):
    """Next quarterly rebalance day after d (first weekday after the 15th; TWSE holidays not known in advance)."""
    lc = cfg["long"]
    y, m = int(d[:4]), int(d[5:7])
    for yy in (y, y + 1):
        for mm in lc["rebalance_months"]:
            x = datetime.date(yy, mm, lc["rebalance_day"]) + datetime.timedelta(days=1)
            while x.weekday() >= 5:
                x += datetime.timedelta(days=1)
            if x.isoformat() > d:
                return x.isoformat()


def write_core_satellite(cfg, d, sig, long_list, days, problems):
    """tw-models/latest/core_satellite.json: 0050 70% + long list 30% (equal weight), quarterly rebalance."""
    w_etf = 0.7
    n = len(long_list)
    alloc = [{"code": "0050", "name": "元大台灣50", "role": "核心", "weight_pct": round(w_etf * 100, 2)}]
    for x in long_list:
        alloc.append({"code": x["code"], "name": x["name"], "industry": x.get("industry"), "role": "衛星（長期名單）",
                      "weight_pct": round((1 - w_etf) * 100 / n, 2) if n else 0})
    rep = C.read_json("tw-models/reports/combo_backtest.json", {}) or {}
    summary = {}
    for per, p in (rep.get("periods") or {}).items():
        res = p.get("results", {})
        summary[per] = {"label": p.get("label"), "from": p.get("from"), "to": p.get("to")}
        for name, key in (("0050 70%＋長期 30%", "core_satellite"), ("0050", "etf_0050"), ("長期 100%", "long_100")):
            m = res.get(name) or {}
            summary[per][key] = {"total_return_pct": m.get("total_return_pct"), "max_drawdown_pct": m.get("max_drawdown_pct"),
                                 "sharpe": m.get("sharpe")}
    probs = list(problems)
    if not summary:
        probs.append("找不到 tw-models/reports/combo_backtest.json，回測摘要從缺")
    past = [x for x in days if x > sig]
    C.write_json("tw-models/latest/core_satellite.json", {
        "date": d,
        "rule": "0050 占 70%、長期名單占 30%（平均分配）；每季（1、4、7、10 月 15 日後第一個交易日，與長期換股同一天）再平衡回目標比例",
        "target_allocation": alloc,
        "long_list_signal_date": sig,
        "last_rebalance": past[0] if past else None,
        "next_rebalance": next_rebalance_date(cfg, d),
        "next_rebalance_note": "以 15 日後第一個平日估計；遇國定假日順延到下一個交易日",
        "backtest_summary": summary,
        "backtest_report": "docs/BACKTEST_combo.md",
        "footer": FOOTER}, probs, SOURCES)


if __name__ == "__main__":
    if "--backtest" in sys.argv:
        backtest_all()
    if "--latest" in sys.argv:
        write_latest()
