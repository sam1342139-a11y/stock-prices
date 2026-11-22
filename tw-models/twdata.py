"""Data loader for tw-models (stdlib only).

Adjusted prices: TWSE's daily change ("spread") is measured against the *reference price*,
so reference = close - spread. On normal days reference == previous close; on ex-dividend,
ex-rights, split or capital-reduction days it differs. Daily factor f_t = reference_t / close_{t-1};
backward-adjusted price_t = raw_t * prod(f_j for j > t). This makes returns include dividends
(as if reinvested) and handles splits such as 0050's 1:4 on 2025-06-18.

History files (per code, gzip) come from fetch_history.py; days appended later by
update_daily.py live in data/daily/<dataset>_<YYYY-MM>.csv and are merged here.
"""
import csv, glob, gzip, io, json, os
from functools import lru_cache

HERE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(HERE, "data")
FACTOR_EPS = 0.0005  # |f-1| below this is treated as rounding noise


def _read(path):
    op = gzip.open if path.endswith(".gz") else open
    with op(path, "rt", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def _num(x):
    try:
        return float(x)
    except (TypeError, ValueError):
        return None


@lru_cache(maxsize=None)
def _daily(dataset):
    """All rows appended by update_daily.py for a dataset, grouped by code."""
    out = {}
    for p in sorted(glob.glob(os.path.join(DATA, "daily", "%s_*.csv" % dataset))):
        for r in _read(p):
            out.setdefault(r["code"], []).append(r)
    return out


def _merged(dataset, code, key="date"):
    rows = {}
    p = os.path.join(DATA, dataset, code + ".csv.gz")
    if os.path.exists(p):
        for r in _read(p):
            rows[r[key]] = r
    for r in _daily(dataset).get(code, []):
        rows[r[key]] = r
    return [rows[k] for k in sorted(rows)]


def universe():
    return _read(os.path.join(DATA, "universe.csv"))


def is_etf(code):
    return code.startswith("00")


class Series:
    """Price series for one code. Lists aligned by index; *_adj are backward-adjusted."""
    __slots__ = ("code", "dates", "open", "high", "low", "close", "volume", "value", "factor",
                 "open_adj", "high_adj", "low_adj", "close_adj", "idx")

    def __init__(self, code, rows, events=None):
        """events: {ex_date: factor} from official ex-rights/dividend results (reference/before)."""
        events = events or {}
        self.code = code
        self.dates, self.open, self.high, self.low, self.close = [], [], [], [], []
        self.volume, self.value, self.factor = [], [], []
        prev = None
        for r in rows:
            c = _num(r["close"])
            if not c:
                continue
            o, h, l = _num(r["open"]) or c, _num(r["high"]) or c, _num(r["low"]) or c
            sp = _num(r.get("spread"))
            f = 1.0
            if r["date"] in events:
                # official ex-rights / ex-dividend: FinMind reports spread 0 on these days
                f = events[r["date"]]
            elif prev and sp:
                # non-zero spread vs reference price: catches splits and capital reductions
                ref = c - sp
                if ref > 0:
                    f = ref / prev
                    if abs(f - 1) < FACTOR_EPS:
                        f = 1.0
            self.dates.append(r["date"]); self.open.append(o); self.high.append(h); self.low.append(l)
            self.close.append(c); self.volume.append(_num(r["volume"]) or 0); self.value.append(_num(r["value"]) or 0)
            self.factor.append(f)
            prev = c
        n = len(self.dates)
        cum = [1.0] * n
        for i in range(n - 2, -1, -1):
            cum[i] = cum[i + 1] * self.factor[i + 1]
        self.open_adj = [self.open[i] * cum[i] for i in range(n)]
        self.high_adj = [self.high[i] * cum[i] for i in range(n)]
        self.low_adj = [self.low[i] * cum[i] for i in range(n)]
        self.close_adj = [self.close[i] * cum[i] for i in range(n)]
        self.idx = {d: i for i, d in enumerate(self.dates)}

    def at(self, date):
        """Index of the last trading row on or before date (None if none)."""
        i = self.idx.get(date)
        if i is not None:
            return i
        import bisect
        j = bisect.bisect_right(self.dates, date) - 1
        return j if j >= 0 else None

    def corporate_actions(self):
        return [(self.dates[i], round(self.factor[i], 6)) for i in range(len(self.dates)) if self.factor[i] != 1.0]


@lru_cache(maxsize=None)
def dividend_factors(code):
    """{ex_date: reference_price / before_price} from official ex-rights/dividend results."""
    out = {}
    for r in dividends(code):
        b, ref = _num(r.get("before_price")), _num(r.get("reference_price"))
        if b and ref and b > 0:
            out[r["ex_date"]] = ref / b
    return out


@lru_cache(maxsize=None)
def prices(code):
    return Series(code, _merged("prices", code), dividend_factors(code))


def unexplained_gaps(code, limit=0.11):
    """Days with |close/prev - 1| > limit and no adjustment factor (possible missing corporate action)."""
    s = prices(code)
    return [s.dates[i] for i in range(1, len(s.dates))
            if s.factor[i] == 1.0 and abs(s.close[i] / s.close[i - 1] - 1) > limit]


@lru_cache(maxsize=None)
def per(code):
    return {r["date"]: (_num(r["pe"]), _num(r["dy"]), _num(r["pb"])) for r in _merged("per", code)}


@lru_cache(maxsize=None)
def inst(code):
    return {r["date"]: (_num(r["foreign"]) or 0, _num(r["trust"]) or 0, _num(r["dealer"]) or 0) for r in _merged("inst", code)}


@lru_cache(maxsize=None)
def revenue(code):
    """[(ym, revenue, available_date)] sorted by ym. Use only rows with available <= signal date."""
    return [(r["ym"], _num(r["revenue"]), r["available"]) for r in _merged("revenue", code, key="ym")]


@lru_cache(maxsize=None)
def dividends(code):
    p = os.path.join(DATA, "dividends", code + ".csv.gz")
    return _read(p) if os.path.exists(p) else []


@lru_cache(maxsize=None)
def market(name):
    """market/<name>.csv as {date: row dict}; merged with daily/market_<name>_*.csv."""
    rows = {}
    p = os.path.join(DATA, "market", name + ".csv")
    if os.path.exists(p):
        for r in _read(p):
            rows[r["date"]] = r
    for q in sorted(glob.glob(os.path.join(DATA, "daily", "market_%s_*.csv" % name))):
        for r in _read(q):
            rows[r["date"]] = r
    return dict(sorted(rows.items()))


def calendar(start=None, end=None):
    """Trading days from TAIEX."""
    ds = list(market("taiex").keys())
    return [d for d in ds if (not start or d >= start) and (not end or d <= end)]


def config():
    with open(os.path.join(HERE, "config.json"), encoding="utf-8") as f:
        return json.load(f)
