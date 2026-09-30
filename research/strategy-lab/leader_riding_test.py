#!/usr/bin/env python3
"""주도 섹터 편승(분기·반기) 코어-위성 포트폴리오, 그리고 거래대금 증가 종목 편승·감소 시 이탈 — 실행 전 고정 설계(2026-09-30). 자문 아님.

    python research/strategy-lab/leader_riding_test.py --selftest
    python research/strategy-lab/leader_riding_test.py     # -> findings/leader-riding-results-2026-09.json

[T1 섹터 편승 코어-위성] 사용자 계획: 50% 는 S&P500(또는 나스닥), 50% 는 분기·반기마다 주도 섹터에 편승.
- 미국 SPDR 9섹터(1999-01~2026-09, 월 총수익) + SPY. 한국 20그룹(2016-02~2026-07)은 위성 초과수익만(코어 자료 없음, 그룹 = 종목 평균이라 ETF 아님).
- 셀 4개 고정: (리밸런스 주기 P, 신호 되돌아보기 L) = (3,3) (3,6) (6,6) (6,12)개월, 상위 k(미국 3 · 한국 5)를 등가중 매수 후 P개월 보유(중간 매매 없음). 월초 리밸런스, 신호는 직전 월말까지의 L개월 수익.
- 미국 포트폴리오: SPY 50% + 위성 50%(상위 k). 비교 기준 2개: (i) SPY 100% (ii) SPY 50% + 9섹터 등가중 50%(같은 P 로 리밸런스). 매매 비용 편도 10bp(자산별 거래액 x 10bp).
- 지표: CAGR · 샤프(무위험 0) · MDD, 위성 기간별 초과(상위 k 바스켓 - 전체 섹터 등가중, 같은 P 보유수익) 평균 bp/기간 · 승률, ΔSharpe(vs i, vs ii) 12개월 블록 부트스트랩 95% 구간.
  난수 플라시보: 같은 P 로 매 리밸런스 무작위 k 섹터 500회 — 실제 셀의 위성 초과수익·ΔSharpe(vs i)가 플라시보 p95 를 넘고 부트스트랩 하한 > 0 이면 '편승 우위 있음'.
- 셀 4개·k 고정. 결과를 보고 P·L·k 를 바꿔 재시험하지 않는다(최적화 = 사후 선택이라 하지 않음).

[T2 거래대금 증가 종목 편승·감소 시 이탈] 한국 개별종목 월 패널(kr-monthly-v1, 2016-02~2026-07, 생존 종목 근사).
- 적격: 20일 평균 거래대금 dv20 >= 20억원. 신호 VOL3 = dv20 / (3개월 전 dv20) - 1. 진입 = 그 달 적격 종목 중 VOL3 상위 10%에 새로 든 것(전월은 상위 10% 밖).
- 퇴출 규칙 5개: 보유 1·3·6개월 · dv20 가 전월보다 줄어드는 첫 달('거래량 감소') · dv20 가 진입 후 최고치 대비 30% 아래로 내려가는 첫 달. 최대 6개월.
- 수익: 종목 fwd1m 복리 - 그 달 적격 종목 평균 복리. 지표는 사건별 월평균 초과(총 · 왕복 33.5bp 를 보유월수로 나눠 차감한 순), 평균/중앙/승률. 12개월 블록 부트스트랩 2,000회, 난수 진입 플라시보 200회(같은 수의 무작위 적격 종목-월).
  기록 전용 변형: 진입에 '3개월 수익 상위 1/3' 조건을 더한 것(가격+거래량).
- 판정: 진입 우위 = 보유 3개월 평균이 플라시보 p95 초과 & 구간 하한 > 0. **반대 방향(약세)** = 평균이 플라시보 p5 미만 & 구간 상한 < 0 → '신호 있음(반대)'. 거래량 기반 퇴출이 낫다 = 그 규칙 - 보유3 짝지은 차이 하한 > 0.
- 한계: 패널은 월 단위(월중 거래량 변화는 못 봄), 폐지 종목 제외(생존 편향), 상·하한가·거래정지 체결 불가는 반영 못 함, 분기·반기 보유는 6개월 이내만.
"""
from __future__ import annotations

import json
import math
import sys
from pathlib import Path

import numpy as np
import pandas as pd

LAB = Path(__file__).resolve().parent
sys.path.insert(0, str(LAB))
from pension_sector_bond_test import mret, kr_returns  # noqa: E402

RES = LAB / "findings" / "leader-riding-results-2026-09.json"
SECT = ["XLB", "XLE", "XLF", "XLI", "XLK", "XLP", "XLU", "XLV", "XLY"]
CELLS = [(3, 3), (3, 6), (6, 6), (6, 12)]
COST = 0.001


