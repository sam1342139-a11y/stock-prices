"""Backtest engine for tw-models.

Rules (see docs/TW_MODELS.md):
- Strategy sees data up to the signal day's close; orders fill at the NEXT trading day's open.
- Costs: commission (rate x discount) on buys and sells, transaction tax on sells
  (stock 0.3%, ETF 0.1%), slippage on every fill. Fractional shares allowed. Cash earns 0.
- Prices are backward-adjusted (dividends reinvested within the position), so returns include dividends.
- In-sample and out-of-sample periods are run separately, each from fresh initial capital.
"""
import json, math, os, sys
import twdata as T

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)


class Sell:
    __slots__ = ("code", "frac", "reason")
    def __init__(self, code, frac=1.0, reason=""):
        self.code, self.frac, self.reason = code, frac, reason


class Buy:
    __slots__ = ("code", "value", "reason")
    def __init__(self, code, value, reason=""):
        self.code, self.value, self.reason = code, value, reason


class Broker:
    def __init__(self, bt):
        self.bt = bt
        self.cash = float(bt["initial_capital"])
        self.pos = {}       # code -> dict(shares, cost, entry_date, entry_px, peak, days, half_sold)
        self.trades = []    # closed (or partially closed) trades
        self.sell_notional = 0.0
        self.fees = 0.0     # commission + tax
        self.slip = 0.0     # slippage cost (price impact vs open)

    def _comm(self, notional):
        return notional * self.bt["commission_rate"] * self.bt["commission_discount"]

    def _tax(self, code, notional):
        return notional * (self.bt["tax_etf"] if T.is_etf(code) else self.bt["tax_stock"])

    def price(self, code, date, field="close_adj"):
        s = T.prices(code)
        i = s.at(date)
        return None if i is None else getattr(s, field)[i]

    def traded_on(self, code, date):
        return date in T.prices(code).idx

    def sell(self, code, frac, date, reason):
        p = self.pos.get(code)
        if not p:
            return True
        if not self.traded_on(code, date):
            return False  # suspended: retry next day
        op = T.prices(code).open_adj[T.prices(code).idx[date]]
        px = op * (1 - self.bt["slippage"])
        sh = p["shares"] * frac
        self.slip += sh * (op - px)
        gross = sh * px
        fee = self._comm(gross) + self._tax(code, gross)
        self.cash += gross - fee
        self.fees += fee
        self.sell_notional += gross
        cost = p["cost"] * frac
        self.trades.append({"code": code, "entry_date": p["entry_date"], "exit_date": date,
                            "days": p["days"], "pnl": gross - fee - cost, "ret_pct": (gross - fee) / cost * 100 - 100 if cost else 0,
                            "frac": frac, "reason": reason})
        if frac >= 0.999:
            del self.pos[code]
        else:
            p["shares"] -= sh
            p["cost"] -= cost
        return True

    def buy(self, code, value, date):
        if not self.traded_on(code, date) or value <= 0:
            return
        s = T.prices(code)
        px = s.open_adj[s.idx[date]] * (1 + self.bt["slippage"])
        rate = self.bt["commission_rate"] * self.bt["commission_discount"]
        value = min(value, self.cash / (1 + rate))
        if value < 1:
            return
        sh = value / px
        self.slip += sh * (px - s.open_adj[s.idx[date]])
        fee = self._comm(value)
        self.cash -= value + fee
        self.fees += fee
        p = self.pos.get(code)
        if p:
            p["shares"] += sh
            p["cost"] += value + fee
        else:
            self.pos[code] = {"shares": sh, "cost": value + fee, "entry_date": date, "entry_px": px,
                              "peak": s.close_adj[s.idx[date]], "days": 0, "half_sold": False}

    def nav(self, date):
        v = self.cash
        for c, p in self.pos.items():
            px = self.price(c, date)
            v += p["shares"] * (px or 0)
        return v

    def weights(self, date):
        n = self.nav(date)
        return {c: p["shares"] * (self.price(c, date) or 0) / n for c, p in self.pos.items()} if n else {}


