"""Acceptance spot-check: compare stored data with TWSE website for a few days (few requests, paced).

Checks:
  1) 2330 daily closes for a sample month (TWSE STOCK_DAY) vs tw-models/data/prices/2330
  2) Ex-dividend records (TWSE TWT49U) vs our adjustment factors for 2330 and 0050
Prints a readable table to the workflow log. Usage: python3 tw-models/spot_check.py
"""
import os, re, sys, time
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(1, os.path.join(os.path.dirname(HERE), "lib"))
import common as C
import twdata as T

CHECKS = [("2330", "20240501"), ("2330", "20260901"), ("0050", "20250601")]
EXDIV = [("2330", "20260901", "20260930"), ("0050", "20250101", "20250131"), ("0050", "20260701", "20260731")]


def roc(s):
    """ROC date '115/09/01' or '115年09月01日' -> '2026-09-01'."""
    y, m, d = re.findall(r"\d+", s)[:3]
    return "%04d-%02d-%02d" % (int(y) + 1911, int(m), int(d))


def num(s):
    try:
        return float(s.replace(",", ""))
    except ValueError:
        return None


def main():
    bad = 0
    print("=== 1) 每日收盤價：證交所 STOCK_DAY vs 本系統 ===")
    for code, ymd in CHECKS:
        j = C.http_json("https://www.twse.com.tw/rwd/zh/afterTrading/STOCK_DAY?date=%s&stockNo=%s&response=json" % (ymd, code))
        time.sleep(4)
        if j.get("stat") != "OK":
            print(code, ymd, "證交所沒有回傳資料：", j.get("stat")); bad += 1; continue
        s = T.prices(code)
        for row in j["data"][:5]:
            d, close = roc(row[0]), num(row[6])
            i = s.idx.get(d)
            ours = s.close[i] if i is not None else None
            ok = ours is not None and abs(ours - close) < 1e-6
            bad += not ok
            print("%s %s 證交所收盤 %s｜本系統 %s｜%s" % (code, d, close, ours, "一致" if ok else "不一致"))
    print("\n=== 2) 除權息：證交所 TWT49U vs 本系統還原係數 ===")
    for code, a, b in EXDIV:
        j = C.http_json("https://www.twse.com.tw/rwd/zh/exRight/TWT49U?startDate=%s&endDate=%s&response=json" % (a, b))
        time.sleep(4)
        f = j.get("fields") or []
        for row in j.get("data") or []:
            if row[1].strip() != code:
                continue
            d = roc(row[0])
            before, ref = num(row[3]), num(row[4])
            tw_factor = ref / before
            s = T.prices(code)
            i = s.idx.get(d)
            ours = s.factor[i] if i is not None else None
            ok = ours is not None and abs(ours - tw_factor) < 1e-4
            bad += not ok
            print("%s 除權息日 %s 除權息前收盤 %s 參考價 %s 權息值 %s｜係數 證交所 %.6f 本系統 %s｜%s" % (
                code, d, before, ref, row[5], tw_factor, "%.6f" % ours if ours else None, "一致" if ok else "不一致"))
    print("\n不一致筆數：%d" % bad)
    sys.exit(1 if bad else 0)


if __name__ == "__main__":
    main()
