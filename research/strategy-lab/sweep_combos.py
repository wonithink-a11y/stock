#!/usr/bin/env python
"""팩터 조합 스윕 (Phase 2) — 돌리는 것보다 '돌린 뒤 운을 걸러내는 것'이 본체다.

왜 3중 게이트가 필요한가
------------------------
조합을 많이 돌릴수록 최고 성적은 반드시 올라간다 - 알파가 있든 없든.
순수 난수 팩터 20개로 4,845개 조합을 돌려 최고를 고르면 t=3.21 / Sharpe 0.98 이
나온다(2026-09-02 실측). 이 프로젝트의 TRAIN 통과 기준이 t>=2.0 이므로,
**알파가 정확히 0인 데이터가 기준을 여유롭게 통과한다.**

그래서 이 스크립트는 세 겹으로 막는다:

  ① TRAIN 에서만 고른다        VALID/TEST 는 스윕이 아예 안 본다
  ② 난수 귀무분포를 같이 돌린다  fwd1m 을 월 내부에서 섞어 같은 스윕을 반복 →
                               "운으로 나올 수 있는 최고 t" 를 실측한다.
                               후보는 이 선을 넘어야 자격이 생긴다
  ③ 조합 개수를 기록한다        4,845개 중 1등과 3개 중 1등은 다른 증거다.
                               nCombosTested 를 결과에 박아 둔다

추가로 이 패널 고유의 함정 하나를 더 막는다:
  ④ 교집합 붕괴              pbr 커버리지 47%, per 36%. 조합하면 어떤 달은
                               11종목까지 떨어진다. 월별 최소 종목수를 못 채운
                               달은 버리고, 남은 달 수(nMonths)와 월평균
                               종목수(avgNames)를 모든 조합에 대해 보고한다

랭킹 규약
---------
팩터별 월별 pct-rank 를 **그 팩터 자신의 non-NaN 집합 안에서** 미리 계산해 두고,
조합은 그 랭크들의 합으로 만든다. 어느 종목의 PBR 랭크가 '그 달에 ROE 가 있느냐'에
따라 흔들리지 않게 하려는 것이다(build_composite_selection.py 는 dropna 를 먼저
하고 랭크를 매겨서 이 성질이 없다 - 차이는 --compare-convention 으로 실측 가능).
조합의 적격 종목은 선택된 팩터가 **전부** 있는 종목이다(합에서 NaN 전파).

사용법
------
  python sweep_combos.py --selftest
  python sweep_combos.py --max-k 2 --nulls 5          # 빠른 확인
  python sweep_combos.py --max-k 3 --nulls 20         # 표준
  python sweep_combos.py --compare-convention pbr,roe # 랭킹 규약 차이 실측
"""
import argparse
import itertools
import json
import math
import os
import sys
import time

import numpy as np
import pandas as pd

LAB = os.path.dirname(os.path.abspath(__file__))
PANEL_PATH = os.path.join(LAB, "data", "factor-panel", "kr-monthly-v1.parquet")
MANIFEST_PATH = os.path.join(LAB, "data", "factor-panel", "_manifest_kr_monthly.json")
CRITERIA_PATH = os.path.join(LAB, "rule_discovery_criteria.json")

MIN_NAMES = 30          # 월별 최소 적격 종목수 (랩 표준, factor_discovery_kr.py 와 동일)
MIN_MONTHS = 24         # 이보다 적게 살아남은 조합은 통계를 안 낸다
ROUNDTRIP_BPS = 30.0    # 랩 표준 왕복비용 (편도 15bp)
TOP_QUANTILE = 0.9      # 상위 decile


# ---------------------------------------------------------------------------
# 패널 -> 패딩 행렬 (월 x 종목슬롯). 조합 평가를 통째로 벡터화하기 위한 형태다.
# ---------------------------------------------------------------------------
def build_matrices(panel, catalog, factors, period=None):
    sub = panel if period in (None, "ALL") else panel[panel["period"] == period]
    sub = sub.sort_values(["date", "ticker"])
    months = sorted(sub["date"].unique())
    counts = sub.groupby("date").size()
    width = int(counts.max())
    M = len(months)

    R = np.full((len(factors), M, width), np.nan, dtype=np.float32)
    FWD = np.full((M, width), np.nan, dtype=np.float32)
    TICK = np.full((M, width), -1, dtype=np.int32)
    codes = {t: i for i, t in enumerate(sorted(sub["ticker"].unique()))}

    for mi, (_, g) in enumerate(sub.groupby("date", sort=True)):
        n = len(g)
        FWD[mi, :n] = g["fwd1m"].to_numpy(dtype=np.float32)
        TICK[mi, :n] = g["ticker"].map(codes).to_numpy(dtype=np.int32)
        for fi, f in enumerate(factors):
            sign = -1.0 if catalog[f]["direction"] == "low" else 1.0
            # 그 팩터 자신의 non-NaN 집합 안에서 pct-rank. NaN 은 NaN 으로 남는다.
            R[fi, mi, :n] = (g[f].rank(pct=True).to_numpy(dtype=np.float32) * sign)
    # TICK 의 정수코드 -> 원래 ticker. simulate_exits.py 가 같은 종목선택을 재현하는 데 쓴다.
    names = [None] * len(codes)
    for t, i in codes.items():
        names[i] = t
    return R, FWD, TICK, months, M, width, names


