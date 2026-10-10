#!/usr/bin/env python3
"""업종 안 후발주 따라잡기 - 2~5위 vs 다른 업종 매칭 대조. 사전등록: findings/sector-follower-catchup-preregistration-2026-10.md (문서가 우선).

  python run_sector_follower_catchup.py --selftest
  python run_sector_follower_catchup.py      # 정식: 사전등록·이 코드가 커밋된 깨끗한 상태에서만 계산한다
"""
import argparse
import json
import sys
from pathlib import Path

import numpy as np

import run_sector_rise_study as rs

HERE = Path(__file__).resolve().parent
PREREG = HERE / "findings" / "sector-follower-catchup-preregistration-2026-10.md"
OUT = HERE / "reports" / "2026-10-sector-follower-catchup" / "results.json"

# ---- 사전등록 고정값
START = "2016-01-04"
B_EXCESS = 0.10
B_DEDUP = 20
F_RANKS = (1, 5)          # 0-기준 슬라이스 → 2~5위
K_CTRL = 5
HORIZONS = (5, 20)
COST_BP = 33.5
PERIODS = [("TRAIN", "2016-01", "2020-12"), ("VALID", "2021-01", "2022-12"), ("TEST", "2023-01", "9999-12")]
ERAS = [("2016~23", "2016-01", "2023-12"), ("2024", "2024-01", "2024-12"), ("2025~", "2025-01", "9999-12")]
N_PLACEBO, N_BOOT = 200, 2000
CELLS = [("A", 5), ("A", 20), ("B", 5), ("B", 20)]


def tv_median(V):
    D, T = V.shape
    M = np.full((D, T), np.nan)
    for i in range(rs.TV_WIN - 1, D):
        w = V[i - rs.TV_WIN + 1:i + 1]
        ok = np.sum(~np.isnan(w), axis=0) >= rs.TV_MIN_VALID
        M[i] = np.where(ok, rs.nanmed(w, axis=0), np.nan)
    return M


def pct(x, mask):
    """mask 안에서 x 의 백분위(0~1). 밖이나 NaN 은 NaN."""
    out = np.full(x.shape, np.nan)
    idx = np.where(mask & ~np.isnan(x))[0]
    if len(idx) > 1:
        out[idx] = np.argsort(np.argsort(x[idx], kind="stable"), kind="stable") / (len(idx) - 1)
    return out


class Ctx:
    def __init__(self, C, O, V, common, gid, ngroups, allow=None):
        self.C, self.O, self.gid, self.ng = C, O, gid, ngroups
        D, T = C.shape
        self.D = D
        allow = np.ones(T, bool) if allow is None else allow
        self.elig = rs.compute_elig(V, common, gid) & allow
        self.MED = tv_median(V)
        self.cum5 = np.full((D, T), np.nan)
        self.cum5[5:] = C[5:] / C[:-5] - 1
        self.fwd = {}
        for h in HORIZONS:
            f = np.full((D, T), np.nan)
            for i in range(D - h):
                f[i] = np.where(O[i + 1] > 0, C[i + h] / O[i + 1] - 1, np.nan)
            self.fwd[h] = f
        self._pc = {}

    def pcts(self, i):
        if i not in self._pc:
            e = self.elig[i] & ~np.isnan(self.cum5[i]) & ~np.isnan(self.MED[i])
            self._pc[i] = (e, pct(self.MED[i], e), pct(self.cum5[i], e))
        return self._pc[i]

    def ranked(self, i, g):
        e, _, _ = self.pcts(i)
        idx = np.where(e & (self.gid == g))[0]
        return idx[np.argsort(-self.MED[i, idx], kind="stable")]

    def value(self, i, g, sel):
        """sel = 'F' | 'L' | 'R6'. 반환 {h: (매칭 차이, F−시장)} 또는 None."""
        e, ptv, pc5 = self.pcts(i)
        order = self.ranked(i, g)
        if len(order) < rs.MIN_GROUP:
            return None
        treat = {"F": order[F_RANKS[0]:F_RANKS[1]], "L": order[:1], "R6": order[F_RANKS[1]:]}[sel]
        pool = np.where(e & (self.gid != g))[0]
        if len(pool) < K_CTRL or not len(treat):
            return None
        out = {}
        for h in HORIZONS:
            if i + h >= self.D:
                out[h] = None
                continue
            f = self.fwd[h][i]
            diffs, raws = [], []
            for s in treat:
                if np.isnan(f[s]):
                    continue
                d = (ptv[pool] - ptv[s]) ** 2 + (pc5[pool] - pc5[s]) ** 2
                cand = pool[~np.isnan(f[pool])]
                dc = d[~np.isnan(f[pool])]
                if len(cand) < K_CTRL:
                    continue
                near = cand[np.argpartition(dc, K_CTRL - 1)[:K_CTRL]]
                diffs.append(f[s] - f[near].mean())
                raws.append(f[s])
            need = 2 if sel == "F" else 1
            if len(diffs) < need:
                out[h] = None
                continue
            mk = rs.nanmean(np.where(self.elig[i], f, np.nan))
            out[h] = (float(np.mean(diffs)), float(np.mean(raws) - mk))
        return out