# ---------------------------------------------------------------- T1
def simulate(R: np.ndarray, target_fn, P: int, t0: int):
    """R: 월수익(T x N 자산). t0 부터 P 개월마다 target_fn(t)->비중 벡터로 리밸런스. 반환: 월수익 배열(t0~)."""
    T, N = R.shape
    w = np.zeros(N)
    out = []
    for t in range(t0, T):
        if (t - t0) % P == 0:
            tw = target_fn(t)
            c = COST * np.abs(tw - w).sum()
            w = tw.copy()
        else:
            c = 0.0
        r = float((w * R[t]).sum())
        out.append(r - c)
        w = w * (1 + R[t]) / (1 + r)
    return np.array(out)


def trailing(R, t, L):
    return np.prod(1 + R[t - L:t], axis=0) - 1


def sharpe(x):
    return float(x.mean() * 12 / (x.std() * math.sqrt(12)))


def summ(x):
    w = np.cumprod(1 + x)
    return dict(cagr=float(w[-1] ** (12 / len(x)) - 1), vol=float(x.std() * math.sqrt(12)), sharpe=sharpe(x), mdd=float((w / np.maximum.accumulate(w) - 1).min()))


def boot_d(a, b, n=2000, block=12, seed=7):
    T = len(a)
    rng = np.random.default_rng(seed)
    nb = math.ceil(T / block)
    ds = []
    for _ in range(n):
        st = rng.integers(0, T, nb)
        ix = np.concatenate([(s + np.arange(block)) % T for s in st])[:T]
        ds.append(sharpe(a[ix]) - sharpe(b[ix]))
    return [float(np.quantile(ds, .025)), float(np.quantile(ds, .975))]


def period_excess(Rs: np.ndarray, P: int, L: int, k: int, rng=None):
    """Rs: 섹터 월수익(T x N). 반환: 리밸런스별 (상위 k 바스켓 - 전체 등가중) P개월 보유수익 배열."""
    T, N = Rs.shape
    ex = []
    for t in range(12, T - P + 1, P):
        sig = trailing(Rs, t, L)
        pick = rng.choice(N, k, replace=False) if rng is not None else np.argsort(-sig)[:k]
        cum = np.prod(1 + Rs[t:t + P], axis=0) - 1
        ex.append(cum[pick].mean() - cum.mean())
    return np.array(ex)


def t1():
    Rus = pd.concat({s: mret(s) for s in SECT}, axis=1).dropna()["1999-01":]
    spy = mret("SPY").reindex(Rus.index)
    RA = np.column_stack([spy.values, Rus.values])          # 자산 0=SPY, 1..9 = 섹터
    Rs = Rus.values
    T = len(RA)
    t0 = 12
    res = {"us": {"months": T - t0, "first": str(Rus.index[t0].date()), "last": str(Rus.index[-1].date())}, "cells": {}}
    core = np.zeros(10)
    core[0] = 1.0
    ew_sat = np.r_[0.5, np.full(9, 0.5 / 9)]
    rng = np.random.default_rng(3)
    for P, L in CELLS:
        def ride(t, L=L):
            sig = trailing(Rs, t, L)
            tw = np.zeros(10)
            tw[0] = 0.5
            tw[1 + np.argsort(-sig)[:3]] = 0.5 / 3
            return tw
        r_ride = simulate(RA, ride, P, t0)
        r_core = simulate(RA, lambda t: core, P, t0)
        r_ew = simulate(RA, lambda t: ew_sat, P, t0)
        ex = period_excess(Rs, P, L, 3)
        nb = len(ex)
        boots = []
        for _ in range(2000):
            st = rng.integers(0, nb, nb)
            boots.append(ex[st].mean())
        plc_ex, plc_ds = [], []
        for _ in range(500):
            rr = np.random.default_rng(rng.integers(1 << 31))
            def rnd(t):
                tw = np.zeros(10)
                tw[0] = 0.5
                tw[1 + rr.choice(9, 3, replace=False)] = 0.5 / 3
                return tw
            plc_ex.append(period_excess(Rs, P, L, 3, np.random.default_rng(rng.integers(1 << 31))).mean())
            plc_ds.append(sharpe(simulate(RA, rnd, P, t0)) - sharpe(r_core))
        res["cells"][f"P{P}_L{L}"] = dict(
            ride=summ(r_ride), core=summ(r_core), ew_sat=summ(r_ew),
            d_sharpe_vs_core=sharpe(r_ride) - sharpe(r_core), d_ci_core=boot_d(r_ride, r_core),
            d_sharpe_vs_ew=sharpe(r_ride) - sharpe(r_ew), d_ci_ew=boot_d(r_ride, r_ew),
            placebo_d_sharpe_p95=float(np.quantile(plc_ds, .95)), placebo_d_sharpe_mean=float(np.mean(plc_ds)),
            sat_excess_bp_per_period=float(ex.mean() * 1e4), sat_ci=[float(np.quantile(boots, .025) * 1e4), float(np.quantile(boots, .975) * 1e4)],
            sat_hit=float((ex > 0).mean()), sat_n=int(nb), placebo_ex_p95_bp=float(np.quantile(plc_ex, .95) * 1e4))
        c = res["cells"][f"P{P}_L{L}"]
        c["edge"] = bool(c["sat_excess_bp_per_period"] > c["placebo_ex_p95_bp"] and c["sat_ci"][0] > 0 and c["d_sharpe_vs_core"] > c["placebo_d_sharpe_p95"] and c["d_ci_core"][0] > 0)
    # 한국: 위성 초과수익만
    Rkr = kr_returns().values
    kr = {}
    for P, L in CELLS:
        ex = period_excess(Rkr, P, L, 5)
        nb = len(ex)
        rng2 = np.random.default_rng(5)
        boots = [ex[rng2.integers(0, nb, nb)].mean() for _ in range(2000)]
        plc = [period_excess(Rkr, P, L, 5, np.random.default_rng(rng2.integers(1 << 31))).mean() for _ in range(500)]
        kr[f"P{P}_L{L}"] = dict(sat_excess_bp_per_period=float(ex.mean() * 1e4), ci=[float(np.quantile(boots, .025) * 1e4), float(np.quantile(boots, .975) * 1e4)],
                               hit=float((ex > 0).mean()), n=int(nb), placebo_p95_bp=float(np.quantile(plc, .95) * 1e4))
    res["kr"] = kr
    return res


