"""US quarterly financial statements for the financials watchlist -> financials/us/<TICKER>.json.

Format (same as the CoreWeave chart page and financials/tw/): {"rows": [one row per quarter, oldest first], "meta": [...]}.
Source: SEC EDGAR XBRL companyfacts (data.sec.gov), i.e. the numbers companies tag in their 10-Q / 10-K (and S-1 for
recent IPOs). Units: million USD (EPS in USD). Missing values are null, never 0, never estimated.

Single quarters:
  - a reported 3-month figure is used as is;
  - otherwise year-to-date differences: Q2 = 6M - 3M, Q3 = 9M - 6M (cash-flow statements are year-to-date),
    Q4 = full year - 9M. Every field obtained by subtraction is listed in the row's "derived_fields".
  - EPS is never subtracted (share counts differ between periods): a quarter with no reported EPS gets null.
quarter      = calendar quarter of the period (period_end minus 45 days, so a quarter ending late January is the
               previous calendar Q4), e.g. "26Q3".
fiscal_label = the company's own fiscal year / quarter, e.g. NVIDIA's quarter ending 2026-10-26 is "FY27Q3".

Usage: python3 financials/us_fetch.py              -> every ticker in financials/watchlist.json "us"
       python3 financials/us_fetch.py NVDA CRWV    -> only these tickers (ad-hoc; the watchlist is not changed)
       add --debug to print which XBRL tag was used for each field
SEC asks automated clients to identify themselves (name + e-mail): the User-Agent uses the bot's generic
GitHub no-reply address and this project's public page, no personal data.
"""
import datetime, json, os, sys, time, urllib.request
HERE = os.path.dirname(os.path.abspath(__file__))
# SEC rejects a User-Agent without an e-mail address; this is the generic GitHub no-reply address the data bot
# already commits with (no personal data), plus the project page.
UA = "stock-prices-data-bot bot@users.noreply.github.com https://github.com/sam1342139-a11y/stock-prices"
TICKERS_URL = "https://www.sec.gov/files/company_tickers.json"
FACTS_URL = "https://data.sec.gov/api/xbrl/companyfacts/CIK%010d.json"
KEEP_QUARTERS = 16
MIN_QUARTERS = 12
M = 1e6
FORMS = ("10-Q", "10-K", "S-1", "424B")   # prefixes; amendments (10-K/A ...) included
DEBUG = False

# field -> candidate us-gaap tags, first one with data for that quarter wins
DURATION = {
    "revenue": ["Revenues", "RevenueFromContractWithCustomerExcludingAssessedTax", "SalesRevenueNet",
                "RevenueFromContractWithCustomerIncludingAssessedTax"],
    "cogs": ["CostOfRevenue", "CostOfGoodsAndServicesSold", "CostOfGoodsSold"],
    "gross": ["GrossProfit"],
    "op_income": ["OperatingIncomeLoss"],
    "interest": ["InterestExpense", "InterestExpenseNonoperating", "InterestExpenseDebt", "InterestAndDebtExpense"],
    "net_income": ["NetIncomeLoss", "ProfitLoss"],
    "ocf": ["NetCashProvidedByUsedInOperatingActivities",
            "NetCashProvidedByUsedInOperatingActivitiesContinuingOperations"],
    "capex": ["PaymentsToAcquirePropertyPlantAndEquipment", "PaymentsToAcquireProductiveAssets"],
    "da": ["DepreciationDepletionAndAmortization", "DepreciationAmortizationAndAccretionNet",
           "DepreciationAndAmortization", "Depreciation"],
}
EPS = {"eps_diluted": ["EarningsPerShareDiluted"], "eps_basic": ["EarningsPerShareBasic"]}
INSTANT = {
    "cash": ["CashAndCashEquivalentsAtCarryingValue",
             "CashCashEquivalentsRestrictedCashAndRestrictedCashEquivalents"],
    "equity": ["StockholdersEquity", "StockholdersEquityIncludingPortionAttributableToNoncontrollingInterest"],
    "assets": ["Assets"],
    "total_liabilities": ["Liabilities"],
    "ppe": ["PropertyPlantAndEquipmentNet",
            "PropertyPlantAndEquipmentAndFinanceLeaseRightOfUseAssetAfterAccumulatedDepreciationAndAmortization"],
    "op_lease": ["OperatingLeaseLiability"],
    "backlog": ["RevenueRemainingPerformanceObligation"],
    "inventory": ["InventoryNet"],
    "receivables": ["AccountsReceivableNetCurrent", "AccountsReceivableNet"],
}
# debt = carrying amount of borrowings; first complete recipe wins
DEBT_RECIPES = [
    ["LongTermDebt", "ShortTermBorrowings?", "CommercialPaper?"],
    ["LongTermDebtNoncurrent", "LongTermDebtCurrent", "ShortTermBorrowings?", "CommercialPaper?"],
    ["LongTermDebtNoncurrent", "DebtCurrent"],
    ["LongTermDebtNoncurrent", "ShortTermBorrowings?", "CommercialPaper?"],
    ["DebtCurrent"],
]
OPLEASE_PARTS = ["OperatingLeaseLiabilityCurrent", "OperatingLeaseLiabilityNoncurrent"]


