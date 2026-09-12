#!/usr/bin/env python3
"""가격 경로별 구조 분해 — episode(고점 시작) 프레임의 편향을 피한 재평가.

`findings/infinite-buying-1a-ma-filter-comparison-2026-09-12.md` §3이 발견한
문제: 3A의 episode 탐지기는 "고점"에서만 구간을 시작해서, 정의상 고점에서 항상
매수 상태인 추세추종 전략(1a)을 그 전략이 제일 취약한 순간에서만 평가하게
만든다. 이 스크립트는 **고점이 아니라 캘린더를 겹치지 않게 타일링**해서 그
편향 없이 V4.0·1a·B&H를 같은 구간에서 비교한다.

분류 규칙(실행 전 확정, 결과 보고 나서 바꾸지 않는다):

    급락      그 구간 최대낙폭(peak->trough) >= 25%  이고  구간 끝이 저점에서
              30% 이내 회복(recovery_ratio<0.3) — 아직 안 빠져나왔다
    V자반등   최대낙폭 >= 25%  이고  구간 끝까지 70% 이상 회복(>=0.7)
    장기하락  총수익률 <= -15%  이고  최대낙폭 < 25%(급락처럼 한 번에 안 빠지고
              완만하게 흘러내림)
    추세장    총수익률 >= +15%  이고  최대낙폭 < 20%(뚜렷한 조정 없이 상승)
    장기횡보  위 네 조건 어디에도 안 걸림(그 외 전부)

25%는 새 값이 아니라 `infinite_buying_drawdown_episodes.py`가 이미 쓰는
임계값을 그대로 가져왔다(교훈: 새 파라미터를 매번 만들지 않는다). 창 길이는
두 개 — 63거래일(분기, 급락/V자반등처럼 짧게 끝나는 패턴용)과 252거래일
(1년, 장기하락/장기횡보/추세장처럼 오래 걸리는 패턴용) — 겹치지 않게 타일링
(stride=창 길이)해서 표본을 인위적으로 부풀리지 않는다.

    python research/strategy-lab/infinite_buying_path_decomposition.py
    python research/strategy-lab/infinite_buying_path_decomposition.py --selftest
"""
import argparse
from datetime import date
from pathlib import Path

import pandas as pd

import infinite_buying_engine as eng
from infinite_buying_1a_ma_filter_compare import compute_position_by_date, simulate as simulate_1a
from realistic_fill_model import use_realistic_fill

ROOT = Path(__file__).resolve().parent
RULES = ROOT / "data" / "leveraged-etf" / "_rules.local.json"
SPLITS = 40
DD_THRESHOLD = 0.25          # infinite_buying_drawdown_episodes.py 와 동일값 재사용
TREND_RET = 0.15
TREND_DD_CAP = 0.20
DECLINE_RET = -0.15
WINDOW_LENGTHS = (63, 252)


def load_engine_candles(ticker: str) -> list[dict]:
    df = pd.read_parquet(ROOT / "data" / "leveraged-etf" / f"{ticker}.parquet")
    return [{"date": d.strftime("%Y-%m-%d"), "open": o, "high": h, "low": lo, "close": c}
            for d, o, h, lo, c in df[["date", "open", "high", "low", "close"]].itertuples(index=False)]


def _ordinal(iso: str) -> int:
    y, m, d = (int(x) for x in iso.split("-"))
    return date(y, m, d).toordinal()


def classify_window(closes: list[float]) -> dict:
    """급락/V자반등/장기하락/추세장/장기횡보 중 하나. §도크스트링의 규칙 그대로."""
    total_return = closes[-1] / closes[0] - 1
    peak = closes[0]
    max_dd = 0.0
    trough_price, trough_peak_price = closes[0], closes[0]
    for p in closes:
        if p > peak:
            peak = p
        dd = (peak - p) / peak if peak > 0 else 0.0
        if dd > max_dd:
            max_dd, trough_price, trough_peak_price = dd, p, peak

    if max_dd > 0:
        recovery_ratio = (closes[-1] - trough_price) / (trough_peak_price - trough_price)
    else:
        recovery_ratio = 1.0

    if max_dd >= DD_THRESHOLD and recovery_ratio < 0.3:
        label = "급락"
    elif max_dd >= DD_THRESHOLD and recovery_ratio >= 0.7:
        label = "V자반등"
    elif total_return <= DECLINE_RET and max_dd < DD_THRESHOLD:
        label = "장기하락"
    elif total_return >= TREND_RET and max_dd < TREND_DD_CAP:
        label = "추세장"
    else:
        label = "장기횡보"
    return {"total_return": total_return * 100, "max_dd": max_dd * 100,
            "recovery_ratio": recovery_ratio, "label": label}


def tile_windows(candles: list[dict], length: int) -> list[list[dict]]:
    """겹치지 않게(stride=length) 자른다 — 표본을 부풀리지 않는다."""
    return [candles[i:i + length] for i in range(0, len(candles) - length + 1, length)]