def run(strategy, start, end, bt=None, delisted=None):
    """strategy(date, broker) -> list of orders, called after each close. Returns result dict."""
    bt = bt or T.config()["backtest"]
    br = Broker(bt)
    cal = T.calendar(start, end)
    pending, curve, exposure = [], [], []
    delisted = delisted or {}
    daily_rate = float(bt.get("cash_interest", 0) or 0) / 252.0
    for d in cal:
        # 0) cash interest (per trading day, simple daily accrual of the annual rate / 252)
        if daily_rate and br.cash > 0:
            br.cash *= 1 + daily_rate
        # 1) fill orders from previous close at today's open: sells first, then buys
        keep = []
        for o in [o for o in pending if isinstance(o, Sell)]:
            if not br.sell(o.code, o.frac, d, o.reason):
                keep.append(o)
        for o in [o for o in pending if isinstance(o, Buy)]:
            br.buy(o.code, o.value, d)
        pending = keep
        # 2) bookkeeping at close
        for c, p in list(br.pos.items()):
            s = T.prices(c)
            if d in s.idx:
                p["days"] += 1
                p["peak"] = max(p["peak"], s.close_adj[s.idx[d]])
            elif delisted.get(c) and d >= delisted[c]:
                # delisted: liquidate at last available close (no further fills possible)
                last = s.close_adj[-1] if s.close_adj else 0
                gross = p["shares"] * last
                br.cash += gross
                br.trades.append({"code": c, "entry_date": p["entry_date"], "exit_date": d, "days": p["days"],
                                  "pnl": gross - p["cost"], "ret_pct": gross / p["cost"] * 100 - 100 if p["cost"] else 0,
                                  "frac": 1.0, "reason": "下市，以最後收盤價結算"})
                del br.pos[c]
        nv = br.nav(d)
        curve.append((d, nv))
        exposure.append((nv - br.cash) / nv if nv else 0)
        # 3) new signals
        pending += strategy(d, br) or []
    return {"curve": curve, "trades": br.trades, "sell_notional": br.sell_notional, "fees": br.fees, "slippage": br.slip,
            "initial": float(bt["initial_capital"]), "exposure": exposure}


def target_orders(br, date, targets, reason=""):
    """Orders to move from current holdings to target weights {code: w} (signal at date's close)."""
    nav = br.nav(date)
    cur = br.weights(date)
    orders = []
    for c, w in cur.items():
        t = targets.get(c, 0)
        if t <= 0:
            orders.append(Sell(c, 1.0, reason))
        elif w > t + 0.02:
            orders.append(Sell(c, 1 - t / w, reason))
    for c, t in targets.items():
        w = cur.get(c, 0)
        if t > w + 0.02:
            orders.append(Buy(c, (t - w) * nav, reason))
    return orders


def metrics(res):
    curve = res["curve"]
    if len(curve) < 2:
        return {}
    navs = [v for _, v in curve]
    rets = [navs[i] / navs[i - 1] - 1 for i in range(1, len(navs))]
    n = len(rets)
    years = n / 252.0
    total = navs[-1] / res["initial"] - 1
    cagr = (navs[-1] / res["initial"]) ** (1 / years) - 1 if years > 0 else 0
    peak, mdd = navs[0], 0.0
    for v in navs:
        peak = max(peak, v)
        mdd = min(mdd, v / peak - 1)
    mean = sum(rets) / n
    sd = math.sqrt(sum((r - mean) ** 2 for r in rets) / (n - 1)) if n > 1 else 0
    sharpe = mean / sd * math.sqrt(252) if sd else 0
    tr = res["trades"]
    full = [t for t in tr]
    wins = sum(1 for t in full if t["pnl"] > 0)
    yearly, prev = {}, res["initial"]
    for i, (d, v) in enumerate(curve):
        if i == len(curve) - 1 or curve[i + 1][0][:4] != d[:4]:
            yearly[d[:4]] = round((v / prev - 1) * 100, 2)
            prev = v
    avg_nav = sum(navs) / len(navs)
    return {
        "start": curve[0][0], "end": curve[-1][0], "trading_days": n,
        "total_return_pct": round(total * 100, 2),
        "cagr_pct": round(cagr * 100, 2),
        "max_drawdown_pct": round(mdd * 100, 2),
        "sharpe": round(sharpe, 2),
        "trades": len(full),
        "win_rate_pct": round(wins / len(full) * 100, 1) if full else None,
        "avg_holding_days": round(sum(t["days"] for t in full) / len(full), 1) if full else None,
        "annual_turnover_x": round(res["sell_notional"] / avg_nav / years, 2) if years else None,
        "fees_ntd": round(res["fees"]),
        "costs_ntd": round(res["fees"] + res.get("slippage", 0)),
        # share of the pre-cost gain eaten by costs (commission + tax + slippage); None if there was no pre-cost gain
        "cost_share_pct": (round((res["fees"] + res.get("slippage", 0)) / (navs[-1] - res["initial"] + res["fees"] + res.get("slippage", 0)) * 100, 1)
                           if navs[-1] - res["initial"] + res["fees"] + res.get("slippage", 0) > 0 else None),
        "final_nav": round(navs[-1]),
        "yearly_return_pct": yearly,
    }


def benchmark_0050(start, end, bt=None):
    def strat(d, br):
        return [Buy("0050", br.cash * 0.999, "基準：買進持有 0050")] if not br.pos else []
    return run(strat, start, end, bt)


