#!/usr/bin/env python3
"""연금계좌용 주도섹터·30년물 시험 — 사전등록 findings/pension-sector-bond-preregistration-2026-09.md (정정 §8 포함).

    python research/strategy-lab/pension_sector_bond_test.py --selftest   # 네트워크·데이터 없음
    python research/strategy-lab/pension_sector_bond_test.py              # 전체 실행 -> findings/pension-sector-bond-results-2026-09.json

입력: data/pension-test/*.parquet(pension_test_fetch.py) · data/factor-panel/kr-monthly-v1.parquet · data/etf-ohlc/*.jsonl
"""
from __future__ import annotations

import argparse
import json
import math
import sys
from pathlib import Path

import numpy as np
import pandas as pd

LAB = Path(__file__).resolve().parent
D = LAB / "data" / "pension-test"
COST = 0.0005            # 편도 5bp
SECT = ["XLB", "XLE", "XLF", "XLI", "XLK", "XLP", "XLU", "XLV", "XLY"]
PERIODS = {"TRAIN": ("1999-01", "2009-12"), "VALID": ("2010-01", "2017-12"), "TEST": ("2018-01", "2026-12")}
N_PERM, N_BOOT, N_FLOOR, BLOCK = 2000, 2000, 500, 12
sys.path.insert(0, str(LAB))
from sector_step0 import nw_tstat, build_sector_panel, load_rollup  # noqa: E402


# ---------------------------------------------------------------- 공통
def monthly_last(name):
    s = pd.read_parquet(D / f"{name}.parquet")["close"]
    return s.resample("ME").last().dropna()


def mret(name):
    return monthly_last(name).pct_change().dropna()


def par_bond_price(c, y, n):
    """쿠폰 c·수익률 y(연, 반기복리)·잔존 n년 채권 가격(액면 1). c==y 이면 정확히 1."""
    y = np.asarray(y, float)
    c = np.asarray(c, float)
    v = (1 + y / 2) ** (-2 * n)
    return c / y * (1 - v) + v


def par_bond_tr(y_pct: pd.Series, maturity: float) -> pd.Series:
    """상수만기 par 채권 월수익. 월초 수익률로 쿠폰을 정하고 한 달 뒤 만기 (maturity-1/12) 년·월말 수익률로 재평가 + 쿠폰/12."""
    y = y_pct / 100.0
    y0 = y.shift(1)
    p1 = par_bond_price(y0.values, y.values, maturity - 1 / 12)
    return pd.Series((p1 + y0.values / 12) - 1, index=y.index).dropna()


def comp(x):
    return float(np.prod(1 + np.asarray(x)) - 1)


def stats(r: pd.Series, rf: pd.Series):
    r = r.dropna()
    n = len(r)
    if n < 24:
        return None
    w = (1 + r).cumprod()
    dd = w / w.cummax() - 1
    under, cur = 0, 0
    for v in dd.values:
        cur = cur + 1 if v < -1e-12 else 0
        under = max(under, cur)
    ex = r - rf.reindex(r.index).fillna(0)
    roll12 = (1 + r).rolling(12).apply(np.prod, raw=True) - 1
    roll120 = ((1 + r).rolling(120).apply(np.prod, raw=True)) ** (1 / 10) - 1
    return dict(n=n, cagr=float(w.iloc[-1] ** (12 / n) - 1), vol=float(r.std() * math.sqrt(12)),
                sharpe=float(ex.mean() * 12 / (r.std() * math.sqrt(12))), mdd=float(dd.min()),
                worst12=float(roll12.min()), underwater_max=int(under),
                r10_min=None if roll120.dropna().empty else float(roll120.min()),
                r10_med=None if roll120.dropna().empty else float(roll120.median()))


# ---------------------------------------------------------------- A 지속성
def trailing(R: pd.DataFrame, J: int, skip: int = 0):
    lg = np.log1p(R)
    if skip:
        return np.expm1(lg.rolling(J - skip).sum().shift(skip))
    return np.expm1(lg.rolling(J).sum())


