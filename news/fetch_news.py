"""News headline pre-screen for the FCN morning update: news/raw.json (titles only, no article text).

Sources (public feeds reachable from GitHub Actions):
  鉅亨網 news API (美股 / 台股 / 外匯 categories), 中央社財經 RSS, CNBC RSS (Top News, Markets), MarketWatch RSS.
Window: from the previous US trading session to now (Taiwan time). Titles mentioning one of the 26 tickers
(code or name, news/aliases.json) get a `tickers` field. movers = 26 tickers moving more than 5% (latest.json, last two days).
Usage: python3 news/fetch_news.py
"""
import datetime, email.utils, html, json, os, re, sys, time, urllib.request
import xml.etree.ElementTree as ET
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "lib"))
import common as C

UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36"
TZ = datetime.timezone(datetime.timedelta(hours=8))
CNYES = "https://api.cnyes.com/media/api/v1/newslist/category/%s?limit=30&page=%d"
CNYES_CATS = [("us_stock", "鉅亨網 美股"), ("tw_stock", "鉅亨網 台股"), ("forex", "鉅亨網 外匯")]
RSS = [("https://feeds.feedburner.com/rsscna/finance", "中央社 財經"),
       ("https://www.cnbc.com/id/100003114/device/rss/rss.html", "CNBC Top News"),
       ("https://www.cnbc.com/id/20910258/device/rss/rss.html", "CNBC Markets"),
       ("https://feeds.content.dowjones.io/public/rss/mw_topstories", "MarketWatch Top Stories")]
MOVE_PCT = 5.0


def get(url):
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept-Language": "zh-TW,zh;q=0.9,en;q=0.8"})
    for i in range(3):
        try:
            return urllib.request.urlopen(req, timeout=60).read()
        except Exception as e:
            err = e
            time.sleep(3 * (i + 1))
    raise RuntimeError(type(err).__name__)


def window_start(now):
    """Start of the window: 06:00 Taiwan on the day the previous US session opened (covers the whole session).
    Tue-Sat morning -> previous calendar day 06:00; Sun/Mon -> Friday 06:00."""
    d = now.date()
    back = {0: 3, 6: 2}.get(d.weekday(), 1)
    return datetime.datetime.combine(d - datetime.timedelta(days=back), datetime.time(6, 0), TZ)


def matcher():
    al = json.load(open(os.path.join(ROOT, "news/aliases.json"), encoding="utf-8"))["aliases"]
    pats = {}
    for code, names in al.items():
        parts = [r"\(%s-US\)" % re.escape(code)]
        if len(code) >= 3:
            parts.append(r"(?<![A-Za-z])%s(?![A-Za-z])" % re.escape(code))
        for n in names:
            parts.append(re.escape(n) if re.search(r"[^\x00-\x7f]", n) else r"(?<![A-Za-z])%s(?![A-Za-z])" % re.escape(n))
        pats[code] = re.compile("|".join(parts))
    return lambda title: sorted(c for c, p in pats.items() if p.search(title))


def cnyes(cat, label, since, problems):
    out = []
    for page in range(1, 6):
        try:
            js = json.loads(get(CNYES % (cat, page)))
        except Exception as e:
            problems.append("%s 讀取失敗：%s" % (label, e))
            break
        rows = (js.get("items") or {}).get("data") or []
        if not rows:
            break
        for r in rows:
            t = datetime.datetime.fromtimestamp(int(r.get("publishAt") or 0), TZ)
            if t >= since:
                out.append({"title": html.unescape(r.get("title") or "").strip(), "url": "https://news.cnyes.com/news/id/%s" % r.get("newsId"),
                            "source": label, "published_tw": t.strftime("%Y-%m-%d %H:%M")})
        if datetime.datetime.fromtimestamp(int(rows[-1].get("publishAt") or 0), TZ) < since:
            break
        time.sleep(1)
    return out


def rss(url, label, since, problems):
    try:
        root = ET.fromstring(get(url))
    except Exception as e:
        problems.append("%s 讀取失敗：%s" % (label, e))
        return []
    out = []
    for it in root.iter("item"):
        title, link, pub = it.findtext("title"), it.findtext("link"), it.findtext("pubDate")
        try:
            t = email.utils.parsedate_to_datetime(pub).astimezone(TZ)
        except (TypeError, ValueError):
            continue
        if title and t >= since:
            out.append({"title": html.unescape(title).strip(), "url": (link or "").strip(), "source": label, "published_tw": t.strftime("%Y-%m-%d %H:%M")})
    return out