def events_A(ctx, C, O, V, common, gid, ngroups, start_i):
    ev = rs.study(C, O, V, common, gid, ngroups)
    return sorted({(e["i"], e["g"]) for e in ev if e["kind"] == "S1" and e["h"] == HORIZONS[0] and e["i"] >= start_i})


def events_B(ctx, start_i):
    out, last = [], {}
    for i in range(max(10, rs.TV_WIN), ctx.D):
        e, _, _ = ctx.pcts(i)
        if e.sum() < 50:
            continue
        mk5 = rs.nanmed(ctx.cum5[i, e])
        for g in range(ctx.ng):
            order = ctx.ranked(i, g)
            if len(order) < rs.MIN_GROUP:
                continue
            if ctx.cum5[i, order[0]] - mk5 >= B_EXCESS:
                if g not in last or i - last[g] > B_DEDUP:
                    if i >= start_i:
                        out.append((i, g))
                    last[g] = i      # 사전등록 §2: 직전 20거래일 안의 'B 사건' 기준
    return out


def month_t(vals_by_month):
    m = np.array([np.mean(v) for v in vals_by_month.values()])
    if len(m) < 3:
        return np.nan, np.nan, len(m)
    return float(m.mean()), float(m.mean() / (m.std(ddof=1) / np.sqrt(len(m)))), len(m)


def by_month(rows, dates, lo, hi, k):
    bm = {}
    for i, v in rows:
        mo = dates[i][:7]
        if lo <= mo <= hi and v is not None:
            bm.setdefault(mo, []).append(v[k])
    return bm


def boot_ci(bm, rng):
    m = np.array([np.mean(v) for v in bm.values()])
    if len(m) < 3:
        return (np.nan, np.nan)
    s = rng.choice(m, (N_BOOT, len(m))).mean(axis=1)
    return float(np.quantile(s, 0.05)), float(np.quantile(s, 0.95))


def summarize(vals, dates, rng):
    """vals: {h: [(i, (diff, raw))]} → 구간·시기별 요약."""
    res = {}
    for h, rows in vals.items():
        r = {}
        for name, lo, hi in PERIODS + ERAS + [("ALL", "2016-01", "9999-12")]:
            bm = by_month(rows, dates, lo, hi, 0)
            mean, t, nm = month_t(bm)
            bmr = by_month(rows, dates, lo, hi, 1)
            raw, traw, _ = month_t(bmr)
            r[name] = {"diff_bp": mean * 1e4 if mean == mean else None, "t": t, "months": nm,
                       "events": sum(len(v) for v in bm.values()), "ci90_bp": [x * 1e4 for x in boot_ci(bm, rng)],
                       "raw_vs_mkt_bp": raw * 1e4 if raw == raw else None, "net_bp": (raw * 1e4 - COST_BP) if raw == raw else None}
        res[h] = r
    return res


def compute(ctx, evs, sel="F"):
    vals = {h: [] for h in HORIZONS}
    for i, g in evs:
        v = ctx.value(i, g, sel)
        if v is None:
            continue
        for h in HORIZONS:
            vals[h].append((i, v[h]))
    return vals