def get(url):
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept-Encoding": "identity"})
    err = None
    for i in range(3):
        try:
            return json.loads(urllib.request.urlopen(req, timeout=60).read())
        except Exception as e:
            err = e
            time.sleep(3 * (i + 1))
    raise RuntimeError("%s：%s" % (url, err))


def d(s):
    return datetime.date.fromisoformat(s)


def days(a, b):
    return (d(b) - d(a)).days


class Facts:
    """us-gaap facts of one company, deduplicated by period (latest filing wins = restated numbers)."""

    def __init__(self, raw):
        self.gaap = raw.get("facts", {}).get("us-gaap", {})
        self.dur, self.inst, self._fy = {}, {}, {}
        for tag, body in self.gaap.items():
            for unit, items in body.get("units", {}).items():
                if unit not in ("USD", "USD/shares"):
                    continue
                for x in items:
                    if not str(x.get("form", "")).startswith(FORMS) or x.get("val") is None:
                        continue
                    if "start" in x:
                        key, store = (x["start"], x["end"]), self.dur.setdefault(tag, {})
                    else:
                        key, store = x["end"], self.inst.setdefault(tag, {})
                    old = store.get(key)
                    if old is None or x.get("filed", "") >= old.get("filed", ""):
                        store[key] = x

    def tags_like(self, *words):
        return sorted(t for t in self.gaap if any(w.lower() in t.lower() for w in words))

    def instant(self, tags, end):
        for t in tags:
            x = self.inst.get(t, {}).get(end)
            if x is not None:
                return x["val"], t
        return None, None

    def quarter(self, tags, qs, qe, allow_diff=True):
        """Single-quarter value for the quarter (qs .. qe). Returns (value, tag, derived)."""
        for t in tags:
            facts = self.dur.get(t, {})
            for (s, e), x in facts.items():
                if e == qe and 80 <= days(s, e) <= 100:
                    return x["val"], t, False
        if not allow_diff:
            return None, None, False
        prev_end = (d(qs) - datetime.timedelta(days=1)).isoformat()
        for t in tags:
            facts = self.dur.get(t, {})
            # longer period ending at qe minus the same-start period ending the day before qs
            for (s, e), x in sorted(facts.items(), key=lambda kv: kv[0][0]):
                if e != qe or days(s, e) <= 100:
                    continue
                y = facts.get((s, prev_end))
                if y is not None:
                    return x["val"] - y["val"], t, True
        return None, None, False


def quarter_list(f):
    """[(start, end)] of every fiscal quarter seen in the revenue / net income facts."""
    tags = DURATION["revenue"] + DURATION["net_income"]
    ends, starts, annual = {}, {}, set()
    for t in tags:
        for (s, e) in f.dur.get(t, {}):
            n = days(s, e)
            if 80 <= n <= 100:
                ends[e] = s
            elif 350 <= n <= 380:
                annual.add((s, e))
            elif n > 100:
                starts.setdefault(e, set()).add(s)
    q = dict(ends)
    for s, e in annual:          # Q4: from the day after the 9-month period ending inside this fiscal year
        if e in q:
            continue
        nine = [e9 for e9, ss in starts.items() if s in ss and 250 <= days(s, e9) <= 290]
        if nine:
            q[e] = (d(max(nine)) + datetime.timedelta(days=1)).isoformat()
    return sorted((s, e) for e, s in q.items()), sorted(annual, key=lambda p: p[1])


def fiscal_years(f, annual):
    """{fiscal year end date: FY number}.

    "fy" on a fact is the fiscal year of the filing it came from (comparatives carry it too), so only the newest
    annual period of the newest 10-K is a safe anchor; earlier fiscal years are counted back from it."""
    anchor = None
    for t in DURATION["revenue"] + DURATION["net_income"]:
        for (s, e), x in f.dur.get(t, {}).items():
            if (s, e) in annual and str(x.get("form", "")).startswith("10-K") and x.get("fy"):
                if anchor is None or e > anchor[0]:
                    anchor = (e, int(x["fy"]))
    ends = sorted({e for _, e in annual})
    if anchor is None:           # no 10-K yet (fresh IPO): name fiscal years by the calendar year they end in
        return {e: d(e).year for e in ends}
    return {e: anchor[1] - int(round(days(e, anchor[0]) / 365.25)) for e in ends}


