"""台股每日資料（證交所，上市全市場）。

輸出：
- tw/latest.csv   code,name,date,close,volume,high,low,pe,dy,pb,foreign,trust,dealer
- tw/revenue.csv  code,ym,revenue,yoy,ytd（只在每月 10～16 日更新）
- tw/meta.json    日期、筆數、單位、problems、sources

用法：
    python3 tw/fetch_tw.py             正式執行
    python3 tw/fetch_tw.py --dry-run   輸出到 .dryrun/tw/
    python3 tw/fetch_tw.py --if-stale  18:00 重試用：今天的資料已經抓到就直接結束
    python3 tw/fetch_tw.py --revenue   不論日期都抓月營收（測試或手動補抓用）
"""
import os, sys
sys.path.insert(1, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "lib"))
import common as C

MAX_BYTES = 90_000  # 90KB（以 90,000 bytes 計，保守）
URL_DAY = "https://openapi.twse.com.tw/v1/exchangeReport/STOCK_DAY_ALL"
URL_BW = "https://openapi.twse.com.tw/v1/exchangeReport/BWIBBU_ALL"
URL_T86 = "https://www.twse.com.tw/rwd/zh/fund/T86?date={ymd}&selectType=ALLBUT0999&response=json"
URL_REV = "https://openapi.twse.com.tw/v1/opendata/t187ap05_L"
HEADER = ["code", "name", "date", "close", "volume", "high", "low", "pe", "dy", "pb", "foreign", "trust", "dealer"]


def roc_date(s):
    """民國日期 1151120 → 2026-11-20"""
    s = s.strip()
    return "%04d-%s-%s" % (int(s[:-4]) + 1911, s[-4:-2], s[-2:])


def num(s):
    """'1,234.50' → 1234.5；空白、'--'、'-' 等無資料 → None"""
    s = (s or "").replace(",", "").strip()
    try:
        return float(s)
    except ValueError:
        return None


def fmt(v, nd=2):
    """數字轉短字串：去掉多餘的 0，None 變空白（不估算）"""
    if v is None:
        return ""
    s = ("%." + str(nd) + "f") % v
    return s.rstrip("0").rstrip(".") if "." in s else s


def lots(shares):
    """股 → 張（1 張 = 1,000 股），四捨五入到整數張"""
    return None if shares is None else int(round(shares / 1000.0))


