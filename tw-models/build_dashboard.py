"""Builds the dashboard data file (public data only) that the dashboard routine uploads.

Same content the routine used to assemble by hand, plus `stock_analysis` (33 large caps + 0050, with 7-day
headlines from news/tw_stocks.json), `stock_news`, `us_regime` (regime/regime.json) and `closes`: every TWSE security's daily close
since CLOSES_FROM (from tw/closes/*.csv), so the page can value the account on any past day itself.
Usage: python3 tw-models/build_dashboard.py [out_path]     (default /tmp/tw_dashboard.json)
"""
import csv, glob, json, os, sys
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CLOSES_FROM = "2026-10-01"   # account ledger starts in October 2026
MAX_DAYS = 400


def j(rel):
    return json.load(open(os.path.join(ROOT, rel), encoding="utf-8"))


def closes():
    rows = []
    for f in sorted(glob.glob(os.path.join(ROOT, "tw", "closes", "*.csv"))):
        if os.path.basename(f)[:7] < CLOSES_FROM[:7]:
            continue
        with open(f, encoding="utf-8") as fh:
            rows += [r for r in csv.DictReader(fh) if r["date"] >= CLOSES_FROM]
    dates = sorted({r["date"] for r in rows})[-MAX_DAYS:]
    idx = {d: i for i, d in enumerate(dates)}
    c = {}
    for r in rows:
        if r["date"] in idx:
            c.setdefault(r["code"], [None] * len(dates))[idx[r["date"]]] = float(r["close"])
    return {"from": CLOSES_FROM, "dates": dates, "c": c,
            "note": "證交所每日收盤行情（上市全部證券，不含權證）；c[代號][i] 是 dates[i] 的收盤價，沒成交為 null"}


def main():
    out_path = sys.argv[1] if len(sys.argv) > 1 else "/tmp/tw_dashboard.json"
    out = {"regime": j("tw-models/latest/regime_tw.json"), "paper": j("tw-models/paper/latest.json"),
           "swing": j("tw-models/latest/swing.json"), "long": j("tw-models/latest/long.json"),
           "core": j("tw-models/latest/core_satellite.json"),
           "nav": list(csv.DictReader(open(os.path.join(ROOT, "tw-models/paper/nav.csv"), encoding="utf-8")))}
    for key, rel in (("screen", "tw-models/latest/old_screen.json"), ("after_market", "tw-models/latest/after_market.json"),
                     ("stock_analysis", "tw-models/latest/stock_analysis.json"), ("stock_news", "news/tw_stocks.json"),
                     ("us_regime", "regime/regime.json")):
        if os.path.exists(os.path.join(ROOT, rel)):
            out[key] = j(rel)
    # convenience: each analysed stock also carries its own 7-day headlines
    if "stock_analysis" in out and "stock_news" in out:
        for c, x in out["stock_analysis"].get("stocks", {}).items():
            x["news"] = out["stock_news"].get("by_code", {}).get(c, [])
    out["closes"] = closes()
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, separators=(",", ":"))
    print("dashboard file", out_path, os.path.getsize(out_path), "bytes;", len(out["closes"]["dates"]), "close dates,", len(out["closes"]["c"]), "codes")


if __name__ == "__main__":
    main()
