#!/usr/bin/env python3
"""3C — "저점 시점 현금비중"이 Hybrid v1 효과의 방향을 가르는가.

전제(고정, 재선정 금지):
  - episode 목록 = 3A(infinite_buying_drawdown_episodes.py) 확정본 그대로(threshold 25%,
    TQQQ 16건·SOXL 12건). 여기서 다시 고르지 않는다.
  - cash_ratio_at_trough = 3B(연속 backtest, 상태 리셋 없음)의 trough 날짜 값 그대로.
  - Hybrid 파라미터 = 기존에 이미 실험한 max_frac=0.75 고정(재튜닝 안 함 — 이미
    max_frac×splits 스윕에서 데이터마이닝 위험을 확인했다).

주 분석: 각 episode(peak_date~recovery_date/end_date)에 V4.0 과 Hybrid 를 "새 사이클로"
동일 시드로 재실행해 성과 차이(ΔCAGR·ΔMDD·Δ최종자산)를 낸다. 그리고 그 차이가
cash_ratio_at_trough 와 상관되는지 본다(pooled·TQQQ만·SOXL만, Pearson+Spearman,
저/고 현금비중 그룹 비교).

보조 분석: trough 로부터 고정 252거래일(~1년) 뒤까지만 잘라 같은 비교를 반복한다
(사전에 정한 길이 — 결과를 보고 유리한 길이를 고르지 않는다). 데이터가 252거래일
안 남으면 그 episode 는 보조 분석에서 제외하고 표시한다.

전략 엔진 코드는 수정하지 않는다. commit/push 없음(사용자 지시).

    python research/strategy-lab/infinite_buying_episode_hybrid_effect.py
"""
from pathlib import Path

import numpy as np
import pandas as pd

from infinite_buying_engine import Rules, backtest, plan_orders
from infinite_buying_hybrid_v1 import make_plan_fn
from infinite_buying_drawdown_episodes import detect_episodes, load_candles as load_price_candles

ROOT = Path(__file__).resolve().parent
RULES = ROOT / "data" / "leveraged-etf" / "_rules.local.json"
THRESHOLD = 0.25          # 3A 확정치
HYBRID_MAX_FRAC = 0.75    # 기존 실험 그대로, 재튜닝 안 함
FIXED_HORIZON_DAYS = 252  # 보조 분석: trough 후 약 1년(거래일), 사전 고정


def load_engine_candles(ticker: str) -> list[dict]:
    df = pd.read_parquet(ROOT / "data" / "leveraged-etf" / f"{ticker}.parquet")
    return [{"date": d.strftime("%Y-%m-%d"), "open": o, "high": h, "low": lo, "close": c}
            for d, o, h, lo, c in df[["date", "open", "high", "low", "close"]].itertuples(index=False)]


def _row_at_or_before(df: pd.DataFrame, date: str) -> pd.Series:
    sub = df[df["date"] <= date]
    return sub.iloc[-1] if len(sub) else df.iloc[0]


def _slice(candles: list[dict], start: str, end: str) -> list[dict]:
    return [c for c in candles if start <= c["date"] <= end]


def run_pair(candles: list[dict], r: Rules) -> tuple:
    base = backtest(candles, r, plan_fn=plan_orders)
    hyb = backtest(candles, r, plan_fn=make_plan_fn(HYBRID_MAX_FRAC))
    return base, hyb


def pearson(x: list[float], y: list[float]) -> float:
    if len(x) < 2 or np.std(x) == 0 or np.std(y) == 0:
        return float("nan")
    return float(np.corrcoef(x, y)[0, 1])


def spearman(x: list[float], y: list[float]) -> float:
    return pearson(list(pd.Series(x).rank()), list(pd.Series(y).rank()))