def leader_flags(sig: pd.DataFrame, k: int) -> np.ndarray:
    rk = sig.rank(axis=1, ascending=False, method="first")
    return ((rk <= k) & sig.notna()).values


def runs(flags: np.ndarray):
    out = []
    for j in range(flags.shape[1]):
        c = 0
        for v in flags[:, j]:
            if v:
                c += 1
            elif c:
                out.append(c)
                c = 0
        if c:
            out.append(c)
    return out


def persist_stats(flags: np.ndarray, ks=(1, 3, 6, 12)):
    T = flags.shape[0]
    res = {}
    for k in ks:
        a, b = flags[: T - k], flags[k:]
        res[f"P{k}"] = float((a & b).sum() / max(a.sum(), 1))
    rl = runs(flags)
    res["run_mean"] = float(np.mean(rl)) if rl else float("nan")
    res["run_median"] = float(np.median(rl)) if rl else float("nan")
    res["run_ge6"] = float(np.mean([x >= 6 for x in rl])) if rl else float("nan")
    return res


def persistence_block(R: pd.DataFrame, J: int, k: int, seed=0):
    sig = trailing(R, J)
    obs = persist_stats(leader_flags(sig, k))
    rng = np.random.default_rng(seed)
    T = len(R)
    nulls = []
    for _ in range(N_PERM):
        Rp = pd.DataFrame(R.values[rng.permutation(T)], columns=R.columns)
        nulls.append(persist_stats(leader_flags(trailing(Rp, J), k)))
    nl = pd.DataFrame(nulls)
    out = {}
    for key, v in obs.items():
        p95 = float(nl[key].quantile(0.95))
        out[key] = dict(obs=v, null_mean=float(nl[key].mean()), null_p95=p95, above=bool(v > p95),
                        p_perm=float((nl[key] >= v).mean()))
    return out


def age_table(R: pd.DataFrame, J: int, k: int, seed=1):
    """리더 진입 후 경과(개월)별 다음 1·3개월 초과수익(횡단면 평균 대비). 12개월 블록 부트스트랩."""
    sig = trailing(R, J)
    F = leader_flags(sig, k)
    T, N = F.shape
    age = np.zeros((T, N), int)
    for t in range(T):
        age[t] = np.where(F[t], (age[t - 1] + 1) if t else 1, 0)
    lg = np.log1p(R.values)
    ex1 = np.full((T, N), np.nan)
    ex3 = np.full((T, N), np.nan)
    for t in range(T - 1):
        x = R.values[t + 1]
        ex1[t] = x - np.nanmean(x)
    for t in range(T - 3):
        c = np.expm1(lg[t + 1:t + 4].sum(0))
        ex3[t] = c - np.nanmean(c)
    buckets = {"진입 1": (1, 1), "2-3": (2, 3), "4-6": (4, 6), "7+": (7, 999), "비리더": (0, 0)}
    names = list(buckets)

    def agg(ex):
        s = np.zeros((T, len(names)))
        c = np.zeros((T, len(names)))
        for b, (lo, hi) in enumerate(buckets.values()):
            m = (age >= lo) & (age <= hi) & np.isfinite(ex)
            s[:, b] = np.where(m, ex, 0).sum(1)
            c[:, b] = m.sum(1)
        return s, c

    out = {}
    rng = np.random.default_rng(seed)
    for lab, ex in (("fwd1", ex1), ("fwd3", ex3)):
        s, c = agg(ex)
        point = s.sum(0) / np.maximum(c.sum(0), 1)
        boots = []
        nb = math.ceil(T / BLOCK)
        for _ in range(N_BOOT):
            st = rng.integers(0, T, nb)
            idx = np.concatenate([(x + np.arange(BLOCK)) % T for x in st])[:T]
            boots.append(s[idx].sum(0) / np.maximum(c[idx].sum(0), 1))
        boots = np.array(boots)
        out[lab] = {n: dict(mean=float(point[i]), lo=float(np.quantile(boots[:, i], .025)),
                            hi=float(np.quantile(boots[:, i], .975)), n=int(c.sum(0)[i]))
                    for i, n in enumerate(names)}
    return out


