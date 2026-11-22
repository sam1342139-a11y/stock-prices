"""Daily append for tw-models (run 18:30 Taiwan time on weekdays).

Per-stock (TWSE OpenAPI / T86, a handful of requests per day):
  daily/prices_YYYY-MM.csv   date,code,open,high,low,close,volume,value,spread   (STOCK_DAY_ALL; TWSE "Change" is vs the reference price)
  daily/per_YYYY-MM.csv      date,code,pe,dy,pb                                  (BWIBBU_ALL)
  daily/inst_YYYY-MM.csv     date,code,foreign,trust,dealer  (net shares)        (T86)
  daily/revenue_YYYY-MM.csv  code,ym,revenue,announced,available                 (t187ap05_L, only on days 10–16)
Market level (FinMind, 4 requests): market_taiex / taiex_tri / inst_total / margin_total
US market (Twelve Data): soxx.csv, usdtwd.csv via fetch_us_market.py (called from the workflow)

Usage: python3 tw-models/update_daily.py [--dry-run]
"""
import csv, datetime, os, sys, time
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(1, os.path.join(os.path.dirname(HERE), "lib"))
import common as C
import fetch_history as H

URL_DAY = "https://openapi.twse.com.tw/v1/exchangeReport/STOCK_DAY_ALL"
URL_BW = "https://openapi.twse.com.tw/v1/exchangeReport/BWIBBU_ALL"
URL_T86 = "https://www.twse.com.tw/rwd/zh/fund/T86?date={ymd}&selectType=ALLBUT0999&response=json"
URL_REV = "https://openapi.twse.com.tw/v1/opendata/t187ap05_L"


def roc(s):
    s = s.strip()
    return "%04d-%s-%s" % (int(s[:-4]) + 1911, s[-4:-2], s[-2:])


def num(s):
    s = (s or "").replace(",", "").strip()
    try:
        return float(s)
    except ValueError:
        return None


def g(v):
    return "" if v is None else "%g" % v


def upsert(rel, header, key_cols, rows):
    """Merge rows into a monthly daily file, replacing rows with the same key."""
    path = C.out_path(rel)
    cur = {}
    if os.path.exists(C.read_path(rel)):
        with open(C.read_path(rel), encoding="utf-8") as f:
            for r in csv.DictReader(f):
                cur[tuple(r[k] for k in key_cols)] = [r[h] for h in header]
    for r in rows:
        cur[tuple(r[header.index(k)] for k in key_cols)] = r
    with open(path, "w", encoding="utf-8", newline="") as f:
        w = csv.writer(f, lineterminator="\n")
        w.writerow(header)
        w.writerows(sorted(cur.values()))
    return len(rows)


