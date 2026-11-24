"""Data sanity checks for tw-models, run before computed outputs are committed (rules: docs/DATA_CHECKS.md).

  python3 tw-models/sanity.py check --out <report.json>   run all checks, write {ok, date, problems}; always exits 0
  python3 tw-models/sanity.py mark  --report <report.json> after the previous outputs were restored, add the failure
                                                            reason to each output file's `problems` (nothing else changes)

The workflow keeps yesterday's outputs (git checkout HEAD) when a check fails, marks them, commits, and opens an issue.
"""
import argparse, datetime, glob, json, os, re, subprocess, sys
HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, HERE)
sys.path.insert(1, os.path.join(ROOT, "lib"))
import twdata as T

LIMITS = {
    "index_vs_ma200_pct": 40,      # TAIEX more than ±40% away from its 200-day average
    "index_day_pct": 12,           # TAIEX daily change over ±12%
    "stock_day_pct": 11,           # stock daily change over ±11% (price limit is 10%) with no corporate action
    "stock_day_min_count": 3,      # ...blocks publishing only when this many stocks do it on the same day (1-2 = a missing ex-rights record, noted)
    "foreign_vs_record_x": 2,      # foreign daily net buy/sell over 2x the largest one on record
    "fx_day_pct": 3,               # USD/TWD daily change over 3%
}
DAILY_FILE = re.compile(r"^(prices|per|inst|revenue)_\d{4}-\d{2}\.csv$|^market_(taiex|taiex_tri|inst_total|margin_total)_\d{4}-\d{2}\.csv$")
OUTPUTS = sorted(glob.glob(os.path.join(ROOT, "tw-models", "latest", "*.json"))) + [os.path.join(ROOT, "tw-models", "paper", "latest.json")]


def num(x):
    try:
        return float(x)
    except (TypeError, ValueError):
        return None


def series(name, field="close"):
    rows = T.market(name)
    return [(d, num(rows[d].get(field))) for d in sorted(rows)]


def check_index(problems):
    s = series("taiex")
    if not s:
        problems.append("讀不到加權指數資料")
        return None
    d, last = s[-1]
    if not last:
        problems.append("加權指數 %s 收盤為 0 或空值" % d)
        return d
    closes = [v for _, v in s[-200:] if v]
    if len(closes) == 200:
        dev = (last / (sum(closes) / 200) - 1) * 100
        if abs(dev) > LIMITS["index_vs_ma200_pct"]:
            problems.append("加權指數 %s 收盤 %.1f，偏離 200 日均線 %+.1f%%（超過 ±%d%%），可能讀錯資料（例如報酬指數）" % (d, last, dev, LIMITS["index_vs_ma200_pct"]))
    prev = s[-2][1] if len(s) > 1 else None
    if prev:
        chg = (last / prev - 1) * 100
        if abs(chg) > LIMITS["index_day_pct"]:
            problems.append("加權指數 %s 單日變動 %+.1f%%（超過 ±%d%%）" % (d, chg, LIMITS["index_day_pct"]))
    return d


def check_stocks(problems, d, notes):
    bad, zero = [], []
    for r in T.universe():
        c = r["code"]
        try:
            s = T.prices(c)
        except Exception:
            continue
        i = s.idx.get(d)
        if i is None:
            continue
        if not s.close[i]:
            zero.append(c)
            continue
        if i == 0 or not s.close[i - 1] or s.factor[i] != 1.0:
            continue  # first day, or an ex-dividend / split day (not limited the same way)
        chg = (s.close[i] / s.close[i - 1] - 1) * 100
        if abs(chg) > LIMITS["stock_day_pct"]:
            bad.append("%s %+.1f%%" % (c, chg))
    if zero:
        problems.append("%s 有 %d 檔收盤為 0 或空值：%s" % (d, len(zero), "、".join(zero[:10])))
    if len(bad) >= LIMITS["stock_day_min_count"]:
        problems.append("%s 有 %d 檔單日漲跌超過 ±%d%%（漲跌幅限制 10%%）且沒有除權息或減資：%s" % (d, len(bad), LIMITS["stock_day_pct"], "、".join(bad[:10])))
    elif bad:
        notes.append("%s 有 %d 檔單日漲跌超過 ±%d%%，可能是除權息資料還沒補上（不擋發布）：%s" % (d, len(bad), LIMITS["stock_day_pct"], "、".join(bad)))


def check_foreign(problems):
    s = [(d, v) for d, v in series("inst_total", "foreign") if v is not None]
    if len(s) < 30:
        return
    d, last = s[-1]
    record = max(abs(v) for _, v in s[:-1])
    if record and abs(last) > LIMITS["foreign_vs_record_x"] * record:
        problems.append("外資 %s 單日買賣超 %.1f 億，超過歷史最大值 %.1f 億的 %d 倍" % (d, last / 1e8, record / 1e8, LIMITS["foreign_vs_record_x"]))


