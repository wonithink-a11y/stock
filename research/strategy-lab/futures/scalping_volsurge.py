#!/usr/bin/env python3
"""크립토 1분봉 거래량 급증 모멘텀 — 사전등록 findings/scalping-volsurge-preregistration-2026-09.md

    python research/strategy-lab/futures/scalping_volsurge.py            # 실행
    python research/strategy-lab/futures/scalping_volsurge.py --selftest
"""
from __future__ import annotations

import json
import sys
from multiprocessing import Pool
from pathlib import Path

import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from scalping_candidates import load, span, tstat, summarize, TRAIN, OOS_START, N_NULL  # noqa: E402

OUT = HERE.parent / "findings" / "scalping-volsurge-results-2026-09.json"
SEED = 20260928
LOOK = 60                                    # 기준 거래량 = 직전 60분 중앙값(현재 분 제외)
MS = (5.0, 10.0)
HS = (5, 15, 60)
SIDES = ("U", "D")                           # U = 급증 분이 양봉 → 롱 · D = 음봉 → 숏 (TRAIN 부호가 모멘텀/반전을 정한다)
CELLS = [(m, h, s) for m in MS for h in HS for s in SIDES]


def prep(b: pd.DataFrame) -> dict:
    v = b["volume"]
    base = v.shift(1).rolling(LOOK, min_periods=LOOK).median()
    with np.errstate(invalid="ignore", divide="ignore"):
        ratio = (v / base).to_numpy(float)
    body = (b["close"] - b["open"]).to_numpy(float)
    return {"idx": b.index, "open": b["open"].to_numpy(float), "ratio": ratio, "body": body}


def signal(P, m, side):
    with np.errstate(invalid="ignore"):
        return (P["ratio"] > m) & ((P["body"] > 0) if side == "U" else (P["body"] < 0))


def events(P, m, h, side, lo_i, hi_i, shift=0):
    sub = signal(P, m, side)[lo_i:hi_i + 1]
    if shift:
        sub = np.roll(sub, shift)
    o, n = P["open"], len(P["open"])
    sgn = 1.0 if side == "U" else -1.0
    out, last = [], -1
    for t in np.flatnonzero(sub) + lo_i:
        if t <= last:
            continue
        a, z = t + 1, t + 1 + h
        if z >= n or z > hi_i + 1:
            break
        if np.isfinite(o[a]) and np.isfinite(o[z]):
            out.append(sgn * (o[z] / o[a] - 1) * 1e4)
            last = z
    return np.array(out)


_P = {}


def _init(P):
    _P.update(P)


def _null_max(args):
    lo_i, hi_i, seed = args
    sh = int(np.random.default_rng(seed).integers(1440, hi_i - lo_i - 1440))
    return max(abs(tstat(events(_P, *c, lo_i, hi_i, sh))) for c in CELLS)


def _null_mean(args):
    cell, lo_i, hi_i, seed = args
    x = events(_P, *cell, lo_i, hi_i, int(np.random.default_rng(seed).integers(1440, hi_i - lo_i - 1440)))
    return float(x.mean()) if len(x) else np.nan


def with_pool(P, fn, args):
    with Pool(8, initializer=_init, initargs=(P,)) as pool:
        return pool.map(fn, args)


