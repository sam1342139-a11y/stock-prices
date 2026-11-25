"""Checks latest.json (26 US closes) and writes fcn/prices_checked.json for the FCN morning update.

Replaces the checks the morning Claude routine used to do by hand. Does not modify latest.json.
  - basic: complete, no problems, exactly 26 positive prices, fetched after asof 21:00 UTC
  - final-value corrections: today's history vs the provisional prices of the previous run (git history)
  - a single ticker off by >0.5% does NOT fail the file: it goes to `mismatch` (with integer-multiple check,
    detected split, and a second source: Nasdaq historical quotes)
  - splits in the last 30 days: Twelve Data raw (adjust=none) vs split-adjusted closes -> `splits`
  - day move beyond +-25% -> watch
  - trading days present in history but never published as asof -> fill_days
  - Cathay United Bank board rate (spot buy USD/AUD/JPY), best effort -> fx
Usage: python3 fcn/check_prices.py
"""
import datetime, json, os, re, subprocess, sys, time, urllib.parse, urllib.request
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "lib"))
import common as C

EXPECTED = 26
EXPECTED_SYMBOLS = ["AAPL", "AMAT", "AMD", "ARM", "ASML", "ASX", "AVGO", "AMZN", "CRWD", "GOOG", "INTC", "KLAC", "LITE", "MSFT",
                    "MU", "NVDA", "SNDK", "SOXX", "SPCX", "SPY", "TSLA", "TSM", "ENTG", "NBIS", "BE", "SOXL"]
SAME, CORR_MAX, WATCH_PCT = 0.01, 0.005, 25.0
SPLIT_RATIOS = [2, 3, 4, 5, 8, 10, 15, 20, 25, 30, 40, 50]
TD = "https://api.twelvedata.com/time_series"
NASDAQ_HIST = "https://api.nasdaq.com/api/quote/%s/historical?assetclass=%s&fromdate=%s&todate=%s&limit=40"
ETFS = {"SOXX", "SPY", "SOXL"}
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36"
SPLIT_DAYS, MATCH_PCT = 30, 0.1
FX_URL = "https://www.cathaybk.com.tw/cathaybk/personal/product/deposit/currency-billboard/"
SOURCES = [{"name": "stock-prices latest.json（Twelve Data 收盤價）", "url": "https://github.com/sam1342139-a11y/stock-prices/blob/main/latest.json"},
           {"name": "Twelve Data time_series（adjust=none 原始價，用來偵測拆合股）", "url": TD},
           {"name": "Nasdaq 歷史行情（第二價格來源，交叉比對）", "url": "https://www.nasdaq.com/market-activity/quotes/historical"},
           {"name": "國泰世華銀行 牌告匯率（即期買入）", "url": FX_URL}]


def git(*a):
    return subprocess.run(["git", "-C", ROOT] + list(a), capture_output=True, text=True).stdout


def previous_run(asof):
    """Most recent committed latest.json whose asof is earlier than today's asof."""
    for sha in git("log", "-n", "40", "--format=%H", "--", "latest.json").split():
        try:
            d = json.loads(git("show", "%s:latest.json" % sha))
        except ValueError:
            continue
        if d.get("asof") and d["asof"] < asof:
            return sha, d
    return None, None


def split_ratio(old, new):
    r = new / old if old else 0
    for k in SPLIT_RATIOS:
        for v, label in ((k, "%d 倍" % k), (1.0 / k, "1/%d" % k)):
            if abs(r / v - 1) < 0.03:
                return label
    return None


def td_series(symbols, outputsize, adjust=None):
    """Twelve Data closes {symbol: {date: close}}; groups of 7 per minute (free plan: 8 credits/min)."""
    key = os.environ.get("TWELVEDATA_KEY", "").strip()
    if not key:
        raise RuntimeError("沒有設定 TWELVEDATA_KEY")
    out, syms = {}, list(symbols)
    for i in range(0, len(syms), 7):
        time.sleep(65)  # the price fetch (or the previous group) just used this minute's credits
        q = {"symbol": ",".join(syms[i:i + 7]), "interval": "1day", "outputsize": outputsize}
        if adjust:
            q["adjust"] = adjust
        req = urllib.request.Request(TD + "?" + urllib.parse.urlencode(q), headers={"Authorization": "apikey " + key})
        data = json.loads(urllib.request.urlopen(req, timeout=60).read())
        if len(syms[i:i + 7]) == 1:
            data = {syms[i]: data}
        for s_, d in data.items():
            if isinstance(d, dict) and d.get("values"):
                out[s_] = {r["datetime"]: float(r["close"]) for r in d["values"]}
    return out


def split_label(k):
    return ("1 拆 %d" % round(k)) if k > 1 else ("%d 合 1" % round(1 / k))