def check_fx(problems):
    s = [(d, v) for d, v in series("usdtwd") if v]
    if len(s) < 2:
        return
    (d0, a), (d1, b) = s[-2], s[-1]
    chg = (b / a - 1) * 100
    if abs(chg) > LIMITS["fx_day_pct"]:
        problems.append("美元兌台幣 %s 單日變動 %+.2f%%（超過 ±%d%%）" % (d1, chg, LIMITS["fx_day_pct"]))


def check_files(problems):
    daily = os.path.join(T.DATA, "daily")
    if os.path.isdir(daily):
        odd = [f for f in sorted(os.listdir(daily)) if not DAILY_FILE.match(f)]
        if odd:
            problems.append("每日資料夾出現預期外的檔名（可能讀錯檔案）：%s" % "、".join(odd[:10]))


def check_outputs(problems):
    """Every output must still have the fields it had in the last committed version (new fields are fine)."""
    for p in OUTPUTS:
        rel = os.path.relpath(p, ROOT)
        if not os.path.exists(p):
            problems.append("輸出檔不見了：%s" % rel)
            continue
        try:
            cur = json.load(open(p, encoding="utf-8"))
        except ValueError as e:
            problems.append("輸出檔不是正確的 JSON：%s（%s）" % (rel, e))
            continue
        try:
            old = json.loads(subprocess.run(["git", "show", "HEAD:" + rel], cwd=ROOT, capture_output=True, text=True, check=True).stdout)
        except Exception:
            continue  # new file: nothing to compare with
        missing = sorted(set(old) - set(cur))
        if missing:
            problems.append("%s 少了欄位：%s（欄位結構改變）" % (rel, "、".join(missing)))
    reg = os.path.join(ROOT, "tw-models", "latest", "regime_tw.json")
    if os.path.exists(reg):
        r = json.load(open(reg, encoding="utf-8"))
        if not (isinstance(r.get("total"), int) and 0 <= r["total"] <= 10):
            problems.append("regime_tw.json 總分 %r 不在 0～10" % r.get("total"))


