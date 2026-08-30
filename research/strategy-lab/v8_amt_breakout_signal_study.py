#!/usr/bin/env python
"""V8 거래대금 상위 + 저항선 돌파 최소 signal study (엔진 미연결 — 이벤트 스터디만).

가설[V8, OBSERVED]: 거래대금 상위 종목군 + 차트상 저항선 + 돌파 시 매수 — 컨셉만
확인된 단타. 지시에 따라 trend_breakout_v1(Donchian 20일 고점 엣지 트리거,
strategies/trend_breakout_v1/policy.json의 signal.expression 그대로)과 비교해
거래대금 상위 필터의 incremental value를 분리 측정한다.

[UNSPECIFIED] -> 임시 채택 (첫 실행 고정, 튜닝 없음):
  - 저항선 = 직전 20거래일 최고가(Donchian high, 당일 제외) — trend_breakout_v1과
    동일해야 비교가 성립하므로 채택. 영상 기간 미상(ASSUMPTION).
  - 트리거 = Close[t]>dh[t] AND Close[t-1]<=dh[t-1] (엣지, 동일)
  - "조정 깊이"·"거래량 수축" 조건: 첫 실행에서는 넣지 않는다(미확정 항목 유지).
  - 거래대금 상위 = 당일 거래대금이 같은 날 패널 내 백분위 >= 0.70 (V7과 동일 임시).

비교 설계:
  variantA_breakoutOnly   : trend_breakout_v1 신호만 (a4 유니버스 전체)
  variantB_amtTop30       : 위 신호 AND 거래대금 상위 30% (V8 컨셉)
두 변형의 차이가 곧 V8 컨셉의 incremental value다.

데이터: A2a OHLC 캐시(.cache/a2a_parquet, 읽기 전용) + a4 패널(total_amount).
측정: v1~v7와 동일 관계 — T+1/5/10/20 close-to-close(A2a), 같은 날 유니버스 전체
동일가중 벤치마크, 날짜별 초과수익의 날짜 동일가중 평균.

  python v8_amt_breakout_signal_study.py
"""
import json
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
A4_PANEL_PATH = os.path.join(REPO_ROOT, "research", "strategy-lab", "data", "a4", "a4-research-dataset.parquet")
A2A_CACHE_DIR = os.path.join(REPO_ROOT, "research", "strategy-lab", ".cache", "a2a_parquet")
OUT_DIR = os.path.join(REPO_ROOT, "research", "strategy-lab", "findings", "v8-amt-breakout")
HORIZONS = {"T+1": 1, "T+5": 5, "T+10": 10, "T+20": 20}
DONCHIAN_N = 20
AMT_Q = 0.70


def load_ohlc_with_amount():
    uni = set(pd.read_parquet(A4_PANEL_PATH, columns=["ticker"])["ticker"].unique())
    frames = []
    for year in range(2016, 2027):
        p = os.path.join(A2A_CACHE_DIR, f"{year}.parquet")
        if not os.path.exists(p):
            continue
        d = pd.read_parquet(p, columns=["ticker", "date", "high", "low", "close"])
        d = d[d["ticker"].isin(uni)]
        frames.append(d)
    df = pd.concat(frames, ignore_index=True)
    df["date"] = pd.to_datetime(df["date"]).dt.strftime("%Y-%m-%d")
    amt = pd.read_parquet(A4_PANEL_PATH, columns=["ticker", "date", "total_amount"])
    df = df.merge(amt, on=["ticker", "date"], how="left")
    df = df.sort_values(["ticker", "date"]).reset_index(drop=True)
    g = df.groupby("ticker")
    # trend_breakout_v1/engine/indicators/donchian.py 규약: 당일 제외 직전 N일 최고가
    df["donchianHigh"] = g["high"].transform(
        lambda s: s.rolling(DONCHIAN_N, min_periods=DONCHIAN_N).max().shift(1))
    for h_name, h in HORIZONS.items():
        df[f"fwd_{h}"] = g["close"].transform(lambda s: s.shift(-h) / s - 1)
    return df


def stats_for(sig, bench_by_date, fwd_col):
    d = sig.dropna(subset=[fwd_col])
    if d.empty:
        return {"n": 0}
    joined = d.set_index("date")[fwd_col].rename("sig").to_frame().join(bench_by_date.rename("bench"))
    daily_excess = joined["sig"] - joined["bench"]
    years = d["date"].str[:4]
    yearly = {}
    for y in sorted(years.unique()):
        m = (years == y).values
        yearly[y] = {
            "n": int(m.sum()),
            "excessMean": round(float(daily_excess[m].mean()), 5),
            "sigMean": round(float(d.loc[m, fwd_col].mean()), 5),
        }
    return {
        "n": int(len(d)),
        "nDates": int(d["date"].nunique()),
        "avgPerDay": round(len(d) / max(1, d["date"].nunique()), 1),
        "mean": round(float(d[fwd_col].mean()), 5),
        "median": round(float(d[fwd_col].median()), 5),
        "winRate": round(float((d[fwd_col] > 0).mean()), 4),
        "benchMean": round(float(joined["bench"].mean()), 5),
        "excessPerDateMatched": round(float(daily_excess.mean()), 5),
        "yearly": yearly,
    }


