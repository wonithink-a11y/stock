#!/usr/bin/env python3
"""상승 모멘텀 5종(급등일·주간 급등·연속 상승일·연속 상승 주·꾸준 상승) 이후 지속·소멸 + 주간 최고가 대비 이탈 — 결과 산출.
사전등록: findings/surge-day-continuation-preregistration-2026-10.md (커밋 d57299ec). 정의·구간·판정은 사전등록 그대로이며 결과를 보고 바꾸지 않는다.

    python research/strategy-lab/surge_day_continuation.py --selftest
    python research/strategy-lab/surge_day_continuation.py            # A2a+A2b 일봉 필요, 산출 findings/surge-day-continuation-results-2026-10.{md,json}

구현 세부(사전등록이 열어 둔 부분, 실행 전에 고정):
  · 세분화 17칸·복합 유형 T1~T3 = 급등일 중심 칸(D:center)의 **에피소드 제거 뒤 사건의 부분집합**(칸마다 따로 다시 제거하지 않는다).
  · 플라시보 20종목 = 같은 진입 신호일의 적격 종목(유동·기업행사 제외·진입 시가 유효) 중 **어떤 가족·칸에서든 사건이 있던 종목(합집합) 제외** 후 무작위(시드 고정).
  · 가짜 사건(귀무) = 같은 수·같은 진입일 분포로 적격 종목-일을 뽑아 Info = 수익 − 그날 플라시보 평균. 가짜 격자의 칸은 서로 독립으로 뽑는다(실제 격자는 포개져 있어 바닥선이 보수적).
  · 'Info 평균' = 진입월 평균들의 구간(또는 전체) 평균. 부트스트랩 = 진입월 6개월 이동 블록 2,000회.
  · '다음 주·다음 4주 수익 > 0' = 신호 종가 → 5·20거래일 뒤 종가. MFE/MAE = 진입 시가 대비 향후 5·20거래일 최고 고가/최저 저가.
  · 폐지 종목은 마지막 종가가 청산가로 이어진다(ffill, 기록 한계). 데이터 끝 margin 175거래일은 사건에서 제외(보유 창 부족).
"""
from __future__ import annotations

import argparse
import gzip
import re
import json
import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd

LAB = Path(__file__).resolve().parent
REPO = LAB.parents[1]
A2A, A2B = REPO / "data" / "backfill" / "price" / "a2a", REPO / "data" / "backfill" / "price" / "a2b"
A5 = REPO / "docs" / "data" / "a5-latest.json"
OUT = LAB / "findings" / "surge-day-continuation-results-2026-10"
SEED = 20261013
COST, COST_STRESS = 0.002354, 0.00335
EP, MARGIN, MINN = 130, 175, 80
N_PERM, N_BOOT, BLOCK, NPLAC = 1000, 2000, 6, 20
LIQ_MIN = 2e9
HOLD_W = 26
XS = [0.10, 0.15, 0.20, 0.25, 0.30, 0.40]
WIN = ["TRAIN", "VALID", "TEST", "REC"]
WYEARS = {"TRAIN": (2016, 2020), "VALID": (2021, 2022), "TEST": (2023, 2025), "REC": (2026, 2026)}
Y0 = 2016


# ───────────────────── 자료 ─────────────────────
def load_raw():
    rows = []
    for base in (A2A, A2B):
        for y in range(2015, 2027):
            f = base / f"{y}.jsonl.gz"
            if not f.exists():
                continue
            with gzip.open(f, "rt", encoding="utf-8") as fh:
                for line in fh:
                    d = json.loads(line)
                    rows.append((d["ticker"], d["date"], d["open"], d["high"], d["low"], d["close"], d["volume"]))
    df = pd.DataFrame(rows, columns=["ticker", "date", "open", "high", "low", "close", "volume"]).drop_duplicates(["ticker", "date"])
    df["date"] = pd.to_datetime(df["date"])
    dates = np.unique(df["date"].values)
    tick = np.array(sorted(df["ticker"].astype(str).unique()))
    di = np.searchsorted(dates, df["date"].values)
    ti = np.searchsorted(tick, df["ticker"].astype(str).values)
    out = {}
    for c in ("open", "high", "low", "close", "volume"):
        M = np.full((len(dates), len(tick)), np.nan)
        M[di, ti] = df[c].values.astype(float)
        out[c] = M
    return pd.DatetimeIndex(dates), list(tick), out


def sh(A, k):
    """행 t 가 A[t+k] 를 갖도록 이동 (범위 밖은 NaN)."""
    R = np.full_like(A, np.nan, dtype=float)
    if k >= 0:
        if k < len(A):
            R[: len(A) - k] = A[k:]
    else:
        R[-k:] = A[: len(A) + k]
    return R


def ffill0(A):
    return pd.DataFrame(A).ffill().to_numpy()


def derive(raw, dates):
    O, H, L, C, V = (raw[k] for k in ("open", "high", "low", "close", "volume"))
    D, N = C.shape
    hz = (O == 0) & (V == 0)
    On, Hn, Ln, Cn, Vn = (np.where(M > 0, M, np.nan) for M in (O, H, L, C, V))
    Cff = ffill0(Cn)
    tv = pd.DataFrame(Cn * Vn).shift(1).rolling(20, min_periods=15).mean().to_numpy()
    liquid = tv >= LIQ_MIN
    vavg = pd.DataFrame(Vn).shift(1).rolling(20, min_periods=15).mean().to_numpy()
    vr = Vn / vavg
    ret1 = Cn / sh(Cn, -1) - 1
    # 기업행사(정지) 제외: [t-20, t+30] 안에 연속 2일 이상 정지
    h2 = hz & (np.vstack([np.zeros((1, N), bool), hz[:-1]]) | np.vstack([hz[1:], np.zeros((1, N), bool)]))
    cs = np.vstack([np.zeros((1, N)), np.cumsum(h2, axis=0)])
    t = np.arange(D)
    hi, lo = np.minimum(t + 31, D), np.maximum(t - 20, 0)
    halt = (cs[hi] - cs[lo]) > 0
    entry_ok = ~np.isnan(sh(On, 1))
    start = int(np.searchsorted(dates, pd.Timestamp(f"{Y0}-01-04"))) - 1
    tmask = np.zeros(D, bool)
    tmask[max(start, 0): D - MARGIN] = True
    elig = liquid & ~halt & entry_ok & tmask[:, None]
    # 주 구조
    wid = pd.factorize(pd.Series(dates.to_period("W-FRI")))[0]
    li = np.flatnonzero(np.r_[wid[1:] != wid[:-1], True])
    fi = np.flatnonzero(np.r_[True, wid[1:] != wid[:-1]])
    nw = len(li)
    Wc = Cff[li]
    Wcv = Cn[li]
    Wo = pd.DataFrame(On).groupby(wid).first().to_numpy()
    prev = np.vstack([Wc[:1], Wc[:-1]])
    Wo = np.where(np.isnan(Wo), prev, Wo)
    Wv = np.add.reduceat(np.nan_to_num(Vn), fi, axis=0)
    lv = np.array([np.flatnonzero(~np.isnan(Cn[:, j]))[-1] if (~np.isnan(Cn[:, j])).any() else -1 for j in range(N)])
    return dict(D=D, N=N, dates=dates, On=On, Hn=Hn, Ln=Ln, Cn=Cn, Vn=Vn, Cff=Cff, liquid=liquid, vr=vr, ret1=ret1, elig=elig, halt=halt,
                wid=wid, li=li, fi=fi, nw=nw, Wc=Wc, Wcv=Wcv, Wo=Wo, Wv=Wv, lv=lv)