# ---------------------------------------------------------------------------
# 조합 하나 평가
# ---------------------------------------------------------------------------
def _threshold(c, topq, top_n):
    """월별 컷 기준값 (M,1). top_n 이 주어지면 상위 N번째 값, 아니면 분위수."""
    if not top_n:
        return np.nanquantile(c, topq, axis=1)[:, None]
    # NaN 을 -inf 로 채운 뒤 행별 N번째 큰 값. 유효 개수가 N 미만인 행은
    # min_names 게이트가 이미 걸러내지만, 안전하게 N 을 유효개수로 자른다.
    filled = np.where(np.isnan(c), -np.inf, c)
    n_valid = (~np.isnan(c)).sum(axis=1)
    k = np.minimum(top_n, n_valid) - 1
    part = -np.partition(-filled, kth=np.unique(np.clip(k, 0, c.shape[1] - 1)), axis=1)
    return part[np.arange(c.shape[0]), np.clip(k, 0, c.shape[1] - 1)][:, None]


def eval_combo(idx, R, FWD, topq=TOP_QUANTILE, min_names=MIN_NAMES, top_n=0):
    """선택 팩터 랭크합의 상위 decile 을 매달 동일가중으로 사는 전략.

    핵심 통계량은 **같은 적격집합 동일가중(EW) 대비 초과수익**이다. 절대수익으로
    재면 모든 조합이 시장 베타·사이즈 노출을 공유해, 정답을 섞어도 t 가 거의
    같은 값으로 수렴해 난수 기준선이 무의미해진다(2026-09-02 실측: 666개 조합의
    난수 max-t 가 3회 전부 0.73으로 동일). 초과수익으로 재면 섞었을 때 정확히
    0 근처로 무너지므로 기준선이 제 역할을 한다.

    초과수익은 비용이 상쇄돼 사라진다(전략도 EW 도 리밸런싱한다). 회전율 차이의
    실제 비용은 Phase 3 엔진에서 제대로 계산한다 - 여기서는 turnover 를 진단으로만 낸다.
    """
    comp = R[idx].sum(axis=0) if len(idx) > 1 else R[idx[0]].copy()
    valid = ~np.isnan(comp)
    n_valid = valid.sum(axis=1)
    live = n_valid >= min_names                      # ④ 교집합 붕괴 게이트
    if not live.any():
        return None

    c = comp[live]
    f = FWD[live]
    thr = _threshold(c, topq, top_n)
    sel = (c >= thr) & ~np.isnan(c)
    elig = valid[live] & ~np.isnan(f)                # 벤치마크는 같은 적격집합의 EW
    with np.errstate(invalid="ignore"):
        num = np.where(sel & ~np.isnan(f), f, 0.0).sum(axis=1)
        den = (sel & ~np.isnan(f)).sum(axis=1)
        bnum = np.where(elig, f, 0.0).sum(axis=1)
        bden = elig.sum(axis=1)
    keep = (den > 0) & (bden > 0)
    if keep.sum() < 2:
        return None
    gross = num[keep] / den[keep]
    bench = bnum[keep] / bden[keep]
    return {
        "monthly_gross": gross,
        "monthly_net": gross - ROUNDTRIP_BPS / 10000.0,
        "monthly_bench": bench,
        "monthly_excess": gross - bench,
        "month_index": np.flatnonzero(live)[keep],
        "avg_names": float(n_valid[live][keep].mean()),
        "avg_held": float(den[keep].mean()),
    }


