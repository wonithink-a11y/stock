# -*- coding: utf-8 -*-
"""연도별 기여도 + 트레이드 레벨 진단 (Stage 4-3 검증용)."""
import sys
sys.path.insert(0, r"research\strategy-lab\futures")
import numpy as np
import pandas as pd
from stage4_3_basis_backtest import load, build_signals, run_strategy, cost

fr = load()
basis = fr["TDD_CLSPRC"] - fr["SPOT_PRC"]
sig = {k: pd.Series(build_signals(basis.to_numpy(), p), index=fr.index)
       for k, p in {"A": 0.20, "B": 0.30, "C": 0.40}.items()}
THRESH = {"A": 0.20, "B": 0.30, "C": 0.40}

# 모든 strat/period에 대해 트레이드 gross/연도별 net 수익률 기여
for sname in ["A", "B", "C"]:
    for hold in [5, 20]:
        trades, eqn, eqg, ts, exp = run_strategy(fr, sig[sname], hold)
        rows = []
        for t in trades:
            if t["gross"] is None:
                continue
            net = t["gross"] - cost(t["entry_px"]) - cost(t["exit_px"])
            rows.append((pd.Timestamp(t["entry_ts"]).year, net, t["gross"]))
        df = pd.DataFrame(rows, columns=["year", "net", "gross"])
        by = df.groupby("year")[["net"]].sum()
        total = by["net"].sum()
        print(f"[{sname} h{hold}] 전체 net={total:,.0f}")
        print("  연도별 net 기여:", by.round(0).to_dict()["net"])
        # 2025~ 비중
        tail = df[df.year >= 2025]["net"].sum()
        print(f"  2025~ 기여={tail:,.0f} ({tail/total*100:.0f}%)" if total else f"  2025~ 기여={tail:,.0f}")