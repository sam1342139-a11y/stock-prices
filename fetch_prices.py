import json, os, sys, time, urllib.request, urllib.parse, datetime

SYMBOLS = ["AAPL","AMAT","AMD","ARM","ASML","ASX","AVGO",
           "AMZN","CRWD","GOOG","INTC","KLAC","LITE","MSFT",
           "MU","NVDA","SNDK","SOXX","SPCX","SPY","TSLA",
           "TSM","ENTG","NBIS","BE","SOXL"]
GROUP = 7
WAIT = 65
KEY = os.environ.get("TWELVEDATA_KEY", "").strip()


def call_api(symbols):
    q = urllib.parse.urlencode({"symbol": ",".join(symbols), "interval": "1day",
                                "outputsize": 6, "apikey": KEY})
    with urllib.request.urlopen("https://api.twelvedata.com/time_series?" + q, timeout=60) as r:
        return json.loads(r.read().decode("utf-8"))


def fetch_group(symbols):
    for attempt in range(3):
        data = call_api(symbols)
        if isinstance(data, dict) and data.get("status") == "error" and data.get("code") == 429:
            time.sleep(WAIT)
            continue
        return data
    return {"status": "error", "message": "rate limited"}


def main():
    if not KEY:
        print("missing TWELVEDATA_KEY")
        sys.exit(1)
    groups = [SYMBOLS[i:i + GROUP] for i in range(0, len(SYMBOLS), GROUP)]
    hist, problems, latest = {}, [], {}
    for gi, g in enumerate(groups):
        if gi:
            time.sleep(WAIT)
        data = fetch_group(g)
        if data.get("status") == "error":
            problems.append("group failed %s: %s" % (",".join(g), data.get("message")))
            continue
        for s in g:
            d = data.get(s)
            if not d or d.get("status") != "ok" or not d.get("values"):
                problems.append("%s no data" % s)
                continue
            for row in d["values"]:
                hist.setdefault(row["datetime"], {})[s] = round(float(row["close"]), 2)
            latest[s] = d["values"][0]["datetime"]
    asof = max(latest.values()) if latest else None
    for s in SYMBOLS:
        if s in latest and latest[s] != asof:
            problems.append("%s latest date %s differs from %s" % (s, latest[s], asof))
    complete = (not problems) and asof is not None and len(latest) == len(SYMBOLS)
    out = {
        "complete": complete,
        "asof": asof,
        "fetched_at_utc": datetime.datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S"),
        "problems": problems,
        "prices": hist.get(asof, {}) if complete else {},
        "history": {d: hist[d] for d in sorted(hist) if len(hist[d]) == len(SYMBOLS)},
    }
    with open("latest.json", "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=1)
    print("complete=%s asof=%s problems=%s" % (complete, asof, problems))
    if not complete:
        sys.exit(1)


if __name__ == "__main__":
    main()
