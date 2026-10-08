#!/usr/bin/env python3
"""KOSPI200 선물 베이시스 → 지수 타이밍 — 사전등록 findings/futures-basis-timing-preregistration-2026-10.md 그대로.

    python research/strategy-lab/futures_basis_timing.py --selftest
    python research/strategy-lab/futures_basis_timing.py      # → findings/futures-basis-timing-results-2026-10.{md,json}
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import etf_timing_lab as e

OUT = HERE / "findings" / "futures-basis-timing-results-2026-10"
Z_TH, LOOK, LOOK_MIN, HOLD, NEAR_EXP = 1.5, 250, 200, 5, 5
CM = re.compile(r"F (\d{6})")


def second_thursday(ym, cal_set):
    y, m = int(ym[:4]), int(ym[4:])
    days = pd.date_range(f"{y}-{m:02d}-01", periods=31, freq="D")
    th = [d for d in days if d.month == m and d.weekday() == 3]
    d = th[1]
    while d not in cal_set and d.day > 1:
        d -= pd.Timedelta(days=1)
    return d


def basis_series():
    df = pd.concat(pd.read_parquet(f) for f in sorted(e.FUT_DIR.glob("kospi200_*.parquet")))
    df = df[(df["PROD_NM"] == "코스피200 선물") & (df["MKT_NM"] == "정규")].copy()
    df["date"] = pd.to_datetime(df["BAS_DD"])
    for c in ("SETL_PRC", "SPOT_PRC", "ACC_TRDVOL"):
        df[c] = pd.to_numeric(df[c].astype(str).str.replace(",", ""), errors="coerce")
    df["cm"] = df["ISU_NM"].str.extract(CM, expand=False)
    df = df[df["cm"].notna() & (df["SETL_PRC"] > 0) & (df["SPOT_PRC"] > 0)]
    cal = pd.DatetimeIndex(sorted(df["date"].unique()))
    cal_set = set(cal)
    exp = {cm: second_thursday(cm, cal_set) for cm in df["cm"].unique()}
    pos = {d: i for i, d in enumerate(cal)}
    df["exp"] = df["cm"].map(exp)
    df["tdays"] = [pos.get(x, np.searchsorted(cal, x)) - pos[d] for d, x in zip(df["date"], df["exp"])]
    df = df[df["tdays"] >= 0]
    out = {}
    for d, g in df.groupby("date"):
        g = g.sort_values("ACC_TRDVOL", ascending=False)
        r = g.iloc[0]
        if r["tdays"] <= NEAR_EXP:
            later = g[g["exp"] > r["exp"]]
            if len(later) == 0:
                continue
            r = later.iloc[0]
        days = max((r["exp"] - d).days, 1)
        out[d] = (r["SETL_PRC"] / r["SPOT_PRC"] - 1) * 365 / days
    b = pd.Series(out).sort_index()
    mu = b.shift(1).rolling(LOOK, min_periods=LOOK_MIN).mean()
    sd = b.shift(1).rolling(LOOK, min_periods=LOOK_MIN).std()
    return b, (b - mu) / sd


def rule(z, cal, side):
    sig = (z <= -Z_TH) if side == "BLO" else (z >= Z_TH)
    sig = sig.reindex(cal).fillna(False).astype(float)
    x = sig.shift(1).rolling(HOLD, min_periods=1).max()
    return x.where(z.reindex(cal).shift(1).notna() | (x > 0))


def run():
    panel = e.load_panel()
    cal, R, spot, fval = e.build(panel)
    rng = np.random.default_rng(e.SEED)
    offsets = rng.integers(e.MIN_SHIFT, len(cal) - e.MIN_SHIFT, e.N_SHIFT)
    rk, rb = R[e.K200], R[e.KTB3]
    b, z = basis_series()
    res, X = {}, {}
    for side in ("BLO", "BHI"):
        X[side] = rule(z, cal, side)
        res[side] = {c_name: e.run_cell(X[side], rk, rb, cal, offsets, c)[0] for c_name, c in (("base", e.COST), ("stress", e.STRESS))}
    S = lambda side, c, w: None if res[side][c][w] is None else res[side][c][w]["act"] - float(np.nanmean(res[side][c][w]["shift"]))
    cen = [np.abs(res[sd]["base"]["TRAIN"]["shift"] - np.nanmean(res[sd]["base"]["TRAIN"]["shift"])) for sd in res]
    floor = float(np.nanpercentile(np.nanmax(np.vstack(cen), axis=0), 95))
    verdict, ev = {}, {}
    fwd5 = rk.rolling(HOLD).sum().shift(-HOLD)
    for side in res:
        st, sv, ste = (S(side, "base", w) for w in e.WINDOWS)
        sg = np.sign(st)
        info = abs(st) >= floor and np.sign(sv) == sg and np.sign(ste) == sg
        econ = info and np.sign(S(side, "stress", "VALID")) == sg and np.sign(S(side, "stress", "TEST")) == sg
        verdict[side] = ("ECONOMIC" if econ else "INFORMATION") + ("(음 — 회피)" if sg < 0 else "") if info else "REJECT"
        days = ((z <= -Z_TH) if side == "BLO" else (z >= Z_TH))
        days = days[days].index.intersection(cal)
        ev[side] = {w: dict(n=int(((days >= pd.Timestamp(a)) & (days <= pd.Timestamp(bb))).sum()),
                            fwd5=float(fwd5.reindex(days[(days >= pd.Timestamp(a)) & (days <= pd.Timestamp(bb))]).mean()),
                            all5=float(fwd5[(fwd5.index >= pd.Timestamp(a)) & (fwd5.index <= pd.Timestamp(bb))].mean()))
                    for w, (a, bb) in e.WINDOWS.items()}
    out = dict(verdict=verdict, floor=floor, res=e._jsonable(res), events=ev, basis_stats=dict(mean=float(b.mean()), sd=float(b.std()), n=int(b.notna().sum())))
    OUT.with_suffix(".json").write_text(json.dumps(out, ensure_ascii=False, indent=1, default=float), encoding="utf-8")
    OUT.with_suffix(".md").write_text(render(out), encoding="utf-8")
    for side in res:
        print(side, verdict[side], {w: round(S(side, "base", w), 3) for w in e.WINDOWS}, ev[side])
    print("floor", floor)
    return 0


def render(o):
    v = o["verdict"]
    pos = [k for k, x in v.items() if x != "REJECT"]
    L = ["---", "track: kr", "factor: futures-basis-timing", "date: 2026-10-09", f"verdict: {'INFORMATION' if pos else 'REJECT'}",
         "criteria_version: research-only (futures-basis-timing-preregistration-2026-10)",
         'conditions: ["KOSPI200 최근월물 연율 베이시스 z(250일)", "z ≤ −1.5 / ≥ +1.5 뒤 5거래일 KODEX 200, 아니면 국고채3년", "원형 이동 1,000 · 가족 바닥선 양측 95백분위", "전환 5bp(스트레스 10bp)"]',
         "reason: >-", f"  신호: {'있음(' + '·'.join(pos) + ')' if pos else '없음'} · 경제성: {'통과' if any('ECONOMIC' in x for x in v.values()) else '미달'}. "
         + " · ".join(f"{k} {x}" for k, x in v.items()) + ". (스크립트 판정)", "---", "",
         "# KOSPI200 선물 베이시스 → 지수 타이밍 — 결과", "", f"연율 베이시스 평균 {o['basis_stats']['mean'] * 100:+.2f}% · 표준편차 {o['basis_stats']['sd'] * 100:.2f}%p ({o['basis_stats']['n']}일). 가족 바닥선 {o['floor']:.2f}.", "",
         "| 칸 | 구간 | S(비용 5bp) | S(스트레스) | 노출 | 연 전환 | CAGR | 샤프 | MDD | 신호일 | 신호 뒤 5일 평균 | 전체 5일 평균 | 판정 |", "|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---|"]
    for side in o["res"]:
        for w in e.WINDOWS:
            b, s = o["res"][side]["base"][w], o["res"][side]["stress"][w]
            evw = o["events"][side][w]
            L.append(f"| {side} | {w} | {b['S']:+.2f} | {s['S']:+.2f} | {b['expo']:.0%} | {b['switches']:.1f} | {b['stats']['cagr'] * 100:+.1f}% | {b['stats']['sharpe']:.2f} | "
                     f"{b['stats']['mdd'] * 100:.1f}% | {evw['n']} | {evw['fwd5'] * 100:+.2f}% | {evw['all5'] * 100:+.2f}% | {'**' + v[side] + '**' if w == 'TRAIN' else ''} |")
    return "\n".join(L) + "\n"


def selftest():
    ok = True

    def check(name, cond):
        nonlocal ok
        ok &= bool(cond)
        print(("PASS " if cond else "FAIL ") + name)

    cal = pd.bdate_range("2024-01-01", "2024-03-29")
    check("2024-03 만기 = 3/14(목)", second_thursday("202403", set(cal)) == pd.Timestamp("2024-03-14"))
    check("휴장이면 전 거래일", second_thursday("202403", set(cal) - {pd.Timestamp("2024-03-14")}) == pd.Timestamp("2024-03-13"))
    z = pd.Series(0.0, index=cal)
    z.iloc[10] = -2.0
    x = rule(z, cal, "BLO")
    check("신호 다음 날부터 5거래일 보유", x.iloc[11:16].tolist() == [1.0] * 5 and x.iloc[16] == 0 and x.iloc[10] == 0)
    print("ALL PASS" if ok else "FAILED")
    return 0 if ok else 1


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--selftest", action="store_true")
    sys.exit(selftest() if ap.parse_args().selftest else run())