def stats_from_monthly(net, excess, bench, months, month_index):
    n = len(net)
    # 헤드라인 t 는 초과수익 기준이다 (위 eval_combo docstring 참고)
    esd = float(excess.std(ddof=1))
    t = float(excess.mean() / (esd / math.sqrt(n))) if esd > 0 else 0.0
    sd = float(net.std(ddof=1))
    eq = float(np.prod(1.0 + net))
    span = n / 12.0
    cagr = eq ** (1.0 / span) - 1.0 if eq > 0 else float("nan")
    sharpe = float(net.mean() / sd * math.sqrt(12)) if sd > 0 else 0.0
    peak, cum, mdd = 1.0, 1.0, 0.0
    for r in net:
        cum *= (1.0 + r)
        peak = max(peak, cum)
        mdd = min(mdd, cum / peak - 1.0)
    # 연도 집중도: 초과수익 기여의 최대 단일연도 비중.
    # PBR 원본이 초과분의 98.6%가 2022년 단 한 해였던 사고를 잡으려고 만든 게이트라
    # (rule_discovery_criteria.json) 절대수익이 아니라 초과수익으로 잰다.
    years = np.array([months[i][:4] for i in month_index])
    tot = float(excess.sum())
    max_year_pct = None
    if tot > 0:
        by = {y: float(excess[years == y].sum()) for y in np.unique(years)}
        max_year_pct = round(100.0 * max(by.values()) / tot, 1)
    pos, neg = net[net > 0].sum(), -net[net < 0].sum()
    return {"nMonths": n, "t": round(t, 3),
            "meanMonthlyExcess": round(float(excess.mean()), 6),
            "meanMonthlyNet": round(float(net.mean()), 6),
            "meanMonthlyBench": round(float(bench.mean()), 6),
            "excessHitRate": round(float((excess > 0).mean()), 3),
            "cagr": round(cagr, 4), "sharpe": round(sharpe, 3),
            "mdd": round(mdd, 4), "hitRate": round(float((net > 0).mean()), 3),
            "totalReturn": round(eq - 1.0, 4),
            "benchTotalReturn": round(float(np.prod(1.0 + bench)) - 1.0, 4),
            "calmar": round(cagr / abs(mdd), 3) if mdd < 0 else None,
            "profitFactor": round(float(pos / neg), 3) if neg > 0 else None,
            "maxSingleYearPct": max_year_pct}


def turnover_of(idx, R, TICK, topq=TOP_QUANTILE, min_names=MIN_NAMES, top_n=0):
    """연속한 두 리밸런스의 보유목록 교체율. 상위 조합에만 계산한다(비싸다)."""
    comp = R[idx].sum(axis=0) if len(idx) > 1 else R[idx[0]]
    prev, rates = None, []
    for mi in range(comp.shape[0]):
        row = comp[mi]
        v = ~np.isnan(row)
        if v.sum() < min_names:
            prev = None
            continue
        thr = float(_threshold(row[None, :], topq, top_n)[0, 0])
        cur = set(TICK[mi][v & (row >= thr)].tolist())
        if prev is not None and cur:
            rates.append(1.0 - len(cur & prev) / len(cur))
        prev = cur
    return round(float(np.mean(rates)), 3) if rates else None


# ---------------------------------------------------------------------------
# 스윕
# ---------------------------------------------------------------------------
def run_sweep(combos, R, FWD, months, topq, min_names, min_months, top_n=0):
    out = []
    for idx in combos:
        r = eval_combo(idx, R, FWD, topq, min_names, top_n)
        if r is None or len(r["monthly_net"]) < min_months:
            continue
        s = stats_from_monthly(r["monthly_net"], r["monthly_excess"], r["monthly_bench"],
                               months, r["month_index"])
        s["factors"] = idx
        s["avgNames"] = round(r["avg_names"], 1)
        s["avgHeld"] = round(r["avg_held"], 1)
        out.append(s)
    return out


def _score_one(idx, R, FWD, months, topq, min_names, min_months, top_n=0):
    r = eval_combo(idx, R, FWD, topq, min_names, top_n)
    if r is None or len(r["monthly_net"]) < min_months:
        return None
    s = stats_from_monthly(r["monthly_net"], r["monthly_excess"], r["monthly_bench"],
                           months, r["month_index"])
    s["factors"] = list(idx)
    s["avgNames"] = round(r["avg_names"], 1)
    s["avgHeld"] = round(r["avg_held"], 1)
    return s


def beam_search(R, FWD, months, topq, min_names, min_months, width, depth, verbose=False):
    """팩터를 한 개씩 붙여가며 상위 `width` 개만 남긴다.

    전수 탐색이 감당 못 하는 k>=4 를 여는 방법이자, 사용자가 원래 묘사한 절차
    그대로다 - "RSI 단독 +1% → PBR 더하니 +2% → 외국인 더하니 +3%".
    평가 횟수가 C(36,k) 가 아니라 width*36*depth 로 줄어드는 만큼 다중검정
    부담도 함께 줄어든다(난수 통과선이 낮아진다).

    반환: (steps, max_t_seen, n_evals)
      steps[i] = {"k", "beam":[상위 width 개], "best":최고}
      각 조합은 chain / chainT / addedFactor / deltaT / deltaExcess 를 들고 있어
      "몇 단계에서 무엇을 붙여 얼마나 좋아졌는지" 가 그대로 복원된다.
    """
    nF = R.shape[0]
    n_evals, max_t = 0, -1e9

    cur = []
    for f in range(nF):
        s = _score_one([f], R, FWD, months, topq, min_names, min_months)
        n_evals += 1
        if s:
            max_t = max(max_t, s["t"])
            s["chain"], s["chainT"] = [f], [s["t"]]
            s["addedFactor"], s["deltaT"], s["deltaExcess"] = f, None, None
            cur.append(s)
    if not cur:
        return [], max_t, n_evals
    cur.sort(key=lambda x: x["t"], reverse=True)
    cur = cur[:width]
    steps = [{"k": 1, "beam": cur, "best": cur[0]}]
    seen = {frozenset(s["factors"]) for s in cur}
    if verbose:
        print(f"    k=1  best t={cur[0]['t']:.2f}", flush=True)

    for k in range(2, depth + 1):
        nxt = []
        for parent in steps[-1]["beam"]:            # t 내림차순이라 먼저 붙는 부모가 최선
            for f in range(nF):
                if f in parent["factors"]:
                    continue
                idx = sorted(parent["factors"] + [f])
                key = frozenset(idx)
                if key in seen:
                    continue
                seen.add(key)
                s = _score_one(idx, R, FWD, months, topq, min_names, min_months)
                n_evals += 1
                if not s:
                    continue
                max_t = max(max_t, s["t"])
                s["chain"] = parent["chain"] + [f]
                s["chainT"] = parent["chainT"] + [s["t"]]
                s["addedFactor"] = f
                s["deltaT"] = round(s["t"] - parent["t"], 3)
                s["deltaExcess"] = round(s["meanMonthlyExcess"] - parent["meanMonthlyExcess"], 6)
                nxt.append(s)
        if not nxt:
            break
        nxt.sort(key=lambda x: x["t"], reverse=True)
        steps.append({"k": k, "beam": nxt[:width], "best": nxt[0]})
        if verbose:
            print(f"    k={k}  best t={nxt[0]['t']:.2f}  (Δt {nxt[0]['deltaT']:+.2f})", flush=True)
    return steps, max_t, n_evals


