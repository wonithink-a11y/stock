#!/usr/bin/env python3
"""국내 상장 ETF 6종 시계열 모멘텀 — 사전등록 findings/multiasset-tsmom-preregistration-2026-10.md 그대로.

    python research/strategy-lab/multiasset_tsmom.py --selftest
    python research/strategy-lab/multiasset_tsmom.py      # → findings/multiasset-tsmom-results-2026-10.{md,json}

가중치는 월말 신호로 정하고 그달 내내 같은 목표 비중(일 단위 재조정 근사)을 쓴다 — 규칙과 기준이 같은 방식이다.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import etf_timing_lab as e

OUT = HERE / "findings" / "multiasset-tsmom-results-2026-10"
ASSETS = ["069500", "143850", "133690", "132030", "148070", "138230"]
NAMES = ["KODEX 200", "S&P500(H)", "나스닥100", "금(H)", "국고채10년", "달러선물"]
CASH = "114260"
WINDOWS = {"TRAIN": ("2012-11-01", "2016-12-31"), "VALID": ("2017-01-01", "2020-12-31"), "TEST": ("2021-01-01", "2026-12-31")}


def weights(R, cal, look=12, invvol=False):
    """반환 W (T × 7: 자산 6 + 현금)."""
    lv = {a: e.month_end_levels(R[a], cal) for a in ASSETS + [CASH]}
    cash12 = lv[CASH] / lv[CASH].shift(look) - 1
    T = len(cal)
    W = np.zeros((T, 7))
    sig = {}
    for k, a in enumerate(ASSETS):
        m = lv[a] / lv[a].shift(look) - 1
        sig[a] = e.monthly_to_daily((m > cash12).astype(float).where(m.notna() & cash12.notna()), cal)
    S = np.column_stack([sig[a].to_numpy() for a in ASSETS])
    if invvol:
        vol = np.column_stack([R[a].rolling(60, min_periods=40).std().to_numpy() for a in ASSETS])
        per = cal.to_period("M")
        me = pd.Series(np.arange(T)).groupby(per).max()
        wv = np.full((T, 6), np.nan)
        for i, p in enumerate(me.index[1:], 1):
            r_prev = me.iloc[i - 1]
            iv = 1 / vol[r_prev]
            wv[(per == p)] = iv / np.nansum(iv)
        base = wv
    else:
        base = np.full((T, 6), 1 / 6)
    W[:, :6] = S * base
    W[:, 6] = 1 - np.nansum(W[:, :6], axis=1)
    W[np.isnan(S).any(1) | np.isnan(base).any(1)] = np.nan
    return W


def run():
    panel = e.load_panel()
    cal = pd.DatetimeIndex(sorted(panel.loc[panel["code"] == e.K200, "date"]))
    R = {a: e.tr_returns(panel, a, cal) for a in ASSETS + [CASH]}
    Rm = np.column_stack([R[a].to_numpy() for a in ASSETS + [CASH]])
    rng = np.random.default_rng(e.SEED)
    offsets = rng.integers(e.MIN_SHIFT, len(cal) - e.MIN_SHIFT, e.N_SHIFT)
    e.WINDOWS = WINDOWS
    out = {}
    for nm, kw in (("판정(12개월·1/6)", {}), ("기록: 변동성 역가중", {"invvol": True}), ("기록: 6개월", {"look": 6})):
        W = weights(R, cal, **kw)
        valid = np.isfinite(W).all(1) & np.isfinite(Rm).all(1)
        res = {c: e.evaluate(np.nan_to_num(W), Rm, cal, valid, offsets, cost)[0] for c, cost in (("base", e.COST), ("stress", e.STRESS))}
        out[nm] = {c: {w: None if r[w] is None else dict(S=r[w]["act"] - float(np.nanmean(r[w]["shift"])), p95=float(np.nanpercentile(r[w]["shift"] - np.nanmean(r[w]["shift"]), 95)),
                                                         stats=r[w]["stats"], expo=float(np.nanmean(np.nan_to_num(W)[valid][:, :6].sum(1)))) for w in WINDOWS} for c, r in res.items()}
        if nm.startswith("판정"):
            valid0 = valid
    bench = np.full((len(cal), 7), 0.0)
    bench[:, :6] = 1 / 6
    br = e.strat_returns(bench, Rm, 0.0)
    bstats = {w: e.stats(br[valid0 & (cal >= pd.Timestamp(a)) & (cal <= pd.Timestamp(b))]) for w, (a, b) in WINDOWS.items()}
    j = out["판정(12개월·1/6)"]
    info = j["base"]["TRAIN"]["S"] >= j["base"]["TRAIN"]["p95"] and j["base"]["VALID"]["S"] > 0 and j["base"]["TEST"]["S"] > 0
    econ = info and j["stress"]["VALID"]["S"] > 0 and j["stress"]["TEST"]["S"] > 0
    verdict = "ECONOMIC" if econ else ("INFORMATION" if info else "REJECT")
    res = dict(verdict=verdict, cells=out, bench=bstats)
    OUT.with_suffix(".json").write_text(json.dumps(res, ensure_ascii=False, indent=1, default=float), encoding="utf-8")
    pc = lambda x: f"{x * 100:+.1f}%"
    L = ["---", "track: kr", "factor: multiasset-tsmom", "date: 2026-10-09", f"verdict: {verdict}", "criteria_version: research-only (multiasset-tsmom-preregistration-2026-10)",
         'conditions: ["국내 상장 ETF 6종(KODEX 200·S&P500(H)·나스닥100·금(H)·국고채10년·달러선물), 현금 국고채3년", "12개월 수익 > 현금 12개월이면 1/6 보유", "원형 이동 1,000회 95백분위", "비용 5bp(스트레스 10bp)"]',
         "reason: >-", f"  신호: {'있음' if verdict != 'REJECT' else '없음'} · 경제성: {'통과' if verdict == 'ECONOMIC' else '미달'}. (스크립트 판정)", "---", "",
         "# 국내 상장 ETF 6종 시계열 모멘텀 — 결과", "", "| 칸 | 구간 | S(5bp) | 바닥선 | S(10bp) | 위험자산 비중 | CAGR | 샤프 | MDD | 기준(1/6 고정) CAGR/샤프/MDD |", "|---|---|---:|---:|---:|---:|---:|---:|---:|---|"]
    for nm, cc in out.items():
        for w in WINDOWS:
            b, s = cc["base"][w], cc["stress"][w]
            bb = bstats[w]
            L.append(f"| {nm} | {w} | {b['S']:+.2f} | {b['p95']:+.2f} | {s['S']:+.2f} | {b['expo']:.0%} | {pc(b['stats']['cagr'])} | {b['stats']['sharpe']:.2f} | {pc(b['stats']['mdd'])} | "
                     f"{pc(bb['cagr'])} / {bb['sharpe']:.2f} / {pc(bb['mdd'])} |")
    L += ["", f"판정: **{verdict}**. 위험자산 비중은 표본 전체 평균."]
    OUT.with_suffix(".md").write_text("\n".join(L) + "\n", encoding="utf-8")
    print(verdict, {nm: {w: round(cc["base"][w]["S"], 2) for w in WINDOWS} for nm, cc in out.items()}, {w: round(bstats[w]["sharpe"], 2) for w in WINDOWS})
    return 0


def selftest():
    ok = True

    def check(name, cond):
        nonlocal ok
        ok &= bool(cond)
        print(("PASS " if cond else "FAIL ") + name)

    cal = pd.bdate_range("2019-01-01", "2021-12-31")
    rng = np.random.default_rng(0)
    R = {a: pd.Series(0.001 if i % 2 == 0 else -0.001, index=cal) for i, a in enumerate(ASSETS)}
    R[CASH] = pd.Series(0.0, index=cal)
    W = weights(R, cal)
    last = W[-1]
    check("12개월 오른 자산만 1/6, 나머지는 현금 1/2", np.allclose(last[:6], [1 / 6, 0, 1 / 6, 0, 1 / 6, 0]) and abs(last[6] - 0.5) < 1e-12)
    print("ALL PASS" if ok else "FAILED")
    return 0 if ok else 1


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--selftest", action="store_true")
    sys.exit(selftest() if ap.parse_args().selftest else run())
