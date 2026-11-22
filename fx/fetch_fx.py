"""匯率位置：目前匯率在近 1、3、5 年處於什麼位置。

貨幣：USD/TWD、AUD/TWD、JPY/TWD（以 100 日圓計）、AUD/USD
來源：Twelve Data 日收盤
- 第一次（或歷史不足時）抓 5 年歷史，存在 fx/history/<PAIR>.csv
- 之後每天只補最近幾天（順便修正前幾天可能被更新的收盤價）
- 只保留週一～週五；當天的 K 棒要到 UTC 22:00（約紐約收盤）後才算完成，避免用到盤中數字

輸出 fx/position.json，每個貨幣：
- latest、date
- windows：近 1／3／5 年的 percentile（目前值在區間內的百分位）、high、low、mean、n
- change_20d_pct、change_60d_pct（以交易日計）
- summary：一句白話，以近 3 年百分位判斷

用法：python3 fx/fetch_fx.py [--dry-run]
"""
import bisect, datetime, os, sys
sys.path.insert(1, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "lib"))
import common as C

PAIRS = [  # (Twelve Data 代號, 檔名, 顯示名稱, 乘數)
    ("USD/TWD", "USD_TWD", "美元兌台幣", 1),
    ("AUD/TWD", "AUD_TWD", "澳幣兌台幣", 1),
    ("JPY/TWD", "JPY100_TWD", "100 日圓兌台幣", 100),
    ("AUD/USD", "AUD_USD", "澳幣兌美元", 1),
]
YEARS = 5
FULL_MIN_ROWS = 250 * YEARS - 50  # 少於這個數量就重新抓完整 5 年


def band(p):
    if p < 20: return "偏低"
    if p < 40: return "略低"
    if p < 60: return "中間"
    if p < 80: return "略高"
    return "偏高"


def bar_complete(d, now):
    """K 棒日期 d 是否已完成：週末不算；今天（UTC）的要等 22:00 UTC 之後"""
    day = datetime.date.fromisoformat(d)
    if day.weekday() >= 5:
        return False
    close_time = datetime.datetime.combine(day, datetime.time(22, 0), tzinfo=datetime.timezone.utc)
    return now >= close_time


def fetch_pair(symbol, mult, start=None, outputsize=15):
    params = {"symbol": symbol, "interval": "1day", "outputsize": 5000 if start else outputsize}
    if start:
        params["start_date"] = start
    data = C.twelvedata("time_series", **params)
    now = C.utc_now()
    return {v["datetime"][:10]: round(float(v["close"]) * mult, 4)
            for v in data.get("values", []) if bar_complete(v["datetime"][:10], now)}


def stats(rows, latest_date, years):
    start = (datetime.date.fromisoformat(latest_date) - datetime.timedelta(days=round(365.25 * years))).isoformat()
    vals = [v for d, v in rows if d >= start]
    if not vals or rows[0][0] > start:
        return None  # 歷史不足這個區間，不估算
    latest = rows[-1][1]
    s = sorted(vals)
    pct = round(bisect.bisect_right(s, latest) / len(s) * 100, 1)
    return {"from": start, "percentile": pct, "high": max(vals), "low": min(vals),
            "mean": round(sum(vals) / len(vals), 4), "n": len(vals)}


def main():
    problems, out = [], {}
    sources = [{"name": "Twelve Data Time Series（日收盤）", "url": "https://api.twelvedata.com/time_series"}]
    first_start = (C.tw_today() - datetime.timedelta(days=round(365.25 * YEARS) + 10)).isoformat()

    for symbol, fname, label, mult in PAIRS:
        rel = "fx/history/%s.csv" % fname
        hist = {r["date"]: float(r["close"]) for r in C.read_csv(rel)}
        try:
            if len(hist) < FULL_MIN_ROWS:
                hist.update(fetch_pair(symbol, mult, start=first_start))
            else:
                hist.update(fetch_pair(symbol, mult))
        except Exception as e:
            problems.append("%s 抓取失敗：%s" % (symbol, e))
        if not hist:
            continue
        rows = sorted(hist.items())
        C.write_csv(rel, ["date", "close"], [[d, "%g" % v] for d, v in rows])

        latest_date, latest = rows[-1]
        item = {"name": label, "pair": symbol if mult == 1 else "100 JPY/TWD",
                "latest": latest, "date": latest_date, "windows": {}}
        for y in (1, 3, 5):
            st = stats(rows, latest_date, y)
            if st is None:
                problems.append("%s 歷史資料不足 %d 年，該區間不計算" % (symbol, y))
            item["windows"]["%dy" % y] = st
        for n in (20, 60):
            item["change_%dd_pct" % n] = round((latest / rows[-1 - n][1] - 1) * 100, 2) if len(rows) > n else None
        w3 = item["windows"]["3y"]
        if w3:
            item["summary"] = "%s 目前 %g，在近 3 年第 %d 百分位（%s）" % (label, latest, round(w3["percentile"]), band(w3["percentile"]))
        else:
            item["summary"] = None
        out[fname] = item

    C.write_json("fx/position.json", {
        "note": "percentile = 區間內小於或等於目前值的天數比例；20/60 日以交易日計；JPY 以 100 日圓計",
        "pairs": out,
    }, problems, sources)
    print("pairs=%d problems=%s" % (len(out), problems))
    for k, v in out.items():
        print(" ", v["summary"], "| 20日 %s%% 60日 %s%%" % (v["change_20d_pct"], v["change_60d_pct"]))


if __name__ == "__main__":
    main()
