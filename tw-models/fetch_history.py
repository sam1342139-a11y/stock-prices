"""Historical Taiwan market data for tw-models (2019-01-01 → today; prices/PER/market from 2014-01-01 as warm-up history).

Backfill source: FinMind API (token from env FINMIND_TOKEN, sent as Bearer header).
TWSE www endpoints block bulk access from cloud hosts, so history comes from FinMind;
the daily append (update_daily.py) uses TWSE OpenAPI.

Layout (tw-models/data/):
  universe.csv                       code,name,industry,market,delisted_date
  prices/<code>.csv.gz               date,open,high,low,close,volume,value,spread
  per/<code>.csv.gz                  date,pe,dy,pb
  inst/<code>.csv.gz                 date,foreign,trust,dealer        (net shares)
  revenue/<code>.csv.gz              ym,revenue,announced,available    (available = max(announced, 10th of next month))
  dividends/<code>.csv.gz            ex_date,kind,amount,before_price,reference_price
  market/taiex.csv                   date,open,high,low,close
  market/taiex_tri.csv               date,close                        (total return index)
  market/inst_total.csv              date,foreign,trust,dealer         (net buy amount, NTD)
  market/margin_total.csv            date,margin_balance               (NTD)
  meta/backfill_state.json           progress (resumable)

Usage:
  python3 tw-models/fetch_history.py [--dry-run] [--limit N] [--only prices,per,...] [--codes 2330,0050]
Rate limit: free token ≈ 600 req/hour → we pace at ~1 req / 6.2 s and stop at --budget-min.
"""
import argparse, csv, datetime, gzip, io, json, os, sys, time, urllib.parse
sys.path.insert(1, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "lib"))
import common as C

START = "2019-01-01"
WARMUP_START = "2014-01-01"  # extra history for 200-day MAs and 5-year percentiles (E)
API = "https://api.finmindtrade.com/api/v4/data"
PACE = 6.1
DATASETS = ["prices", "dividends", "per", "inst", "revenue"]


def data_dir():
    return os.path.dirname(C.out_path("tw-models/data/x"))


_last_call = [0.0]


def pace():
    """Keep request *starts* at least PACE seconds apart (~590/hour), counting response time."""
    wait = PACE - (time.time() - _last_call[0])
    if wait > 0:
        time.sleep(wait)
    _last_call[0] = time.time()


def fm(dataset, **params):
    pace()
    tok = os.environ.get("FINMIND_TOKEN", "").strip()
    if not tok:
        raise RuntimeError("FINMIND_TOKEN 未設定")
    params["dataset"] = dataset
    url = API + "?" + urllib.parse.urlencode(params)
    for attempt in range(6):
        try:
            d = C.http_json(url, {"Authorization": "Bearer " + tok})
        except RuntimeError as e:
            msg = str(e)
            if "402" in msg or "upper limit" in msg.lower():
                print("  rate limit reached, sleeping 10 min", flush=True)
                time.sleep(600)
                continue
            raise
        if d.get("status") == 200:
            return d.get("data") or []
        if d.get("status") in (402, 429):
            print("  rate limit reached, sleeping 10 min", flush=True)
            time.sleep(600)
            continue
        raise RuntimeError("FinMind %s: %s" % (d.get("status"), d.get("msg")))
    raise RuntimeError("FinMind rate limit retries exhausted")


def write_gz(path, header, rows):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".tmp"
    with gzip.open(tmp, "wt", encoding="utf-8", newline="") as f:
        w = csv.writer(f, lineterminator="\n")
        w.writerow(header)
        w.writerows(rows)
    os.replace(tmp, path)


def write_plain(path, header, rows):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="") as f:
        w = csv.writer(f, lineterminator="\n")
        w.writerow(header)
        w.writerows(rows)


def g(v):
    return "" if v is None else ("%g" % v if isinstance(v, float) else str(v))


# ---------- per-dataset fetchers (one request per code) ----------
def get_prices(code, end):
    rows = fm("TaiwanStockPrice", data_id=code, start_date=WARMUP_START, end_date=end)
    return ["date", "open", "high", "low", "close", "volume", "value", "spread"], [
        [r["date"], g(r["open"]), g(r["max"]), g(r["min"]), g(r["close"]), r["Trading_Volume"], r["Trading_money"], g(r["spread"])]
        for r in rows if r.get("close")]


