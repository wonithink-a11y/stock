#!/usr/bin/env python3
"""무한매수 백테스트용 표준 실현 체결모델.

`findings/infinite-buying-loc-fill-realism-2026-09-12.md`(Phase 1 LOC 현실성
검증)의 후속 조치 — 사용자가 그 문서의 판정("V4.0 훼손 큼")에 따라 합의한
조건부 분기대로 "체결모델부터 수정·표준화"를 실행한 것이다.

`infinite_buying_engine.fill()`은 **원본 그대로 둔다.** 기존 findings
(버전별 백테스트·episode 비교 전부)가 그 가정으로 나온 숫자라, 엔진 자체를
조용히 바꾸면 과거 비교가 전부 다른 기준으로 재해석돼야 한다. 대신 앞으로
V4.0을 다른 후보(예: Phase 2의 1a)와 비교할 때는 이 모듈의
`use_realistic_fill()`로 그 비교에서만 감싸 쓴다 — "이전 findings는 이상적
체결 가정, 신규 비교는 실현 체결 가정"이라고 각각 명시하면 된다.

표준값 = **슬리피지 10bp만.** 교란일(상위1% 변동성일 미체결)은 포함하지
않는다 — 근거는 LOC 현실성 findings §5-6:

    10bp  유동성 높은 레버리지 ETF의 마감경매 실행비용 통상 추정치(현실적)
    상위1%교란  "마감경매가 그날 아예 작동 안 한다"는 의도된 상한 스트레스 —
              상시 기본값으로 쓰면 위험을 과장한다(그 findings에서도 별도
              스트레스 변형으로만 다뤘지 표준안으로 제안하지 않았다)

    python research/strategy-lab/realistic_fill_model.py --selftest
    python research/strategy-lab/realistic_fill_model.py   # V4.0 표준 비교 기준선 출력
"""
import argparse
from contextlib import contextmanager
from pathlib import Path

import pandas as pd

import infinite_buying_engine as eng
from infinite_buying_drawdown_episodes import detect_episodes, load_candles as load_price_candles

ROOT = Path(__file__).resolve().parent
RULES = ROOT / "data" / "leveraged-etf" / "_rules.local.json"
SPLITS = 40
THRESHOLD = 0.25
STANDARD_SLIPPAGE_BPS = 10.0  # findings/infinite-buying-loc-fill-realism-2026-09-12.md §5-6


def make_slippage_fill(slip_bps: float):
    """slip_bps=0이면 원본 `eng.fill`과 완전히 동치(selftest가 확인).

    지정가보다 유리하게 체결되는 경우는 절대 없다 — 벤더 종가를 "진짜 종가는
    이보다 약간 나쁠 수 있다"고 조정한 값으로 체결 판정 자체를 다시 할 뿐,
    실제 지정가 주문의 성질(지정가보다 나쁘게 체결되지 않는다)은 그대로다."""

    def _fill(o, c):
        side, kind, limit, qty = o
        if qty <= 0:
            return None
        if kind == "LIMIT":
            hit = c["low"] <= limit if side == "buy" else c["high"] >= limit
            return (limit, qty) if hit else None
        adj = c["close"] * (1 + slip_bps / 10000) if side == "buy" else c["close"] * (1 - slip_bps / 10000)
        if kind == "MOC":
            return (adj, qty)
        if limit is None:
            raise ValueError(f"{kind} 주문에 지정가가 없다")
        hit = adj <= limit if side == "buy" else adj >= limit
        return (adj, qty) if hit else None

    return _fill


@contextmanager
def use_realistic_fill(slip_bps: float = STANDARD_SLIPPAGE_BPS):
    """with use_realistic_fill(): res = eng.backtest(...)

    블록 안에서만 `infinite_buying_engine.fill`을 표준 체결모델로 바꾸고,
    끝나면(예외가 나도) 원복한다. 엔진 파일 자체는 건드리지 않는다."""
    orig = eng.fill
    eng.fill = make_slippage_fill(slip_bps)
    try:
        yield
    finally:
        eng.fill = orig


def load_engine_candles(ticker: str) -> list[dict]:
    df = pd.read_parquet(ROOT / "data" / "leveraged-etf" / f"{ticker}.parquet")
    return [{"date": d.strftime("%Y-%m-%d"), "open": o, "high": h, "low": lo, "close": c}
            for d, o, h, lo, c in df[["date", "open", "high", "low", "close"]].itertuples(index=False)]