# ---------------------------------------------------------------- B 로테이션
def rotation(R: pd.DataFrame, sig: pd.DataFrame, k=3):
    """월말 신호 -> 다음 달 등가중 상위 k. 반환: (총수익, 순수익, 월 편도합 교체)."""
    F = leader_flags(sig, k).astype(float)
    W = F / np.maximum(F.sum(1, keepdims=True), 1)
    T, N = R.shape
    gross = np.full(T, np.nan)
    net = np.full(T, np.nan)
    turn = np.full(T, np.nan)
    drift = np.zeros(N)
    for t in range(1, T):
        w = W[t - 1]
        if F[t - 1].sum() == 0:
            continue
        tr = np.abs(w - drift).sum()
        r = float((w * R.values[t]).sum())
        gross[t], net[t], turn[t] = r, r - COST * tr, tr
        drift = w * (1 + R.values[t]) / (1 + r)
    ix = R.index
    return pd.Series(gross, ix), pd.Series(net, ix), pd.Series(turn, ix)


def ew_series(R: pd.DataFrame):
    T, N = R.shape
    w = np.ones(N) / N
    gross = np.full(T, np.nan)
    net = np.full(T, np.nan)
    drift = np.zeros(N)
    for t in range(1, T):
        r = float((w * R.values[t]).sum())
        gross[t], net[t] = r, r - COST * np.abs(w - drift).sum()
        drift = w * (1 + R.values[t]) / (1 + r)
    return pd.Series(gross, R.index), pd.Series(net, R.index)


def rotation_block(R: pd.DataFrame):
    cells = {"B1_3M": trailing(R, 3), "B2_6M": trailing(R, 6), "B3_12M": trailing(R, 12), "B4_12-1": trailing(R, 12, skip=1)}
    ew_g, ew_n = ew_series(R)
    res, tg = {}, {}
    for name, sig in cells.items():
        g, n, tu = rotation(R, sig)
        exg, exn = (g - ew_g).dropna(), (n - ew_n).dropna()
        t_g = nw_tstat(exg.values)
        per = {}
        for p, (a, b) in PERIODS.items():
            e = exn[a:b]
            per[p] = dict(mean_bp=float(e.mean() * 1e4), n=len(e))
        tu_m = float(tu.dropna().mean())
        res[name] = dict(gross_excess_bp=float(exg.mean() * 1e4), net_excess_bp=float(exn.mean() * 1e4),
                         t_gross=float(t_g), t_net=float(nw_tstat(exn.values)), turnover=tu_m,
                         breakeven_bp_per_side=float(exg.mean() / tu_m * 1e4) if tu_m > 0 else None,
                         periods=per, net_cagr=float((1 + n.dropna()).prod() ** (12 / n.dropna().size) - 1))
        tg[name] = t_g
    # 난수 바닥선: 달마다 신호 열을 섞는다(4셀 같은 순열)
    rng = np.random.default_rng(7)
    sigs = np.stack([s.values for s in cells.values()])
    T, N = R.shape
    ew_gv = ew_g.values
    mx = []
    for _ in range(N_FLOOR):
        P = np.argsort(rng.random((T, N)), axis=1)
        ts = []
        for si in range(len(cells)):
            sp = pd.DataFrame(np.take_along_axis(sigs[si], P, axis=1), index=R.index, columns=R.columns)
            g, _, _ = rotation(R, sp)
            ex = (g.values - ew_gv)
            ex = ex[np.isfinite(ex)]
            ts.append(nw_tstat(ex))
        mx.append(max(ts))
    floor = float(np.quantile(mx, 0.95))
    for name, r in res.items():
        r["pass"] = bool(all(r["periods"][p]["mean_bp"] > 0 for p in PERIODS) and r["t_gross"] > floor
                         and (r["breakeven_bp_per_side"] or 0) > 3 * COST * 1e4)
    spy = mret("SPY")["1999-01":]
    return res, floor, stats(spy, pd.Series(0.0, index=spy.index)), stats(ew_n.dropna(), pd.Series(0.0, index=ew_n.dropna().index))