def detect_splits(problems):
    """Splits within SPLIT_DAYS: raw/adjusted ratio is k before the effective date and 1 from it on."""
    try:
        raw = td_series(EXPECTED_SYMBOLS, SPLIT_DAYS, adjust="none")
    except Exception as e:
        problems.append("拆合股偵測：Twelve Data 原始價抓取失敗（%s）" % type(e).__name__)
        return []
    cand = []
    for s_, ser in raw.items():
        days = sorted(ser)
        if any(ser[a] and not 0.6 < ser[b] / ser[a] < 1.67 for a, b in zip(days, days[1:])):
            cand.append(s_)
    if not cand:
        return []
    try:
        adj = td_series(cand, SPLIT_DAYS)
    except Exception as e:
        problems.append("拆合股偵測：Twelve Data 還原價抓取失敗（%s）" % type(e).__name__)
        return []
    out = []
    for s_ in cand:
        r, a = raw.get(s_, {}), adj.get(s_, {})
        days = sorted(set(r) & set(a))
        ratios = [(d, r[d] / a[d]) for d in days if a[d]]
        before = [(d, k) for d, k in ratios if abs(k - 1) > 0.05]
        if not before:
            continue  # big move but no adjustment: not a split
        k = before[0][1]
        lab = split_ratio(1, k)
        eff = next((d for d, x in ratios if d > before[-1][0] and abs(x - 1) <= 0.01), None)
        out.append({"ticker": s_, "ratio": split_label(k) if lab else "比例 %.4f（非整數倍）" % k, "factor": round(k, 4),
                    "effective_date": eff, "last_date_before": before[-1][0],
                    "adjusted_history": {d: round(a[d], 4) for d in sorted(a)},
                    "raw_history": {d: round(r[d], 4) for d in sorted(r)}})
    return out


def nasdaq_close(ticker, date):
    """Close on `date` from Nasdaq historical quotes (split-adjusted like Twelve Data's default)."""
    d = datetime.date.fromisoformat(date)
    url = NASDAQ_HIST % (ticker, "etf" if ticker in ETFS else "stocks", d - datetime.timedelta(days=3), d + datetime.timedelta(days=1))
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "application/json"})
    rows = ((json.loads(urllib.request.urlopen(req, timeout=40).read()).get("data") or {}).get("tradesTable") or {}).get("rows") or []
    for row in rows:
        m, dd, y = row["date"].split("/")
        if "%s-%s-%s" % (y, m, dd) == date:
            return float(row["close"].replace("$", "").replace(",", ""))
    return None


def second_source(ticker, date, old, new):
    try:
        v = nasdaq_close(ticker, date)
    except Exception as e:
        return {"source": "Nasdaq", "value": None, "matches": "查詢失敗（%s）" % type(e).__name__}
    if v is None:
        return {"source": "Nasdaq", "value": None, "matches": "Nasdaq 查不到這一天"}
    near = lambda x: x and abs(x - v) / v * 100 <= MATCH_PCT
    m = "新值" if near(new) else "舊值" if near(old) else "都不吻合"
    return {"source": "Nasdaq", "value": v, "matches": m}


def fetch_fx():
    """Spot buy rates from the Cathay board. Returns (fx or None, problem or None)."""
    try:
        req = urllib.request.Request(FX_URL, headers={"User-Agent": "Mozilla/5.0", "Accept-Language": "zh-TW"})
        html = urllib.request.urlopen(req, timeout=40).read().decode("utf-8", "replace")
    except Exception as e:
        return None, "國泰世華牌告匯率抓不到（%s），請繼續由 Claude 抓" % type(e).__name__
    text = re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", re.sub(r"(?s)<(script|style)[^>]*>.*?</\1>", " ", html)))
    out = {}
    for cur in ("USD", "AUD", "JPY"):
        # board block: "<中文名><CODE> 歷史走勢 ... 即期匯率 <bank buy> <bank sell>"
        m = re.search(r"%s 歷史走勢.{0,80}?即期匯率 (\d+\.\d+) (\d+\.\d+)" % cur, text)
        if m:
            out[cur] = float(m.group(1))
    t = re.search(r"(\d{4})年(\d{1,2})月(\d{1,2})日 (\d{2}:\d{2}(?::\d{2})?)", text)
    if len(out) < 3:
        return None, "國泰世華牌告匯率頁面格式讀不出 USD／AUD／JPY（讀到 %s），請繼續由 Claude 抓" % (sorted(out) or "無")
    return {"date": "%s-%02d-%02d" % (t.group(1), int(t.group(2)), int(t.group(3))) if t else None, "time": t.group(4) if t else None,
            "source": "國泰世華銀行 牌告匯率（即期買入）", **out}, None


