#!/usr/bin/env python
"""V5 다이버전스 최소 signal study (전략 엔진 미연결 — 이벤트 스터디만).

가설[V5, OBSERVED]: 최근 5거래일 누적 수급에서 외국인 순매수 + 기관 순매도(또는
반대 방향)인 종목. audit.md(findings/v5-divergence) 결론 A에 따라 기존 a4 연구
패널로 첫 실행을 그대로 보고한다 — threshold 튜닝 없이 부호 조건 한 번만 적용.

정의 (audit.md B항목 중 사전 확정분):
  - 외국인 순매수  = foreign_nb_5d > 0   (외국인+기타외국인, 데이터셋 정의)
  - 기관 순매도    = inst_nb_5d < 0      (8카테고리 합, build_a4_research_dataset.py 정의)
  - divA: 외국인 매수 + 기관 매도 / divB: 외국인 매도 + 기관 매수 (반대 방향)
  - 임계값 없음(부호만). 창은 패널 rolling(5, min_periods=1) 그대로.

측정: 신호 발생일 t 종가 기준 T+1/T+5/T+10/T+20 close-to-close 수익률(A2a adjusted).
  벤치마크 = 같은 날 같은 패널 전체 종목 동일가중 평균. 초과수익은 날짜별
  (신호그룹 평균 − 유니버스 평균)을 날짜 동일가중 평균한 값.
  주의: 실거래 계약은 signal t → t+1 open 체결(engine/execution)이라 본 수치는
  이벤트 스터디 근사치다(t→t+1 구간을 전부 포함). 신호 겹침(중복 카운트) 있음.

  python v5_divergence_signal_study.py
"""
import json
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
PANEL_PATH = os.path.join(REPO_ROOT, "research", "strategy-lab", "data", "a4", "a4-research-dataset.parquet")
OUT_DIR = os.path.join(REPO_ROOT, "research", "strategy-lab", "findings", "v5-divergence")
HORIZONS = {"T+1": 1, "T+5": 5, "T+10": 10, "T+20": 20}
DIRECTIONS = {
    "divA_foreignBuy_instSell": lambda f, i: (f > 0) & (i < 0),
    "divB_foreignSell_instBuy": lambda f, i: (f < 0) & (i > 0),
}


def load_panel():
    cols = ["ticker", "date", "foreign_nb_5d", "inst_nb_5d", "close"]
    df = pd.read_parquet(PANEL_PATH, columns=cols)
    df = df.sort_values(["ticker", "date"]).reset_index(drop=True)
    g = df.groupby("ticker")["close"]
    for h_name, h in HORIZONS.items():
        df[f"fwd_{h}"] = g.transform(lambda s: s.shift(-h) / s - 1)
    return df


def stats_for(sig, bench_by_date, fwd_col):
    """sig: 신호 행들. bench_by_date: date -> 유니버스 동일가청 평균."""
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

    f, i = df["foreign_nb_5d"], df["inst_nb_5d"]
    results = {}
    for dir_name, cond_fn in DIRECTIONS.items():
        mask = cond_fn(f, i)
        sig_all = df[mask]
        print(f"{dir_name}: signal rows={len(sig_all)} (raw, before fwd availability)")
        results[dir_name] = {"signalRowsRaw": int(len(sig_all))}
        for h_name, h in HORIZONS.items():
            fwd_col = f"fwd_{h}"
            # 벤치마크: 같은 날 패널 전체(신호 포함) 동일가중, fwd 유효 행만
            bench = df.dropna(subset=[fwd_col]).groupby("date")[fwd_col].mean()
            results[dir_name][h_name] = stats_for(sig_all, bench, fwd_col)
            r = results[dir_name][h_name]
            print(f"  {h_name}: n={r['n']}, mean={r.get('mean')}, median={r.get('median')}, "
                  f"win={r.get('winRate')}, bench={r.get('benchMean')}, excess={r.get('excessPerDateMatched')}")

    os.makedirs(OUT_DIR, exist_ok=True)
    out_path = os.path.join(OUT_DIR, "signal_study_results.json")
    with open(out_path, "w", encoding="utf-8") as fh:
        json.dump({
            "generatedAt": time.strftime("%Y-%m-%dT%H:%M:%S"),
            "context": "V5 다이버전스(외국인 5d 순매수 + 기관 5d 순매도 및 반대 방향) 최소 "
                       "signal study — 엔진 미연결 이벤트 스터디. threshold 부호 고정, 첫 실행 "
                       "결과 그대로. 패널: data/a4/a4-research-dataset.parquet.",
            "panelRows": int(len(df)),
            "conventions": {
                "institution": "inst_nb_5d = 금융투자·보험·투신·사모·은행·기타금융·연기금·기타법인 8개 합 (데이터셋 기존 정의)",
                "threshold": "부호만 (>0 / <0), 규모 임계 없음",
                "window": "foreign_nb_5d/inst_nb_5d = 패널 rolling(5, min_periods=1)",
                "forwardReturn": "t 종가 → t+h째 패널 행 종가 (A2a adjusted, close-to-close)",
                "benchmark": "같은 날 패널 전체 종목 동일가중 (신호 종목 포함)",
                "pitNote": "실거래 계약은 signal t → t+1 open 체결이므로 본 수치는 이벤트 스터디 근사치",
            },
            "results": results,
        }, fh, ensure_ascii=False, indent=2)
    print("saved:", out_path)


if __name__ == "__main__":
    main()