def get_per(code, end):
    rows = fm("TaiwanStockPER", data_id=code, start_date=WARMUP_START, end_date=end)
    return ["date", "pe", "dy", "pb"], [[r["date"], g(r["PER"]), g(r["dividend_yield"]), g(r["PBR"])] for r in rows]


def get_inst(code, end):
    rows = fm("TaiwanStockInstitutionalInvestorsBuySell", data_id=code, start_date=START, end_date=end)
    agg = {}
    for r in rows:
        n = r["name"]
        key = "foreign" if n.startswith("Foreign") else ("trust" if n == "Investment_Trust" else ("dealer" if n.startswith("Dealer") else None))
        if key:
            agg.setdefault(r["date"], {"foreign": 0, "trust": 0, "dealer": 0})[key] += int(r["buy"]) - int(r["sell"])
    return ["date", "foreign", "trust", "dealer"], [[d, v["foreign"], v["trust"], v["dealer"]] for d, v in sorted(agg.items())]


def avail_10th(y, m):
    y2, m2 = (y + 1, 1) if m == 12 else (y, m + 1)
    return "%04d-%02d-10" % (y2, m2)


def get_revenue(code, end):
    rows = fm("TaiwanStockMonthRevenue", data_id=code, start_date="2017-12-01", end_date=end)
    out = []
    for r in rows:
        y, m = int(r["revenue_year"]), int(r["revenue_month"])
        ann = (r.get("create_time") or "")[:10]
        out.append(["%04d-%02d" % (y, m), r["revenue"], ann, max(ann or "0", avail_10th(y, m))])
    return ["ym", "revenue", "announced", "available"], sorted(out)


def get_dividends(code, end):
    rows = fm("TaiwanStockDividendResult", data_id=code, start_date="2014-01-01", end_date=end)
    return ["ex_date", "kind", "amount", "before_price", "reference_price"], [
        [r["date"], r.get("stock_or_cache_dividend", ""), g(r.get("stock_and_cache_dividend")), g(r.get("before_price")), g(r.get("reference_price"))]
        for r in rows]


FETCH = {"prices": get_prices, "per": get_per, "inst": get_inst, "revenue": get_revenue, "dividends": get_dividends}


# ---------- market-level ----------
def fetch_market(end, problems):
    base = os.path.join(data_dir(), "market")
    try:
        rows = fm("TaiwanStockPrice", data_id="TAIEX", start_date=WARMUP_START, end_date=end)
        write_plain(os.path.join(base, "taiex.csv"), ["date", "open", "high", "low", "close"],
                    [[r["date"], g(r["open"]), g(r["max"]), g(r["min"]), g(r["close"])] for r in rows])
        rows = fm("TaiwanStockTotalReturnIndex", data_id="TAIEX", start_date=WARMUP_START, end_date=end)
        write_plain(os.path.join(base, "taiex_tri.csv"), ["date", "close"], [[r["date"], g(r["price"])] for r in rows])
        rows = fm("TaiwanStockTotalInstitutionalInvestors", start_date=WARMUP_START, end_date=end)
        agg = {}
        for r in rows:
            n = r["name"]
            key = "foreign" if n.startswith("Foreign") else ("trust" if n == "Investment_Trust" else ("dealer" if n.startswith("Dealer") else None))
            if key:
                agg.setdefault(r["date"], {"foreign": 0, "trust": 0, "dealer": 0})[key] += int(r["buy"]) - int(r["sell"])
        write_plain(os.path.join(base, "inst_total.csv"), ["date", "foreign", "trust", "dealer"],
                    [[d, v["foreign"], v["trust"], v["dealer"]] for d, v in sorted(agg.items())])
        rows = fm("TaiwanStockTotalMarginPurchaseShortSale", start_date=WARMUP_START, end_date=end)
        write_plain(os.path.join(base, "margin_total.csv"), ["date", "margin_balance"],
                    [[r["date"], r["TodayBalance"]] for r in rows if r["name"] == "MarginPurchaseMoney"])
    except Exception as e:
        problems.append("市場層級資料抓取失敗：%s" % e)