def placebo_floor(ctx, evA, evB, dates, rng):
    tr_lo, tr_hi = PERIODS[0][1], PERIODS[0][2]
    busy = {}
    for i, g in evA + evB:
        busy.setdefault(g, []).append(i)
    cand = []
    for i in range(ctx.D):
        if not (tr_lo <= dates[i][:7] <= tr_hi):
            continue
        for g in range(ctx.ng):
            if any(0 <= i - j <= B_DEDUP for j in busy.get(g, [])):
                continue
            cand.append((i, g))
    cv = []
    for i, g in cand:
        v = ctx.value(i, g, "F")
        if v is not None and all(v[h] is not None for h in HORIZONS):
            cv.append((i, v))
    nA = sum(1 for i, _ in evA if tr_lo <= dates[i][:7] <= tr_hi)
    nB = sum(1 for i, _ in evB if tr_lo <= dates[i][:7] <= tr_hi)
    maxes = []
    for _ in range(N_PLACEBO):
        ts = []
        for n in (nA, nB):
            pick = [cv[k] for k in rng.choice(len(cv), min(n, len(cv)), replace=False)]
            for h in HORIZONS:
                bm = by_month([(i, v[h]) for i, v in pick], dates, tr_lo, tr_hi, 0)
                ts.append(abs(month_t(bm)[1]))
        maxes.append(np.nanmax(ts))
    return float(np.quantile(maxes, 0.95)), len(cv), nA, nB


def judge(summ, floor):
    out = {}
    for kind, h in CELLS:
        s = summ[kind][h]
        tr, va, te = s["TRAIN"], s["VALID"], s["TEST"]
        info = (tr["diff_bp"] or 0) > 0 and (tr["t"] or 0) >= floor and (va["diff_bp"] or 0) > 0 and (te["diff_bp"] or 0) > 0
        econ = info and (te["net_bp"] or -1) > 0
        out[f"{kind}·h{h}"] = "ECONOMIC" if econ else ("INFORMATION" if info else "REJECT")
    return out


# ---------------------------------------------------------------- selftest
def selftest():
    def ok(c, m):
        if not c:
            print("selftest 실패:", m); sys.exit(1)
    rng = np.random.default_rng(3)
    D, T = 120, 160
    C = np.cumprod(1 + rng.normal(0, 0.01, (D, T)), axis=0) * 1000
    O = C.copy()
    V = np.full((D, T), 5e9)
    V[:, :40] = np.linspace(9e9, 2e9, 40)          # 그룹 0: 종목 0 이 거래대금 1위, 1~4 가 2~5위
    gid = np.array([0] * 40 + [1] * 40 + [2] * 40 + [3] * 40)
    common = np.ones(T, bool)
    # 대장(0) 이 50~54일 +15% → B 사건(54). 그 뒤 2~5위만 +6% 따라감(55일 이후 종가, 진입 O[55])
    C[54:, 0] *= 1.15
    O = C.copy()
    C[56:, 1:5] *= 1.06
    ctx = Ctx(C, O, V, common, gid, 4)
    evB = events_B(ctx, 0)
    ok(any(i == 54 and g == 0 for i, g in evB), f"B 사건 탐지 {evB}")
    ok(not any(g == 0 and 55 <= i <= 54 + B_DEDUP for i, g in evB), "20거래일 중복 제거")
    v = ctx.value(54, 0, "F")
    ok(v[5][0] > 0.04, f"2~5위 따라잡기가 매칭 차이에 잡힌다 {v[5]}")
    vl = ctx.value(54, 0, "L")
    ok(abs(vl[5][0]) < 0.04, f"대장은 그 뒤 따로 안 움직였다 {vl[5]}")
    # 대조는 다른 그룹에서만: 그룹 0 전체를 같이 올리면 F−대조가 남고, 다른 그룹도 같이 올리면 사라진다
    C2 = C.copy(); C2[56:, :] = C[56:, :]; C2[56:, 40:] *= 1.06
    O2 = C2.copy(); O2[:56] = O[:56]
    v2 = Ctx(C2, O, V, common, gid, 4).value(54, 0, "F")
    ok(abs(v2[5][0]) < 0.03, f"전 종목이 같이 오르면 차이 없음 {v2[5]}")
    # 미래 가격이 사건 탐지를 안 바꾼다
    C3 = C.copy(); C3[60:] *= 2
    ok([x for x in events_B(Ctx(C3, C3, V, common, gid, 4), 0) if x[0] < 58] == [x for x in evB if x[0] < 58], "미래 정보 누수")
    # 데이터 끝 넘는 h 는 None
    ok(ctx.value(D - 3, 0, "F")[5] is None, "청산일이 데이터 끝을 넘으면 None")
    # 월 군집 t
    m, t, n = month_t({"2020-01": [0.01], "2020-02": [0.02], "2020-03": [0.03]})
    ok(abs(m - 0.02) < 1e-12 and abs(t - 0.02 / (0.01 / np.sqrt(3))) < 1e-9 and n == 3, "월 t")
    print("selftest OK - run_sector_follower_catchup")
    return 0