# ───────────────────── 사건 탐지 ─────────────────────
def streak(up):
    st = np.zeros(up.shape, np.int32)
    for i in range(1, len(up)):
        st[i] = np.where(up[i], st[i - 1] + 1, 0)
    return st


def to_daily(maskw, P):
    out = np.zeros((P["D"], P["N"]), bool)
    out[P["li"]] = maskw
    return out


def dedup(t, j, gap=EP):
    """같은 종목에서 직전 '유지된' 사건 신호일로부터 gap 거래일 안의 새 사건은 버린다. (t, j) 정렬 반환."""
    if len(t) == 0:
        return t, j
    o = np.lexsort((t, j))
    t, j = t[o], j[o]
    keep = np.zeros(len(t), bool)
    lastj, lastt = -1, -10 ** 9
    for i in range(len(t)):
        if j[i] != lastj:
            lastj, lastt = j[i], -10 ** 9
        if t[i] - lastt > gap:
            keep[i] = True
            lastt = t[i]
    return t[keep], j[keep]


def families(P, sector_idx):
    """모든 칸의 (원시 마스크 합집합 U, {칸: (t, j)}), 중심 칸 목록, 가족별 격자 칸 목록."""
    D, N = P["D"], P["N"]
    elig = P["elig"]
    U = np.zeros((D, N), bool)
    cells, fam = {}, {}

    def reg(name, mask, family, extra=None):
        nonlocal U
        m = mask & elig
        U |= m
        t, j = np.nonzero(m)
        raw_n = len(t)
        t, j = dedup(t, j)
        cells[name] = (t, j, raw_n)
        fam.setdefault(family, []).append(name)

    ret1, vr = P["ret1"], P["vr"]
    reg("D:center", (ret1 >= 0.08) & (vr >= 5), "D")
    reg("D:relaxed", (ret1 >= 0.05) & (vr >= 3), "D")
    reg("D:strict", (ret1 >= 0.15) & (vr >= 10), "D")
    # W 주간
    Wcv, Wv = P["Wcv"], P["Wv"]
    wret = np.vstack([np.full((1, N), np.nan), Wcv[1:] / Wcv[:-1] - 1])
    prev4 = np.full(Wv.shape, np.nan)
    for w in range(4, len(Wv)):
        blk = Wv[w - 4: w]
        prev4[w] = np.where((blk > 0).all(0), blk.mean(0), np.nan)
    for w_ in (0.10, 0.15, 0.20, 0.30):
        for m_ in (0, 2):
            cond = wret >= w_
            if m_:
                cond = cond & (Wv >= m_ * prev4)
            reg(f"W:w{int(w_*100)}:m{m_}", to_daily(cond, P), "W")
    # R 연속 상승일
    Cn = P["Cn"]
    up = Cn > sh(Cn, -1)
    st = streak(up)
    for n_ in (3, 4, 5, 7):
        cum = Cn / sh(Cn, -n_) - 1
        for y_ in (0.05, 0.10, 0.15, 0.20):
            reg(f"R:N{n_}:y{int(y_*100)}", (st == n_) & (cum >= y_), "R")
    # K 연속 상승 주
    wup = np.vstack([np.zeros((1, N), bool), Wcv[1:] > Wcv[:-1]])
    wst = streak(wup)
    for k_ in (2, 3, 4, 6):
        base = np.vstack([np.full((k_, N), np.nan), Wcv[:-k_]])
        cum = Wcv / base - 1
        for c_ in (0.10, 0.20, 0.30):
            reg(f"K:k{k_}:c{int(c_*100)}", to_daily((wst == k_) & (cum >= c_), P), "K")
    # Q 꾸준 상승
    logC = np.log(Cn)
    valid = ~np.isnan(logC)
    tt = np.arange(D, dtype=float)[:, None] - D / 2.0
    y0 = np.nan_to_num(logC)
    r5 = Cn / sh(Cn, -5) - 1
    upf = np.where(np.isnan(Cn) | np.isnan(sh(Cn, -1)), np.nan, (Cn > sh(Cn, -1)).astype(float))

    def csum(A):
        return np.vstack([np.zeros((1, A.shape[1])), np.cumsum(A, axis=0)])

    Cy, Cyy, Cty, Cv_ = csum(y0), csum(y0 * y0), csum(tt * y0), csum(valid.astype(float))
    St = None
    for L_ in (20, 40, 60):
        idx = np.arange(D)
        a, b = idx + 1, np.maximum(idx + 1 - L_, 0)
        cnt = Cv_[a] - Cv_[b]
        Sy, Syy, Sty = Cy[a] - Cy[b], Cyy[a] - Cyy[b], Cty[a] - Cty[b]
        tbar = (tt[a - 1, 0] - (L_ - 1) / 2.0)[:, None]          # 창 안 t 평균 (연속 거래일)
        cov = Sty / L_ - (Sy / L_) * tbar
        vx = (L_ ** 2 - 1) / 12.0
        vy = Syy / L_ - (Sy / L_) ** 2
        with np.errstate(divide="ignore", invalid="ignore"):
            r2 = cov ** 2 / (vx * vy)
        r2 = np.where((cnt == L_) & (idx[:, None] >= L_ - 1), r2, np.nan)
        retL = Cn / sh(Cn, -L_) - 1
        worst5 = pd.DataFrame(r5).rolling(L_, min_periods=L_).min().to_numpy()
        ups = pd.DataFrame(upf).rolling(L_, min_periods=L_).mean().to_numpy()
        base = (worst5 >= -0.06) & (ups >= 0.55)
        for rho in (0.7, 0.8, 0.9):
            for r_ in (0.10, 0.20, 0.30):
                cond = base & (r2 >= rho) & (retL >= r_)
                fresh = cond & ~np.vstack([np.zeros((1, N), bool), cond[:-1]])
                reg(f"Q:L{L_}:rho{int(rho*10)}:r{int(r_*100)}", fresh, "Q")
    centers = {"D": "D:center", "W": "W:w15:m0", "R": "R:N5:y10", "K": "K:k3:c20", "Q": "Q:L40:rho8:r20"}
    return U, cells, fam, centers


# ───────────────────── 세분화 ─────────────────────
def seg_features(P, t, j, sector_idx):
    Hn, Ln, Cn = P["Hn"], P["Ln"], P["Cn"]
    D, N = P["D"], P["N"]
    if "_hi252" not in P:
        P["_hi252"] = pd.DataFrame(Hn).rolling(252, min_periods=120).max().to_numpy()
        P["_hi60"] = pd.DataFrame(Hn).shift(1).rolling(60, min_periods=40).max().to_numpy()
        P["_lo60"] = pd.DataFrame(Ln).shift(1).rolling(60, min_periods=40).min().to_numpy()
        c12 = (P["ret1"] >= 0.08) & (P["vr"] >= 5)
        S = int(sector_idx.max()) + 1
        oh = np.zeros((N, S), np.float32)
        for jj, s in enumerate(sector_idx):
            if s >= 0:
                oh[jj, s] = 1
        P["_cnt"] = c12.astype(np.float32) @ oh
        P["_c12"] = c12
    A = Cn[t, j] / P["_hi252"][t, j]
    B = P["_hi60"][t, j] / P["_lo60"][t, j] - 1
    rng_ = Hn[t, j] - Ln[t, j]
    with np.errstate(divide="ignore", invalid="ignore"):
        E = np.where(rng_ > 0, (Cn[t, j] - Ln[t, j]) / rng_, 1.0)
    s = sector_idx[j]
    F = np.where(s >= 0, P["_cnt"][t, np.maximum(s, 0)] - P["_c12"][t, j], np.nan)
    return dict(A=A, B=B, C=P["ret1"][t, j], Dv=P["vr"][t, j], E=E, F=F)