# ---------------------------------------------------------------- C 30년물 조건부
def yield_conditional():
    y = monthly_last("_TYX")
    b30 = par_bond_tr(y, 30.0)
    cash = (monthly_last("_IRX") / 100 / 12).reindex(b30.index).ffill()
    spy = mret("SPY").reindex(b30.index)
    res = {}
    tlt = mret("TLT")
    j = pd.concat([b30, tlt], axis=1, keys=["p", "t"]).dropna()
    beta = float(np.polyfit(j.p, j.t, 1)[0])
    res["tlt_check"] = dict(corr=float(j.corr().iloc[0, 1]), beta_tlt_on_proxy=beta, n=len(j),
                            cagr_proxy=float((1 + j.p).prod() ** (12 / len(j)) - 1),
                            cagr_tlt=float((1 + j.t).prod() ** (12 / len(j)) - 1))
    buckets = [("<3", 0, 3), ("3-4.5", 3, 4.5), ("4.5-5.5", 4.5, 5.5), (">=5.5", 5.5, 99)]
    ys = y.reindex(b30.index)
    out = {}
    for H in (1, 3, 5, 10):
        n = 12 * H
        fb = (np.log1p(b30).rolling(n).sum().shift(-n) * 12 / n)   # 연환산 로그
        fc = (np.log1p(cash).rolling(n).sum().shift(-n) * 12 / n)
        fs = (np.log1p(spy).rolling(n).sum().shift(-n) * 12 / n)
        # 시작 = 월말 t, 수익 = t+1..t+n 개월. shift(-n) 후 rolling 은 t-n+1..t 합 -> 재정렬
        fb = np.log1p(b30).rolling(n).sum().shift(-n) * 12 / n
        rows = {}
        for lab, lo, hi in buckets:
            m = (ys >= lo) & (ys < hi) & fb.notna()
            if m.sum() == 0:
                rows[lab] = dict(months=0)
                continue
            ann = np.expm1(fb[m])
            ex_cash = np.expm1(fb[m]) - np.expm1(fc[m])
            ms = m & fs.notna()
            rows[lab] = dict(months=int(m.sum()), first=str(b30.index[m][0].date()), last=str(b30.index[m][-1].date()),
                             median=float(ann.median()), p10=float(ann.quantile(.1)), p90=float(ann.quantile(.9)),
                             pct_neg=float((ann < 0).mean()), vs_cash_median=float(ex_cash.median()),
                             vs_spy_median=float((np.expm1(fb[ms]) - np.expm1(fs[ms])).median()) if ms.sum() else None,
                             n_ms=int(ms.sum()), n_indep=float(m.sum() / n))
        out[f"{H}y"] = rows
    res["fwd"] = out
    # 출발 금리 vs 실현 10년 (기계적 관계)
    n = 120
    fb10 = np.expm1(np.log1p(b30).rolling(n).sum().shift(-n) * 12 / n)
    d = pd.concat([ys / 100, fb10], axis=1, keys=["y", "r"]).dropna()
    res["y_vs_r10"] = dict(spearman=float(d.corr(method="spearman").iloc[0, 1]), n=len(d),
                           mean_abs_err=float((d.r - d.y).abs().mean()), median_gap=float((d.r - d.y).median()),
                           n_indep=len(d) / 120)
    # 현재 지점 (>=5.5): 이후 12개월 금리 +100bp 이상 상승 비율과 그 경우 수익
    fy = ys.shift(-12) - ys
    m = (ys >= 5.5) & fy.notna()
    r12 = np.expm1(np.log1p(b30).rolling(12).sum().shift(-12))
    rise = m & (fy >= 1.0)
    res["now"] = dict(y_now=float(y.iloc[-1]), months_ge55=int(m.sum()), pct_rise_100bp=float(rise.sum() / max(m.sum(), 1)),
                      r12_if_rise_median=float(r12[rise].median()) if rise.sum() else None,
                      r12_all_median=float(r12[m].median()), r12_all_p10=float(r12[m].quantile(.1)),
                      years_ge55=sorted(set(int(x.year) for x in ys[ys >= 5.5].index)))
    y0 = float(y.iloc[-1]) / 100
    sens = {}
    for bp in (-200, -100, -50, 50, 100, 200):
        sens[str(bp)] = float(par_bond_price(y0, y0 + bp / 1e4, 30.0) - 1)
    res["shock_price_change_30y"] = sens
    res["dur_mod_30y_now"] = float(-(par_bond_price(y0, y0 + 1e-4, 30) - par_bond_price(y0, y0 - 1e-4, 30)) / 2e-4)
    res["carry_breakeven_1y_bp"] = float(y0 / res["dur_mod_30y_now"] * 1e4)
    return res


