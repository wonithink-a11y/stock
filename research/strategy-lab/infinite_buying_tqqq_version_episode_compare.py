#!/usr/bin/env python3
"""TQQQ 단일 종목으로 V2.1 vs V3.0 vs V4.0 최종 비교 — 종목 효과와 버전 효과를 분리.

3A 에서 확정한 TQQQ 16개 episode(재선정 없음)에 세 버전을 그대로 적용해 episode 별
CAGR·MDD·저점현금비중·"가격은 회복했는데 전략은 아직 손실"(전략 자체 회복 실패)을 본다.

    python research/strategy-lab/infinite_buying_tqqq_version_episode_compare.py
"""
from pathlib import Path

import pandas as pd

from infinite_buying_engine import Rules, backtest as v4_backtest, plan_orders
import infinite_buying_legacy_versions as legacy
from infinite_buying_drawdown_episodes import detect_episodes, load_candles as load_price_candles

ROOT = Path(__file__).resolve().parent
RULES = ROOT / "data" / "leveraged-etf" / "_rules.local.json"
THRESHOLD = 0.25
TICKER = "TQQQ"
BASE_PCT = 15.0  # V2.1/V3.0 TQQQ 공식값(quantstack 검증), V4.0 은 rules 파일에서 옴


def load_engine_candles(ticker: str) -> list[dict]:
    df = pd.read_parquet(ROOT / "data" / "leveraged-etf" / f"{ticker}.parquet")
    return [{"date": d.strftime("%Y-%m-%d"), "open": o, "high": h, "low": lo, "close": c}
            for d, o, h, lo, c in df[["date", "open", "high", "low", "close"]].itertuples(index=False)]


def _row_at_or_before(df: pd.DataFrame, date: str) -> pd.Series:
    sub = df[df["date"] <= date]
    return sub.iloc[-1] if len(sub) else df.iloc[0]


def _slice(candles: list[dict], start: str, end: str) -> list[dict]:
    return [c for c in candles if start <= c["date"] <= end]


def run_version(candles: list[dict], version: str, r: Rules) -> tuple:
    """(cagr, mdd, final_equity, cash_ratio_at_trough_lookup_df) 를 낸다."""
    if version == "v4":
        trace: list = []
        res = v4_backtest(candles, r, plan_fn=plan_orders, trace=trace)
        return res.cagr, res.mdd, res.final_equity, pd.DataFrame(trace)
    trace = []
    res = legacy.backtest(candles, version, BASE_PCT, 40, r.seed, trace=trace)
    return res.cagr, res.mdd, res.final_equity, pd.DataFrame(trace)


def selftest() -> int:
    fails: list[str] = []

    def ck(name: str, cond: bool) -> None:
        print(("ok   " if cond else "FAIL ") + name)
        if not cond:
            fails.append(name)

    r = Rules.load(RULES, TICKER, 40)
    price_candles = load_price_candles(TICKER)
    episodes = detect_episodes(price_candles, THRESHOLD)
    ck("3A 확정 TQQQ episode 수(16건) 재선정 없이 그대로 로드", len(episodes) == 16)

    engine_candles = load_engine_candles(TICKER)
    ep = episodes[0]
    end = ep.recovery_date or ep.end_date
    window = _slice(engine_candles, ep.peak_date, end)
    cagr, mdd, final_eq, _ = run_version(window, "v4", r)
    ck("v4 episode 재실행이 유한한 CAGR/MDD 를 낸다", cagr == cagr and mdd == mdd)  # NaN 아님

    trace: list = []
    legacy.backtest(window, "v21", BASE_PCT, 40, r.seed, trace=trace)
    tdf = pd.DataFrame(trace)
    ck("레거시 trace 의 cash/equity 비율이 전부 [0,1] 범위",
       bool(((tdf["cash"] / tdf["equity"]).between(-1e-6, 1 + 1e-6)).all()))

    total = 3
    print(f"\nselftest {total - len(fails)}/{total}" + ("" if not fails else f"  FAILED: {fails}"))
    return 1 if fails else 0


