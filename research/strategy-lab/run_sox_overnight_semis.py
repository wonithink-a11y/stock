#!/usr/bin/env python3
"""밤사이 SOX 상승 → 한국 반도체 시초가 매수·종가 매도. 사전등록: findings/sox-overnight-kr-semis-open-preregistration-2026-10.md (문서가 우선).

  python run_sox_overnight_semis.py --selftest
  python run_sox_overnight_semis.py      # 정식: 사전등록·이 코드가 커밋된 깨끗한 상태에서만
"""
import argparse
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE / "futures"))
import run_sector_rise_study as rs                      # noqa: E402
from run_sector_follower_catchup import semi_mask      # noqa: E402
from us_overnight_study import overnight, zpast, nw    # noqa: E402

PREREG = HERE / "findings" / "sox-overnight-kr-semis-open-preregistration-2026-10.md"
US_CSV = HERE / ".cache" / "us_overnight" / "us_close.csv"
OUT = HERE / "reports" / "2026-10-sox-overnight-semis" / "results.json"
START = "2016-01-04"
Z_EVENT = 1.0
COST_BP = 23.5
MAX_GAP = 0.35
PERIODS = [("TRAIN", "2016-01-01", "2020-12-31"), ("VALID", "2021-01-01", "2022-12-31"), ("TEST", "2023-01-01", "9999-12-31")]
ERAS = [("2016~23", "2016-01-01", "2023-12-31"), ("2024", "2024-01-01", "2024-12-31"), ("2025~", "2025-01-01", "9999-12-31")]
N_SHIFT, SHIFT_MIN, N_BOOT = 1000, 60, 2000


def basket(C, O, Cprev, mask_t):
    """mask_t: (날짜 × 종목) 바스켓 포함 여부 → 일별 등가중 장중·갭 수익."""
    ok = mask_t & (O > 0) & (C > 0) & (Cprev > 0)
    gap = np.where(ok, O / Cprev - 1, np.nan)
    ok &= np.abs(np.nan_to_num(gap, nan=9)) <= MAX_GAP
    y = np.where(ok, C / O - 1, np.nan)
    g = np.where(ok, gap, np.nan)
    with np.errstate(all="ignore"):
        n = ok.sum(1)
        return np.where(n > 0, np.nansum(y, 1) / np.maximum(n, 1), np.nan), np.where(n > 0, np.nansum(g, 1) / np.maximum(n, 1), np.nan)


def nw_t(y, ev):
    d = pd.DataFrame({"y": y, "e": ev.astype(float)}).dropna()
    if d.e.sum() < 5 or (1 - d.e).sum() < 5:
        return np.nan, np.nan
    c, t, _ = nw(d.y.to_numpy(), d.e.to_numpy())
    return c, t


def span(dates, lo, hi):
    return (dates >= lo) & (dates <= hi)


def summarize(dates, y, gap, ev, rng):
    out = {}
    for name, lo, hi in PERIODS + ERAS + [("ALL", "2016-01-01", "9999-12-31")]:
        m = span(dates, lo, hi) & ~np.isnan(y) & ~np.isnan(ev)
        e = m & (ev == 1)
        c, t = nw_t(y[m], ev[m])
        ye = y[e]
        if len(ye) >= 3:
            bs = rng.choice(ye, (N_BOOT, len(ye))).mean(1)
            ci = [float(np.quantile(bs, .05)) * 1e4, float(np.quantile(bs, .95)) * 1e4]
        else:
            ci = [np.nan, np.nan]
        mean = float(ye.mean()) * 1e4 if len(ye) else np.nan
        out[name] = {"n_event": int(e.sum()), "n_days": int(m.sum()), "event_bp": mean, "ci90_bp": ci, "net_bp": mean - COST_BP,
                     "nonevent_bp": float(np.nanmean(y[m & (ev == 0)])) * 1e4, "diff_bp": c * 1e4 if c == c else np.nan, "t": t,
                     "event_gap_bp": float(np.nanmean(gap[e])) * 1e4 if len(ye) else np.nan, "hit": float((ye > 0).mean()) if len(ye) else np.nan}
    return out


def shift_floor(dates, ys, ev, rng):
    tr = span(dates, *PERIODS[0][1:])
    n = len(ev)
    mx = []
    for k in rng.integers(SHIFT_MIN, n - SHIFT_MIN, N_SHIFT):
        es = np.roll(ev, k)
        mx.append(max(abs(nw_t(y[tr], es[tr])[1]) for y in ys))
    return max(2.0, float(np.nanquantile(mx, .95)))


def judge(s, floor):
    tr, va, te = s["TRAIN"], s["VALID"], s["TEST"]
    info = tr["diff_bp"] > 0 and tr["t"] >= floor and va["diff_bp"] > 0 and te["diff_bp"] > 0
    econ = all(x["net_bp"] > 0 for x in (tr, va, te))
    return "ECONOMIC" if (econ and info) else ("INFORMATION" if info else ("ECONOMIC-only(신호 없음)" if econ else "REJECT"))


