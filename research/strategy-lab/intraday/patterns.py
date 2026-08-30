"""OPEN30 pattern classification (directive step 5).

Window: formation bars 09:00..09:29, decision price = as-of close at 09:30
(p_at30m). All thresholds parameterized; defaults documented.

Definitions (thr_up=thr_down=0.005, eps=0 by default):
  up_move  : w_high / open_price - 1 >= thr_up   (made an up-move)
  dn_move  : w_low  / open_price - 1 <= -thr_down (made a down-move)
  above    : p_at30m / open_price - 1 > +eps     (above open at 09:30)
  below    : p_at30m / open_price - 1 < -eps     (below open at 09:30)

  A FLAT             : neither up_move nor dn_move (range-limited window;
                       position at 09:30 irrelevant)
  B FAILED_UP        : (not dn_move) & up_move & below
  C HOLD_ABOVE_OPEN  : (not dn_move) & up_move & above
  D RECOVER_OPEN     : dn_move & above
  E FAILED_RECOVERY  : dn_move & below

Deterministic precedence when BOTH moves happened in a wide-range window
(contested cells resolved by PATH ORDER - documented convention, not a
discovered truth):
  - ends below open: high occurred BEFORE low -> FAILED_UP (morning rally
    reversed); otherwise -> FAILED_RECOVERY (dip, bounce attempt failed).
  - ends above open -> RECOVER_OPEN regardless of order (it did recover).

Boundary rule: p_at30m exactly at open counts as BOTH above and below
(eps=0 default), so such rows fall into the contested-cell resolution
instead of silently becoming FLAT.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

PATTERNS = ("FLAT", "FAILED_UP", "HOLD_ABOVE_OPEN",
            "RECOVER_OPEN", "FAILED_RECOVERY")


def classify_open30(df, thr_up=0.005, thr_down=None, eps=0.0):
    """Vectorized classification -> Series[str] with PATTERNS labels."""
    if thr_down is None:
        thr_down = thr_up
    op = df["open_price"].to_numpy(dtype=float)
    hi = df["w_high"].to_numpy(dtype=float)
    lo = df["w_low"].to_numpy(dtype=float)
    p30 = df["p_at30m"].to_numpy(dtype=float)
    with np.errstate(all="ignore"):
        up = np.isfinite(hi / op) & ((hi / op - 1.0) >= thr_up)
        dn = np.isfinite(lo / op) & ((lo / op - 1.0) <= -thr_down)
        rel = p30 / op - 1.0
    valid = np.isfinite(op) & np.isfinite(rel)
    above = rel >= eps
    below = rel <= -eps
    hbl = pd.to_numeric(df.get("hi_before_lo"), errors="coerce").to_numpy() == 1

    out = np.full(len(df), "FLAT", dtype=object)
    out[dn & below] = "FAILED_RECOVERY"
    out[dn & above] = "RECOVER_OPEN"
    out[~dn & up & below] = "FAILED_UP"
    out[~dn & up & above] = "HOLD_ABOVE_OPEN"
    out[~(up | dn)] = "FLAT"
    # contested cell: BOTH moves & ends below -> decide by extreme order
    out[(up & dn & below) & hbl] = "FAILED_UP"
    out[~valid] = None
    return pd.Series(out, index=df.index, dtype=object)


def classify_simple_baseline(df):
    """Naive baseline the directive asks to compare against: only the sign of
    the 09:30 price vs open - no path information at all."""
    op = df["open_price"].to_numpy(dtype=float)
    p30 = df["p_at30m"].to_numpy(dtype=float)
    rel = np.where((op > 0) & np.isfinite(p30), p30 / op - 1.0, np.nan)
    lab = np.full(len(df), None, dtype=object)
    lab[np.isfinite(rel) & (rel > 0)] = "SIMPLE_ABOVE_OPEN"
    lab[np.isfinite(rel) & (rel <= 0)] = "SIMPLE_BELOW_OPEN"
    return pd.Series(lab, index=df.index, dtype=object)
