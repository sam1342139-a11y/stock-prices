"""每日抓取總經數據，寫入 macro/macro.json。

資料來源：
- FRED（美國聯準會聖路易分行資料庫）：免金鑰
- Twelve Data：美元兌台幣即時匯率（有 TWELVEDATA_KEY 才抓，沒有就跳過）
"""
import csv, datetime, io, json, os, sys, urllib.request, urllib.parse

OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "macro.json")
KEEP = 30  # 每個指標保留最近幾筆歷史資料

# (FRED 代號, 中文名稱, 單位, 說明)
FRED_SERIES = [
    ("DFF",      "聯邦基金有效利率", "%",   "美國聯準會政策利率的實際水準"),
    ("DGS2",     "美國 2 年期公債殖利率", "%", "反映市場對未來升降息的預期"),
    ("DGS10",    "美國 10 年期公債殖利率", "%", "長期利率指標，影響股市估值與房貸"),
    ("T10Y2Y",   "10 年減 2 年利差", "百分點", "負值代表殖利率倒掛，常被視為衰退警訊"),
    ("VIXCLS",   "VIX 恐慌指數", "點",  "20 以下偏平靜，30 以上代表市場恐慌"),
    ("CPIAUCSL", "美國 CPI 消費者物價指數", "指數", "每月公布，看年增率判斷通膨"),
    ("UNRATE",   "美國失業率", "%",    "每月公布，就業市場冷熱指標"),
    ("DEXTAUS",  "美元兌台幣（FRED）", "台幣", "每週更新，較即時匯率晚幾天"),
]


def get(url, headers=None):
    req = urllib.request.Request(url, headers=headers or {"User-Agent": "stock-prices-bot"})
    with urllib.request.urlopen(req, timeout=60) as r:
        return r.read().decode("utf-8")


def fred(series_id, start):
    q = urllib.parse.urlencode({"id": series_id, "cosd": start})
    text = get("https://fred.stlouisfed.org/graph/fredgraph.csv?" + q)
    rows = []
    for row in csv.reader(io.StringIO(text)):
        if len(row) != 2 or row[0] in ("DATE", "observation_date"):
            continue
        try:
            rows.append((row[0], float(row[1])))
        except ValueError:  # FRED 用 "." 表示休市無資料
            continue
    return rows


def usdtwd_live():
    key = os.environ.get("TWELVEDATA_KEY", "").strip()
    if not key:
        return None
    q = urllib.parse.urlencode({"symbol": "USD/TWD", "interval": "1day", "outputsize": KEEP})
    data = json.loads(get("https://api.twelvedata.com/time_series?" + q,
                          {"Authorization": "apikey " + key, "User-Agent": "stock-prices-bot"}))
    if data.get("status") != "ok":
        raise RuntimeError(data.get("message"))
    return [(v["datetime"], round(float(v["close"]), 4)) for v in reversed(data["values"])]


def summarize(name, unit, note, rows):
    last_date, last = rows[-1]
    prev = rows[-2][1] if len(rows) > 1 else None
    return {
        "name": name, "unit": unit, "note": note,
        "date": last_date, "value": last,
        "prev": prev,
        "change": round(last - prev, 4) if prev is not None else None,
        "history": {d: v for d, v in rows[-KEEP:]},
    }


def main():
    today = datetime.date.today()
    start = (today - datetime.timedelta(days=500)).isoformat()  # 抓一年多，才能算 CPI 年增率
    out, problems = {}, []

    for sid, name, unit, note in FRED_SERIES:
        try:
            rows = fred(sid, start)
            if not rows:
                raise RuntimeError("沒有資料")
            item = summarize(name, unit, note, rows)
            if sid == "CPIAUCSL" and len(rows) >= 13:
                item["yoy_pct"] = round((rows[-1][1] / rows[-13][1] - 1) * 100, 2)
                item["note"] += f"；最新年增率 {item['yoy_pct']}%"
            out[sid] = item
        except Exception as e:
            problems.append(f"{sid}: {e}")

    try:
        rows = usdtwd_live()
        if rows:
            out["USDTWD"] = summarize("美元兌台幣", "台幣", "Twelve Data 每日收盤匯率", rows)
    except Exception as e:
        problems.append(f"USDTWD: {e}")

    result = {
        "fetched_at_utc": datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%d %H:%M:%S"),
        "problems": problems,
        "indicators": out,
    }
    with open(OUT, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=1)
    print("indicators=%d problems=%s" % (len(out), problems))
    if not out:
        sys.exit(1)


if __name__ == "__main__":
    main()