def selftest() -> int:
    fails: list[str] = []

    def ck(name: str, cond: bool) -> None:
        print(("ok   " if cond else "FAIL ") + name)
        if not cond:
            fails.append(name)

    c = {"date": "2020-01-06", "open": 100.0, "high": 120.0, "low": 90.0, "close": 100.0}
    zero = make_slippage_fill(0.0)
    for o in [("buy", "LOC", 100.0, 1), ("sell", "LOC", 100.0, 1),
              ("sell", "LIMIT", 115.0, 1), ("sell", "MOC", None, 1)]:
        ck(f"slip=0 은 원본과 동치 — {o}", zero(o, c) == eng.fill(o, c))

    ten = make_slippage_fill(10.0)
    buy = ten(("buy", "LOC", 100.2, 1), c)
    ck("10bp 매수는 종가*1.001 로 조정돼 체결", buy is not None and abs(buy[0] - 100.1) < 1e-6)
    ck("조정가가 지정가보다 비싸면 미체결", ten(("buy", "LOC", 100.05, 1), c) is None)

    orig_fill = eng.fill
    with use_realistic_fill(10.0):
        ck("컨텍스트 진입 중엔 eng.fill 이 바뀐다", eng.fill is not orig_fill)
        ck("컨텍스트 안에서는 표준체결과 같은 값을 낸다",
           eng.fill(("buy", "LOC", 100.2, 1), c) == ten(("buy", "LOC", 100.2, 1), c))
    ck("컨텍스트 종료 후 eng.fill 이 원복된다", eng.fill is orig_fill)

    total = 9
    print(f"\nselftest {total - len(fails)}/{total}" + ("" if not fails else f"  FAILED: {fails}"))
    return 1 if fails else 0


def _episode_table(ticker: str, r: eng.Rules) -> pd.DataFrame:
    engine_candles = load_engine_candles(ticker)
    price_candles = load_price_candles(ticker)
    episodes = detect_episodes(price_candles, THRESHOLD)
    rows = []
    for e in episodes:
        end = e.recovery_date or e.end_date
        window = [c for c in engine_candles if e.peak_date <= c["date"] <= end]
        res = eng.backtest(window, r, plan_fn=eng.plan_orders)
        rows.append({"peak_date": e.peak_date, "cagr": res.cagr, "mdd": res.mdd,
                     "final_eq": res.final_equity, "strategy_fail": res.final_equity < r.seed})
    return pd.DataFrame(rows), engine_candles


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--selftest", action="store_true")
    a = ap.parse_args()
    if a.selftest:
        return selftest()

    print(f"===== V4.0 표준 비교 기준선 (슬리피지 {STANDARD_SLIPPAGE_BPS:g}bp, "
          f"이상적 체결모델 대비) =====\n")
    for ticker in ("TQQQ", "SOXL"):
        r = eng.Rules.load(RULES, ticker, SPLITS)
        engine_candles = load_engine_candles(ticker)

        res_ideal = eng.backtest(engine_candles, r, plan_fn=eng.plan_orders)
        with use_realistic_fill():
            res_real = eng.backtest(engine_candles, r, plan_fn=eng.plan_orders)
            R_real, _ = _episode_table(ticker, r)
        R_ideal, _ = _episode_table(ticker, r)

        print(f"[{ticker}] splits={SPLITS} base={r.base_pct:g} episode {len(R_ideal)}건")
        print(f"  이상적   전체CAGR {res_ideal.cagr:6.2f}%  전체MDD {res_ideal.mdd:5.1f}%  "
              f"ep평균CAGR {R_ideal['cagr'].mean():+6.2f}%p  ep최악CAGR {R_ideal['cagr'].min():+6.2f}%  "
              f"회복실패 {int(R_ideal['strategy_fail'].sum())}/{len(R_ideal)}")
        print(f"  실현({STANDARD_SLIPPAGE_BPS:g}bp) 전체CAGR {res_real.cagr:6.2f}%  전체MDD {res_real.mdd:5.1f}%  "
              f"ep평균CAGR {R_real['cagr'].mean():+6.2f}%p  ep최악CAGR {R_real['cagr'].min():+6.2f}%  "
              f"회복실패 {int(R_real['strategy_fail'].sum())}/{len(R_real)}\n")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
