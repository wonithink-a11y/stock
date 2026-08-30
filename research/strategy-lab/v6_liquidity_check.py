#!/usr/bin/env python
"""V6 절대 유동성 조건 전/후 비교 signal study (오염 가능성 점검).

목적: V6 초과수익(T+20 +0.178%p)이 비용(30bp 왕복 관례)에 못 미치는 결론이 상대
유동성 오염 때문일 수 있는지 점검한다. 이 저장소의 선행 사례
(absolute_turnover_filter_validation.py - 상대 tercile 유동성 통제가 PBR·LOWMOM60을
잘못 기각시켰다가 절대 임계값으로 재검증하니 뒤집힌 전례)를 따른다.

변형 세 개 - threshold 쇼핑 없음, 1억원 단일 값(기존 값 그대로 재사용), 첫 실행:
  A_v6_original   : divBoth + 매집가+5% 필터 (적용 전, findings/v6-accrual-price와 동일)
  B_v6_plus_liq   : A + turnover20 >= 1억원 (절대 유동성 조건 추가)
  C_liq_only      : turnover20 >= 1억원 만 적용 (V6 필터 제거 - 유동성 자체의 alpha 분리)

turnover20 정의는 선례 그대로: (close*volume)의 rolling(20).mean() - a4 패널의
total_amount(당일 거래대금)와 동일 값이므로 패널 컬럼을 사용한다(min_periods=20,
선례의 .rolling(20) 기본 규약과 동일).

측정: v6 스터디와 동일 관례(T+1/5/10/20 A2a close-to-close, 같은 날 패널 동일가중
벤치마크, 날짜 매칭 초과수익).

  python v6_liquidity_check.py
"""
import json
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402

from v6_acc_price_signal_study import (  # noqa: E402
    PRICE_CAP,
    load_buy_flows,
    load_panel,
    stats_for,
)

HERE = os.path.dirname(os.path.abspath(__file__))
OUT_DIR = os.path.join(HERE, "findings", "v6-liquidity-check")
HORIZONS = {"T+1": 1, "T+5": 5, "T+10": 10, "T+20": 20}
MIN_TURNOVER = 100_000_000.0  # 1억원 - 기존 값 그대로 재사용(새로 고르지 않음)


def main():
    t0 = time.time()
    panel_cols = pd.read_parquet(
        os.path.join(REPO_ROOT := os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
                     "research", "strategy-lab", "data", "a4", "a4-research-dataset.parquet"),
        columns=["ticker", "date", "total_amount"])
    panel = load_panel()
    df = panel.merge(panel_cols, on=["ticker", "date"], how="left")
    df = df.sort_values(["ticker", "date"]).reset_index(drop=True)
    print(f"panel rows={len(df)} ({time.time()-t0:.0f}s)")

    g = df.groupby("ticker")
    turn20 = g["total_amount"].transform(lambda s: s.fillna(0).rolling(20, min_periods=20).mean())
    liq = turn20 >= MIN_TURNOVER

    flows = load_buy_flows()
    df = df.merge(flows, on=["ticker", "date"], how="left")
    g = df.groupby("ticker")
    amt5 = g["buyAmt"].transform(lambda s: s.fillna(0).rolling(5, min_periods=1).sum())
    vol5 = g["buyVol"].transform(lambda s: s.fillna(0).rolling(5, min_periods=1).sum())
    acc = np.where(vol5 > 0, amt5 / vol5, float("nan"))
    ratio = df["close"] / acc
    both = (df["foreign_nb_5d"] > 0) & (df["inst_nb_5d"] > 0)

    variants = {
        "A_v6_original": both & ratio.notna() & (ratio <= PRICE_CAP),
        "B_v6_plus_liq": both & ratio.notna() & (ratio <= PRICE_CAP) & liq,
        "C_liq_only": liq,
    }
    diag = {
        "liqRowsShareOfPanel": round(float(liq.mean()), 4),
        "v6RowsPassingLiqShare": round(float((variants["A_v6_original"] & liq).sum()
                                             / max(1, int(variants["A_v6_original"].sum()))), 4),
    }
    print("diag:", diag)

    results = {"diagnostics": diag}
    for name, mask in variants.items():
        sig_all = df[mask]
        block = {"signalRowsRaw": int(len(sig_all))}
        print(f"{name}: rows={len(sig_all)}")
        for h_name, h in HORIZONS.items():
            fwd_col = f"fwd_{h}"
            bench = df.dropna(subset=[fwd_col]).groupby("date")[fwd_col].mean()
            block[h_name] = stats_for(sig_all, bench, fwd_col)
            r = block[h_name]
            print(f"  {h_name}: n={r['n']}, mean={r.get('mean')}, win={r.get('winRate')}, "
                  f"excess={r.get('excessPerDateMatched')}")
        results[name] = block

    os.makedirs(OUT_DIR, exist_ok=True)
    out_path = os.path.join(OUT_DIR, "liquidity_check_results.json")
    with open(out_path, "w", encoding="utf-8") as fh:
        json.dump({
            "generatedAt": time.strftime("%Y-%m-%dT%H:%M:%S"),
            "purpose": "V6 상대 유동성 오염 점검 - 절대 유동성(turnover20>=1억) 전/후 비교",
            "conventions": {
                "liquidity": "turnover20 = rolling(20,min_periods=20) mean of daily 거래대금 >= "
                             "100,000,000 KRW (기존 값 그대로 재사용)",
                "observedV6": "[OBSERVED] 동시 순매수 + 매집가 대비 +5% 이내 (변경 없음)",
                "benchmark": "같은 날 패널 전체 종목 동일가중",
                "pitNote": "실거래 계약은 signal t → t+1 open 체결이므로 이벤트 스터디 근사치",
            },
            "results": results,
        }, fh, ensure_ascii=False, indent=2)
    print("saved:", out_path)


if __name__ == "__main__":
    main()