def selftest():
    def ok(c, m):
        if not c:
            print("selftest 실패:", m); sys.exit(1)
    D = 6
    C = np.array([[100, 100], [110, 100], [110, 100], [100, 100], [100, 200], [100, 100]], float)
    O = np.array([[100, 100], [100, 100], [121, 100], [100, 100], [100, 100], [100, 100]], float)
    Cp = np.vstack([np.full((1, 2), np.nan), C[:-1]])
    m = np.ones((D, 2), bool)
    y, g = basket(C, O, Cp, m)
    ok(abs(y[1] - 0.05) < 1e-12, f"등가중 장중 {y[1]}")             # (110/100−1 + 0)/2
    ok(abs(g[2] - (0.10 + 0) / 2) < 1e-12, f"갭 {g[2]}")             # 121/110−1 = 0.10
    ok(abs(y[2] - (110 / 121 - 1) / 2) < 1e-12, "장중은 시가 기준")
    ok(np.isnan(y[0]), "첫날 전일 종가 없음")
    # 갭 35% 초과 종목 제외: 5일째 종목 1 의 전일 200 → 시가 100 (−50%)
    ok(abs(y[5] - 0.0) < 1e-12 and abs(g[5] - 0.0) < 1e-12, f"큰 갭 제외 {y[5]} {g[5]}")
    # 정렬: 미국 금요일(d) 은 한국 월요일 t 의 밤사이, 미국 월요일은 한국 월요일에 안 들어간다
    us = pd.DataFrame({"^SOX": [100, 110, 121]}, index=pd.to_datetime(["2026-01-01", "2026-01-02", "2026-01-05"]))
    kr = pd.DatetimeIndex(pd.to_datetime(["2026-01-02", "2026-01-05", "2026-01-06"]))
    on, _ = overnight(us, kr)
    ok(abs(on.loc["2026-01-05", "^SOX"] - 0.10) < 1e-12 and abs(on.loc["2026-01-06", "^SOX"] - 0.10) < 1e-12, f"정렬 {on}")
    print("selftest OK - run_sox_overnight_semis")
    return 0


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--selftest", action="store_true")
    if ap.parse_args().selftest:
        return selftest()
    for p in (PREREG, Path(__file__).resolve()):
        if not rs.committed_clean(p):
            print(f"{p.name} 가 커밋되지 않았거나 수정 중 - 계산하지 않는다")
            return 2
    rng = np.random.default_rng(20261011)
    dates, tickers, groups, C, O, V, common, gid = rs.load_all()
    us = pd.read_csv(US_CSV, index_col=0, parse_dates=True)[["^SOX"]]
    kr = pd.DatetimeIndex(pd.to_datetime(dates))
    on, ndays = overnight(us, kr)
    z = zpast(on["^SOX"]).to_numpy()
    last_us = us.index.max()
    kr_end = kr[kr > last_us].min() if (kr > last_us).any() else kr.max()   # 미국 마지막 날을 밤사이로 쓰는 한국 날까지만(그 뒤는 overnight() 가 0 으로 채운다)
    valid = (kr >= pd.Timestamp(START)) & (kr <= kr_end) & ~np.isnan(z)
    ev = np.where(valid, (z >= Z_EVENT).astype(float), np.nan)
    Cp = np.vstack([np.full((1, C.shape[1]), np.nan), C[:-1]])
    elig = rs.compute_elig(V, common, gid)
    sm = semi_mask(tickers, groups, gid)
    k2 = np.isin(np.array(tickers), ["005930", "000660"])
    yK2, gK2 = basket(C, O, Cp, np.broadcast_to(k2, C.shape) & elig)
    yKS, gKS = basket(C, O, Cp, elig & sm)
    yNS, gNS = basket(C, O, Cp, elig & ~sm)
    ds = np.array(dates)
    floor = shift_floor(ds, [yK2, yKS], np.nan_to_num(ev, nan=0), rng)
    cells = {"K2": summarize(ds, yK2, gK2, ev, rng), "KS": summarize(ds, yKS, gKS, ev, rng)}
    ev2 = np.where(valid, (z >= 2).astype(float), np.nan)
    evd = np.where(valid, (z <= -1).astype(float), np.nan)
    rec = {"nonsemi_same_events": summarize(ds, yNS, gNS, ev, rng),
           "z>=2": {"K2": summarize(ds, yK2, gK2, ev2, rng), "KS": summarize(ds, yKS, gKS, ev2, rng)},
           "z<=-1": {"K2": summarize(ds, yK2, gK2, evd, rng), "KS": summarize(ds, yKS, gKS, evd, rng)}}
    res = {"sample": [str(kr[valid][0].date()), str(kr[valid][-1].date())], "us_last": str(last_us.date()),
           "semis_n_tickers": int(sm.sum()), "floor_t": floor, "verdict": {k: judge(v, floor) for k, v in cells.items()},
           "cells": cells, "record_only": rec}
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(res, ensure_ascii=False, indent=1, default=float), encoding="utf-8")
    print(f"표본 {res['sample']} · 반도체 {res['semis_n_tickers']}종목 · 바닥선 t {floor:.2f}")
    print("판정:", res["verdict"])
    print(f"→ {OUT}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
