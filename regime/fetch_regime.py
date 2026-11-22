"""市場風險燈號。規則完整寫在 docs/REGIME.md，這裡的門檻要和文件一致。

每項 0／1／2 分（綠／黃／紅），附數值、日期、門檻。總分 0～3 綠、4～6 黃、7 以上紅。
抓不到的項目不估算：該項 score 為 null、不計入總分，原因寫進 problems。

輸出：
- regime/regime.json   本次結果
- regime/history.csv   每天一行（同一天重跑會覆蓋該行）
- regime/spy_history.csv  SPY 日收盤（至少 200 個交易日，算 200 日均線用）

用法：python3 regime/fetch_regime.py [--dry-run]
"""
import csv, datetime, io, math, os, sys
sys.path.insert(1, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "lib"))
import common as C

CBOE_VIX = "https://cdn-api.cboe.com/api/global/us_indices/daily_prices/VIX_History.csv"
FRED_URL = "https://fred.stlouisfed.org/series/"
SPY_KEEP = 320          # SPY 至少 220 天（200 日均線 + 20 天斜率），多存一些
MA_SLOPE_FLAT = 0.1     # 200 日均線 20 個交易日內上升超過 0.1% 才算「上升」
COLORS = {0: "綠", 1: "黃", 2: "紅"}
ITEMS = ["vix", "spy_ma200", "t10y3m", "hy_spread", "recession_prob", "sahm", "soxx_vs_spy"]


def item(name, value, date, score, threshold, source, extra=None):
    d = {"name": name, "value": value, "date": date, "score": score,
         "color": COLORS.get(score), "threshold": threshold, "source": source}
    if extra:
        d.update(extra)
    return d


def missing(name, threshold, source, reason, problems, key):
    problems.append("%s：%s" % (name, reason))
    return item(name, None, None, None, threshold, source)


def vix_series():
    rows = []
    for r in csv.DictReader(io.StringIO(C.http_get(CBOE_VIX))):
        try:
            d = datetime.datetime.strptime(r["DATE"].strip(), "%m/%d/%Y").date().isoformat()
            rows.append((d, round(float(r["CLOSE"]), 2)))
        except (KeyError, ValueError):
            continue
    return sorted(rows), "CBOE 官方 VIX 每日收盤"


def td_closes(symbol, n):
    data = C.twelvedata("time_series", symbol=symbol, interval="1day", outputsize=n)
    return sorted((v["datetime"][:10], float(v["close"])) for v in data.get("values", []))


def phi(x):
    return 0.5 * (1 + math.erf(x / math.sqrt(2)))


