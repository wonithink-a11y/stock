#!/usr/bin/env python
"""V6(동시 순매수+매집가+5%) 엔진 스모크 드라이버 (소표본 30종목, 전체 실행 금지).

engine.runner.run_smoke를 그대로 재사용하고, 같은 30종목 집합에 대해
v6_acc_price_signal_study 방식 수치를 재계산해 비교 자료를 만든다.
selection.json이 없으면 먼저 build_selection.build()를 호출한다.
결과는 research/strategy-lab/findings/v6-engine-smoke/ 에만 쓴다.

  python run_v6_engine_smoke.py
"""
import json
import os
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

from engine.runner import run_smoke  # noqa: E402
from run_5dc_v1a_p_merged import realized_pnl_metrics, trades_from_portfolio, yearly_breakdown  # noqa: E402

REPO_ROOT = os.path.abspath(os.path.join(HERE, "..", ".."))
OUT_DIR = os.path.join(HERE, "findings", "v6-engine-smoke")
START, END = "2016-01-04", "2026-08-03"
SELECTION_PATH = os.path.join(HERE, "strategies", "v6_acc_price", "selection.json")


def main():
    t0 = time.time()
    # --- subset: selection.json이 단일 출처 (없으면 빌더가 seed=42 30종목으로 생성)
    if not os.path.exists(SELECTION_PATH):
        sys.path.insert(0, os.path.join(HERE, "strategies", "v6_acc_price"))
        import build_selection as bs
        bs.build(bs.smoke_subset())
    with open(SELECTION_PATH, encoding="utf-8") as f:
        sel_meta = json.load(f)
    subset = set(sel_meta["selection"].keys())
    print(f"subset={len(subset)} tickers, selection rows={sel_meta['signalRows']}")

    res = run_smoke("v6_acc_price", START, END, REPO_ROOT,
                    ticker_subset=subset, trace_limit=10)
    diag = res["diag"]
    portfolio = res["portfolio"]
    trades = trades_from_portfolio(portfolio)
    print(f"smoke done: signals={diag['signalCount']}, executable={diag['executableTradeCount']}, "
          f"closed={len(trades)} ({time.time()-t0:.0f}s)")

    gross_rets = [t["exit_price"] / t["entry_price"] - 1 for t in trades]
    hold_days = [t["holding_sessions"] for t in trades]
    realized = realized_pnl_metrics(portfolio, START, END)

    engine_block = {
        "tickers": sorted(subset),
        "period": f"{START}~{END}",
        "diag": {k: diag[k] for k in ("tickersScanned", "suspensionRowsDropped", "signalCount",
                                      "invalidSignalCount", "skippedSignalCount", "skippedReasons",
                                      "executableTradeCount", "exitTypeCounts", "firstSignalDate",
                                      "lastSignalDate", "maxSimultaneousPositionsObserved",
                                      "continuousHoldsMergedCount", "openPositionCountAtEnd")},
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

    # --- 같은 30종목에 대한 v6 signal study 방식 수치
    sys.path.insert(0, HERE)
    from v6_acc_price_signal_study import load_buy_flows, load_panel, PRICE_CAP  # noqa: E402

    panel = load_panel()
    flows = load_buy_flows()
    df = panel.merge(flows, on=["ticker", "date"], how="left")
    df = df.sort_values(["ticker", "date"]).reset_index(drop=True)
    g = df.groupby("ticker")
    amt5 = g["buyAmt"].transform(lambda s: s.fillna(0).rolling(5, min_periods=1).sum())
    vol5 = g["buyVol"].transform(lambda s: s.fillna(0).rolling(5, min_periods=1).sum())
    df["accPrice"] = __import__("numpy").where(vol5 > 0, amt5 / vol5, float("nan"))
    df["priceRatio"] = df["close"] / df["accPrice"]
    both = (df["foreign_nb_5d"] > 0) & (df["inst_nb_5d"] > 0)
    sig_all = df[df["ticker"].isin(subset) & both & (df["priceRatio"] <= PRICE_CAP)]

    study_block = {"signalRowsRaw": int(len(sig_all))}
    for h_name, days in (("T+1", 1), ("T+5", 5), ("T+10", 10), ("T+20", 20)):
        col = f"fwd_{days}"
        d = sig_all.dropna(subset=[col])
        study_block[h_name] = {
            "n": int(len(d)),
            "mean": round(float(d[col].mean()), 6),
            "median": round(float(d[col].median()), 6),
            "winRate": round(float((d[col] > 0).mean()), 4),
        }
    print("study(v6 variant) on same subset:",
          {h: study_block[h].get("mean") for h in ("T+5", "T+10", "T+20")})

    os.makedirs(OUT_DIR, exist_ok=True)
    out_path = os.path.join(OUT_DIR, "engine_smoke_results.json")
    with open(out_path, "w", encoding="utf-8") as fh:
        json.dump({
            "generatedAt": time.strftime("%Y-%m-%dT%H:%M:%S"),
            "purpose": "V6 엔진 연결 소표본 스모크 - 전체 실행 아님",
            "assumptions": {
                "holdSessions": "[ASSUMPTION] 고정 20세션 - 영상 미지정, study T+20 비교 정렬용",
                "riskEnvelope": "[ASSUMPTION] stop 도달 불가(entry*100)+RR 1.0 - TIME_EXIT 전용(pbr 패턴)",
                "maxPositions": "[ASSUMPTION] 30 - pbr 선례(선택 폭=슬롯 수) 따름",
                "scheduling": "continuousHoldOnRenewal=true - 연속 보유 갱신 병합 opt-in",
                "observedExitDeviation": "[OBSERVED]에 청산 규칙 없음 - 20세션 시간 청산이 유일한 청산",
            },
            "engine": engine_block,
            "signalStudySameSubset": study_block,
            "studyFullUniverseReference": {
                "note": "v6_acc_price_signal_study.py 결과(findings/v6-accrual-price) - 초과수익 기준",
                "T+20excessPerDateMatched": 0.00178,
                "T+20absoluteMean": 0.00884,
                "T+20winRate": 0.4583,
            },
        }, fh, ensure_ascii=False, indent=2, default=str)
    print("saved:", out_path)


if __name__ == "__main__":
    main()
