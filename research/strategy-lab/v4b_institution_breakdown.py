#!/usr/bin/env python
"""V4b 기관 카테고리별 breakdown signal study.

V5(findings/v5-divergence)가 기관을 8카테고리 합계로만 봤던 것을 개별로 쪼갠다.
audit.md B-1의 8개 카테고리 중 기타법인을 뺀 7개(금융투자·보험·투신·사모·은행·
기타금융·연기금) 각각에 대해 V5와 동일한 방법론을 적용한다:
  - 신호 = 해당 카테고리 5일 누적 순매수 부호(rolling 5, min_periods=1, threshold 없음)
  - 두 방향 모두 보고: nb5d>0(순매수) / nb5d<0(순매도) - V5의 divA/divB처럼
  - 측정: T+1/5/10/20 close-to-close(A2a), 같은 날 패널 전체 동일가중 벤치마크,
    날짜별 초과수익의 날짜 동일가중 평균

연기금은 주목 대상으로 지정됐으나 결론에는 숫자만 기록한다(통념 개입 없음).

  python v4b_institution_breakdown.py
"""
import json
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import pandas as pd  # noqa: E402

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
PANEL_PATH = os.path.join(REPO_ROOT, "research", "strategy-lab", "data", "a4", "a4-research-dataset.parquet")
OUT_DIR = os.path.join(REPO_ROOT, "research", "strategy-lab", "findings", "v4b-institution-breakdown")
HORIZONS = {"T+1": 1, "T+5": 5, "T+10": 10, "T+20": 20}
CATEGORIES = ["금융투자", "보험", "투신", "사모", "은행", "기타금융", "연기금"]
DIRECTIONS = {"netBuy5d_pos": ("gt",), "netSell5d_neg": ("lt",)}


def load_panel():
    cols = ["ticker", "date", "close"] + [f"net_{c}" for c in CATEGORIES]
    df = pd.read_parquet(PANEL_PATH, columns=cols)
    df = df.sort_values(["ticker", "date"]).reset_index(drop=True)
    g = df.groupby("ticker")["close"]
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
    print(f"panel rows={len(df)}, tickers={df['ticker'].nunique()} ({time.time()-t0:.0f}s)")

    results = {}
    for cat in CATEGORIES:
        col = f"net_{cat}"
        nb5d = df.groupby("ticker")[col].transform(lambda s: s.fillna(0).rolling(5, min_periods=1).sum())
        block = {}
        for dir_name, (op,) in DIRECTIONS.items():
            mask = (nb5d > 0) if op == "gt" else (nb5d < 0)
            sig_all = df[mask]
            sub = {dir_name: {"signalRowsRaw": int(len(sig_all))}}
            for h_name, h in HORIZONS.items():
                fwd_col = f"fwd_{h}"
                bench = df.dropna(subset=[fwd_col]).groupby("date")[fwd_col].mean()
                sub[dir_name][h_name] = stats_for(sig_all, bench, fwd_col)
                r = sub[dir_name][h_name]
                print(f"{cat}/{dir_name} {h_name}: n={r['n']}, excess={r.get('excessPerDateMatched')}, "
                      f"win={r.get('winRate')}")
            block.update(sub)
        results[cat] = block

    os.makedirs(OUT_DIR, exist_ok=True)
    out_path = os.path.join(OUT_DIR, "breakdown_results.json")
    with open(out_path, "w", encoding="utf-8") as fh:
        json.dump({
            "generatedAt": time.strftime("%Y-%m-%dT%H:%M:%S"),
            "context": "V4b 기관 카테고리별 breakdown - V5 방법론(5일 누적 부호, T+1/5/10/20 "
                       "초과수익)을 7개 카테고리 개별 적용. threshold 없음, 첫 실행 결과 그대로.",
            "categories": CATEGORIES,
            "excludedNote": "기타법인 제외(audit.md B-1 8개 중 7개) - V5 합계 정의와의 차이는 "
                            "합계=7개+기타법인임으로 역산 가능",
            "conventions": {
                "signal": "해당 카테고리 rolling(5,min_periods=1) 순매수합 부호",
                "forwardReturn": "t 종가 → t+h째 행 종가 (A2a adjusted, close-to-close)",
                "benchmark": "같은 날 패널 전체 종목 동일가중 (신호 종목 포함)",
                "pitNote": "실거래 계약은 signal t → t+1 open 체결이므로 이벤트 스터디 근사치",
            },
            "results": results,
        }, fh, ensure_ascii=False, indent=2)
    print("saved:", out_path)


if __name__ == "__main__":
    main()