def seg_masks(f):
    A, B, C, Dv, E, F = f["A"], f["B"], f["C"], f["Dv"], f["E"], f["F"]
    m = {}
    m["A1"], m["A2"], m["A3"] = A >= 0.90, (A >= 0.60) & (A < 0.90), A < 0.60
    m["B1"], m["B2"], m["B3"] = B <= 0.30, (B > 0.30) & (B <= 0.80), B > 0.80
    m["C1"], m["C2"], m["C3"] = C < 0.15, (C >= 0.15) & (C < 0.25), C >= 0.25
    m["D1"], m["D2"], m["D3"] = Dv < 10, (Dv >= 10) & (Dv < 20), Dv >= 20
    m["E1"], m["E2"] = E >= 0.9, E < 0.9
    m["F1"], m["F2"], m["F3"] = F == 0, (F >= 1) & (F <= 2), F >= 3
    # NaN 특징은 어느 칸에도 안 들어간다 (비교가 False)
    comp = {"T1": m["B1"] & (Dv >= 10), "T2": m["A1"], "T3": m["A3"]}
    return m, comp


# ───────────────────── 결과 행렬·플라시보 ─────────────────────
def outcome_mats(P):
    On, Hn, Ln, Cn, Cff = P["On"], P["Hn"], P["Ln"], P["Cn"], P["Cff"]
    f32 = np.float32
    E = sh(On, 1)
    Xo = sh(On, 21)
    Xo = np.where(np.isnan(Xo), sh(Cff, 20), Xo)
    M = {"R20": (Xo / E - 1).astype(f32)}
    hmax = np.full_like(E, -np.inf)
    lmin = np.full_like(E, np.inf)
    up = Cn > sh(Cn, -1)
    upf = up.astype(np.float32)
    alive = np.ones_like(E, bool)
    runlen = np.zeros(E.shape, np.float32)
    ups = np.zeros(E.shape, np.float32)
    for k in range(1, 21):
        hmax = np.fmax(hmax, sh(Hn, k))
        lmin = np.fmin(lmin, sh(Ln, k))
        uk = sh(upf, k)
        if k <= 5:
            ups += np.nan_to_num(uk)
        alive &= (np.nan_to_num(uk) > 0)
        runlen += alive
        if k == 5:
            M["MFE5"], M["MAE5"] = (hmax / E - 1).astype(f32), (lmin / E - 1).astype(f32)
    M["MFE20"], M["MAE20"] = (hmax / E - 1).astype(f32), (lmin / E - 1).astype(f32)
    M["UP5"], M["RUN"] = (ups / 5).astype(f32), runlen
    M["POS5"] = np.where(np.isnan(sh(Cff, 5)) | np.isnan(Cn), np.nan, (sh(Cff, 5) > Cn)).astype(f32)
    M["POS20"] = np.where(np.isnan(sh(Cff, 20)) | np.isnan(Cn), np.nan, (sh(Cff, 20) > Cn)).astype(f32)
    for k in M:
        M[k] = np.where(np.isfinite(M[k]), M[k], np.nan).astype(f32)
    return M


def placebo(P, U, M, rng):
    """날짜별 플라시보 인덱스(D × NPLAC), 날짜별 적격 풀(CSR), 플라시보 평균(결과별 D 벡터)."""
    D = P["D"]
    ok = P["elig"] & ~np.isnan(M["R20"])
    PL = np.full((D, NPLAC), -1, np.int64)
    for t in range(D):
        pool = np.flatnonzero(ok[t] & ~U[t])
        if len(pool) == 0:
            continue
        PL[t] = rng.choice(pool, NPLAC, replace=len(pool) < NPLAC)
    PM = {}
    for k, A in M.items():
        X = np.where(PL >= 0, A[np.arange(D)[:, None], np.maximum(PL, 0)], np.nan)
        with np.errstate(all="ignore"):
            PM[k] = np.nanmean(X, axis=1)
    cnt = ok.sum(1)
    start = np.r_[0, np.cumsum(cnt)[:-1]]
    flat = np.nonzero(ok)[1]
    return PL, PM, (start, cnt, flat)


# ───────────────────── 통계 ─────────────────────
def month_idx(dates, t):
    d = dates[t + 1]
    return (d.year - Y0) * 12 + d.month - 1


def win_of_month(m):
    y = Y0 + m // 12
    for w, (a, b) in WYEARS.items():
        if a <= y <= b:
            return WIN.index(w)
    return -1


NM = (2026 - Y0 + 1) * 12
WM = np.array([win_of_month(m) for m in range(NM)])


def mmean(x, mi):
    w = ~np.isnan(x)
    s = np.bincount(mi[w], weights=x[w], minlength=NM)
    c = np.bincount(mi[w], minlength=NM)
    out = np.full(NM, np.nan)
    ok = c > 0
    out[ok] = s[ok] / c[ok]
    return out


def wmean_of(mm_, w_idx=None):
    if w_idx is None:
        sel = (WM >= 0) & (WM <= 2) & ~np.isnan(mm_)
    else:
        sel = (WM == w_idx) & ~np.isnan(mm_)
    return float(mm_[sel].mean()) if sel.any() else np.nan


def block_ci(mm_, sel, rng):
    x = mm_[sel & ~np.isnan(mm_)]
    m = len(x)
    if m < 2 * BLOCK:
        return (np.nan, np.nan)
    nb = int(np.ceil(m / BLOCK))
    st = rng.integers(0, m - BLOCK + 1, (N_BOOT, nb))
    idx = (st[:, :, None] + np.arange(BLOCK)).reshape(N_BOOT, -1)[:, :m]
    means = x[idx].mean(1)
    return (float(np.percentile(means, 2.5)), float(np.percentile(means, 97.5)))


def null_dist(cell_arrays, pool, M20, PM20, rng, n_rep):
    """cell_arrays: [(t, mi)] → (n_rep, ncell, 2) = [TRAIN 평균, 전체(TRAIN~TEST) 평균] 가짜 사건 평균 Info."""
    start, cnt, flat = pool
    out = np.full((n_rep, len(cell_arrays), 2), np.nan)
    pre = []
    for t, mi in cell_arrays:
        pre.append((t, mi, start[t], cnt[t], PM20[t]))
    for r in range(n_rep):
        for c, (t, mi, st, ln, pm) in enumerate(pre):
            if len(t) == 0:
                continue
            jr = flat[st + (rng.random(len(t)) * ln).astype(np.int64)]
            x = M20[t, jr].astype(float) - pm
            mm_ = mmean(x, mi)
            out[r, c, 0] = wmean_of(mm_, 0)
            out[r, c, 1] = wmean_of(mm_, None)
    return out