def fiscal_label(qe, fy_ends):
    """FYyyQn for the quarter ending qe."""
    known = sorted(fy_ends)
    if not known:
        return None
    nxt = [e for e in known if e >= qe and days(qe, e) < 370]
    if nxt:
        fe, fy = nxt[0], fy_ends[nxt[0]]
    else:                        # quarters after the last fiscal-year end: next fiscal year, same pattern
        last = known[-1]
        k = (days(last, qe) - 1) // 365 + 1
        fe, fy = (d(last) + datetime.timedelta(days=365 * k)).isoformat(), fy_ends[last] + k
    qn = 4 - int(round(days(qe, fe) / 91.3))
    if not 1 <= qn <= 4:
        return None
    return "FY%02dQ%d" % (fy % 100, qn)


def cal_quarter(qe):
    m = d(qe) - datetime.timedelta(days=45)
    return "%02dQ%d" % (m.year % 100, (m.month - 1) // 3 + 1)


def mil(x, n=1):
    return None if x is None else round(x / M, n)


def pct(a, b, n=1):
    return None if a is None or b in (None, 0) else round(a / b * 100, n)


def growth(a, b, n=1):
    return None if a is None or b in (None, 0) or b < 0 else round((a / b - 1) * 100, n)


def debt_at(f, end):
    for recipe in DEBT_RECIPES:
        vals, used, ok = [], [], True
        for part in recipe:
            opt = part.endswith("?")
            tag = part.rstrip("?")
            v, _ = f.instant([tag], end)
            if v is None and not opt:
                ok = False
                break
            if v is not None:
                vals.append(v)
                used.append(tag)
        if ok and vals:
            return sum(vals), "+".join(used)
    return None, None


def one(ticker, cik):
    problems, used = [], {}
    f = Facts(get(FACTS_URL % cik))
    quarters, annual = quarter_list(f)
    fy_ends = fiscal_years(f, annual)
    rows = []
    for qs, qe in quarters:
        r = {"quarter": cal_quarter(qe), "period_end": qe, "fiscal_label": fiscal_label(qe, fy_ends)}
        derived = []
        vals = {}
        for k, tags in DURATION.items():
            v, t, der = f.quarter(tags, qs, qe)
            vals[k] = v
            if t:
                used.setdefault(k, set()).add(t)
            if der:
                derived.append(k)
        if vals["gross"] is None and vals["revenue"] is not None and vals["cogs"] is not None:
            vals["gross"] = vals["revenue"] - vals["cogs"]
            derived.append("gross")
        if vals["cogs"] is None and vals["revenue"] is not None and vals["gross"] is not None:
            vals["cogs"] = vals["revenue"] - vals["gross"]
            derived.append("cogs")
        for k in ("revenue", "gross", "cogs", "op_income", "interest", "net_income"):
            r[k] = mil(vals[k])
        for k, tags in EPS.items():
            v, t, _ = f.quarter(tags, qs, qe, allow_diff=False)
            r[k] = v
            if t:
                used.setdefault(k, set()).add(t)
        r["ocf"], r["capex"], r["da"] = mil(vals["ocf"]), mil(vals["capex"]), mil(vals["da"])
        debt, dt = debt_at(f, qe)
        r["debt"] = mil(debt)
        if dt:
            used.setdefault("debt", set()).add(dt)
        inst = {}
        for k, tags in INSTANT.items():
            inst[k], t = f.instant(tags, qe)
            if t:
                used.setdefault(k, set()).add(t)
        if inst["op_lease"] is None:
            parts = [f.instant([t], qe)[0] for t in OPLEASE_PARTS]
            if all(p is not None for p in parts):
                inst["op_lease"] = sum(parts)
                used.setdefault("op_lease", set()).add("+".join(OPLEASE_PARTS))
        if inst["total_liabilities"] is None:
            le, _ = f.instant(["LiabilitiesAndStockholdersEquity"], qe)
            eq, _ = f.instant(["StockholdersEquityIncludingPortionAttributableToNoncontrollingInterest",
                               "StockholdersEquity"], qe)
            if le is not None and eq is not None:
                inst["total_liabilities"] = le - eq
                derived.append("total_liabilities")
        for k in ("cash", "equity", "assets", "total_liabilities", "ppe", "op_lease", "backlog", "inventory", "receivables"):
            r[k] = mil(inst[k])
        r["derived_fields"] = derived
        rows.append(r)
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
    # a gap in the quarter list (missing filing) would make YoY/QoQ compare the wrong quarters
    for n in range(1, len(rows)):
        if days(rows[n - 1]["period_end"], rows[n]["period_end"]) > 100:
            problems.append("%s %s 之前缺一季（%s 到 %s），季增／年增可能不準" % (
                ticker, rows[n]["quarter"], rows[n - 1]["period_end"], rows[n]["period_end"]))
    rows = rows[-KEEP_QUARTERS:]
    missing = {}
    for r in rows:
        for k, v in r.items():
            if v is None and not k.endswith(("_pct", "_ratio")) and k not in (
                    "fcf", "debt_to_equity", "interest_to_op_income", "inventory_days"):
                missing.setdefault(k, []).append(r["quarter"])
    for k, qs in missing.items():
        problems.append("%s 查不到 %s：%s" % (ticker, k, "、".join(qs)))
    if len(rows) < MIN_QUARTERS:
        problems.append("%s 只有 %d 季資料（目標至少 %d 季）" % (ticker, len(rows), MIN_QUARTERS))
    if DEBUG:
        print(ticker, "tags used:", {k: sorted(v) for k, v in used.items()})
        print(ticker, "debt-like tags:", f.tags_like("Debt", "Borrowing", "Notes", "Lease")[:80])
        print(ticker, "D&A / interest-like tags:", f.tags_like("Depreciation", "Amortization", "Interest")[:60])
    return rows, problems, {k: sorted(v) for k, v in used.items()}


def write(ticker, cik, rows, problems, used):
    src = open(os.path.abspath(__file__), encoding="utf-8").read()
    tag_note = "；".join("%s=%s" % (k, "／".join(v)) for k, v in sorted(used.items()))
    out = {"rows": rows, "meta": [
        {"label": os.path.basename(__file__), "value": src, "type": "code", "lang": "python"},
        {"label": "資料來源", "value": "美國證管會 SEC EDGAR 的 XBRL 財報資料（公司申報的 10-Q、10-K；新上市公司含 S-1）"
                                     "https://data.sec.gov/api/xbrl/companyfacts/CIK%010d.json" % cik},
        {"label": "注意", "value": "單位百萬美元（EPS 為美元）。quarter 是日曆季（季底日往前 45 天所在的季），"
                                   "fiscal_label 是公司自己的會計年度（例如輝達的會計年度在 1 月底結束）。"
                                   "財報有單季數字就直接用；沒有的用年初累計相減：Q2＝半年−Q1、Q3＝九個月−半年、"
                                   "Q4＝全年−前三季（現金流量表本來就是年初累計）。用相減算出的欄位列在該季的 derived_fields。"
                                   "EPS 不做相減（各期股數不同），財報沒有單季 EPS 的季別留空（Q4 通常如此）。"
                                   "debt 是借款的帳面值（長短期借款＋商業本票），不含租賃負債；op_lease 是營業租賃負債；"
                                   "backlog 是剩餘履約義務（RPO）。公司重編或拆股後以最新申報的數字為準。"
                                   "本檔使用的 XBRL 欄位：" + tag_note},
        {"label": "problems", "value": "；".join(problems) if problems else "無"},
        {"label": "更新時間", "value": datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")},
    ]}
    os.makedirs(os.path.join(HERE, "us"), exist_ok=True)
    with open(os.path.join(HERE, "us", ticker + ".json"), "w", encoding="utf-8") as fh:
        json.dump(out, fh, ensure_ascii=False, indent=1)


def main():
    global DEBUG
    args = [a for a in sys.argv[1:] if a != "--debug"]
    DEBUG = len(args) != len(sys.argv[1:])
    tickers = args or json.load(open(os.path.join(HERE, "watchlist.json"), encoding="utf-8"))["us"]
    if not tickers:
        print("no US tickers")
        return
    ciks = {v["ticker"].upper(): int(v["cik_str"]) for v in get(TICKERS_URL).values()}
    for t in tickers:
        t = t.strip().upper()
        if not t.replace(".", "").replace("-", "").isalnum():
            print("略過不合法的代號：", t)
            continue
        if t not in ciks:
            print(t, "SEC 查不到這個代號（可能不是在美國申報的公司）")
            continue
        try:
            rows, problems, used = one(t, ciks[t])
        except Exception as e:
            rows, problems, used = [], ["%s 抓取失敗：%s" % (t, e)], {}
        if rows:
            write(t, ciks[t], rows, problems, used)
        print(t, len(rows), "quarters;", len(problems), "problems", problems[:5])
        time.sleep(0.3)   # SEC fair-access limit is 10 requests/second


if __name__ == "__main__":
    main()
