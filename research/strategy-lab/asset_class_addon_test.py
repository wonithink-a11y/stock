#!/usr/bin/env python3
"""코어(SPY, 또는 SPY·QQQ 50/50)에 자산군 하나를 20% 더했을 때의 한계 효과 — 실행 전 고정한 설계(2026-09-30).

    python research/strategy-lab/asset_class_addon_test.py --selftest
    python research/strategy-lab/asset_class_addon_test.py     # -> findings/asset-class-addon-results-2026-09.json

- 후보 8개 고정: QQQ(중복 대조) GLD(금) TLT(미국 장기채) IEF(미국 중기채) EFA(선진국 ex-US) EEM(신흥국) EWY(한국, USD) VNQ(리츠) DBC(원자재)
- 코어 80 + 후보 20, 연 1회 12월 리밸런스, 편도 5bp, 월간 USD 총수익(yfinance auto_adjust). 기간 2006-03~2026-09(DBC 이력 기준).
- 지표: 코어 대비 ΔCAGR ΔSharpe ΔMDD Δ최악12개월, 코어와 월수익 상관, 코어 최악 낙폭 두 구간(2007-11~2009-02, 2021-12~2022-09)의 후보 수익.
- ΔSharpe 신뢰구간 = 12개월 블록 부트스트랩 2,000회(같은 표본 인덱스로 두 포트폴리오). 구간 나눔 2006-2012 · 2013-2021 · 2022~.
- 판정 규칙(결과 전): "분산 효과 있음" = ΔMDD 가 음(낙폭 축소)이고 ΔSharpe 95% 구간 하한이 −0.1 이상이며 세 구간 중 두 구간에서 ΔSharpe ≥ 0.
  "샤프 개선" 은 ΔSharpe 95% 구간 하한 > 0 일 때만 쓴다. 나머지는 "구분 불가". 결과를 보고 비중·후보를 바꿔 재시험하지 않는다.
- 한계: 하나의 역사 경로, 환율·환헤지·세금 미반영, 미국 대형주 우위 기간(2010~)에 치우침.
"""
from __future__ import annotations

import json
import math
import sys
from pathlib import Path

import numpy as np
import pandas as pd

LAB = Path(__file__).resolve().parent
D = LAB / "data" / "pension-test"
COST = 0.0005
CAND = ["QQQ", "GLD", "TLT", "IEF", "EFA", "EEM", "EWY", "VNQ", "DBC"]
SLICES = {"전체": ("2006-03", "2026-12"), "2006-2012": ("2006-03", "2012-12"), "2013-2021": ("2013-01", "2021-12"), "2022~": ("2022-01", "2026-12")}
EPIS = {"2007-11~2009-02": ("2007-11", "2009-02"), "2021-12~2022-09": ("2021-12", "2022-09")}


def ensure(t):
    f = D / f"{t}.parquet"
    if f.exists():
        return
    import yfinance as yf
    df = yf.Ticker(t).history(period="max", auto_adjust=True)
    df.index = pd.to_datetime(df.index).tz_localize(None).normalize()
    df[["Close"]].rename(columns={"Close": "close"}).to_parquet(f)


def mret(t):
    ensure(t)
    return pd.read_parquet(D / f"{t}.parquet")["close"].resample("ME").last().dropna().pct_change().dropna()


def sim(R: pd.DataFrame, tw: np.ndarray):
    T = len(R)
    out = np.zeros(T)
    drift = np.zeros(R.shape[1])
    for i in range(T):
        if i == 0 or R.index[i - 1].month == 12:
            cost = COST * np.abs(tw - drift).sum()
            drift = tw.copy()
        else:
            cost = 0.0
        r = float((drift * R.values[i]).sum())
        out[i] = r - cost
        drift = drift * (1 + R.values[i]) / (1 + r)
    return pd.Series(out, R.index)


def sharpe(x):
    return x.mean() * 12 / (x.std() * math.sqrt(12))


