#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""부분 익절 그림자 관측 — 사전등록: docs/control/부분익절-그림자-설계-2026-09-20.md

**반사실 계산이다. 실제 슬리브 주문은 한 줄도 안 바꾼다.** pbr_value_v1_combined 의
forward 창(신호일 >= FORWARD_START)에서 "규칙을 켠 가상 곡선"과 "전량 보유 곡선"을
같은 진입·같은 비용으로 만들어 비교한다. 엔진은 partial_exit_sweep 을 그대로 쓴다.

  판정을 가진 규칙  PRIMARY 하나(+20%/70%). 나머지 SECONDARY 는 **기록 전용**이다 -
                    결과를 본 뒤 좋은 걸 고르면 다중검정이다. 승격은 새 사전등록.
  세 관측           (A) 규칙 5개 동시  (B) 능선 방향성(ΔSharpe>0 인 칸 비율)
                    (C) 메커니즘 - 트리거 이후 잔여 수익률(시장 대비)
  판정은 1회       MIN_COHORTS·MIN_TRADES 를 채울 때까지 기록만 한다.

  python run_partial_exit_shadow.py --selftest
  python run_partial_exit_shadow.py --precheck     # C 를 in-sample(pbr_value_v1)에서 미리 본다
  python run_partial_exit_shadow.py                # 월 1회, A2a 직후