def main():
    problems = []
    sources = [
        {"name": "證交所 OpenAPI 上市個股日成交資訊 STOCK_DAY_ALL", "url": URL_DAY},
        {"name": "證交所 OpenAPI 個股本益比、殖利率及股價淨值比 BWIBBU_ALL", "url": URL_BW},
        {"name": "證交所 三大法人買賣超日報 T86", "url": URL_T86.replace("{ymd}", "YYYYMMDD")},
    ]
    today = C.tw_today().isoformat()
    meta_old = C.read_json("tw/meta.json", {}) or {}
    if "--if-stale" in sys.argv and meta_old.get("date") == today:
        print("今天（%s）的資料已經抓到，略過重試" % today)
        return

    # 1) 日成交
    day = C.http_json(URL_DAY)
    if not day:
        raise SystemExit("STOCK_DAY_ALL 沒有資料")
    date = roc_date(day[0]["Date"])
    if date != today:
        problems.append("證交所最新資料日期 %s 不是今天 %s（可能尚未更新或休市）" % (date, today))
    rows = {}
    for r in day:
        if roc_date(r["Date"]) != date:
            continue
        rows[r["Code"].strip()] = {
            "code": r["Code"].strip(), "name": r["Name"].strip(), "date": date,
            "close": num(r["ClosingPrice"]), "volume": lots(num(r["TradeVolume"])),
            "high": num(r["HighestPrice"]), "low": num(r["LowestPrice"]),
            "value": num(r["TradeValue"]) or 0,
        }

    # 2) 本益比、殖利率、股價淨值比（日期要一致才採用，不一致就留空）
    try:
        bw = C.http_json(URL_BW)
        bw_date = roc_date(bw[0]["Date"]) if bw else None
        if bw_date != date:
            problems.append("BWIBBU_ALL 日期 %s 與成交資料 %s 不同，pe/dy/pb 留空" % (bw_date, date))
        else:
            for r in bw:
                x = rows.get(r["Code"].strip())
                if x:
                    x["pe"], x["dy"], x["pb"] = num(r["PEratio"]), num(r["DividendYield"]), num(r["PBratio"])
    except Exception as e:
        problems.append("BWIBBU_ALL 抓取失敗：%s" % e)

    # 3) 三大法人（單位：張）
    try:
        t = C.http_json(URL_T86.format(ymd=date.replace("-", "")))
        if t.get("stat") != "OK":
            problems.append("T86 三大法人 %s 沒有資料：%s" % (date, t.get("stat")))
        else:
            f = t["fields"]
            i_code = f.index("證券代號")
            i_fx = f.index("外陸資買賣超股數(不含外資自營商)")
            i_fxd = f.index("外資自營商買賣超股數")
            i_tr = f.index("投信買賣超股數")
            i_dl = f.index("自營商買賣超股數")
            for d in t["data"]:
                x = rows.get(d[i_code].strip())
                if x:
                    fx, fxd = num(d[i_fx]), num(d[i_fxd])
                    x["foreign"] = lots(None if fx is None else fx + (fxd or 0))
                    x["trust"], x["dealer"] = lots(num(d[i_tr])), lots(num(d[i_dl]))
    except Exception as e:
        problems.append("T86 三大法人抓取失敗：%s" % e)

    # 4) 控制檔案大小：一般股票（4 碼）優先，其餘（ETF 等）依成交金額由大到小，加到 90KB 為止
    order = sorted(rows.values(), key=lambda x: (not (len(x["code"]) == 4 and x["code"].isdigit()), -x["value"]))
    def line(x):
        return [x["code"], x["name"], x["date"], fmt(x["close"]), "" if x["volume"] is None else str(x["volume"]),
                fmt(x["high"]), fmt(x["low"]), fmt(x.get("pe")), fmt(x.get("dy")), fmt(x.get("pb")),
                "" if x.get("foreign") is None else str(x["foreign"]),
                "" if x.get("trust") is None else str(x["trust"]),
                "" if x.get("dealer") is None else str(x["dealer"])]
    out, size = [], len(",".join(HEADER).encode()) + 1
    for x in order:
        l = line(x)
        b = len(",".join(l).encode("utf-8")) + 1
        if size + b > MAX_BYTES - 512:  # 留一點空間給 CSV 引號
            break
        out.append(l)
        size += b
    omitted = len(order) - len(out)
    if omitted:
        problems.append("為控制 tw/latest.csv 在 90KB 內，省略成交金額最小的 %d 檔（非一般股票優先省略）" % omitted)
    out.sort(key=lambda l: l[0])
    path = C.write_csv("tw/latest.csv", HEADER, out)
    real_size = os.path.getsize(path)

    # 5) 月營收：只在每月 10～16 日抓
    rev_info = {"updated": False}
    day_of_month = C.tw_today().day
    if 10 <= day_of_month <= 16 or "--revenue" in sys.argv:
        sources.append({"name": "證交所 OpenAPI 上市公司每月營業收入彙總表 t187ap05_L", "url": URL_REV})
        try:
            rev = C.http_json(URL_REV)
            rrows = []
            for r in rev:
                ym_roc = r["資料年月"].strip()
                ym = "%04d-%s" % (int(ym_roc[:-2]) + 1911, ym_roc[-2:])
                rrows.append([r["公司代號"].strip(), ym, fmt(num(r["營業收入-當月營收"]), 0),
                              fmt(num(r["營業收入-去年同月增減(%)"]), 2), fmt(num(r["累計營業收入-當月累計營收"]), 0)])
            rrows.sort()
            C.write_csv("tw/revenue.csv", ["code", "ym", "revenue", "yoy", "ytd"], rrows)
            rev_info = {"updated": True, "rows": len(rrows), "ym": sorted({r[1] for r in rrows})}
        except Exception as e:
            problems.append("月營收 t187ap05_L 抓取失敗：%s" % e)
    else:
        rev_info["note"] = "非月營收抓取期間（每月 10～16 日），tw/revenue.csv 維持上次內容"
        if meta_old.get("revenue"):
            rev_info["last"] = meta_old["revenue"]

    C.write_json("tw/meta.json", {
        "date": date,
        "rows": len(out),
        "omitted": omitted,
        "latest_csv_bytes": real_size,
        "units": {
            "close/high/low": "元", "volume": "張（1 張 = 1,000 股）",
            "pe": "本益比（倍）", "dy": "殖利率（%）", "pb": "股價淨值比（倍）",
            "foreign": "外資及陸資買賣超（張，含外資自營商）", "trust": "投信買賣超（張）", "dealer": "自營商買賣超（張）",
            "revenue/ytd": "千元（證交所原始單位）", "yoy": "去年同月增減（%）",
        },
        "revenue": rev_info,
    }, problems, sources)
    print("date=%s rows=%d omitted=%d bytes=%d problems=%s" % (date, len(out), omitted, real_size, problems))


if __name__ == "__main__":
    main()