# ───────────────────── 주간 이탈 시뮬레이션 ─────────────────────
def sim_exit(P, t, j, xs):
    """각 (t, j) 쌍에 대해 xs(+무이탈) 이탈 규칙 시뮬레이션. 반환 dict: ret[x idx, n], hold, trig, peak(무이탈 최고점/진입 −1), closes(n × 34)."""
    n = len(t)
    E = P["On"][t + 1, j]
    w0 = P["wid"][t + 1]
    Wc, Wo, nw = P["Wc"], P["Wo"], P["nw"]
    ks = np.arange(HOLD_W + 8)
    wi = np.minimum(w0[:, None] + ks, nw - 1)
    closes = Wc[wi, j[:, None]]                       # n × 34
    nx = len(xs)
    ret = np.full((nx + 1, n), np.nan)
    hold = np.full((nx + 1, n), np.nan)
    trig = np.zeros((nx + 1, n), bool)
    peakx = np.full((nx + 1, n), np.nan)
    done = np.zeros((nx + 1, n), bool)
    pk = E.copy()
    xs_ = np.array(list(xs) + [np.inf])[:, None]
    for k in range(HOLD_W):
        ck = closes[:, k]
        pk = np.fmax(pk, ck)
        t_hit = (ck[None, :] <= (1 - xs_) * pk[None, :]) | (k == HOLD_W - 1)
        new = t_hit & ~done
        # 무이탈 행(xs_=inf)은 마지막 주에만 발동
        new[nx] = (k == HOLD_W - 1) & ~done[nx]
        if new.any():
            wx = np.minimum(w0 + k + 1, nw - 1)
            px = Wo[wx, j]
            r = px / E - 1
            for q in range(nx + 1):
                m = new[q]
                if m.any():
                    ret[q, m] = r[m]
                    hold[q, m] = k + 1
                    trig[q, m] = (k < HOLD_W - 1)
                    peakx[q, m] = pk[m] / E[m] - 1
            done |= new
    return dict(ret=ret, hold=hold, trig=trig, peak=peakx, closes=closes, E=E)


# ───────────────────── 실행 ─────────────────────
def cell_summary(name, t, j, mi, P, M, PM, rng, with_ci=True):
    """칸 요약: Info(20일)·연속성·MFE/MAE·구간별."""
    r20 = M["R20"][t, j].astype(float)
    pm = PM["R20"][t]
    info = r20 - pm
    ok = ~np.isnan(info)
    t, j, mi, r20, pm, info = t[ok], j[ok], mi[ok], r20[ok], pm[ok], info[ok]
    res = {"n": int(len(t)), "firms": int(len(set(j.tolist())))}
    mmI = mmean(info, mi)
    res["info_mean"] = {w: wmean_of(mmI, k) for k, w in enumerate(WIN)}
    res["info_all"] = wmean_of(mmI, None)
    res["n_win"] = {w: int(((WM[mi] == k)).sum()) for k, w in enumerate(WIN)}
    if with_ci:
        selT, selV, selA = (WM == 0), (WM == 1), ((WM >= 0) & (WM <= 2))
        res["ci"] = {"TRAIN": block_ci(mmI, selT, rng), "VALID": block_ci(mmI, selV, rng), "ALL": block_ci(mmI, selA, rng)}
    net = r20 - COST
    mm_net = mmean(net, mi)
    res["net_mean"] = {w: wmean_of(mm_net, k) for k, w in enumerate(WIN)}
    res["net_all"] = wmean_of(mm_net, None)
    res["median_ret_pct"] = float(np.median(r20) * 100) if len(r20) else None
    res["win_rate_net"] = float((net > 0).mean()) if len(net) else None
    oos = (WM[mi] == 1) | (WM[mi] == 2)
    res["oos_net_mean_pct"] = float(net[oos].mean() * 100) if oos.any() else None
    res["oos_stress_net_mean_pct"] = float((r20[oos] - COST_STRESS).mean() * 100) if oos.any() else None
    if oos.sum() > 20:
        o = np.argsort(-r20[oos])[:20]
        keep = np.ones(oos.sum(), bool)
        keep[o] = False
        res["oos_net_ex_top20_pct"] = float((net[oos][keep]).mean() * 100)
    else:
        res["oos_net_ex_top20_pct"] = None
    rec = {}
    for k in ("UP5", "RUN", "POS5", "POS20", "MFE5", "MAE5", "MFE20", "MAE20"):
        ev = M[k][t, j].astype(float)
        pk = PM[k][t]
        ok2 = ~np.isnan(ev) & ~np.isnan(pk)
        a, b = ev[ok2], pk[ok2]
        mi2 = mi[ok2]
        mm_e, mm_p = mmean(a, mi2), mmean(b, mi2)
        rec[k] = {"event": wmean_of(mm_e, None), "placebo": wmean_of(mm_p, None), "diff": wmean_of(mm_e - mm_p, None),
                  "median_event": float(np.median(a)) if len(a) else None}
    ev = M["MFE20"][t, j].astype(float)
    ea = M["MAE20"][t, j].astype(float)
    pf = M["MFE20"]
    good = ~np.isnan(ev) & ~np.isnan(ea)
    rec["MFE10_MAE_gt_m10_share"] = float(((ev[good] >= 0.10) & (ea[good] > -0.10)).mean()) if good.any() else None
    res["cont"] = rec
    res["_arr"] = dict(t=t, j=j, mi=mi, info=info, r20=r20)
    return res


