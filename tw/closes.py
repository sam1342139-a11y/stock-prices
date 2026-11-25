"""Daily closes of every TWSE-listed security (stocks and ETFs), kept as monthly CSV files.

  tw/closes/YYYY-MM.csv   date,code,close   (one line per security per trading day; appended daily)
Source: TWSE 每日收盤行情 (MI_INDEX, type=ALLBUT0999). Public market data only.

Usage:
  python3 tw/closes.py                     add the latest trading day (today, Taiwan time) if missing
  python3 tw/closes.py --backfill 2026-10-01   add every missing trading day from that date to today
Used by the dashboard (tw-models/build_dashboard.py) to value the account on any past day.
"""
import csv, datetime, glob, json, os, sys, time, urllib.request
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DIR = os.path.join(ROOT, "tw", "closes")
URL = "https://www.twse.com.tw/rwd/zh/afterTrading/MI_INDEX?date=%s&type=ALLBUT0999&response=json"
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36"


def have_dates():
    out = set()
    for f in glob.glob(os.path.join(DIR, "*.csv")):
        with open(f, encoding="utf-8") as fh:
            out |= {r["date"] for r in csv.DictReader(fh)}
    return out


def fetch(day):
    """{code: close} for a trading day, {} for a holiday / no data."""
    req = urllib.request.Request(URL % day.strftime("%Y%m%d"), headers={"User-Agent": UA})
    for i in range(3):
        try:
            d = json.loads(urllib.request.urlopen(req, timeout=60).read())
            break
        except Exception as e:
            err = e
            time.sleep(5 * (i + 1))
    else:
        raise RuntimeError("MI_INDEX %s：%s" % (day, type(err).__name__))
    if d.get("stat") != "OK":
        return {}
    for t in d.get("tables") or []:
        f = t.get("fields") or []
        if "每日收盤行情" in (t.get("title") or "") and "證券代號" in f and "收盤價" in f:
            ic, ix = f.index("證券代號"), f.index("收盤價")
            out = {}
            for r in t.get("data") or []:
                try:
                    out[r[ic].strip()] = float(r[ix].replace(",", ""))
                except (ValueError, AttributeError):
                    pass  # no trade that day ("--")
            return out
    return {}


def append(day, closes):
    os.makedirs(DIR, exist_ok=True)
    path = os.path.join(DIR, day.strftime("%Y-%m") + ".csv")
    new = not os.path.exists(path)
    with open(path, "a", encoding="utf-8", newline="") as fh:
        w = csv.writer(fh)
        if new:
            w.writerow(["date", "code", "close"])
        for c in sorted(closes):
            w.writerow([day.isoformat(), c, ("%.4f" % closes[c]).rstrip("0").rstrip(".")])


def main():
    today = (datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(hours=8)).date()
    start = today
    if "--backfill" in sys.argv:
        start = datetime.date.fromisoformat(sys.argv[sys.argv.index("--backfill") + 1])
    have = have_dates()
    added = []
    d = start
    while d <= today:
        if d.weekday() < 5 and d.isoformat() not in have:
            c = fetch(d)
            if c:
                append(d, c)
                added.append((d.isoformat(), len(c)))
            time.sleep(3)
        d += datetime.timedelta(days=1)
    print("closes added:", added or "none")


if __name__ == "__main__":
    main()