def movers(problems):
    try:
        d = json.load(open(os.path.join(ROOT, "latest.json"), encoding="utf-8"))
        days = sorted(d["history"])
        a, b = d["history"][days[-2]], d["history"][days[-1]]
    except (OSError, KeyError, IndexError, ValueError):
        problems.append("latest.json 讀不到最後兩天價格，無法列 movers")
        return None, []
    out = [{"ticker": k, "date": days[-1], "prev_close": a[k], "close": b[k], "change_pct": round((b[k] / a[k] - 1) * 100, 2)}
           for k in sorted(b) if a.get(k) and b.get(k) and abs(b[k] / a[k] - 1) * 100 > MOVE_PCT]
    out.sort(key=lambda x: -abs(x["change_pct"]))
    return days[-1], out


TW_STOCKS = "news/tw_stocks.json"
TW_KEEP_DAYS = 7


def tw_stock_names():
    """{code: name} of the 33 large caps + 0050 (public fixed list) from the committed model outputs."""
    for rel, key in (("tw-models/latest/stock_analysis.json", "stocks"), ("tw-models/latest/old_screen.json", "list")):
        try:
            d = json.load(open(os.path.join(ROOT, rel), encoding="utf-8"))
        except (OSError, ValueError):
            continue
        rows = d[key].values() if isinstance(d[key], dict) else d[key]
        names = {r["code"]: r.get("name") for r in rows if r.get("name")}
        if names:
            names.setdefault("0050", "元大台灣50")
            return names
    return {}


def tw_stock_news(items, now, problems):
    """Rolling 7-day headlines that mention one of the 33 large caps / 0050 (title + link only)."""
    names = tw_stock_names()
    if not names:
        problems.append("讀不到 33 檔名單，台股個股新聞未更新")
        return
    pats = {c: re.compile(r"%s|\(%s-TW\)|(?<![0-9])%s(?![0-9])" % (re.escape(n), c, c)) for c, n in names.items()}
    path = os.path.join(ROOT, TW_STOCKS)
    try:
        old = json.load(open(path, encoding="utf-8")).get("by_code", {})
    except (OSError, ValueError):
        old = {}
    cutoff = (now - datetime.timedelta(days=TW_KEEP_DAYS)).strftime("%Y-%m-%d %H:%M")
    by = {c: [x for x in old.get(c, []) if x["published_tw"] >= cutoff] for c in names}
    for x in items:
        if x["source"] not in ("鉅亨網 台股", "中央社 財經"):
            continue
        for c, p in pats.items():
            if p.search(x["title"]) and all(y["url"] != x["url"] for y in by[c]):
                by[c].append({k: x[k] for k in ("title", "url", "source", "published_tw")})
    for c in by:
        by[c] = sorted(by[c], key=lambda x: x["published_tw"], reverse=True)[:20]
    C.write_json(TW_STOCKS, {"keep_days": TW_KEEP_DAYS, "names": names, "by_code": by,
                             "notes": ["33 檔大型股＋0050 近 7 天的新聞標題（鉅亨網台股、中央社財經），只存標題與連結；用公司名稱或代號比對標題，可能有少數誤判"]},
                 [], [{"name": "鉅亨網", "url": "https://news.cnyes.com/"}, {"name": "中央社 財經", "url": "https://www.cna.com.tw/list/aie.aspx"}])


def main():
    now = datetime.datetime.now(TZ)
    since = window_start(now)
    problems, items = [], []
    for cat, label in CNYES_CATS:
        items += cnyes(cat, label, since, problems)
    for url, label in RSS:
        items += rss(url, label, since, problems)
    seen, uniq = set(), []
    for x in sorted(items, key=lambda x: x["published_tw"], reverse=True):
        k = x["url"] or x["title"]
        if k not in seen:
            seen.add(k)
            uniq.append(x)
    match = matcher()
    for x in uniq:
        t = match(x["title"])
        if t:
            x["tickers"] = t
    tw_stock_news(uniq, now, problems)
    asof, mv = movers(problems)
    C.write_json("news/raw.json", {
        "window_tw": [since.strftime("%Y-%m-%d %H:%M"), now.strftime("%Y-%m-%d %H:%M")],
        "count": len(uniq), "count_with_tickers": sum(1 for x in uniq if x.get("tickers")),
        "movers_rule": "26 檔在 %s 單日漲跌超過 %.0f%%（latest.json 最後兩天收盤）" % (asof, MOVE_PCT), "movers": mv,
        "items": uniq,
        "notes": ["只存標題、連結、來源、發布時間（台灣時間），不存內文；要看內容請開連結",
                  "tickers 是用代號或公司名稱比對標題得到，可能有少數誤判（例如「蘋果」指水果）"]},
        problems, [{"name": label, "url": url.split("?")[0]} for url, label in RSS] +
                  [{"name": "鉅亨網", "url": "https://news.cnyes.com/"}])
    print("news", len(uniq), "items;", sum(1 for x in uniq if x.get("tickers")), "with tickers; movers", len(mv), "; problems", problems)


if __name__ == "__main__":
    main()
