"""Taiwan market regime (水位燈號). Rules: docs/TW_MODELS.md §C; parameters: config.json "regime_tw".

Five items, each 0/1/2 (green/yellow/red). Total → suggested equity exposure band.
No look-ahead: TW data (TAIEX, foreign flows, margin) use the signal day's close (available after close);
US-market data (SOXX, USD/TWD from Twelve Data) use the latest bar dated strictly BEFORE the signal day,
because the US session for that date has not happened yet at Taiwan's close.

Usage:
  python3 tw-models/regime_tw.py [--dry-run]            write latest/regime_tw.json + history csv
  python3 tw-models/regime_tw.py --calibrate            print/write 2019–2023 foreign-flow percentiles
  python3 tw-models/regime_tw.py --backtest             0050 with regime exposure vs always fully invested
"""
import bisect, json, os, sys
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(1, os.path.join(os.path.dirname(HERE), "lib"))
import common as C
import twdata as T

COLORS = {0: "綠", 1: "黃", 2: "紅"}
ITEMS = ["taiex_ma200", "foreign_20d", "margin_vs_index", "usdtwd_20d", "soxx_ma200"]
SOURCES = [
    {"name": "FinMind（加權指數、三大法人買賣金額、融資餘額，歷史）", "url": "https://api.finmindtrade.com/api/v4/data"},
    {"name": "證交所 OpenAPI（每日累加）", "url": "https://openapi.twse.com.tw/"},
    {"name": "Twelve Data（SOXX、美元兌台幣日收盤）", "url": "https://api.twelvedata.com/time_series"},
]


def series(name, field="close"):
    m = T.market(name)
    ds = list(m.keys())
    return ds, [float(m[d][field]) for d in ds]


def pct(a, b):
    return (a / b - 1) * 100


def compute_all(cfg):
    """Daily regime for every TAIEX trading day with enough history. Returns {date: result}."""
    r = cfg["regime_tw"]
    td, tc = series("taiex")
    fd, fv = series("inst_total", "foreign")
    fidx = {d: i for i, d in enumerate(fd)}
    md, mv = series("margin_total", "margin_balance")
    midx = {d: i for i, d in enumerate(md)}
    sd, sv = series("soxx")
    ud, uv = series("usdtwd")
    W = r["ma_slope_lookback"]
    out = {}
    for i, d in enumerate(td):
        res = {}
        # 1) TAIEX vs 200-day MA
        if i >= r["ma_days"] + W - 1:
            ma = sum(tc[i - r["ma_days"] + 1:i + 1]) / r["ma_days"]
            ma_prev = sum(tc[i - W - r["ma_days"] + 1:i - W + 1]) / r["ma_days"]
            dist, slope = pct(tc[i], ma), pct(ma, ma_prev)
            rising = slope > r["ma_rising_min_pct"]
            s = 0 if dist >= 0 and rising else (1 if dist >= -r["taiex_yellow_below_pct"] else 2)
            res["taiex_ma200"] = (s, round(dist, 2), d, {"taiex": tc[i], "ma200": round(ma, 2), "ma200_20d_change_pct": round(slope, 2)})
        # 2) Foreign net buy, 20-day sum (NTD)
        j = fidx.get(d)
        if j is not None and j >= r["foreign_window"] - 1:
            tot = sum(fv[j - r["foreign_window"] + 1:j + 1])
            s = 0 if tot > 0 else (1 if tot >= r["foreign_red_threshold_ntd"] else 2)
            res["foreign_20d"] = (s, round(tot / 1e8, 1), d, {"unit": "億元"})
        # 3) Margin balance 20-day change vs TAIEX 20-day change
        k = midx.get(d)
        if k is not None and k >= r["margin_window"] and i >= r["margin_window"]:
            mchg, ichg = pct(mv[k], mv[k - r["margin_window"]]), pct(tc[i], tc[i - r["margin_window"]])
            if ichg < 0 and mchg > 0:
                s = 2
            elif ichg > 0 and mchg <= r["margin_stable_pct"]:
                s = 0
            else:
                s = 1
            res["margin_vs_index"] = (s, round(mchg, 2), d, {"index_20d_pct": round(ichg, 2)})
        # 4) USD/TWD 20-day change (bars strictly before d)
        u = bisect.bisect_left(ud, d) - 1
        if u >= r["usdtwd_window"]:
            ch = pct(uv[u], uv[u - r["usdtwd_window"]])
            b = r["usdtwd_band_pct"]
            s = 0 if ch < -b else (1 if ch <= b else 2)
            res["usdtwd_20d"] = (s, round(ch, 2), ud[u], {"usdtwd": uv[u]})
        # 5) SOXX vs own 200-day MA (bars strictly before d)
        q = bisect.bisect_left(sd, d) - 1
        if q >= r["ma_days"] - 1:
            ma = sum(sv[q - r["ma_days"] + 1:q + 1]) / r["ma_days"]
            dist = pct(sv[q], ma)
            n = r["soxx_near_pct"]
            s = 0 if dist > n else (1 if dist >= -n else 2)
            res["soxx_ma200"] = (s, round(dist, 2), sd[q], {"soxx": sv[q], "ma200": round(ma, 2)})
        if len(res) == len(ITEMS):
            total = sum(v[0] for v in res.values())
            out[d] = {"total": total, "items": res}
    return out


