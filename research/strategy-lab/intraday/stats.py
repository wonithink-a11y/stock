"""Event-study statistics. Pure functions; no data access.

Conventions (V1~V9 strategy-lab convention):
  - Excess return = stock return - same-date equal-weight market proxy return.
  - Reported group stats are per-date means of excess returns, then averaged
    over dates where a date mean is used (guards against one heavy day
    dominating), alongside pooled ticker-level stats.
"""
from __future__ import annotations

import numpy as np
from scipy import stats as sps


def summarize(returns, excess=None):
    """n/mean/median/win_rate/vol/t/p (+excess block when given).

    returns/excess: 1-d arrays with NaN allowed. NaN rows drop pairwise.
    t-test is one-sample t against 0 on the non-NaN values (research
    descriptive, not a trading significance claim).
    """
    r = np.asarray(returns, dtype=float)
    r = r[np.isfinite(r)]
    out = {
        "n": int(r.size),
        "mean": _f(np.mean(r)) if r.size else None,
        "median": _f(np.median(r)) if r.size else None,
        "winRate": _f(np.mean(r > 0)) if r.size else None,
        "vol": _f(np.std(r, ddof=1)) if r.size > 1 else None,
    }
    if r.size > 1 and np.std(r, ddof=1) > 0:
        t, p = sps.ttest_1samp(r, 0.0)
        out["t"] = _f(t)
        out["p"] = _f(p)
    if excess is not None:
        e = np.asarray(excess, dtype=float)
        ok = np.isfinite(e) & np.isfinite(np.asarray(returns, dtype=float))
        e = e[ok]
        block = {
            "nExcess": int(e.size),
            "meanExcess": _f(np.mean(e)) if e.size else None,
            "medianExcess": _f(np.median(e)) if e.size else None,
            "winRateExcess": _f(np.mean(e > 0)) if e.size else None,
        }
        if e.size > 1 and np.std(e, ddof=1) > 0:
            t, p = sps.ttest_1samp(e, 0.0)
            block["tExcess"] = _f(t)
            block["pExcess"] = _f(p)
        out["excess"] = block
    return out


def daily_mean_series(df, value_col, date_col="date"):
    """Equal-weight per-date mean of value_col -> Series indexed by date."""
    g = df.dropna(subset=[value_col]).groupby(date_col)[value_col]
    return g.mean()


def rank_ic_by_date(df, feature_col, return_col, date_col="date"):
    """Cross-sectional Spearman rank IC per date; returns (mean, n_dates,
    t_stat). Dates with <10 valid pairs are skipped."""
    ics = []
    for _, g in df.dropna(subset=[feature_col, return_col]).groupby(date_col):
        if len(g) < 10:
            continue
        ic = sps.spearmanr(g[feature_col].to_numpy(), g[return_col].to_numpy())
        if np.isfinite(ic.statistic):
            ics.append(ic.statistic)
    if len(ics) < 3:
        return {"meanIC": None, "nDates": len(ics), "tIC": None}
    ics = np.asarray(ics)
    t = np.mean(ics) / (np.std(ics, ddof=1) / np.sqrt(len(ics)))
    return {"meanIC": _f(np.mean(ics)), "nDates": int(len(ics)), "tIC": _f(t)}


def _f(x):
    return float(x) if x is not None and np.isfinite(x) else None


def paired_date_diff_ttest(ev, mask_a, mask_b, col):
    """Per-date mean(A)-mean(B) differences -> one-sample t-test over dates.

    A/B are boolean masks over the same event frame; dates need >=1 valid
    observation on both sides. Returns nDates/meanDiff/t/p/positiveDayShare.
    """
    a = ev[mask_a].groupby("date")[col].mean()
    b = ev[mask_b].groupby("date")[col].mean()
    d = (a - b).dropna()
    if len(d) < 10:
        return {"nDates": int(len(d)), "meanDiff": None, "t": None}
    t, p = sps.ttest_1samp(d.to_numpy(), 0.0)
    return {"nDates": int(len(d)),
            "meanDiff": _f(np.mean(d)),
            "t": _f(t), "p": _f(p),
            "positiveDayShare": _f((d > 0).mean())}


def round_block(d, nd=6):
    """Recursively round floats / convert numpy scalars for JSON output."""
    if isinstance(d, dict):
        return {k: round_block(v, nd) for k, v in d.items()}
    if isinstance(d, (list, tuple)):
        return [round_block(v, nd) for v in d]
    if isinstance(d, (np.floating, np.integer)):
        d = d.item()
    if isinstance(d, float):
        return round(d, nd) if np.isfinite(d) else None
    return d
