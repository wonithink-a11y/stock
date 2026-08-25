#!/usr/bin/env python
"""pbr_value_v1(baseline, 매달 top-30 완전 재선정) vs pbr_value_v1_dropout
(Qlib TopkDropoutStrategy 방식, 매달 최대 nDrop=3개만 교체) - 같은 MTM
방법론(pbr_vs_ew_monthly_mtm.py의 run_and_measure(), 월별 시가평가)으로
공정 비교한다. run_pbr_value_v1.py가 쓰는 realized-pnl-at-exit-event
방식은 안 쓴다 - 그 방식은 연속보유 병합 포지션의 손익을 마지막 청산일이
속한 해에 몰아 왜곡한다는 게 이미 밝혀졌다(2026-08-22 발견, CLAUDE.md).

  python run_pbr_dropout_vs_baseline_mtm.py
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
    print(f"=== PBR baseline vs dropout(nDrop=3), monthly MTM, {START} ~ {END} ===")
    baseline = run_and_measure("pbr_value_v1")
    dropout = run_and_measure("pbr_value_v1_dropout")

    cagr_gap = round(dropout["resultTable"]["cagr"] - baseline["resultTable"]["cagr"], 4)
    sharpe_gap = None
    if baseline["resultTable"]["sharpe"] is not None and dropout["resultTable"]["sharpe"] is not None:
        sharpe_gap = round(dropout["resultTable"]["sharpe"] - baseline["resultTable"]["sharpe"], 4)

    result = {
        "period": f"{START} ~ {END}", "method": "monthly mark-to-market equity curve",
        "pbr_value_v1_baseline": baseline, "pbr_value_v1_dropout": dropout,
        "dropoutMinusBaseline": {"cagr": cagr_gap, "sharpe": sharpe_gap},
    }
    print("\n", json.dumps(result, ensure_ascii=False, indent=2, default=str))

    out_dir = os.path.join(REPO_ROOT, "research", "strategy-lab", "reports",
                            "2026-08-26-pbr-dropout-vs-baseline-mtm")
    os.makedirs(out_dir, exist_ok=True)
    out_path = os.path.join(out_dir, "pbr-dropout-vs-baseline-mtm.json")
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump({
            "generatedAt": time.strftime("%Y-%m-%dT%H:%M:%S"),
            "context": "Qlib TopkDropoutStrategy(n_drop) 방식이 pbr_value_v1 회전율을 줄여 "
                       "net 성과를 개선하는지 검증. selection.json 하나만 다르고(dropout: "
                       "매달 최대 3종목 교체 vs baseline: 매달 top-30 완전 재선정) 엔진·비용·"
                       "portfolio 설정은 완전히 동일(strategies/pbr_value_v1_dropout/policy.json). "
                       "findings/github-strategy-sources-usability-2026-08.md 후속.",
            "result": result,
        }, f, ensure_ascii=False, indent=2, default=str)
    print("\nsaved:", out_path)


if __name__ == "__main__":
    main()
