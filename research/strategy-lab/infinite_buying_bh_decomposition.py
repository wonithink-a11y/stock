#!/usr/bin/env python3
"""§0③ 두 번째 항목 — B&H 대비 V4.0 성과를 세 요소로 분해.

    cash drag         현금(미투자) 상태로 놓친/피한 수익
    averaging benefit 저가 분할매수가 일시불 진입 대비 평단을 얼마나 낮췄나
    recovery capture  저점->회복 구간에서 가격 반등을 계좌가 얼마나 따라갔나

새 전략·파라미터 탐색 없음. 엔진(`infinite_buying_engine.py`) 불변. 체결모델은
`realistic_fill_model`의 표준(실현10bp) 그대로 — Phase 1 이후 확립한 기준선과
동일 조건.

세 지표는 **정확히 더해서 총수익 차이가 되는 분해가 아니다** — 그렇게 만들려면
상호작용항이 필요해 오히려 불투명해진다. 대신 각각 독립된 질문에 답하는
서술적 지표로 설계했다:

    cash drag   = Σ (전날 노출비중 - 1) * 그날 수익률          — 전체 백테스트
    averaging benefit = (사이클 첫날 종가 - 사이클 마지막 평단) / 사이클 첫날 종가
                        — 완결된 사이클마다
    recovery capture  = 계좌 저점->회복 수익률 / 가격 저점->회복 수익률
                        — 3A 확정 episode마다(회복된 것만)

    python research/strategy-lab/infinite_buying_bh_decomposition.py
    python research/strategy-lab/infinite_buying_bh_decomposition.py --selftest
"""
import argparse
from pathlib import Path

import pandas as pd

import infinite_buying_engine as eng
from infinite_buying_drawdown_episodes import detect_episodes, load_candles as load_price_candles
from realistic_fill_model import use_realistic_fill

ROOT = Path(__file__).resolve().parent
RULES = ROOT / "data" / "leveraged-etf" / "_rules.local.json"
SPLITS = 40
THRESHOLD = 0.25


def load_engine_candles(ticker: str) -> list[dict]:
    df = pd.read_parquet(ROOT / "data" / "leveraged-etf" / f"{ticker}.parquet")
    return [{"date": d.strftime("%Y-%m-%d"), "open": o, "high": h, "low": lo, "close": c}
            for d, o, h, lo, c in df[["date", "open", "high", "low", "close"]].itertuples(index=False)]


def _row_at_or_before(df: pd.DataFrame, date: str) -> pd.Series:
    sub = df[df["date"] <= date]
    return sub.iloc[-1] if len(sub) else df.iloc[0]


def cash_drag(trace: pd.DataFrame) -> dict:
    """(전날 노출비중 - 1) * 당일수익률 을 전 구간 합산 — 덧셈 근사치임을
    분모(복리 아님)로 명시한다. 노출<100%일 때 수익률이 +면 손해(음수 기여),
    -면 이익(양수 기여)이라 "현금이 항상 손해"는 아니다."""
    df = trace.copy()
    df["exposure_prev"] = (df["qty"].shift(1) * df["close"].shift(1)) / df["equity"].shift(1)
    df["ret"] = df["close"] / df["close"].shift(1) - 1
    df["drag"] = (df["exposure_prev"] - 1) * df["ret"]
    df = df.dropna(subset=["drag", "exposure_prev"])
    reverse_col = df["reverse"] if "reverse" in df.columns else pd.Series(False, index=df.index)
    return {
        "mean_exposure_pct": df["exposure_prev"].mean() * 100,
        "cash_drag_total_pct": df["drag"].sum() * 100,
        "cash_drag_reverse_pct": df.loc[reverse_col, "drag"].sum() * 100,
        "cash_drag_accum_pct": df.loc[~reverse_col, "drag"].sum() * 100,
    }


def averaging_benefit(cycles: list[dict], trace: pd.DataFrame) -> pd.DataFrame:
    """완결 사이클마다: 사이클 첫날 종가(일시불 진입 가정) vs 사이클 마지막
    보유일의 평단(실제 분할매수 결과). 양수면 분할매수가 일시불보다 싸게 샀다."""
    rows = []
    for cyc in cycles:
        window = trace[(trace["date"] >= cyc["start"]) & (trace["date"] <= cyc["end"])]
        held = window[window["qty"] > 0]
        if held.empty or window.empty:
            continue
        lump_sum_price = window.iloc[0]["close"]
        final_avg_cost = held.iloc[-1]["avg"]
        if lump_sum_price <= 0:
            continue
        rows.append({
            "start": cyc["start"], "end": cyc["end"], "days": cyc["days"],
            "lump_sum_price": lump_sum_price, "final_avg_cost": final_avg_cost,
            "averaging_benefit_pct": (lump_sum_price - final_avg_cost) / lump_sum_price * 100,
        })
    return pd.DataFrame(rows)


def recovery_capture(episodes: list, trace: pd.DataFrame) -> pd.DataFrame:
    """회복된 episode마다: 계좌의 저점->회복 수익률 / 가격의 저점->회복 수익률.
    1.0=가격 반등을 그대로 따라감, <1=일부만(분할매도로 노출이 줄어서),
    >1=오히려 증폭(역전 국면에서 매도대금으로 더 싸게 재매수해서)."""
    rows = []
    for e in episodes:
        if not e.recovery_date:
            continue
        price_ret = e.recovery_price / e.trough_price - 1
        if price_ret == 0:
            continue
        eq_trough = _row_at_or_before(trace, e.trough_date)["equity"]
        eq_recov = _row_at_or_before(trace, e.recovery_date)["equity"]
        strat_ret = eq_recov / eq_trough - 1 if eq_trough > 0 else float("nan")
        rows.append({
            "peak_date": e.peak_date, "trough_date": e.trough_date, "recovery_date": e.recovery_date,
            "price_recovery_pct": price_ret * 100, "strategy_recovery_pct": strat_ret * 100,
            "capture_ratio": strat_ret / price_ret,
        })
    return pd.DataFrame(rows)