# ---------------------------------------------------------------- D 포트폴리오
def sim_lump(R: pd.DataFrame, target: dict, rule: str, wfn=None):
    """월 수익 행렬 R(열=자산). target: 열이름->비중. rule: none|annual|semi|quarterly|band. wfn(i)->target dict(동적)."""
    cols = list(R.columns)
    T = len(R)
    w_t = np.array([target.get(c, 0.0) for c in cols]) if target else None
    drift = np.zeros(len(cols))
    out = np.full(T, np.nan)
    prev_month = R.index.month
    first = True
    for i in range(T):
        do = first
        if not do:
            pm = prev_month[i - 1]
            if rule == "annual":
                do = pm == 12
            elif rule == "semi":
                do = pm in (6, 12)
            elif rule == "quarterly":
                do = pm in (3, 6, 9, 12)
            elif rule == "band":
                do = (np.abs(drift - w_t) > 0.05).any() if wfn is None else False
        if do:
            tw = np.array([wfn(i).get(c, 0.0) for c in cols]) if wfn else w_t
            cost = COST * np.abs(tw - drift).sum()
            drift = tw
            w_t = tw
        else:
            cost = 0.0
        first = False
        r = float((drift * R.values[i]).sum())
        out[i] = r - cost
        drift = drift * (1 + R.values[i]) / (1 + r)
    return pd.Series(out, R.index)


def dca_window(Rv: np.ndarray, tw: np.ndarray, policy: str, start: int, months=120):
    h = np.zeros(len(tw))
    contrib = 0.0
    for m in range(months):
        i = start + m
        # 월초 납입 1
        W = h.sum()
        want = tw * (W + 1)
        buy = np.maximum(want - h, 0)
        buy = buy * (1 / buy.sum())
        h = h + buy
        contrib += 1
        if policy == "contrib_annual" and (m % 12 == 0) and m:
            tot = h.sum()
            cost = COST * np.abs(tw * tot - h).sum()
            h = tw * (tot - cost)
        h = h * (1 + Rv[i])
        h = h - COST * buy   # 매수 비용(근사)
    return h.sum() / contrib


def dca_stats(R: pd.DataFrame, tw_dict, policy):
    tw = np.array([tw_dict.get(c, 0.0) for c in R.columns])
    Rv = R.values
    res = [dca_window(Rv, tw, policy, s) for s in range(0, len(R) - 120 + 1)]
    a = np.array(res)
    return dict(median=float(np.median(a)), p10=float(np.quantile(a, .1)), min=float(a.min()), n=len(a))


