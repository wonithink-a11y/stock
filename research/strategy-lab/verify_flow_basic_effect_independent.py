#!/usr/bin/env python
"""외국인수급5D 효과(flow-basic-effect-2026-08.md) 독립 재현.

목적: 그 finding은 다른 에이전트(추정 OpenCode) 산출물이라 이 프로젝트 원칙상
("생산자·검증자 분리") 독립 검증 전까지 확정 사실로 취급하지 않는다. 원본
스크립트(flow_basic_effect.py)의 사전 가공 parquet(data/a4/a4-research-
dataset.parquet)을 그대로 재사용하지 않고, **원시 소스(A2a 가격 + A4
raw 수급)부터 독립적으로 새로 짠다** - 그래야 그 parquet 자체의 오류도
같이 잡을 수 있다. 방법론(날짜별 cross-sectional quintile + Newey-West
t검정, 자동 lag)과 기간분할(TRAIN/VALID/TEST 경계)은 원본과 동일하게
맞춰야 숫자를 직접 비교할 수 있다 - 방법론까지 다르면 뭐가 달라서 다른
결과가 나왔는지 못 가린다.

실측 대조로 확인한 것: foreign_net = buyAmount[외국인]+buyAmount[기타외국인]
- sellAmount[외국인]-sellAmount[기타외국인] (외국인 하나만 쓰면 다른 값이
나옴 - 000020/2016-01-04 실측으로 확인, 기타외국인 누락분=31,800원).
"""
import glob
import gzip
import json
import os

import numpy as np
import pandas as pd

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
A2A_DIR = os.path.join(REPO_ROOT, "data", "backfill", "price", "a2a")
A4_DIR = os.path.join(REPO_ROOT, "data", "backfill", "supplyDemand", "a4")

SPLIT = {
    "TRAIN": ("2016-01-01", "2022-06-30"),
    "VALID": ("2022-07-01", "2024-01-01"),
    "TEST": ("2024-01-01", "2026-12-31"),
}


def load_a2a_price():
    frames = []
    for path in sorted(glob.glob(os.path.join(A2A_DIR, "*.jsonl.gz"))):
        with gzip.open(path, "rt", encoding="utf-8") as f:
            recs = [json.loads(line) for line in f]
        frames.append(pd.DataFrame(recs, columns=["ticker", "date", "close"]))
    df = pd.concat(frames, ignore_index=True)
    df["close"] = pd.to_numeric(df["close"], errors="coerce")
    return df


def load_a4_flow():
    frames = []
    for path in sorted(glob.glob(os.path.join(A4_DIR, "*.jsonl.gz"))):
        recs = []
        with gzip.open(path, "rt", encoding="utf-8") as f:
            for line in f:
                o = json.loads(line)
                ba, sa = o["buyAmount"], o["sellAmount"]
                foreign_net = (ba.get("외국인", 0) + ba.get("기타외국인", 0)
                               - sa.get("외국인", 0) - sa.get("기타외국인", 0))
                recs.append({
                    "ticker": o["ticker"],
                    "date": o["date"],
                    "foreign_net": foreign_net,
                    "total_amount": ba.get("전체", np.nan),
                })
        frames.append(pd.DataFrame(recs))
    df = pd.concat(frames, ignore_index=True)
    df["foreign_net"] = pd.to_numeric(df["foreign_net"], errors="coerce")
    df["total_amount"] = pd.to_numeric(df["total_amount"], errors="coerce")
    return df


def compute_quintile_spread(df, feat, fwd_col, n_quintile=5):
    """원본(flow_basic_effect.py)과 동일한 방법 - 날짜별 ordinal rank -> quintile,
    quintile별 평균을 날짜별로 구해 Q5-Q1 스프레드 시계열을 만든다."""
    sub = df.dropna(subset=[feat, fwd_col]).copy()
    if len(sub) == 0:
        return None
    ranks = sub.groupby("date")[feat].rank(method="first")
    counts = sub.groupby("date")[feat].transform("count")
    sub["q"] = np.ceil(ranks / counts * n_quintile).astype(int).clip(1, n_quintile)
    qmean = sub.groupby(["date", "q"])[fwd_col].mean().unstack()
    qmean = qmean[[c for c in range(1, n_quintile + 1) if c in qmean.columns]]
    qmean["spread"] = qmean[n_quintile] - qmean[1]
    qdf = qmean.dropna(subset=["spread"])
    return qdf