def main() -> int:
    import sys
    if "--selftest" in sys.argv:
        return selftest()
    r = Rules.load(RULES, TICKER, 40)
    price_candles = load_price_candles(TICKER)
    episodes = detect_episodes(price_candles, THRESHOLD)
    engine_candles = load_engine_candles(TICKER)

    versions = {"V2.1": "v21", "V3.0": "v30", "V4.0": "v4"}

    # 1) 연속(상태 리셋 없음) trace — 저점 현금비중용
    continuous_trace = {}
    for label, v in versions.items():
        trace: list = []
        if v == "v4":
            v4_backtest(engine_candles, r, plan_fn=plan_orders, trace=trace)
        else:
            legacy.backtest(engine_candles, v, BASE_PCT, 40, r.seed, trace=trace)
        continuous_trace[label] = pd.DataFrame(trace)

    rows = []
    for ep in episodes:
        end = ep.recovery_date or ep.end_date
        window = _slice(engine_candles, ep.peak_date, end)
        row = {"peak_date": ep.peak_date, "recovered": ep.recovery_date is not None,
               "dd_pct": (ep.peak_price - ep.trough_price) / ep.peak_price * 100,
               "recovery_days": None}
        from infinite_buying_drawdown_episodes import _days_between
        row["recovery_days"] = _days_between(ep.trough_date, end)

        for label, v in versions.items():
            cagr, mdd, final_eq, _ = run_version(window, v, r)
            cdf = continuous_trace[label]
            trough_row = _row_at_or_before(cdf, ep.trough_date)
            cash_ratio = trough_row["cash"] / trough_row["equity"] if trough_row["equity"] > 0 else float("nan")
            strategy_recovery_fail = final_eq < r.seed  # 가격은 회복했는데 전략 자체는 아직 손실
            row[f"{label}_cagr"] = cagr
            row[f"{label}_mdd"] = mdd
            row[f"{label}_final_eq"] = final_eq
            row[f"{label}_cash_at_trough"] = cash_ratio
            row[f"{label}_strategy_fail"] = strategy_recovery_fail
        rows.append(row)

    R = pd.DataFrame(rows)

    print(f"===== TQQQ episode 별 V2.1 vs V3.0 vs V4.0 (episode={len(R)}건, 3A 확정 그대로) =====\n")
    for label in versions:
        print(f"--- {label} ---")
        cols = ["peak_date", "recovered", "dd_pct", f"{label}_cagr", f"{label}_mdd",
                f"{label}_cash_at_trough", f"{label}_strategy_fail"]
        with pd.option_context("display.float_format", "{:.2f}".format, "display.width", 140):
            print(R[cols].sort_values("dd_pct", ascending=False).to_string(index=False))
        worst = R.loc[R[f"{label}_cagr"].idxmin()]
        worst_cash = R.loc[R[f"{label}_cash_at_trough"].idxmin()]
        n_fail = int(R[f"{label}_strategy_fail"].sum())
        max_recov = R.loc[R["recovery_days"].idxmax()]
        print(f"  최악 episode CAGR: {worst['peak_date']}({worst[f'{label}_cagr']:.2f}%, MDD {worst[f'{label}_mdd']:.1f}%)")
        print(f"  최악 저점현금비중: {worst_cash['peak_date']}({worst_cash[f'{label}_cash_at_trough']*100:.0f}%)")
        print(f"  최장 회복기간(가격기준, 버전무관): {max_recov['peak_date']}({max_recov['recovery_days']}일)")
        print(f"  전략 자체 회복실패(가격은 회복했는데 최종자산<시드) episode 수: {n_fail}/{len(R)}\n")

    print("===== 요약 =====")
    for label in versions:
        avg_cagr = R[f"{label}_cagr"].mean()
        worst_cagr = R[f"{label}_cagr"].min()
        worst_mdd = R[f"{label}_mdd"].max()
        print(f"  {label}: episode 평균CAGR {avg_cagr:+.2f}%p  최악CAGR {worst_cagr:+.2f}%  최악MDD {worst_mdd:.1f}%  "
              f"회복실패 {int(R[f'{label}_strategy_fail'].sum())}/{len(R)}건")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