def portfolios_block():
    tyx = monthly_last("_TYX")
    tnx = monthly_last("_TNX")
    b30 = par_bond_tr(tyx, 30.0)
    b10 = par_bond_tr(tnx, 10.0)
    cash = (monthly_last("_IRX") / 100 / 12)
    spy, gld = mret("SPY"), mret("GLD")
    real = {n: mret(n) for n in ("TLT", "IEF", "SHY")}
    res = {}
    # 프록시 세트 1993-02~
    P = pd.concat([spy, b30, b10, cash, gld], axis=1, keys=["SPY", "B30", "B10", "CASH", "GLD"])
    main = P.dropna(subset=["SPY", "B30", "B10", "CASH"])["1993-02":]
    rf = main["CASH"]
    y_prev = tyx.reindex(main.index).shift(1)

    def run_set(Rm, mapping, label, period_slices):
        out = {}
        defs = {"P1": {mapping["eq"]: 1.0},
                "P2": {mapping["eq"]: .7, mapping["b30"]: .3},
                "P3": {mapping["eq"]: .6, mapping["b30"]: .4},
                "P4": {mapping["eq"]: .6, mapping["b10"]: .4},
                "P5": {mapping["eq"]: .6, mapping["cash"]: .4}}
        if mapping.get("gld") and mapping["gld"] in Rm.columns:
            defs["P6"] = {mapping["eq"]: .6, mapping["b30"]: .3, mapping["gld"]: .1}
        for nm, tw in defs.items():
            cols = list(tw)
            sub = Rm[cols].dropna() if nm == "P6" else Rm[cols]
            r = sim_lump(sub[cols], tw, "annual")
            out[nm] = {sl: stats(r[a:b], rf) for sl, (a, b) in period_slices.items()}
            out[nm]["dca_contrib"] = dca_stats(sub[cols], tw, "contrib_only") if len(sub) > 150 else None
        # P7: 연 1회 ^TYX>=5.0 이면 30년채 아니면 현금 (프록시 세트만)
        if label == "proxy":
            cols = [mapping["eq"], mapping["b30"], mapping["cash"]]
            def wfn(i):
                yy = y_prev.iloc[i]
                return {mapping["eq"]: .6, (mapping["b30"] if (pd.notna(yy) and yy >= 5.0) else mapping["cash"]): .4}
            r = sim_lump(Rm[cols], None, "annual", wfn=wfn)
            out["P7"] = {sl: stats(r[a:b], rf) for sl, (a, b) in period_slices.items()}
        return out

    sl_main = {"전체 1993-": ("1993-02", "2026-12"), "1993-2007": ("1993-02", "2007-12"),
               "2008-2021": ("2008-01", "2021-12"), "2022-": ("2022-01", "2026-12")}
    res["proxy"] = run_set(main.assign(SPY=main.SPY), dict(eq="SPY", b30="B30", b10="B10", cash="CASH", gld="GLD"), "proxy", sl_main)
    # P6 비교용 동일 기간(2004-12~)
    sub = P.dropna()["2004-12":]
    sl6 = {"2004-12~": ("2004-12", "2026-12")}
    res["proxy_2004"] = run_set(sub, dict(eq="SPY", b30="B30", b10="B10", cash="CASH", gld="GLD"), "proxy2004", sl6)
    # 실물 ETF 세트 2002-08~
    Rr = pd.concat([spy, real["TLT"], real["IEF"], real["SHY"]], axis=1, keys=["SPY", "TLT", "IEF", "SHY"]).dropna()
    sl_r = {"전체 2002-": ("2002-08", "2026-12"), "2022-": ("2022-01", "2026-12")}
    res["real"] = run_set(Rr, dict(eq="SPY", b30="TLT", b10="IEF", cash="SHY"), "real", sl_r)
    # 리밸런스 정책 (P3, 프록시)
    tw = {"SPY": .6, "B30": .4}
    pol = {}
    for rule in ("none", "annual", "semi", "quarterly", "band"):
        r = sim_lump(main[["SPY", "B30"]], tw, rule)
        pol[rule] = {sl: stats(r[a:b], rf) for sl, (a, b) in sl_main.items()}
    pol["dca_contrib_only"] = dca_stats(main[["SPY", "B30"]], tw, "contrib_only")
    pol["dca_contrib_annual"] = dca_stats(main[["SPY", "B30"]], tw, "contrib_annual")
    pol["dca_P1"] = dca_stats(main[["SPY"]].assign(B30=0.0)[["SPY", "B30"]], {"SPY": 1.0}, "contrib_only")
    res["policy_P3"] = pol
    # KRW 비헷지 민감도 (SPY·B30·GLD x KRW)
    fx = monthly_last("KRW_X").pct_change().dropna()
    K = main[["SPY", "B30"]].join(fx.rename("fx"), how="inner")["2004-01":]
    Rk = pd.DataFrame({"SPY": (1 + K.SPY) * (1 + K.fx) - 1, "B30": (1 + K.B30) * (1 + K.fx) - 1})
    Ru = K[["SPY", "B30"]]
    rf2 = rf.reindex(K.index)
    res["krw"] = {}
    for nm, tw_ in (("P1", {"SPY": 1.0}), ("P3", {"SPY": .6, "B30": .4})):
        res["krw"][nm] = dict(usd=stats(sim_lump(Ru[list(tw_)], tw_, "annual"), rf2),
                              krw_unhedged=stats(sim_lump(Rk[list(tw_)], tw_, "annual"), rf2))
    return res


