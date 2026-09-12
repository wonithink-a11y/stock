#!/usr/bin/env python3
"""Phase 3 — 1a(QQQ 50SMA 추세필터) vs 무한매수 V4.0, 동일 체결모델 비교.

`docs/control/무한매수법-비교대상-후보탐색-Phase2-2026-09-12.md`의 1a 재현.
원형 규칙(auto-trade.app "Conservative Strategy"):

    QQQ 종가가 50일 SMA 위로 2일 연속        -> TQQQ 매수(보유)
    QQQ 종가가 50일 SMA 아래로 2일 연속       -> 현금
    QQQ 종가가 50일 SMA 대비 ±0.5% 이내(밴드) -> "무매매"

★ 밴드 해석이 원문 자체로 갈린다 — auto-trade.app 원문은 "Stay in cash when
  within band"라고 명시하는데, 이건 "밴드=현금 강제"로도, 기술적 분석의 표준
  관행("무매매"=기존 포지션 유지)으로도 읽힌다. 둘 다 구현해 비교한다
  (`band_mode="cash"` / `"hold"`) — 하나를 임의로 골라 "재현"이라 부르지 않는다.

체결모델은 `realistic_fill_model.STANDARD_SLIPPAGE_BPS`(10bp)를 그대로 쓴다 —
V4.0만 새 체결모델로 비교하고 1a는 옛(무비용) 가정으로 두면 불공정하다
(Phase2 문서 §8에서 이미 못박은 원칙).

룩어헤드 없음: 시그널은 d일 종가까지 정보로 정해지고, **d+1일의 포지션**으로만
쓴다(당일 마감 정보로 당일 마감 주문을 낼 수는 없다 — QQQ와 TQQQ는 같은
나스닥 마감경매 시각에 마감한다).

    python research/strategy-lab/infinite_buying_1a_ma_filter_compare.py
    python research/strategy-lab/infinite_buying_1a_ma_filter_compare.py --selftest
"""
import argparse
from datetime import date
from pathlib import Path

import pandas as pd

import infinite_buying_engine as eng
from infinite_buying_drawdown_episodes import detect_episodes, load_candles as load_price_candles, _days_between
from realistic_fill_model import STANDARD_SLIPPAGE_BPS, use_realistic_fill

ROOT = Path(__file__).resolve().parent
RULES = ROOT / "data" / "leveraged-etf" / "_rules.local.json"
SPLITS = 40
THRESHOLD = 0.25
TICKER = "TQQQ"
SLIP = STANDARD_SLIPPAGE_BPS / 10000
SMA_WINDOW = 50
BAND = 0.005


def load_engine_candles(ticker: str) -> list[dict]:
    df = pd.read_parquet(ROOT / "data" / "leveraged-etf" / f"{ticker}.parquet")
    return [{"date": d.strftime("%Y-%m-%d"), "open": o, "high": h, "low": lo, "close": c}
            for d, o, h, lo, c in df[["date", "open", "high", "low", "close"]].itertuples(index=False)]


def _ordinal(iso: str) -> int:
    y, m, d = (int(x) for x in iso.split("-"))
    return date(y, m, d).toordinal()


def compute_position_by_date(qqq_candles: list[dict], band_mode: str,
                              sma_window: int = SMA_WINDOW, band: float = BAND) -> dict:
    """{date: 그날 보유해야 할 포지션(bool)}. 룩어헤드 없음 — signal(d)는
    d일 종가까지 정보로 정해지고 d+1일의 포지션으로 한 칸 밀려 들어간다."""
    closes = [c["close"] for c in qqq_candles]
    dates = [c["date"] for c in qqq_candles]
    sma = pd.Series(closes).rolling(sma_window).mean()

    position = False
    consec_above = consec_below = 0
    signal_today: list[bool] = []
    for close, s in zip(closes, sma):
        if pd.isna(s):
            signal_today.append(position)
            continue
        if close > s * (1 + band):
            consec_above += 1
            consec_below = 0
            zone = "above"
        elif close < s * (1 - band):
            consec_below += 1
            consec_above = 0
            zone = "below"
        else:
            consec_above = consec_below = 0
            zone = "band"

        if zone == "above" and consec_above >= 2:
            position = True
        elif zone == "below" and consec_below >= 2:
            position = False
        elif zone == "band" and band_mode == "cash":
            position = False
        # else: 아직 확정 안 됨(밴드+hold, 또는 1일차 above/below) -> 기존 포지션 유지
        signal_today.append(position)

    result = {}
    prev = False  # 첫 거래일 이전엔 무포지션(현금)
    for d, sig in zip(dates, signal_today):
        result[d] = prev  # 오늘 포지션 = 어제까지의 시그널
        prev = sig
    return result


