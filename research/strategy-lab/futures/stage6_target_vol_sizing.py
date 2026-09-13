# -*- coding: utf-8 -*-
"""Stage 6: KOSPI200 선물 목표변동성(target vol) 연속 sizing (READ-ONLY 연구 산출물).

Stage 5-3(§9 제안 1) 후속 — 0/0.5/1x 이산(binary) sizing이 2010-2017(상승기)에서
수익 프리미엄을 잘라내던 한계를, threshold 없는 연속 함수로 완화할 수 있는지 검증.
데이터·신호·비용·기간 분리·look-ahead 금지는 Stage 5-3과 완전 동일(새 수집 없음).

- 신호: rv20(20일 rolling 연율화 실현변동성) 원값. Stage 5-1에서 이미 계산된 것 재사용
  (percentile이 아니라 raw level — 연속 sizing엔 순위가 아니라 크기가 필요하다).
- w(t) = min(target_vol / rv20(t-1), 1.0)  — 레버리지 확대 금지(Stage 5-3 제약 유지), 하한 0.
- target_vol 사전 지정(사후 탐색 아님, round number 2개만):
    15% — rv20 전체표본 median(15.2%)에 가장 가까운 round number이자 target-vol 전략의
          통상적 기준값(변동성 축소도 확대도 없는 "평균적" 노출을 겨냥)
    10% — 더 보수적인 통상값(비교용, threshold 최적화 아님 — 두 값 다 사전 라운드넘버)
- Stage 5-3의 A(0.5x)/B(0x) 이산 규칙과 나란히 비교해 "연속이 이산보다 2010-2017 수익
  프리미엄을 더 보존하는가"가 핵심 질문.
- 금지(미실행): target_vol 그리드서치·최적화, EMA/basis/OI 결합, Short, WFA/OOS, 타선물,
  새 데이터, production, commit.

    python research/strategy-lab/futures/stage6_target_vol_sizing.py
"""
from pathlib import Path

import numpy as np
import pandas as pd

from stage5_1_volatility_event_study import load, front_series, process, PERIODS
from stage5_3_sizing_backtest import (
    run_buyhold, metrics, decompose, COST_SIDE, MULT,
)

OUTDIR = Path(__file__).resolve().parent
TARGET_VOLS = {"tv15": 0.15, "tv10": 0.10}
W_CAP = 1.0


def run_target_vol(cts, rv20, target_vol):
    """w[t] = min(target_vol / rv20[t-1], W_CAP), rv20 NaN(warmup) → 1.0x.
    체결·비용 모형은 stage5_3.run_sizing과 동일(신호 t close → t+1 적용,
    |Δw|*COST_SIDE 편도 비용, 진입/청산 각 1편도 상당)."""
    o = cts["TDD_OPNPRC"].to_numpy(dtype=float)
    c = cts["TDD_CLSPRC"].to_numpy(dtype=float)
    idx = cts.index
    rv = rv20.reindex(idx).to_numpy(dtype=float)
    n = len(cts)
    if n < 2:
        return None

    w = np.full(n, np.nan)
    w[0] = 1.0
    for t in range(1, n):
        prev = rv[t - 1]
        w[t] = 1.0 if prev != prev else min(target_vol / prev, W_CAP)

    cap = float(cts["TDD_CLSPRC"].max()) * MULT
    nav = np.empty(n)
    nav[0] = cap - COST_SIDE
    cost = COST_SIDE
    resizes = 0
    for t in range(1, n):
        pnl = w[t - 1] * (o[t] - c[t - 1]) + w[t] * (c[t] - o[t])
        pnl *= MULT
        c_up = abs(w[t] - w[t - 1]) * COST_SIDE
        if w[t] != w[t - 1]:
            resizes += 1
        nav[t] = nav[t - 1] + pnl - c_up
        cost += c_up
    cost += w[-1] * COST_SIDE
    nav[-1] -= w[-1] * COST_SIDE
    return dict(nav=nav, w=w, idx=idx, cap=cap, cost=cost, resizes=resizes)