def run(P, sector_idx, n_perm=N_PERM, verbose=True):
    t0 = time.time()
    rng = np.random.default_rng(SEED)
    log = (lambda *a: print(f"[{time.time()-t0:5.0f}s]", *a, flush=True)) if verbose else (lambda *a: None)
    U, cells, fam, centers = families(P, sector_idx)
    log("칸", len(cells), "| 사건(중복제거 전→후) 중심:", {k: (cells[v][2], len(cells[v][0])) for k, v in centers.items()})
    M = outcome_mats(P)
    PL, PM, pool = placebo(P, U, M, rng)
    log("플라시보·결과 행렬 완료")
    # 세분화
    ct, cj, _ = cells[centers["D"]]
    feats = seg_features(P, ct, cj, sector_idx)
    segm, compm = seg_masks(feats)
    allcells = {}
    for name, (t, j, rn) in cells.items():
        allcells[name] = (t, j)
    for nm, m in list(segm.items()) + list(compm.items()):
        allcells["S:" + nm if nm in segm else "T:" + nm] = (ct[m], cj[m])
    summ, mis = {}, {}
    for name, (t, j) in allcells.items():
        if len(t) == 0:
            summ[name] = {"n": 0}
            continue
        mi = month_idx(P["dates"], t)
        s = cell_summary(name, t, j, mi, P, M, PM, rng)
        summ[name] = s
        mis[name] = (s["_arr"]["t"], s["_arr"]["mi"])
    log("칸 요약 완료")
    # 귀무
    names = [n for n in allcells if summ[n]["n"] >= 1]
    nd = null_dist([mis[n] for n in names], pool, M["R20"], PM["R20"], rng, n_perm)
    nidx = {n: i for i, n in enumerate(names)}
    log("귀무 완료")
    out = {"cells": {}, "centers": centers, "fam": fam, "n_perm": n_perm, "_raw": {n: (cells[n][2], len(cells[n][0])) for n in cells}}
    # 가족 바닥선 B (세분화 17칸, n>=MINN)
    segnames = [n for n in names if n.startswith("S:") and summ[n]["n"] >= MINN]
    cols = [nidx[n] for n in segnames]
    mx = np.nanmax(np.abs(nd[:, cols, 0]), axis=1) if cols else np.array([np.nan])
    B = float(np.nanpercentile(mx, 95)) if cols else np.nan
    out["floor_B_seg"] = B
    # 칸 판정
    for n in names:
        s = summ[n]
        c = {k: v for k, v in s.items() if k != "_arr"}
        d = c["info_mean"]
        c["null_p"] = {"p99_all": float(np.nanpercentile(nd[:, nidx[n], 1], 99)), "p1_all": float(np.nanpercentile(nd[:, nidx[n], 1], 1))}
        if n in segnames:
            tr, va, te = d["TRAIN"], d["VALID"], d["TEST"]
            ok1 = abs(tr) > B
            ok2 = bool(np.sign(va) == np.sign(te) == np.sign(tr) and abs(va) >= .5 * abs(tr) and abs(te) >= .5 * abs(tr))
            ct_, cv_ = c["ci"]["TRAIN"], c["ci"]["VALID"]
            ok3 = bool(not (ct_[0] <= 0 <= ct_[1]) and not (cv_[0] <= 0 <= cv_[1])) if not np.isnan(ct_[0]) and not np.isnan(cv_[0]) else False
            c["conf"] = {"floor": bool(ok1), "sign_size": ok2, "ci": ok3, "status": "CONFIRMED" if (ok1 and ok2 and ok3) else ("후보(바닥선만)" if ok1 else "—")}
            if c["conf"]["status"] == "CONFIRMED" and tr > 0:
                c["conf"]["economic"] = bool((c["oos_net_mean_pct"] or -1) > 0 and (c["oos_net_ex_top20_pct"] or -1) > 0)
        out["cells"][n] = c
    # J1 중심 칸
    j1 = {}
    for fm, n in centers.items():
        if n not in nidx:
            continue
        c = out["cells"][n]
        a = c["info_all"]
        p99, p1 = c["null_p"]["p99_all"], c["null_p"]["p1_all"]
        d = c["info_mean"]
        sg = np.sign(a)
        same = all(np.sign(d[w]) == sg for w in ("TRAIN", "VALID", "TEST"))
        ci = c["ci"]["ALL"]
        if a > p99 and same and ci[0] > 0:
            v = "INFORMATION"
        elif a < p1 and same and ci[1] < 0:
            v = "REVERSE"
        else:
            v = "NONE"
        j1[fm] = {"cell": n, "info_all": a, "p99": p99, "p1": p1, "same_sign": bool(same), "ci_all": ci, "verdict": v}
    out["J1"] = j1
    # J4 격자 최댓값
    j4 = {}
    for fm, lst in fam.items():
        use = [n for n in lst if n in nidx and summ[n]["n"] >= MINN]
        if not use:
            continue
        cl = [nidx[n] for n in use]
        mxs = np.nanmax(nd[:, cl, 0], axis=1)
        mns = np.nanmin(nd[:, cl, 0], axis=1)
        tv_ = lambda n: np.nan_to_num(out["cells"][n]["info_mean"]["TRAIN"], nan=0.0)
        best = max(use, key=tv_)
        worst = min(use, key=tv_)
        bd, wd = out["cells"][best]["info_mean"], out["cells"][worst]["info_mean"]
        j4[fm] = {"cells": len(use), "best": best, "best_train": bd["TRAIN"], "p95_max": float(np.nanpercentile(mxs, 95)),
                  "best_valid": bd["VALID"], "best_test": bd["TEST"],
                  "candidate": bool(bd["TRAIN"] > np.nanpercentile(mxs, 95) and np.sign(bd["VALID"]) == 1 and np.sign(bd["TEST"]) == 1),
                  "worst": worst, "worst_train": wd["TRAIN"], "p5_min": float(np.nanpercentile(mns, 5)),
                  "worst_valid": wd["VALID"], "worst_test": wd["TEST"],
                  "reverse_candidate": bool(wd["TRAIN"] < np.nanpercentile(mns, 5) and np.sign(wd["VALID"]) == -1 and np.sign(wd["TEST"]) == -1)}
    out["J4"] = j4
    # 용량-반응 (격자 셀 ALL 평균 Info 의 스피어만)
    dose = {}

    def sp(xs_, ys_):
        s = pd.DataFrame({"x": xs_, "y": ys_}).dropna()
        return float(s["x"].corr(s["y"], method="spearman")) if len(s) >= 4 and s["x"].nunique() > 1 else None
    def parse(n):
        o = {}
        for p in n.split(":")[1:]:
            mm = re.match(r"([A-Za-z]+)(\d+)", p)
            o[mm.group(1)] = float(mm.group(2))
        return o
    for fm, lst in fam.items():
        if fm == "D":
            continue
        use = [n for n in lst if n in out["cells"] and summ[n]["n"] >= MINN]
        rows = [(parse(n), out["cells"][n]["info_all"]) for n in use]
        axes = set().union(*[set(r[0]) for r in rows]) if rows else set()
        dose[fm] = {ax: sp([r[0].get(ax) for r in rows], [r[1] for r in rows]) for ax in sorted(axes)}
    out["dose"] = dose
    # 층 2: 주간 이탈 격자 (중심 칸 5개 + D 위치 A1~A3)
    exits = {}
    exit_cells = {fm: allcells[n] for fm, n in centers.items()}
    for a in ("A1", "A2", "A3"):
        exit_cells["D|" + a] = allcells["S:" + a]
    simcache = {}
    for key, (t, j) in exit_cells.items():
        ok = (t + 1 + HOLD_W * 5 + 40 < P["D"]) & (P["wid"][np.minimum(t + 1, P["D"] - 1)] + HOLD_W + 8 < P["nw"])
        t, j = t[ok], j[ok]
        if len(t) == 0:
            continue
        mi = month_idx(P["dates"], t)
        ev = sim_exit(P, t, j, XS)
        # 플라시보: 날짜별 20종목 (같은 규칙)
        pj = PL[t]                                     # n × 20
        okp = pj >= 0
        tp = np.repeat(t, NPLAC)[okp.ravel()]
        jp = pj.ravel()[okp.ravel()]
        pid = np.repeat(np.arange(len(t)), NPLAC)[okp.ravel()]
        vp = (P["wid"][tp + 1] + HOLD_W + 8 < P["nw"]) & ~np.isnan(P["On"][tp + 1, jp])
        tp, jp, pid = tp[vp], jp[vp], pid[vp]
        pl = sim_exit(P, tp, jp, XS)
        nxs = len(XS) + 1
        table = []
        for q in range(nxs):
            r = ev["ret"][q]
            plm = np.full(len(t), np.nan)
            if len(pid):
                s_ = np.bincount(pid, weights=np.nan_to_num(pl["ret"][q]), minlength=len(t))
                c_ = np.bincount(pid, weights=(~np.isnan(pl["ret"][q])).astype(float), minlength=len(t))
                with np.errstate(all="ignore"):
                    plm = np.where(c_ > 0, s_ / c_, np.nan)
            info = r - plm
            okq = ~np.isnan(r)
            mm_n, mm_i = mmean((r - COST)[okq], mi[okq]), mmean(info[okq], mi[okq])
            peak = ev["peak"][q]
            with np.errstate(all="ignore"):
                give = np.where(ev["trig"][q], (1 + r) / (1 + peak) - 1, np.nan)
                cap = np.where(peak > 0, r / peak, np.nan)
            row = {"x": (XS[q] if q < len(XS) else None), "n": int(okq.sum()),
                   "net_mean_pct": float(np.nanmean(r - COST) * 100), "median_pct": float(np.nanmedian(r) * 100),
                   "win_net": float(np.nanmean((r - COST) > 0)), "hold_weeks": float(np.nanmean(ev["hold"][q])),
                   "trig_share": float(ev["trig"][q].mean()), "exit_vs_peak_pct": float(np.nanmean(give) * 100) if np.isfinite(give).any() else None,
                   "capture": float(np.nanmean(cap[np.isfinite(cap)])) if np.isfinite(cap).any() else None,
                   "info_mean_all_pct": wmean_of(mm_i, None) * 100 if not np.isnan(wmean_of(mm_i, None)) else None,
                   "net_by_window_pct": {w: (wmean_of(mm_n, k) * 100 if not np.isnan(wmean_of(mm_n, k)) else None) for k, w in enumerate(WIN)}}
            table.append(row)
        # J3: 20% vs 무이탈
        diff = ev["ret"][XS.index(0.20)] - ev["ret"][len(XS)]
        okd = ~np.isnan(diff)
        mmd = mmean(diff[okd], mi[okd])
        j3 = {"mean_pct": wmean_of(mmd, None) * 100, "by_window_pct": {w: wmean_of(mmd, k) * 100 for k, w in enumerate(WIN)},
              "ci_pct": [x * 100 for x in block_ci(mmd, (WM >= 0) & (WM <= 2), rng)], "n": int(okd.sum())}
        # 정점·낙폭·재상승
        cl = ev["closes"][:, :HOLD_W]
        Eb = ev["E"]
        pkx = np.fmax.accumulate(np.concatenate([Eb[:, None], cl], axis=1), axis=1)[:, 1:]
        pk_w = np.argmax(cl, axis=1)
        pk_w = np.where(cl.max(1) <= Eb, -1, pk_w)
        fin_dd = cl[:, -1] / pkx[:, -1] - 1
        recov = {}
        mx8 = np.stack([np.nanmax(ev["closes"][:, k + 1: k + 9], axis=1) for k in range(HOLD_W)], axis=1)
        for x in XS:
            hit = cl <= (1 - x) * pkx
            anyh = hit.any(1)
            fk = np.argmax(hit, axis=1)
            idx = np.arange(len(fk))
            rec_ = mx8[idx, fk] > pkx[idx, fk]
            recov[str(int(x * 100))] = {"triggered": float(anyh.mean()), "recover8w": float(rec_[anyh].mean()) if anyh.any() else None}
        exits[key] = {"table": table, "J3_20_vs_hold": j3, "peak_week_quantiles": [float(np.percentile(pk_w, q_)) for q_ in (10, 25, 50, 75, 90)],
                      "peak_never_above_entry": float((pk_w == -1).mean()), "final_dd_from_peak_median_pct": float(np.median(fin_dd) * 100),
                      "recover_after_first_touch": recov, "n": int(len(t))}
    out["exits"] = exits
    # J3 판정(D 중심)
    jd = exits["D"]["J3_20_vs_hold"]
    signs = [np.sign(jd["by_window_pct"][w]) for w in ("TRAIN", "VALID", "TEST")]
    if jd["ci_pct"][0] > 0 and len(set(signs)) == 1 and signs[0] > 0:
        out["J3"] = "20% 이탈이 무이탈보다 낫다"
    elif jd["ci_pct"][1] < 0 and len(set(signs)) == 1 and signs[0] < 0:
        out["J3"] = "20% 이탈이 해롭다(무이탈이 낫다)"
    else:
        out["J3"] = "NONE (구간·신뢰구간 기준 미충족)"
    out["_summ"] = {n: {k: v for k, v in s.items() if k != "_arr"} for n, s in summ.items()}
    # 상위 20건 (D 중심, 20일 수익)
    t, j = allcells[centers["D"]]
    r20 = M["R20"][t, j].astype(float)
    od = np.argsort(-np.nan_to_num(r20, nan=-9))[:20]
    out["top20_D"] = [{"t": int(t[i]), "j": int(j[i]), "ret_pct": float(r20[i] * 100)} for i in od]
    out["segnames"] = segnames
    out["n_cells"] = len(out["cells"])
    log("완료")
    return out