"""
import argparse
import json
import os
import sys
import time
from datetime import datetime, timedelta, timezone

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from engine.portfolio.portfolio import PortfolioConfig                    # noqa: E402
from partial_exit_sweep import (load_run, random_timing_control,           # noqa: E402
                                scale_out_events)
from pbr_vs_ew_monthly_mtm import (_month_end_dates, curve_metrics,        # noqa: E402
                                   schedule_with_monthly_mtm)

LAB = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(LAB, "reports", "2026-09-partial-exit-shadow", "observations.jsonl")

# ---- 사전등록 상수 (결과를 본 뒤 바꾸지 않는다 - 바꾸려면 새 사전등록) --------------
STRATEGY = "pbr_value_v1_combined"
FORWARD_START = "2026-08-15"          # 근거 스윕(--end 2026-08-14) 데이터 끝의 다음 날
PRIMARY = (0.20, 0.70)                # (트리거, 매도비율) - 판정을 가진 유일한 규칙
SECONDARY = ((0.15, 0.70), (0.30, 0.70), (0.20, 0.50), (0.40, 0.50))   # 기록 전용
CONTROL_SEEDS = (1, 2, 3)
MIN_COHORTS, MIN_TRADES, EXTEND_COHORTS = 12, 300, 24
MAX_CAGR_LOSS = 0.005                 # 백테스트 -0.31%p 의 여유
MIN_BASE_MDD = 0.10                   # 기준선 MDD 가 이보다 얕으면 하락이 없어 못 잰다
SEG_TRAIN_END, SEG_VALID_END = "2022-05-31", "2023-12-28"   # precheck 전용, 09-04 finding 과 동일


def _label(rule):
    return "+{:.0f}%/{:.0f}%".format(rule[0] * 100, rule[1] * 100)


# ---- 계산 -----------------------------------------------------------------------
def forward_trades(resolved, start):
    return [it for it in resolved if it[0].signal_date >= start]


def _calmar(m):
    return m["cagr"] / abs(m["mdd"]) if m["mdd"] else None


def simulate(run, trades, start, end, rule=None, seed=None):
    """rule=None 이면 전량 보유(기준선). 반환: (metrics, 부분매도 건수, snapshots)."""
    p = run["params"]
    cfg = PortfolioConfig(
        initial_capital=p["portfolio"]["initialCapital"],
        max_positions=p["portfolio"]["maxPositions"],
        equal_weight=p["portfolio"]["equalWeight"],
        fractional_shares=p["portfolio"]["fractionalShares"],
        tie_break=p["portfolio"]["tieBreak"])
    pe = None
    if rule is not None:
        pe = scale_out_events(trades, run["bars_by_ticker"], rule[0], rule[1],
                              p["cost"]["exitCostBps"], p["cost"]["slippageBps"])
        if seed is not None:
            pe = random_timing_control(pe, trades, run["bars_by_ticker"], seed)
    _, snaps = schedule_with_monthly_mtm(trades, cfg, run["bars_by_ticker"], run["calendar"],
                                         start, end, partial_exits=pe)
    return curve_metrics(snaps), len(pe or {}), snaps


def observation_end(run, trades):
    """모든 (닫힌) 거래가 청산된 뒤 첫 월말. 그 전에 끊으면 마지막 코호트의 실현이 곡선에 안 들어간다."""
    last_exit = max(it[3].fill_date for it in trades)
    d = datetime.strptime(last_exit, "%Y-%m-%d") + timedelta(days=45)
    ends = _month_end_dates(run["calendar"], last_exit, d.strftime("%Y-%m-%d"))
    return next((e for e in ends if e >= last_exit), last_exit)


def market_ew_returns(bars_by_ticker):
    """일별 동일가중 시장수익률 {date: r}. 종목 수 5개 미만인 날은 뺀다."""
    import pandas as pd
    closes = pd.concat({t: b["close"] for t, b in bars_by_ticker.items() if not b.empty}, axis=1)
    closes.index = closes.index.astype(str)
    rets = closes.pct_change(fill_method=None)
    cnt = rets.notna().sum(axis=1)
    ew = rets.mean(axis=1)[cnt >= 5]
    return {d: float(v) for d, v in ew.items() if v == v}


def bench_return(ew, d0, d1):
    """(d0, d1] 구간 동일가중 시장 누적수익률."""
    r = 1.0
    for d, v in ew.items():
        if d0 < d <= d1:
            r *= 1 + v
    return r - 1


def residual_stats(trades, events, ew):
    """C - 트리거가 걸린 거래의 '트리거 이후 잔여 수익률'(트리거 체결가 -> 원래 청산가)과 시장 대비.

    부분 익절이 값을 하려면 트리거 이후 잔여 경로가 시장보다 못해야 한다(09-04 한계 1).
    거래 단위 쌍대 통계라 월 12점 Sharpe 보다 검출력이 훨씬 좋다. 코호트 월로 묶어
    se 를 따로 낸다 - 같은 달 종목은 시장 충격을 공유하므로 거래 단위 se 는 낙관적이다."""
    by_key = {(o.symbol, o.order_date): (it[0], it[2], it[3]) for it in trades
              for o in [it[1]]}
    rows = []
    for key, (d, pf, _) in events.items():
        sig, ef, xf = by_key[key]
        post = xf.fill_price / pf.fill_price - 1
        b = bench_return(ew, d, xf.fill_date)
        rows.append((sig.signal_date[:7], d, post, b))
    if not rows:
        return {"n": 0}
    post = np.array([r[2] for r in rows])
    exc = post - np.array([r[3] for r in rows])
    months = {}
    for (m, _, p, b) in rows:
        months.setdefault(m, []).append(p - b)
    mm = np.array([np.mean(v) for v in months.values()])
    se_m = float(mm.std(ddof=1) / np.sqrt(len(mm))) if len(mm) > 1 else None
    return {"n": len(rows), "meanPost": round(float(post.mean()), 4),
            "meanExcess": round(float(exc.mean()), 4), "medianExcess": round(float(np.median(exc)), 4),
            "seTrade": round(float(exc.std(ddof=1) / np.sqrt(len(exc))), 4) if len(exc) > 1 else None,
            "months": len(mm), "seMonthCluster": round(se_m, 4) if se_m else None,
            "tMonthCluster": round(float(mm.mean() / se_m), 2) if se_m else None}


# ---- 판정 (순수 함수) -----------------------------------------------------------
def judge(cohorts, n_trades, rule_m, base_m, control_sharpes, prior_verdicts=()):
    """반환 (verdict, reasons). 판정은 1회다 - 이미 끝났으면 DONE, 유예 뒤엔 24코호트에서만."""
    if any(v in ("KEEP-CANDIDATE", "REJECT", "INCONCLUSIVE") for v in prior_verdicts):
        return "DONE", []
    extended = "INCONCLUSIVE-EXTEND" in prior_verdicts
    if cohorts < (EXTEND_COHORTS if extended else MIN_COHORTS) or n_trades < MIN_TRADES:
        return "PENDING", []
    ds = None if rule_m["sharpe"] is None or base_m["sharpe"] is None else rule_m["sharpe"] - base_m["sharpe"]
    mdd_ok = rule_m["mdd"] >= base_m["mdd"]                     # 덜 음수 = 덜 깊다
    cal_r, cal_b = _calmar(rule_m), _calmar(base_m)
    ctrl = float(np.mean(control_sharpes)) if control_sharpes else None
    reasons = ["dSharpe={}".format(None if ds is None else round(ds, 3)),
               "mddRule={} mddBase={}".format(rule_m["mdd"], base_m["mdd"]),
               "cagrLoss={}".format(round(base_m["cagr"] - rule_m["cagr"], 4)),
               "controlSharpe={}".format(None if ctrl is None else round(ctrl, 3))]
    final = extended                                            # 연장 뒤엔 유예 없이 끝낸다
    if ds is not None and ds < 0 and not mdd_ok:
        return "REJECT", reasons
    if abs(base_m["mdd"]) < MIN_BASE_MDD:
        return ("INCONCLUSIVE" if final else "INCONCLUSIVE-EXTEND"), reasons + ["기준선 MDD 얕음"]
    if (ds is not None and ds > 0 and mdd_ok and cal_r is not None and cal_b is not None
            and cal_r > cal_b and base_m["cagr"] - rule_m["cagr"] <= MAX_CAGR_LOSS
            and ctrl is not None and rule_m["sharpe"] > ctrl):
        return "KEEP-CANDIDATE", reasons
    return ("INCONCLUSIVE" if final else "INCONCLUSIVE-EXTEND"), reasons


# ---- 관측 1행 -------------------------------------------------------------------
def observe(run, prior_verdicts=()):
    trades = forward_trades(run["resolved"], FORWARD_START)
    if not trades:
        return None
    end = observation_end(run, trades)
    ew = market_ew_returns(run["bars_by_ticker"])
    base_m, _, _ = simulate(run, trades, FORWARD_START, end)
    p = run["params"]
    rules, ridge = {}, []
    for rule in (PRIMARY,) + SECONDARY:
        m, n_part, _ = simulate(run, trades, FORWARD_START, end, rule)
        ev = scale_out_events(trades, run["bars_by_ticker"], rule[0], rule[1],
                              p["cost"]["exitCostBps"], p["cost"]["slippageBps"])
        ds = None if m["sharpe"] is None or base_m["sharpe"] is None else round(m["sharpe"] - base_m["sharpe"], 4)
        ridge.append(ds)
        rules[_label(rule)] = {"role": "PRIMARY" if rule == PRIMARY else "RECORD-ONLY",
                               **m, "dSharpe": ds, "partialCount": n_part,
                               "residual": residual_stats(trades, ev, ew)}
    ctrl = []
    for sd in CONTROL_SEEDS:
        m, _, _ = simulate(run, trades, FORWARD_START, end, PRIMARY, seed=sd)
        ctrl.append(m["sharpe"])
    ctrl_ok = [c for c in ctrl if c is not None]
    cohorts = len({it[0].signal_date for it in trades})
    known = [d for d in ridge if d is not None]
    verdict, reasons = judge(cohorts, len(trades), rules[_label(PRIMARY)], base_m, ctrl_ok, prior_verdicts)
    return {"asOf": end, "strategy": STRATEGY, "forwardStart": FORWARD_START,
            "cohorts": cohorts, "closedTrades": len(trades),
            "baseline": base_m, "rules": rules,
            "ridgeShare": {"positive": sum(1 for d in known if d > 0), "of": len(known)},
            "controlSharpes": ctrl, "verdict": verdict, "verdictReasons": reasons}


def append_once(path, row):
    """같은 asOf 재실행은 중복 append 안 한다(F2 shadow 와 같은 규칙). 반환: (append 됐나, 이전 verdict들)."""
    prior = []
    if os.path.exists(path):
        with open(path, encoding="utf-8") as f:
            prior = [json.loads(l) for l in f if l.strip()]
    if any(r["asOf"] == row["asOf"] for r in prior):
        return False
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "a", encoding="utf-8") as f:
        f.write(json.dumps(row, ensure_ascii=False) + "\n")
    return True


def prior_verdicts(path):
    if not os.path.exists(path):
        return []
    with open(path, encoding="utf-8") as f:
        return [json.loads(l)["verdict"] for l in f if l.strip()]


# ---- precheck: C 를 in-sample 로 -------------------------------------------------
def precheck():
    """pbr_value_v1 767건 전체(2016~2026-08-14)에서 트리거 이후 잔여 수익률을 미리 잰다.
    forward 관측과 별개의 값싼 사전 점검이다 - 여기서 잔여 수익률이 시장보다 좋으면
    부분 익절은 위험장치 값을 못 한다(계속 오르는 걸 파는 것)."""
    run = load_run("pbr_value_v1", "2016-01-01", "2026-08-14")
    trades = run["resolved"]
    p = run["params"]
    ew = market_ew_returns(run["bars_by_ticker"])
    out = {}
    for rule in (PRIMARY,) + SECONDARY:
        ev = scale_out_events(trades, run["bars_by_ticker"], rule[0], rule[1],
                              p["cost"]["exitCostBps"], p["cost"]["slippageBps"])
        seg = {"ALL": ev,
               "TRAIN": {k: v for k, v in ev.items() if v[0] <= SEG_TRAIN_END},
               "VALID": {k: v for k, v in ev.items() if SEG_TRAIN_END < v[0] <= SEG_VALID_END},
               "TEST": {k: v for k, v in ev.items() if v[0] > SEG_VALID_END}}
        out[_label(rule)] = {s: residual_stats(trades, e, ew) for s, e in seg.items()}
        print(_label(rule), json.dumps(out[_label(rule)], ensure_ascii=False), flush=True)
    return out


# ---- selftest -------------------------------------------------------------------
def selftest():
    base = {"cagr": 0.06, "mdd": -0.20, "sharpe": 0.5}
    good = {"cagr": 0.057, "mdd": -0.15, "sharpe": 0.6}
    bad = {"cagr": 0.05, "mdd": -0.25, "sharpe": 0.4}
    j = judge
    assert j(11, 400, good, base, [0.3])[0] == "PENDING"                 # 코호트 부족
    assert j(12, 299, good, base, [0.3])[0] == "PENDING"                 # 거래 부족
    assert j(12, 300, good, base, [0.3, 0.4])[0] == "KEEP-CANDIDATE"
    assert j(12, 300, bad, base, [0.3])[0] == "REJECT"                   # 둘 다 나쁨
    assert j(12, 300, {**good, "mdd": -0.26}, base, [0.3])[0] == "INCONCLUSIVE-EXTEND"   # Sharpe↑ MDD↓ 섞임
    assert j(12, 300, {**good, "cagr": 0.05}, base, [0.3])[0] == "INCONCLUSIVE-EXTEND"   # CAGR 손실 1%p > 0.5%p
    assert j(12, 300, good, base, [0.7])[0] == "INCONCLUSIVE-EXTEND"     # 대조군이 더 좋으면 규칙의 값이 아니다
    assert j(12, 300, good, {**base, "mdd": -0.08}, [0.3])[0] == "INCONCLUSIVE-EXTEND"   # 하락이 없었다
    assert j(23, 700, good, base, [0.3], ["INCONCLUSIVE-EXTEND"])[0] == "PENDING"        # 연장은 24 에서만
    assert j(24, 700, good, base, [0.3], ["INCONCLUSIVE-EXTEND"])[0] == "KEEP-CANDIDATE"
    assert j(24, 700, {**good, "cagr": 0.05}, base, [0.3], ["INCONCLUSIVE-EXTEND"])[0] == "INCONCLUSIVE"  # 두 번째는 유예 없음
    assert j(30, 900, good, base, [0.3], ["KEEP-CANDIDATE"])[0] == "DONE"  # 판정은 1회
    assert j(12, 300, {"cagr": .06, "mdd": -.2, "sharpe": None}, base, [.3])[0] == "INCONCLUSIVE-EXTEND"  # 잴 수 없으면 판정을 부정한다

    # append_once
    import tempfile
    d = tempfile.mkdtemp()
    path = os.path.join(d, "o.jsonl")
    assert append_once(path, {"asOf": "2026-10-30", "verdict": "PENDING"}) is True
    assert append_once(path, {"asOf": "2026-10-30", "verdict": "PENDING"}) is False   # 중복 없음
    assert append_once(path, {"asOf": "2026-11-30", "verdict": "INCONCLUSIVE-EXTEND"}) is True
    assert prior_verdicts(path) == ["PENDING", "INCONCLUSIVE-EXTEND"]

    # 시장 대비 잔여 수익률: 트리거 체결 110 -> 청산 121(+10%), 시장 +5% -> 초과 +5%
    from engine.execution.contracts import Fill, Order
    o = Order("A", "2026-09-01", "2026-09-02", "LONG", None)
    ef = Fill(o, "2026-09-02", 100.0, "OPEN", 15, 0)
    xf = Fill(o, "2026-09-30", 121.0, "TIME_EXIT", 15, 0)
    pf = Fill(o, "2026-09-10", 110.0, "TARGET", 15, 0)
    class S:
        signal_date = "2026-09-01"
    tr = [(S, o, ef, xf, None, None)]
    ev = {("A", "2026-09-02"): ("2026-09-10", pf, 0.7)}
    ew = {"2026-09-10": 0.5, "2026-09-11": 0.05, "2026-09-30": 0.0}   # 트리거일 당일 수익은 세지 않는다
    r = residual_stats(tr, ev, ew)
    assert r["n"] == 1 and abs(r["meanPost"] - 0.10) < 1e-9 and abs(r["meanExcess"] - 0.05) < 1e-9, r
    assert residual_stats(tr, {}, ew) == {"n": 0}
    print("selftest ok (19건)")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--selftest", action="store_true")
    ap.add_argument("--precheck", action="store_true")
    ap.add_argument("--end", default=None, help="가격 데이터 끝(기본: 오늘 KST)")
    a = ap.parse_args()
    if a.selftest:
        return selftest()
    if a.precheck:
        return precheck()
    end = a.end or datetime.now(timezone(timedelta(hours=9))).strftime("%Y-%m-%d")
    run = load_run(STRATEGY, "2026-08-01", end)
    row = observe(run, prior_verdicts(OUT))
    if row is None:
        print("forward 창에 닫힌 거래가 아직 없다 - 기록하지 않는다")
        return
    print(json.dumps({k: row[k] for k in ("asOf", "cohorts", "closedTrades", "ridgeShare", "verdict")},
                     ensure_ascii=False))
    print("append" if append_once(OUT, row) else "같은 asOf 가 이미 있다 - 건너뜀")


if __name__ == "__main__":
    main()