def semi_mask(tickers, groups, gid):
    themes = json.load(open(rs.REPO / "config" / "themeTree.json", encoding="utf-8"))["themes"]
    ai = {x["t"] for g in themes["AI·반도체"].values() for x in g}
    gsemi = groups.index("반도체")
    return np.array([(t in ai) or (gid[k] == gsemi) for k, t in enumerate(tickers)])


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--selftest", action="store_true")
    a = ap.parse_args()
    if a.selftest:
        return selftest()
    for p in (PREREG, Path(__file__).resolve()):
        if not rs.committed_clean(p):
            print(f"{p.name} 가 커밋되지 않았거나 수정 중 - 계산하지 않는다")
            return 2
    rng = np.random.default_rng(20261011)
    dates, tickers, groups, C, O, V, common, gid = rs.load_all()
    start_i = next(k for k, d in enumerate(dates) if d >= START)
    ng = len(groups)
    ctx = Ctx(C, O, V, common, gid, ng)
    evA = events_A(ctx, C, O, V, common, gid, ng, start_i)
    evB = events_B(ctx, start_i)
    print(f"A2a {dates[0]} ~ {dates[-1]} · 종목 {len(tickers)} · 업종 {ng} · 사건 A {len(evA)} · B {len(evB)}", flush=True)
    summ = {"A": summarize(compute(ctx, evA), dates, rng), "B": summarize(compute(ctx, evB), dates, rng)}
    floor, ncand, nA, nB = placebo_floor(ctx, evA, evB, dates, rng)
    verdict = judge(summ, floor)
    rec = {k: {"L": summarize(compute(ctx, ev, "L"), dates, rng), "R6": summarize(compute(ctx, ev, "R6"), dates, rng)}
           for k, ev in (("A", evA), ("B", evB))}
    sm = semi_mask(tickers, groups, gid)
    ctx_ex = Ctx(C, O, V, common, gid, ng, allow=~sm)
    gsemi = groups.index("반도체")
    semi_ex = {k: summarize(compute(ctx_ex, [x for x in ev if x[1] != gsemi]), dates, rng) for k, ev in (("A", evA), ("B", evB))}
    res = {"data": [dates[0], dates[-1]], "events": {"A": len(evA), "B": len(evB)},
           "placebo": {"floor_t": floor, "candidates": ncand, "train_events": {"A": nA, "B": nB}},
           "verdict": verdict, "cells": summ, "record_only": {"leader_and_rank6plus": rec, "semis_excluded": semi_ex},
           "eventsByGroup": {k: {groups[g]: sum(1 for _, x in ev if x == g) for g in range(ng)} for k, ev in (("A", evA), ("B", evB))}}
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(res, ensure_ascii=False, indent=1, default=float), encoding="utf-8")
    print(f"바닥선 t {floor:.2f} (placebo 후보 {ncand}, TRAIN 사건 A {nA}·B {nB})")
    print("판정:", verdict)
    print(f"→ {OUT}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