def beam_null_max_t(R, FWD, months, topq, min_names, min_months, width, depth, reps, seed=0):
    """빔서치는 적응적으로 고르므로, 난수 기준선도 **같은 절차 전체**를 다시 돌려야 한다.
    평가 횟수만 세서 보정하면 적응적 선택의 이득을 놓친다."""
    rng = np.random.default_rng(seed)
    maxes = []
    for rep in range(reps):
        F = FWD.copy()
        for mi in range(F.shape[0]):
            row = F[mi]
            v = np.flatnonzero(~np.isnan(row))
            if len(v) > 1:
                row[v] = row[rng.permutation(v)]
        _, mt, _ = beam_search(R, F, months, topq, min_names, min_months, width, depth)
        maxes.append(mt)
        print(f"    null {rep + 1}/{reps}: max t = {mt:.2f}", flush=True)
    return maxes


def null_max_t(combos, R, FWD, months, topq, min_names, min_months, reps, seed=0, top_n=0):
    """② fwd1m 을 월 내부에서 섞어 같은 스윕을 반복 → '운으로 나올 수 있는 최고 t' 분포.

    팩터 행렬 R 은 그대로 두므로 조합끼리의 상관구조(=다중검정 구조)가 보존된다.
    섞는 것은 정답(fwd)뿐이라 횡단면 예측력만 정확히 파괴된다.
    """
    rng = np.random.default_rng(seed)
    maxes = []
    for rep in range(reps):
        F = FWD.copy()
        for mi in range(F.shape[0]):
            row = F[mi]
            v = np.flatnonzero(~np.isnan(row))
            if len(v) > 1:
                row[v] = row[rng.permutation(v)]
        res = run_sweep(combos, R, F, months, topq, min_names, min_months, top_n)
        maxes.append(max((r["t"] for r in res), default=0.0))
        print(f"    null {rep + 1}/{reps}: max t = {maxes[-1]:.2f}", flush=True)
    return maxes


# ---------------------------------------------------------------------------
# 랭킹 규약 차이 실측 (판단을 근거 있게 하려고 남겨둔 진단)
# ---------------------------------------------------------------------------
def compare_convention(panel, catalog, names, topq=TOP_QUANTILE, min_names=MIN_NAMES):
    from scipy.stats import rankdata
    sub = panel[panel["period"] == "TRAIN"]
    a, b = [], []
    for _, g in sub.groupby("date"):
        gg = g.dropna(subset=list(names))
        if len(gg) < min_names:
            continue
        signs = [-1.0 if catalog[f]["direction"] == "low" else 1.0 for f in names]
        # A: 이 스크립트 규약 - 팩터별 전체 non-NaN 안에서 랭크한 뒤 교집합만 취함
        ca = sum(s * g[f].rank(pct=True).reindex(gg.index).to_numpy()
                 for f, s in zip(names, signs))
        # B: build_composite_selection.py 규약 - dropna 먼저, 그 안에서 랭크
        cb = sum(s * rankdata(gg[f].to_numpy()) / len(gg) for f, s in zip(names, signs))
        for c, acc in ((ca, a), (cb, b)):
            thr = np.quantile(c, topq)
            acc.append(float(gg["fwd1m"].to_numpy()[c >= thr].mean()))
    a, b = np.array(a), np.array(b)
    tt = lambda x: float(x.mean() / (x.std(ddof=1) / math.sqrt(len(x))))
    print(f"랭킹 규약 비교  ({'+'.join(names)}, TRAIN {len(a)}개월)")
    print(f"  A 이 스크립트(팩터별 랭크 후 교집합) : 월평균 {a.mean() * 100:+.3f}%  t={tt(a):.3f}")
    print(f"  B 기존(dropna 먼저 후 랭크)          : 월평균 {b.mean() * 100:+.3f}%  t={tt(b):.3f}")
    print(f"  차이                                 : {abs(a.mean() - b.mean()) * 100:.4f}%p, "
          f"월별 상관 {np.corrcoef(a, b)[0, 1]:.4f}")


