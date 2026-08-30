#!/usr/bin/env python
"""A3/A3b 미활용 필드 팩터 프리체크 - [RESEARCH HYPOTHESIS] (첫 실행, 튜닝 없음).

대상 필드 3개 (모두 PIT 규칙 availableFrom <= 리밸런스일 준수):
  1. divYield : 연간 dividendPerShare(A3b) / 당일 종가
  2. per      : 당일 종가 / EPS(A3b, eps>0만)   - 기존 valuation-panel의 per 재검증 격
  3. opMargin : opProfit / revenue (A3, revenue>0만)

설계 (교훈 반영 - 처음부터 절대 유동성):
  - 월별 리밸런스(각 월 첫 거래일), 2017-01~2026-07
  - turnover20(rolling20,min_periods=20, 거래대금) >= 1억원 만 대상 (기존 값 재사용)
  - 요인값 날짜 내 10분위(decile, method='first' 결정적) -> 각 분위 T+20 초과수익
    (같은 날 패널 전체 동일가중 벤치마크) + 날짜별 Spearman 순위IC 평균/t
  - 방향 가정 없이 오름차순(작은 값=Q1) 고정 보고

  python a3_factor_precheck.py
"""
import glob
import gzip
import json
import os
import sys
import time

import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))
REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
FUND_DIR = os.path.join(REPO_ROOT, "data", "backfill", "fundamentals")
PANEL_PATH = os.path.join(REPO_ROOT, "research", "strategy-lab", "data", "a4", "a4-research-dataset.parquet")
OUT_DIR = os.path.join(HERE, "findings", "a3-factor-precheck")
MIN_TURNOVER = 100_000_000.0


def read_gz_years(sub, fields, year_range):
    rows = []
    for year in range(*year_range):
        p = os.path.join(FUND_DIR, sub, f"{year}.jsonl.gz")
        if not os.path.exists(p):
            continue
        with gzip.open(p, "rt", encoding="utf-8") as fh:
            for line in fh:
                d = json.loads(line)
                av = str(d.get("availableFrom", ""))
                av = f"{av[:4]}-{av[4:6]}-{av[6:8]}" if len(av) == 8 else d.get("availableFrom")
                if not av:
                    continue
                rows.append([d["ticker"], av] + [d.get(k) for k in fields])
    return pd.DataFrame(rows, columns=["ticker", "avail"] + fields)


def load_panel():
    cols = ["ticker", "date", "close", "total_amount"]
    df = pd.read_parquet(PANEL_PATH, columns=cols)
    df = df.sort_values(["ticker", "date"]).reset_index(drop=True)
    g = df.groupby("ticker")["close"]
    df["fwd20"] = g.transform(lambda s: s.shift(-20) / s - 1)
    df["turn20"] = g["close"].transform(lambda s: 0.0) if False else None
    ta = df.groupby("ticker")["total_amount"]
    df["turn20"] = ta.transform(lambda s: s.fillna(0).rolling(20, min_periods=20).mean())
    return df


