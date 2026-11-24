"""Earnings calendar for the FCN watchlist: earnings/calendar.json (daily).

US: Nasdaq earnings calendar (public JSON, one call per date) scanned from 3 days ago to ~10 weeks ahead.
TW: MOPS investor-conference announcements (法人說明會), last / current / next month.
Merged pairs (TSM->2330, ASX->3711) become one entry; ETFs are skipped (earnings/watchlist.json).
Dates are never guessed: symbols without a date are listed in problems.
Usage: python3 earnings/fetch_calendar.py
"""
import datetime, html, json, os, re, sys, time, urllib.parse, urllib.request
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "lib"))
import common as C

UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36"
NASDAQ = "https://api.nasdaq.com/api/calendar/earnings?date=%s"
MOPS = "https://mopsov.twse.com.tw/mops/web/ajax_t100sb02_1"
BACK, AHEAD, RECENT_DAYS = 3, 70, 3
TW_NAMES = {"2330": "台積電", "2454": "聯發科", "2317": "鴻海", "2382": "廣達", "2303": "聯電", "3711": "日月光投控"}


def get(url, data=None, headers=None, timeout=90):
    req = urllib.request.Request(url, data=data, headers={"User-Agent": UA, "Accept-Language": "zh-TW,zh;q=0.9,en;q=0.8", **(headers or {})})
    for i in range(3):
        try:
            return urllib.request.urlopen(req, timeout=timeout).read().decode("utf-8", "replace")
        except Exception as e:
            err = e
            time.sleep(3 * (i + 1))
    raise RuntimeError("%s：%s" % (url.split("?")[0], type(err).__name__))


def tw_today():
    return (datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(hours=8)).date()


def us_eastern_offset(d):
    """UTC offset of US Eastern time on date d (DST: 2nd Sunday of March to 1st Sunday of November)."""
    def nth_sunday(y, m, n):
        x = datetime.date(y, m, 1)
        x += datetime.timedelta(days=(6 - x.weekday()) % 7)
        return x + datetime.timedelta(weeks=n - 1)
    return -4 if nth_sunday(d.year, 3, 2) <= d < nth_sunday(d.year, 11, 1) else -5


def us_entries(symbols, problems):
    """Scan Nasdaq daily calendars; keep rows for our symbols."""
    found = {}
    today = tw_today()
    for k in range(-BACK - 1, AHEAD + 1):
        d = today + datetime.timedelta(days=k)
        if d.weekday() >= 5:
            continue
        try:
            js = json.loads(get(NASDAQ % d.isoformat(), headers={"Accept": "application/json"}))
        except Exception as e:
            problems.append("Nasdaq 財報日曆 %s 讀取失敗：%s" % (d, e))
            continue
        for r in ((js.get("data") or {}).get("rows") or []):
            s = (r.get("symbol") or "").upper()
            if s in symbols and s not in found:
                found[s] = (d, r)
        time.sleep(0.5)
    out = []
    for s, (d, r) in found.items():
        tcode = r.get("time") or ""
        off = us_eastern_offset(d)
        if "after" in tcode:  # after 16:00 ET -> next morning in Taiwan
            date_tw = d + datetime.timedelta(days=1)
            tw_time = "約 %02d:00 後（美股盤後公布）" % ((16 - off + 8) % 24)
        elif "pre" in tcode:  # before 09:30 ET -> Taiwan evening
            date_tw = d
            tw_time = "約 %02d:30 前（美股盤前公布）" % ((9 - off + 8) % 24)
        else:
            date_tw = d
            tw_time = "公司未提供時間"
        out.append({"ticker": s, "name": r.get("name"), "market": "美股", "period": "財報季末 %s" % r.get("fiscalQuarterEnding", "") if r.get("fiscalQuarterEnding") else None,
                    "event": "財報", "date": date_tw.isoformat(), "date_us": d.isoformat(), "time": tw_time,
                    "confirmed": "預估",  # Nasdaq does not say whether the company confirmed the date
                    "eps_forecast": r.get("epsForecast") or None,
                    "source": "https://www.nasdaq.com/market-activity/earnings"})
    return out


