#!/usr/bin/env python3
"""스캘핑 후보 중 미검증 두 갈래 — 사전등록 findings/scalping-candidates-preregistration-2026-09.md

  V: 크립토 1분봉 VWAP ±kσ 밴드 회귀(바이낸스 현물 BTCUSDT TRAIN 2018~21 · OOS 2022~ · ETHUSDT 전체)
  K7/K8: 국내 주식 5분 ORB 돌파 즉시 매수(거래량 조건 유무) — structure_phase4 의 K 인프라(K6 재테스트와 같은 OR 정의)

    python research/strategy-lab/futures/scalping_candidates.py            # 실행
    python research/strategy-lab/futures/scalping_candidates.py --selftest
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
from structure_phase4 import (KR, KR_FIXED_BP, KR_TICK_K, KR_TICK_K2, tick_bp, make_obs, family,  # noqa: E402
                              _first, MI, J1520, day_splitter)

LAB = HERE.parent
DATA = LAB / "data" / "crypto" / "1m"
OUT = LAB / "findings" / "scalping-candidates-results-2026-09.json"
SEED = 20260927
N_NULL = 200
SIDE_BP, STRESS_SIDE_BP = 5.0, 10.0
TRAIN = ("2018-01-01", "2021-12-31 23:59")
OOS_START = "2022-01-01"
WARM = 60                                   # UTC 자정 앵커 뒤 60분은 신호 없음(σ 안정화)
KS = (2.0, 3.0)
ENTRIES = ("T", "R")                         # T = 밴드 밖으로 나간 분 · R = 밴드 안으로 되돌아온 분(재진입 확인)
EXITS = (15, 60, 240, "V")                   # V = 종가가 VWAP 을 넘어선 다음 분 시가(최대 240분)
SIDES = ("L", "S")                           # L = 하단 → 롱 · S = 상단 → 숏
CELLS = [(k, e, x, s) for k in KS for e in ENTRIES for x in EXITS for s in SIDES]
V_CAP = 240
K_FAMILY_BAR = 2.86                          # structure-patterns K 가족 바닥선 — K7/K8 은 그 가족의 확장이라 더 엄한 쪽을 쓴다


# ---- 크립토 VWAP 밴드 ------------------------------------------------------------
def load(sym: str) -> pd.DataFrame:
    b = pd.read_parquet(DATA / f"{sym}_1m.parquet", columns=["open_time_utc", "open", "high", "low", "close", "volume"])
    b = b.set_index("open_time_utc").sort_index()
    b = b[~b.index.duplicated()]
    return b.asfreq("1min")


def prep(b: pd.DataFrame) -> dict:
    """UTC 자정 앵커 VWAP 과 거래량가중 표준편차. 봉 t 의 값은 t 종가까지의 정보만 쓴다."""
    tp = ((b["high"] + b["low"] + b["close"]) / 3).to_numpy(float)
    v = b["volume"].to_numpy(float)
    bad = ~(np.isfinite(tp) & np.isfinite(v))
    tp, v = np.where(bad, 0.0, tp), np.where(bad, 0.0, v)
    day = b.index.floor("D")
    g = pd.DataFrame({"v": v, "tv": tp * v, "tv2": tp * tp * v}, index=b.index).groupby(day).cumsum()
    cv = g["v"].to_numpy()
    with np.errstate(invalid="ignore", divide="ignore"):
        vwap = g["tv"].to_numpy() / cv
        sd = np.sqrt(np.clip(g["tv2"].to_numpy() / cv - vwap ** 2, 0, None))
        z = (b["close"].to_numpy(float) - vwap) / sd
    mod = (b.index - day).total_seconds().to_numpy() // 60
    z[(mod < WARM) | ~np.isfinite(z)] = np.nan
    return {"idx": b.index, "open": b["open"].to_numpy(float), "z": z,
            "up": np.flatnonzero(z >= 0), "dn": np.flatnonzero(z <= 0)}


def span(P, lo, hi):
    idx = P["idx"]
    return int(np.searchsorted(idx, pd.Timestamp(lo))), int(np.searchsorted(idx, pd.Timestamp(hi), side="right")) - 1


def signal(P, k, ent, side):
    zz = P["z"] if side == "L" else -P["z"]
    prev = np.roll(zz, 1)
    prev[0] = np.nan
    with np.errstate(invalid="ignore"):
        return ((prev > -k) & (zz <= -k)) if ent == "T" else ((prev <= -k) & (zz > -k))


def events(P, k, ent, x, side, lo_i, hi_i, shift=0):
    """셀 방향 수익(bp). 체결 = 신호 다음 분 시가, 청산 = 시가. 같은 셀 안 비중첩. shift = 바닥선용 순환 이동."""
    hit = signal(P, k, ent, side)
    sub = hit[lo_i:hi_i + 1]
    if shift:
        sub = np.roll(sub, shift)
    o, n = P["open"], len(P["open"])
    cross = P["up"] if side == "L" else P["dn"]
    sgn = 1.0 if side == "L" else -1.0
    out, last = [], -1
    for t in np.flatnonzero(sub) + lo_i:
        if t <= last:
            continue
        a = t + 1
        if x == "V":
            j = np.searchsorted(cross, a)
            z = min(cross[j] + 1, a + V_CAP) if j < len(cross) else a + V_CAP
        else:
            z = a + x
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


_P = {}


def _init(P):
    _P.update(P)


def _null_max(args):
    lo_i, hi_i, seed = args
    rng = np.random.default_rng(seed)
    sh = int(rng.integers(1440, hi_i - lo_i - 1440))
    return max(abs(tstat(events(_P, *c, lo_i, hi_i, sh))) for c in CELLS)


def _null_mean(args):
    cell, lo_i, hi_i, seed = args
    rng = np.random.default_rng(seed)
    x = events(_P, *cell, lo_i, hi_i, int(rng.integers(1440, hi_i - lo_i - 1440)))
    return float(x.mean()) if len(x) else np.nan


def summarize(x, s):
    y = s * np.asarray(x, float)
    rng = np.random.default_rng(SEED)
    boot = [rng.choice(y, len(y)).mean() for _ in range(2000)] if len(y) > 2 else [np.nan]
    n10, n20 = y - 2 * SIDE_BP, y - 2 * STRESS_SIDE_BP
    return {"n": int(len(y)), "gross_bp": float(y.mean()) if len(y) else None,
            "gross_ci95": [float(np.quantile(boot, .025)), float(np.quantile(boot, .975))],
            "gross_t": tstat(y), "net10_bp": float(n10.mean()) if len(y) else None, "net10_t": tstat(n10),
            "net20_bp": float(n20.mean()) if len(y) else None, "breakeven_roundtrip_bp": float(y.mean()) if len(y) else None}


def with_pool(P, fn, args):
    with Pool(8, initializer=_init, initargs=(P,)) as pool:
        return pool.map(fn, args)


def run_crypto():
    btc = prep(load("BTCUSDT"))
    lo, hi = span(btc, *TRAIN)
    t_real = [tstat(events(btc, *c, lo, hi)) for c in CELLS]
    n_real = [len(events(btc, *c, lo, hi)) for c in CELLS]
    mx = with_pool(btc, _null_max, [(lo, hi, SEED + i) for i in range(N_NULL)])
    floor = float(np.quantile(mx, 0.95))
    best = int(np.argmax(np.abs(t_real)))
    cell, s = CELLS[best], float(np.sign(t_real[best]))
    passed = abs(t_real[best]) >= floor
    tr = events(btc, *cell, lo, hi)
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
    info = bool(passed and sb["n"] and se["n"] and sb["gross_bp"] > 0 and se["gross_bp"] > 0
                and ex_b > 0 and ex_e > 0)
    econ = bool(info and sb["net10_bp"] > 0 and sb["net20_bp"] > 0 and se["net10_bp"] > 0)
    robust = bool(econ and sb["net10_t"] >= 2 and se["net10_t"] >= 2)
    verdict = "ROBUST" if robust else ("ECONOMIC" if econ else ("INFORMATION" if info else "REJECT"))
    return {"floor_abs_t": floor, "null_max_abs_t_median": float(np.median(mx)), "n_cells": len(CELLS),
            "cells_train": [{"k": c[0], "entry": c[1], "exit": c[2], "side": c[3], "t": t, "n": n}
                            for c, t, n in zip(CELLS, t_real, n_real)],
            "selected": {"k": cell[0], "entry": cell[1], "exit": cell[2], "side": cell[3],
                         "direction": "회귀" if s > 0 else "추세"},
            "train_t": t_real[best], "train_pass_floor": bool(passed), "train": summarize(tr, s),
            "oos_btc": sb, "oos_btc_shift_null_mean_signed": s * float(np.nanmean(nb)), "oos_btc_excess": ex_b,
            "eth": se, "eth_shift_null_mean_signed": s * float(np.nanmean(ne)), "eth_excess": ex_e,
            "verdict": verdict}


# ---- 국내 ORB 돌파 즉시 매수 ------------------------------------------------------
def d_orb(A, p, vol):
    """OR = 첫 3봉 고가. 11:00 까지 종가 > ORH x (1+bo) 인 첫 봉(vol 이면 그 봉 거래량 > 3 x 직전 최대 6봉 평균도)."""
    h, c, v = A["h"], A["c"], A["v"]
    orh = np.nanmax(h[:, :3], 1)
    dec = np.full(len(c), -1)
    for j in range(3, MI["1100"] + 1):
        m = c[:, j] > orh * (1 + p["bo"])
        if vol:
            with np.errstate(invalid="ignore"):
                m &= v[:, j] > 3.0 * np.nanmean(v[:, max(0, j - 6):j], 1)
        _first(dec, m, j)
    return dec


KR_ORB_CELLS = {"K7a": (False, "a"), "K7b": (False, "b"), "K8a": (True, "a"), "K8b": (True, "b")}


def run_kr():
    kr = KR()
    A, rows = kr.A, np.arange(len(kr.A["c"]))
    obs, counts = {}, {}
    for vol in (False, True):
        dec = d_orb(A, {"bo": 0.003}, vol)
        e = dec + 1
        ok = (dec >= 0) & (e < A["c"].shape[1])
        px = np.full(len(dec), np.nan)
        px[ok] = A["c"][rows[ok], e[ok]]
        counts["orb_vol" if vol else "orb"] = int((dec >= 0).sum())
        for cid, (cv, ex) in KR_ORB_CELLS.items():
            if cv != vol:
                continue
            exit_col = (lambda ee: ee + 6) if ex == "a" else (lambda ee: np.full(len(ee), J1520))
            obs[cid] = make_obs(dec, e, px, exit_col, 1, A["c"], lambda r, k: kr.I[r, k], kr.dates,
                                lambda pp: (KR_FIXED_BP + KR_TICK_K * tick_bp(pp), KR_FIXED_BP + KR_TICK_K2 * tick_bp(pp)),
                                lambda ee, xx: (ee <= J1520) & (xx <= J1520) & (xx > ee))
    sd = sorted(kr.meta["date"].unique())
    res = family(obs, day_splitter(sd), np.random.default_rng(SEED), {c: {"long_only": True} for c in obs})
    own = res["bar"]
    if own < K_FAMILY_BAR:                   # 더 엄한 바닥선으로 다시 판정(사전등록 §2)
        from structure_phase4 import judge
        splitter = day_splitter(sd)
        parts = {}
        for cid, ev in obs.items():
            p = {k: ([], [], [], []) for k in ("TRAIN", "VALID", "TEST")}
            for dt, i, g, c1, c2 in ev:
                b = p[splitter(dt)]
                b[0].append(i); b[1].append(g); b[2].append(c1); b[3].append(c2)
            parts[cid] = {k: tuple(np.array(x, float) for x in v) for k, v in p.items()}
        res["cells"] = {c: judge(parts[c], K_FAMILY_BAR, long_only=True) for c in parts}
        res["bar"] = K_FAMILY_BAR
    res.update({"own_bar": own, "event_counts": counts, "span": [sd[0], sd[-1], len(sd)]})
    return res


def main():
    out = {"K": run_kr()}
    print("K bar", out["K"]["bar"], "own", out["K"]["own_bar"], out["K"]["event_counts"])
    for c, r in out["K"]["cells"].items():
        print(c, json.dumps(r, ensure_ascii=False))
    out["V"] = run_crypto()
    v = out["V"]
    print("V floor", v["floor_abs_t"], "selected", v["selected"], "t", v["train_t"], v["verdict"])
    print("TRAIN", v["train"]); print("BTC OOS", v["oos_btc"], v["oos_btc_excess"]); print("ETH", v["eth"], v["eth_excess"])
    OUT.write_text(json.dumps(out, ensure_ascii=False, indent=1, default=float), encoding="utf-8")


def selftest():
    ok = 0
    # 1) VWAP·σ: 같은 날 두 분, 가격 100(거래량 1)·102(거래량 3) → VWAP 101.5, σ = sqrt(3/4·(0.5²)+1/4·(1.5²)) = sqrt(0.75)
    idx = pd.date_range("2020-01-01", periods=WARM + 3, freq="1min")
    px = np.full(len(idx), 100.0); vol = np.zeros(len(idx)); vol[0] = 1
    px[WARM:] = 102.0; vol[WARM] = 3
    b = pd.DataFrame({"open": px, "high": px, "low": px, "close": px, "volume": vol}, index=idx)
    P = prep(b)
    assert np.isnan(P["z"][WARM - 1]), "워밍업 구간은 신호 없음"; ok += 1
    assert abs(P["z"][WARM] - 0.5 / np.sqrt(0.75)) < 1e-9, P["z"][WARM]; ok += 1
    # 2) 신호·체결: z 경로를 직접 넣어 T/R·청산 확인
    n = 30
    P = {"idx": pd.date_range("2020-01-01", periods=n, freq="1min"), "open": np.linspace(100, 129, n),
         "z": np.array([0.0] * 5 + [-2.5, -2.2, -1.5, -0.5, 0.3] + [0.0] * 20)}
    P["up"], P["dn"] = np.flatnonzero(P["z"] >= 0), np.flatnonzero(P["z"] <= 0)
    assert np.flatnonzero(signal(P, 2.0, "T", "L")).tolist() == [5]; ok += 1
    assert np.flatnonzero(signal(P, 2.0, "R", "L")).tolist() == [7]; ok += 1
    x = events(P, 2.0, "T", 3, "L", 0, n - 1)                 # 진입 6분 시가 106 → 9분 시가 109
    assert len(x) == 1 and abs(x[0] - (109 / 106 - 1) * 1e4) < 1e-9, x; ok += 1
    x = events(P, 2.0, "R", "V", "L", 0, n - 1)               # 진입 8분 시가 108, VWAP 넘은 첫 분 = 9 → 10분 시가 110
    assert len(x) == 1 and abs(x[0] - (110 / 108 - 1) * 1e4) < 1e-9, x; ok += 1
    xs = events(P, 2.0, "T", 3, "S", 0, n - 1)                # 상단 신호 없음
    assert len(xs) == 0; ok += 1
    # 3) ORB: 첫 3봉 고가 100.5, 5번 봉 종가 101(> 100.8) → 결정 5, 거래량 조건이면 5번 봉 거래량이 3배를 넘어야 함
    T = MI["1100"] + 5
    A = {"h": np.full((2, T), 100.5), "c": np.full((2, T), 100.0), "v": np.full((2, T), 1000.0)}
    A["c"][:, 5] = 101.0
    assert d_orb(A, {"bo": 0.003}, False).tolist() == [5, 5]; ok += 1
    A["v"][0, 5] = 3500.0
    assert d_orb(A, {"bo": 0.003}, True).tolist() == [5, -1]; ok += 1
    print(f"selftest {ok}/9 OK")


if __name__ == "__main__":
    selftest() if "--selftest" in sys.argv else main()