# ───────────────────── 출력 ─────────────────────
def f(x, d=2, pct=False, sign=True):
    if x is None or (isinstance(x, float) and np.isnan(x)):
        return "-"
    v = x * 100 if pct else x
    return f"{v:+.{d}f}" if sign else f"{v:.{d}f}"


def render(out, P, tick, names):
    L = ["---\ntrack: kr\nfactor: surge-day-continuation\ndate: 2026-10-08\n"]
    j1 = out["J1"]
    verd = {k: v["verdict"] for k, v in j1.items()}
    seg_conf = [n for n in out["segnames"] if out["cells"][n].get("conf", {}).get("status") == "CONFIRMED"]
    anyinfo = any(v == "INFORMATION" for v in verd.values())
    anyrev = any(v == "REVERSE" for v in verd.values())
    top = "INFORMATION" if (anyinfo or seg_conf) else ("REVERSE" if anyrev else "NONE")
    L.append(f"verdict: {top}\ncriteria_version: research-only (surge-day-continuation-preregistration-2026-10)\n"
             f"conditions: [\"가족 D·W·R·K·Q 중심 칸 5개 J1 99백분위\", \"급등일 세분화 17칸 가족 바닥선\", \"주간 최고가 대비 x% 이탈 격자(J3 = 20% vs 무이탈)\", \"플라시보 20종목 대비 Info\"]\n"
             f"reason: >-\n  신호: J1 {verd} · 세분화 CONFIRMED {len(seg_conf)}칸 · 경제성: 별도 표. 이탈 J3: {out['J3']}.\n---\n")
    L.append("# 상승 모멘텀 5종 이후 지속·소멸 + 주간 이탈 — 결과\n")
    L.append("수치는 `surge_day_continuation.py` 가 계산해 그대로 옮긴 값이다. 정의·구간·판정은 사전등록(d57299ec) 그대로이며 결과를 보고 바꾸지 않았다. Info = 20거래일 수익(진입 시가→20일 뒤 시가) − 같은 진입일 플라시보 20종목 평균(단위 %p).\n")
    L.append("## 1. J1 — 가족별 중심 칸 (전체 사건)\n")
    L.append("| 가족 | 칸 | 사건 | Info 전체 | TRAIN | VALID | TEST | 2026(기록) | 귀무 p99 | 귀무 p1 | 부호 일치 | 구간 95% | 판정 |")
    L.append("|---|---|---|---|---|---|---|---|---|---|---|---|---|")
    for fm, v in j1.items():
        c = out["cells"][v["cell"]]
        d = c["info_mean"]
        L.append(f"| {fm} | {v['cell']} | {c['n']:,} | {f(v['info_all'],2,True)} | {f(d['TRAIN'],2,True)} | {f(d['VALID'],2,True)} | {f(d['TEST'],2,True)} | {f(d['REC'],2,True)} | {f(v['p99'],2,True)} | {f(v['p1'],2,True)} | {'O' if v['same_sign'] else 'x'} | [{f(v['ci_all'][0],2,True)}, {f(v['ci_all'][1],2,True)}] | {v['verdict']} |")
    L.append("\n사건 수(중복 제거 전 → 후): " + " · ".join(f"{k} {out['_raw'][v][0]:,}→{out['_raw'][v][1]:,}" for k, v in out["centers"].items()) + "\n")
    L.append("## 2. 급등일 세분화 17칸 (가족 바닥선 B = %s %%p, 사건 < %d 칸 제외)\n" % (f(out["floor_B_seg"], 2, True, False), MINN))
    L.append("| 칸 | 사건 | TRAIN | VALID | TEST | ① 바닥선 | ② 부호·크기 | ③ 구간 | 상태 | 비용 후 OOS 평균(%) | 상위20 제외(%) |")
    L.append("|---|---|---|---|---|---|---|---|---|---|---|")
    for n in sorted(k for k in out["cells"] if k.startswith("S:")):
        c = out["cells"][n]
        d = c["info_mean"]
        cf = c.get("conf")
        if cf is None:
            L.append(f"| {n[2:]} | {c['n']} | - | - | - | 표본 부족 | | | | | |")
            continue
        L.append(f"| {n[2:]} | {c['n']:,} | {f(d['TRAIN'],2,True)} | {f(d['VALID'],2,True)} | {f(d['TEST'],2,True)} | {'O' if cf['floor'] else 'x'} | {'O' if cf['sign_size'] else 'x'} | {'O' if cf['ci'] else 'x'} | {cf['status']}{' · 경제성 ' + ('통과' if cf.get('economic') else '미달') if 'economic' in cf else ''} | {f(c['oos_net_mean_pct'])} | {f(c['oos_net_ex_top20_pct'])} |")
    L.append("\n### 복합 유형 (기록 전용)\n")
    L.append("| 유형 | 사건 | TRAIN | VALID | TEST | 비용 후 OOS 평균(%) | 중앙 수익(%) | 승률(비용 후) |")
    L.append("|---|---|---|---|---|---|---|---|")
    for n, lab in (("T:T1", "T1 횡보 후 폭발"), ("T:T2", "T2 신고가 돌파"), ("T:T3", "T3 바닥 반등")):
        c = out["cells"].get(n)
        if c:
            d = c["info_mean"]
            L.append(f"| {lab} | {c['n']:,} | {f(d['TRAIN'],2,True)} | {f(d['VALID'],2,True)} | {f(d['TEST'],2,True)} | {f(c['oos_net_mean_pct'])} | {f(c['median_ret_pct'])} | {f(c['win_rate_net'],2,False,False)} |")
    L.append("\n## 3. 격자 전체 (Info 전체 평균 %p / TRAIN·VALID·TEST / 사건 수)\n")
    for fm in ("D", "W", "R", "K", "Q"):
        L.append(f"### {fm}\n")
        L.append("| 칸 | 사건 | Info 전체 | TRAIN | VALID | TEST | 비용 후 OOS(%) |")
        L.append("|---|---|---|---|---|---|---|")
        for n in out["fam"][fm]:
            c = out["cells"].get(n)
            if not c:
                continue
            d = c["info_mean"]
            L.append(f"| {n[2:]}{' ★' if n == out['centers'][fm] else ''} | {c['n']:,}{' (표본 부족)' if c['n'] < MINN else ''} | {f(c['info_all'],2,True)} | {f(d['TRAIN'],2,True)} | {f(d['VALID'],2,True)} | {f(d['TEST'],2,True)} | {f(c['oos_net_mean_pct'])} |")
        L.append("")
    L.append("## 4. J4 — 격자 최댓값 검정 (탐색 후보, 채택 아님)\n")
    L.append("| 가족 | 칸 수 | TRAIN 최고 칸 | TRAIN | 가짜 격자 최댓값 p95 | VALID | TEST | 후보 | TRAIN 최저 칸 | TRAIN | 가짜 최솟값 p5 | VALID | TEST | 반대 후보 |")
    L.append("|---|---|---|---|---|---|---|---|---|---|---|---|---|---|")
    for fm, v in out["J4"].items():
        L.append(f"| {fm} | {v['cells']} | {v['best'][2:]} | {f(v['best_train'],2,True)} | {f(v['p95_max'],2,True)} | {f(v['best_valid'],2,True)} | {f(v['best_test'],2,True)} | {'O' if v['candidate'] else 'x'} | {v['worst'][2:]} | {f(v['worst_train'],2,True)} | {f(v['p5_min'],2,True)} | {f(v['worst_valid'],2,True)} | {f(v['worst_test'],2,True)} | {'O' if v['reverse_candidate'] else 'x'} |")
    L.append("\n### 용량-반응 (임계를 올릴수록 Info 가 커지는가 — 스피어만 순위상관, 칸 단위)\n")
    for fm, d in out["dose"].items():
        L.append(f"- {fm}: " + ", ".join(f"{k} {f(v,2)}" for k, v in d.items()))
    L.append("\n## 5. 연속성·MFE/MAE (중심 칸, 사건 평균 / 플라시보 평균 / 차이)\n")
    L.append("| 칸 | 첫 5일 상승일 비율 | 직후 연속 상승일 수 | 신호 종가→5일 양 | →20일 양 | MFE5 | MAE5 | MFE20 | MAE20 | MFE≥10% & MAE>−10% |")
    L.append("|---|---|---|---|---|---|---|---|---|---|")
    for fm, n in out["centers"].items():
        c = out["cells"][n]["cont"]
        def cc(k, pct=False):
            x = c[k]
            return f"{f(x['event'],2,pct,False)} / {f(x['placebo'],2,pct,False)} / {f(x['diff'],2,pct)}"
        L.append(f"| {fm} | {cc('UP5')} | {cc('RUN')} | {cc('POS5')} | {cc('POS20')} | {cc('MFE5',pct=True)} | {cc('MAE5',pct=True)} | {cc('MFE20',pct=True)} | {cc('MAE20',pct=True)} | {f(c['MFE10_MAE_gt_m10_share'],2,False,False)} |")
    L.append("\n## 6. 주간 최고가 대비 x% 이탈 (진입 시가 → 다음 주 시가 청산, 최대 26주, 비용 23.54bp 차감, Info = 플라시보 20종목에 같은 규칙)\n")
    L.append(f"**J3 (D 중심 칸, 20% 이탈 − 무이탈)**: {out['J3']} · 평균 {f(out['exits']['D']['J3_20_vs_hold']['mean_pct'])}%p, 구간 [{f(out['exits']['D']['J3_20_vs_hold']['ci_pct'][0])}, {f(out['exits']['D']['J3_20_vs_hold']['ci_pct'][1])}], 구간별 {', '.join(w + ' ' + f(v) for w, v in out['exits']['D']['J3_20_vs_hold']['by_window_pct'].items())}\n")
    for key, e in out["exits"].items():
        L.append(f"### {key} (사건 {e['n']:,}건)\n")
        L.append("| 이탈 x | 비용 후 평균(%) | 중앙(%) | 승률 | 평균 보유(주) | 발동 비율 | 청산가/최고점 −1 평균(%) | 고점 포착률 | Info(%p) | TRAIN | VALID | TEST |")
        L.append("|---|---|---|---|---|---|---|---|---|---|---|---|")
        for r in e["table"]:
            xl = "무이탈(26주)" if r["x"] is None else f"{int(r['x']*100)}%"
            nb = r["net_by_window_pct"]
            L.append(f"| {xl} | {f(r['net_mean_pct'])} | {f(r['median_pct'])} | {f(r['win_net'],2,False,False)} | {f(r['hold_weeks'],1,False,False)} | {f(r['trig_share'],2,False,False)} | {f(r['exit_vs_peak_pct'])} | {f(r['capture'],2)} | {f(r['info_mean_all_pct'])} | {f(nb['TRAIN'])} | {f(nb['VALID'])} | {f(nb['TEST'])} |")
        q = e["peak_week_quantiles"]
        L.append(f"\n무이탈 경로: 정점 주 분위(10·25·50·75·90) = {', '.join(f(v,0,False,False) for v in q)} (−1 = 진입가 위로 못 오름, 비율 {f(e['peak_never_above_entry'],2,False,False)}) · 26주째 정점 대비 낙폭 중앙 {f(e['final_dd_from_peak_median_pct'])}% · 최고점 대비 −x% 첫 터치 뒤 8주 안 신고가 재갱신 비율: " +
                 ", ".join(f"{k}% → {f(v['recover8w'],2,False,False)} (터치 {f(v['triggered'],2,False,False)})" for k, v in e["recover_after_first_touch"].items()) + "\n")
    L.append("## 7. 사전등록 대조\n")
    L.append("- 사건·구간·비용·플라시보·판정 규칙 모두 사전등록대로. 에피소드 중복 제거는 같은 종목·같은 가족·같은 칸 안(130거래일), 가족·칸 간 중복은 제거하지 않았다. 세분화는 D 중심 사건에만 적용.")
    L.append("- 한계: 업종 현재 분류 · 폐지 종목은 마지막 종가가 청산가(실제 상장폐지 정리매매 손실 미반영) · 상·하한가·동시호가 체결 불가 미반영 · 일봉이라 장중 고저 순서 불명 · 격자 칸은 서로 포개져 독립이 아님 · 가짜 격자는 독립 추출이라 J4 바닥선이 보수적.")
    L.append("- 이 결과는 점수·매매·종목 선별에 연결하지 않는다.")
    return "\n".join(L) + "\n", top


