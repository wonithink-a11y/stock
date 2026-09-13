#!/usr/bin/env python3
"""SOXL 선행지표 파일럿 공용 배터리 — VIX/IPG3344S/DART/TSMC 4건에서 반복
작성하던 검증 세트(Spearman·Newey-West·비중첩·분위수·전환이벤트)를 추출했다.
세 번째부터 복붙하는 건 재사용 규칙(ladder 2단) 위반이라 여기로 뺐다.
기존 DART/TSMC 스크립트는 이미 커밋된 동작코드라 되짚어 고치지 않는다 —
다음 파일럿부터 이걸 쓴다.

    python research/strategy-lab/soxl_leadlag_common.py --selftest
"""
from pathlib import Path

import numpy as np
import pandas as pd
from scipy import stats

ROOT = Path(__file__).resolve().parent


def load_fwd_returns(df: pd.DataFrame, price: pd.Series, prefix: str,
                      asof_col: str = "availableFrom", months=(1, 3, 6)) -> pd.DataFrame:
    """asof_col 시점부터 임의 가격 시리즈(date-indexed close)의 향후
    1/3/6개월 수익률(%) 열을 `{prefix}_fwd_{m}m`으로 붙인다. SOXL 전용이던
    `load_soxl_fwd`를 일반화한 것 — DRAM/메모리주 파일럿(005930·000660)이
    같은 로직을 재사용한다."""
    def fwd_ret(asof, m):
        end = asof + pd.DateOffset(months=m)
        s = price.loc[asof:end]
        if len(s) < 2 or s.index[0] > asof + pd.Timedelta(days=10):
            return np.nan
        return (s.iloc[-1] / s.iloc[0] - 1) * 100

    df = df.copy()
    for m in months:
        df[f"{prefix}_fwd_{m}m"] = df[asof_col].apply(lambda d: fwd_ret(d, m))
    return df


def load_soxl_fwd(df: pd.DataFrame, asof_col: str = "availableFrom",
                   months=(1, 3, 6)) -> pd.DataFrame:
    """asof_col 시점부터 SOXL의 향후 1/3/6개월 수익률(%) 열을 붙인다."""
    soxl = pd.read_parquet(ROOT / "data" / "leveraged-etf" / "SOXL.parquet")
    soxl["date"] = pd.to_datetime(soxl["date"])
    soxl = soxl.sort_values("date").set_index("date")["close"]
    return load_fwd_returns(df, soxl, "soxl", asof_col, months)


def run_battery(df: pd.DataFrame, factors: list[str], date_col: str = "periodEnd",
                 months=(1, 3, 6), min_n: int = 20, target_prefix: str = "soxl") -> None:
    """Spearman(naive) + Newey-West(HAC) + 완전 비중첩 + 5분위 + 상승/하락전환.
    threshold 최적화·전략화는 절대 하지 않는다 — 관측만 출력한다.
    target_prefix: `load_fwd_returns`가 붙인 열 이름 접두사(예: "soxl"→
    soxl_fwd_1m, "s005930"→s005930_fwd_1m)."""
    import statsmodels.api as sm

    def col(m):
        return f"{target_prefix}_fwd_{m}m"

    print(f"관측치: {len(df)}행 ({df[date_col].min()} ~ {df[date_col].max()})")

    print("\n=== 1. Spearman (naive, overlap 있음) ===")
    print(f"{'factor':18s} {'horizon':8s} {'n':>4s} {'rho':>8s} {'p':>8s}")
    for factor in factors:
        for m in months:
            sub = df[[factor, col(m)]].dropna()
            if len(sub) < min_n:
                continue
            rho, p = stats.spearmanr(sub[factor], sub[col(m)])
            flag = " *" if p < 0.05 else ""
            print(f"{factor:18s} {str(m)+'m':8s} {len(sub):4d} {rho:+8.3f} {p:8.3f}{flag}")

    print("\n=== 2. Newey-West(HAC) OLS ===")
    for factor in factors:
        for m in months:
            sub = df[[factor, col(m)]].dropna()
            if len(sub) < min_n:
                continue
            X = sm.add_constant(sub[factor])
            y = sub[col(m)]
            lag = max(1, m - 1)
            model = sm.OLS(y, X).fit(cov_type="HAC", cov_kwds={"maxlags": lag})
            coef, p = model.params[factor], model.pvalues[factor]
            flag = " *" if p < 0.05 else ""
            print(f"{factor:18s} {str(m)+'m':8s} n={len(sub):4d} lag={lag}  "
                  f"coef={coef:+8.3f}  p={p:8.3f}{flag}")

    print("\n=== 3. 완전 비중첩 서브샘플 (첫 factor만) ===")
    primary = factors[0]
    for m in months:
        sub_full = df[[primary, col(m)]].dropna()
        sub = sub_full.iloc[::m]
        if len(sub) < 15:
            continue
        rho, p = stats.spearmanr(sub[primary], sub[col(m)])
        print(f"{primary} vs {m}m 비중첩(n={len(sub)}):  rho={rho:+.3f}  p={p:.3f}")

    print(f"\n=== 4. 분위수별 선행수익률 ({primary} 5분위) ===")
    sub = df[[primary] + [col(m) for m in months]].dropna().copy()
    sub["q"] = pd.qcut(sub[primary], 5, labels=["Q1(최저)", "Q2", "Q3", "Q4", "Q5(최고)"])
    print(sub.groupby("q", observed=True)[[col(m) for m in months]].mean().to_string())
    print("표본수:", sub.groupby("q", observed=True).size().to_dict())

    print(f"\n=== 5. {primary} 상승전환/하락전환 이벤트 ===")
    sub2 = df[[date_col, primary] + [col(m) for m in months]].dropna().reset_index(drop=True)
    sub2["prev_sign"] = np.sign(sub2[primary].shift(1))
    sub2["curr_sign"] = np.sign(sub2[primary])
    up_cross = sub2[(sub2["prev_sign"] < 0) & (sub2["curr_sign"] > 0)]
    down_cross = sub2[(sub2["prev_sign"] > 0) & (sub2["curr_sign"] < 0)]
    for label, ev in (("상승전환", up_cross), ("하락전환", down_cross)):
        means = "  ".join(f"fwd{m}m={ev[col(m)].mean():+.1f}%" for m in months)
        print(f"{label}(n={len(ev)}): 평균 {means}")


def selftest() -> int:
    fails = []

    def ck(name, cond):
        print(("ok   " if cond else "FAIL ") + name)
        if not cond:
            fails.append(name)

    idx = pd.date_range("2020-01-31", periods=24, freq="ME")
    df = pd.DataFrame({"periodEnd": idx, "availableFrom": idx + pd.Timedelta(days=15),
                        "factor": np.sin(np.arange(24) / 3)})
    out = load_soxl_fwd(df)
    ck("soxl_fwd 열 3개 생성", all(f"soxl_fwd_{m}m" in out.columns for m in (1, 3, 6)))
    ck("결측 아닌 값이 하나 이상", out["soxl_fwd_1m"].notna().sum() > 0)

    print("\n(run_battery 출력 스모크 — 값 검증이 아니라 예외 없이 도는지만 확인)")
    run_battery(out, ["factor"], min_n=5)

    total = 2
    print(f"\nselftest {total - len(fails)}/{total}" + ("" if not fails else f"  FAILED: {fails}"))
    return 1 if fails else 0


if __name__ == "__main__":
    import sys
    if "--selftest" in sys.argv:
        raise SystemExit(selftest())
    print(__doc__)