def build_universe(problems):
    info = fm("TaiwanStockInfo")
    delist = fm("TaiwanStockDelisting")
    twse = {}
    for r in info:
        if r["type"] != "twse":
            continue
        c = r["stock_id"]
        if c == "0050" or (len(c) == 4 and c.isdigit() and not c.startswith("0")
                           and r["industry_category"] not in ("ETF", "ETN", "受益證券", "存託憑證", "Index")):
            twse.setdefault(c, {"name": r["stock_name"], "industry": r["industry_category"]})
    tpex = {r["stock_id"] for r in info if r["type"] == "tpex"}
    rows, unknown = [], 0
    for c, v in sorted(twse.items()):
        rows.append([c, v["name"], v["industry"], "twse", ""])
    for r in delist:
        c = r["stock_id"]
        if r["date"] < START or not (len(c) == 4 and c.isdigit()) or c.startswith("0"):
            continue
        if c in twse:
            for row in rows:
                if row[0] == c:
                    row[4] = r["date"]
        elif c not in tpex:
            unknown += 1
    if unknown:
        problems.append("有 %d 檔 2019 年後下市股票無法確認是上市或上櫃，未納入（可能有些微倖存者偏差）" % unknown)
    write_plain(os.path.join(data_dir(), "universe.csv"), ["code", "name", "industry", "market", "delisted_date"], rows)
    return [r[0] for r in rows]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--limit", type=int, default=0, help="max requests this run (0 = no limit)")
    ap.add_argument("--budget-min", type=float, default=0, help="stop after N minutes (0 = no limit)")
    ap.add_argument("--only", default="", help="comma list of datasets")
    ap.add_argument("--codes", default="", help="comma list of codes (testing)")
    a = ap.parse_args()
    t0 = time.time()
    problems = []
    end = C.tw_today().isoformat()
    dd = data_dir()
    state_path = os.path.join(dd, "meta", "backfill_state.json")
    state = json.load(open(state_path)) if os.path.exists(state_path) else {"done": {}}

    if a.codes:
        codes = a.codes.split(",")
    else:
        codes = build_universe(problems) if not state.get("universe_built") else [r["code"] for r in C.read_csv("tw-models/data/universe.csv")]
        state["universe_built"] = True
        if not state.get("market_done"):
            fetch_market(end, problems)
            state["market_done"] = end
    datasets = a.only.split(",") if a.only else DATASETS
    n = 0
    for ds in datasets:
        done = set(state["done"].get(ds, []))
        for code in codes:
            if code in done:
                continue
            if (a.limit and n >= a.limit) or (a.budget_min and time.time() - t0 > a.budget_min * 60):
                break
            try:
                header, rows = FETCH[ds](code, end)
                if rows:
                    write_gz(os.path.join(dd, ds, code + ".csv.gz"), header, rows)
                done.add(code)
            except Exception as e:
                problems.append("%s %s：%s" % (ds, code, e))
            n += 1
            state["done"][ds] = sorted(done)
            if n % 20 == 0:
                os.makedirs(os.path.dirname(state_path), exist_ok=True)
                json.dump(state, open(state_path, "w"), indent=0)
                print("  %s %d/%d  (requests this run %d)" % (ds, len(done), len(codes), n), flush=True)
    state["updated_utc"] = C.utc_now().strftime("%Y-%m-%d %H:%M:%S")
    state["remaining"] = {ds: len(codes) - len(set(state["done"].get(ds, []))) for ds in DATASETS}
    os.makedirs(os.path.dirname(state_path), exist_ok=True)
    json.dump(state, open(state_path, "w"), indent=0)
    C.write_json("tw-models/data/meta/backfill_report.json", {
        "requests_this_run": n, "remaining": state["remaining"], "end_date": end,
    }, problems[-200:], [{"name": "FinMind API v4", "url": API}])
    print("requests=%d remaining=%s problems=%d" % (n, state["remaining"], len(problems)))


if __name__ == "__main__":
    main()