def selftest() -> int:
    fails: list[str] = []

    def ck(name: str, cond: bool) -> None:
        print(("ok   " if cond else "FAIL ") + name)
        if not cond:
            fails.append(name)

    ck("완전한 양의 상관 -> Pearson=1", abs(pearson([1, 2, 3, 4], [10, 20, 30, 40]) - 1.0) < 1e-9)
    ck("완전한 음의 상관 -> Pearson=-1", abs(pearson([1, 2, 3, 4], [40, 30, 20, 10]) - (-1.0)) < 1e-9)
    ck("무관 -> Pearson=0 근처", abs(pearson([1, 2, 3, 4], [5, 5, 5, 5]) or 0) < 1e-9 or
       str(pearson([1, 2, 3, 4], [5, 5, 5, 5])) == "nan")
    ck("비선형 단조 -> Spearman=1(Pearson<1)",
       abs(spearman([1, 2, 3, 4], [1, 8, 27, 64]) - 1.0) < 1e-9 and
       pearson([1, 2, 3, 4], [1, 8, 27, 64]) < 1.0)

    total = 4
    print(f"\nselftest {total - len(fails)}/{total}" + ("" if not fails else f"  FAILED: {fails}"))
    return 1 if fails else 0


def main() -> int:
    import sys
    if "--selftest" in sys.argv:
        return selftest()
    rows = []
    full_trace_by_ticker = {}
    full_candles_by_ticker = {}

    for ticker in ["TQQQ", "SOXL"]:
        r = Rules.load(RULES, ticker, 40)
        price_candles = load_price_candles(ticker)
        episodes = detect_episodes(price_candles, THRESHOLD)
        engine_candles = load_engine_candles(ticker)
        full_candles_by_ticker[ticker] = engine_candles

        trace: list = []
        backtest(engine_candles, r, trace=trace)
        df = pd.DataFrame(trace)
        full_trace_by_ticker[ticker] = df

        for ep in episodes:
            end = ep.recovery_date or ep.end_date
            trough_row = _row_at_or_before(df, ep.trough_date)
            cash_ratio = trough_row["cash"] / trough_row["equity"] if trough_row["equity"] > 0 else float("nan")

            window = _slice(engine_candles, ep.peak_date, end)
            base, hyb = run_pair(window, r)
            d_cagr = hyb.cagr - base.cagr
            d_mdd = hyb.mdd - base.mdd
            d_equity = hyb.final_equity - base.final_equity

            # 보조: trough 후 고정 252거래일
            idx_trough = next((i for i, c in enumerate(engine_candles) if c["date"] >= ep.trough_date), None)
            idx_peak = next((i for i, c in enumerate(engine_candles) if c["date"] >= ep.peak_date), None)
            aux = None
            if idx_trough is not None and idx_peak is not None:
                idx_end_fixed = idx_trough + FIXED_HORIZON_DAYS
                if idx_end_fixed < len(engine_candles):
                    fixed_window = engine_candles[idx_peak:idx_end_fixed + 1]
                    fb, fh = run_pair(fixed_window, r)
                    aux = {"d_cagr": fh.cagr - fb.cagr, "d_mdd": fh.mdd - fb.mdd,
                           "d_equity": fh.final_equity - fb.final_equity}

            rows.append({
                "ticker": ticker, "peak_date": ep.peak_date, "trough_date": ep.trough_date,
                "end_date": end, "recovered": ep.recovery_date is not None,
                "dd_pct": (ep.peak_price - ep.trough_price) / ep.peak_price * 100,
                "cash_ratio_at_trough": cash_ratio,
                "base_cagr": base.cagr, "hybrid_cagr": hyb.cagr, "d_cagr": d_cagr,
                "base_mdd": base.mdd, "hybrid_mdd": hyb.mdd, "d_mdd": d_mdd,
                "d_equity": d_equity,
                "aux_d_cagr": aux["d_cagr"] if aux else None,
                "aux_d_mdd": aux["d_mdd"] if aux else None,
                "aux_d_equity": aux["d_equity"] if aux else None,
                "aux_available": aux is not None,
            })

    R = pd.DataFrame(rows)

    print(f"★ episode 목록: 3A 확정 그대로(threshold {THRESHOLD:.0%}) — 재선정 없음")
    print(f"★ Hybrid max_frac={HYBRID_MAX_FRAC} 고정(재튜닝 안 함)")
    print(f"★ 총 {len(R)}개 episode (TQQQ {len(R[R.ticker=='TQQQ'])} / SOXL {len(R[R.ticker=='SOXL'])})\n")

    print("===== 전체 episode 표 (반례 포함, 전부 표시) =====")
    cols = ["ticker", "peak_date", "recovered", "dd_pct", "cash_ratio_at_trough",
            "d_cagr", "d_mdd", "d_equity"]
    with pd.option_context("display.float_format", "{:.2f}".format, "display.width", 160):
        print(R[cols].to_string(index=False))

    print(f"\n===== 주분석: cash_ratio_at_trough ↔ Hybrid 효과(ΔCAGR) 상관 =====")
    for label, sub in [("pooled(전체)", R), ("TQQQ만", R[R.ticker == "TQQQ"]),
                        ("SOXL만", R[R.ticker == "SOXL"])]:
        x = sub["cash_ratio_at_trough"].tolist()
        y_cagr = sub["d_cagr"].tolist()
        y_eq = sub["d_equity"].tolist()
        print(f"  [{label}] n={len(sub)}  "
              f"Pearson(cash,ΔCAGR)={pearson(x, y_cagr):.3f}  Spearman={spearman(x, y_cagr):.3f}  "
              f"Pearson(cash,Δ자산)={pearson(x, y_eq):.3f}  Spearman={spearman(x, y_eq):.3f}")

    print(f"\n===== 저/고 현금비중 그룹 비교 (중앙값 분할, pooled) =====")
    med = R["cash_ratio_at_trough"].median()
    low = R[R["cash_ratio_at_trough"] <= med]
    high = R[R["cash_ratio_at_trough"] > med]
    print(f"  중앙값 = {med:.2%}")
    print(f"  저현금비중군(n={len(low)}) ΔCAGR 평균 {low['d_cagr'].mean():+.2f}%p  "
          f"Δ자산 평균 ${low['d_equity'].mean():+,.0f}")
    print(f"  고현금비중군(n={len(high)}) ΔCAGR 평균 {high['d_cagr'].mean():+.2f}%p  "
          f"Δ자산 평균 ${high['d_equity'].mean():+,.0f}")

    print(f"\n===== 티커별 저/고 현금비중 그룹 비교 =====")
    for ticker in ["TQQQ", "SOXL"]:
        sub = R[R.ticker == ticker]
        med_t = sub["cash_ratio_at_trough"].median()
        low_t = sub[sub["cash_ratio_at_trough"] <= med_t]
        high_t = sub[sub["cash_ratio_at_trough"] > med_t]
        print(f"  [{ticker}] 중앙값 {med_t:.2%}  저군(n={len(low_t)}) ΔCAGR {low_t['d_cagr'].mean():+.2f}%p"
              f"  고군(n={len(high_t)}) ΔCAGR {high_t['d_cagr'].mean():+.2f}%p")

    print(f"\n===== 보조분석: trough 후 고정 {FIXED_HORIZON_DAYS}거래일 창 (사전 고정, 데이터부족 시 제외) =====")
    aux_avail = R[R.aux_available]
    aux_excl = R[~R.aux_available]
    print(f"  적용 가능 {len(aux_avail)}건 / 데이터부족 제외 {len(aux_excl)}건")
    if len(aux_excl):
        print(f"  제외된 episode: {aux_excl['peak_date'].tolist()} ({aux_excl['ticker'].tolist()})")
    if len(aux_avail) >= 2:
        x = aux_avail["cash_ratio_at_trough"].tolist()
        y = aux_avail["aux_d_cagr"].tolist()
        print(f"  Pearson(cash, 보조ΔCAGR)={pearson(x, y):.3f}  Spearman={spearman(x, y):.3f}")
        med_a = aux_avail["cash_ratio_at_trough"].median()
        low_a = aux_avail[aux_avail["cash_ratio_at_trough"] <= med_a]
        high_a = aux_avail[aux_avail["cash_ratio_at_trough"] > med_a]
        print(f"  저현금군(n={len(low_a)}) 보조ΔCAGR 평균 {low_a['aux_d_cagr'].mean():+.2f}%p  "
              f"고현금군(n={len(high_a)}) 보조ΔCAGR 평균 {high_a['aux_d_cagr'].mean():+.2f}%p")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
