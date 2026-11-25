"""Per-stock analysis data for the 33 large caps of the old screen + 0050: tw-models/latest/stock_analysis.json.

Public market data only (no holdings, no watch list). Daily, in the update-tw-models workflow after the screen.
Per code: last-year closes with 60/240-day moving averages, 52-week high/low and Fibonacci retracement levels,
monthly revenue (24 months, YoY), last 8 quarters EPS and gross/operating/net margins, foreign and trust
net buy/sell (20 trading days, lots), P/E with its 5-year percentile.
Sources: FinMind data already cached by the tw-models workflow; quarterly statements fetched from FinMind.
Usage: python3 tw-models/stock_analysis.py        env FINMIND_TOKEN
"""
import datetime, json, os, sys, time, urllib.parse, urllib.request
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(1, os.path.join(os.path.dirname(HERE), "lib"))
import common as C
import twdata as T

API = "https://api.finmindtrade.com/api/v4/data"
DAYS = 250            # about one year of trading days
FIB = [0, 0.236, 0.382, 0.5, 0.618, 0.786, 1]
SOURCES = [{"name": "FinMind（證交所／公開資訊觀測站資料：股價、本益比、法人、月營收、財報）", "url": API}]
FOOTER = "資料依公開資訊整理，只列事實數字與計算值，不構成投資建議。"


def r2(x, n=2):
    return None if x is None else round(x, n)


def finmind(dataset, code, start):
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