def tw_entries(codes, problems):
    """MOPS 法人說明會 list for last month, this month and next (ROC year)."""
    out, seen = [], set()
    today = tw_today()
    prev = (today.year - (today.month == 1), (today.month - 2) % 12 + 1)
    months = [prev, (today.year, today.month), ((today.year + (today.month == 12)), today.month % 12 + 1)]
    for y, m in months:
        try:
            body = urllib.parse.urlencode({"encodeURIComponent": 1, "step": 1, "firstin": 1, "off": 1, "TYPEK": "sii",
                                           "year": y - 1911, "month": "%02d" % m}).encode()
            page = get(MOPS, data=body)
        except Exception as e:
            problems.append("公開資訊觀測站法說會（%d-%02d）讀取失敗：%s" % (y, m, e))
            continue
        for row in re.findall(r"(?is)<tr[^>]*>(.*?)</tr>", page):
            cells = [html.unescape(re.sub(r"<[^>]+>", " ", c)).strip() for c in re.findall(r"(?is)<td[^>]*>(.*?)</td>", row)]
            cells = [re.sub(r"\s+", " ", c) for c in cells]
            if len(cells) < 3 or cells[0] not in codes:
                continue
            code = cells[0]
            dm = re.search(r"(\d{2,3})/(\d{1,2})/(\d{1,2})", " ".join(cells[2:4]))
            if not dm:
                continue
            d = datetime.date(int(dm.group(1)) + 1911, int(dm.group(2)), int(dm.group(3)))
            tm = re.search(r"\b(\d{1,2}:\d{2})\b", " ".join(cells[2:5]))
            key = (code, d)
            if key in seen:
                continue
            seen.add(key)
            q = (d.month - 1) // 3  # conference reports the previous quarter
            period = "%dQ%d" % (d.year, q) if q else "%dQ4" % (d.year - 1)
            desc = " ".join(cells[4:6])
            # The company's own quarterly conference uploads a new deck named <code><meeting date>M001.pdf;
            # broker forums reuse an older deck (or none) and usually say 受邀／參加.
            own_deck = ("%s%s" % (code, d.strftime("%Y%m%d"))) in " ".join(cells)
            hosted = bool(re.search(r"受邀|邀請", desc))
            own_words = bool(re.search(r"召開|自行舉辦|營運成果|財務業務|第.季", desc))
            invited = hosted or not (own_deck or own_words)
            out.append({"ticker": code, "name": cells[1] or TW_NAMES.get(code), "market": "台股", "period": None if invited else period,
                        "event": "受邀參加券商論壇" if invited else "法說會", "date": d.isoformat(), "time": tm.group(1) if tm else "公告未寫時間",
                        "confirmed": "公司已公告", "detail": desc[:300],
                        "source": "https://mops.twse.com.tw/mops/#/web/t100sb02_1"})
        time.sleep(2)
    return out


def main():
    wl = json.load(open(os.path.join(ROOT, "earnings/watchlist.json"), encoding="utf-8"))
    merge, skip = wl.get("merge", {}), set(wl.get("skip", []))
    us = [s for s in wl["us"] if s not in skip]
    problems = []
    us_rows = us_entries(set(us), problems)
    tw_rows = tw_entries(set(wl["tw"]), problems)
    rows = []
    by_tw = {r["ticker"]: r for r in tw_rows if r["event"] == "法說會"}
    for r in us_rows:
        tw = merge.get(r["ticker"])
        if tw:  # one entry per company: keep the Taiwan conference if we have it, else the ADR date
            r["merged_with"] = tw
            if tw in by_tw:
                by_tw[tw]["merged_with"] = r["ticker"]
                continue
            r["ticker"] = "%s／%s" % (tw, r["ticker"])
        rows.append(r)
    rows += tw_rows
    rows.sort(key=lambda r: (r["date"], r["ticker"]))
    today = tw_today()
    have = set()
    for r in rows:
        if r["event"] != "受邀參加券商論壇":
            have |= set(r["ticker"].split("／")) | ({r["merged_with"]} if r.get("merged_with") else set())
    for s in us + wl["tw"]:
        if s not in have and (merge.get(s) or s) not in have:
            problems.append("%s：%s 天內查不到財報或法說會日期（不估算）" % (s, AHEAD))
    lo = (today - datetime.timedelta(days=RECENT_DAYS - 1)).isoformat()
    recent = [r for r in rows if lo <= r["date"] <= today.isoformat() and r["event"] != "受邀參加券商論壇"]
    C.write_json("earnings/calendar.json", {
        "today_tw": today.isoformat(),
        "recent_rule": "最近 %d 天內（含今天，台灣時間）已召開或已公布" % RECENT_DAYS,
        "recent": recent, "upcoming": [r for r in rows if r["date"] > today.isoformat()], "all": rows,
        "notes": ["date 一律是台灣日期；美股盤後公布的財報，台灣日期是隔天早上",
                  "美股日期來自 Nasdaq 行事曆，不區分公司是否已確認，標為「預估」；台股來自公開資訊觀測站法說會公告，標為「公司已公告」",
                  "TSM 與 2330、ASX 與 3711 合併成一筆；SPY、SOXX、SOXL 是 ETF，略過",
                  "台股「受邀參加券商論壇」是公司受券商邀請說明已公開的資訊，不是季度法說會，不列入 recent；判斷方式：季度法說會會上傳當天日期的新簡報（代號＋日期 M001.pdf），沒有新簡報或寫明受邀／參加的都算論壇",
                  "台股季度法說會通常在財報公告前後；公開資訊觀測站只列已公告的場次，還沒公告的不會出現在這裡"]},
        problems, [{"name": "Nasdaq Earnings Calendar", "url": "https://www.nasdaq.com/market-activity/earnings"},
                   {"name": "公開資訊觀測站 法人說明會一覽表", "url": "https://mops.twse.com.tw/mops/#/web/t100sb02_1"}])
    print("calendar", len(rows), "rows; recent", len(recent), "; problems", len(problems))


if __name__ == "__main__":
    main()
