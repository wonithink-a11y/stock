#!/usr/bin/env python3
"""공매도 급증·고비중 뒤 개별주 — 사전등록 findings/short-selling-alert-preregistration-2026-10.md 그대로.

    python research/strategy-lab/short_selling_alert.py --selftest
    python research/strategy-lab/short_selling_alert.py      # → findings/short-selling-alert-results-2026-10.{md,json}
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent.parent
sys.path.insert(0, str(HERE))
import surge_day_continuation as s
import distribution_day_study as dd

A8 = ROOT / "data" / "backfill" / "shortSelling" / "a8"
OUT = HERE / "findings" / "short-selling-alert-results-2026-10"
SEED, GAP = 20261009, 60
SR_MIN, SPIKE, BASE_N, BASE_MIN, TOP = 0.20, 3.0, 60, 40, 0.10
CENTRAL = ("S1", "S2")


def load_short(dates, tick):
    ti = {t: j for j, t in enumerate(tick)}
    M = np.full((len(dates), len(tick)), np.nan)
    for f in sorted(A8.glob("*.jsonl.gz")):
        d = pd.read_json(f, lines=True, compression="gzip", dtype={"ticker": str})
        d["date"] = pd.to_datetime(d["date"])
        r = np.searchsorted(dates, d["date"].to_numpy())
        ok = (r < len(dates)) & (dates[np.minimum(r, len(dates) - 1)] == d["date"].to_numpy())
        j = d["ticker"].map(ti)
        ok &= j.notna().to_numpy()
        M[r[ok], j[ok].astype(int).to_numpy()] = d.loc[ok, "shortVolume"].to_numpy(float)
    return M


def short_ratio(SV, V):
    with np.errstate(invalid="ignore", divide="ignore"):
        return np.where(V > 0, SV / V, np.nan)


def masks(SR, V, month_end):
    base = pd.DataFrame(SR).shift(1).rolling(BASE_N, min_periods=BASE_MIN).mean().to_numpy()
    sr20 = pd.DataFrame(SR).rolling(20, min_periods=15).mean().to_numpy()
    Vz = np.where(V > 0, V, np.nan)
    vr = V / pd.DataFrame(Vz).shift(1).rolling(30, min_periods=20).mean().to_numpy()
    with np.errstate(invalid="ignore"):
        S1 = (SR >= SR_MIN) & (SR >= SPIKE * base)
        S0 = S1 & (vr >= 3)
    return {"S1": S1, "S0": S0}, sr20, base


def top_decile(sr20, elig, rows):
    S2 = np.zeros_like(elig)
    for r in rows:
        v = np.where(elig[r] & (sr20[r] > 0), sr20[r], np.nan)
        if np.isfinite(v).sum() < 50:
            continue
        S2[r] = v >= np.nanquantile(v, 1 - TOP)
    return S2


def run():
    dates, tick, raw = s.load_raw()
    P = s.derive(raw, dates)
    SR = short_ratio(load_short(dates, tick), P["Vn"])
    me_rows = pd.Series(np.arange(len(dates))).groupby(dates.to_period("M")).max().to_numpy()
    raw_m, sr20, base = masks(SR, P["Vn"], me_rows)
    ok = P["elig"] & ~dd.share_event_mask(dates, tick)
    raw_m["S2"] = top_decile(sr20, ok, me_rows)
    raw_m = {k: m & ok for k, m in raw_m.items()}
    U = np.zeros_like(ok)
    for m in raw_m.values():
        U |= m
    rng = np.random.default_rng(SEED)
    M = s.outcome_mats(P)
    PL, PM, pool = s.placebo(P, U, M, rng)
    cells, arrs = {}, {}
    for k in ("S1", "S2", "S0"):
        t, j = np.nonzero(raw_m[k])
        t, j = s.dedup(t, j, GAP) if k != "S2" else (t, j)
        mi = np.asarray(s.month_idx(dates, t), dtype=np.int64)
        keep = (mi >= 0) & (mi < s.NM)
        t, j, mi = t[keep], j[keep], mi[keep]
        cells[k] = s.cell_summary(k, t, j, mi, P, M, PM, rng)
        arrs[k] = (t, j, mi)
    null = s.null_dist([(arrs[k][0], arrs[k][2]) for k in CENTRAL], pool, M["R20"], PM["R20"], rng, s.N_PERM)
    verdicts = {}
    for c, k in enumerate(CENTRAL):
        r = cells[k]
        lo, hi = np.nanpercentile(null[:, c, 1], [1, 99])
        w = [r["info_mean"][x] for x in ("TRAIN", "VALID", "TEST")]
        ci = r["ci"]["ALL"]
        v = "REVERSE" if (r["info_all"] < lo and all(x < 0 for x in w) and ci[1] < 0) else (
            "INFORMATION" if (r["info_all"] > hi and all(x > 0 for x in w) and ci[0] > 0) else "NONE")
        verdicts[k] = dict(verdict=v, null_1=float(lo), null_99=float(hi),
                           avoid_economic=bool(v == "REVERSE" and all(-r["info_mean"][x] > s.COST for x in ("VALID", "TEST"))))
    segs = {}
    for k in ("S1",):
        t, j, mi = arrs[k]
        sb = SR[t, j] / base[t, j]
        feats = {"SR 20~30%": SR[t, j] < 0.3, "SR ≥30%": SR[t, j] >= 0.3, "급증 3~5배": sb < 5, "급증 ≥5배": sb >= 5}
        segs[k] = {}
        for name, sel in feats.items():
            if sel.sum() >= 30:
                r = s.cell_summary(name, t[sel], j[sel], mi[sel], P, M, PM, rng, with_ci=False)
                segs[k][name] = dict(n=r["n"], info_all=r["info_all"], info=r["info_mean"])
    years = {k: pd.Series(dates[arrs[k][0] + 1].year).value_counts().sort_index().to_dict() for k in cells}
    out = dict(cells={k: {x: v for x, v in r.items() if x != "_arr"} for k, r in cells.items()}, verdicts=verdicts, segments=segs,
               years={k: {int(a): int(b) for a, b in v.items()} for k, v in years.items()}, price_last=str(dates[-1].date()), d1_minus_d0=np.nan)
    OUT.with_suffix(".json").write_text(json.dumps(out, ensure_ascii=False, indent=1, default=float), encoding="utf-8")
    md = dd.render(out).replace("distribution-day", "short-selling-alert").replace("대량 거래 장대음봉(분산일) 뒤 개별주", "공매도 급증·고비중 뒤 개별주") \
        .replace("distribution_day_study.py", "short_selling_alert.py")
    md = md.replace('conditions: ["A2a+A2b 일봉 2016~2026-10-02", "D1 = 60일 +20% ∧ 거래량 30일 평균 3배 ∧ 음봉 몸통 4% ∧ 하락", "D2 = 앞선 상승 무관",',
                    'conditions: ["A2a+A2b 일봉 + A8 공매도 2016~2026", "S1 = 공매도 비중 ≥20% ∧ 직전 60일 평균 3배", "S2 = 월말 20일 평균 공매도 비중 상위 10%",')
    md = "\n".join(line for line in md.splitlines() if not line.startswith("D1 − D0"))
    OUT.with_suffix(".md").write_text(md + "\n", encoding="utf-8")
    for k in cells:
        r = cells[k]
        print(k, r["n"], {w: round(r["info_mean"][w] * 100, 2) for w in s.WIN}, "all", round(r["info_all"] * 100, 2), verdicts.get(k))
    return 0


def selftest():
    ok = True

    def check(name, cond):
        nonlocal ok
        ok &= bool(cond)
        print(("PASS " if cond else "FAIL ") + name)

    D = 120
    V = np.full((D, 1), 1000.0)
    SV = np.full((D, 1), 50.0)                   # 평소 5%
    SV[100, 0] = 300.0                            # 30% = 6배
    SR = short_ratio(SV, V)
    m, sr20, base = masks(SR, V, None)
    check("S1 은 100일만", np.flatnonzero(m["S1"][:, 0]).tolist() == [100])
    SV2 = SV.copy()
    SV2[100, 0] = 150.0                           # 15% → 비중 20% 미달
    check("비중 15% 면 아님", not masks(short_ratio(SV2, V), V, None)[0]["S1"][100, 0])
    elig = np.ones((5, 100), bool)
    sr = np.tile(np.arange(100, dtype=float) / 1000 + 0.001, (5, 1))
    t = top_decile(sr, elig, [4])
    check("월말 상위 10% = 10종목", t[4].sum() == 10 and t[4, 99] and not t[4, 0])
    print("ALL PASS" if ok else "FAILED")
    return 0 if ok else 1


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--selftest", action="store_true")
    sys.exit(selftest() if ap.parse_args().selftest else run())