def main():
    cur = json.load(open(os.path.join(ROOT, "latest.json"), encoding="utf-8"))
    asof, prices, hist = cur.get("asof"), cur.get("prices") or {}, cur.get("history") or {}
    fail, problems = [], []

    # 1) basic
    if cur.get("complete") is not True:
        fail.append("latest.json 的 complete 不是 true")
    if cur.get("problems"):
        fail.append("latest.json 有 problems：%s" % "；".join(map(str, cur["problems"])))
    bad = [k for k, v in prices.items() if not isinstance(v, (int, float)) or v <= 0]
    if len(prices) != EXPECTED or bad:
        fail.append("價格應為 %d 檔正數，實際 %d 檔%s" % (EXPECTED, len(prices), "，非正數：" + "、".join(bad) if bad else ""))
    try:
        fetched = datetime.datetime.strptime(cur.get("fetched_at_utc", ""), "%Y-%m-%d %H:%M:%S")
        if fetched < datetime.datetime.strptime(asof, "%Y-%m-%d") + datetime.timedelta(hours=21):
            fail.append("抓價時間 %s UTC 早於 %s 21:00 UTC（可能是盤中價）" % (cur["fetched_at_utc"], asof))
    except (ValueError, TypeError):
        fail.append("fetched_at_utc 或 asof 格式不對")

    # 2) final-value corrections vs the previous run's provisional prices.
    #    A single ticker off by >0.5% goes to `mismatch`; the file status stays ok (only that ticker should be held back).
    splits = detect_splits(problems)
    split_by = {x["ticker"]: x for x in splits}
    corrections, mismatch, compared_with = [], [], None
    sha, prev = previous_run(asof) if asof else (None, None)
    if not prev:
        problems.append("找不到前一次的 latest.json，無法做終值修正比對")
    else:
        pd = prev["asof"]
        compared_with = {"asof": pd, "commit": sha[:7]}
        final = hist.get(pd)
        if not final:
            problems.append("history 裡沒有前一次的日期 %s，無法比對終值" % pd)
        else:
            for k, old in sorted((prev.get("prices") or {}).items()):
                new = final.get(k)
                if new is None or not old:
                    continue
                diff = abs(new - old)
                if diff <= SAME:
                    continue
                sr = split_ratio(old, new)
                if sr or diff / old > CORR_MAX:
                    mismatch.append({"ticker": k, "date": pd, "old": old, "new": new, "diff_pct": round((new / old - 1) * 100, 2),
                                     "integer_multiple": sr, "split": {kk: split_by[k][kk] for kk in ("ratio", "effective_date")} if k in split_by else None,
                                     "second_source": None if sr else second_source(k, pd, old, new)})
                else:
                    corrections.append({"ticker": k, "date": pd, "old": old, "new": new})

    # 3) watch: day move beyond +-25%
    days = sorted(hist)
    watch = []
    if len(days) >= 2 and days[-1] == asof:
        a, b = hist[days[-2]], hist[days[-1]]
        for k in sorted(b):
            if a.get(k) and b.get(k):
                pct = (b[k] / a[k] - 1) * 100
                if abs(pct) > WATCH_PCT:
                    watch.append({"ticker": k, "date": asof, "prev_close": a[k], "close": b[k], "change_pct": round(pct, 2)})

    # 4) trading days in history newer than the previous run but not today (never published as asof)
    fill = [{"date": d, "prices": hist[d]} for d in days if prev and prev["asof"] < d < asof]

    fx, fx_problem = fetch_fx()
    if fx_problem:
        problems.append(fx_problem)

    C.write_json("fcn/prices_checked.json", {
        "status": "fail" if fail else "ok", "fail_reasons": fail, "asof": asof,
        "fetched_at_utc": cur.get("fetched_at_utc"), "compared_with": compared_with,
        "prices": prices, "corrections": corrections,
        "mismatch_tickers": [m["ticker"] for m in mismatch], "mismatch": mismatch, "splits": splits,
        "fill_days": fill, "watch": watch, "history": hist, "fx": fx,
        "notes": ["asof 當天的 prices 是暫定價，隔天以 history 的終值為準；corrections 是前一次暫定價改成終值的清單",
                  "status 為 fail（基本檢查沒過）時整批不要寫入；fail_reasons 說明原因",
                  "mismatch：前一次暫定價和這次終值差超過 0.5% 的個別代號，只有這些代號不要寫入，其他照常；integer_multiple 是整數倍（疑似拆合股），second_source 是 Nasdaq 交叉比對結果（matches：新值／舊值／都不吻合）",
                  "splits：近 30 天偵測到的拆合股（ratio、effective_date 生效日），adjusted_history 是還原後的歷史價、raw_history 是原始價",
                  "fill_days：前一次到這次之間、history 有但沒被當作 asof 發布過的交易日",
                  "fx 抓不到時為 null，原因在 problems"]}, problems, SOURCES)
    print("prices_checked", asof, "fail" if fail else "ok", fail, problems)


if __name__ == "__main__":
    main()
