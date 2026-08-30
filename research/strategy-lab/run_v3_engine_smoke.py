#!/usr/bin/env python
"""V3 Bollinger+RSI 엔진 스모크 드라이버 (소표본 ≤30종목, 전체 실행 금지).

engine.runner.run_smoke를 그대로 재사용하고, 같은 30종목 집합에 대해
v3_bb_rsi_signal_study 방식의 수치를 재계산해 비교 자료를 만든다.
결과는 research/strategy-lab/findings/v3-engine-smoke/ 에만 쓴다.

  python run_v3_engine_smoke.py
"""
import json
import os
import random
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

from engine.data.universeProvider import UniverseProvider  # noqa: E402
from engine.runner import run_smoke  # noqa: E402
from run_5dc_v1a_p_merged import realized_pnl_metrics, trades_from_portfolio, yearly_breakdown  # noqa: E402

REPO_ROOT = os.path.abspath(os.path.join(HERE, "..", ".."))
OUT_DIR = os.path.join(HERE, "findings", "v3-engine-smoke")
N_TICKERS = 30
START, END = "2016-01-04", "2026-08-03"
SEED = 42


def main():
    t0 = time.time()
    universe = UniverseProvider(repo_root=REPO_ROOT, include_delisted=False)
    tk_sorted = sorted(universe.tickers)
    rng = random.Random(SEED)
    subset = set(rng.sample(tk_sorted, N_TICKERS))
    print(f"universe={len(universe.tickers)}, smoke subset={len(subset)} (seed={SEED})")

    res = run_smoke("v3_bollinger_rsi", START, END, REPO_ROOT,
                    ticker_subset=subset, trace_limit=10)
    diag = res["diag"]
    portfolio = res["portfolio"]
    trades = trades_from_portfolio(portfolio)
    print(f"smoke done: signals={diag['signalCount']}, executable={diag['executableTradeCount']}, "
          f"closed={len(trades)} ({time.time()-t0:.0f}s)")

    # 거래별 총수익률(비용 전) - 신호 스터디와의 비교용
    gross_rets = [t["exit_price"] / t["entry_price"] - 1 for t in trades]
    hold_days = [t["holding_sessions"] for t in trades]
    realized = realized_pnl_metrics(portfolio, START, END)

    engine_block = {
        "tickers": sorted(subset),
        "period": f"{START}~{END}",
        "diag": {
            k: diag[k] for k in ("tickersScanned", "suspensionRowsDropped", "signalCount",
                                 "invalidSignalCount", "skippedSignalCount", "skippedReasons",
                                 "executableTradeCount", "exitTypeCounts", "firstSignalDate",
                                 "lastSignalDate", "maxSimultaneousPositionsObserved",
                                 "openPositionCountAtEnd")
        },
        "tradeCount": len(trades),
        "grossReturnPerTrade": {
            "mean": round(sum(gross_rets) / len(gross_rets), 6) if gross_rets else None,
            "median": round(sorted(gross_rets)[len(gross_rets)//2], 6) if gross_rets else None,
            "winRate": round(sum(1 for r in gross_rets if r > 0) / len(gross_rets), 4) if gross_rets else None,
        },
        "holdingSessions": {"mean": round(sum(hold_days)/len(hold_days), 2) if hold_days else None},
        "realizedPortfolioMetrics": realized,
        "yearlyBreakdown": yearly_breakdown(trades),
        "traces": res["traces"],
    }

    # --- 같은 30종목에 대한 v3 signal study 방식 수치 (entryLow 변형)
    from v3_bb_rsi_signal_study import load_ohlc, find_signals_and_exit
    HORIZONS = ("T+1", "T+5", "T+10", "T+20")

    df_all = load_ohlc()
    df = df_all[df_all["ticker"].isin(subset)].reset_index(drop=True)
    sig_pos = find_signals_and_exit(df, "low")[0]
    sig_all = df.iloc[sig_pos]

    study_block = {"signalRowsRaw": int(len(sig_all))}
    for h_name, days in (("T+1", 1), ("T+5", 5), ("T+10", 10), ("T+20", 20)):
        col = f"fwd_{days}"
        d = sig_all.dropna(subset=[col])
        if d.empty:
            study_block[h_name] = {"n": 0}
            continue
        study_block[h_name] = {
            "n": int(len(d)),
            "mean": round(float(d[col].mean()), 6),
            "median": round(float(d[col].median()), 6),
            "winRate": round(float((d[col] > 0).mean()), 4),
        }
    print("study(entryLow) on same subset:", {h: study_block[h].get("mean") for h in HORIZONS})

    # --- BB 표준편차 관례 차이(ddof=0 vs 1)가 신호 수에 미치는 영향 정량화
    g = df.groupby("ticker")["close"]
    mid = g.transform(lambda s: s.rolling(20, min_periods=20).mean())
    sd0 = g.transform(lambda s: s.rolling(20, min_periods=20).std(ddof=0))
    lower0 = mid - 2.0 * sd0
    cond0 = (df["low"] < lower0) & (df["rsi"] <= 30)
    cond1 = (df["low"] < df["bbLower"]) & (df["rsi"] <= 30)
    ddof_block = {
        "signalRowsDdof0_engineConvention": int(cond0.sum()),
        "signalRowsDdof1_studyConvention": int(cond1.sum()),
        "overlapRows": int((cond0 & cond1).sum()),
    }
    print("ddof comparison:", ddof_block)

    os.makedirs(OUT_DIR, exist_ok=True)
    out_path = os.path.join(OUT_DIR, "engine_smoke_results.json")
    with open(out_path, "w", encoding="utf-8") as fh:
        json.dump({
            "generatedAt": time.strftime("%Y-%m-%dT%H:%M:%S"),
            "purpose": "V3 엔진 연결 소표본 스모크 - 전체 실행 아님",
            "assumptions": {
                "stopDistance": "[ASSUMPTION] 2*ATR[t] (기존 계약 상수 재사용)",
                "rewardRisk": "[ASSUMPTION] 3.0 (동일)",
                "maxHoldingSessions": "[ASSUMPTION] 60 세션 (동일, 무기한 보유 방지용)",
                "observedExitDeviation": "High>=UpperBand 동적 청산은 executor 정적 계약으로 "
                                         "미표현 - stop/target/time 중 하나로만 청산됨",
            },
            "engine": engine_block,
            "signalStudySameSubset": study_block,
            "bbStdConventionImpact": ddof_block,
        }, fh, ensure_ascii=False, indent=2, default=str)
    print("saved:", out_path)


if __name__ == "__main__":
    main()
