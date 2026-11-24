"""Monday weekly report of the Taiwan models: tw-models/latest/weekly_report.md.

Copies figures from the existing output files (no model re-run). The only arithmetic is on the paper-trading
NAV curve (week return, gap vs 0050), done here so the morning routine does not have to.
Usage: python3 tw-models/weekly_report.py
"""
import csv, datetime, json, os
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FILES = {"regime": "tw-models/latest/regime_tw.json", "long": "tw-models/latest/long.json", "swing": "tw-models/latest/swing.json",
         "core": "tw-models/latest/core_satellite.json", "paper": "tw-models/paper/latest.json"}
PAPER = [("core_satellite", "七三組合"), ("long", "長期 100%"), ("etf_0050", "0050 100%")]


def load(rel):
    try:
        return json.load(open(os.path.join(ROOT, rel), encoding="utf-8"))
    except (OSError, ValueError):
        return None


def pct(x, unit="%"):
    return "—" if x is None else "%+.2f" % x + unit


def week_returns():
    """Per account: (latest nav, return over the last completed week). Week = last NAV of the previous ISO week -> latest."""
    try:
        rows = list(csv.DictReader(open(os.path.join(ROOT, "tw-models/paper/nav.csv"), encoding="utf-8")))
    except OSError:
        return {}
    if not rows:
        return {}
    last = rows[-1]
    wk = datetime.date.fromisoformat(last["date"]).isocalendar()[:2]
    before = [r for r in rows if datetime.date.fromisoformat(r["date"]).isocalendar()[:2] < wk]
    base = before[-1] if before else rows[0]
    out = {}
    for k, _ in PAPER:
        try:
            out[k] = (float(base[k]), float(last[k]), base["date"], last["date"])
        except (KeyError, ValueError):
            pass
    return out


def main():
    d = {k: load(v) for k, v in FILES.items()}
    today = datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(hours=8)
    L = ["# 台股模型週報（%s）" % today.strftime("%Y-%m-%d"), "",
         "> 自動產生（GitHub Actions），內容照抄各輸出檔，不重算模型；模型依公開資料與固定規則產生，回測不代表未來，非投資建議。", ""]
    warn = []
    for k, rel in FILES.items():
        if d[k] is None:
            warn.append("⚠️ 資料檢查未通過：%s 讀不到" % rel)
            continue
        for p in d[k].get("problems") or []:
            p = str(p)
            warn.append(("⚠️ 資料檢查未通過：%s：%s" if p.startswith("資料檢查未通過") else "⚠️ 資料提醒：%s：%s") % (rel, p))
    if warn:
        L += warn + [""]

    r = d["regime"] or {}
    L += ["## 台股水位燈號", "",
          "- 整體燈號：**%s**（總分 %s／%s，資料日 %s）" % (r.get("overall_light", "—"), r.get("total", "—"), r.get("max_total", "—"), r.get("date", "—")),
          "- %s：%s" % (r.get("reference_exposure_label", "參考水位"), "～".join("%s%%" % x for x in r.get("reference_exposure_pct") or []) or "—"),
          "- 紅黃燈指標（回測擇時效果不明顯，僅供參考）："]
    hits = [i for i in (r.get("items") or {}).values() if i.get("color") in ("紅", "黃")]
    L += ["  - %s：%s（%s，%s）" % (i.get("name"), i.get("color"), i.get("value"), i.get("date")) for i in hits] or ["  - 無"]
    L.append("")

    g = d["long"] or {}
    L += ["## 長期名單（%d 檔）" % len(g.get("list") or []), "",
          "訊號日 %s；下次換股：%s" % (g.get("signal_date", "—"), g.get("next_rebalance", "—")), "",
          "| 名次 | 代號 | 名稱 | 上榜原因 |", "|---|---|---|---|"]
    L += ["| %s | %s | %s | %s |" % (x.get("rank"), x.get("code"), x.get("name"), x.get("reason", "")) for x in g.get("list") or []]
    L.append("")

    s = d["swing"] or {}
    L += ["## 波段名單（%s）" % (s.get("caution") or "回測未勝過 0050，僅供觀察"), "",
          "資料日 %s；%s" % (s.get("date", "—"), s.get("note", "") if s.get("red_light") else ""), "",
          "| 名次 | 代號 | 名稱 | 收盤 | 預估停損價 | 上榜原因 |", "|---|---|---|---|---|---|"]
    L += ["| %s | %s | %s | %s | %s | %s |" % (x.get("rank"), x.get("code"), x.get("name"), x.get("close"), x.get("stop_price_est"), x.get("reason", ""))
          for x in s.get("list") or []]
    L += ["", "預估停損價：%s" % s.get("stop_price_est_note", ""), ""]

    c = d["core"] or {}
    L += ["## 七三組合（0050 七成＋長期名單三成）", "",
          "- 上次再平衡：%s；下次再平衡：%s（%s）" % (c.get("last_rebalance", "—"), c.get("next_rebalance", "—"), c.get("next_rebalance_note", "")), ""]

    p = d["paper"] or {}
    pf = p.get("portfolios") or {}
    wr = week_returns()
    base0050 = (pf.get("etf_0050") or {}).get("return_pct")
    L += ["## 模擬資金（各起始 %s 元，%s 起）" % ("{:,}".format(p.get("initial_capital", 1000000)), p.get("start", "—")), "",
          "資料日 %s。上週報酬與相對 0050 差距為程式依 nav.csv 計算。" % p.get("date", "—"), "",
          "| 組合 | 最新淨值 | 累計報酬 | 上週報酬 | 累計相對 0050 |", "|---|---|---|---|---|"]
    for k, label in PAPER:
        x = pf.get(k) or {}
        w = wr.get(k)
        wk = (w[1] / w[0] - 1) * 100 if w and w[0] else None
        rel = None if k == "etf_0050" or x.get("return_pct") is None or base0050 is None else x["return_pct"] - base0050
        L.append("| %s | %s | %s | %s | %s |" % (label, "{:,.0f}".format(x["nav"]) if x.get("nav") is not None else "—",
                                               pct(x.get("return_pct")), pct(wk), "—" if k == "etf_0050" else pct(rel, " 個百分點")))
    if wr:
        any_w = next(iter(wr.values()))
        L += ["", "上週報酬期間：%s → %s" % (any_w[2], any_w[3])]
    L += ["", "—", "模型依公開資料與固定規則產生，回測與模擬不代表未來，非投資建議。", ""]
    with open(os.path.join(ROOT, "tw-models/latest/weekly_report.md"), "w", encoding="utf-8") as f:
        f.write("\n".join(L))
    print("weekly_report written;", len(warn), "warnings")


if __name__ == "__main__":
    main()
