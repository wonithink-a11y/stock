#!/usr/bin/env python
"""growth_screen_v1.py(TOP20/50/100 전부 기각) 후속 - "왜 안 되는가"를 파고드는
원인분석. 새 factor mining이 아니라 이미 기각된 실험의 사후 분해라 과적합
위험이 낮다(사용자 지시 2026-08-28). A(자산증가율TOP20)·B(매출증가율TOP20)·
C(영업이익증가율TOP20) 단일축과 2way·3way 교집합 7종의 수익률을 비교해,
"3개 조건 전부 요구(A∩B∩C)"가 실제로 단일축보다 나은지, 아니면 교집합
자체가 표본을 지나치게 좁혀 노이즈를 키우는지 확인한다.

growth_screen_v1.py의 데이터 로드·selection_at()을 그대로 재사용(TOP_N=20,
동일 유니버스·가격·비용가정) - 새 계산·API 호출 없음. debt filter는 이
분해에서 적용하지 않는다(원 실험이 이미 "부채필터가 오히려 악화"를
확인했으므로, 여기서는 A/B/C 자체의 신호만 본다).

  python growth_screen_venn_decomposition.py
"""
import json
import os

import numpy as np

from growth_screen_v1 import (
    load_shared_data, selection_at, compute_metrics, REBAL_DATES, TOP_N, COST_RT_BPS,
)

BUCKETS = ["A_asset", "B_revenue", "C_opProfit", "AandB", "AandC", "BandC", "AandBandC"]


def bucket_members(sel, bucket):
    A, B, C = set(sel["assetTop20"]), set(sel["revenueTop20"]), set(sel["opProfitTop20"])
    sets = {"A_asset": A, "B_revenue": B, "C_opProfit": C,
            "AandB": A & B, "AandC": A & C, "BandC": B & C, "AandBandC": A & B & C}
    return sorted(sets[bucket])


def run_bucket(selections, price_lookup, bucket, cost_bps=COST_RT_BPS):
    periods = []
    for k in range(len(selections) - 1):
        t, t1 = selections[k]["as_of"], selections[k + 1]["as_of"]
        members = bucket_members(selections[k], bucket)
        rets, held = [], []
        for tk in members:
            p0, p1 = price_lookup.get((tk, t)), price_lookup.get((tk, t1))
            if p0 is None or p1 is None or p0 <= 0:
                continue
            rets.append(p1 / p0 - 1.0)
            held.append(tk)
        net = float(np.mean(rets)) - cost_bps / 1e4 if held else 0.0
        periods.append({"start": t, "end": t1, "ret": net, "n": len(held)})
    return periods


def main():
    a3, all_tickers, names, price_lookup, outlier_info = load_shared_data()

    print("computing selections at each as_of (TOP20, no debt filter)...")
    selections = [selection_at(a3, all_tickers, names, price_lookup, d, top_n=TOP_N) for d in REBAL_DATES]
    for sel in selections:
        print(f"  {sel['as_of']}: universe={sel['universeSize']} "
              f"A={len(sel['assetTop20'])} B={len(sel['revenueTop20'])} C={len(sel['opProfitTop20'])} "
              f"A∩B∩C={len(sel['intersection'])}")

    print("\n=== 7-way Venn decomposition backtest (동일가중, 30bps, 부채필터 없음) ===")
    results = {}
    for bucket in BUCKETS:
        periods = run_bucket(selections, price_lookup, bucket)
        metrics = compute_metrics(periods)
        results[bucket] = {"metrics": metrics, "periods": periods}
        print(f"  {bucket:>12}: CAGR={metrics.get('cagr')} MDD={metrics.get('mdd')} "
              f"Sharpe={metrics.get('sharpe')} avgHoldings={metrics.get('avgHoldings')} "
              f"nPeriods={metrics.get('nPeriods')}")

    out_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "reports",
                            "2026-08-28-growth-screen-venn-decomposition")
    os.makedirs(out_dir, exist_ok=True)
    out_path = os.path.join(out_dir, "growth-screen-venn-decomposition.json")
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump({
            "context": "growth_screen_v1.py(TOP20 A∩B∩C+부채필터, CAGR -14.12%, 기각) 후속 원인분석 - "
                       "A/B/C 단일축과 2way/3way 교집합 7종 비교. 부채필터는 적용하지 않음(원 실험이 "
                       "이미 이 필터가 도움 안 됨을 확인).",
            "buckets": results,
        }, f, ensure_ascii=False, indent=2, default=str)
    print("\nsaved:", out_path)


if __name__ == "__main__":
    main()
