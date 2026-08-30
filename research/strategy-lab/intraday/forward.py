"""Forward-return computation for event studies (directive steps 3/6).

PIT contract (hard rule):
  - Event features may only use data at or before the event mark.
  - Everything AFTER the event mark exists ONLY to compute forward returns.

Prices come from the 5-minute grid whose closes are AS-OF (last trade at or
before the mark), so missing bars never fabricate prices - an illiquid name
carries its last traded price; NaN when nothing has traded yet.

Horizons are measured on the same-session timeline. A horizon that would run
past the 15:30 close stays NaN (honest unknown); next-session outcomes are
provided separately from the NEXT session's panel rows.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from .session import hhmm_to_min

HORIZONS = (5, 10, 30, 60, 120)
CLOSE_MIN = 930          # 15:30 in minutes-since-midnight


def snap_to_grid(mark):
    """Round an hhmm int DOWN to the nearest 5-min grid mark (>=09:05).
    Returns int or None when nothing tradable precedes it."""
    if mark is None or (isinstance(mark, float) and not np.isfinite(mark)):
        return None
    m = (hhmm_to_min(int(mark)) // 5) * 5
    return m if m >= 545 else None


def _target_col(mark_min_plus_h):
    return f"c{(mark_min_plus_h // 60) * 100 + mark_min_plus_h % 60:04d}"


def attach_forward_returns(events, grid_closes, price_col,
                           event_mark_col="event_mark"):
    """Adds f005/f010/f030/f060/f120 = P(event+h)/P(event)-1 (same session).

    events needs: date, ticker, event_mark (hhmm int), <price_col>.
    grid_closes: DataFrame date,ticker + all c#### columns.
    """
    ev = events.copy().reset_index(drop=True)
    p = ev[price_col].to_numpy(dtype=float)
    snap = ev[event_mark_col].map(snap_to_grid).astype("float64")

    # per-horizon target column name per row (None = unobservable)
    target_lists = {}
    needed = set()
    for h in HORIZONS:
        lst = []
        sm = snap.to_numpy()
        for i in range(len(ev)):
            if not np.isfinite(sm[i]) or not np.isfinite(p[i]):
                lst.append(None)
                continue
            t = int(sm[i]) + h
            if t > CLOSE_MIN:
                lst.append(None)
                continue
            c = _target_col(t)
            lst.append(c)
            needed.add(c)
        target_lists[h] = lst

    cols = sorted(needed)
    base = ev[["date", "ticker"]].drop_duplicates(["date", "ticker"])
    sub = base.merge(grid_closes[["date", "ticker"] + cols],
                     on=["date", "ticker"], how="left")
    # map back to event row order
    key = ev["date"].astype(str) + "|" + ev["ticker"].astype(str)
    skey = sub["date"].astype(str) + "|" + sub["ticker"].astype(str)
    row_of_key = pd.Series(np.arange(len(sub)), index=skey)
    ridx = row_of_key.reindex(key).to_numpy()
    if np.isnan(ridx).any():
        raise RuntimeError("grid_closes missing some (date,ticker) event keys")
    ridx = ridx.astype(int)

    arr = sub[cols].to_numpy(dtype=float)
    pos = {c: j for j, c in enumerate(cols)}
    for h, lst in target_lists.items():
        out = np.full(len(ev), np.nan)
        codes_arr, uniques = pd.factorize(pd.Series(lst, dtype="object"))
        cat_index = {}
        for k, c in enumerate(uniques):
            if c is not None and c in pos:
                cat_index[k] = pos[c]
        code_arr = np.asarray(codes_arr)
        valid = np.isin(code_arr, list(cat_index.keys()))
        if valid.any():
            vr = np.where(valid)[0]
            vals = arr[ridx[vr], np.array([cat_index[code_arr[r]] for r in vr])]
            with np.errstate(all="ignore"):
                out[vr] = vals / p[vr] - 1.0
        ev[f"f{h:03d}"] = out
    return ev


def attach_close_and_next(events, grid_closes, next_day, price_col,
                          this_close_col="day_close"):
    """f_dayclose + next-session outcomes + overnight gap.

    overnight uses <this_close_col> on the event row (present when the caller
    merged the same-day panel close onto the events beforehand); NaN otherwise.
    """
    ev = events.merge(grid_closes[["date", "ticker", "c1530"]],
                      on=["date", "ticker"], how="left")
    p = ev[price_col]
    with np.errstate(all="ignore"):
        ev["f_dayclose"] = ev["c1530"] / p - 1.0
    nd = next_day[["ticker", "date", "next_open", "next_close"]]
    ev = ev.merge(nd, on=["ticker", "date"], how="left")
    with np.errstate(all="ignore"):
        ev["r_next_open"] = ev["next_open"] / p - 1.0
        ev["r_next_close"] = ev["next_close"] / p - 1.0
        if this_close_col in ev.columns:
            ev["overnight"] = ev["next_open"] / ev[this_close_col] - 1.0
        else:
            ev["overnight"] = np.nan
    return ev


def build_next_day(panel):
    """panel -> DataFrame[ticker, date(prev session), next_open, next_close].

    Pure numpy adjacency (sorted by ticker,date; successor kept only when the
    next row belongs to the SAME ticker). Avoids groupby-shift/to_numpy
    ordering pitfalls entirely.
    """
    s = panel.sort_values(["ticker", "date"])
    tk = s["ticker"].to_numpy()
    d = s["date"].to_numpy()
    op = s["day_open"].to_numpy()
    cl = s["day_close"].to_numpy()
    same = np.empty(len(tk), dtype=bool)
    same[:-1] = tk[:-1] == tk[1:]
    same[-1] = False
    idx = np.where(same)[0]
    return pd.DataFrame({
        "ticker": tk[idx],
        "date": d[idx],
        "next_open": op[idx + 1],
        "next_close": cl[idx + 1],
    })


def forward_returns(events, grid_closes, next_day, price_col="event_price",
                    event_mark_col="event_mark", this_close_col="day_close"):
    """Full outcome block for an event table.

    events should already carry the same-day close column (named by
    this_close_col) when the overnight gap is wanted.
    """
    ev = attach_forward_returns(events, grid_closes, price_col, event_mark_col)
    ev = attach_close_and_next(ev, grid_closes, next_day, price_col,
                               this_close_col)
    return ev