def main():
    t0 = time.time()
    dates, tick, raw = load_raw()
    print(f"로드 {len(dates)}일 × {len(tick)}종목 ({time.time()-t0:.0f}s)", flush=True)
    P = derive(raw, dates)
    del raw
    items = json.load(open(A5, encoding="utf-8"))["items"]
    sec = {x["t"]: x["s"] for x in items if x.get("s")}
    snames = sorted(set(sec.values()))
    sidx = {s: i for i, s in enumerate(snames)}
    sector_idx = np.array([sidx.get(sec.get(tk), -1) for tk in tick])
    names = {x["t"]: x["n"] for x in items}
    out = run(P, sector_idx)
    OUT.with_suffix(".json").write_text(json.dumps({k: v for k, v in out.items() if k not in ("_summ",)}, ensure_ascii=False, indent=1, default=lambda o: float(o) if isinstance(o, (np.floating, np.integer)) else str(o)), encoding="utf-8")
    md, top = render(out, P, tick, names)
    OUT.with_suffix(".md").write_text(md, encoding="utf-8")
    print("verdict", top, "| J1", {k: v["verdict"] for k, v in out["J1"].items()}, "| J3", out["J3"])


# ───────────────────── 자체 시험 ─────────────────────
def synth():
    rng = np.random.default_rng(3)
    D, N = 520, 70
    dates = pd.bdate_range("2016-01-04", periods=D)
    px = np.full((D, N), 10000.0)
    vol = rng.uniform(2.5e5, 4e5, (D, N))
    drift = np.zeros((D, N))
    for t in range(60, D - 40):
        hit = rng.random(N) < 0.004
        for j in np.flatnonzero(hit):
            drift[t, j] = 0.12
            vol[t, j] *= 8
            drift[t + 1: t + 21, j] += 0.012       # 심은 지속
    ret = rng.normal(0, 0.02, (D, N)) + drift
    px = 10000 * np.exp(np.cumsum(ret, axis=0))
    O = px * (1 + rng.normal(0, 0.002, (D, N)))
    H = np.maximum(O, px) * 1.01
    L = np.minimum(O, px) * 0.99
    return dates, ["T%03d" % i for i in range(N)], dict(open=O, high=H, low=L, close=px, volume=vol)