def main():
    t0 = time.time()
    df = load_ohlc_with_amount()
    print(f"panel rows={len(df)}, tickers={df['ticker'].nunique()}, "
          f"dates={df['date'].nunique()} ({df['date'].min()}~{df['date'].max()}) ({time.time()-t0:.0f}s)")

    g = df.groupby("ticker")
    # trend_breakout_v1 규약: 엣지 트리거 Close[t]>dh[t] AND Close[t-1]<=dh[t-1]
    above = df["close"] > df["donchianHigh"]
    prev_above = above.groupby(df["ticker"]).shift(1)
    signal = (above & ~prev_above.fillna(False).astype(bool)).astype(bool)
    n_raw = int(signal.sum())
    print(f"breakout signal rows={n_raw} ({time.time()-t0:.0f}s)")

    amt_rank = df.groupby("date")["total_amount"].rank(pct=True)
    variants = {
        "variantA_breakoutOnly": signal,
        "variantB_amtTop30": signal & (amt_rank >= AMT_Q),
    }
    diag = {
        "breakoutRowsRaw": n_raw,
        "overlapShareAmtTop30": round(float((variants["variantB_amtTop30"]).sum() / max(1, n_raw)), 4),
    }
    print("diag:", diag)

    results = {"diagnostics": diag}
    for name, m in variants.items():
        sig_all = df[m]
        block = {"signalRowsRaw": int(len(sig_all))}
        print(f"{name}: rows={len(sig_all)}")
        for h_name, h in HORIZONS.items():
            fwd_col = f"fwd_{h}"
            bench = df.dropna(subset=[fwd_col]).groupby("date")[fwd_col].mean()
            block[h_name] = stats_for(sig_all, bench, fwd_col)
            r = block[h_name]
            print(f"  {h_name}: n={r['n']}, mean={r.get('mean')}, median={r.get('median')}, "
                  f"win={r.get('winRate')}, bench={r.get('benchMean')}, excess={r.get('excessPerDateMatched')}")
        results[name] = block

    os.makedirs(OUT_DIR, exist_ok=True)
    out_path = os.path.join(OUT_DIR, "signal_study_results.json")
    with open(out_path, "w", encoding="utf-8") as fh:
        json.dump({
            "generatedAt": time.strftime("%Y-%m-%dT%H:%M:%S"),
            "context": "V8 거래대금 상위 + 저항선 돌파 — trend_breakout_v1 대비 거래대금 필터의 "
                       "incremental value 분리 측정용 이벤트 스터디. 첫 실행 결과 그대로.",
            "panelRows": int(len(df)),
            "conventions": {
                "observed": "거래대금 상위 종목군 + 차트상 저항선 돌파 매수 (컨셉만 확인)",
                "unspecifiedProvisional": {
                    "resistance": "직전 20거래일 최고가(Donchian high, 당일 제외) — "
                                  "trend_breakout_v1과 동일 (기간은 ASSUMPTION)",
                    "trigger": "Close[t]>dh[t] AND Close[t-1]<=dh[t-1] 엣지",
                    "pullbackDepthVolumeDryUp": "조건 없음 — 미확정 항목 유지",
                    "amountTop": "당일 거래대금 패널 백분위 >= 0.70 (V7과 동일 임시)",
                    "comparison": "variantA(브레이크아웃만)=trend_breakout_v1 신호 등가, "
                                  "variantB(+거래대금 상위30%) 차이가 incremental value",
                },
                "data": "A2a OHLC 캐시(읽기 전용) + a4 패널 total_amount",
                "forwardReturn": "t 종가 → t+h째 행 종가 (A2a adjusted, close-to-close)",
                "benchmark": "같은 날 유니버스 전체 종목 동일가중 (신호 종목 포함)",
                "pitNote": "실거래 계약은 signal t → t+1 open 체결(engine contract)이므로 이벤트 "
                           "스터디 근사치. 엔진 기반 trend_breakout_v1 성과는 "
                           "reports/2026-08-15-trend-breakout-v1-* 참고.",
            },
            "results": results,
        }, fh, ensure_ascii=False, indent=2)
    print("saved:", out_path)


if __name__ == "__main__":
    main()
