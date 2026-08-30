"""Market proxies and regime flags built from the research panel itself.

There is no KOSPI/KOSDAQ index series in the local data, so the market proxy
is the equal-weight mean of constituent returns per (date, market segment) -
the same convention as V1~V9 strategy-lab studies ("같은 날 유니버스 동일가중").
Excess = stock return - segment EW mean, computed per horizon so market
moves at one horizon do not contaminate another.

Regime flags are PIT-safe: volatility uses trailing windows only.
"""
from __future__ import annotations

import numpy as np
import pandas as pd


def segment_ew(df, value_col):
    """Per (date, market) equal-weight mean of value_col -> DataFrame
    [date, market, seg_mean]. Rows with NaN value_col are excluded from that
    mean (per-horizon denominator)."""
    g = (df.dropna(subset=[value_col])
           .groupby(["date", "market"])[value_col].mean().rename("seg_mean"))
    return g.reset_index()


def add_excess(events, ret_cols):
    """For each ret_col add '<col>_exc' = col - EW mean over the SAME date and
    market among the rows present in `events` (event-eligible universe).

    This keeps the benchmark consistent with the study sample; the ALL-market
    variant is available via market='ALL' rows if a caller adds them."""
    for col in ret_cols:
        m = events.dropna(subset=[col]).groupby(["date", "market"])[col].transform("mean")
        events[f"{col}_exc"] = events[col] - m
    return events


def day_regimes(panel):
    """One row per date with regime flags.

      kospi_ret / kosdaq_ret : segment EW open->close return of that day
      mkt_up / mkt_down      : sign of the stock's own segment return
      vol_hi / vol_lo        : trailing 20-session std of segment returns,
                               above/below its own EXPANDING median shifted
                               by one day (past-only threshold)
    """
    seg = (panel.dropna(subset=["day_ret_oc"])
                .groupby(["date", "market"])["day_ret_oc"].mean()
                .unstack("market"))
    out = pd.DataFrame(index=seg.index)
    for m in ("KOSPI", "KOSDAQ"):
        if m in seg.columns:
            out[f"{m.lower()}_ret"] = seg[m]
    # stock-side regime uses the stock's own segment when available
    own = panel[["date", "market", "day_ret_oc"]]
    seg_of_day = own.groupby(["date", "market"])["day_ret_oc"].mean()
    out["seg_ret_by_mkt"] = seg_of_day
    roll_std = seg.rolling(20, min_periods=10).std()
    thr = roll_std.expanding(min_periods=30).median().shift(1)
    out["vol_thr_kospi"] = thr.get("KOSPI")
    out["kospi_vol20"] = roll_std.get("KOSPI")
    out["kosdaq_vol20"] = roll_std.get("KOSDAQ")
    out["date"] = out.index
    return out.reset_index(drop=True)


def attach_regimes(events, regimes):
    """Merge per-date regime flags onto an event table."""
    r = regimes.rename(columns={
        "kospi_ret": "reg_kospi_ret", "kosdaq_ret": "reg_kosdaq_ret"})
    keep = ["date", "reg_kospi_ret", "reg_kosdaq_ret",
            "kospi_vol20", "kosdaq_vol20", "vol_thr_kospi"]
    keep = [k for k in keep if k in r.columns]
    return events.merge(r[keep], on="date", how="left")


def regime_masks(events):
    """Boolean masks dict over an event table with regime columns attached."""
    masks = {}
    kr = events.get("reg_kospi_ret")
    kd = events.get("reg_kosdaq_ret")
    if kr is not None:
        masks["kospi_up_day"] = kr > 0
        masks["kospi_down_day"] = kr < 0
    if kd is not None:
        masks["kosdaq_up_day"] = kd > 0
        masks["kosdaq_down_day"] = kd < 0
    if {"kospi_vol20", "vol_thr_kospi"}.issubset(events.columns):
        v, t = events["kospi_vol20"], events["vol_thr_kospi"]
        masks["kospi_volatile"] = v > t
        masks["kospi_calm"] = v <= t
    return {k: m.fillna(False) for k, m in masks.items()}