def main():
    btc = prep(load("BTCUSDT"))
    lo, hi = span(btc, *TRAIN)
    tr_all = [events(btc, *c, lo, hi) for c in CELLS]
    t_real = [tstat(x) for x in tr_all]
    mx = with_pool(btc, _null_max, [(lo, hi, SEED + i) for i in range(N_NULL)])
    floor = float(np.quantile(mx, 0.95))
    best = int(np.argmax(np.abs(t_real)))
    cell, s = CELLS[best], float(np.sign(t_real[best]))
    passed = abs(t_real[best]) >= floor
    o_lo, o_hi = span(btc, OOS_START, btc["idx"][-1])
    ob = events(btc, *cell, o_lo, o_hi)
    nb = with_pool(btc, _null_mean, [(cell, o_lo, o_hi, SEED + 5000 + i) for i in range(N_NULL)])
    del btc
    eth = prep(load("ETHUSDT"))
    e_lo, e_hi = span(eth, TRAIN[0], eth["idx"][-1])
    oe = events(eth, *cell, e_lo, e_hi)
    ne = with_pool(eth, _null_mean, [(cell, e_lo, e_hi, SEED + 9000 + i) for i in range(N_NULL)])
    sb, se = summarize(ob, s), summarize(oe, s)
    ex_b = sb["gross_bp"] - s * float(np.nanmean(nb)) if sb["n"] else None
    ex_e = se["gross_bp"] - s * float(np.nanmean(ne)) if se["n"] else None
    info = bool(passed and sb["n"] and se["n"] and sb["gross_bp"] > 0 and se["gross_bp"] > 0 and ex_b > 0 and ex_e > 0)
    econ = bool(info and sb["net10_bp"] > 0 and sb["net20_bp"] > 0 and se["net10_bp"] > 0)
    robust = bool(econ and sb["net10_t"] >= 2 and se["net10_t"] >= 2)
    verdict = "ROBUST" if robust else ("ECONOMIC" if econ else ("INFORMATION" if info else "REJECT"))
    res = {"floor_abs_t": floor, "null_max_abs_t_median": float(np.median(mx)), "n_cells": len(CELLS),
           "cells_train": [{"m": c[0], "h": c[1], "side": c[2], "t": t, "n": len(x),
                            "gross_bp": float(x.mean()) if len(x) else None}
                           for c, t, x in zip(CELLS, t_real, tr_all)],
           "selected": {"m": cell[0], "h": cell[1], "side": cell[2], "direction": "모멘텀" if s > 0 else "반전"},
           "train_t": t_real[best], "train_pass_floor": bool(passed), "train": summarize(tr_all[best], s),
           "oos_btc": sb, "oos_btc_shift_null_mean_signed": s * float(np.nanmean(nb)), "oos_btc_excess": ex_b,
           "eth": se, "eth_shift_null_mean_signed": s * float(np.nanmean(ne)), "eth_excess": ex_e, "verdict": verdict}
    OUT.write_text(json.dumps(res, ensure_ascii=False, indent=1, default=float), encoding="utf-8")
    print("floor", floor, "selected", res["selected"], "t", t_real[best], verdict)
    print("TRAIN", res["train"]); print("BTC OOS", sb, ex_b); print("ETH", se, ex_e)


def selftest():
    ok = 0
    idx = pd.date_range("2020-01-01", periods=LOOK + 10, freq="1min")
    o = np.linspace(100, 169, len(idx)); c = o + 0.5; v = np.full(len(idx), 10.0)
    v[LOOK + 2] = 120.0                                       # 12배 급증, 양봉
    b = pd.DataFrame({"open": o, "high": c, "low": o, "close": c, "volume": v}, index=idx)
    P = prep(b)
    assert np.isnan(P["ratio"][LOOK - 1]) and abs(P["ratio"][LOOK + 2] - 12.0) < 1e-9; ok += 1
    assert np.flatnonzero(signal(P, 10.0, "U")).tolist() == [LOOK + 2]; ok += 1
    assert not signal(P, 10.0, "D").any(); ok += 1
    x = events(P, 10.0, 5, "U", 0, len(o) - 1)               # 진입 = 다음 분 시가, 5분 뒤 시가 청산
    a = LOOK + 3
    assert len(x) == 1 and abs(x[0] - (o[a + 5] / o[a] - 1) * 1e4) < 1e-9, x; ok += 1
    print(f"selftest {ok}/4 OK")


if __name__ == "__main__":
    selftest() if "--selftest" in sys.argv else main()
