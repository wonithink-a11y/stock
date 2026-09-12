#!/usr/bin/env python3
"""V4.0 사이클별 데이터 조회 — 지정 구간에 걸친 완결 사이클 + 진행 중인 사이클.

새 분석 방법이 아니라 기존 엔진 출력(`Result.cycles`, `trace`)을 날짜로 잘라
보여주는 조회 도구다. 엔진 불변, 체결모델은 `realistic_fill_model` 표준
(실현10bp) 그대로.

    python research/strategy-lab/infinite_buying_cycle_report.py
    python research/strategy-lab/infinite_buying_cycle_report.py --ticker SOXL --start 2024-01-01
    python research/strategy-lab/infinite_buying_cycle_report.py --selftest
"""
import argparse
from pathlib import Path

import pandas as pd

import infinite_buying_engine as eng
from realistic_fill_model import use_realistic_fill

ROOT = Path(__file__).resolve().parent
RULES = ROOT / "data" / "leveraged-etf" / "_rules.local.json"
SPLITS = 40


def load_engine_candles(ticker: str) -> list[dict]:
    df = pd.read_parquet(ROOT / "data" / "leveraged-etf" / f"{ticker}.parquet")
    return [{"date": d.strftime("%Y-%m-%d"), "open": o, "high": h, "low": lo, "close": c}
            for d, o, h, lo, c in df[["date", "open", "high", "low", "close"]].itertuples(index=False)]


def cycles_since(res: eng.Result, trace: pd.DataFrame, start: str) -> pd.DataFrame:
    """지정일 이후에 끝난 완결 사이클을 표로 만든다(진입가·최종평단·역전여부·
    사이클내 최대낙폭 포함)."""
    rows = []
    for cyc in res.cycles:
        if cyc["end"] < start:
            continue
        window = trace[(trace["date"] >= cyc["start"]) & (trace["date"] <= cyc["end"])]
        if window.empty:
            continue
        held = window[window["qty"] > 0]
        entry_price = window.iloc[0]["close"]
        final_avg = held.iloc[-1]["avg"] if len(held) else float("nan")
        went_reverse = bool(window["reverse"].any()) if "reverse" in window else False
        max_dd = window["drawdown_pct"].max() if "drawdown_pct" in window else float("nan")
        rows.append({
            "시작": cyc["start"], "종료": cyc["end"], "보유일": cyc["days"],
            "진입가": round(entry_price, 2),
            "최종평단": round(final_avg, 2) if final_avg == final_avg else None,
            "역전여부": "O" if went_reverse else "-",
            "수익($)": round(cyc["profit"], 0),
            "사이클내최대낙폭%": round(max_dd, 1) if max_dd == max_dd else None,
        })
    return pd.DataFrame(rows)


def open_cycle_info(trace: pd.DataFrame) -> "dict | None":
    """마지막으로 qty==0이었던 날 다음부터가 진행 중인 사이클이다."""
    qty0_idx = trace.index[trace["qty"] == 0]
    start_i = (qty0_idx[-1] + 1) if len(qty0_idx) and qty0_idx[-1] + 1 < len(trace) else 0
    window = trace.iloc[start_i:]
    if window.empty or window.iloc[-1]["qty"] == 0:
        return None
    last = window.iloc[-1]
    return {
        "시작": window.iloc[0]["date"], "현재": last["date"], "보유일": len(window),
        "평단": round(last["avg"], 2), "현재가": round(last["close"], 2),
        "평가손익%": round((last["close"] / last["avg"] - 1) * 100, 1),
        "사이클내최대낙폭%": round(window["drawdown_pct"].max(), 1),
    }


def selftest() -> int:
    fails: list[str] = []

    def ck(name: str, cond: bool) -> None:
        print(("ok   " if cond else "FAIL ") + name)
        if not cond:
            fails.append(name)

    r = eng.Rules.load(RULES, "TQQQ", SPLITS)
    candles = load_engine_candles("TQQQ")[:600]
    trace: list = []
    with use_realistic_fill():
        res = eng.backtest(candles, r, plan_fn=eng.plan_orders, trace=trace)
    tdf = pd.DataFrame(trace)

    all_from_start = cycles_since(res, tdf, candles[0]["date"])
    ck("처음부터 조회하면 전체 완결 사이클 수와 같다", len(all_from_start) == len(res.cycles))

    far_future = cycles_since(res, tdf, "2099-01-01")
    ck("미래 날짜로 조회하면 0건", len(far_future) == 0)

    if len(res.cycles) >= 2:
        mid = res.cycles[1]["start"]
        subset = cycles_since(res, tdf, mid)
        ck("중간 날짜부터 조회하면 그 이후 것만 걸린다",
           all(c["종료"] >= mid for _, c in subset.iterrows()))

    oc = open_cycle_info(tdf)
    ck("마지막 600일 슬라이스는 사이클이 진행 중이거나(dict) 마침 0에서 끝난다(None)",
       oc is None or (oc["보유일"] > 0 and oc["시작"] <= oc["현재"]))

    total = 4
    print(f"\nselftest {total - len(fails)}/{total}" + ("" if not fails else f"  FAILED: {fails}"))
    return 1 if fails else 0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--selftest", action="store_true")
    ap.add_argument("--ticker", default="TQQQ")
    ap.add_argument("--start", default="2024-01-01")
    a = ap.parse_args()
    if a.selftest:
        return selftest()

    r = eng.Rules.load(RULES, a.ticker, SPLITS)
    candles = load_engine_candles(a.ticker)
    trace: list = []
    with use_realistic_fill():
        res = eng.backtest(candles, r, plan_fn=eng.plan_orders, trace=trace)
    tdf = pd.DataFrame(trace)

    print(f"===== {a.ticker} (splits={SPLITS}, base={r.base_pct:g}, 실현10bp) "
          f"— {a.start} 이후 완결 사이클 =====")
    R = cycles_since(res, tdf, a.start)
    print(f"전체기간 완결 사이클 {len(res.cycles)}건 중 이 구간에 걸친 것 {len(R)}건\n")
    with pd.option_context("display.width", 160, "display.max_columns", 20):
        print(R.to_string(index=False))

    oc = open_cycle_info(tdf)
    if oc:
        print(f"\n[진행 중] {oc['시작']} ~ {oc['현재']}(현재, 미완결)  평단 {oc['평단']}  "
              f"현재가 {oc['현재가']}  보유일 {oc['보유일']}일  평가손익 {oc['평가손익%']:+.1f}%  "
              f"사이클내최대낙폭 {oc['사이클내최대낙폭%']:.1f}%")

    win = tdf[tdf["date"] >= a.start]
    if len(win):
        eq_s, eq_e = win.iloc[0]["equity"], tdf.iloc[-1]["equity"]
        px_s, px_e = win.iloc[0]["close"], tdf.iloc[-1]["close"]
        print(f"\n{a.ticker} 구간 요약({a.start}~{tdf.iloc[-1]['date']}): "
              f"계좌 {eq_s:,.0f} -> {eq_e:,.0f} ({(eq_e/eq_s-1)*100:+.1f}%)  "
              f"가격 {px_s:.2f} -> {px_e:.2f} ({(px_e/px_s-1)*100:+.1f}%)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
