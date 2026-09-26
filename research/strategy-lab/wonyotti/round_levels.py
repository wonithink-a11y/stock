#!/usr/bin/env python3
"""어림수 가격 반응(지지·저항) — 사전등록 findings/round-number-levels-preregistration-2026-09.md

    python research/strategy-lab/wonyotti/round_levels.py            # 실행
    python research/strategy-lab/wonyotti/round_levels.py --selftest
"""
from __future__ import annotations

import json
import sys
from multiprocessing import Pool
from pathlib import Path

import numpy as np
import pandas as pd

LAB = Path(__file__).resolve().parents[1]
DATA = LAB / "data" / "crypto" / "1m"
OUT = LAB / "findings" / "round-number-levels-results-2026-09.json"
SIDE_BP = 5.0
STRESS_SIDE_BP = 10.0
N_NULL = 200
SEED = 20260926
TRAIN = ("2018-01-01", "2021-12-31 23:59")
OOS_START = "2022-01-01"

GRAN = (1.0, 0.5, 0.1)     # 유효숫자 둘째 자리 단위의 배수: 1 = 예) BTC 6만 → 1,000달러 · 0.5 → 500 · 0.1 → 100
WS = (60, 240)             # 직전 W 분 동안 수준에 닿지 않았어야 한다
HS = (15, 60, 240)         # 보유 분
TYPES = ("S", "R")         # S = 위에서 내려와 닿음 → 롱(반등) · R = 아래에서 올라와 닿음 → 숏(반락)
CELLS = [(g, w, h, ty) for g in GRAN for w in WS for h in HS for ty in TYPES]


def load(sym: str) -> pd.DataFrame:
    b = pd.read_parquet(DATA / f"{sym}_1m.parquet", columns=["open_time_utc", "open", "high", "low", "close"])
    b = b.set_index("open_time_utc").sort_index()
    b = b[~b.index.duplicated()]
    return b.asfreq("1min")


def prep(b: pd.DataFrame) -> dict:
    ref = b["close"].shift(1).ffill()
    base = 10.0 ** (np.floor(np.log10(ref)) - 1)
    P = {"idx": b.index, "open": b["open"].to_numpy(float), "high": b["high"].to_numpy(float),
         "low": b["low"].to_numpy(float), "base": base.to_numpy(float)}
    for w in WS:
        P[f"minp{w}"] = b["low"].shift(1).rolling(w, min_periods=w).min().to_numpy(float)
        P[f"maxp{w}"] = b["high"].shift(1).rolling(w, min_periods=w).max().to_numpy(float)
    return P


def levels(prev_ext, G, off, ty):
    """S: 직전 최저가보다 엄격히 아래의 가장 가까운 격자 수준 · R: 직전 최고가보다 엄격히 위의 가장 가까운 격자 수준.
    격자 = off·G + n·G (off = 0 이 진짜 어림수)."""
    if ty == "S":
        return G * (np.ceil((prev_ext - off * G) / G) - 1) + off * G
    return G * (np.floor((prev_ext - off * G) / G) + 1) + off * G


def events(P, g, w, h, ty, off, lo_i, hi_i):
    """부호 붙인 수익(bp) 배열 — 체결 = 다음 분 시가, 청산 = 그 뒤 h 분 시가. 같은 셀 안 비중첩."""
    G = P["base"] * g
    if ty == "S":
        X = levels(P[f"minp{w}"], G, off, "S")
        hit = P["low"] <= X
        sgn = 1.0
    else:
        X = levels(P[f"maxp{w}"], G, off, "R")
        hit = P["high"] >= X
        sgn = -1.0
    hit = hit & np.isfinite(X)
    hit[:lo_i] = False
    hit[hi_i + 1:] = False
    o = P["open"]
    n = len(o)
    out, last = [], -1
    for t in np.flatnonzero(hit):
        if t <= last:
            continue
        a, z = t + 1, t + 1 + h
        if z >= n or z > hi_i + 1:
            break
        if not (np.isfinite(o[a]) and np.isfinite(o[z])):
            continue
        out.append(sgn * (o[z] / o[a] - 1) * 1e4)
        last = z
    return np.array(out)


def tstat(x) -> float:
    x = np.asarray(x, float)
    return float(x.mean() / (x.std(ddof=1) / np.sqrt(len(x)))) if len(x) > 2 and x.std(ddof=1) > 0 else 0.0


def span(P, lo, hi):
    idx = P["idx"]
    return int(np.searchsorted(idx, pd.Timestamp(lo))), int(np.searchsorted(idx, pd.Timestamp(hi), side="right")) - 1


def all_t(P, off, lo_i, hi_i):
    return [tstat(events(P, g, w, h, ty, off, lo_i, hi_i)) for g, w, h, ty in CELLS]


def _null(args):
    P, lo_i, hi_i, seed = args
    off = float(np.random.default_rng(seed).uniform(0.1, 0.9))
    return max(abs(t) for t in all_t(P, off, lo_i, hi_i))


def _null_mean(args):
    P, cell, lo_i, hi_i, seed = args
    off = float(np.random.default_rng(seed).uniform(0.1, 0.9))
    x = events(P, *cell, off, lo_i, hi_i)
    return float(x.mean()) if len(x) else np.nan


def summarize(x, s):
    """s = TRAIN 부호(검정 방향). x 는 셀 방향 수익."""
    y = s * np.asarray(x, float)
    rng = np.random.default_rng(SEED)
    boot = [rng.choice(y, len(y)).mean() for _ in range(2000)] if len(y) > 2 else [np.nan]
    n10, n20 = y - 2 * SIDE_BP, y - 2 * STRESS_SIDE_BP
    return {"n": int(len(y)), "gross_bp": float(y.mean()) if len(y) else None,
            "gross_ci95": [float(np.quantile(boot, .025)), float(np.quantile(boot, .975))],
            "gross_t": tstat(y), "net10_bp": float(n10.mean()) if len(y) else None, "net10_t": tstat(n10),
            "net20_bp": float(n20.mean()) if len(y) else None, "breakeven_roundtrip_bp": float(y.mean()) if len(y) else None}