# ---------------------------------------------------------------------------
def selftest():
    """심어둔 신호를 찾아내는가 + 난수 기준선이 실제로 작동하는가."""
    rng = np.random.default_rng(7)
    M, N, K = 60, 300, 5
    R = rng.standard_normal((K, M, N)).astype(np.float32)
    # 팩터 0 에만 진짜 신호를 심는다
    FWD = (0.05 * R[0] + rng.standard_normal((M, N)) * 0.08).astype(np.float32)
    months = [f"20{16 + i // 12:02d}-{i % 12 + 1:02d}-01" for i in range(M)]

    combos = [list(c) for k in (1, 2) for c in itertools.combinations(range(K), k)]
    res = run_sweep(combos, R, FWD, months, TOP_QUANTILE, MIN_NAMES, MIN_MONTHS)
    assert res, "스윕이 아무 조합도 못 냈다"
    best = max(res, key=lambda r: r["t"])
    assert 0 in best["factors"], f"심어둔 신호를 못 찾았다: {best['factors']}"
    assert best["t"] > 2.0, best["t"]

    # 정답을 섞으면 그 신호가 사라져야 한다
    nulls = null_max_t(combos, R, FWD, months, TOP_QUANTILE, MIN_NAMES, MIN_MONTHS, reps=3, seed=1)
    assert max(nulls) < best["t"], f"난수 기준선({max(nulls):.2f})이 진짜 신호({best['t']:.2f})를 넘었다"

    # 교집합 붕괴 게이트: 종목이 모자란 달은 버려져야 한다
    R2 = R.copy()
    R2[1, :30, :] = np.nan                      # 팩터1 을 앞 30개월 전부 결측
    r_all = eval_combo([0], R2, FWD)
    r_int = eval_combo([0, 1], R2, FWD)
    assert len(r_int["monthly_net"]) == len(r_all["monthly_net"]) - 30, \
        "결측 월이 안 걸러졌다"

    # 비용이 실제로 빠지는가
    r = eval_combo([0], R, FWD)
    assert np.allclose(r["monthly_gross"] - r["monthly_net"], ROUNDTRIP_BPS / 10000.0)

    # top-N 고정 선택: 매달 정확히 N개를 고르고, decile 과 다른 결과를 낸다
    # (이 픽스처는 월 300종목이라 decile 이 정확히 30개다 - top_n 은 그보다 작게 잡는다)
    r_dec = eval_combo([0], R, FWD, TOP_QUANTILE, MIN_NAMES)
    r_n10 = eval_combo([0], R, FWD, TOP_QUANTILE, MIN_NAMES, top_n=10)
    assert abs(r_n10["avg_held"] - 10.0) < 1e-9, r_n10["avg_held"]
    assert abs(r_dec["avg_held"] - 30.0) < 1e-9, r_dec["avg_held"]
    assert not np.allclose(r_dec["monthly_gross"], r_n10["monthly_gross"]), \
        "top_n 을 줬는데 decile 과 같은 결과가 나온다(옵션이 안 먹었다)"
    # 유효 종목수가 N 보다 적은 달에서도 터지지 않아야 한다
    R_thin = R.copy()
    R_thin[0, :, 40:] = np.nan
    assert eval_combo([0], R_thin, FWD, TOP_QUANTILE, MIN_NAMES, top_n=100) is not None

    # 빔서치: 심어둔 신호를 1단계에서 잡고, 체인이 실제로 복원되는가
    steps, bmax, nev = beam_search(R, FWD, months, TOP_QUANTILE, MIN_NAMES, MIN_MONTHS,
                                   width=3, depth=3)
    assert steps and steps[0]["best"]["factors"] == [0], steps[0]["best"]["factors"]
    assert nev < sum(math.comb(K, k) for k in range(1, 4)) * 3, "빔이 전수보다 안 줄었다"
    top = max((s["best"] for s in steps), key=lambda x: x["t"])
    assert bmax >= top["t"], "max_t_seen 이 실제 최고보다 작다"
    for s in steps[1:]:
        b = s["best"]
        assert len(b["chain"]) == s["k"] and b["chain"][-1] == b["addedFactor"]
        assert len(b["chainT"]) == s["k"], "증분 경로(chainT)가 안 쌓였다"
        assert b["deltaT"] is not None

    # 추가 지표가 실제로 계산되는가
    s1 = _score_one([0], R, FWD, months, TOP_QUANTILE, MIN_NAMES, MIN_MONTHS)
    for key in ("totalReturn", "calmar", "profitFactor", "benchTotalReturn"):
        assert key in s1, key

    print("selftest OK (신호탐지·난수기준선·교집합게이트·비용반영·빔체인·지표 6건)")


