#!/usr/bin/env python
"""V1 MA 5/25/75 Pullback 최소 signal study (전략 엔진 미연결 — 이벤트 스터디만).

가설[V1, OBSERVED]: 5·25·75일 이동평균 사용. 상승 추세에서 주가가 5일선 아래로
조정 후 종가 기준 재돌파 시 매수. 하락 추세는 매도만(롱온리 스터디라 신호 없음
처리). 손익비 1:3은 RiskSpec/execution 연결(다음 단계)에서 다룬다 — 본 스터디
범위 밖.

[UNSPECIFIED] → 임시 채택 (첫 실행 고정, 튜닝 없음 — 이 구분을 문서에 그대로 남긴다):
  - "상승 추세" = MA5 > MA25 > MA75 정렬 (영상이 쓴 지표 집합 안에서의 최소 정의)
  - "조정 허용폭" 조건 없음 (재돌파 엣지 자체가 전일 종가 <= MA5를 함의)
  - 재돌파 트리거: close[t] > MA5[t] AND close[t-1] <= MA5[t-1], 추세 조건은 t에만 적용

측정: v5_divergence_signal_study.py와 동일 관례 — 같은 a4 패널(V1은 close만 사용),
T+1/5/10/20 close-to-close(A2a adjusted), 같은 날 패널 전체 동일가중 벤치마크,
날짜별 초과수익의 날짜 동일가중 평균. 실거래 계약(signal t → t+1 open)과의 차이는
v5와 같은 근사치 한계.

  python v1_ma_pullback_signal_study.py
"""
import json
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import pandas as pd  # noqa: E402

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
PANEL_PATH = os.path.join(REPO_ROOT, "research", "strategy-lab", "data", "a4", "a4-research-dataset.parquet")
OUT_DIR = os.path.join(REPO_ROOT, "research", "strategy-lab", "findings", "v1-ma-pullback")
HORIZONS = {"T+1": 1, "T+5": 5, "T+10": 10, "T+20": 20}
MA_FAST, MA_MID, MA_SLOW = 5, 25, 75


def load_panel():
    df = pd.read_parquet(PANEL_PATH, columns=["ticker", "date", "close"])
    df = df.sort_values(["ticker", "date"]).reset_index(drop=True)
    g = df.groupby("ticker")["close"]
    for n in (MA_FAST, MA_MID, MA_SLOW):
        df[f"ma{n}"] = g.transform(lambda s: s.rolling(n, min_periods=n).mean())
    for h_name, h in HORIZONS.items():
        df[f"fwd_{h}"] = g.transform(lambda s: s.shift(-h) / s - 1)
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
    df = load_panel()
    print(f"panel rows={len(df)}, tickers={df['ticker'].nunique()}, "
          f"dates={df['date'].nunique()} ({df['date'].min()}~{df['date'].max()}) ({time.time()-t0:.0f}s)")

    uptrend = (df["ma5"] > df["ma25"]) & (df["ma25"] > df["ma75"])
    prev_close = df.groupby("ticker")["close"].shift(1)
    prev_ma5 = df.groupby("ticker")["ma5"].shift(1)
    signal_mask = uptrend & (df["close"] > df["ma5"]) & (prev_close <= prev_ma5)

    sig_all = df[signal_mask]
    print(f"signal rows={len(sig_all)} ({time.time()-t0:.0f}s)")

    results = {}
    results["signalRowsRaw"] = int(len(sig_all))
    for h_name, h in HORIZONS.items():
        fwd_col = f"fwd_{h}"
        bench = df.dropna(subset=[fwd_col]).groupby("date")[fwd_col].mean()
        results[h_name] = stats_for(sig_all, bench, fwd_col)
        r = results[h_name]
        print(f"  {h_name}: n={r['n']}, mean={r.get('mean')}, median={r.get('median')}, "
              f"win={r.get('winRate')}, bench={r.get('benchMean')}, excess={r.get('excessPerDateMatched')}")

    os.makedirs(OUT_DIR, exist_ok=True)
    out_path = os.path.join(OUT_DIR, "signal_study_results.json")
    with open(out_path, "w", encoding="utf-8") as fh:
        json.dump({
            "generatedAt": time.strftime("%Y-%m-%dT%H:%M:%S"),
            "context": "V1 MA 5/25/75 Pullback 최소 signal study — 엔진 미연결 이벤트 "
                       "스터디. [OBSERVED] 규칙만 구현, threshold 튜닝 없음, 첫 실행 결과 "
                       "그대로.",
            "panelRows": int(len(df)),
            "conventions": {
                "observed": "MA5/25/75(close SMA), 상승 추세 중 5일선 아래 조정 후 종가 "
                            "재돌파 매수, 하락 추세 매수 없음",
                "unspecifiedProvisional": {
                    "uptrend": "MA5>MA25>MA75 (신호일 t에만 요구)",
                    "trigger": "close[t]>ma5[t] AND close[t-1]<=ma5[t-1]",
                    "adjustDepthFilter": "없음",
                },
                "rewardRisk13": "RiskSpec 연결 단계 항목 — 본 스터디 범위 밖",
                "forwardReturn": "t 종가 → t+h째 패널 행 종가 (A2a adjusted, close-to-close)",
                "benchmark": "같은 날 패널 전체 종목 동일가중 (신호 종목 포함)",
                "pitNote": "실거래 계약은 signal t → t+1 open 체결이므로 이벤트 스터디 근사치",
            },
            "results": results,
        }, fh, ensure_ascii=False, indent=2)
    print("saved:", out_path)


if __name__ == "__main__":
    main()
