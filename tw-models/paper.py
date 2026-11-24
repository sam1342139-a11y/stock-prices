"""Paper trading (simulated money) for the frozen v1.0 rules. Personal tracking only; no real orders.

Three portfolios, each starting with 1,000,000 NTD on the start date (config paper.start):
  core_satellite  0050 70% + long list 30% (equal weight), rebalanced quarterly with the long model
  long            long list 100% (equal weight), quarterly
  etf_0050        0050 buy and hold (benchmark)
Same engine and costs as the backtests (signal at close, fill at next day's open, commission x discount,
tax, slippage, dividends via adjusted prices). On the start date the portfolios enter the CURRENT long list
(signal at the start date's close) instead of waiting for the next quarterly day.

The whole history is re-run from the start date every day (deterministic, no hidden state), then written to:
  tw-models/paper/nav.csv          date, nav per portfolio
  tw-models/paper/latest.json      today's NAV, return, drawdown, holdings, pending orders, next rebalance
  docs/PAPER.md                    phone-friendly report with monthly returns

Usage: python3 tw-models/paper.py [--dry-run]
"""
import datetime, os, sys
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(1, os.path.join(os.path.dirname(HERE), "lib"))
import common as C
import twdata as T
import backtest as B
import models as M

NAMES = {"core_satellite": "七三組合（0050 70%＋長期 30%）", "long": "長期名單 100%", "etf_0050": "0050 100%"}


def first_day_targets(cfg, d, kind):
    picks, _, _, _, _ = M.long_rank(d, cfg)
    if kind == "etf_0050" or not picks:
        return {"0050": 1.0} if kind != "long" else {}
    w_etf = 0.7 if kind == "core_satellite" else 0.0
    tg = {"0050": w_etf} if w_etf else {}
    for c in picks:
        tg[c] = tg.get(c, 0) + (1 - w_etf) / len(picks)
    return tg


def strategy(cfg, kind, start_day):
    base = {"core_satellite": M.combo_strategy(cfg, 0.7), "long": M.long_strategy(cfg)}.get(kind)

    def strat(d, br):
        if d == start_day:
            return B.target_orders(br, d, first_day_targets(cfg, d, kind), "模擬開始：依目前名單建倉")
        if kind == "etf_0050":
            return []
        return base(d, br)
    return strat


def holdings(br_pos, d):
    out = []
    for c, p in br_pos.items():
        s = T.prices(c)
        i = s.at(d)
        px_adj = s.close_adj[i] if i is not None else None
        out.append({"code": c, "name": M.info(c).get("name") or ("元大台灣50" if c == "0050" else ""),
                    "value": round(p["shares"] * (px_adj or 0)), "entry_date": p["entry_date"],
                    "return_pct": round(((p["shares"] * (px_adj or 0)) / p["cost"] - 1) * 100, 2) if p["cost"] else None})
    return sorted(out, key=lambda x: -x["value"])


def run_one(cfg, kind, start, end):
    """Re-run the portfolio and also return the final broker positions (engine keeps them internal)."""
    captured = {}

    def strat(d, br):
        captured["br"] = br
        return inner(d, br)
    cal = T.calendar(start, end)
    inner = strategy(cfg, kind, cal[0])
    res = B.run(strat, start, end, delisted=T.delisted())
    return res, captured.get("br")