def main():
    t0 = time.time()
    # --- 펀더멘털 패널
    a3 = read_gz_years("a3", ["opProfit", "revenue"], (2015, 2027))
    a3 = a3.dropna(subset=["opProfit", "revenue"])
    a3 = a3[a3["revenue"] > 0]
    a3["opMargin"] = a3["opProfit"] / a3["revenue"]

    a3b = read_gz_years("a3b", ["eps", "dividendPerShare", "dividendRowPresent"], (2015, 2027))
    print(f"a3 rows={len(a3)}, a3b rows={len(a3b)} ({time.time()-t0:.0f}s)", flush=True)

    # --- 가격 패널 + 리밸런스 일자
    px = load_panel()
    dates = sorted(px["date"].unique())
    rb_dates, seen = [], set()
    for d in dates:
        if d < "2017-01-01" or d > "2026-07-31":
            continue
        ym = d[:7]
        if ym not in seen:
            seen.add(ym)
            rb_dates.append(d)
    print(f"rebalance dates={len(rb_dates)} ({time.time()-t0:.0f}s)", flush=True)

    uni = px[(px["date"].isin(set(rb_dates)))].copy()

    def latest_asof(fund):
        fund = fund.copy()
        fund["avail"] = pd.to_datetime(fund["avail"])
        fund = fund.sort_values("avail")  # merge_asof는 양쪽 on 키 전역 정렬 요구
        u = uni[["ticker", "date"]].copy()
        u["dateDt"] = pd.to_datetime(u["date"])
        u = u.sort_values("dateDt")
        return pd.merge_asof(u, fund, left_on="dateDt", right_on="avail",
                             by="ticker", direction="backward")

    def evaluate(factor_df, value_col, name, valid_fn, derive=None):
        """value_col: 최종 랭킹 컬럼명. derive가 있으면 가격 병합 후 파생(예: per=close/eps)."""
        m = latest_asof(factor_df)
        if derive is None:
            m = m.dropna(subset=[value_col])
            m = m[m[value_col].map(valid_fn)]
        pxr = px[px["date"].isin(set(rb_dates))][["ticker", "date", "close", "turn20", "fwd20"]]
        j = m.merge(pxr, on=["ticker", "date"], how="left")
        if derive is not None:
            j = j.dropna(subset=["eps", "close"])
            j[value_col] = derive(j)
            keepmask = j[value_col].map(valid_fn)
            j = j[keepmask.fillna(False)]
        j = j[j["turn20"] >= MIN_TURNOVER]
        j = j[j["fwd20"].notna()]
        bench = px[px["date"].isin(set(rb_dates)) & px["fwd20"].notna()] \
                    .groupby("date")["fwd20"].mean().rename("bench")
        j = j.merge(bench, on="date", how="left")
        j["excess"] = j["fwd20"] - j["bench"]
        j = j.sort_values(["date", "ticker"]).reset_index(drop=True)
        j["decile"] = j.groupby("date")[value_col].transform(
            lambda s: np.minimum(np.ceil(s.rank(method="first", pct=True) * 10), 10).astype(int))

        lad = j.groupby(["date", "decile"])["excess"].mean().groupby("decile").mean() * 100
        ic = j.groupby("date").apply(
            lambda x: x[value_col].corr(x["fwd20"], method="spearman"),
            include_groups=False).dropna()
        block = {
            "rows": int(len(j)),
            "dates": int(ic.shape[0]),
            "decileExcessMeanPct": {f"D{q}": round(float(lad.get(q, float('nan'))), 4)
                                    for q in range(1, 11)},
            "spearmanICMean": round(float(ic.mean()), 5),
            "icT": round(float(ic.mean() / (ic.std() / max(1, np.sqrt(len(ic))))), 2),
        }
        print(name, json.dumps(block, ensure_ascii=False)[:260], flush=True)
        return block

    results = {}
    results["divYield"] = evaluate(a3b, "dividendPerShare", "divYield(dps/close, asc)",
                                   lambda v: pd.notna(v) and v >= 0,
                                   derive=lambda d: d["dividendPerShare"] / d["close"])
    eps_pos = a3b.dropna(subset=["eps"])
    eps_pos = eps_pos[eps_pos["eps"] > 0]
    results["perEpsPositive"] = evaluate(eps_pos, "per", "per(close/eps, asc)",
                                         lambda v: pd.notna(v) and v > 0,
                                         derive=lambda d: d["close"] / d["eps"])
    results["opMargin"] = evaluate(a3, "opMargin", "opMargin(asc)", lambda v: pd.notna(v))

    os.makedirs(OUT_DIR, exist_ok=True)
    out_path = os.path.join(OUT_DIR, "precheck_results.json")
    with open(out_path, "w", encoding="utf-8") as fh:
        json.dump({
            "generatedAt": time.strftime("%Y-%m-%dT%H:%M:%S"),
            "label": "[RESEARCH HYPOTHESIS] - 첫 실행, 튜닝 없음",
            "conventions": {
                "liquidity": f"turnover20 >= {MIN_TURNOVER:,.0f} KRW (기존 값 재사용, 처음부터 적용)",
                "pit": "fundamentals availableFrom <= 리밸런스일 (연간 갱신이라 최대 ~15개월 정태 허용됨)",
                "decile": "요인값 오름차순 10분위(Q1=최소값) - 방향 가정 없음",
                "metric": "분위별 T+20 초과수익(%p, 같은 날 패널 전체 동일가중 대비) + 날짜별 "
                          "Spearman 순위IC 평균/t",
                "period": "월별 리밸런스 2017-01~2026-07",
            },
            "results": results,
        }, fh, ensure_ascii=False, indent=2)
    print("saved:", out_path)


if __name__ == "__main__":
    main()
