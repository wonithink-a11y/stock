#!/usr/bin/env python3
"""국면결합(하이브리드) — 1a의 이미 검증된 QQQ 50SMA 시그널로 모드를 정하고,
IN(추세 확인)이면 1a식 100%노출, OUT(비추세/현금)이면 V4.0 엔진을 그대로 돌린다.

동기: `infinite-buying-path-decomposition-2026-09-12.md`가 확인한 상호보완성
(V4.0은 급락·V자반등·장기횡보에 강하고, 1a는 추세장에 압도적으로 강하다)을
실제로 이으면 어떻게 되는지 본다.

★ 이건 "국면 예측 모델 설계"가 아니라 "이미 검증된 두 규칙을 이미 있는 시그널로
  잇는다"다. 국면을 사전에 판별하는 새 지표를 만들지 않았다 — 그건 이것과
  완전히 다른(더 큰) 작업이라 하지 않는다(경로분해 findings §6에서 이미
  그렇게 선을 그었고, 사용자도 "국면결합까지만" 이라고 범위를 못박았다).
  1a의 시그널(QQQ 50SMA, 룩어헤드 없음, 밴드=hold)을 그대로 스위치로 쓸 뿐이다.

전환 규칙(단순화, 의도적으로 보수적):
  - 모드가 바뀌는 날, 그 모드의 보유분을 실현10bp로 전량 청산하고 그 현금을
    다음 모드의 시드로 넘긴다. 둘 다 TQQQ를 들고 있어도 청산->재진입으로
    처리한다 — 왕복 슬리피지를 두 번 물어 하이브리드 성과를 **과소평가하는
    쪽으로만** 작용하는 보수적 가정이다(실제로는 그대로 들고 가도 된다).
  - V4.0 쪽으로 전환하면 그 시점부터 완전히 새 사이클(t=0, cost=0)로 시작한다
    — 엔진 자체(`plan_orders`/`step`)는 그대로 재사용, 수정 없음.

TQQQ에만 적용한다(1a 원형이 QQQ→TQQQ 전용 — 기존 결정 그대로 유지, SOXL 확장
안 함).

    python research/strategy-lab/infinite_buying_regime_hybrid.py
    python research/strategy-lab/infinite_buying_regime_hybrid.py --selftest
"""
import argparse
from datetime import date
from pathlib import Path

import pandas as pd

import infinite_buying_engine as eng
from infinite_buying_1a_ma_filter_compare import compute_position_by_date
from infinite_buying_drawdown_episodes import detect_episodes, load_candles as load_price_candles
from infinite_buying_bh_decomposition import recovery_capture
from infinite_buying_path_decomposition import classify_window, tile_windows, WINDOW_LENGTHS
from realistic_fill_model import STANDARD_SLIPPAGE_BPS, use_realistic_fill

ROOT = Path(__file__).resolve().parent
RULES = ROOT / "data" / "leveraged-etf" / "_rules.local.json"
SPLITS = 40
THRESHOLD = 0.25
TICKER = "TQQQ"
SLIP = STANDARD_SLIPPAGE_BPS / 10000


def load_engine_candles(ticker: str) -> list[dict]:
    df = pd.read_parquet(ROOT / "data" / "leveraged-etf" / f"{ticker}.parquet")
    return [{"date": d.strftime("%Y-%m-%d"), "open": o, "high": h, "low": lo, "close": c}
            for d, o, h, lo, c in df[["date", "open", "high", "low", "close"]].itertuples(index=False)]


def _ordinal(iso: str) -> int:
    y, m, d = (int(x) for x in iso.split("-"))
    return date(y, m, d).toordinal()


