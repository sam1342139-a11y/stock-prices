"""美股財報日曆：latest.json 那 26 檔（清單從 fetch_prices.py 讀）。

來源：Twelve Data /earnings_calendar（需要 Grow 以上方案）。
方案不支援時，不估算、不換其他來源，把原因寫進 problems，清單留空。

輸出 calendar/earnings.json：
- earnings：[{symbol, company, date, time, date_tw, confirmed, source}]
- next_7_days、next_14_days：以台灣今天為起點
欄位說明：
- time：bmo（盤前）／amc（盤後）／unknown
- date_tw：台灣日期。bmo 與美國日期同一天；amc 是美國日期的隔天（台灣清晨）；unknown 留 null
- confirmed：Twelve Data 沒有提供「是否確定」欄位時留 null

用法：python3 calendar/fetch_earnings.py [--dry-run]
"""
import datetime, os, sys
sys.path.insert(1, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "lib"))
import common as C

DAYS_AHEAD = 30
TIME_MAP = {"pre market": "bmo", "before market open": "bmo", "bmo": "bmo",
            "after hours": "amc", "after market close": "amc", "amc": "amc"}


def to_time(raw):
    return TIME_MAP.get((raw or "").strip().lower(), "unknown")


def date_tw(date, t):
    if t == "bmo":
        return date
    if t == "amc":
        return (datetime.date.fromisoformat(date) + datetime.timedelta(days=1)).isoformat()
    return None


def main():
    problems = []
    today = C.tw_today()
    end = today + datetime.timedelta(days=DAYS_AHEAD)
    symbols = C.us_symbols()
    url = "https://api.twelvedata.com/earnings_calendar?start_date=%s&end_date=%s" % (today, end)
    sources = [{"name": "Twelve Data Earnings Calendar", "url": "https://api.twelvedata.com/earnings_calendar"}]

    earnings = []
    try:
        data = C.twelvedata("earnings_calendar", start_date=today.isoformat(), end_date=end.isoformat())
        by_date = data.get("earnings") or {}
        wanted = set(symbols)
        for d, items in by_date.items():
            for it in items or []:
                if it.get("symbol") not in wanted:
                    continue
                t = to_time(it.get("time"))
                earnings.append({
                    "symbol": it["symbol"], "company": it.get("name"), "date": d, "time": t,
                    "date_tw": date_tw(d, t), "confirmed": it.get("confirmed"), "source": "Twelve Data",
                })
        found = {e["symbol"] for e in earnings}
        missing = [s for s in symbols if s not in found]
        if missing:
            problems.append("未來 %d 天內沒有財報資料（ETF 本來就沒有財報）：%s" % (DAYS_AHEAD, ", ".join(missing)))
    except Exception as e:
        problems.append("財報日曆抓取失敗，未估算：%s" % e)

    earnings.sort(key=lambda e: (e["date"], e["symbol"]))
    def within(n):
        lim = (today + datetime.timedelta(days=n)).isoformat()
        return [e for e in earnings if today.isoformat() <= (e["date_tw"] or e["date"]) <= lim]

    C.write_json("calendar/earnings.json", {
        "today_tw": today.isoformat(),
        "symbols": symbols,
        "earnings": earnings,
        "next_7_days": within(7),
        "next_14_days": within(14),
    }, problems, sources)
    print("earnings=%d problems=%s" % (len(earnings), problems))


if __name__ == "__main__":
    main()
