#!/usr/bin/env python3
"""미국 국채 월말 효과. 사전등록 findings/us-treasury-month-end-preregistration-2026-11.md

    python research/strategy-lab/us_treasury_month_end.py            # 결과 JSON + 요약 (수 초, yfinance 공개)
    python research/strategy-lab/us_treasury_month_end.py --selftest

월 초과 E = 마지막 3거래일 일 수익 합 − 같은 달 나머지 거래일 평균 × 3. 바닥선 = 같은 달 안 무작위 3연속 거래일 창 순열. 기록 전용.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
OUT_JSON = HERE / "findings" / "us-treasury-month-end-results.json"
WIN, NPERM, NBOOT, SEED, ALPHA, ALPHA_TEST, COST_BP = 3, 4000, 2000, 20261117, 0.05 / 12, 0.05, 5.0
PERIODS = {"TRAIN": ("2002-08", "2012-12"), "VALID": ("2013-01", "2019-12"), "TEST": ("2020-01", "2026-10")}
ERAS = {"2016~23": ("2016-01", "2023-12"), "2024": ("2024-01", "2024-12"), "2025~": ("2025-01", "2026-10")}
LAST_FULL = "2026-10"


def fetch(tk: str) -> pd.Series:
    import yfinance as yf
    x = yf.download(tk, start="2002-01-01", auto_adjust=True, progress=False)
    x.columns = x.columns.get_level_values(0)
    s = x["Close"].dropna()
    assert len(s) > 5000, f"{tk} 행 {len(s)}"                                          # 빈 응답을 성공으로 세지 않는다(교훈 81)
    return s.pct_change().dropna()


def month_tables(r: pd.Series, w: int = WIN):
    """완결 월별 (키, 관측 E, 위치별 E 배열). 첫 부분 월(상장 달)과 마지막 미완결 월은 제외."""
    keys, obs, alls = [], [], []
    for k, g in r.groupby(r.index.strftime("%Y-%m")):
        v = g.to_numpy()
        if len(v) < 15 or k < "2002-08" or k > LAST_FULL:
            continue
        n = len(v)
        csum = np.r_[0.0, np.cumsum(v)]
        tot = csum[-1]
        wsum = csum[w:] - csum[:-w]                                                        # 길이 n−w+1, 위치 j 의 창 합
        E_all = wsum - w * (tot - wsum) / (n - w)
        keys.append(k)
        obs.append(float(E_all[-1]))                                                       # 마지막 w 거래일
        alls.append(E_all)
    return keys, np.array(obs), alls


def in_period(keys, a, b):
    return np.array([a <= k <= b for k in keys])


def perm_p(alls, mask, obs_mean, rng):
    idx = np.nonzero(mask)[0]
    draws = np.empty(NPERM)
    for t in range(NPERM):
        draws[t] = np.mean([alls[i][rng.integers(0, len(alls[i]))] for i in idx])
    return float((1 + np.sum(draws >= obs_mean)) / (1 + NPERM))


def boot_ci(x, rng):
    bs = [np.mean(rng.choice(x, len(x))) for _ in range(NBOOT)]
    return [round(float(np.percentile(bs, 2.5)) * 1e4, 2), round(float(np.percentile(bs, 97.5)) * 1e4, 2)]


def summarize(keys, obs, alls, rng, with_p=True):
    out = {}
    for nm, (a, b) in {"전 기간": ("2002-08", "2026-10"), **PERIODS, **ERAS}.items():
        m = in_period(keys, a, b)
        if m.sum() < 6:
            out[nm] = None
            continue
        x = obs[m]
        mean = float(x.mean())
        row = dict(n=int(m.sum()), grossBp=round(mean * 1e4, 2), ci95Bp=boot_ci(x, rng), netBp=round(mean * 1e4 - COST_BP, 2),
                   breakevenBp=round(mean * 1e4, 2), pos=round(float((x > 0).mean() * 100)))
        if with_p and nm in ("전 기간", "TRAIN", "VALID", "TEST"):
            row["permP"] = round(perm_p(alls, m, mean, rng), 4)
        out[nm] = row
    return out


def verdict(res) -> tuple[str, str]:
    full, parts = res["전 기간"], [res[k] for k in PERIODS]
    if full["grossBp"] <= 0 or full["permP"] > ALPHA_TEST:
        sig = "REJECT"
    elif full["permP"] <= ALPHA and all(p["grossBp"] > 0 for p in parts) and res["TEST"]["permP"] <= ALPHA_TEST:
        sig = "신호 있음"
    elif full["permP"] <= ALPHA:
        sig = "INFORMATION"
    else:
        sig = "INCONCLUSIVE"
    econ = "통과" if full["netBp"] > 0 and res["TEST"]["netBp"] > 0 else "미달"
    return sig, econ


def selftest() -> int:
    ok = 0
    d = pd.bdate_range("2003-01-01", "2012-12-31")
    rng = np.random.default_rng(1)
    r = pd.Series(rng.normal(0, 0.003, len(d)), index=d)
    ends = r.groupby([r.index.year, r.index.month]).tail(3).index
    r[ends] += 0.001                                                                    # 월말 3일에 하루 +10bp 심기
    keys, obs, alls = month_tables(r)
    assert 100 < len(keys) <= 120 and abs(obs.mean() - 0.003) < 0.0015, (len(keys), obs.mean()); ok += 1   # 3일×10bp ≈ 30bp
    res = summarize(keys, obs, alls, np.random.default_rng(2), with_p=True)
    assert res["전 기간"]["permP"] <= 0.01 and res["전 기간"]["grossBp"] > 20, res["전 기간"]; ok += 1       # 심은 효과는 잡힌다
    r0 = pd.Series(rng.normal(0, 0.003, len(d)), index=d)
    k0, o0, a0 = month_tables(r0)
    assert summarize(k0, o0, a0, np.random.default_rng(3))["전 기간"]["permP"] > 0.01; ok += 1             # 심지 않으면 안 잡힌다
    _, E = np.array([0.0]), None
    v = np.array([1, 1, 1, 1, 1, 4, 4, 4.0]) / 100
    s = pd.Series(v, index=pd.bdate_range("2003-01-27", periods=8))
    csum = np.r_[0.0, np.cumsum(v)]; w = csum[3:] - csum[:-3]; Ea = w - 3 * (csum[-1] - w) / 5
    assert abs(Ea[-1] - (0.12 - 3 * 0.01)) < 1e-12; ok += 1                          # E = 합 − 3×나머지 평균
    print(f"selftest OK ({ok})")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--selftest", action="store_true")
    if ap.parse_args().selftest:
        return selftest()
    out = {}
    rng = np.random.default_rng(SEED)
    keys, obs, alls = month_tables(fetch("IEF"))
    res = summarize(keys, obs, alls, rng)
    sig, econ = verdict(res)
    out["IEF"] = dict(result=res, signal=sig, economics=econ, months=len(keys), monthly={k: round(float(e) * 1e4, 2) for k, e in zip(keys, obs)})
    print(f"IEF 월 {len(keys)}개 → 신호 {sig} · 경제성 {econ}")
    for nm, row in res.items():
        print(f"  {nm}: {row}")
    rec = {}
    for tk in ("TLT",):                                                                 # 기록 전용
        k2, o2, a2 = month_tables(fetch(tk))
        rec[tk] = summarize(k2, o2, a2, np.random.default_rng(SEED + 1))
    for w in (1, 2, 5):
        k2, o2, a2 = month_tables(fetch("IEF"), w)
        rec[f"IEF 창 {w}일"] = {k: v for k, v in summarize(k2, o2, a2, np.random.default_rng(SEED + w), with_p=True).items() if k in ("전 기간", "TEST")}
    out["기록전용"] = rec
    for nm, v in rec.items():
        print("기록", nm, {k: (r["grossBp"], r.get("permP")) for k, r in v.items() if r})
    OUT_JSON.write_text(json.dumps(out, ensure_ascii=False, indent=1, default=float), encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main())
