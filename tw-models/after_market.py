"""Daily after-market chip summary (public TWSE data): institutional flows, margin balance, top net buys/sells.

Writes tw-models/latest/after_market.json. Usage: python3 tw-models/after_market.py [--dry-run]
All amounts are NTD; output shows 億元 (1e8) and 張 (1,000 shares). Facts only: no forecasts, not advice.
"""
import os, sys
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(1, os.path.join(os.path.dirname(HERE), "lib"))
import common as C
import twdata as T

FOOTER = "資料為證交所公開資訊整理（收盤後），只列事實數字，不構成投資建議。"
SOURCES = [{"name": "證交所 OpenAPI／三大法人買賣超（T86）、FinMind 市場層級資料", "url": "https://openapi.twse.com.tw/"}]
TOP_N = 10


def num(x):
    try:
        return float(x)
    except (TypeError, ValueError):
        return None


def series(name, field):
    rows = T.market(name)
    return [(d, num(rows[d].get(field))) for d in sorted(rows) if num(rows[d].get(field)) is not None]


def streak(values):
    """Consecutive days with the same sign at the end: (+n buying / -n selling)."""
    n, sign = 0, 0
    for v in reversed(values):
        s = 1 if v > 0 else -1 if v < 0 else 0
        if s == 0 or (sign and s != sign):
            break
        sign, n = s, n + 1
    return sign * n


def yi(v):
    return None if v is None else round(v / 1e8, 1)


def main():
    problems = []
    taiex = series("taiex", "close")
    if not taiex:
        C.write_json("tw-models/latest/after_market.json", {"date": None}, ["讀不到加權指數資料"], SOURCES)
        return
    d, close = taiex[-1]
    prev = taiex[-2][1] if len(taiex) > 1 else None

    # 1) market-wide institutional net buy (NTD)
    inst = T.market("inst_total")
    dates = [x for x in sorted(inst) if x <= d]
    def col(k):
        return [num(inst[x].get(k)) or 0 for x in dates]
    fo, tr, de = col("foreign"), col("trust"), col("dealer")
    flows = {}
    if dates and dates[-1] == d:
        for key, arr in (("foreign", fo), ("trust", tr), ("dealer", de)):
            flows[key] = {"today_yi": yi(arr[-1]), "sum5_yi": yi(sum(arr[-5:])), "sum20_yi": yi(sum(arr[-20:])), "streak_days": streak(arr)}
        flows["total"] = {"today_yi": yi(fo[-1] + tr[-1] + de[-1]), "sum5_yi": yi(sum(fo[-5:]) + sum(tr[-5:]) + sum(de[-5:])),
                          "sum20_yi": yi(sum(fo[-20:]) + sum(tr[-20:]) + sum(de[-20:]))}
    else:
        problems.append("三大法人買賣金額還沒有 %s 的資料" % d)

    # 2) margin balance (融資餘額, NTD)
    mg = [(x, v) for x, v in series("margin_total", "margin_balance") if x <= d]
    margin = {}
    if mg and mg[-1][0] == d:
        b = mg[-1][1]
        margin = {"balance_yi": yi(b), "change_yi": yi(b - mg[-2][1]) if len(mg) > 1 else None,
                  "change_pct": round((b / mg[-2][1] - 1) * 100, 2) if len(mg) > 1 else None,
                  "change20_pct": round((b / mg[-21][1] - 1) * 100, 2) if len(mg) > 20 else None,
                  "index_change20_pct": round((close / taiex[-21][1] - 1) * 100, 2) if len(taiex) > 20 else None}
    else:
        problems.append("融資餘額還沒有 %s 的資料（通常晚一點才公布）" % d)

    # 3) per-stock net buys/sells today (shares -> 張; amount ≈ shares x close)
    names = {r["code"]: r["name"] for r in T.universe()}
    rows = []
    for c in names:
        i = T.inst(c).get(d)
        if not i:
            continue
        s = T.prices(c)
        k = s.idx.get(d)
        px = s.close[k] if k is not None else None
        f, t, dl = i
        rows.append({"code": c, "name": names[c], "close": px, "foreign_lots": round(f / 1000), "trust_lots": round(t / 1000),
                     "foreign_amt_yi": yi(f * px) if px else None, "trust_amt_yi": yi(t * px) if px else None})
    if not rows:
        problems.append("個股法人買賣超還沒有 %s 的資料" % d)

    def top(key, rev):
        r = [x for x in rows if x[key] is not None]
        r.sort(key=lambda x: x[key], reverse=rev)
        out = [x for x in r if (x[key] > 0 if rev else x[key] < 0)][:TOP_N]
        return [{"rank": n + 1, "code": x["code"], "name": x["name"], "close": x["close"],
                 "lots": x[key.replace("_amt_yi", "_lots")], "amt_yi": x[key]} for n, x in enumerate(out)]

    C.write_json("tw-models/latest/after_market.json", {
        "date": d,
        "taiex": {"close": close, "change_pct": round((close / prev - 1) * 100, 2) if prev else None},
        "institutional": flows,
        "margin": margin,
        "top": {"foreign_buy": top("foreign_amt_yi", True), "foreign_sell": top("foreign_amt_yi", False),
                "trust_buy": top("trust_amt_yi", True), "trust_sell": top("trust_amt_yi", False)},
        "notes": ["金額單位：億元；個股以張（1,000 股）計，金額 ≈ 買賣超股數 × 收盤價",
                  "外資含外資自營商；連續天數正數是連續買超、負數是連續賣超",
                  "streak_days 只看最近一段同方向的交易日"],
        "footer": FOOTER}, problems, SOURCES)
    print("after_market", d, "problems:", problems)


if __name__ == "__main__":
    main()