def simulate_hybrid(candles: list[dict], position_by_date: dict, r: eng.Rules) -> dict:
    seed = r.seed
    mode = "1a" if position_by_date.get(candles[0]["date"], False) else "v4"
    v4_state = eng.State(cash=seed if mode == "v4" else 0.0)
    v4_closes: list[float] = []
    a_cash, a_qty = (seed, 0) if mode == "1a" else (0.0, 0)

    rows = []
    peak_eq = seed
    mdd = 0.0
    switches = 0

    for c in candles:
        pos = position_by_date.get(c["date"], mode == "1a")
        want = "1a" if pos else "v4"

        if want != mode:
            switches += 1
            px_sell = c["close"] * (1 - SLIP)
            cash_out = (v4_state.cash + v4_state.qty * px_sell + v4_state.realized
                        if mode == "v4" else a_cash + a_qty * px_sell)
            if want == "v4":
                v4_state, v4_closes = eng.State(cash=cash_out), []
                a_cash, a_qty = 0.0, 0
            else:
                a_cash, a_qty = cash_out, 0
                v4_state = eng.State(cash=0.0)
            mode = want

        if mode == "1a":
            if a_qty == 0 and a_cash > 0:
                px_buy = c["close"] * (1 + SLIP)
                q = int(a_cash // px_buy) if px_buy > 0 else 0
                if q > 0:
                    a_cash -= q * px_buy
                    a_qty += q
            eq = a_cash + a_qty * c["close"]
        else:
            orders = eng.plan_orders(v4_state, r, v4_closes)
            eng.step(v4_state, r, c, orders)
            v4_closes.append(c["close"])
            eq = v4_state.cash + v4_state.qty * c["close"] + v4_state.realized

        peak_eq = max(peak_eq, eq)
        if peak_eq > 0:
            mdd = max(mdd, (peak_eq - eq) / peak_eq * 100)
        rows.append({"date": c["date"], "equity": eq, "mode": mode})

    final_eq = rows[-1]["equity"]
    yrs = (_ordinal(candles[-1]["date"]) - _ordinal(candles[0]["date"])) / 365.25
    cagr = ((final_eq / seed) ** (1 / yrs) - 1) * 100 if yrs > 0 else 0.0
    return {"cagr": cagr, "mdd": mdd, "final_eq": final_eq, "switches": switches,
            "trace": pd.DataFrame(rows)}


def selftest() -> int:
    fails: list[str] = []

    def ck(name: str, cond: bool) -> None:
        print(("ok   " if cond else "FAIL ") + name)
        if not cond:
            fails.append(name)

    r = eng.Rules.load(RULES, TICKER, SPLITS)
    candles = load_engine_candles(TICKER)[:400]

    never_trend = {c["date"]: False for c in candles}
    hy_v4only = simulate_hybrid(candles, never_trend, r)
    ck("한 번도 안 트렌드면 전환 0회", hy_v4only["switches"] == 0)
    pure_v4 = eng.backtest(candles, r, plan_fn=eng.plan_orders)
    ck("한 번도 안 트렌드면 순수 V4.0과 동일 CAGR",
       abs(hy_v4only["cagr"] - pure_v4.cagr) < 1e-6)

    always_trend = {c["date"]: True for c in candles}
    hy_1aonly = simulate_hybrid(candles, always_trend, r)
    ck("항상 트렌드면 전환 0회", hy_1aonly["switches"] == 0)
    buy_px = candles[0]["close"] * (1 + SLIP)
    expected_final = int(r.seed // buy_px) * candles[-1]["close"] + (r.seed - int(r.seed // buy_px) * buy_px)
    ck("항상 트렌드면 1일차 매수 후 보유만 하는 것과 같다",
       abs(hy_1aonly["final_eq"] - expected_final) < 1.0)

    toggling = {}
    prev = False
    for i, c in enumerate(candles):
        prev = (i // 30) % 2 == 0
        toggling[c["date"]] = prev
    hy_switch = simulate_hybrid(candles, toggling, r)
    expected_switches = len(candles) // 30
    ck(f"30일마다 토글이면 전환 횟수가 대략 {expected_switches}",
       abs(hy_switch["switches"] - expected_switches) <= 1)
    ck("전환이 있어도 평가금이 유한하고 음수가 아니다",
       hy_switch["final_eq"] == hy_switch["final_eq"] and hy_switch["final_eq"] >= 0)

    total = 6
    print(f"\nselftest {total - len(fails)}/{total}" + ("" if not fails else f"  FAILED: {fails}"))
    return 1 if fails else 0


def confirm_days_sweep(candles: list[dict], qqq_candles: list[dict], r: eng.Rules,
                        values: tuple[int, ...] = (1, 2, 3, 4, 5, 7, 10, 15, 20)) -> pd.DataFrame:
    """1a 신호의 확인일수(원형=2)를 바꿔가며 하이브리드 전체 성과를 본다.

    ★ 이건 파라미터 튜닝이다 — 사용자가 위험을 인지하고 명시적으로 요청해
    돌린다(2026-09-13). 결과의 '최고점'은 in-sample 최적화 산물이지 검증된
    개선이 아니다. 채택 판단 없이 관측만 남긴다."""
    rows = []
    for cd in values:
        pos = compute_position_by_date(qqq_candles, band_mode="hold", confirm_days=cd)
        hy = simulate_hybrid(candles, pos, r)
        rows.append({"confirm_days": cd, "cagr": hy["cagr"], "mdd": hy["mdd"],
                     "switches": hy["switches"]})
    return pd.DataFrame(rows)


def regime_breakdown(candles: list[dict], pos: dict, r: eng.Rules) -> pd.DataFrame:
    rows = []
    for length in WINDOW_LENGTHS:
        for window in tile_windows(candles, length):
            closes = [c["close"] for c in window]
            cls = classify_window(closes)
            hy_res = simulate_hybrid(window, pos, r)
            rows.append({"win": length, "label": cls["label"],
                         "hy_cagr": hy_res["cagr"], "hy_mdd": hy_res["mdd"]})
    R = pd.DataFrame(rows)
    return R.groupby(["win", "label"]).agg(
        n=("label", "count"), hy_cagr=("hy_cagr", "mean"), hy_mdd=("hy_mdd", "mean"))


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--selftest", action="store_true")
    ap.add_argument("--confirm-sweep", action="store_true",
                     help="1a 확인일수 파라미터 스윕(위험 인지 하에 사용자 요청, in-sample)")
    a = ap.parse_args()
    if a.selftest:
        return selftest()

    if a.confirm_sweep:
        r = eng.Rules.load(RULES, TICKER, SPLITS)
        candles = load_engine_candles(TICKER)
        qqq_candles = load_engine_candles("QQQ")
        sweep = confirm_days_sweep(candles, qqq_candles, r)
        print("===== 1a 확인일수 파라미터 스윕 (in-sample, 채택 판단 아님) =====\n")
        with pd.option_context("display.float_format", "{:.2f}".format):
            print(sweep.to_string(index=False))
        best_cagr = sweep.loc[sweep["cagr"].idxmax()]
        best_mdd = sweep.loc[sweep["mdd"].idxmin()]
        print(f"\nCAGR 최고: confirm_days={int(best_cagr['confirm_days'])} "
              f"({best_cagr['cagr']:.2f}%, MDD {best_cagr['mdd']:.1f}%)")
        print(f"MDD 최저: confirm_days={int(best_mdd['confirm_days'])} "
              f"({best_mdd['mdd']:.1f}%, CAGR {best_mdd['cagr']:.2f}%)")
        print("\n----- 국면별 분해: 기존(2일) vs CAGR 최고 지점 -----")
        for cd, label in [(2, "confirm_days=2(원형)"), (int(best_cagr["confirm_days"]), "confirm_days=CAGR최고")]:
            pos = compute_position_by_date(qqq_candles, band_mode="hold", confirm_days=cd)
            print(f"\n[{label}]")
            with pd.option_context("display.float_format", "{:.2f}".format):
                print(regime_breakdown(candles, pos, r).to_string())
        print("\n★ 위 '최고' 지점은 같은 데이터에서 고른 in-sample 최적화 결과다 — "
              "OOS 재현 없이는 채택 근거로 쓰지 않는다.")
        return 0

    r = eng.Rules.load(RULES, TICKER, SPLITS)
    candles = load_engine_candles(TICKER)
    qqq_candles = load_engine_candles("QQQ")
    pos = compute_position_by_date(qqq_candles, band_mode="hold")

    hy = simulate_hybrid(candles, pos, r)
    with use_realistic_fill():
        v4 = eng.backtest(candles, r, plan_fn=eng.plan_orders)

    print(f"===== 국면결합 하이브리드 vs V4.0 단독 vs 1a 단독 — {TICKER} 전체기간 =====\n")
    print(f"{'전략':20} {'전체CAGR':>9} {'전체MDD':>8} {'비고'}")
    print(f"{'V4.0(실현10bp)':20} {v4.cagr:8.2f}% {v4.mdd:7.1f}%")
    print(f"{'하이브리드':20} {hy['cagr']:8.2f}% {hy['mdd']:7.1f}%  전환 {hy['switches']}회")
    print("  (1a 단독 수치는 infinite-buying-1a-ma-filter-comparison finding 참고: "
          "18.84%/67.6%)")

    print("\n----- 경로분해 프레임 재사용: 하이브리드가 어느 국면에서 좋아졌나 -----")
    for length in WINDOW_LENGTHS:
        rows = []
        for window in tile_windows(candles, length):
            closes = [c["close"] for c in window]
            cls = classify_window(closes)
            with use_realistic_fill():
                v4_res = eng.backtest(window, r, plan_fn=eng.plan_orders)
            hy_res = simulate_hybrid(window, pos, r)
            rows.append({"label": cls["label"], "v4_cagr": v4_res.cagr, "hy_cagr": hy_res["cagr"],
                         "v4_mdd": v4_res.mdd, "hy_mdd": hy_res["mdd"]})
        R = pd.DataFrame(rows)
        summary = R.groupby("label").agg(
            n=("label", "count"), v4_cagr=("v4_cagr", "mean"), hy_cagr=("hy_cagr", "mean"),
            v4_mdd=("v4_mdd", "mean"), hy_mdd=("hy_mdd", "mean"),
        ).reindex(["급락", "V자반등", "장기횡보", "추세장"]).dropna(how="all")
        print(f"\n[창 {length}거래일]")
        with pd.option_context("display.float_format", "{:.2f}".format):
            print(summary.to_string())

    print("\n----- episode 기준 recovery capture (하이브리드 vs V4.0) -----")
    price_candles = load_price_candles(TICKER)
    episodes = detect_episodes(price_candles, THRESHOLD)
    hy_full = simulate_hybrid(candles, pos, r)
    with use_realistic_fill():
        trace_v4: list = []
        eng.backtest(candles, r, plan_fn=eng.plan_orders, trace=trace_v4)
    rc_v4 = recovery_capture(episodes, pd.DataFrame(trace_v4))
    rc_hy = recovery_capture(episodes, hy_full["trace"])
    print(f"V4.0(실현10bp):  평균 capture_ratio {rc_v4['capture_ratio'].mean():.2f}  "
          f"(회복 {len(rc_v4)}/{len(episodes)})")
    print(f"하이브리드:      평균 capture_ratio {rc_hy['capture_ratio'].mean():.2f}  "
          f"(회복 {len(rc_hy)}/{len(episodes)})")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