# ---------------------------------------------------------------- E 국내 ETF 대조
def domestic_check():
    codes = {"304660": "KODEX 미국채울트라30년선물(H)", "148070": "KOSEF 국고채10년", "453850": "ACE 미국30년국채액티브(H)"}
    rows = {c: {} for c in codes}
    for f in sorted((LAB / "data" / "etf-ohlc").glob("*.jsonl")):
        if int(f.stem) < 2018:
            continue
        with open(f, encoding="utf-8") as fh:
            for line in fh:
                for c in codes:
                    if f'"ISU_CD": "{c}"' in line:
                        d = json.loads(line)
                        rows[c][d["BAS_DD"]] = (float(d["NAV"]), float(d["TDD_CLSPRC"]))
    tyx = monthly_last("_TYX")
    b30 = par_bond_tr(tyx, 30.0)
    tlt = mret("TLT")
    fx = monthly_last("KRW_X").pct_change()
    out = {}
    for c, nm in codes.items():
        if not rows[c]:
            continue
        s = pd.Series({pd.Timestamp(k): v[0] for k, v in rows[c].items()}).sort_index()
        m = s.resample("ME").last().pct_change().dropna()
        j = pd.concat([m, b30, tlt, fx], axis=1, keys=["etf", "proxy", "tlt", "fx"]).dropna()
        proxy_krw = (1 + j.proxy) * (1 + j.fx) - 1
        n = len(j)
        ann = lambda x: float((1 + x).prod() ** (12 / n) - 1)
        out[c] = dict(name=nm, n=n, first=str(j.index[0].date()), corr_proxy_usd=float(j.etf.corr(j.proxy)),
                      corr_proxy_krw=float(j.etf.corr(proxy_krw)), cagr_etf_nav=ann(j.etf), cagr_proxy_usd=ann(j.proxy),
                      cagr_proxy_krw_unhedged=ann(proxy_krw), cagr_tlt_usd=ann(j.tlt))
    return out


