#!/usr/bin/env python3
"""KOSPI200 정기변경 편입·편출 — 사전등록 findings/kospi200-rebalance-preregistration-2026-10.md.

    python research/strategy-lab/kospi200_rebalance.py --selftest
    python research/strategy-lab/kospi200_rebalance.py      # → futures/ 가 아니라 findings 옆 json
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE / "futures"))
from short_horizon_study import null_bar, tstat  # noqa: E402

CHANGES = HERE / "data" / "kospi200-rebal" / "changes.json"
OUT = HERE / "findings" / "kospi200-rebalance-results-2026-10.json"
SEED = 20261017
COST, STRESS = 23.54, 33.5
CELLS = {"R1": ("added", -5, 0), "R2": ("removed", 0, 20)}
RECORD = {"R1_post": ("added", 0, 20), "R2_pre": ("removed", -5, 0)}


def split(y: int) -> str:
    return "TRAIN" if y <= 2019 else ("VALID" if y <= 2022 else "TEST")


def period(y: int) -> str:
    return "2014~23" if y <= 2023 else ("2024" if y == 2024 else "2025~")


def window(R: np.ndarray, ew: np.ndarray, j: int, i0: int, i1: int):
    """종가 i0 매수 → 종가 i1 매도 = 행 i0+1 .. i1 의 수익. (원수익, 초과) bp 또는 None."""
    r = R[i0 + 1:i1 + 1, j]
    if np.isnan(r).all():
        return None
    raw = np.prod(1 + np.nan_to_num(r)) - 1
    mk = np.prod(1 + ew[i0 + 1:i1 + 1]) - 1
    return raw * 1e4, (raw - mk) * 1e4


def events(dates, tick, R, ew, changes, spec):
    side, a, b = spec
    col = {t: k for k, t in enumerate(tick)}
    rows = []
    for k, v in changes.items():
        i = int(np.searchsorted(dates, pd.Timestamp(v["expiry"])))
        if i + b >= len(dates) or i + a < 0 or dates[i] != pd.Timestamp(v["expiry"]):
            continue
        for t in v[side]:
            w = window(R, ew, col[t], i + a, i + b) if t in col else None
            if w:
                rows.append({"chg": k, "year": int(k[:4]), "ticker": t, "raw": w[0], "ex": w[1]})
    return pd.DataFrame(rows)


def judge(df: pd.DataFrame, bar: float) -> dict:
    sp = df["year"].map(split)
    ex = {s: df.loc[sp == s, "ex"].to_numpy() for s in ("TRAIN", "VALID", "TEST")}
    tr = ex["TRAIN"]
    sg = np.sign(tr.mean())
    info = bool(abs(tstat(tr)) >= bar and sg > 0 and np.sign(ex["VALID"].mean()) == sg and np.sign(ex["TEST"].mean()) == sg)
    oos = df[sp != "TRAIN"]
    net = lambda c: (float(oos["raw"].mean() - c), float(oos["ex"].mean() - c))
    eco = info and min(net(COST)) > 0 and min(net(STRESS)) > 0
    rob = eco and tstat(oos["ex"].to_numpy() - COST) >= 2
    rng = np.random.default_rng(SEED)
    o = oos["ex"].to_numpy()
    ci = [round(float(np.percentile([rng.choice(o, len(o)).mean() for _ in range(2000)], q)), 1) for q in (2.5, 97.5)]
    v = "판정불가" if len(ex["TEST"]) < 20 else "ROBUST" if rob else "ECONOMIC" if eco else "INFORMATION" if info else "REJECT"
    by_chg = df.groupby("chg")["ex"].mean()
    csp = pd.Series(by_chg.index.str[:4].astype(int), index=by_chg.index).map(split)
    return {"verdict": v, "sign": int(sg), "t_train": round(tstat(tr), 2),
            **{s: {"n": int((sp == s).sum()), "ex_bp": round(float(df.loc[sp == s, "ex"].mean()), 1),
                   "raw_bp": round(float(df.loc[sp == s, "raw"].mean()), 1), "t": round(tstat(ex[s]), 2),
                   "t_by_change": round(tstat(by_chg[csp == s].to_numpy()), 2), "n_changes": int((csp == s).sum())}
               for s in ("TRAIN", "VALID", "TEST")},
            "oos_ex_bp": round(float(o.mean()), 1), "oos_ex_ci95": ci, "oos_raw_bp": round(float(oos["raw"].mean()), 1),
            "net_raw_ex": [round(x, 1) for x in net(COST)], "net_raw_ex_stress": [round(x, 1) for x in net(STRESS)],
            "t_net_ex": round(tstat(o - COST), 2), "breakeven_bp": round(min(oos["raw"].mean(), o.mean()), 1),
            "periods": {g: {"n": int(len(x)), "ex_bp": round(float(x["ex"].mean()), 1), "t": round(tstat(x["ex"].to_numpy()), 2)}
                        for g, x in df.groupby(df["year"].map(period))},
            "by_change_ex_bp": {k: round(float(x), 1) for k, x in by_chg.items()}}


def main():
    import krx_daily_panel as kp
    dates, tick, M, _, _ = kp.build()
    R = kp.clean_returns(M["R"])
    ew = np.nan_to_num(np.nanmean(R, axis=1))
    changes = json.loads(CHANGES.read_text(encoding="utf-8"))
    ev = {c: events(dates, tick, R, ew, changes, s) for c, s in CELLS.items()}
    rng = np.random.default_rng(SEED)
    bar = null_bar([d.loc[d["year"] <= 2019, "ex"].to_numpy() for d in ev.values()], rng)
    out = {"bar": round(bar, 2), "cells": {c: judge(d, bar) for c, d in ev.items()}, "record": {}}
    for c, s in RECORD.items():
        d = events(dates, tick, R, ew, changes, s)
        out["record"][c] = {sp: {"n": int(len(x)), "ex_bp": round(float(x["ex"].mean()), 1), "t": round(tstat(x["ex"].to_numpy()), 2)}
                            for sp, x in d.groupby(d["year"].map(split))}
    OUT.write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
    print(json.dumps(out, ensure_ascii=False, indent=1))


def selftest():
    dates = pd.bdate_range("2015-01-01", periods=60)
    tick = ["A", "B"]
    R = np.zeros((60, 2))
    R[31:36, 0] = 0.01          # A: 30 종가 → 35 종가 사이 매일 +1%
    ew = R.mean(axis=1)
    raw, ex = window(R, ew, 0, 30, 35)
    assert abs(raw - (1.01 ** 5 - 1) * 1e4) < 1e-6 and ex > 0
    ch = {"2015-06": {"expiry": str(dates[35].date()), "added": ["A"], "removed": ["B", "Z"]}}
    d = events(dates, tick, R, ew, ch, ("added", -5, 0))
    assert len(d) == 1 and abs(d["raw"].iloc[0] - raw) < 1e-9
    assert len(events(dates, tick, R, ew, ch, ("removed", 0, 20))) == 1      # Z 는 패널에 없음 → 빠짐
    assert window(np.full((10, 1), np.nan), np.zeros(10), 0, 2, 5) is None
    print("selftest 4/4 OK")


if __name__ == "__main__":
    selftest() if "--selftest" in sys.argv else main()