def main():
    problems, items = [], {}
    sources = [
        {"name": "CBOE VIX 每日收盤歷史檔", "url": CBOE_VIX},
        {"name": "FRED VIXCLS（CBOE 抓不到時備援）", "url": FRED_URL + "VIXCLS"},
        {"name": "Twelve Data SPY、SOXX 日收盤", "url": "https://api.twelvedata.com/time_series"},
        {"name": "FRED T10Y3M 10 年減 3 個月公債利差", "url": FRED_URL + "T10Y3M"},
        {"name": "FRED BAMLH0A0HYM2 高收益債選擇權調整利差", "url": FRED_URL + "BAMLH0A0HYM2"},
        {"name": "FRED UNRATE 失業率", "url": FRED_URL + "UNRATE"},
        {"name": "紐約聯準會殖利率曲線衰退機率模型（公式）", "url": "https://www.newyorkfed.org/research/capital_markets/ycfaq"},
    ]
    start2y = (C.tw_today() - datetime.timedelta(days=760)).isoformat()

    # 1) VIX
    th = "<18 綠；18～25 黃；>25 紅"
    try:
        try:
            rows, src = vix_series()
        except Exception as e:
            problems.append("CBOE VIX 抓不到，改用 FRED：%s" % e)
            rows, src = C.fred("VIXCLS", start2y), "FRED VIXCLS"
        d, v = rows[-1]
        items["vix"] = item("VIX 恐慌指數", v, d, 0 if v < 18 else (1 if v <= 25 else 2), th, src)
    except Exception as e:
        items["vix"] = missing("VIX 恐慌指數", th, "CBOE／FRED", "抓取失敗 %s" % e, problems, "vix")

    # 2) SPY 相對 200 日均線
    th = ("綠：在均線之上且均線上升；黃：在均線之上但均線走平或下降，或低於均線 0～3%%；紅：低於均線超過 3%%"
          "（均線上升 = 200 日均線比 20 個交易日前高 %.1f%% 以上）" % MA_SLOPE_FLAT)
    hist = {r["date"]: float(r["close"]) for r in C.read_csv("regime/spy_history.csv")}
    spy_rows = sorted(hist.items())
    try:
        new = td_closes("SPY", SPY_KEEP if len(hist) < 220 else 15)
        hist.update(new)
        spy_rows = sorted(hist.items())[-SPY_KEEP:]
        C.write_csv("regime/spy_history.csv", ["date", "close"], [[d, "%g" % v] for d, v in spy_rows])
    except Exception as e:
        problems.append("SPY 抓取失敗，沿用已存的歷史：%s" % e)
    if len(spy_rows) >= 220:
        closes = [v for _, v in spy_rows]
        ma = sum(closes[-200:]) / 200
        ma_prev = sum(closes[-220:-20]) / 200
        dist = (closes[-1] / ma - 1) * 100
        slope = (ma / ma_prev - 1) * 100
        rising = slope > MA_SLOPE_FLAT
        score = 0 if dist >= 0 and rising else (1 if dist >= -3 else 2)
        items["spy_ma200"] = item("SPY 相對 200 日均線", round(dist, 2), spy_rows[-1][0], score, th, "Twelve Data SPY",
                                  {"unit": "%（SPY 高於均線的幅度）", "spy": closes[-1], "ma200": round(ma, 2),
                                   "ma200_20d_change_pct": round(slope, 2), "ma200_rising": rising})
    else:
        items["spy_ma200"] = missing("SPY 相對 200 日均線", th, "Twelve Data SPY",
                                     "SPY 歷史只有 %d 天，不足 220 天" % len(spy_rows), problems, "spy_ma200")

    # 3) 10 年減 3 個月利差（也用在第 5 項）
    th = ">0.5 綠；0～0.5 黃；<0 紅"
    t10y3m = []
    try:
        t10y3m = C.fred("T10Y3M", start2y)
        d, v = t10y3m[-1]
        items["t10y3m"] = item("10 年減 3 個月利差", v, d, 0 if v > 0.5 else (1 if v >= 0 else 2), th, "FRED T10Y3M",
                               {"unit": "百分點"})
    except Exception as e:
        items["t10y3m"] = missing("10 年減 3 個月利差", th, "FRED T10Y3M", "抓取失敗 %s" % e, problems, "t10y3m")

    # 4) 高收益債利差
    th = "<4 綠；4～5.5 黃；>5.5 紅"
    try:
        d, v = C.fred("BAMLH0A0HYM2", start2y)[-1]
        items["hy_spread"] = item("高收益債利差", v, d, 0 if v < 4 else (1 if v <= 5.5 else 2), th,
                                  "FRED BAMLH0A0HYM2", {"unit": "百分點"})
    except Exception as e:
        items["hy_spread"] = missing("高收益債利差", th, "FRED BAMLH0A0HYM2", "抓取失敗 %s" % e, problems, "hy_spread")

    # 5) 12 個月衰退機率（紐約聯準會 probit），用最近一個「完整月份」的 T10Y3M 月平均
    th = "P = Φ(−0.5333 − 0.6330 × T10Y3M 月平均)；<20% 綠；20～35% 黃；>35% 紅"
    this_month = C.tw_today().strftime("%Y-%m")
    months = {}
    for d, v in t10y3m:
        months.setdefault(d[:7], []).append(v)
    done = sorted(m for m in months if m < this_month)
    if done:
        m = done[-1]
        avg = sum(months[m]) / len(months[m])
        p = phi(-0.5333 - 0.6330 * avg) * 100
        items["recession_prob"] = item("12 個月衰退機率", round(p, 1), m, 0 if p < 20 else (1 if p <= 35 else 2), th,
                                       "依 FRED T10Y3M 計算", {"unit": "%", "t10y3m_month_avg": round(avg, 3)})
    else:
        items["recession_prob"] = missing("12 個月衰退機率", th, "依 FRED T10Y3M 計算", "沒有完整月份的 T10Y3M", problems, "recession_prob")

    # 6) Sahm 規則
    th = "近 3 月平均失業率 − 前 12 個月中最低的 3 月平均；<0.3 綠；0.3～0.5 黃；≥0.5 紅"
    try:
        un = C.fred("UNRATE", (C.tw_today() - datetime.timedelta(days=800)).isoformat())
        ma3 = [(un[i][0], sum(x for _, x in un[i - 2:i + 1]) / 3) for i in range(2, len(un))]
        if len(ma3) < 13:
            raise RuntimeError("UNRATE 資料不足 15 個月")
        cur = ma3[-1][1]
        low = min(x for _, x in ma3[-13:-1])
        v = round(cur - low, 2)
        items["sahm"] = item("Sahm 規則", v, ma3[-1][0][:7], 0 if v < 0.3 else (1 if v < 0.5 else 2), th, "FRED UNRATE",
                             {"unit": "百分點", "unrate_3m_avg": round(cur, 2), "prior_12m_low": round(low, 2)})
    except Exception as e:
        items["sahm"] = missing("Sahm 規則", th, "FRED UNRATE", "計算失敗 %s" % e, problems, "sahm")

    # 7) SOXX 相對 SPY 近 20 日報酬
    th = "SOXX 20 日報酬 − SPY 20 日報酬；>0 綠；−5%～0 黃；<−5% 紅"
    try:
        sx = td_closes("SOXX", 30)
        sp = dict(spy_rows)
        common_d = [d for d, _ in sx if d in sp]
        if len(common_d) < 21:
            raise RuntimeError("SOXX 與 SPY 共同交易日不足 21 天")
        sxd = dict(sx)
        d1, d0 = common_d[-1], common_d[-21]
        r_sx = (sxd[d1] / sxd[d0] - 1) * 100
        r_sp = (sp[d1] / sp[d0] - 1) * 100
        v = round(r_sx - r_sp, 2)
        items["soxx_vs_spy"] = item("SOXX 相對 SPY 近 20 日", v, d1, 0 if v > 0 else (1 if v >= -5 else 2), th,
                                    "Twelve Data SOXX、SPY",
                                    {"unit": "百分點", "soxx_20d_pct": round(r_sx, 2), "spy_20d_pct": round(r_sp, 2), "from": d0})
    except Exception as e:
        items["soxx_vs_spy"] = missing("SOXX 相對 SPY 近 20 日", th, "Twelve Data SOXX、SPY", "計算失敗 %s" % e, problems, "soxx_vs_spy")

    # 總分與轉色
    scored = {k: v["score"] for k, v in items.items() if v["score"] is not None}
    total = sum(scored.values())
    level = "綠" if total <= 3 else ("黃" if total <= 6 else "紅")
    today = C.tw_today().isoformat()
    hist_rows = [r for r in C.read_csv("regime/history.csv") if r.get("date") != today]
    prev = hist_rows[-1] if hist_rows else None
    turned_yellow, turned_red = [], []
    if prev:
        for k, s in scored.items():
            try:
                ps = int(prev.get(k + "_score", ""))
            except ValueError:
                continue
            if s > ps and s == 1:
                turned_yellow.append(items[k]["name"])
            if s > ps and s == 2:
                turned_red.append(items[k]["name"])

    C.write_json("regime/regime.json", {
        "date_tw": today,
        "total": total, "level": level, "max_possible": 2 * len(scored), "items_scored": len(scored),
        "rule": "每項 0 綠／1 黃／2 紅；總分 0～3 綠、4～6 黃、7 以上紅。規則見 docs/REGIME.md",
        "compared_with": prev["date"] if prev else None,
        "turned_yellow": turned_yellow, "turned_red": turned_red,
        "items": items,
    }, problems, sources)

    header = ["date", "total", "level"] + [x for k in ITEMS for x in (k, k + "_score")]
    row = {"date": today, "total": total, "level": level}
    for k in ITEMS:
        row[k] = "" if items[k]["value"] is None else items[k]["value"]
        row[k + "_score"] = "" if items[k]["score"] is None else items[k]["score"]
    all_rows = [[r.get(h, "") for h in header] for r in hist_rows] + [[row[h] for h in header]]
    C.write_csv("regime/history.csv", header, all_rows)
    print("total=%d level=%s turned_yellow=%s turned_red=%s problems=%s" % (total, level, turned_yellow, turned_red, problems))
    for k in ITEMS:
        it = items[k]
        print("  %s %s = %s（%s）" % (it["color"] or "—", it["name"], it["value"], it["date"]))


if __name__ == "__main__":
    main()
