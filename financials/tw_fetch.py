"""Taiwan quarterly financial statements for the financials watchlist -> financials/tw/<code>.json.

Format (same as the CoreWeave chart page): {"rows": [one row per quarter, oldest first], "meta": [...]}.
Source: FinMind (MOPS filings): income statement (single quarter), balance sheet, cash flow statement
(year-to-date, converted to single quarters here), monthly revenue. Units: million NTD (EPS in NTD).
Missing values are null, never 0.

Usage: python3 financials/tw_fetch.py              -> every code in financials/watchlist.json "tw"
       python3 financials/tw_fetch.py 2603 2002    -> only these codes (ad-hoc; the watchlist is not changed)
env FINMIND_TOKEN (Bearer)
"""
import datetime, json, os, sys, time, urllib.parse, urllib.request
HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
API = "https://api.finmindtrade.com/api/v4/data"
YEARS_BACK = 5          # one extra year so every published quarter has a YoY figure
KEEP_QUARTERS = 16     # rows written (at least MIN_QUARTERS)
MIN_QUARTERS = 12
M = 1e6                 # million NTD


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
    raise RuntimeError("%s：%s" % (dataset, err))


def by_date(rows):
    out = {}
    for r in rows:
        out.setdefault(r["date"], {})[r["type"]] = r["value"]
    return out


def prev_quarter_end(d):
    y, m = int(d[:4]), int(d[5:7])
    if m == 3:
        return None  # Q1: year-to-date is already single quarter
    pm = m - 3
    return "%04d-%02d-%s" % (y, pm, "30" if pm in (6, 9) else "31")


def single_quarter(ytd, d, key):
    """Year-to-date cash-flow item -> single quarter (Q1 as is, others minus the previous quarter-end)."""
    cur = (ytd.get(d) or {}).get(key)
    if cur is None:
        return None
    p = prev_quarter_end(d)
    if p is None:
        return cur
    prev = (ytd.get(p) or {}).get(key)
    return None if prev is None else cur - prev


def mil(x, n=1):
    return None if x is None else round(x / M, n)


def pct(a, b, n=1):
    return None if a is None or b in (None, 0) else round(a / b * 100, n)


def growth(a, b, n=1):
    return None if a is None or b in (None, 0) else round((a / b - 1) * 100, n)


