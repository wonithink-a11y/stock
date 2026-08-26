#!/usr/bin/env python
"""PEAD 분기 SUE 전면수집 결과의 OOS(TRAIN/VALID/TEST) 검증 - 파일럿
(findings/pead-quarterly-pilot-2026-08.md)이 전체 기간 하나로만 IC를 봐서
사후적으로 유리한 구간을 골랐을 위험(이 프로젝트가 REV20·Opening Fade에서
이미 겪은 "OOS 반전" 패턴)이 있었다. `build_quarterly_earnings_panel.py`
전면 수집이 끝나면 이 스크립트로 공시월 타임라인을 CAND1/Opening Fade와
같은 60/15/25% 시간분할(TRAIN/VALID/TEST)로 나눠 같은 IC가 전 구간에서
유지되는지 확인한다 - `run_strategy_validation.py`의 "TRAIN에서만 스윕,
VALID·TEST는 고정 설정을 보고만 한다"는 원칙과 같되, PEAD는 스윕할
파라미터가 없어(SUE 정의·T+20/T+60 둘 다 이미 고정) 세 구간 다 같은
decile_analysis()를 그대로 돌려 비교만 한다.

수집이 끝나기 전에도 부분 패널로 코드 경로를 미리 검증할 수 있다(결과
자체는 무의미 - 티커 알파벳순 수집이라 초반 종목에 편향).

  python analyze_pead_quarterly_oos.py
"""
import json
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import pandas as pd  # noqa: E402

from engine.data.a2aProvider import A2aProvider  # noqa: E402
from engine.runner import _drop_suspension_rows  # noqa: E402
from pead_quarterly_pilot import compute_sue, build_events, decile_analysis, HORIZONS, MIN_TURNOVER  # noqa: E402

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
PANEL_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                          "data", "quarterly-earnings", "quarterly-earnings-panel.jsonl")
START, END = "2016-01-01", "2026-08-14"
SPLIT_FRACTIONS = {"TRAIN": 0.60, "VALID": 0.15, "TEST": 0.25}


def load_panel():
    rows = []
    with open(PANEL_PATH, encoding="utf-8") as f:
        for line in f:
            rows.append(json.loads(line))
    return pd.DataFrame(rows)


def split_by_month(events, fractions=SPLIT_FRACTIONS):
    events = events.copy()
    events["month"] = events["availableFrom"].str.slice(0, 7)
    months = sorted(events["month"].unique())
    n = len(months)
    n_train = int(round(n * fractions["TRAIN"]))
    n_valid = int(round(n * fractions["VALID"]))
    train_months = set(months[:n_train])
    valid_months = set(months[n_train:n_train + n_valid])
    test_months = set(months[n_train + n_valid:])
    return {
        "TRAIN": events[events["month"].isin(train_months)],
        "VALID": events[events["month"].isin(valid_months)],
        "TEST": events[events["month"].isin(test_months)],
    }, {"TRAIN": sorted(train_months), "VALID": sorted(valid_months), "TEST": sorted(test_months)}


def main():
    t0 = time.time()
    if not os.path.exists(PANEL_PATH):
        print(f"패널 없음: {PANEL_PATH} - build_quarterly_earnings_panel.py 먼저 실행")
        sys.exit(1)

    panel = load_panel()
    print(f"panel loaded: {len(panel)} quarterly records, "
          f"{panel['ticker'].nunique()} tickers ({time.time()-t0:.0f}s)")

    sue_df = compute_sue(panel)
    n_valid_sue = sue_df["sue"].notna().sum()
    print(f"SUE computable: {n_valid_sue}/{len(sue_df)}")

    tickers = sorted(panel["ticker"].unique())
    a2a = A2aProvider(repo_root=REPO_ROOT, use_cache=True)
    bars_raw = a2a.load(tickers, START, END, universe_hash="pead-quarterly-oos")
    bars_by_ticker = {t: _drop_suspension_rows(df) for t, df in bars_raw.items()}
    print(f"bars loaded: {len(bars_by_ticker)} tickers ({time.time()-t0:.0f}s)")

    events = build_events(sue_df, bars_by_ticker)
    eligible = events[events["turnover20"] >= MIN_TURNOVER]
    print(f"events: {len(events)}, eligible: {len(eligible)}")

    splits, split_months = split_by_month(events)
    eligible_splits, _ = split_by_month(eligible)

    results = {}
    for split_name in ("TRAIN", "VALID", "TEST"):
        for h in HORIZONS:
            for label, df_ in [("allEvents", splits[split_name]), ("eligibleLiquidity", eligible_splits[split_name])]:
                key = f"{split_name}_t{h}_{label}"
                results[key] = decile_analysis(df_, f"ret_t{h}")
                r = results[key]
                print(f"  {key}: IC={r['meanMonthlyIC']} t={r['icTstat']} "
                      f"top-bottom={r['topMinusBottomDecile']} months={r['monthsUsed']} n={r['nEvents']}")

    out_dir = os.path.join(REPO_ROOT, "research", "strategy-lab", "reports",
                            "2026-08-26-pead-quarterly-oos")
    os.makedirs(out_dir, exist_ok=True)
    out_path = os.path.join(out_dir, "pead-quarterly-oos.json")
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump({
            "generatedAt": time.strftime("%Y-%m-%dT%H:%M:%S"),
            "context": "PEAD 분기 SUE 전면수집 OOS(TRAIN/VALID/TEST 60/15/25 시간분할) "
                       "검증. findings/pead-quarterly-pilot-2026-08.md 후속.",
            "splitMonths": split_months, "nEvents": len(events), "nEligible": len(eligible),
            "results": results,
        }, f, ensure_ascii=False, indent=2, default=str)
    print(f"\nsaved: {out_path} ({time.time()-t0:.0f}s)")


if __name__ == "__main__":
    main()