def simulate(tqqq_candles: list[dict], position_by_date: dict, seed: float) -> dict:
    cash = seed
    qty = 0
    prev_pos = False
    rows = []
    peak_eq = seed
    mdd = 0.0
    cash_days = 0

    for c in tqqq_candles:
        pos = position_by_date.get(c["date"], prev_pos)
        if pos and not prev_pos:
            px = c["close"] * (1 + SLIP)
            q = int(cash // px) if px > 0 else 0
            if q > 0:
                cash -= q * px
                qty += q
        elif not pos and prev_pos:
            px = c["close"] * (1 - SLIP)
            cash += qty * px
            qty = 0
        prev_pos = pos
        if qty == 0:
            cash_days += 1

        eq = cash + qty * c["close"]
        peak_eq = max(peak_eq, eq)
        if peak_eq > 0:
            mdd = max(mdd, (peak_eq - eq) / peak_eq * 100)
        rows.append({"date": c["date"], "equity": eq, "position": pos})

    final_eq = cash + qty * tqqq_candles[-1]["close"]
    yrs = (_ordinal(tqqq_candles[-1]["date"]) - _ordinal(tqqq_candles[0]["date"])) / 365.25
    cagr = ((final_eq / seed) ** (1 / yrs) - 1) * 100 if yrs > 0 else 0.0
    return {
        "cagr": cagr, "mdd": mdd, "final_eq": final_eq,
        "cash_days_frac": cash_days / len(tqqq_candles) if tqqq_candles else 0.0,
        "trace": pd.DataFrame(rows),
    }


def recovery_days_from(trace: pd.DataFrame, seed: float, trough_date: str, end_date: str) -> "int | None":
    sub = trace[(trace["date"] >= trough_date) & (trace["date"] <= end_date)]
    hit = sub[sub["equity"] >= seed]
    if hit.empty:
        return None
    return _days_between(trough_date, hit.iloc[0]["date"])


def v4_realistic(candles: list[dict], r: eng.Rules) -> dict:
    trace: list = []
    with use_realistic_fill():
        res = eng.backtest(candles, r, plan_fn=eng.plan_orders, trace=trace)
    return {"cagr": res.cagr, "mdd": res.mdd, "final_eq": res.final_equity, "trace": pd.DataFrame(trace)}


def selftest() -> int:
    fails: list[str] = []

    def ck(name: str, cond: bool) -> None:
        print(("ok   " if cond else "FAIL ") + name)
        if not cond:
            fails.append(name)

    # 합성 QQQ: 처음 60일 100 근처 평탄(SMA 안정) -> 61일째부터 뚜렷하게 상승 -> 하락
    synth = []
    px = 100.0
    for i in range(60):
        synth.append({"date": f"2020-{1 + i // 28:02d}-{1 + i % 28:02d}", "close": px})
    for i in range(10):
        px *= 1.02
        synth.append({"date": f"2020-{3 + i // 28:02d}-{1 + i % 28:02d}", "close": px})
    for i in range(10):
        px *= 0.97
        synth.append({"date": f"2020-{4 + i // 28:02d}-{1 + i % 28:02d}", "close": px})

    pos_hold = compute_position_by_date(synth, band_mode="hold")
    pos_cash = compute_position_by_date(synth, band_mode="cash")
    ck("SMA 미확정 구간(첫 49일)은 전부 무포지션", not any(list(pos_hold.values())[:49]))
    ck("뚜렷한 상승 뒤 어딘가에서 포지션이 True 로 바뀐다", any(pos_hold.values()))
    ck("hold/cash 두 해석 다 최소 하나는 진입 신호를 낸다", any(pos_cash.values()))

    c = {"date": "2020-01-06", "open": 100.0, "high": 100.0, "low": 100.0, "close": 100.0}
    tqqq = [dict(c, date=f"2020-01-{6+i:02d}") for i in range(5)]
    always_in = {row["date"]: True for row in tqqq}
    res = simulate(tqqq, always_in, seed=1000.0)
    ck("횡보+항상보유면 슬리피지 매수 1회만 발생, 평가금이 시드 근처(수수료 없음 전제)",
       abs(res["final_eq"] - 1000.0) < 5.0)
    ck("현금일수 비율이 0(항상 보유)", res["cash_days_frac"] == 0.0)

    never_in: dict = {row["date"]: False for row in tqqq}
    res2 = simulate(tqqq, never_in, seed=1000.0)
    ck("항상 현금이면 평가금 = 시드 그대로", res2["final_eq"] == 1000.0)
    ck("현금일수 비율이 1(항상 현금)", res2["cash_days_frac"] == 1.0)

    r = eng.Rules.load(RULES, TICKER, SPLITS)
    engine_candles = load_engine_candles(TICKER)[:300]
    v4 = v4_realistic(engine_candles, r)
    ck("V4.0 실현체결 재실행이 유한 CAGR/MDD 를 낸다", v4["cagr"] == v4["cagr"] and v4["mdd"] == v4["mdd"])

    total = 8
    print(f"\nselftest {total - len(fails)}/{total}" + ("" if not fails else f"  FAILED: {fails}"))
    return 1 if fails else 0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--selftest", action="store_true")
    a = ap.parse_args()
    if a.selftest:
        return selftest()

    qqq_candles = load_engine_candles("QQQ")
    tqqq_candles = load_engine_candles(TICKER)
    r = eng.Rules.load(RULES, TICKER, SPLITS)
    seed = r.seed

    price_candles = load_price_candles(TICKER)
    episodes = detect_episodes(price_candles, THRESHOLD)

    print(f"===== 1a(QQQ 50SMA 추세필터) vs V4.0(실현{STANDARD_SLIPPAGE_BPS:g}bp) — "
          f"{TICKER}, episode {len(episodes)}건 =====\n")

    variants = {}
    for mode in ("hold", "cash"):
        pos = compute_position_by_date(qqq_candles, band_mode=mode)
        full = simulate(tqqq_candles, pos, seed)
        variants[f"1a(밴드={mode})"] = {"full": full, "pos": pos}
    v4_full = v4_realistic(tqqq_candles, r)
    variants["V4.0(실현10bp)"] = {"full": v4_full, "pos": None}

    print(f"{'전략':18} {'전체CAGR':>9} {'전체MDD':>8} {'현금일수비율':>10}")
    for label, v in variants.items():
        f = v["full"]
        cash_frac = f.get("cash_days_frac")
        cash_str = f"{cash_frac*100:8.1f}%" if cash_frac is not None else "     n/a"
        print(f"{label:18} {f['cagr']:8.2f}% {f['mdd']:7.1f}% {cash_str}")

    print(f"\n----- episode 별({len(episodes)}건, 3A 확정 그대로, peak->실제회복일) -----")
    rows = []
    for e in episodes:
        end = e.recovery_date or e.end_date
        window_tqqq = [c for c in tqqq_candles if e.peak_date <= c["date"] <= end]
        if not window_tqqq:
            continue
        row = {"peak_date": e.peak_date, "dd_pct": (e.peak_price - e.trough_price) / e.peak_price * 100}

        for mode in ("hold", "cash"):
            pos = variants[f"1a(밴드={mode})"]["pos"]
            res = simulate(window_tqqq, pos, seed)
            rec = recovery_days_from(res["trace"], seed, e.trough_date, end)
            row[f"1a_{mode}_cagr"] = res["cagr"]
            row[f"1a_{mode}_mdd"] = res["mdd"]
            row[f"1a_{mode}_cash_frac"] = res["cash_days_frac"]
            row[f"1a_{mode}_recov"] = rec
            row[f"1a_{mode}_fail"] = res["final_eq"] < seed

        v4_res = v4_realistic(window_tqqq, r)
        rec4 = recovery_days_from(v4_res["trace"], seed, e.trough_date, end)
        row["v4_cagr"] = v4_res["cagr"]
        row["v4_mdd"] = v4_res["mdd"]
        row["v4_recov"] = rec4
        row["v4_fail"] = v4_res["final_eq"] < seed
        rows.append(row)

    R = pd.DataFrame(rows)
    with pd.option_context("display.float_format", "{:.1f}".format, "display.width", 200,
                            "display.max_columns", 20):
        cols = ["peak_date", "dd_pct", "v4_cagr", "v4_mdd", "v4_recov", "v4_fail",
                "1a_hold_cagr", "1a_hold_mdd", "1a_hold_recov", "1a_hold_fail",
                "1a_hold_cash_frac"]
        print(R[cols].sort_values("dd_pct", ascending=False).to_string(index=False))

    print("\n----- 요약 -----")
    print(f"V4.0(실현10bp):    회복실패 {int(R['v4_fail'].sum())}/{len(R)}  "
          f"episode평균CAGR {R['v4_cagr'].mean():+.2f}%p  최악CAGR {R['v4_cagr'].min():+.2f}%  "
          f"최악MDD {R['v4_mdd'].max():.1f}%")
    for mode in ("hold", "cash"):
        c = f"1a_{mode}"
        print(f"1a(밴드={mode}):  회복실패 {int(R[c+'_fail'].sum())}/{len(R)}  "
              f"episode평균CAGR {R[c+'_cagr'].mean():+.2f}%p  최악CAGR {R[c+'_cagr'].min():+.2f}%  "
              f"최악MDD {R[c+'_mdd'].max():.1f}%  평균현금일비율 {R[c+'_cash_frac'].mean()*100:.0f}%")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