def check_schemas(problems, notes, d):
    """Column-by-column format rules with pandera (MIT, https://github.com/unionai-oss/pandera).
    Today's appended daily rows and the published lists must have the right types and ranges."""
    try:
        import pandas as pd
        import pandera.pandas as pa
        from pandera.pandas import Check, Column, DataFrameSchema
    except Exception:
        notes.append("pandera 沒有安裝，這次略過欄位格式檢查")
        return
    ymd, code = r"^\d{4}-\d{2}-\d{2}$", r"^[0-9A-Z]{4,6}$"

    def explain(e, df, key):
        """Readable examples: '代號：哪條規則（欄位=值）', one per offending row, at most 3."""
        out, seen = [], set()
        for _, r in e.failure_cases.iterrows():
            idx = r["index"]
            who = str(df.loc[idx, key]) if idx is not None and idx == idx and idx in df.index and key in df.columns else "整份"
            what = str(r["check"]) if r["column"] in (None, "") or r["schema_context"] == "DataFrameSchema" else "%s=%s（%s）" % (r["column"], r["failure_case"], r["check"])
            k = (who, what)
            if k not in seen:
                seen.add(k)
                out.append("%s：%s" % (who, what))
        return len(seen), "；".join(out[:3])
    schemas = {
        "prices": DataFrameSchema({
            "date": Column(str, Check.str_matches(ymd)), "code": Column(str, Check.str_matches(code)),
            "open": Column(float, Check.gt(0), nullable=True), "high": Column(float, Check.gt(0), nullable=True),
            "low": Column(float, Check.gt(0), nullable=True), "close": Column(float, Check.gt(0)),
            "volume": Column(float, Check.ge(0))},
            checks=[Check(lambda df: (df["high"].isna() | (df["high"] >= df["low"])), error="最高價低於最低價"),
                    Check(lambda df: (df["high"].isna() | ((df["close"] <= df["high"] * 1.0001) & (df["close"] >= df["low"] * 0.9999))), error="收盤不在最高、最低之間")],
            unique=["date", "code"], strict=False, coerce=True),
        "per": DataFrameSchema({"date": Column(str, Check.str_matches(ymd)), "code": Column(str, Check.str_matches(code)),
            "pe": Column(float, Check.ge(0), nullable=True), "dy": Column(float, Check.in_range(0, 100), nullable=True),
            "pb": Column(float, Check.ge(0), nullable=True)}, unique=["date", "code"], strict=False, coerce=True),
        "inst": DataFrameSchema({"date": Column(str, Check.str_matches(ymd)), "code": Column(str, Check.str_matches(code)),
            "foreign": Column(int), "trust": Column(int), "dealer": Column(int)}, unique=["date", "code"], strict=False, coerce=True),
    }
    daily = os.path.join(T.DATA, "daily")
    for ds, sch in schemas.items():
        p = os.path.join(daily, "%s_%s.csv" % (ds, (d or "")[:7]))
        if not d or not os.path.exists(p):
            continue
        df = pd.read_csv(p, dtype={"code": str, "date": str})
        df = df[df["date"] == d]
        if df.empty:
            continue
        try:
            sch.validate(df, lazy=True)
        except pa.errors.SchemaErrors as e:
            n, ex = explain(e, df, "code")
            problems.append("%s 的每日 %s 資料有 %d 處格式或數值不合理（例如 %s）" % (d, ds, n, ex))
    lists = {
        "swing.json": DataFrameSchema({"rank": Column(int, Check.ge(1), unique=True), "code": Column(str, Check.str_matches(code)),
                                       "close": Column(float, Check.gt(0)), "stop_price_est": Column(float, Check.gt(0))}, strict=False, coerce=True),
        "long.json": DataFrameSchema({"rank": Column(int, Check.ge(1), unique=True), "code": Column(str, Check.str_matches(code), unique=True)}, strict=False, coerce=True),
        "old_screen.json": DataFrameSchema({"code": Column(str, Check.str_matches(code), unique=True), "score": Column(int, Check.in_range(0, 4)),
                                            "close": Column(float, Check.gt(0))}, strict=False, coerce=True),
    }
    for fn, sch in lists.items():
        p = os.path.join(ROOT, "tw-models", "latest", fn)
        if not os.path.exists(p):
            continue
        rows = json.load(open(p, encoding="utf-8")).get("list") or []
        if not rows:
            continue
        df = pd.DataFrame(rows)
        try:
            sch.validate(df, lazy=True)
        except pa.errors.SchemaErrors as e:
            n, ex = explain(e, df, "code")
            problems.append("%s 名單有 %d 處格式或數值不合理（例如 %s）" % (fn, n, ex))
    reg = os.path.join(ROOT, "tw-models", "latest", "regime_tw.json")
    if os.path.exists(reg):
        items = json.load(open(reg, encoding="utf-8")).get("items") or {}
        df = pd.DataFrame([{"key": k, "score": v.get("score"), "color": v.get("color")} for k, v in items.items()])
        sch = DataFrameSchema({"score": Column(int, Check.isin([0, 1, 2])), "color": Column(str, Check.isin(["綠", "黃", "紅"]))}, strict=False, coerce=True)
        try:
            if len(df) != 5:
                problems.append("regime_tw.json 應該有 5 項指標，現在是 %d 項" % len(df))
            sch.validate(df, lazy=True)
        except pa.errors.SchemaErrors as e:
            problems.append("regime_tw.json 指標有 %d 處不合理（分數要 0／1／2、燈號要綠／黃／紅）" % len(e.failure_cases))


def run_checks():
    problems, notes = [], []
    d = check_index(problems)
    if d:
        check_stocks(problems, d, notes)
    check_foreign(problems)
    check_fx(problems)
    check_files(problems)
    check_outputs(problems)
    check_schemas(problems, notes, d)
    return {"ok": not problems, "date": d, "checked_at_utc": datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%d %H:%M:%S"),
            "limits": LIMITS, "problems": problems, "notes": notes}


def mark(report):
    msg = "資料檢查未通過（%s），本檔維持前一次的資料：%s" % (report.get("date"), "；".join(report["problems"]))
    for p in OUTPUTS:
        if not os.path.exists(p):
            continue
        j = json.load(open(p, encoding="utf-8"))
        probs = [x for x in (j.get("problems") or []) if not str(x).startswith("資料檢查未通過")]
        j["problems"] = [msg] + probs
        with open(p, "w", encoding="utf-8") as f:
            json.dump(j, f, ensure_ascii=False, indent=1)
            f.write("\n")
    print(msg)


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("mode", choices=["check", "mark"])
    ap.add_argument("--out")
    ap.add_argument("--report")
    a = ap.parse_args()
    if a.mode == "check":
        rep = run_checks()
        json.dump(rep, open(a.out, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
        print("ok" if rep["ok"] else "FAILED", rep["problems"], "notes:", rep["notes"])
    else:
        mark(json.load(open(a.report, encoding="utf-8")))