# ---------------------------------------------------------------- T2
RULES2 = ["보유1", "보유3", "보유6", "거래량감소", "고점-30%"]
H2 = 6
RT_COST = 0.00335


def t2():
    p = pd.read_parquet(LAB / "data" / "factor-panel" / "kr-monthly-v1.parquet", columns=["ticker", "date", "dv20", "fwd1m", "mom3m"])
    p["date"] = pd.to_datetime(p["date"])
    piv = lambda c: p.pivot(index="date", columns="ticker", values=c).sort_index()
    DV, RET, MOM = piv("dv20"), piv("fwd1m"), piv("mom3m")
    dates = DV.index
    T, N = DV.shape
    elig = (DV >= 2e9).values
    dv = DV.values
    raw = np.clip(RET.values, -0.6, 1.5)
    bench = np.nanmean(np.where(elig, raw, np.nan), axis=1)      # 벤치마크 = 그 달 적격 종목 평균
    ret = np.nan_to_num(raw, nan=0.0)                            # 자료가 끊긴 종목은 이후 월 수익 0(현금)으로 둔다. 적격 탈락으로 표본을 지우지 않는다.
    vol3 = dv / np.vstack([np.full((3, N), np.nan), dv[:-3]]) - 1
    vol3 = np.where(elig, vol3, np.nan)
    pr = pd.DataFrame(vol3).rank(axis=1, pct=True).values
    top = pr >= 0.9
    new = top & ~np.vstack([np.zeros((1, N), bool), top[:-1]])
    mrk = pd.DataFrame(np.where(elig, MOM.values, np.nan)).rank(axis=1, pct=True).values
    # 누적(종목, 벤치) h 개월 (t..t+h-1 월 수익 복리)
    def cum(h):
        cs = np.ones((T, N))
        cb = np.ones(T)
        for k in range(h):
            r_k = np.full((T, N), np.nan)
            r_k[:T - k] = ret[k:]
            cs = cs * (1 + r_k)
            b_k = np.full(T, np.nan)
            b_k[:T - k] = bench[k:]
            cb = cb * (1 + b_k)
        return cs - 1, cb - 1
    E = {}
    for h in range(1, H2 + 1):
        cs, cb = cum(h)
        E[h] = (cs - cb[:, None])
    # 퇴출 보유월수 행렬
    def dv_at(k):
        x = np.full((T, N), np.nan)
        x[:T - k] = dv[k:]
        return x
    H_vd = np.full((T, N), H2)
    H_pk = np.full((T, N), H2)
    done_vd = np.zeros((T, N), bool)
    done_pk = np.zeros((T, N), bool)
    peak = dv.copy()
    for h in range(1, H2 + 1):
        cur, prev = dv_at(h), dv_at(h - 1)
        peak = np.fmax(peak, cur)
        c1 = ~(cur >= prev) & ~done_vd
        H_vd = np.where(c1, h, H_vd)
        done_vd |= c1
        c2 = ~(cur >= 0.7 * peak) & ~done_pk
        H_pk = np.where(c2, h, H_pk)
        done_pk |= c2

    def excess_for(mask):
        idx = np.argwhere(mask)
        t_i, j_i = idx[:, 0], idx[:, 1]
        out = {}
        for r in RULES2:
            if r.startswith("보유"):
                h = np.full(len(idx), int(r[2:]))
            elif r == "거래량감소":
                h = H_vd[t_i, j_i]
            else:
                h = H_pk[t_i, j_i]
            e = np.array([E[hh][t, j] for t, j, hh in zip(t_i, j_i, h)])
            out[r] = (e / h, e / h - RT_COST / h, h)
        return t_i, out

    valid = np.zeros((T, N), bool)
    valid[1:T - H2] = elig[1:T - H2] & ~np.isnan(RET.values[1:T - H2])
    ent_mask = new & valid
    variants = {"거래대금증가": ent_mask, "거래대금증가+3개월수익 상위1/3(기록)": ent_mask & (mrk >= 2 / 3)}
    rng = np.random.default_rng(13)
    res = {"n_months": int(T), "first": str(dates[0].date()), "last": str(dates[-1].date())}
    flat_valid = np.argwhere(valid)
    for vname, mask in variants.items():
        t_i, out = excess_for(mask)
        nE = len(t_i)
        # 부트스트랩(달 블록)
        boots = {r: [] for r in RULES2}
        diffs = {r: [] for r in RULES2}
        nb = math.ceil(T / 12)
        base3 = out["보유3"][0]
        for _ in range(2000):
            st = rng.integers(0, T, nb)
            cnt = np.bincount(np.concatenate([(s0 + np.arange(12)) % T for s0 in st])[:T], minlength=T)
            w = cnt[t_i].astype(float)
            for r in RULES2:
                e = out[r][0]
                ok = ~np.isnan(e) & ~np.isnan(base3)
                ww = w * ok
                if ww.sum() == 0:
                    continue
                boots[r].append(np.nansum(e * ww) / ww.sum())
                diffs[r].append(np.nansum((e - base3) * ww) / ww.sum())
        # 플라시보
        plc = {r: [] for r in RULES2}
        for _ in range(200):
            pick = flat_valid[rng.choice(len(flat_valid), size=min(nE, len(flat_valid)), replace=False)]
            m2 = np.zeros((T, N), bool)
            m2[pick[:, 0], pick[:, 1]] = True
            _, o2 = excess_for(m2)
            for r in RULES2:
                plc[r].append(np.nanmean(o2[r][0]))
        rr = {}
        for r in RULES2:
            g, n_, h = out[r]
            v = g[~np.isnan(g)]
            rr[r] = dict(n=int(len(v)), gross_bp=float(v.mean() * 1e4), net_bp=float(np.nanmean(n_) * 1e4), median_bp=float(np.median(v) * 1e4), hit=float((v > 0).mean()),
                         avg_hold=float(h.mean()), ci=[float(np.quantile(boots[r], .025) * 1e4), float(np.quantile(boots[r], .975) * 1e4)],
                         placebo_p5_bp=float(np.quantile(plc[r], .05) * 1e4), placebo_p95_bp=float(np.quantile(plc[r], .95) * 1e4),
                         diff_vs_hold3_bp=(None if r == "보유3" else float(np.mean(diffs[r]) * 1e4)),
                         diff_ci=(None if r == "보유3" else [float(np.quantile(diffs[r], .025) * 1e4), float(np.quantile(diffs[r], .975) * 1e4)]))
        h3 = rr["보유3"]
        res[vname] = dict(n_entries=int(nE), rules=rr,
                          edge=bool(h3["gross_bp"] > h3["placebo_p95_bp"] and h3["ci"][0] > 0),
                          reverse=bool(h3["gross_bp"] < h3["placebo_p5_bp"] and h3["ci"][1] < 0),
                          better_vol_exit=[r for r in ("거래량감소", "고점-30%") if rr[r]["diff_ci"][0] > 0])
    return res


def main():
    out = {"T1": t1()}
    out["T2"] = t2()
    RES.write_text(json.dumps(out, ensure_ascii=False, indent=1, default=float), encoding="utf-8")
    print("done")


def selftest():
    R = np.zeros((40, 3))
    o = simulate(R, lambda t: np.array([1.0, 0, 0]), 3, 0)
    assert abs(o[0] + COST) < 1e-12 and np.allclose(o[1:], 0)
    R2 = np.tile([.02, 0.0, -0.01], (40, 1))
    ex = period_excess(R2, 3, 3, 1)
    assert (ex > 0).all()
    assert abs(sharpe(np.array([.01, .02, .0, .03]))) > 0
    print("selftest ok")


if __name__ == "__main__":
    selftest() if "--selftest" in sys.argv else main()
