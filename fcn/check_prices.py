"""Checks latest.json (26 US closes) and writes fcn/prices_checked.json for the FCN morning update.

Replaces the checks the morning Claude routine used to do by hand. Does not modify latest.json.
  - basic: complete, no problems, exactly 26 positive prices, fetched after asof 21:00 UTC
  - final-value corrections: today's history vs the provisional prices of the previous run (git history)
  - split suspicion (fixed ratio) / >0.5% difference -> fail
  - day move beyond +-25% -> watch
  - trading days present in history but never published as asof -> fill_days
  - Cathay United Bank board rate (spot buy USD/AUD/JPY), best effort -> fx
Usage: python3 fcn/check_prices.py
"""
import datetime, json, os, re, subprocess, sys, urllib.request
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "lib"))
import common as C

EXPECTED = 26
SAME, CORR_MAX, WATCH_PCT = 0.01, 0.005, 25.0
SPLIT_RATIOS = [2, 3, 4, 5, 8, 10, 15, 20, 25, 30, 40, 50]
FX_URL = "https://www.cathaybk.com.tw/cathaybk/personal/product/deposit/currency-billboard/"
SOURCES = [{"name": "stock-prices latest.json（Twelve Data 收盤價）", "url": "https://github.com/sam1342139-a11y/stock-prices/blob/main/latest.json"},
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

    # 2) final-value corrections vs the previous run's provisional prices
    corrections, compared_with = [], None
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
                if sr:
                    fail.append("%s 在 %s 的價格從 %s 變 %s，約 %s，疑似拆合股" % (k, pd, old, new, sr))
                elif diff / old > CORR_MAX:
                    fail.append("%s 在 %s 的終值和暫定價差 %.2f%%（%s → %s），超過 0.5%%" % (k, pd, diff / old * 100, old, new))
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
        "prices": prices, "corrections": corrections, "fill_days": fill, "watch": watch,
        "history": hist, "fx": fx,
        "notes": ["asof 當天的 prices 是暫定價，隔天以 history 的終值為準；corrections 是前一次暫定價改成終值的清單",
                  "status 為 fail 時不要寫入價格；fail_reasons 說明原因",
                  "fill_days：前一次到這次之間、history 有但沒被當作 asof 發布過的交易日",
                  "fx 抓不到時為 null，原因在 problems"]}, problems, SOURCES)
    print("prices_checked", asof, "fail" if fail else "ok", fail, problems)


if __name__ == "__main__":
    main()
