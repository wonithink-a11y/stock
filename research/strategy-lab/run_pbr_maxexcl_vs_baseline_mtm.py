#!/usr/bin/env python
"""pbr_value_v1(baseline) vs pbr_value_v1_maxexcl(그 달 적격 유니버스 내
MAX5 상위 20% 종목을 대체 없이 제외) - 같은 MTM 방법론
(pbr_vs_ew_monthly_mtm.py의 run_and_measure())으로 공정 비교한다.

  python run_pbr_maxexcl_vs_baseline_mtm.py
"""
import json
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from pbr_vs_ew_monthly_mtm import run_and_measure  # noqa: E402

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
START, END = "2016-01-01", "2026-08-14"


def main():
    print(f"=== PBR baseline vs MAX-excl(top20%%), monthly MTM, {START} ~ {END} ===")
    baseline = run_and_measure("pbr_value_v1")
    maxexcl = run_and_measure("pbr_value_v1_maxexcl")

    cagr_gap = round(maxexcl["resultTable"]["cagr"] - baseline["resultTable"]["cagr"], 4)
    sharpe_gap = None
    if baseline["resultTable"]["sharpe"] is not None and maxexcl["resultTable"]["sharpe"] is not None:
        sharpe_gap = round(maxexcl["resultTable"]["sharpe"] - baseline["resultTable"]["sharpe"], 4)

    result = {
        "period": f"{START} ~ {END}", "method": "monthly mark-to-market equity curve",
        "pbr_value_v1_baseline": baseline, "pbr_value_v1_maxexcl": maxexcl,
        "maxexclMinusBaseline": {"cagr": cagr_gap, "sharpe": sharpe_gap},
    }
    print("\n", json.dumps(result, ensure_ascii=False, indent=2, default=str))

    out_dir = os.path.join(REPO_ROOT, "research", "strategy-lab", "reports",
                            "2026-08-26-pbr-maxexcl-vs-baseline-mtm")
    os.makedirs(out_dir, exist_ok=True)
    out_path = os.path.join(out_dir, "pbr-maxexcl-vs-baseline-mtm.json")
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump({
            "generatedAt": time.strftime("%Y-%m-%dT%H:%M:%S"),
            "context": "Nartea/Wu/Liu(2014) MAX효과(한국시장 실측)를 pbr_value_v1에 카운터팩추얼로 "
                       "적용 - baseline이 뽑은 top-30 중 그 달 적격 유니버스 내 MAX5 상위 20%인 "
                       "종목을 대체 없이 제외. selection.json 하나만 다르고 엔진·비용·portfolio "
                       "설정은 완전히 동일. findings/"
                       "github-literature-return-enhancement-candidates-2026-08.md 후속.",
            "result": result,
        }, f, ensure_ascii=False, indent=2, default=str)
    print("\nsaved:", out_path)


if __name__ == "__main__":
    main()