def selftest():
    fails = []

    def check(n, c):
        print(("OK  " if c else "FAIL"), n)
        if not c:
            fails.append(n)

    # streak
    up = np.array([[0], [1], [1], [1], [0], [1]], bool)
    check("streak 길이", streak(up).ravel().tolist() == [0, 1, 2, 3, 0, 1])
    # dedup
    t = np.array([0, 50, 129, 131, 140, 5, 300])
    j = np.array([0, 0, 0, 0, 0, 1, 0])
    tt, jj = dedup(t, j)
    check("dedup 130 거래일", sorted(zip(jj.tolist(), tt.tolist())) == [(0, 0), (0, 131), (0, 300), (1, 5)])
    # sh
    A = np.arange(5, dtype=float)[:, None]
    check("sh +1", np.nan_to_num(sh(A, 1).ravel(), nan=-1).tolist() == [1, 2, 3, 4, -1])
    check("sh -1", np.nan_to_num(sh(A, -1).ravel(), nan=-1).tolist() == [-1, 0, 1, 2, 3])
    # 주 구조 + 트레일링 시뮬레이션 손계산
    dates = pd.bdate_range("2020-01-06", periods=300)      # 월요일 시작
    D = len(dates)
    N = 2
    C = np.full((D, N), 100.0)
    O = C.copy()
    # 종목 0: 진입(월요일 2번째 주) 이후 주 종가 110,120,96(−20%),...
    wk = pd.factorize(pd.Series(dates.to_period("W-FRI")))[0]
    for w, px in enumerate([100, 100, 110, 120, 96, 90] + [90] * 80):
        C[wk == w, 0] = px
        O[wk == w, 0] = px
    O[wk == 5, 0] = 95                                     # 청산일 시가
    raw = dict(open=O.copy(), high=C * 1.0, low=C * 1.0, close=C.copy(), volume=np.full((D, N), 1e6))
    raw["volume"] *= 1e3
    Pq = derive(raw, dates)
    t = np.array([4 * 0 + 4])                               # 1주차(w=1) 금요일 신호 → 다음 월요일(2주차) 진입
    # 1주차 금요일 인덱스
    t0 = int(np.flatnonzero(wk == 1)[-1])
    ev = sim_exit(Pq, np.array([t0]), np.array([0]), XS)
    # 진입가 = 2주차 시가 100? (w=2 가격 110) → 진입 시가 O[t0+1]
    E = O[t0 + 1, 0]
    check("진입가 = 다음 거래일 시가", abs(ev["E"][0] - E) < 1e-9 and E == 110)
    # 주 종가: w2=110, w3=120, w4=96 → 120 대비 −20% 이하 (96 ≤ 96) → 20% 이탈 발동 w4, 청산은 w5 시가 95
    r20 = ev["ret"][XS.index(0.20)][0]
    check("20% 이탈: 최고 주종가 120 → 96 에서 발동, 다음 주 시가 95 청산", abs(r20 - (95 / 110 - 1)) < 1e-9 and ev["trig"][XS.index(0.20)][0])
    r10 = ev["ret"][XS.index(0.10)][0]
    check("10% 이탈은 더 일찍(120→96 이전 −10% 안 닿음 → 같은 주 발동)", abs(r10 - (95 / 110 - 1)) < 1e-9)
    r40 = ev["ret"][XS.index(0.40)][0]
    check("40% 이탈은 26주 보유", ev["hold"][XS.index(0.40)][0] == HOLD_W and not ev["trig"][XS.index(0.40)][0])
    check("무이탈 보유 26주", ev["hold"][len(XS)][0] == HOLD_W)
    # 전체 파이프라인: 합성 자료
    dts, tick, raw2 = synth()
    P = derive(raw2, dts)
    sidx = np.arange(len(tick)) % 7
    out = run(P, sidx, n_perm=60, verbose=False)
    d = out["cells"]["D:center"]
    check("합성: 급등일 사건 발생", d["n"] > 20)
    check("합성: 심은 지속 → Info 양(+)", d["info_all"] > 0.02)
    check("J1 판정 산출(D 포함)", "D" in out["J1"] and all(v["verdict"] in ("INFORMATION", "REVERSE", "NONE") for v in out["J1"].values()))
    check("이탈 표 7행(6격자+무이탈)", all(len(e["table"]) == 7 for e in out["exits"].values()))
    check("J3 문자열", isinstance(out["J3"], str))
    print("selftest", "PASS" if not fails else f"FAIL {fails}")
    return 1 if fails else 0


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--selftest", action="store_true")
    a = ap.parse_args()
    if a.selftest:
        sys.exit(selftest())
    main()
