#!/usr/bin/env python
"""pbr_value_v1(baseline) vs dropout vs maxexcl vs combined(dropout+maxexcl) -
같은 MTM 방법론(pbr_vs_ew_monthly_mtm.py의 run_and_measure())으로 4개 전략을
공정 비교한다. 두 실험(회전율제한·MAX제외)이 각각 CAGR을 개선했을 때 함께
적용하면 단순 합산인지, 겹쳐서 상쇄되는지, 초과 개선인지 확인.

  python run_pbr_combined_vs_components_mtm.py
"""
import json
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from pbr_vs_ew_monthly_mtm import run_and_measure  # noqa: E402

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
START, END = "2016-01-01", "2026-08-14"
STRATEGIES = ["pbr_value_v1", "pbr_value_v1_dropout", "pbr_value_v1_maxexcl", "pbr_value_v1_combined"]


def main():
    print(f"=== PBR baseline vs dropout vs maxexcl vs combined, monthly MTM, {START} ~ {END} ===")
    runs = {sid: run_and_measure(sid) for sid in STRATEGIES}

    base_cagr = runs["pbr_value_v1"]["resultTable"]["cagr"]
    base_sharpe = runs["pbr_value_v1"]["resultTable"]["sharpe"]
    dropout_gap = runs["pbr_value_v1_dropout"]["resultTable"]["cagr"] - base_cagr
    maxexcl_gap = runs["pbr_value_v1_maxexcl"]["resultTable"]["cagr"] - base_cagr
    combined_gap = runs["pbr_value_v1_combined"]["resultTable"]["cagr"] - base_cagr
    naive_sum_gap = dropout_gap + maxexcl_gap

    comparison = {
        "cagrGapVsBaseline": {
            "dropout": round(dropout_gap, 4), "maxexcl": round(maxexcl_gap, 4),
            "combined": round(combined_gap, 4),
            "naiveSumOfDropoutAndMaxexcl": round(naive_sum_gap, 4),
            "combinedMinusNaiveSum": round(combined_gap - naive_sum_gap, 4),
        },
    }
    if base_sharpe is not None:
        for sid, key in [("pbr_value_v1_dropout", "dropout"), ("pbr_value_v1_maxexcl", "maxexcl"),
                          ("pbr_value_v1_combined", "combined")]:
            s = runs[sid]["resultTable"]["sharpe"]
            comparison.setdefault("sharpeGapVsBaseline", {})[key] = round(s - base_sharpe, 4) if s is not None else None

    result = {"period": f"{START} ~ {END}", "method": "monthly mark-to-market equity curve",
              "runs": runs, "comparison": comparison}
    print("\n", json.dumps(result, ensure_ascii=False, indent=2, default=str))

    out_dir = os.path.join(REPO_ROOT, "research", "strategy-lab", "reports",
                            "2026-08-26-pbr-combined-vs-components-mtm")
    os.makedirs(out_dir, exist_ok=True)
    out_path = os.path.join(out_dir, "pbr-combined-vs-components-mtm.json")
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump({
            "generatedAt": time.strftime("%Y-%m-%dT%H:%M:%S"),
            "context": "dropout(회전율제한)·maxexcl(MAX복권효과 제외) 두 실험을 함께 적용한 "
                       "combined이 단순 합산 가정과 얼마나 다른지 확인. 세션인수인계-"
                       "2026-08-26.md §5-1 후속.",
            "result": result,
        }, f, ensure_ascii=False, indent=2, default=str)
    print("\nsaved:", out_path)


if __name__ == "__main__":
    main()
