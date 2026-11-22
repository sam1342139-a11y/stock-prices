"""SOXX and USD/TWD daily closes (Twelve Data) for the Taiwan regime model.

Writes tw-models/data/market/soxx.csv and usdtwd.csv (date,close). First run pulls from 2019,
later runs refresh the last ~15 days. Weekend FX bars are dropped.
Usage: python3 tw-models/fetch_us_market.py [--dry-run]
"""
import datetime, os, sys
sys.path.insert(1, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "lib"))
import common as C

ITEMS = [("SOXX", "soxx"), ("USD/TWD", "usdtwd")]


def main():
    problems = []
    for sym, name in ITEMS:
        rel = "tw-models/data/market/%s.csv" % name
        hist = {r["date"]: r["close"] for r in C.read_csv(rel)}
        try:
            params = {"symbol": sym, "interval": "1day"}
            if len(hist) < 2500:
                params.update(start_date="2014-01-01", outputsize=5000)
            else:
                params.update(outputsize=15)
            data = C.twelvedata("time_series", **params)
            for v in data.get("values", []):
                d = v["datetime"][:10]
                if datetime.date.fromisoformat(d).weekday() < 5:
                    hist[d] = "%g" % float(v["close"])
        except Exception as e:
            problems.append("%s 抓取失敗：%s" % (sym, e))
        C.write_csv(rel, ["date", "close"], sorted(hist.items()))
        print(sym, len(hist), "rows, last", max(hist) if hist else None)
    if problems:
        print("problems:", problems)


if __name__ == "__main__":
    main()