def one(code):
    problems = []
    start = "%d-01-01" % (datetime.date.today().year - YEARS_BACK)
    inc = by_date(fetch("TaiwanStockFinancialStatements", code, start))
    bal = by_date(fetch("TaiwanStockBalanceSheet", code, start))
    cf = by_date(fetch("TaiwanStockCashFlowsStatement", code, start))
    revm = fetch("TaiwanStockMonthRevenue", code, "%d-01-01" % (datetime.date.today().year - YEARS_BACK - 1))
    monthly = {(x["revenue_year"], x["revenue_month"]): x["revenue"] for x in revm}
    rows = []
    for d in sorted(inc):
        i, b = inc[d], bal.get(d, {})
        y, q = int(d[:4]), (int(d[5:7]) - 1) // 3 + 1
        g = lambda dct, k: dct.get(k)
        debt_parts = [b.get(k) for k in ("ShortTermBorrowings", "ShortTermNotesAndBillsPayable", "LongtermLiabilitiesCurrentPortion",
                                         "LongtermBorrowings", "BondsPayable")]
        debt = sum(v for v in debt_parts if v is not None) if any(v is not None for v in debt_parts) else None
        ocf = single_quarter(cf, d, "CashFlowsFromOperatingActivities")
        if ocf is None:
            ocf = single_quarter(cf, d, "NetCashInflowFromOperatingActivities")
        ppe_buy = single_quarter(cf, d, "PropertyAndPlantAndEquipment")
        dep, amo = single_quarter(cf, d, "Depreciation"), single_quarter(cf, d, "AmortizationExpense")
        da = None if dep is None and amo is None else (dep or 0) + (amo or 0)
        recv = [b.get("AccountsReceivableNet"), b.get("AccountsReceivableDuefromRelatedPartiesNet")]
        months = [monthly.get((y, mo)) for mo in range(3 * q - 2, 3 * q + 1)]
        rows.append({
            "quarter": "%02dQ%d" % (y % 100, q), "period_end": d, "fiscal_label": "FY%02dQ%d" % (y % 100, q),
            "revenue": mil(g(i, "Revenue")), "gross": mil(g(i, "GrossProfit")), "cogs": mil(g(i, "CostOfGoodsSold")),
            "op_income": mil(g(i, "OperatingIncome")), "interest": mil(single_quarter(cf, d, "InterestExpense")),
            "net_income": mil(g(i, "IncomeAfterTaxes")), "eps_diluted": None, "eps_basic": g(i, "EPS"),
            "ocf": mil(ocf), "capex": mil(-ppe_buy) if ppe_buy is not None else None, "da": mil(da),
            "debt": mil(debt), "cash": mil(b.get("CashAndCashEquivalents")), "equity": mil(b.get("Equity")),
            "assets": mil(b.get("TotalAssets")), "total_liabilities": mil(b.get("Liabilities")),
            "ppe": mil(b.get("PropertyPlantAndEquipment")), "op_lease": None, "backlog": None,
            "inventory": mil(b.get("Inventories")),
            "receivables": mil(sum(v for v in recv if v is not None)) if any(v is not None for v in recv) else None,
            "monthly_revenue": [mil(v) for v in months],
        })
    for n, r in enumerate(rows):
        r["fcf"] = None if r["ocf"] is None or r["capex"] is None else round(r["ocf"] - r["capex"], 1)
        r["gross_margin_pct"] = pct(r["gross"], r["revenue"])
        r["op_margin_pct"] = pct(r["op_income"], r["revenue"])
        r["net_margin_pct"] = pct(r["net_income"], r["revenue"])
        r["revenue_yoy_pct"] = growth(r["revenue"], rows[n - 4]["revenue"]) if n >= 4 else None
        r["revenue_qoq_pct"] = growth(r["revenue"], rows[n - 1]["revenue"]) if n >= 1 else None
        r["debt_to_equity"] = round(r["debt"] / r["equity"], 2) if r["debt"] is not None and r["equity"] and r["equity"] > 0 else None
        r["interest_to_op_income"] = (round(r["interest"] / r["op_income"], 3)
                                      if r["interest"] is not None and r["op_income"] and r["op_income"] > 0 else None)
        r["inventory_days"] = round(r["inventory"] / r["cogs"] * 91, 1) if r["inventory"] is not None and r["cogs"] else None
    rows = rows[-KEEP_QUARTERS:]
    for r in rows:
        for k, v in r.items():
            if v is None and k not in ("eps_diluted", "op_lease", "backlog"):
                problems.append("%s %s 查不到 %s" % (code, r["quarter"], k))
    if len(rows) < MIN_QUARTERS:
        problems.append("%s 只有 %d 季資料（目標至少 %d 季）" % (code, len(rows), MIN_QUARTERS))
    return rows, problems


def write(code, rows, problems):
    src = open(os.path.abspath(__file__), encoding="utf-8").read()
    out = {"rows": rows, "meta": [
        {"label": os.path.basename(__file__), "value": src, "type": "code", "lang": "python"},
        {"label": "資料來源", "value": "FinMind（公開資訊觀測站申報的財報：綜合損益表、資產負債表、現金流量表、月營收）https://api.finmindtrade.com/api/v4/data"},
        {"label": "注意", "value": "單位百萬新台幣（EPS 為元）。損益表是單季數字；現金流量表是年初累計，已換算成單季（Q1 原值，其他季減前一季）。"
                                   "Q4 損益由 FinMind 提供的單季數字。interest 取自現金流量表調整項的利息費用（損益表未單獨列示）。"
                                   "debt = 短期借款＋短期票券＋一年內到期長期負債＋長期借款＋應付公司債，為帳面值。"
                                   "eps_diluted 留空（來源只有基本每股盈餘，見 eps_basic）；op_lease、backlog 來源沒有，留空。"
                                   "公司重編財報時以最新申報數字為準。"},
        {"label": "problems", "value": "；".join(problems) if problems else "無"},
        {"label": "更新時間", "value": datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")},
    ]}
    os.makedirs(os.path.join(HERE, "tw"), exist_ok=True)
    with open(os.path.join(HERE, "tw", code + ".json"), "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=1)


def main():
    codes = sys.argv[1:] or json.load(open(os.path.join(HERE, "watchlist.json"), encoding="utf-8"))["tw"]
    for c in codes:
        c = c.strip()
        if not c.isalnum():
            print("略過不合法的代號：", c)
            continue
        try:
            rows, problems = one(c)
        except Exception as e:
            rows, problems = [], ["%s 抓取失敗：%s" % (c, e)]
        if rows:
            write(c, rows, problems)
        print(c, len(rows), "quarters;", len(problems), "problems", problems[:3])


if __name__ == "__main__":
    main()
