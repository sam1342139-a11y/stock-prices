"""Taiwan quarterly financials + monthly revenue for the watchlist: earnings/tw_financials.json.

Source: FinMind (MOPS filings). Income statement is single-quarter; cash flow is year-to-date and is
converted to single quarters here. Inventory days = inventory / quarter COGS x days in quarter (計算值).
Usage: python3 earnings/tw_financials.py      env FINMIND_TOKEN (Bearer)
"""
import calendar, datetime, json, os, sys, time, urllib.parse, urllib.request
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "lib"))
import common as C

API = "https://api.finmindtrade.com/api/v4/data"
QUARTERS = 8
SOURCES = [{"name": "FinMind（公開資訊觀測站財報：綜合損益表、資產負債表、現金流量表、月營收）", "url": API},
           {"name": "公開資訊觀測站", "url": "https://mops.twse.com.tw/"}]


def fetch(dataset, code, start):
    q = urllib.parse.urlencode({"dataset": dataset, "data_id": code, "start_date": start})
    req = urllib.request.Request(API + "?" + q)
    tok = os.environ.get("FINMIND_TOKEN", "").strip()
    if tok:
        req.add_header("Authorization", "Bearer " + tok)
    for i in range(3):
        try:
            d = json.loads(urllib.request.urlopen(req, timeout=60).read())
            if d.get("status") == 200:
                return d.get("data", [])
            raise RuntimeError(d.get("msg"))
        except Exception as e:
            err = e
            time.sleep(5 * (i + 1))
    raise RuntimeError("%s %s: %s" % (dataset, code, err))


def by_date(rows, *types):
    out = {}
    for r in rows:
        if r["type"] in types:
            out.setdefault(r["date"], {})[r["type"]] = r["value"]
    return out


def qlabel(d):
    y, m = int(d[:4]), int(d[5:7])
    return "%dQ%d" % (y, (m - 1) // 3 + 1)


def qdays(d):
    y, m = int(d[:4]), int(d[5:7])
    return sum(calendar.monthrange(y, mm)[1] for mm in range(m - 2, m + 1))


def pct(a, b):
    return None if a is None or not b else round((a / b - 1) * 100, 2)


def r2(x, n=2):
    return None if x is None else round(x, n)


def one(code, problems):
    start = "%d-01-01" % (datetime.date.today().year - QUARTERS // 4 - 2)
    inc = by_date(fetch("TaiwanStockFinancialStatements", code, start), "Revenue", "GrossProfit", "OperatingIncome", "EPS", "CostOfGoodsSold")
    bal = by_date(fetch("TaiwanStockBalanceSheet", code, start), "Inventories")
    cf = by_date(fetch("TaiwanStockCashFlowsStatement", code, start), "CashFlowsFromOperatingActivities", "NetCashInflowFromOperatingActivities")
    rev = fetch("TaiwanStockMonthRevenue", code, "%d-01-01" % (datetime.date.today().year - 2))
    dates = sorted(inc)
    rows = []
    for d in dates:
        i, b = inc[d], bal.get(d, {})
        revq, cogs, inv = i.get("Revenue"), i.get("CostOfGoodsSold"), b.get("Inventories")
        ytd = (cf.get(d) or {}).get("CashFlowsFromOperatingActivities", (cf.get(d) or {}).get("NetCashInflowFromOperatingActivities"))
        ocf = None
        if ytd is not None:
            if d[5:7] == "03":
                ocf = ytd
            else:
                pm = "%02d" % (int(d[5:7]) - 3)
                prev_d = "%s-%s-%s" % (d[:4], pm, "30" if pm in ("06", "09") else "31")
                p = cf.get(prev_d) or {}
                pv = p.get("CashFlowsFromOperatingActivities", p.get("NetCashInflowFromOperatingActivities"))
                ocf = None if pv is None else ytd - pv
        rows.append({"period": qlabel(d), "end": d, "revenue": revq,
                     "gross_margin_pct": r2(i.get("GrossProfit") / revq * 100) if revq and i.get("GrossProfit") is not None else None,
                     "operating_margin_pct": r2(i.get("OperatingIncome") / revq * 100) if revq and i.get("OperatingIncome") is not None else None,
                     "eps": i.get("EPS"), "inventory": inv, "cogs": cogs, "operating_cash_flow": ocf,
                     "inventory_days": r2(inv / cogs * qdays(d), 1) if inv is not None and cogs else None})
    for n, r in enumerate(rows):
        p1 = rows[n - 1] if n >= 1 else None
        p4 = rows[n - 4] if n >= 4 else None
        r["inventory_qoq_pct"] = pct(r["inventory"], p1 and p1["inventory"])
        r["inventory_yoy_pct"] = pct(r["inventory"], p4 and p4["inventory"])
        r["inventory_days_qoq_pct"] = pct(r["inventory_days"], p1 and p1["inventory_days"])
        for k in ("revenue", "eps", "inventory", "cogs", "operating_cash_flow"):
            if r[k] is None:
                problems.append("%s %s 查不到 %s" % (code, r["period"], k))
    rows = rows[-QUARTERS:]
    m = {(x["revenue_year"], x["revenue_month"]): x["revenue"] for x in rev}
    months = []
    for (y, mo) in sorted(m)[-13:]:
        months.append({"month": "%d-%02d" % (y, mo), "revenue": m[(y, mo)], "yoy_pct": pct(m[(y, mo)], m.get((y - 1, mo)))})
    return {"code": code, "quarters": rows, "monthly_revenue": months[-12:]}


def main():
    wl = json.load(open(os.path.join(ROOT, "earnings/watchlist.json"), encoding="utf-8"))
    problems, out = [], {}
    for code in wl["tw"]:
        try:
            out[code] = one(code, problems)
        except Exception as e:
            problems.append("%s 財報抓取失敗：%s" % (code, e))
    C.write_json("earnings/tw_financials.json", {
        "units": {"revenue": "新台幣元", "inventory": "新台幣元", "cogs": "新台幣元（營業成本）", "operating_cash_flow": "新台幣元（單季，由年初累計數相減）"},
        "notes": ["inventory_days（存貨週轉天數）= 存貨 ÷ 當季營業成本 × 當季天數，為計算值，公司若有揭露以公司為準",
                  "inventory_qoq_pct／inventory_yoy_pct：存貨季增／年增；inventory_days_qoq_pct：週轉天數季增",
                  "財報季（Q1 5/15、Q2 8/14、Q3 11/14、Q4 隔年 3/31 前公告），公告前最新一季不會出現",
                  "monthly_revenue：單月營收與年增率（最近 12 個月）"],
        "companies": out}, problems, SOURCES)
    print("tw_financials", len(out), "companies; problems:", problems)


if __name__ == "__main__":
    main()