def _bh_metrics(window: list[dict]) -> dict:
    closes = [c["close"] for c in window]
    yrs = (_ordinal(window[-1]["date"]) - _ordinal(window[0]["date"])) / 365.25
    ret = closes[-1] / closes[0] - 1
    cagr = ((1 + ret) ** (1 / yrs) - 1) * 100 if yrs > 0 else 0.0
    return {"cagr": cagr}


def selftest() -> int:
    fails: list[str] = []

    def ck(name: str, cond: bool) -> None:
        print(("ok   " if cond else "FAIL ") + name)
        if not cond:
            fails.append(name)

    trend = [100 + i for i in range(60)]  # 100->159, +59%, 무조정 상승
    ck("꾸준한 상승은 추세장", classify_window(trend)["label"] == "추세장")

    flat = [100.0, 101, 99, 100, 101, 99, 100]
    ck("작은 등락은 장기횡보", classify_window(flat)["label"] == "장기횡보")

    crash = [100.0] + [100 - i * 3 for i in range(1, 11)] + [70, 70, 70, 70, 70]
    ck("70까지 떨어져 안 돌아오면 급락", classify_window(crash)["label"] == "급락")

    v = [100.0] + [100 - i * 3 for i in range(1, 11)] + [70 + i * 3 for i in range(1, 11)]
    ck("떨어졌다 그대로 되돌아오면 V자반등", classify_window(v)["label"] == "V자반등")

    grind = [100 - i * 0.3 for i in range(60)]  # 완만하게 -17.7%, 최대낙폭도 완만
    ck("완만한 하락(조정 없이)은 장기하락", classify_window(grind)["label"] == "장기하락")

    candles = [{"date": f"2020-{1+i//28:02d}-{1+i%28:02d}", "close": 100.0} for i in range(130)]
    tiles = tile_windows(candles, 63)
    ck("130개를 63일씩 자르면 2조각(나머지 버림), 안 겹친다",
       len(tiles) == 2 and tiles[0][-1] is not tiles[1][0])

    total = 6
    print(f"\nselftest {total - len(fails)}/{total}" + ("" if not fails else f"  FAILED: {fails}"))
    return 1 if fails else 0


def run_ticker(ticker: str, include_1a: bool) -> None:
    r = eng.Rules.load(RULES, ticker, SPLITS)
    engine_candles = load_engine_candles(ticker)
    pos_by_date = None
    if include_1a:
        qqq_candles = load_engine_candles("QQQ")
        pos_by_date = compute_position_by_date(qqq_candles, band_mode="hold")

    for length in WINDOW_LENGTHS:
        rows = []
        for window in tile_windows(engine_candles, length):
            closes = [c["close"] for c in window]
            cls = classify_window(closes)
            with use_realistic_fill():
                v4 = eng.backtest(window, r, plan_fn=eng.plan_orders)
            row = {
                "start": window[0]["date"], "label": cls["label"],
                "total_return": cls["total_return"], "max_dd": cls["max_dd"],
                "v4_cagr": v4.cagr, "v4_mdd": v4.mdd, "v4_fail": v4.final_equity < r.seed,
                "bh_cagr": _bh_metrics(window)["cagr"],
            }
            if include_1a:
                res1a = simulate_1a(window, pos_by_date, r.seed)
                row["1a_cagr"] = res1a["cagr"]
                row["1a_mdd"] = res1a["mdd"]
                row["1a_fail"] = res1a["final_eq"] < r.seed
            rows.append(row)

        R = pd.DataFrame(rows)
        print(f"\n===== {ticker} — 창 {length}거래일 ({len(R)}개 타일, 안 겹침) =====")
        agg = {"n": ("label", "count"), "v4_cagr_mean": ("v4_cagr", "mean"),
               "v4_mdd_mean": ("v4_mdd", "mean"), "v4_fail_rate": ("v4_fail", "mean"),
               "bh_cagr_mean": ("bh_cagr", "mean")}
        if include_1a:
            agg.update({"1a_cagr_mean": ("1a_cagr", "mean"), "1a_mdd_mean": ("1a_mdd", "mean"),
                        "1a_fail_rate": ("1a_fail", "mean")})
        summary = R.groupby("label").agg(**agg).reindex(
            ["급락", "V자반등", "장기하락", "장기횡보", "추세장"]).dropna(how="all")
        with pd.option_context("display.float_format", "{:.2f}".format, "display.width", 160):
            print(summary.to_string())


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--selftest", action="store_true")
    a = ap.parse_args()
    if a.selftest:
        return selftest()

    run_ticker("TQQQ", include_1a=True)
    run_ticker("SOXL", include_1a=False)  # 1a 원형은 QQQ->TQQQ 전용, SOXL 대응(SOXX) 데이터 없음 — 확장 안 함
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