def newey_west_tstat(series):
    x = series.dropna().values
    n = len(x)
    if n < 3:
        return None, None
    lags = int(np.floor(4 * (n / 100) ** (2 / 9)))
    mean = x.mean()
    demeaned = x - mean
    gamma0 = np.mean(demeaned ** 2)
    nw_var = gamma0
    for l in range(1, lags + 1):
        w = 1 - l / (lags + 1)
        gamma_l = np.mean(demeaned[l:] * demeaned[:-l])
        nw_var += 2 * w * gamma_l
    se = np.sqrt(nw_var / n)
    t = mean / se if se > 0 else None
    return t, lags


def spread_stats(qdf):
    s = qdf["spread"].dropna()
    n = len(s)
    mean = float(s.mean())
    std = float(s.std(ddof=1))
    t_stat = mean / (std / np.sqrt(n)) if std > 0 and n > 1 else None
    nw_t, lags = newey_west_tstat(s)
    return {"mean": mean, "std": std, "t_stat": t_stat, "nw_t": nw_t, "n_days": n, "nw_lags": lags}


def main():
    print("Loading raw A2a price + A4 flow (independent build, not reusing a4-research-dataset.parquet)...")
    price = load_a2a_price()
    flow = load_a4_flow()
    print(f"  A2A price: {len(price)} rows, {price['ticker'].nunique()} tickers")
    print(f"  A4 flow: {len(flow)} rows, {flow['ticker'].nunique()} tickers")

    df = price.merge(flow, on=["ticker", "date"], how="inner")
    df = df.sort_values(["ticker", "date"]).reset_index(drop=True)
    print(f"  Merged: {len(df)} rows, {df['ticker'].nunique()} tickers, "
          f"date range {df['date'].min()} ~ {df['date'].max()}")

    df["fwd_d5"] = df.groupby("ticker")["close"].transform(lambda s: s.shift(-5) / s - 1)
    df["foreign_flow_ratio"] = df["foreign_net"] / df["total_amount"].replace(0, np.nan)

    print("\n=== 전체 기간 (독립재현 vs flow-basic-effect.md 원본 값) ===")
    qdf_all = compute_quintile_spread(df, "foreign_flow_ratio", "fwd_d5")
    s_all = spread_stats(qdf_all)
    print(f"  독립재현: mean={s_all['mean']:+.6f} t={s_all['t_stat']:.3f} "
          f"NW_t={s_all['nw_t']:.3f} n_days={s_all['n_days']} (lags={s_all['nw_lags']})")
    print(f"  원본 문서: mean=+0.003793 t=19.870 NW_t=15.530 n_days=2590")

    print("\n=== 구간별 (독립재현 vs 원본) ===")
    results = {}
    for period_name, (start, end) in SPLIT.items():
        mask = (df["date"] >= start) & (df["date"] < end)
        qdf = compute_quintile_spread(df[mask], "foreign_flow_ratio", "fwd_d5")
        s = spread_stats(qdf)
        results[period_name] = s
        print(f"  {period_name}: mean={s['mean']:+.6f} t={s['t_stat']:.3f} "
              f"NW_t={s['nw_t']:.3f} n_days={s['n_days']}")
    print("  원본 문서: TRAIN mean=+0.004642 NW_t=15.155 n=1595 | "
          "VALID mean=+0.001620 NW_t=3.263 n=370 | TEST mean=+0.002951 NW_t=5.914 n=624")

    all_pos = all(results[p]["mean"] > 0 for p in SPLIT)
    print(f"\n방향 일관성(독립재현): {'CONSISTENT (전 구간 양)' if all_pos else 'INCONSISTENT'}")


if __name__ == "__main__":
    main()