def level(cfg, total):
    for lv in cfg["regime_tw"]["levels"]:
        if total <= lv["max_score"]:
            return lv
    return cfg["regime_tw"]["levels"][-1]


NAMES = {"taiex_ma200": "加權指數 vs 200 日均線", "foreign_20d": "外資近 20 日累計買賣超",
         "margin_vs_index": "融資近 20 日變化 vs 指數", "usdtwd_20d": "美元兌台幣近 20 日", "soxx_ma200": "SOXX vs 200 日均線"}


def thresholds(cfg):
    r = cfg["regime_tw"]
    return {
        "taiex_ma200": "綠：在 200 日均線之上且均線上升（20 日內上升超過 %.1f%%）；黃：在均線之上但走平或下降，或低於均線 0～%g%%；紅：低於均線超過 %g%%" % (r["ma_rising_min_pct"], r["taiex_yellow_below_pct"], r["taiex_yellow_below_pct"]),
        "foreign_20d": "綠：> 0；黃：%d 億～0；紅：< %d 億（門檻由 2019–2023 第 %d 百分位校正）" % (r["foreign_red_threshold_ntd"] / 1e8, r["foreign_red_threshold_ntd"] / 1e8, r["foreign_calibration_percentile"]),
        "margin_vs_index": "紅：指數跌且融資增加；綠：指數漲且融資增加不超過 %g%%；其餘（兩者同向等）黃" % r["margin_stable_pct"],
        "usdtwd_20d": "綠：台幣升值超過 %g%%（美元兌台幣下跌）；黃：±%g%% 內；紅：台幣貶值超過 %g%%" % (r["usdtwd_band_pct"], r["usdtwd_band_pct"], r["usdtwd_band_pct"]),
        "soxx_ma200": "綠：高於 200 日均線超過 %g%%；黃：均線上下 %g%% 內；紅：低於均線超過 %g%%" % (r["soxx_near_pct"], r["soxx_near_pct"], r["soxx_near_pct"]),
    }


def write_latest(cfg, allres, problems):
    d = max(allres)
    res = allres[d]
    lv = level(cfg, res["total"])
    th = thresholds(cfg)
    dates = sorted(allres)
    prev = allres[dates[-2]] if len(dates) > 1 else None
    items = {}
    for k in ITEMS:
        s, v, dd, extra = res["items"][k]
        items[k] = dict({"name": NAMES[k], "score": s, "color": COLORS[s], "value": v, "date": dd, "threshold": th[k]}, **extra)
    changed = [NAMES[k] for k in ITEMS if prev and res["items"][k][0] > prev["items"][k][0]]
    C.write_json("tw-models/latest/regime_tw.json", {
        "date": d, "total": res["total"], "max_total": 10,
        "suggested_exposure_pct": [int(lv["exposure"][0] * 100), int(lv["exposure"][1] * 100)],
        "rule": "每項 0 綠／1 黃／2 紅；總分 0～2 建議持股 80～100%，3～5 分 50～70%，6 分以上 20～40%。規則見 docs/TW_MODELS.md",
        "worsened_vs_previous_day": changed,
        "items": items,
        "footer": "模型依公開資料與固定規則產生，回測不代表未來，非投資建議。",
    }, problems, SOURCES)
    hdr = ["date", "total", "exposure_low", "exposure_high"] + [x for k in ITEMS for x in (k, k + "_score")]
    rows = []
    for dd in dates[-260:]:
        r = allres[dd]
        l2 = level(cfg, r["total"])
        rows.append([dd, r["total"], l2["exposure"][0], l2["exposure"][1]] + [x for k in ITEMS for x in (r["items"][k][1], r["items"][k][0])])
    C.write_csv("tw-models/latest/regime_tw_history.csv", hdr, rows)
    print("regime_tw %s total=%d exposure=%s" % (d, res["total"], lv["exposure"]))
    for k in ITEMS:
        print("  %s %s = %s (%s)" % (COLORS[res["items"][k][0]], NAMES[k], res["items"][k][1], res["items"][k][2]))