def main():
    cfg = T.config()
    pc = cfg.get("paper", {})
    start = pc.get("start", "2026-11-23")
    problems = []
    cal = T.calendar(start)
    if not cal:
        C.write_json("tw-models/paper/latest.json", {"start": start, "status": "尚未開始（還沒有開始日之後的交易日資料）"},
                     ["沒有 %s 之後的加權指數資料" % start], M.SOURCES)
        print("no trading days since", start)
        return
    end = cal[-1]
    results = {}
    for kind in NAMES:
        res, br = run_one(cfg, kind, start, end)
        m = B.metrics(res) if len(res["curve"]) >= 2 else {}
        nav = res["curve"][-1][1]
        navs = [v for _, v in res["curve"]]
        peak, mdd = navs[0], 0.0
        for v in navs:
            peak = max(peak, v)
            mdd = min(mdd, v / peak - 1)
        results[kind] = {"name": NAMES[kind], "nav": round(nav), "return_pct": round((nav / res["initial"] - 1) * 100, 2),
                         "max_drawdown_pct": round(mdd * 100, 2), "cash": round(br.cash) if br else None,
                         "holdings": holdings(br.pos, end) if br else [], "trades": len(res["trades"]),
                         "costs_ntd": m.get("costs_ntd"), "curve": res["curve"]}
    # nav.csv
    rows = []
    for i, (d, _) in enumerate(results["etf_0050"]["curve"]):
        rows.append([d] + [round(results[k]["curve"][i][1]) for k in NAMES])
    C.write_csv("tw-models/paper/nav.csv", ["date"] + list(NAMES), rows)
    # monthly returns
    monthly = {}
    for k in NAMES:
        prev = 1_000_000.0
        for i, (d, v) in enumerate(results[k]["curve"]):
            last = i == len(results[k]["curve"]) - 1 or results[k]["curve"][i + 1][0][:7] != d[:7]
            if last:
                monthly.setdefault(d[:7], {})[k] = round((v / prev - 1) * 100, 2)
                prev = v
    out = {"start": start, "date": end, "version": cfg.get("version"), "initial_capital": 1_000_000,
           "rule": "每組 100 萬元；訊號用收盤後資料、隔天開盤成交；成本與回測相同；七三組合與長期每季（1、4、7、10 月 15 日後第一個交易日）換股",
           "next_rebalance": M.next_rebalance_date(cfg, end),
           "portfolios": {k: {x: v for x, v in r.items() if x != "curve"} for k, r in results.items()},
           "monthly_return_pct": monthly,
           "note": "模擬資金，非真實帳戶；模型依公開資料與固定規則產生，回測與模擬不代表未來，非投資建議。"}
    C.write_json("tw-models/paper/latest.json", out, problems, M.SOURCES)
    write_md(out, {k: results[k]["curve"] for k in NAMES})
    print("paper", end, {k: results[k]["nav"] for k in NAMES})


QS_MIN_DAYS = 20


def quantstats_section(curves):
    """Advanced figures via quantstats once there are enough days; report only (rules unchanged)."""
    days = min((len(c) for c in curves.values()), default=0)
    L = ["", "## 進階指標（quantstats）", ""]
    if days < QS_MIN_DAYS:
        return L + ["累積滿 %d 個交易日後自動產生（目前 %d 天）。" % (QS_MIN_DAYS, days)]
    try:
        import qs_report as Q
        res = {NAMES[k]: Q.metrics(c) for k, c in curves.items()}
    except Exception as e:
        return L + ["這次沒有產生（%s）。" % type(e).__name__]
    L += Q.table_md(list(res), res)
    img = Q.heatmap(curves["core_satellite"], C.out_path("docs/img/PAPER_core_satellite_monthly.png"), "七三組合 模擬資金 月報酬（%）")
    if img:
        L += ["", "![七三組合月報酬](img/PAPER_core_satellite_monthly.png)"]
    return L


def write_md(o, curves=None):
    L = ["# 模擬資金追蹤", "", "> 模擬資金，非真實帳戶；模型依公開資料與固定規則產生，非投資建議。", "",
         "規則版本 %s｜開始日 %s｜最新 %s｜每組起始 100 萬元｜下次換股：%s" % (o["version"], o["start"], o["date"], o["next_rebalance"]), "",
         "## 目前成績", "", "| 組合 | 淨值 | 報酬 | 最大回撤 | 交易次數 |", "|---|---|---|---|---|"]
    for k, p in o["portfolios"].items():
        L.append("| %s | %s | %s%% | %s%% | %s |" % (p["name"], format(p["nav"], ","), p["return_pct"], p["max_drawdown_pct"], p["trades"]))
    L += ["", "## 每月報酬（%）", "", "| 月份 | " + " | ".join(NAMES.values()) + " |", "|---|" + "---|" * len(NAMES)]
    for ym in sorted(o["monthly_return_pct"]):
        L.append("| %s | " % ym + " | ".join(str(o["monthly_return_pct"][ym].get(k, "")) for k in NAMES) + " |")
    L += ["", "## 目前持股（七三組合）", "", "| 代號 | 名稱 | 市值 | 持有報酬 |", "|---|---|---|---|"]
    for h in o["portfolios"]["core_satellite"]["holdings"]:
        L.append("| %s | %s | %s | %s%% |" % (h["code"], h["name"], format(h["value"], ","), h["return_pct"]))
    L += quantstats_section(curves or {})
    L += ["", "原始數字：`tw-models/paper/latest.json`、`tw-models/paper/nav.csv`", ""]
    with open(C.out_path("docs/PAPER.md"), "w", encoding="utf-8") as f:
        f.write("\n".join(L))


if __name__ == "__main__":
    main()