def quarters(code, problems):
    """Last 8 quarters: EPS and margins (single-quarter income statement)."""
    start = "%d-01-01" % (datetime.date.today().year - 3)
    try:
        rows = finmind("TaiwanStockFinancialStatements", code, start)
    except Exception as e:
        problems.append("%s 季報抓取失敗：%s" % (code, e))
        return []
    by = {}
    for r in rows:
        by.setdefault(r["date"], {})[r["type"]] = r["value"]
    out = []
    for d in sorted(by)[-8:]:
        x = by[d]
        rev = x.get("Revenue")
        m = lambda k: r2(x[k] / rev * 100) if rev and x.get(k) is not None else None
        out.append({"period": "%sQ%d" % (d[:4], (int(d[5:7]) - 1) // 3 + 1), "eps": x.get("EPS"),
                    "gross_margin_pct": m("GrossProfit"), "operating_margin_pct": m("OperatingIncome"),
                    "net_margin_pct": m("IncomeAfterTaxes")})
    return out


def one(code, d, problems):
    s = T.prices(code)
    k = s.idx.get(d)
    if k is None:
        problems.append("%s 沒有 %s 的股價" % (code, d))
        return None
    lo = max(0, k - DAYS + 1)
    dates, close = s.dates[lo:k + 1], s.close[lo:k + 1]
    adj = s.close_adj  # moving averages and 52-week range on adjusted closes (ex-dividend gaps removed)
    ma = lambda n, i: (sum(adj[i - n + 1:i + 1]) / n) * (s.close[i] / adj[i]) if i >= n - 1 else None
    ma60 = [r2(ma(60, i)) for i in range(lo, k + 1)]
    ma240 = [r2(ma(240, i)) for i in range(lo, k + 1)]
    w = range(max(0, k - 249), k + 1)
    hi_i = max(w, key=lambda i: s.high_adj[i]); lo_i = min(w, key=lambda i: s.low_adj[i])
    scale = s.close[k] / adj[k]
    hi, low = s.high_adj[hi_i] * scale, s.low_adj[lo_i] * scale
    fib = [{"ratio": f, "price": r2(hi - (hi - low) * f)} for f in FIB]
    pos = r2((hi - s.close[k]) / (hi - low) * 100, 1) if hi > low else None

    # P/E and its 5-year percentile (positive P/E only)
    per = T.per(code)
    pe = (per.get(d) or (None, None, None))
    five = (datetime.date.fromisoformat(d) - datetime.timedelta(days=5 * 365)).isoformat()
    hist = [v[0] for dd, v in per.items() if five <= dd <= d and v[0] and v[0] > 0]
    pe_pct = r2(sum(1 for v in hist if v <= pe[0]) / len(hist) * 100, 1) if pe[0] and pe[0] > 0 and hist else None

    # monthly revenue, 24 months, announced by d
    rev = [(ym, v) for ym, v, av in T.revenue(code) if av and av <= d and v]
    m = dict(rev)
    months = []
    for ym, v in rev[-24:]:
        prev = m.get("%04d-%s" % (int(ym[:4]) - 1, ym[5:]))
        months.append({"month": ym, "revenue": v, "yoy_pct": r2((v / prev - 1) * 100) if prev else None})

    # institutional net buy/sell, last 20 trading days, in lots (1,000 shares)
    ins = T.inst(code)
    inst = [{"date": dd, "foreign_lots": round(ins[dd][0] / 1000), "trust_lots": round(ins[dd][1] / 1000)}
            for dd in s.dates[max(0, k - 19):k + 1] if dd in ins]

    return {"code": code, "name": None, "date": d, "close": s.close[k],
            "chart": {"dates": dates, "close": close, "ma60": ma60, "ma240": ma240},
            "ma60": ma60[-1], "ma240": ma240[-1],
            "high_52w": r2(hi), "high_52w_date": s.dates[hi_i], "low_52w": r2(low), "low_52w_date": s.dates[lo_i],
            "fib_levels": fib, "fib_position_pct": pos,
            "pe": pe[0], "pe_5y_percentile": pe_pct, "dividend_yield_pct": pe[1], "pb": pe[2],
            "monthly_revenue": months, "quarters": [] if T.is_etf(code) else quarters(code, problems),
            "institutional_20d": inst,
            "foreign_20d_lots": sum(x["foreign_lots"] for x in inst), "trust_20d_lots": sum(x["trust_lots"] for x in inst)}


def main():
    cfg = T.config()
    codes = list(cfg["old_screen"]["universe"]) + ["0050"]
    d = T.calendar()[-1]
    names = {r["code"]: r["name"] for r in T.universe()}
    problems, out = [], {}
    for c in codes:
        try:
            x = one(c, d, problems)
        except Exception as e:
            problems.append("%s 計算失敗：%s" % (c, type(e).__name__))
            x = None
        if x:
            x["name"] = names.get(c)
            out[c] = x
    payload = {
        "date": d, "codes": codes, "stocks": out,
        "notes": ["範圍：舊篩選法的 33 檔大型股＋0050（固定公開名單，不含個人持股或觀察清單）",
                  "chart：近一年（約 250 個交易日）收盤價與 60／240 日均線；均線與 52 週高低用還原權息價計算後換回目前價位",
                  "fib_levels：以 52 週高低計算的黃金分割位置（ratio 0 = 52 週高點，1 = 52 週低點）；fib_position_pct：目前收盤從高點回落了高低差的幾 %",
                  "pe_5y_percentile：目前本益比在近 5 年每日本益比（只算正值）中的百分位，越高代表越貴",
                  "institutional_20d：外資、投信近 20 個交易日買賣超（張）；quarters：近 8 季 EPS 與毛利率、營益率、淨利率（%）",
                  "新聞標題在 build_dashboard.py 組檔時由 news/tw_stocks.json 併入（近 7 天，只有標題與連結）"],
        "footer": FOOTER}
    # compact JSON (the file is rewritten daily; keeps the repository small)
    data = {"generated_at_utc": C.utc_now().strftime("%Y-%m-%d %H:%M:%S"), "problems": problems, "sources": SOURCES}
    data.update(payload)
    with open(C.out_path("tw-models/latest/stock_analysis.json"), "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, separators=(",", ":"))
    print("stock_analysis", d, len(out), "codes; problems", problems[:5])


if __name__ == "__main__":
    main()