def calibrate(cfg):
    r = cfg["regime_tw"]
    fd, fv = series("inst_total", "foreign")
    W = r["foreign_window"]
    sums = [sum(fv[j - W + 1:j + 1]) / 1e8 for j in range(W - 1, len(fd)) if "2019-01-01" <= fd[j] <= "2023-12-31"]
    sums.sort()
    q = lambda p: sums[min(len(sums) - 1, int(p / 100 * len(sums)))]
    out = {"window_days": W, "n": len(sums), "unit": "億元",
           "percentiles": {str(p): round(q(p), 1) for p in (5, 10, 15, 20, 30, 50)},
           "share_below_minus_500": round(sum(1 for x in sums if x < -500) / len(sums) * 100, 1)}
    p = r["foreign_calibration_percentile"]
    out["chosen_percentile"] = p
    out["chosen_threshold_yi"] = int(q(p) // 50 * 50)  # round down to 50 億
    C.write_json("tw-models/reports/regime_tw_calibration.json", out, [], SOURCES[:1])
    print(json.dumps(out, ensure_ascii=False))
    return out


def backtest(cfg):
    import backtest as B
    allres = compute_all(cfg)

    def regime_strat(d, br):
        r = allres.get(d)
        if not r:
            return []
        lv = level(cfg, r["total"])
        target = sum(lv["exposure"]) / 2  # midpoint of the band
        w = br.weights(d).get("0050", 0)
        if abs(w - target) > 0.05 or not br.pos:
            return B.target_orders(br, d, {"0050": target}, "水位調整")
        return []

    def fixed(target):
        def strat(d, br):
            w = br.weights(d).get("0050", 0)
            if abs(w - target) > 0.05 or not br.pos:
                return B.target_orders(br, d, {"0050": target}, "固定比例")
            return []
        return strat

    bt0 = dict(cfg["backtest"])
    bt1 = dict(cfg["backtest"], cash_interest=cfg["backtest"]["cash_interest_alt"])
    rate = "%g%%" % (cfg["backtest"]["cash_interest_alt"] * 100)
    V_REG, V_FIX = "水位調整", "固定比例"
    V_REG_I, V_FIX_I = "水位調整（現金年息%s）" % rate, "固定比例（現金年息%s）" % rate
    variants = {V_REG: {}, V_FIX: {}, V_REG_I: {}, V_FIX_I: {}, "0050": {}}
    avg = {}
    for per, (s, e) in B.periods().items():
        variants[V_REG][per] = B.run(regime_strat, s, e, bt0)
        ex = variants[V_REG][per]["exposure"]
        avg[per] = round(sum(ex) / len(ex), 3)
        variants[V_FIX][per] = B.run(fixed(avg[per]), s, e, bt0)
        variants[V_REG_I][per] = B.run(regime_strat, s, e, bt1)
        variants[V_FIX_I][per] = B.run(fixed(avg[per]), s, e, bt1)
        variants["0050"][per] = B.benchmark_0050(s, e, bt0)
    notes = ["比較「依水位燈號調整 0050 持股比例」與「一直滿倉 0050」。",
             "持股比例取各級距中點：0～2 分 90%、3～5 分 60%、6 分以上 30%；比例偏離超過 5 個百分點才調整。",
             "「固定比例」= 一直維持水位版在同一期間的平均持股比例（樣本內 %.1f%%、樣本外 %.1f%%），用來檢驗燈號是否真的有擇時效果：水位版要贏固定比例版，才代表燈號有用。" % (avg["in_sample"] * 100, avg["out_of_sample"] * 100),
             "注意：固定比例用的是「同一期間事後算出的平均比例」，實務上事前無法知道，只作為檢驗用的比較組。",
             "「現金年息%s」版本：未投入的現金每個交易日計息（年息 ÷ 252）；其餘版本現金不計利息。" % rate,
             "訊號用當天收盤後資料，隔天開盤成交；含手續費、證交稅（ETF 0.1%）、滑價 0.1%。"]
    B.write_report("regime_tw", "台股水位燈號（依水位調整持股 vs 滿倉）", variants, notes, [], SOURCES)
    for per in B.periods():
        for v in variants:
            m = B.metrics(variants[v][per])
            print(per, v, m["total_return_pct"], m["cagr_pct"], m["max_drawdown_pct"], m["sharpe"])


def main():
    cfg = T.config()
    if "--calibrate" in sys.argv:
        calibrate(cfg)
        return
    if "--backtest" in sys.argv:
        backtest(cfg)
        return
    problems = []
    allres = compute_all(cfg)
    if not allres:
        raise SystemExit("資料不足，無法計算水位燈號")
    last_tw = max(T.market("taiex"))
    if max(allres) != last_tw:
        problems.append("最新完整計算日 %s 早於加權指數最新日 %s（某些項目資料尚未更新）" % (max(allres), last_tw))
    write_latest(cfg, allres, problems)


if __name__ == "__main__":
    main()