# ---------------------------------------------------------------- 실행
def kr_returns():
    panel = pd.read_parquet(LAB / "data" / "factor-panel" / "kr-monthly-v1.parquet")
    agg = build_sector_panel(panel, load_rollup())
    M = agg.pivot(index="date", columns="group", values="fwd1m").sort_index()
    M = M.dropna(axis=1, thresh=int(len(M) * 0.9)).dropna(how="any")
    return M


def main_run():
    res = {"meta": dict(prereg="pension-sector-bond-preregistration-2026-09.md", cost_per_side=COST)}
    Rus = pd.concat({s: mret(s) for s in SECT}, axis=1).dropna()["1999-01":]
    res["A_us"] = {f"J{J}": persistence_block(Rus, J, 3) for J in (3, 6, 12)}
    res["A_us_n"] = dict(months=len(Rus), first=str(Rus.index[0].date()), last=str(Rus.index[-1].date()))
    res["A_us_age"] = {f"J{J}": age_table(Rus, J, 3) for J in (3, 6)}
    Rkr = kr_returns()
    res["A_kr"] = {f"J{J}": persistence_block(Rkr, J, 5) for J in (3, 6)}
    res["A_kr_n"] = dict(months=len(Rkr), groups=Rkr.shape[1], first=str(Rkr.index[0].date()), last=str(Rkr.index[-1].date()))
    res["A_kr_age"] = {f"J{J}": age_table(Rkr, J, 5) for J in (3, 6)}
    rot, floor, spy_st, ew_st = rotation_block(Rus)
    res["B"] = dict(cells=rot, floor_t=floor, spy=spy_st, ew9=ew_st)
    res["C"] = yield_conditional()
    res["D"] = portfolios_block()
    res["E"] = domestic_check()
    out = LAB / "findings" / "pension-sector-bond-results-2026-09.json"
    out.write_text(json.dumps(res, ensure_ascii=False, indent=1), encoding="utf-8")
    print("wrote", out)


def selftest():
    # 채권: 수익률 불변이면 월수익 = y/12, 상승하면 손실
    y = pd.Series([5.0] * 5, index=pd.date_range("2020-01-31", periods=5, freq="ME"))
    r = par_bond_tr(y, 30.0)
    assert np.allclose(r.values, 0.05 / 12, atol=1e-12), r.values
    y2 = pd.Series([5.0, 6.0], index=y.index[:2])
    assert par_bond_tr(y2, 30.0).iloc[0] < -0.10          # 듀레이션 ~14 x 100bp
    # 런 길이
    f = np.array([[1, 0], [1, 1], [0, 1], [1, 1]], bool)
    assert sorted(runs(f)) == [1, 2, 3]
    # 지속성: 완전 지속이면 P1=1
    assert persist_stats(np.array([[1, 0]] * 20, bool), ks=(1,))["P1"] == 1.0
    # 리밸런스: 수익 0 이고 안 움직이면 비용 = 초기 매수 뿐
    R = pd.DataFrame(0.0, index=pd.date_range("2020-01-31", periods=24, freq="ME"), columns=["a", "b"])
    s = sim_lump(R, {"a": .5, "b": .5}, "annual")
    assert abs(s.iloc[0] + COST * 1.0) < 1e-12 and (s.iloc[1:].abs() < 1e-12).all()
    # DCA: 수익 0 이면 배수 ~1 - 비용
    assert abs(dca_window(np.zeros((200, 2)), np.array([.5, .5]), "contrib_only", 0) - 1) < 1e-3
    # 순열 귀무: 시간 의존 없는 수익이면 관측 ≈ 귀무 평균
    rng = np.random.default_rng(0)
    Rr = pd.DataFrame(rng.normal(0, .04, (200, 9)), columns=list("abcdefghi"))
    globals()["N_PERM"] = 50
    pb = persistence_block(Rr, 6, 3)
    assert abs(pb["P1"]["obs"] - pb["P1"]["null_mean"]) < 0.06
    print("selftest ok")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--selftest", action="store_true")
    a = ap.parse_args()
    selftest() if a.selftest else main_run()