def periods():
    p = T.config()["periods"]
    last = T.calendar()[-1]
    return {"in_sample": (p["in_sample"][0], p["in_sample"][1]),
            "out_of_sample": (p["out_of_sample"][0], p["out_of_sample"][1] or last)}


PERIOD_ZH = {"in_sample": "樣本內（2019–2023，用來訂規則）", "out_of_sample": "樣本外（2024～今，用來驗證）"}


def write_report(model, title, variants, notes, problems, sources):
    """variants: {variant_name: {period: res}} (must include '0050'). Writes json, md and png."""
    import common as C
    out = {"model": model, "title": title, "notes": notes, "periods": {}}
    for per, (s, e) in periods().items():
        out["periods"][per] = {"from": s, "to": e, "label": PERIOD_ZH[per],
                               "results": {v: metrics(r[per]) for v, r in variants.items()}}
    C.write_json("tw-models/reports/%s_backtest.json" % model, out, problems, sources)
    imgs = _plot(model, variants)
    _markdown(model, title, out, notes, imgs, problems)


def _plot(model, variants):
    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
        from matplotlib import font_manager
        for f in font_manager.findSystemFonts():
            if "wqy" in f.lower() or "noto" in f.lower() and "cjk" in f.lower():
                font_manager.fontManager.addfont(f)
                plt.rcParams["font.family"] = font_manager.FontProperties(fname=f).get_name()
                break
        plt.rcParams["axes.unicode_minus"] = False
    except Exception:
        return {}
    import common as C
    imgs = {}
    for per in periods():
        fig, ax = plt.subplots(figsize=(7, 3.6), dpi=150)
        for v, r in variants.items():
            c = r[per]["curve"]
            if not c:
                continue
            base = r[per]["initial"]
            xs = list(range(len(c)))
            ax.plot(xs, [x[1] / base for x in c], label=v, linewidth=1.6 if v != "0050" else 1.2,
                    color="#888888" if v == "0050" else None)
            ticks = [i for i in range(len(c)) if i == 0 or c[i][0][:4] != c[i - 1][0][:4]]
            ax.set_xticks(ticks)
            ax.set_xticklabels([c[i][0][:4] for i in ticks])
        ax.set_title("%s 淨值（起始 = 1）" % PERIOD_ZH[per].split("（")[0])
        ax.grid(alpha=0.3)
        ax.legend(fontsize=8)
        fig.tight_layout()
        rel = "docs/img/BACKTEST_%s_%s.png" % (model, per)
        fig.savefig(C.out_path(rel))
        plt.close(fig)
        imgs[per] = rel
    return imgs


def _markdown(model, title, out, notes, imgs, problems):
    import common as C
    L = ["# %s 回測" % title, "",
         "> 模型依公開資料與固定規則產生，回測不代表未來，非投資建議。", "",
         "產生時間（UTC）：%s　｜　原始數字：`tw-models/reports/%s_backtest.json`" % (C.utc_now().strftime("%Y-%m-%d %H:%M"), model), ""]
    if notes:
        L += ["## 說明"] + ["- " + n for n in notes] + [""]
    rows = [("總報酬", "total_return_pct", "%"), ("年化報酬", "cagr_pct", "%"), ("最大回撤", "max_drawdown_pct", "%"),
            ("夏普值", "sharpe", ""), ("交易次數", "trades", ""), ("勝率", "win_rate_pct", "%"),
            ("平均持有天數", "avg_holding_days", ""), ("年週轉率", "annual_turnover_x", " 倍"),
            ("成本占報酬比例", "cost_share_pct", "%")]
    for per, p in out["periods"].items():
        res = p["results"]
        names = list(res.keys())
        L += ["## %s" % p["label"], "", "期間：%s ～ %s" % (p["from"], p["to"]), ""]
        if imgs.get(per):
            L += ["![%s](img/%s)" % (per, os.path.basename(imgs[per])), ""]
        L += ["| 指標 | " + " | ".join(names) + " |", "|---|" + "---|" * len(names)]
        for zh, k, u in rows:
            L.append("| %s | " % zh + " | ".join("" if res[n].get(k) is None else "%s%s" % (res[n][k], u) for n in names) + " |")
        years = sorted({y for n in names for y in res[n].get("yearly_return_pct", {})})
        L += ["", "**逐年報酬（%）**", "", "| 年 | " + " | ".join(names) + " |", "|---|" + "---|" * len(names)]
        for y in years:
            L.append("| %s | " % y + " | ".join(str(res[n].get("yearly_return_pct", {}).get(y, "")) for n in names) + " |")
        L.append("")
    if problems:
        L += ["## 資料問題", ""] + ["- " + x for x in problems[:30]] + [""]
    with open(C.out_path("docs/BACKTEST_%s.md" % model), "w", encoding="utf-8") as f:
        f.write("\n".join(L))