def main():
    btc = prep(load("BTCUSDT"))
    lo, hi = span(btc, *TRAIN)
    t_real = all_t(btc, 0.0, lo, hi)
    with Pool(8) as pool:
        mx = pool.map(_null, [(btc, lo, hi, SEED + k) for k in range(N_NULL)])
    floor = float(np.quantile(mx, 0.95))
    order = np.argsort(np.abs(t_real))[::-1]
    best = int(order[0])
    cell = CELLS[best]
    s = float(np.sign(t_real[best]))
    passed = abs(t_real[best]) >= floor
    tr = events(btc, *cell, 0.0, lo, hi)
    o_lo, o_hi = span(btc, OOS_START, btc["idx"][-1])
    ob = events(btc, *cell, 0.0, o_lo, o_hi)
    eth = prep(load("ETHUSDT"))
    e_lo, e_hi = span(eth, TRAIN[0], eth["idx"][-1])
    oe = events(eth, *cell, 0.0, e_lo, e_hi)
    with Pool(8) as pool:
        nb = pool.map(_null_mean, [(btc, cell, o_lo, o_hi, SEED + 5000 + k) for k in range(N_NULL)])
        ne = pool.map(_null_mean, [(eth, cell, e_lo, e_hi, SEED + 9000 + k) for k in range(N_NULL)])
    sb, se = summarize(ob, s), summarize(oe, s)
    ex_b = sb["gross_bp"] - s * float(np.nanmean(nb)) if sb["n"] else None
    ex_e = se["gross_bp"] - s * float(np.nanmean(ne)) if se["n"] else None
    info = bool(passed and sb["gross_bp"] and sb["gross_bp"] > 0 and se["gross_bp"] and se["gross_bp"] > 0
                and ex_b is not None and ex_b > 0 and ex_e is not None and ex_e > 0)
    econ = bool(info and sb["net10_bp"] > 0 and sb["net20_bp"] > 0 and se["net10_bp"] > 0)
    robust = bool(econ and sb["net10_t"] >= 2 and se["net10_t"] >= 2)
    verdict = "ROBUST" if robust else ("ECONOMIC" if econ else ("INFORMATION" if info else "REJECT"))
    res = {"floor_abs_t": floor, "null_max_abs_t_median": float(np.median(mx)), "n_cells": len(CELLS),
           "cells_train": [{"gran": c[0], "W": c[1], "h": c[2], "type": c[3], "t": t} for c, t in zip(CELLS, t_real)],
           "selected": {"gran": cell[0], "W": cell[1], "h": cell[2], "type": cell[3], "direction": "반전" if s > 0 else "지속"},
           "train_t": t_real[best], "train_pass_floor": bool(passed), "train": summarize(tr, s),
           "oos_btc": sb, "oos_btc_fake_grid_mean_signed": s * float(np.nanmean(nb)), "oos_btc_excess_vs_fake": ex_b,
           "eth": se, "eth_fake_grid_mean_signed": s * float(np.nanmean(ne)), "eth_excess_vs_fake": ex_e,
           "verdict": verdict}
    OUT.write_text(json.dumps(res, ensure_ascii=False, indent=1, default=float), encoding="utf-8")
    print(json.dumps({k: res[k] for k in ("floor_abs_t", "selected", "train_t", "train_pass_floor", "verdict")}, ensure_ascii=False))
    print("TRAIN", res["train"]); print("BTC OOS", sb, "excess", ex_b); print("ETH", se, "excess", ex_e)


def selftest():
    ok = 0
    # 1) 격자 수준: 60,000 정확히 → 엄격히 아래 59,000 · 위 61,000 / 가짜 격자 off 0.5
    G = np.array([1000.0])
    assert levels(np.array([60000.0]), G, 0, "S")[0] == 59000 and levels(np.array([60000.0]), G, 0, "R")[0] == 61000; ok += 1
    assert levels(np.array([60200.0]), G, 0.5, "S")[0] == 59500 and levels(np.array([60200.0]), G, 0.5, "R")[0] == 60500; ok += 1
    # 2) 합성 경로: 60,300 에서 60,000 을 건드리고 반등 → S 이벤트 1건, 수익 = 다음 분 시가(60,200) → 그 뒤 h=2 분 시가(60,500)
    idx = pd.date_range("2020-01-01", periods=12, freq="1min")
    o = np.array([60300, 60300, 60300, 60300, 60100, 60050, 60200, 60400, 60500, 60500, 60500, 60500], float)
    lo = o.copy(); lo[5] = 59990
    b = pd.DataFrame({"open": o, "high": o + 10, "low": lo, "close": o}, index=idx)
    global WS
    WS_saved, WS = WS, (3,)
    try:
        P = prep(b)
        x = events(P, 1.0, 3, 2, "S", 0.0, 0, len(o) - 1)
        assert len(x) == 1 and abs(x[0] - (60500 / 60200 - 1) * 1e4) < 1e-9, x; ok += 1
        # 가짜 격자(off 0.5 → 59,500·60,500): 저가 59,990 은 59,500 에 안 닿음 → 이벤트 0
        assert len(events(P, 1.0, 3, 2, "S", 0.5, 0, len(o) - 1)) == 0; ok += 1
    finally:
        WS = WS_saved
    print(f"selftest {ok}/4 OK")


if __name__ == "__main__":
    selftest() if "--selftest" in sys.argv else main()
