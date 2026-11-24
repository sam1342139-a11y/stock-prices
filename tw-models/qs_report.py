"""Performance report helpers built on quantstats (Apache-2.0, https://github.com/ranaroussi/quantstats).

Used only to REPORT results (backtests and the paper accounts); model rules are not touched.
  metrics(nav_curve)            -> dict of performance figures from a [(date, nav), ...] curve
  heatmap(nav_curve, path, ttl) -> monthly-return heatmap PNG (returns the path, or None when matplotlib is missing)
  table_md(names, results)      -> markdown table comparing several curves
quantstats is imported lazily so the rest of the system keeps working without it.
"""
import math, os

ROWS = [  # (label, key, unit)
    ("總報酬", "total_pct", "%"), ("年化報酬", "cagr_pct", "%"), ("年化波動", "vol_pct", "%"),
    ("夏普值", "sharpe", ""), ("索提諾值", "sortino", ""), ("最大回撤", "mdd_pct", "%"),
    ("最長回撤天數", "longest_dd_days", " 天"), ("卡瑪值（年化報酬÷最大回撤）", "calmar", ""),
    ("月勝率", "win_month_pct", "%"), ("最佳月", "best_month_pct", "%"), ("最差月", "worst_month_pct", "%"),
    ("單日風險值（95%）", "var95_pct", "%"),
]


def _series(curve):
    import pandas as pd
    s = pd.Series([v for _, v in curve], index=pd.to_datetime([d for d, _ in curve]), dtype=float)
    return s.pct_change().dropna()


def _r(x, n=2):
    return None if x is None or (isinstance(x, float) and (math.isnan(x) or math.isinf(x))) else round(float(x), n)


def metrics(curve):
    """Figures for a daily NAV curve. Sharpe/Sortino: daily returns, risk-free 0, x sqrt(252) (same as backtest.py)."""
    import quantstats as qs
    r = _series(curve)
    if len(r) < 2:
        return {}
    m = qs.stats.monthly_returns(r, eoy=False, compounded=True)
    months = [v for row in m.values for v in row if v == v and v != 0]
    dd = qs.stats.drawdown_details(qs.stats.to_drawdown_series(r))
    longest = int(dd["days"].max()) if len(dd) else 0
    return {
        "total_pct": _r(qs.stats.comp(r) * 100), "cagr_pct": _r(qs.stats.cagr(r, periods=252) * 100),
        "vol_pct": _r(qs.stats.volatility(r, periods=252, annualize=True) * 100),
        "sharpe": _r(qs.stats.sharpe(r, rf=0, periods=252, annualize=True)),
        "sortino": _r(qs.stats.sortino(r, rf=0, periods=252, annualize=True)),
        "mdd_pct": _r(qs.stats.max_drawdown(r) * 100), "longest_dd_days": longest,
        "calmar": _r(qs.stats.calmar(r, periods=252)),
        "win_month_pct": _r(sum(1 for v in months if v > 0) / len(months) * 100, 1) if months else None,
        "best_month_pct": _r(max(months) * 100) if months else None,
        "worst_month_pct": _r(min(months) * 100) if months else None,
        "var95_pct": _r(qs.stats.value_at_risk(r, confidence=0.95) * 100),
    }


def table_md(names, results):
    L = ["| 指標 | " + " | ".join(names) + " |", "|---|" + "---|" * len(names)]
    for label, k, u in ROWS:
        L.append("| %s | " % label + " | ".join("" if results[n].get(k) is None else "%s%s" % (results[n][k], u) for n in names) + " |")
    return L


def heatmap(curve, path, title):
    """Monthly returns (%) as a year x month grid. Writes a PNG; returns path or None."""
    try:
        import quantstats as qs
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
        from matplotlib import font_manager
        for f in font_manager.findSystemFonts():
            if "wqy" in f.lower() or "noto" in f.lower() and "cjk" in f.lower():
                font_manager.fontManager.addfont(f)
                plt.rcParams["font.family"] = font_manager.FontProperties(fname=f).get_name()
                break
        plt.rcParams["axes.unicode_minus"] = False
    except Exception:
        return None
    m = qs.stats.monthly_returns(_series(curve), eoy=False, compounded=True) * 100
    years, cols = list(m.index), list(m.columns)
    fig, ax = plt.subplots(figsize=(7.5, 0.45 * len(years) + 1.2), dpi=150)
    lim = max(5.0, float(abs(m.values).max())) if m.size else 5.0
    ax.imshow(m.values, cmap="RdYlGn_r", vmin=-lim, vmax=lim, aspect="auto")  # Taiwan convention: up = red
    ax.set_xticks(range(len(cols)))
    ax.set_xticklabels(["%d月" % (i + 1) for i in range(len(cols))], fontsize=8)
    ax.set_yticks(range(len(years)))
    ax.set_yticklabels([str(y) for y in years], fontsize=8)
    for i in range(len(years)):
        for j in range(len(cols)):
            v = m.values[i][j]
            if v == v and v != 0:
                ax.text(j, i, "%.1f" % v, ha="center", va="center", fontsize=7, color="white" if abs(v) > 0.6 * lim else "#161b22")
    ax.grid(False)
    for sp in ax.spines.values():
        sp.set_visible(False)
    ax.set_title(title, fontsize=10)
    fig.tight_layout()
    os.makedirs(os.path.dirname(path), exist_ok=True)
    fig.savefig(path)
    plt.close(fig)
    return path
