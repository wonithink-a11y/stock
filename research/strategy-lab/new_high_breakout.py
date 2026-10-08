#!/usr/bin/env python3
"""신고가 돌파(저스템형) 유형 — 결과 산출. 사전등록: findings/new-high-breakout-preregistration-2026-10.md (커밋 f1563a3b).
정의·구간·판정은 사전등록 그대로이며 결과를 보고 바꾸지 않는다.

    python research/strategy-lab/new_high_breakout.py --selftest
    python research/strategy-lab/new_high_breakout.py        # A2a+A2b 일봉 필요 -> findings/new-high-breakout-results-2026-10.{md,json}

구현 세부(사전등록이 열어 둔 부분, 실행 전에 고정):
  · 판정 방식·귀무·부트스트랩·플라시보 20종목은 surge_day_continuation.py 와 같은 함수를 쓴다(진입월 평균, 6개월 이동 블록 2,000회, 가짜 사건 1,000회).
  · 세분화 17칸·교차 3칸은 H1 에피소드 제거 뒤 사건의 부분집합. 업종 동반 = 같은 날 같은 업종 다른 종목 중 H1 원시 조건(적격 포함)을 만족한 수.
  · 돌파선 이탈의 플라시보: 같은 신호일 플라시보 종목에 '사건의 (돌파선 / 진입 시가) 비율'을 그대로 적용한 선(진입 시가 × 비율)을 쓴다.
  · 돌파선 이탈 판정은 진입일부터 매 거래일 종가(ffill), 청산은 다음 거래일 시가(결측이면 그날 종가), 최대 130거래일.
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import surge_day_continuation as m  # noqa: E402

OUT = HERE / "findings" / "new-high-breakout-results-2026-10"
SEED = 20261014
KS = [0.0, 0.03, 0.05, 0.10]
HOLD_D = 130
CENTERS = ["H1", "H2", "TJ"]
MIN_N = 80


# ───────────────────── 사건 ─────────────────────
def build(P):
    """(U, {H1,H2,TJ: (t, j)}, 특징 행렬 dict). U = 세 칸 원시 마스크 합집합."""
    D, N = P["D"], P["N"]
    Hn, Ln, Cn, elig = P["Hn"], P["Ln"], P["Cn"], P["elig"]
    hi252 = pd.DataFrame(Hn).shift(1).rolling(252, min_periods=252).max().to_numpy()
    lo252 = pd.DataFrame(Ln).shift(1).rolling(252, min_periods=252).min().to_numpy()
    hiall = pd.DataFrame(Hn).shift(1).expanding(min_periods=500).max().to_numpy()

    def first_day(brk):
        recent = pd.DataFrame(brk.astype(float)).shift(1).rolling(20, min_periods=1).max().to_numpy() > 0
        return brk & ~recent

    b1 = Cn > hi252
    b2 = Cn > hiall
    H1 = first_day(b1) & elig
    H2 = first_day(b2) & elig
    TJ = H2 & ((Cn / lo252 - 1) >= 2.0)
    U = H1 | H2 | TJ
    cells = {}
    for name, mask in (("H1", H1), ("H2", H2), ("TJ", TJ)):
        t, j = np.nonzero(mask)
        t, j = m.dedup(t, j)
        cells[name] = (t, j)
    return U, cells, dict(hi252=hi252, lo252=lo252, hiall=hiall, H1raw=H1)


def seg_masks(P, F, t, j, sector_idx):
    """H1 사건(t, j)의 세분화 칸 마스크 17 + 교차 3."""
    Cn, Hn, On = P["Cn"], P["Hn"], P["On"]
    reb = Cn[t, j] / F["lo252"][t, j] - 1
    # 돌파선 형성일로부터 경과 거래일
    days = np.full(len(t), np.nan)
    for i, (tt, jj) in enumerate(zip(t.tolist(), j.tolist())):
        w = Hn[tt - 252: tt, jj]
        if len(w) == 252 and not np.isnan(w).all():
            days[i] = 252 - int(np.nanargmax(w))
    vr = P["vr"][t, j]
    ret = P["ret1"][t, j]
    gap = On[t, j] > F["hi252"][t, j]
    # 업종 동반
    if "_hcnt" not in P:
        S = int(sector_idx.max()) + 1
        oh = np.zeros((P["N"], S), np.float32)
        for jj, s in enumerate(sector_idx):
            if s >= 0:
                oh[jj, s] = 1
        P["_hcnt"] = F["H1raw"].astype(np.float32) @ oh
    s = sector_idx[j]
    fc = np.where(s >= 0, P["_hcnt"][t, np.maximum(s, 0)] - F["H1raw"][t, j], np.nan)
    M = {}
    M["A1"], M["A2"], M["A3"] = reb < 1, (reb >= 1) & (reb < 2), reb >= 2
    M["B1"], M["B2"], M["B3"] = days < 40, (days >= 40) & (days <= 120), days > 120
    M["C1"], M["C2"], M["C3"] = vr < 1.5, (vr >= 1.5) & (vr < 3), vr >= 3
    M["D1"], M["D2"], M["D3"] = ret < 0.03, (ret >= 0.03) & (ret < 0.08), ret >= 0.08
    M["E1"], M["E2"] = gap, ~gap
    M["F1"], M["F2"], M["F3"] = fc == 0, (fc >= 1) & (fc <= 2), fc >= 3
    X = {"A3&C1": M["A3"] & M["C1"], "A3&E2": M["A3"] & M["E2"], "B3&C3": M["B3"] & M["C3"]}
    overlap = float(((ret >= 0.08) & (vr >= 5)).mean()) if len(t) else float("nan")
    return M, X, overlap, dict(reb=reb, days=days, vr=vr, ret=ret, gap=gap)


# ───────────────────── 돌파선 이탈 ─────────────────────
def sim_line_exit(P, t, j, rel, ks=KS, hold=HOLD_D):
    """매 거래일 종가 ≤ 선 × (1−k) 이면 다음 거래일 시가 청산. 선 = 진입 시가 × rel. 마지막 행 = 무이탈(hold 일 뒤 시가)."""
    n = len(t)
    E = P["On"][t + 1, j]
    L = rel * E
    nx = len(ks)
    ret = np.full((nx + 1, n), np.nan)
    hd = np.full((nx + 1, n), np.nan)
    trig = np.zeros((nx + 1, n), bool)
    done = np.zeros((nx + 1, n), bool)
    ka = np.array(ks)[:, None]
    Cff, On = P["Cff"], P["On"]
    for i in range(hold):
        e = t + 1 + i
        c = Cff[e, j]
        px = On[e + 1, j]
        px = np.where(np.isnan(px), c, px)
        r = px / E - 1
        hit = c[None, :] <= L[None, :] * (1 - ka)
        new = np.zeros((nx + 1, n), bool)
        new[:nx] = (hit | (i == hold - 1)) & ~done[:nx]
        if i == hold - 1:
            new[nx] = ~done[nx]
        for q in range(nx + 1):
            mm = new[q]
            if mm.any():
                ret[q, mm] = r[mm]
                hd[q, mm] = i + 1
                trig[q, mm] = (i < hold - 1) if q < nx else False
        done |= new
    return dict(ret=ret, hold=hd, trig=trig, E=E)


# ───────────────────── 실행 ─────────────────────
def pairs_placebo(PL, t):
    pj = PL[t]
    okp = pj >= 0
    pid = np.repeat(np.arange(len(t)), m.NPLAC)[okp.ravel()]
    tp = np.repeat(t, m.NPLAC)[okp.ravel()]
    jp = pj.ravel()[okp.ravel()]
    return tp, jp, pid


def mean_by_pid(vals, pid, n):
    s = np.bincount(pid, weights=np.nan_to_num(vals), minlength=n)
    c = np.bincount(pid, weights=(~np.isnan(vals)).astype(float), minlength=n)
    with np.errstate(all="ignore"):
        return np.where(c > 0, s / c, np.nan)


def line_exit_block(P, line, t, j, PL, mi):
    """H1/H2/TJ 한 칸의 돌파선 이탈 표."""
    ok = (t + 1 + HOLD_D + 2 < P["D"])
    t, j, mi = t[ok], j[ok], mi[ok]
    E = P["On"][t + 1, j]
    rel = line[t, j] / E
    ev = sim_line_exit(P, t, j, rel)
    tp, jp, pid = pairs_placebo(PL, t)
    vp = (tp + 1 + HOLD_D + 2 < P["D"]) & ~np.isnan(P["On"][tp + 1, jp])
    tp, jp, pid = tp[vp], jp[vp], pid[vp]
    pl = sim_line_exit(P, tp, jp, rel[pid])
    rows = []
    for q in range(len(KS) + 1):
        r = ev["ret"][q]
        plm = mean_by_pid(pl["ret"][q], pid, len(t))
        info = r - plm
        okq = ~np.isnan(r)
        mm_n = m.mmean((r - m.COST)[okq], mi[okq])
        mm_i = m.mmean(info[okq], mi[okq])
        rows.append({"k": (KS[q] if q < len(KS) else None), "n": int(okq.sum()), "net_mean_pct": float(np.nanmean(r - m.COST) * 100),
                     "median_pct": float(np.nanmedian(r) * 100), "win_net": float(np.nanmean((r - m.COST) > 0)),
                     "hold_days": float(np.nanmean(ev["hold"][q])), "trig_share": float(ev["trig"][q].mean()),
                     "info_all_pct": (None if np.isnan(m.wmean_of(mm_i, None)) else m.wmean_of(mm_i, None) * 100),
                     "net_by_window_pct": {w: (None if np.isnan(m.wmean_of(mm_n, kk)) else m.wmean_of(mm_n, kk) * 100) for kk, w in enumerate(m.WIN)}})
    hit0 = ev["trig"][0]
    fh = ev["hold"][0][hit0]
    block = {"table": rows, "n": int(len(t)), "line_return_days_quantiles": [float(np.percentile(fh, q)) for q in (10, 25, 50, 75, 90)] if len(fh) else None,
             "share_line_lost_within_60d": float((hit0 & (ev["hold"][0] <= 60)).mean()), "share_line_lost_ever": float(hit0.mean())}
    return block, ev, mi


def weekly_block(P, t, j, PL, mi):
    """주간 최고가 대비 x% 이탈 격자(기록 전용). surge_day_continuation.run 의 층 2 와 같은 규칙."""
    ok = (t + 1 + m.HOLD_W * 5 + 40 < P["D"]) & (P["wid"][np.minimum(t + 1, P["D"] - 1)] + m.HOLD_W + 8 < P["nw"])
    t, j, mi = t[ok], j[ok], mi[ok]
    ev = m.sim_exit(P, t, j, m.XS)
    tp, jp, pid = pairs_placebo(PL, t)
    vp = (P["wid"][tp + 1] + m.HOLD_W + 8 < P["nw"]) & ~np.isnan(P["On"][tp + 1, jp])
    tp, jp, pid = tp[vp], jp[vp], pid[vp]
    pl = m.sim_exit(P, tp, jp, m.XS)
    rows = []
    for q in range(len(m.XS) + 1):
        r = ev["ret"][q]
        info = r - mean_by_pid(pl["ret"][q], pid, len(t))
        okq = ~np.isnan(r)
        mm_n = m.mmean((r - m.COST)[okq], mi[okq])
        mm_i = m.mmean(info[okq], mi[okq])
        rows.append({"x": (m.XS[q] if q < len(m.XS) else None), "net_mean_pct": float(np.nanmean(r - m.COST) * 100), "median_pct": float(np.nanmedian(r) * 100),
                     "win_net": float(np.nanmean((r - m.COST) > 0)), "hold_weeks": float(np.nanmean(ev["hold"][q])), "trig_share": float(ev["trig"][q].mean()),
                     "info_all_pct": (None if np.isnan(m.wmean_of(mm_i, None)) else m.wmean_of(mm_i, None) * 100),
                     "net_by_window_pct": {w: (None if np.isnan(m.wmean_of(mm_n, kk)) else m.wmean_of(mm_n, kk) * 100) for kk, w in enumerate(m.WIN)}})
    return {"table": rows, "n": int(len(t))}


def extra_mfe(P, t, j):
    """60거래일 MFE/MAE (진입 시가 대비 최고 고가/최저 저가)."""
    ok = t + 1 + 61 < P["D"]
    t, j = t[ok], j[ok]
    ks = np.arange(1, 61)
    H = P["Hn"][t[:, None] + ks, j[:, None]]
    L = P["Ln"][t[:, None] + ks, j[:, None]]
    E = P["On"][t + 1, j]
    with np.errstate(all="ignore"):
        mfe = np.nanmax(H, axis=1) / E - 1
        mae = np.nanmin(L, axis=1) / E - 1
    return {"MFE60_mean_pct": float(np.nanmean(mfe) * 100), "MAE60_mean_pct": float(np.nanmean(mae) * 100)}


def run(P, sector_idx, n_perm=m.N_PERM, verbose=True):
    t0 = time.time()
    rng = np.random.default_rng(SEED)
    log = (lambda *a: print(f"[{time.time()-t0:5.0f}s]", *a, flush=True)) if verbose else (lambda *a: None)
    U, cells, F = build(P)
    log("사건", {k: len(v[0]) for k, v in cells.items()})
    M = m.outcome_mats(P)
    PL, PM, pool = m.placebo(P, U, M, rng)
    log("플라시보·결과 행렬 완료")
    ht, hj = cells["H1"]
    segm, crossm, overlap, feats = seg_masks(P, F, ht, hj, sector_idx)
    allcells = dict(cells)
    for nm, mk in segm.items():
        allcells["S:" + nm] = (ht[mk], hj[mk])
    for nm, mk in crossm.items():
        allcells["X:" + nm] = (ht[mk], hj[mk])
    summ, mis = {}, {}
    for name, (t, j) in allcells.items():
        if len(t) == 0:
            summ[name] = {"n": 0}
            continue
        mi = m.month_idx(P["dates"], t)
        s = m.cell_summary(name, t, j, mi, P, M, PM, rng)
        summ[name] = s
        mis[name] = (s["_arr"]["t"], s["_arr"]["mi"])
    log("칸 요약 완료")
    names = [n for n in allcells if summ[n]["n"] >= 1]
    nd = m.null_dist([mis[n] for n in names], pool, M["R20"], PM["R20"], rng, n_perm)
    nidx = {n: i for i, n in enumerate(names)}
    log("귀무 완료")
    out = {"cells": {}, "n_perm": n_perm, "counts": {k: int(len(v[0])) for k, v in cells.items()}, "overlap_h1_with_surge_day": overlap}
    segn = [n for n in names if n.startswith("S:") and summ[n]["n"] >= MIN_N]
    cols = [nidx[n] for n in segn]
    mx = np.nanmax(np.abs(nd[:, cols, 0]), axis=1) if cols else np.array([np.nan])
    B = float(np.nanpercentile(mx, 95)) if cols else float("nan")
    out["floor_B_seg"] = B
    for n in names:
        c = {k: v for k, v in summ[n].items() if k != "_arr"}
        c["null_p"] = {"p99_all": float(np.nanpercentile(nd[:, nidx[n], 1], 99)), "p1_all": float(np.nanpercentile(nd[:, nidx[n], 1], 1))}
        if n in segn:
            d = c["info_mean"]
            tr, va, te = d["TRAIN"], d["VALID"], d["TEST"]
            ok1 = abs(tr) > B
            ok2 = bool(np.sign(va) == np.sign(te) == np.sign(tr) and abs(va) >= .5 * abs(tr) and abs(te) >= .5 * abs(tr))
            ct, cv = c["ci"]["TRAIN"], c["ci"]["VALID"]
            ok3 = bool(not (ct[0] <= 0 <= ct[1]) and not (cv[0] <= 0 <= cv[1])) if not np.isnan(ct[0]) and not np.isnan(cv[0]) else False
            c["conf"] = {"floor": bool(ok1), "sign_size": ok2, "ci": ok3, "status": "CONFIRMED" if (ok1 and ok2 and ok3) else ("후보(바닥선만)" if ok1 else "—")}
            if c["conf"]["status"] == "CONFIRMED" and tr > 0:
                c["conf"]["economic"] = bool((c["oos_net_mean_pct"] or -1) > 0 and (c["oos_net_ex_top20_pct"] or -1) > 0)
        out["cells"][n] = c
    j1 = {}
    for n in CENTERS:
        if n not in out["cells"]:
            continue
        c = out["cells"][n]
        a, d = c["info_all"], c["info_mean"]
        p99, p1 = c["null_p"]["p99_all"], c["null_p"]["p1_all"]
        same = all(np.sign(d[w]) == np.sign(a) for w in ("TRAIN", "VALID", "TEST"))
        ci = c["ci"]["ALL"]
        v = "INFORMATION" if (a > p99 and same and ci[0] > 0) else ("REVERSE" if (a < p1 and same and ci[1] < 0) else "NONE")
        j1[n] = {"info_all": a, "p99": p99, "p1": p1, "same_sign": bool(same), "ci_all": ci, "verdict": v}
    out["J1"] = j1
    # J4
    if segn:
        cl = [nidx[n] for n in segn]
        mxs, mns = np.nanmax(nd[:, cl, 0], axis=1), np.nanmin(nd[:, cl, 0], axis=1)
        tv = lambda n: np.nan_to_num(out["cells"][n]["info_mean"]["TRAIN"], nan=0.0)
        best, worst = max(segn, key=tv), min(segn, key=tv)
        bd, wd = out["cells"][best]["info_mean"], out["cells"][worst]["info_mean"]
        out["J4"] = {"cells": len(segn), "best": best, "best_train": bd["TRAIN"], "p95_max": float(np.nanpercentile(mxs, 95)), "best_valid": bd["VALID"], "best_test": bd["TEST"],
                     "candidate": bool(bd["TRAIN"] > np.nanpercentile(mxs, 95) and bd["VALID"] > 0 and bd["TEST"] > 0),
                     "worst": worst, "worst_train": wd["TRAIN"], "p5_min": float(np.nanpercentile(mns, 5)), "worst_valid": wd["VALID"], "worst_test": wd["TEST"],
                     "reverse_candidate": bool(wd["TRAIN"] < np.nanpercentile(mns, 5) and wd["VALID"] < 0 and wd["TEST"] < 0)}
    # 층 2: 돌파선 이탈
    ex = {}
    keep = {}
    for n in CENTERS:
        t, j = cells[n]
        mi = m.month_idx(P["dates"], t)
        blk, ev, mi2 = line_exit_block(P, F["hi252"] if n == "H1" else F["hiall"], t, j, PL, mi)
        blk["mfe60"] = extra_mfe(P, t, j)
        ex[n] = {"line": blk}
        keep[n] = (ev, mi2)
    for n in ("H1", "TJ"):
        t, j = cells[n]
        mi = m.month_idx(P["dates"], t)
        ex[n]["weekly"] = weekly_block(P, t, j, PL, mi)
    out["exits"] = ex
    # J3: H1, k=5% vs 무이탈 (짝지은 차이)
    ev, mi = keep["H1"]
    diff = ev["ret"][KS.index(0.05)] - ev["ret"][len(KS)]
    okd = ~np.isnan(diff)
    mmd = m.mmean(diff[okd], mi[okd])
    rng2 = np.random.default_rng(SEED + 1)
    j3 = {"mean_pct": m.wmean_of(mmd, None) * 100, "by_window_pct": {w: m.wmean_of(mmd, k) * 100 for k, w in enumerate(m.WIN)},
          "ci_pct": [x * 100 for x in m.block_ci(mmd, (m.WM >= 0) & (m.WM <= 2), rng2)], "n": int(okd.sum())}
    sg = [np.sign(j3["by_window_pct"][w]) for w in ("TRAIN", "VALID", "TEST")]
    if j3["ci_pct"][0] > 0 and len(set(sg)) == 1 and sg[0] > 0:
        j3["verdict"] = "돌파선 5% 이탈이 보유보다 낫다"
    elif j3["ci_pct"][1] < 0 and len(set(sg)) == 1 and sg[0] < 0:
        j3["verdict"] = "돌파선 5% 이탈이 해롭다(보유가 낫다)"
    else:
        j3["verdict"] = "NONE (구간·신뢰구간 기준 미충족)"
    out["J3"] = j3
    # 상위 20건 (H1·TJ 20일 수익)
    tops = {}
    for n in ("H1", "TJ"):
        t, j = cells[n]
        r20 = M["R20"][t, j].astype(float)
        od = np.argsort(-np.nan_to_num(r20, nan=-9))[:20]
        tops[n] = [{"t": int(t[i]), "j": int(j[i]), "ret_pct": float(r20[i] * 100)} for i in od]
    out["top20"] = tops
    out["segnames"] = segn
    log("완료")
    return out


# ───────────────────── 출력 ─────────────────────
def f(x, d=2, pct=False, sign=True):
    return m.f(x, d, pct, sign)


def render(out, P, tick, names):
    j1 = out["J1"]
    verd = {k: v["verdict"] for k, v in j1.items()}
    seg_conf = [n for n in out["segnames"] if out["cells"][n].get("conf", {}).get("status") == "CONFIRMED"]
    pos = [n for n in seg_conf if out["cells"][n]["info_mean"]["TRAIN"] > 0]
    neg = [n for n in seg_conf if out["cells"][n]["info_mean"]["TRAIN"] <= 0]
    top = "INFORMATION" if (any(v == "INFORMATION" for v in verd.values()) or pos) else ("REVERSE" if (any(v == "REVERSE" for v in verd.values()) or neg) else "NONE")
    L = ["---", "track: kr", "factor: new-high-breakout", "date: 2026-10-08", f"verdict: {top}", "criteria_version: research-only (new-high-breakout-preregistration-2026-10)",
         "conditions: [\"중심 칸 H1·H2·TJ J1 99백분위\", \"H1 세분화 17칸 가족 바닥선\", \"돌파선 이탈 J3 = 5% vs 무이탈\", \"플라시보 20종목 대비 Info\"]",
         "reason: >-", f"  신호: J1 {verd} · 세분화 CONFIRMED 양(+) {len(pos)}칸·음(−, 반대 방향) {len(neg)}칸 · 경제성: 별도 표. 돌파선 이탈 J3: {out['J3']['verdict']}.", "---", ""]
    L.append("# 신고가 돌파(저스템형) 유형 — 결과\n")
    L.append("수치는 `new_high_breakout.py` 가 계산해 그대로 옮긴 값이다. 정의·구간·판정은 사전등록(f1563a3b) 그대로이며 결과를 보고 바꾸지 않았다. Info = 20거래일 수익(진입 시가→20일 뒤 시가) − 같은 진입일 플라시보 20종목 평균(단위 %p).\n")
    L.append("## 1. J1 — 중심 칸 3개\n")
    L.append("| 칸 | 사건 | Info 전체 | TRAIN | VALID | TEST | 2026(기록) | 귀무 p99 | 귀무 p1 | 부호 일치 | 구간 95% | 판정 | 비용 후 OOS 평균(%) | 중앙 수익(%) | 승률(비용 후) |")
    L.append("|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|")
    lab = {"H1": "H1 52주 신고가 첫날", "H2": "H2 역사적 신고가 첫날", "TJ": "TJ 저스템형"}
    for n, v in j1.items():
        c = out["cells"][n]
        d = c["info_mean"]
        L.append(f"| {lab[n]} | {c['n']:,} | {f(v['info_all'],2,True)} | {f(d['TRAIN'],2,True)} | {f(d['VALID'],2,True)} | {f(d['TEST'],2,True)} | {f(d['REC'],2,True)} | {f(v['p99'],2,True)} | {f(v['p1'],2,True)} | {'O' if v['same_sign'] else 'x'} | [{f(v['ci_all'][0],2,True)}, {f(v['ci_all'][1],2,True)}] | {v['verdict']} | {f(c['oos_net_mean_pct'])} | {f(c['median_ret_pct'])} | {f(c['win_rate_net'],2,False,False)} |")
    L.append(f"\nH1 사건 중 당일 +8%·거래량 5배(급등일) 비율 {f(out['overlap_h1_with_surge_day'],2,True,False)}%.\n")
    L.append("## 2. H1 세분화 17칸 (가족 바닥선 B = %s %%p, 사건 < %d 칸 제외)\n" % (f(out["floor_B_seg"], 2, True, False), MIN_N))
    L.append("| 칸 | 사건 | TRAIN | VALID | TEST | ① 바닥선 | ② 부호·크기 | ③ 구간 | 상태 | 비용 후 OOS(%) | 상위20 제외(%) |")
    L.append("|---|---|---|---|---|---|---|---|---|---|---|")
    for n in sorted(k for k in out["cells"] if k.startswith("S:")):
        c = out["cells"][n]
        d = c["info_mean"]
        cf = c.get("conf")
        if cf is None:
            L.append(f"| {n[2:]} | {c['n']} | - | - | - | 표본 부족 | | | | | |")
            continue
        L.append(f"| {n[2:]} | {c['n']:,} | {f(d['TRAIN'],2,True)} | {f(d['VALID'],2,True)} | {f(d['TEST'],2,True)} | {'O' if cf['floor'] else 'x'} | {'O' if cf['sign_size'] else 'x'} | {'O' if cf['ci'] else 'x'} | {cf['status']}{' · 경제성 ' + ('통과' if cf.get('economic') else '미달') if 'economic' in cf else ''} | {f(c['oos_net_mean_pct'])} | {f(c['oos_net_ex_top20_pct'])} |")
    L.append("\n### 교차 유형 (기록 전용)\n")
    L.append("| 유형 | 사건 | TRAIN | VALID | TEST | 비용 후 OOS(%) | 중앙(%) | 승률 |")
    L.append("|---|---|---|---|---|---|---|---|")
    for n in ("X:A3&C1", "X:A3&E2", "X:B3&C3"):
        c = out["cells"].get(n)
        if c:
            d = c["info_mean"]
            L.append(f"| {n[2:]} | {c['n']:,} | {f(d['TRAIN'],2,True)} | {f(d['VALID'],2,True)} | {f(d['TEST'],2,True)} | {f(c['oos_net_mean_pct'])} | {f(c['median_ret_pct'])} | {f(c['win_rate_net'],2,False,False)} |")
    j4 = out.get("J4")
    if j4:
        L.append("\n## 3. J4 — 격자 최댓값 검정 (탐색 후보, 채택 아님)\n")
        L.append(f"- 최고 TRAIN 칸 {j4['best'][2:]} {f(j4['best_train'],2,True)}%p (가짜 격자 최댓값 p95 {f(j4['p95_max'],2,True)}) · VALID {f(j4['best_valid'],2,True)} · TEST {f(j4['best_test'],2,True)} → 후보 {'O' if j4['candidate'] else 'x'}")
        L.append(f"- 최저 TRAIN 칸 {j4['worst'][2:]} {f(j4['worst_train'],2,True)}%p (가짜 최솟값 p5 {f(j4['p5_min'],2,True)}) · VALID {f(j4['worst_valid'],2,True)} · TEST {f(j4['worst_test'],2,True)} → 반대 후보 {'O' if j4['reverse_candidate'] else 'x'}")
    L.append("\n## 4. 연속성·MFE/MAE (중심 칸, 사건 평균 / 플라시보 평균 / 차이)\n")
    L.append("| 칸 | 첫 5일 상승일 비율 | 신호 종가→5일 양 | →20일 양 | MFE5 | MAE5 | MFE20 | MAE20 | MFE≥10% & MAE>−10% | MFE60 평균 | MAE60 평균 |")
    L.append("|---|---|---|---|---|---|---|---|---|---|---|")
    for n in CENTERS:
        c = out["cells"][n]["cont"]
        def cc(k, pct=False):
            x = c[k]
            return f"{f(x['event'],2,pct,False)} / {f(x['placebo'],2,pct,False)} / {f(x['diff'],2,pct)}"
        mf = out["exits"][n]["line"]["mfe60"]
        L.append(f"| {n} | {cc('UP5')} | {cc('POS5')} | {cc('POS20')} | {cc('MFE5',pct=True)} | {cc('MAE5',pct=True)} | {cc('MFE20',pct=True)} | {cc('MAE20',pct=True)} | {f(c['MFE10_MAE_gt_m10_share'],2,False,False)} | {f(mf['MFE60_mean_pct'])}% | {f(mf['MAE60_mean_pct'])}% |")
    L.append("\n## 5. 돌파선 이탈 (종가 ≤ 돌파선 × (1−k) → 다음 거래일 시가 청산, 최대 130거래일, 비용 23.54bp 차감, Info = 플라시보에 같은 비율 선 적용)\n")
    j3 = out["J3"]
    L.append(f"**J3 (H1, k=5% 이탈 − 무이탈)**: {j3['verdict']} · 평균 {f(j3['mean_pct'])}%p, 구간 [{f(j3['ci_pct'][0])}, {f(j3['ci_pct'][1])}], 구간별 {', '.join(w + ' ' + f(v) for w, v in j3['by_window_pct'].items())}\n")
    for n in CENTERS:
        e = out["exits"][n]["line"]
        L.append(f"### {n} (사건 {e['n']:,}건)\n")
        L.append("| 이탈 k | 비용 후 평균(%) | 중앙(%) | 승률 | 평균 보유(일) | 발동 비율 | Info(%p) | TRAIN | VALID | TEST |")
        L.append("|---|---|---|---|---|---|---|---|---|---|")
        for r in e["table"]:
            kl = "무이탈(130일)" if r["k"] is None else f"{int(r['k']*100)}%"
            nb = r["net_by_window_pct"]
            L.append(f"| {kl} | {f(r['net_mean_pct'])} | {f(r['median_pct'])} | {f(r['win_net'],2,False,False)} | {f(r['hold_days'],1,False,False)} | {f(r['trig_share'],2,False,False)} | {f(r['info_all_pct'])} | {f(nb['TRAIN'])} | {f(nb['VALID'])} | {f(nb['TEST'])} |")
        q = e["line_return_days_quantiles"]
        L.append(f"\n돌파선 아래 종가가 처음 나오기까지 일수(발동 사건, 분위 10·25·50·75·90): {', '.join(f(v,0,False,False) for v in q) if q else '-'} · 60거래일 안 재이탈 비율 {f(e['share_line_lost_within_60d'],2,False,False)} · 130일 안 재이탈 비율 {f(e['share_line_lost_ever'],2,False,False)}\n")
    L.append("## 6. 주간 최고가 대비 x% 이탈 격자 (H1·TJ, 기록 전용)\n")
    for n in ("H1", "TJ"):
        e = out["exits"][n]["weekly"]
        L.append(f"### {n} (사건 {e['n']:,}건)\n")
        L.append("| 이탈 x | 비용 후 평균(%) | 중앙(%) | 승률 | 평균 보유(주) | 발동 비율 | Info(%p) | TRAIN | VALID | TEST |")
        L.append("|---|---|---|---|---|---|---|---|---|---|")
        for r in e["table"]:
            xl = "무이탈(26주)" if r["x"] is None else f"{int(r['x']*100)}%"
            nb = r["net_by_window_pct"]
            L.append(f"| {xl} | {f(r['net_mean_pct'])} | {f(r['median_pct'])} | {f(r['win_net'],2,False,False)} | {f(r['hold_weeks'],1,False,False)} | {f(r['trig_share'],2,False,False)} | {f(r['info_all_pct'])} | {f(nb['TRAIN'])} | {f(nb['VALID'])} | {f(nb['TEST'])} |")
        L.append("")
    L.append("## 7. 20일 수익 상위 20건 (H1 · TJ)\n")
    for n in ("H1", "TJ"):
        L.append(f"### {n}\n")
        L.append("| 종목 | 신호일 | 20일 수익 |")
        L.append("|---|---|---|")
        for r in out["top20"][n]:
            tk = tick[r["j"]]
            L.append(f"| {names.get(tk, tk)}({tk}) | {pd.Timestamp(P['dates'][r['t']]).strftime('%Y-%m-%d')} | {r['ret_pct']:+.1f}% |")
        L.append("")
    L.append("## 8. 사전등록 대조\n")
    L.append("- 정의·구간·비용·플라시보·판정 규칙 모두 사전등록대로. 에피소드 중복 제거는 같은 종목·같은 칸 130거래일, 세분화는 H1 중심 칸 사건의 부분집합.")
    L.append("- 한계: 업종 현재 분류 · 폐지 종목은 마지막 종가가 청산가 · 상·하한가·동시호가 체결 불가 미반영 · 칸은 포개져 독립이 아님 · 가짜 격자는 독립 추출이라 J4 바닥선이 보수적 · 고가 기준 돌파라 사건의 약 60% 가 급등일(겹침 비율 위).")
    L.append("- 이 결과는 점수·매매·종목 선별에 연결하지 않는다.")
    return "\n".join(L) + "\n", top


def main():
    t0 = time.time()
    dates, tick, raw = m.load_raw()
    print(f"로드 {len(dates)}일 × {len(tick)}종목 ({time.time()-t0:.0f}s)", flush=True)
    P = m.derive(raw, dates)
    del raw
    items = json.load(open(m.A5, encoding="utf-8"))["items"]
    sec = {x["t"]: x["s"] for x in items if x.get("s")}
    sidx = {s: i for i, s in enumerate(sorted(set(sec.values())))}
    sector_idx = np.array([sidx.get(sec.get(tk), -1) for tk in tick])
    names = {x["t"]: x["n"] for x in items}
    out = run(P, sector_idx)
    OUT.with_suffix(".json").write_text(json.dumps(out, ensure_ascii=False, indent=1, default=lambda o: float(o) if isinstance(o, (np.floating, np.integer)) else str(o)), encoding="utf-8")
    md, top = render(out, P, tick, names)
    OUT.with_suffix(".md").write_text(md, encoding="utf-8")
    print("verdict", top, "| J1", {k: v["verdict"] for k, v in out["J1"].items()}, "| J3", out["J3"]["verdict"])


# ───────────────────── 자체 시험 ─────────────────────
def selftest():
    fails = []

    def check(n, c):
        print(("OK  " if c else "FAIL"), n)
        if not c:
            fails.append(n)

    # 1. 결정적 H1: 종목 0 은 520일 평평 → t=520 첫 돌파, 이후는 첫날이 아님
    D, N = 900, 2
    BK = 520
    dates = pd.bdate_range("2016-01-04", periods=D)
    C = np.full((D, N), 100.0)
    C[BK:, 0] = [101.0 + 0.1 * i for i in range(D - BK)]
    O = C.copy()
    H = C * 1.005
    H[:BK, 0] = 100.5
    L = C * 0.995
    V = np.full((D, N), 3e7)
    raw = dict(open=O, high=H, low=L, close=C, volume=V)
    P = m.derive(raw, dates)
    U, cells, F = build(P)
    t, j = cells["H1"]
    check("H1 첫날만 사건(t=BK, 종목 0)", t.tolist() == [BK] and j.tolist() == [0])
    check("H2(역사적) 첫날도 같은 날", cells["H2"][0].tolist() == [BK])
    check("TJ 는 반등 +200% 미달로 없음", len(cells["TJ"][0]) == 0)
    # 2. 돌파선 이탈 손계산: 선 L=100, k=5% → 95 이하 종가에서 발동
    D2 = 400
    d2 = pd.bdate_range("2016-01-04", periods=D2)
    C2 = np.full((D2, 1), 110.0)
    O2 = C2.copy()
    C2[11, 0], C2[12, 0], C2[13, 0] = 102.0, 99.0, 94.0      # 진입일 t+1=11 → i=0: 102, i=1: 99, i=2: 94 (≤95 발동)
    O2[14, 0] = 93.0                                          # 청산 시가
    raw2 = dict(open=O2, high=C2 * 1.0, low=C2 * 1.0, close=C2.copy(), volume=np.full((D2, 1), 3e7))
    P2 = m.derive(raw2, d2)
    E = P2["On"][11, 0]
    ev = sim_line_exit(P2, np.array([10]), np.array([0]), np.array([100.0 / E]))
    k5 = KS.index(0.05)
    check("진입가 = 11일 시가", abs(E - O2[11, 0]) < 1e-9)
    check("k=5% 이탈: 종가 94 에서 발동 → 다음 시가 93 청산", abs(ev["ret"][k5][0] - (93.0 / E - 1)) < 1e-9 and ev["trig"][k5][0] and ev["hold"][k5][0] == 3)
    check("k=0%: 종가 99 ≤ 100 에서 먼저 발동(i=1)", ev["hold"][0][0] == 2)
    check("k=10%: 종가 94 > 90 이면 미발동 → 130일 보유", ev["hold"][KS.index(0.10)][0] == HOLD_D and not ev["trig"][KS.index(0.10)][0])
    check("무이탈 130일", ev["hold"][len(KS)][0] == HOLD_D)
    # 3. 합성 전체 파이프라인
    dts, tick, raw3 = m.synth()
    P3 = m.derive(raw3, dts)
    sidx = np.arange(len(tick)) % 7
    out = run(P3, sidx, n_perm=60, verbose=False)
    check("합성: H1 사건 존재", out["counts"]["H1"] > 30)
    s = out["cells"]
    nA = sum(s["S:" + a]["n"] for a in ("A1", "A2", "A3") if "S:" + a in s)
    check("세분화 A1+A2+A3 ≤ H1 사건 수(결측 특징 제외)", 0 < nA <= out["counts"]["H1"])
    check("J1 판정 문자열", all(v["verdict"] in ("INFORMATION", "REVERSE", "NONE") for v in out["J1"].values()) and "H1" in out["J1"])
    check("돌파선 이탈 표 5행", all(len(out["exits"][c]["line"]["table"]) == len(KS) + 1 for c in out["exits"] if "line" in out["exits"][c]))
    check("J3 산출", isinstance(out["J3"]["verdict"], str))
    print("selftest", "PASS" if not fails else f"FAIL {fails}")
    return 1 if fails else 0


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--selftest", action="store_true")
    a = ap.parse_args()
    if a.selftest:
        sys.exit(selftest())
    main()