def run_beam_mode(a, factors, catalog, manifest, R, FWD, TICK, months, t0):
    nm = lambda i: factors[i]
    print(f"\n① TRAIN({a.period}) 빔서치: 폭 {a.beam} x 깊이 {a.beam_k} "
          f"x {len(factors)}팩터 ...", flush=True)
    t1 = time.time()
    steps, best_t, n_evals = beam_search(R, FWD, months, a.top_quantile, a.min_names,
                                         a.min_months, a.beam, a.beam_k, verbose=True)
    beam_s = time.time() - t1
    if not steps:
        print("빔서치가 아무 조합도 못 냈다 (게이트 통과 0)")
        return 1
    print(f"  평가 {n_evals:,}회, {beam_s:.0f}s  "
          f"(전수 k<={a.beam_k} 였다면 "
          f"{sum(math.comb(len(factors), k) for k in range(1, a.beam_k + 1)):,}회)")

    print(f"\n② 난수 귀무분포 {a.nulls}회 — 같은 빔서치 절차를 통째로 재실행 "
          f"(예상 {beam_s * a.nulls / 60:.0f}분) ...", flush=True)
    nulls = beam_null_max_t(R, FWD, months, a.top_quantile, a.min_names, a.min_months,
                            a.beam, a.beam_k, a.nulls, seed=20260902)
    bar95 = float(np.quantile(nulls, 0.95))
    print(f"  난수 max-t: 중앙값 {np.median(nulls):.2f} / 95분위 {bar95:.2f} / "
          f"최대 {max(nulls):.2f}")

    overall = max((s["best"] for s in steps), key=lambda x: x["t"])
    print(f"\n③ 평가 {n_evals:,}회 중 최고 t={overall['t']:.2f} "
          f"vs 난수선 {bar95:.2f} -> "
          f"{'난수선 통과' if overall['t'] > bar95 else '난수선 이하 (운과 구분 안 됨)'}")

    print(f"\n=== 단계별 증분 (최종 최고 조합이 만들어진 경로) ===")
    print(f"{'k':>2} {'추가한 팩터':<24} {'t':>6} {'Δt':>6} {'초과/월':>8} {'Δ초과':>8} "
          f"{'CAGR':>7} {'MDD':>7}")
    print("-" * 82)
    chain = overall["chain"]
    for k in range(1, len(chain) + 1):
        node = next((c for c in steps[k - 1]["beam"] if c["chain"] == chain[:k]), None)
        if node is None:
            continue
        dt = f"{node['deltaT']:+.2f}" if node["deltaT"] is not None else "-"
        de = f"{node['deltaExcess'] * 100:+.3f}%" if node["deltaExcess"] is not None else "-"
        print(f"{k:>2} {nm(chain[k - 1]):<24} {node['t']:>6.2f} {dt:>6} "
              f"{node['meanMonthlyExcess'] * 100:>7.3f}% {de:>8} "
              f"{node['cagr'] * 100:>6.2f}% {node['mdd'] * 100:>6.1f}%")

    print(f"\n=== 각 k 의 최고 조합 ===")
    print(f"{'k':>2} {'t':>6} {'초과/월':>8} {'CAGR':>7} {'Sharpe':>7} {'MDD':>7} "
          f"{'Calmar':>7} {'PF':>5} {'승률':>5} {'월':>4} 조합")
    print("-" * 118)
    for s in steps:
        b = s["best"]
        b["turnover"] = turnover_of(b["factors"], R, TICK, a.top_quantile, a.min_names)
        cal = f"{b['calmar']:.2f}" if b["calmar"] is not None else "-"
        pf = f"{b['profitFactor']:.2f}" if b["profitFactor"] is not None else "-"
        flag = "" if b["t"] > bar95 else "  (난수선 이하)"
        print(f"{s['k']:>2} {b['t']:>6.2f} {b['meanMonthlyExcess'] * 100:>7.3f}% "
              f"{b['cagr'] * 100:>6.2f}% {b['sharpe']:>7.2f} {b['mdd'] * 100:>6.1f}% "
              f"{cal:>7} {pf:>5} {b['hitRate'] * 100:>4.0f}% {b['nMonths']:>4} "
              f"{'+'.join(nm(i) for i in b['factors'])}{flag}")

    for s in steps:
        for c in s["beam"]:
            c["factorNames"] = [nm(i) for i in c["factors"]]
            c["chainNames"] = [nm(i) for i in c["chain"]]
            c["addedFactorName"] = nm(c["addedFactor"])
    out_dir = a.out or os.path.join(LAB, "reports",
                                    f"{time.strftime('%Y-%m-%d')}-combo-sweep")
    os.makedirs(out_dir, exist_ok=True)
    tag = f"-no{a.exclude_family.replace(',', '')}" if a.exclude_family else ""
    out_path = os.path.join(out_dir, f"beam-{a.period.lower()}-w{a.beam}k{a.beam_k}{tag}.json")
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump({
            "experiment": "COMBO-BEAM-KR",
            "panelVersion": manifest["panelVersion"],
            "period": a.period,
            "method": "beam search (forward selection, 폭 유지)",
            "gates": {
                "trainOnly": a.period, "beamWidth": a.beam, "beamDepth": a.beam_k,
                "nEvaluations": n_evals,          # ③ 다중검정 규모
                "exhaustiveEquivalent": sum(math.comb(len(factors), k)
                                            for k in range(1, a.beam_k + 1)),
                "nullReps": a.nulls, "nullMaxT": [round(x, 3) for x in nulls],
                "nullBar95": round(bar95, 3), "nullBarMax": round(max(nulls), 3),
                "bestT": overall["t"], "passesNullBar": bool(overall["t"] > bar95),
                "minNames": a.min_names, "minMonths": a.min_months,
                "topQuantile": a.top_quantile, "roundTripBps": ROUNDTRIP_BPS,
            },
            "warning": "TRAIN 전용. VALID/TEST 는 이 절차가 보지 않았다. 난수선 통과는 "
                       "'운이 아닐 수 있다'이지 '알파다'가 아니다 - 채택은 "
                       "rule_discovery_criteria.json 의 나머지 게이트를 통과한 뒤에만.",
            "factorsUsed": factors,
            "bestChain": [nm(i) for i in chain],
            "steps": steps,
        }, f, ensure_ascii=False, indent=1)
    print(f"\n저장: {out_path}")
    print(f"총 {time.time() - t0:.0f}s")
    return 0


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--max-k", type=int, default=3, help="전수 탐색 최대 조합 크기")
    ap.add_argument("--beam", type=int, default=0,
                    help="빔서치 폭(0이면 전수 탐색). k>=4 는 전수가 불가능해서 이쪽을 쓴다 - "
                         "C(36,5)=376,992 vs 빔(폭10,깊이8) 2,486회")
    ap.add_argument("--beam-k", type=int, default=8, help="빔서치 최대 깊이")
    ap.add_argument("--nulls", type=int, default=20)
    ap.add_argument("--period", default="TRAIN")
    ap.add_argument("--factors", default="all")
    ap.add_argument("--top-quantile", type=float, default=TOP_QUANTILE)
    ap.add_argument("--top-n", type=int, default=0,
                    help="0 이면 상위 decile(분위수), N 이면 매달 랭크합 상위 N개 고정. "
                         "엔진의 maxPositions 와 맞춰 재검증할 때 쓴다")
    ap.add_argument("--min-names", type=int, default=MIN_NAMES)
    ap.add_argument("--min-months", type=int, default=MIN_MONTHS)
    ap.add_argument("--include-redundant", action="store_true")
    ap.add_argument("--exclude-family", default=None,
                    help="계열 제외 (쉼표구분). 예: Liquidity — 이 패널에서 dv20_log(저유동성)가 "
                         "다른 모든 팩터를 압도하는데, 2026-08-21에 확인된 '유동성이 팩터보다 "
                         "강한 예측변수' 함정과 같은 현상이라 그 아래를 보려면 떼고 돌려야 한다")
    ap.add_argument("--top", type=int, default=25)
    ap.add_argument("--out", default=None)
    ap.add_argument("--selftest", action="store_true")
    ap.add_argument("--compare-convention", default=None)
    a = ap.parse_args()

    if a.selftest:
        selftest()
        return 0

    manifest = json.load(open(MANIFEST_PATH, encoding="utf-8"))
    catalog = manifest["factors"]
    panel = pd.read_parquet(PANEL_PATH)

    if a.compare_convention:
        compare_convention(panel, catalog, a.compare_convention.split(","),
                           a.top_quantile, a.min_names)
        return 0

    selftest()
    if a.factors == "all":
        factors = [f for f, v in catalog.items()
                   if a.include_redundant or not v.get("redundant")]
    else:
        factors = a.factors.split(",")
    if a.exclude_family:
        drop = set(a.exclude_family.split(","))
        before = len(factors)
        factors = [f for f in factors if catalog[f]["family"] not in drop]
        print(f"계열 제외 {sorted(drop)}: {before} -> {len(factors)}개 팩터")
    for f in factors:
        if f not in catalog:
            raise SystemExit(f"패널에 없는 팩터: {f}")

    t0 = time.time()
    print(f"\n패널 {len(panel):,}행 -> {a.period} 행렬 구성 ...", flush=True)
    R, FWD, TICK, months, M, width, _names = build_matrices(panel, catalog, factors, a.period)
    print(f"  {M}개월 x 최대 {width}종목 x {len(factors)}팩터  ({time.time() - t0:.1f}s)")

    if a.beam:
        return run_beam_mode(a, factors, catalog, manifest, R, FWD, TICK, months, t0)

    combos = [list(c) for k in range(1, a.max_k + 1)
              for c in itertools.combinations(range(len(factors)), k)]
    print(f"\n① TRAIN({a.period}) 전용 스윕: {len(combos):,}개 조합 ...", flush=True)
    t1 = time.time()
    res = run_sweep(combos, R, FWD, months, a.top_quantile, a.min_names, a.min_months, a.top_n)
    sweep_s = time.time() - t1
    print(f"  {len(res):,}개 조합이 게이트 통과 "
          f"({len(combos) - len(res):,}개는 교집합/월수 부족으로 탈락), {sweep_s:.0f}s")

    print(f"\n② 난수 귀무분포 {a.nulls}회 (예상 {sweep_s * a.nulls / 60:.0f}분) ...", flush=True)
    nulls = null_max_t(combos, R, FWD, months, a.top_quantile, a.min_names,
                       a.min_months, a.nulls, seed=20260902, top_n=a.top_n)
    bar95 = float(np.quantile(nulls, 0.95))
    bar_max = float(max(nulls))
    print(f"  난수 max-t: 중앙값 {np.median(nulls):.2f} / 95분위 {bar95:.2f} / 최대 {bar_max:.2f}")

    res.sort(key=lambda r: r["t"], reverse=True)
    survivors = [r for r in res if r["t"] > bar95]
    print(f"\n③ 조합 {len(combos):,}개 중 난수 95분위({bar95:.2f})를 넘은 것: "
          f"{len(survivors):,}개")

    print(f"\n  t 는 '같은 적격집합 EW 대비 초과수익'의 t 다. CAGR 은 비용 반영 절대수익.")
    print(f"\n{'#':>3} {'t':>6} {'초과/월':>8} {'CAGR':>7} {'Sharpe':>7} {'MDD':>7} "
          f"{'최대연도%':>8} {'월':>4} {'적격':>6} {'회전':>5} 조합")
    print("-" * 118)
    for i, r in enumerate(res[:a.top], 1):
        r["turnover"] = turnover_of(r["factors"], R, TICK, a.top_quantile, a.min_names, a.top_n)
        names = "+".join(factors[j] for j in r["factors"])
        my = f"{r['maxSingleYearPct']:.0f}" if r["maxSingleYearPct"] is not None else "-"
        tv = f"{r['turnover']:.2f}" if r["turnover"] is not None else "-"
        flag = "" if r["t"] > bar95 else "  (난수선 이하)"
        print(f"{i:>3} {r['t']:>6.2f} {r['meanMonthlyExcess'] * 100:>7.3f}% "
              f"{r['cagr'] * 100:>6.2f}% {r['sharpe']:>7.2f} {r['mdd'] * 100:>6.1f}% "
              f"{my:>8} {r['nMonths']:>4} {r['avgNames']:>6.0f} {tv:>5} {names}{flag}")

    for r in res:
        r["factors"] = [factors[j] for j in r["factors"]]
    out_dir = a.out or os.path.join(LAB, "reports",
                                    f"{time.strftime('%Y-%m-%d')}-combo-sweep")
    os.makedirs(out_dir, exist_ok=True)
    payload = {
        "experiment": "COMBO-SWEEP-KR",
        "panelVersion": manifest["panelVersion"],
        "period": a.period,
        "gates": {
            "trainOnly": a.period,
            "nCombosTested": len(combos),          # ③ 다중검정 규모를 결과에 박는다
            "nCombosPassedCoverageGate": len(res),
            "nullReps": a.nulls,
            "nullMaxT": [round(x, 3) for x in nulls],
            "nullBar95": round(bar95, 3),
            "nullBarMax": round(bar_max, 3),
            "nSurvivorsAboveNullBar95": len(survivors),
            "minNames": a.min_names, "minMonths": a.min_months,
            "topQuantile": a.top_quantile, "topN": a.top_n, "roundTripBps": ROUNDTRIP_BPS,
        },
        "rankingConvention": "팩터별 월내 pct-rank 후 선택팩터 전부 존재하는 종목만(교집합)",
        "warning": "TRAIN 전용 결과다. VALID/TEST 는 이 스윕이 보지 않았다. "
                   "난수선을 넘었다는 것은 '운이 아닐 수 있다'이지 '알파다'가 아니다 - "
                   "채택은 rule_discovery_criteria.json 의 나머지 게이트(구간 부호 일관성·"
                   "연도집중도·절대임계값 재확인·엔진 실전검증)를 통과한 뒤에만.",
        "factorsUsed": factors,
        "results": res,
    }
    tag = f"-no{a.exclude_family.replace(',', '')}" if a.exclude_family else ""
    out_path = os.path.join(out_dir, f"combo-sweep-{a.period.lower()}-k{a.max_k}{tag}.json")
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=1)
    print(f"\n저장: {out_path}")
    print(f"총 {time.time() - t0:.0f}s")
    return 0


if __name__ == "__main__":
    sys.exit(main())