def summ(r: pd.Series):
    w = (1 + r).cumprod()
    roll12 = (1 + r).rolling(12).apply(np.prod, raw=True) - 1
    return dict(cagr=float(w.iloc[-1] ** (12 / len(r)) - 1), sharpe=float(sharpe(r)),
                mdd=float((w / w.cummax() - 1).min()), worst12=float(roll12.min()))


def boot_dsharpe(a: np.ndarray, b: np.ndarray, n=2000, block=12, seed=3):
    T = len(a)
    rng = np.random.default_rng(seed)
    nb = math.ceil(T / block)
    ds = []
    for _ in range(n):
        st = rng.integers(0, T, nb)
        ix = np.concatenate([(s + np.arange(block)) % T for s in st])[:T]
        ds.append(sharpe(pd.Series(a[ix])) - sharpe(pd.Series(b[ix])))
    return float(np.quantile(ds, .025)), float(np.quantile(ds, .975))


def run():
    res = {}
    for core_name in ("SPY", "SPY+QQQ"):
        res[core_name] = {}
        for c in CAND:
            if core_name == "SPY+QQQ" and c == "QQQ":
                continue
            X = pd.concat([mret(x) for x in {"SPY": 1, "QQQ": 1, c: 1}], axis=1, keys=list({"SPY": 1, "QQQ": 1, c: 1})).dropna()["2006-03":]
            # 코어 단독
            if c == "QQQ":
                Xc = X[["SPY", "QQQ"]]
                core_only = sim(Xc, np.array([1.0, 0.0]))
                comb = sim(Xc, np.array([.8, .2]))
            else:
                Xc = X[["SPY", "QQQ", c]]
                cwt = np.array([1.0, 0.0, 0.0]) if core_name == "SPY" else np.array([.5, .5, 0.0])
                core_only = sim(Xc, cwt)
                comb = sim(Xc, cwt * .8 + np.array([0, 0, .2]))
            row = {"n": len(core_only), "first": str(core_only.index[0].date()),
                   "corr_core": float(X[c].corr(core_only)) if c != "QQQ" else float(X["QQQ"].corr(X["SPY"]))}
            row["core"] = summ(core_only)
            row["combo"] = summ(comb)
            lo, hi = boot_dsharpe(comb.values, core_only.values)
            row["d"] = dict(cagr=row["combo"]["cagr"] - row["core"]["cagr"], sharpe=row["combo"]["sharpe"] - row["core"]["sharpe"],
                            sharpe_ci=[lo, hi], mdd=row["combo"]["mdd"] - row["core"]["mdd"],
                            worst12=row["combo"]["worst12"] - row["core"]["worst12"])
            row["d_slices"] = {k: float(sharpe(comb[a:b]) - sharpe(core_only[a:b])) for k, (a, b) in SLICES.items() if k != "전체"}
            row["episodes"] = {k: dict(cand=float(np.prod(1 + X[c][a:b]) - 1), core=float(np.prod(1 + core_only[a:b]) - 1))
                               for k, (a, b) in EPIS.items()}
            div = (row["d"]["mdd"] < 0 and lo >= -0.1 and sum(v >= 0 for v in row["d_slices"].values()) >= 2)
            row["label"] = ("샤프 개선" if lo > 0 else "분산 효과 있음" if div else "구분 불가")
            res[core_name][c] = row
    out = LAB / "findings" / "asset-class-addon-results-2026-09.json"
    out.write_text(json.dumps(res, ensure_ascii=False, indent=1), encoding="utf-8")
    print("wrote", out)


def selftest():
    idx = pd.date_range("2020-01-31", periods=36, freq="ME")
    R = pd.DataFrame({"a": 0.01, "b": 0.0}, index=idx)
    s = sim(R, np.array([1.0, 0.0]))
    assert abs(s.iloc[0] - (0.01 - COST)) < 1e-12 and abs(s.iloc[5] - 0.01) < 1e-12
    x = pd.Series(np.random.default_rng(0).normal(.01, .04, 120))
    lo, hi = boot_dsharpe(x.values, x.values, n=50)
    assert lo == 0 == hi
    print("selftest ok")


if __name__ == "__main__":
    selftest() if "--selftest" in sys.argv else run()