def main():
    df = load()
    fr = front_series(df)
    d, fwd, mae = process(fr)
    cts_all = fr[~fr["roll"]].copy()
    rv20 = d["rv20"]

    print("== Stage 6: 목표변동성 연속 sizing (Stage 5-3 이산 sizing과 비교) ==")
    rows, dec_rows = [], []
    for pname, (ps, pe) in PERIODS.items():
        sub = cts_all[cts_all.index >= pd.Timestamp(ps)] if ps else cts_all
        if pe:
            sub = sub[sub.index <= pd.Timestamp(pe)]
        if len(sub) < 3:
            continue
        bh = run_buyhold(sub)
        m = metrics(bh)
        m |= dict(strategy="buyhold", period=pname, status="OK")
        rows.append(m)
        for key, tv in TARGET_VOLS.items():
            bt = run_target_vol(sub, rv20, tv)
            mb = metrics(bt)
            mb |= dict(strategy=f"sizing_{key}", period=pname, status="OK")
            rows.append(mb)
            dc = decompose(bt, bh)
            dc |= dict(strategy=f"sizing_{key}", period=pname)
            dec_rows.append(dc)

    bt_out = pd.DataFrame(rows)
    cols = ["strategy", "period", "years", "bars", "capital_krw",
            "cagr_net", "sharpe_net", "sortino_net", "calmar_net", "mdd_net",
            "win_rate", "profit_factor", "resize_count", "n_segments",
            "trades_per_year", "total_cost_krw", "total_cost_pct_cap",
            "avg_exposure", "time_in_market", "final_equity_krw", "status"]
    bt_out = bt_out[[c for c in cols if c in bt_out.columns]].sort_values(["period", "strategy"])
    bt_out.to_csv(OUTDIR / "futures-stage6-target-vol-backtest.csv", index=False, encoding="utf-8-sig")

    dec_out = pd.DataFrame(dec_rows).sort_values(["period", "strategy"])
    dec_out.to_csv(OUTDIR / "futures-stage6-target-vol-decomposition.csv", index=False, encoding="utf-8-sig")

    import json
    (OUTDIR / "futures-stage6-target-vol-backtest.json").write_text(
        json.dumps({"backtest": bt_out.to_dict(orient="records"),
                    "decomposition": dec_out.to_dict(orient="records"),
                    "config": {"target_vols": TARGET_VOLS, "w_cap": W_CAP,
                               "cost_side_krw": COST_SIDE}},
                   ensure_ascii=False, indent=2), encoding="utf-8")

    pd.set_option("display.width", 260)
    pd.set_option("display.max_columns", 50)
    print("\n--- 백테스트 (B&H vs Stage5-3 이산 vs Stage6 연속) ---")
    show = bt_out[["strategy", "period", "cagr_net", "sharpe_net", "sortino_net",
                   "mdd_net", "calmar_net", "avg_exposure", "resize_count", "total_cost_krw"]]
    print(show.to_string(index=False))
    print("\n--- B&H 대비 분해(delta) ---")
    print(dec_out.to_string(index=False))
    print(f"\n저장: futures-stage6-target-vol-backtest.{{csv,json}}")


def selftest() -> int:
    fails = []

    def ck(name, cond):
        print(("ok   " if cond else "FAIL ") + name)
        if not cond:
            fails.append(name)

    idx = pd.date_range("2020-01-01", periods=30, freq="B")
    cts = pd.DataFrame({"TDD_OPNPRC": 100.0 + np.arange(30) * 0.1,
                        "TDD_CLSPRC": 100.2 + np.arange(30) * 0.1}, index=idx)
    rv = pd.Series(np.full(30, 0.30), index=idx)  # 항상 목표(0.15)의 2배 → w=0.5 기대
    bt = run_target_vol(cts, rv, 0.15)
    ck("w[0]=1.0(진입)", bt["w"][0] == 1.0)
    ck("w[1:] 전부 0.5(target/rv=0.5, cap 미적용)", np.allclose(bt["w"][1:], 0.5))

    rv_calm = pd.Series(np.full(30, 0.05), index=idx)  # target/rv=3.0 → cap 1.0
    bt2 = run_target_vol(cts, rv_calm, 0.15)
    ck("저변동시 W_CAP(1.0)으로 clip", np.allclose(bt2["w"][1:], 1.0))

    total = 3
    print(f"\nselftest {total - len(fails)}/{total}" + ("" if not fails else f"  FAILED: {fails}"))
    return 1 if fails else 0


if __name__ == "__main__":
    import sys
    if "--selftest" in sys.argv:
        raise SystemExit(selftest())
    main()