def selftest() -> int:
    fails: list[str] = []

    def ck(name: str, cond: bool) -> None:
        print(("ok   " if cond else "FAIL ") + name)
        if not cond:
            fails.append(name)

    # --- cash_drag ---
    full = pd.DataFrame({
        "date": ["d1", "d2", "d3"], "close": [100.0, 110.0, 121.0],
        "qty": [10, 10, 10], "equity": [1000.0, 1100.0, 1210.0], "reverse": [False, False, False],
    })
    cd_full = cash_drag(full)
    ck("항상 100% 노출이면 cash drag ~0", abs(cd_full["cash_drag_total_pct"]) < 1e-6)

    half_up = pd.DataFrame({
        "date": ["d1", "d2"], "close": [100.0, 110.0],
        "qty": [5, 5], "equity": [1000.0, 1050.0], "reverse": [False, False],
    })
    cd_half_up = cash_drag(half_up)
    ck("50%노출+상승이면 cash drag 음수(손해)", cd_half_up["cash_drag_total_pct"] < 0)

    half_down = pd.DataFrame({
        "date": ["d1", "d2"], "close": [100.0, 90.0],
        "qty": [5, 5], "equity": [1000.0, 950.0], "reverse": [False, False],
    })
    cd_half_down = cash_drag(half_down)
    ck("50%노출+하락이면 cash drag 양수(방어)", cd_half_down["cash_drag_total_pct"] > 0)

    # --- averaging_benefit ---
    cycles = [{"start": "2020-01-01", "end": "2020-01-03", "days": 3, "profit": 100.0}]
    trace = pd.DataFrame({
        "date": ["2020-01-01", "2020-01-02", "2020-01-03"],
        "close": [100.0, 80.0, 90.0], "qty": [5, 10, 10], "avg": [100.0, 85.0, 85.0],
    })
    ab = averaging_benefit(cycles, trace)
    ck("분할매수로 평단이 일시불보다 싸면 benefit 양수",
       len(ab) == 1 and abs(ab.iloc[0]["averaging_benefit_pct"] - 15.0) < 1e-6)

    # --- recovery_capture ---
    class E:
        peak_date, trough_date, recovery_date = "2020-01-01", "2020-03-01", "2020-06-01"
        trough_price, recovery_price = 50.0, 100.0

    trace2 = pd.DataFrame({"date": ["2020-03-01", "2020-06-01"], "equity": [1000.0, 1500.0]})
    rc = recovery_capture([E()], trace2)
    ck("가격 100%반등에 계좌 50%반등이면 capture_ratio=0.5",
       len(rc) == 1 and abs(rc.iloc[0]["capture_ratio"] - 0.5) < 1e-6)

    total = 6
    print(f"\nselftest {total - len(fails)}/{total}" + ("" if not fails else f"  FAILED: {fails}"))
    return 1 if fails else 0


def run_ticker(ticker: str) -> None:
    r = eng.Rules.load(RULES, ticker, SPLITS)
    engine_candles = load_engine_candles(ticker)
    price_candles = load_price_candles(ticker)
    episodes = detect_episodes(price_candles, THRESHOLD)

    trace_list: list = []
    with use_realistic_fill():
        res = eng.backtest(engine_candles, r, plan_fn=eng.plan_orders, trace=trace_list)
    trace = pd.DataFrame(trace_list)

    print(f"\n===== {ticker} (실현10bp, 전체기간 {engine_candles[0]['date']}~{engine_candles[-1]['date']}) =====")

    cd = cash_drag(trace)
    print(f"\n[1] cash drag — 평균노출 {cd['mean_exposure_pct']:.1f}%  "
          f"총 {cd['cash_drag_total_pct']:+.2f}%p  "
          f"(정상국면 {cd['cash_drag_accum_pct']:+.2f}%p / 역전국면 {cd['cash_drag_reverse_pct']:+.2f}%p)")

    ab = averaging_benefit(res.cycles, trace)
    if len(ab):
        print(f"\n[2] averaging benefit — 완결사이클 {len(ab)}건  "
              f"평균 {ab['averaging_benefit_pct'].mean():+.2f}%  "
              f"중앙값 {ab['averaging_benefit_pct'].median():+.2f}%  "
              f"음수(일시불보다 못함) {int((ab['averaging_benefit_pct'] < 0).sum())}건")
    else:
        print("\n[2] averaging benefit — 완결 사이클 없음")

    rc = recovery_capture(episodes, trace)
    if len(rc):
        print(f"\n[3] recovery capture — 회복된 episode {len(rc)}/{len(episodes)}건  "
              f"평균 capture_ratio {rc['capture_ratio'].mean():.2f}  "
              f"중앙값 {rc['capture_ratio'].median():.2f}  "
              f"1.0 초과(증폭) {int((rc['capture_ratio'] > 1.0).sum())}건  "
              f"0.5 미만(절반도 못 따라감) {int((rc['capture_ratio'] < 0.5).sum())}건")
        with pd.option_context("display.float_format", "{:.1f}".format, "display.width", 140):
            print(rc.sort_values("capture_ratio").to_string(index=False))


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--selftest", action="store_true")
    a = ap.parse_args()
    if a.selftest:
        return selftest()

    run_ticker("TQQQ")
    run_ticker("SOXL")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