def main():
    problems = []
    codes = {r["code"] for r in C.read_csv("tw-models/data/universe.csv")}
    if not codes:
        print("tw-models/data/universe.csv 不存在（歷史回補尚未開始），今天先略過")
        return
    day = C.http_json(URL_DAY)
    date = roc(day[0]["Date"])
    ym = date[:7]
    today = C.tw_today().isoformat()
    if date != today:
        problems.append("證交所最新資料日期 %s 不是今天 %s（可能休市或尚未更新）" % (date, today))

    rows = [[date, r["Code"].strip(), g(num(r["OpeningPrice"])), g(num(r["HighestPrice"])), g(num(r["LowestPrice"])),
             g(num(r["ClosingPrice"])), r["TradeVolume"], r["TradeValue"], g(num(r["Change"]))]
            for r in day if r["Code"].strip() in codes and num(r["ClosingPrice"])]
    n_px = upsert("tw-models/data/daily/prices_%s.csv" % ym,
                  ["date", "code", "open", "high", "low", "close", "volume", "value", "spread"], ["date", "code"], rows)

    try:
        bw = C.http_json(URL_BW)
        if bw and roc(bw[0]["Date"]) == date:
            rows = [[date, r["Code"].strip(), g(num(r["PEratio"])), g(num(r["DividendYield"])), g(num(r["PBratio"]))]
                    for r in bw if r["Code"].strip() in codes]
            upsert("tw-models/data/daily/per_%s.csv" % ym, ["date", "code", "pe", "dy", "pb"], ["date", "code"], rows)
        else:
            problems.append("BWIBBU_ALL 日期與成交資料不同，本益比未更新")
    except Exception as e:
        problems.append("BWIBBU_ALL 抓取失敗：%s" % e)

    try:
        t = C.http_json(URL_T86.format(ymd=date.replace("-", "")))
        if t.get("stat") == "OK":
            f = t["fields"]
            ic, ifx, ifd, itr, idl = (f.index(x) for x in ("證券代號", "外陸資買賣超股數(不含外資自營商)", "外資自營商買賣超股數",
                                                            "投信買賣超股數", "自營商買賣超股數"))
            rows = []
            for d in t["data"]:
                c = d[ic].strip()
                if c in codes:
                    rows.append([date, c, int((num(d[ifx]) or 0) + (num(d[ifd]) or 0)), int(num(d[itr]) or 0), int(num(d[idl]) or 0)])
            upsert("tw-models/data/daily/inst_%s.csv" % ym, ["date", "code", "foreign", "trust", "dealer"], ["date", "code"], rows)
        else:
            problems.append("T86 三大法人 %s 沒有資料：%s" % (date, t.get("stat")))
    except Exception as e:
        problems.append("T86 三大法人抓取失敗：%s" % e)

    if 10 <= C.tw_today().day <= 16 or "--revenue" in sys.argv:
        try:
            rev = C.http_json(URL_REV)
            rows = []
            for r in rev:
                c = r["公司代號"].strip()
                if c not in codes:
                    continue
                y, m = int(r["資料年月"][:-2]) + 1911, int(r["資料年月"][-2:])
                ann = roc(r["出表日期"])
                v = num(r["營業收入-當月營收"])  # 千元 → 元（與 FinMind 歷史一致）
                rows.append([c, "%04d-%02d" % (y, m), "" if v is None else str(int(round(v * 1000))),
                             ann, max(ann, H.avail_10th(y, m))])
            upsert("tw-models/data/daily/revenue_%s.csv" % ym, ["code", "ym", "revenue", "announced", "available"], ["code", "ym"], rows)
        except Exception as e:
            problems.append("月營收抓取失敗：%s" % e)

    # market level via FinMind (same source as history)
    start = (datetime.date.fromisoformat(date) - datetime.timedelta(days=10)).isoformat()
    try:
        r = H.fm("TaiwanStockPrice", data_id="TAIEX", start_date=start, end_date=date)
        upsert("tw-models/data/daily/market_taiex_%s.csv" % ym, ["date", "open", "high", "low", "close"], ["date"],
               [[x["date"], g(x["open"]), g(x["max"]), g(x["min"]), g(x["close"])] for x in r if x["date"][:7] == ym])
        r = H.fm("TaiwanStockTotalReturnIndex", data_id="TAIEX", start_date=start, end_date=date)
        upsert("tw-models/data/daily/market_taiex_tri_%s.csv" % ym, ["date", "close"], ["date"],
               [[x["date"], g(x["price"])] for x in r if x["date"][:7] == ym])
        r = H.fm("TaiwanStockTotalInstitutionalInvestors", start_date=start, end_date=date)
        agg = {}
        for x in r:
            n = x["name"]
            k = "foreign" if n.startswith("Foreign") else ("trust" if n == "Investment_Trust" else ("dealer" if n.startswith("Dealer") else None))
            if k and x["date"][:7] == ym:
                agg.setdefault(x["date"], {"foreign": 0, "trust": 0, "dealer": 0})[k] += int(x["buy"]) - int(x["sell"])
        upsert("tw-models/data/daily/market_inst_total_%s.csv" % ym, ["date", "foreign", "trust", "dealer"], ["date"],
               [[d, v["foreign"], v["trust"], v["dealer"]] for d, v in agg.items()])
        r = H.fm("TaiwanStockTotalMarginPurchaseShortSale", start_date=start, end_date=date)
        upsert("tw-models/data/daily/market_margin_total_%s.csv" % ym, ["date", "margin_balance"], ["date"],
               [[x["date"], x["TodayBalance"]] for x in r if x["name"] == "MarginPurchaseMoney" and x["date"][:7] == ym])
    except Exception as e:
        problems.append("市場層級資料（FinMind）抓取失敗：%s" % e)

    C.write_json("tw-models/data/meta/daily_report.json", {"date": date, "price_rows": n_px}, problems, [
        {"name": "證交所 OpenAPI STOCK_DAY_ALL", "url": URL_DAY}, {"name": "證交所 OpenAPI BWIBBU_ALL", "url": URL_BW},
        {"name": "證交所 T86 三大法人", "url": URL_T86.replace("{ymd}", "YYYYMMDD")},
        {"name": "證交所 OpenAPI t187ap05_L 月營收", "url": URL_REV},
        {"name": "FinMind（加權指數、法人買賣金額、融資餘額）", "url": H.API}])
    print("date=%s prices=%d problems=%s" % (date, n_px, problems))


if __name__ == "__main__":
    main()
