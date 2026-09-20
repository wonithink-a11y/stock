#!/usr/bin/env python3
"""crypto_upshock_v1 모의 슬리브 1회 실행. 사전등록:
findings/crypto-upshock-paper-sleeve-preregistration-2026-09.md

    python research/strategy-lab/run_crypto_upshock_paper.py             # dry-run(기본)
    python research/strategy-lab/run_crypto_upshock_paper.py --execute   # 상태 기록
    python research/strategy-lab/run_crypto_upshock_paper.py --selftest  # 네트워크 없음

매일 **KST 09:05** 에 한 번 돈다(= UTC 00:05, 업비트 일봉 경계 직후).
그 시각이 규칙의 일부다 - policy.json 의 maxEntryDelayMinutes(120) 를 넘겨
실행되면 진입을 건너뛴다. 늦게 돌아도 조용히 다른 전략이 되지 않게 막는다
(교훈57 - 잴 수 없는 간격에서는 판정하지 않는다).

브로커는 UpbitPaperBroker(로컬 시뮬레이션)뿐이다. 이 스크립트는 업비트의
인증 메서드를 부르지 않으므로 키가 없어도 끝까지 돈다 - 실주문 경로가 없다.

순서: poll(어제 포지션 청산) -> scan(새 신호) -> poll(매수 제출·체결).
청산을 먼저 처리해야 오늘 청산된 코인이 오늘 다시 신호를 내면 재진입할 수 있다.
"""
import argparse
import os
import sys
from datetime import datetime, timedelta, timezone

import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))
REPO_ROOT = os.path.dirname(os.path.dirname(HERE))   # research/strategy-lab -> research -> 저장소 루트
sys.path.insert(0, HERE)

for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(errors="replace")
    except Exception:
        pass

from engine.live import positionStore                      # noqa: E402
from engine.live.paperEngine import poll_once, scan_signals  # noqa: E402
from strategies.crypto_upshock_v1 import rule               # noqa: E402

PARAMS = rule.PARAMS
STRATEGY_ID = PARAMS["strategyId"]
UNIVERSE = PARAMS["testUniverse"]
KST = timezone(timedelta(hours=9))


def minutes_into_utc_day(now_utc):
    return now_utc.hour * 60 + now_utc.minute


def pick_as_of(bars_by_market):
    """마지막 **완성된** UTC 일을 고른다.

    업비트는 형성 중인 당일 봉도 같이 준다(실측). 그 봉의 close 는 확정값이
    아니므로 신호에 쓰면 안 된다 - 시계로 추론하지 않고 데이터에서 직접
    마지막 행을 떨어뜨린다(실행 시각이 흔들려도 같은 답이 나온다).
    """
    dates = None
    for df in bars_by_market.values():
        d = set(df.index[:-1])          # 형성 중인 마지막 봉 제외
        dates = d if dates is None else (dates & d)
    if not dates:
        return None
    return max(dates).strftime("%Y-%m-%d")


def run(broker, bars_by_market, now_utc, execute, log=print):
    as_of = pick_as_of(bars_by_market)
    if as_of is None:
        log("[중단] 완성된 공통 일봉이 없다 - 아무 것도 하지 않는다")
        return {"as_of": None, "signals": [], "events": []}

    trimmed = {m: df.loc[:as_of] for m, df in bars_by_market.items()}

    delay = minutes_into_utc_day(now_utc)
    limit = PARAMS["entry"]["maxEntryDelayMinutes"]
    too_late = delay > limit
    if too_late:
        log(f"[진입 건너뜀] UTC 일 시가 이후 {delay}분 경과 > 한도 {limit}분. "
            f"청산만 처리한다(규칙이 조용히 바뀌는 것을 막는다).")

    # 오늘 신호를 미리 보여준다 - dry-run 에서도 무엇이 걸렸는지 보여야 한다
    signals = []
    for market, df in trimmed.items():
        if rule.signal_fires(rule.compute_features(df), as_of):
            f = rule.compute_features(df).loc[pd.Timestamp(as_of)]
            signals.append({"market": market, "ret_pct": round(float(f["ret"]) * 100, 2),
                            "threshold_pct": round(float(f["threshold"]) * 100, 2)})
    signals.sort(key=lambda s: -s["ret_pct"])

    log(f"기준일(마지막 완성 UTC 일) = {as_of} · 유니버스 {len(trimmed)}종 · "
        f"신호 {len(signals)}건")
    for s in signals:
        log(f"  신호  {s['market']:10s} ret={s['ret_pct']:+.2f}%  (문턱 {s['threshold_pct']:+.2f}%)")

    if not execute:
        state = positionStore.load(REPO_ROOT, STRATEGY_ID)
        log(f"[dry-run] 상태를 쓰지 않는다. 현재 보유/대기 {len(state)}건: "
            f"{sorted(state) if state else '없음'}")
        return {"as_of": as_of, "signals": signals, "events": [], "dryRun": True}

    now_kst = now_utc.astimezone(KST)
    events = []
    for _ in range(3):                      # 어제 포지션 청산까지 상태기계를 굴린다
        events += poll_once(REPO_ROOT, rule, broker, log=log, enable_live_orders=True, now=now_kst)

    if not too_late:
        events += scan_signals(REPO_ROOT, rule, as_of, log=log, bars_by_ticker=trimmed)
        for _ in range(3):                  # 매수 제출 -> 체결 확인 -> OPEN
            events += poll_once(REPO_ROOT, rule, broker, log=log, enable_live_orders=True, now=now_kst)

    state = positionStore.load(REPO_ROOT, STRATEGY_ID)
    log(f"완료. 보유/대기 {len(state)}건: {sorted(state) if state else '없음'}")
    return {"as_of": as_of, "signals": signals, "events": events}


def _selftest():
    """네트워크 없이 규칙과 배관을 확인한다.

    ★ 실전 strategyId 를 쓰면 안 된다 - poll_once 가 record_order() 로 주문
    원장에 쓰기 때문에 합성 주문이 진짜 관측 원장에 섞인다(2026-09-20 실제로
    한 번 오염시킨 뒤 격리했다). positions 만 비우는 것으로는 안 지워진다.
    """
    import copy

    import numpy as np

    global PARAMS, STRATEGY_ID
    _orig_params, _orig_id = rule.PARAMS, STRATEGY_ID
    rule.PARAMS = copy.deepcopy(_orig_params)
    rule.PARAMS["strategyId"] = _orig_id + "_selftest"
    PARAMS, STRATEGY_ID = rule.PARAMS, rule.PARAMS["strategyId"]
    try:
        return _selftest_body(np)
    finally:
        rule.PARAMS, PARAMS, STRATEGY_ID = _orig_params, _orig_params, _orig_id


def _selftest_body(np):

    class FakeBroker:
        def __init__(self):
            self.buys, self.sells = [], []

        def submit_buy(self, s, q):
            self.buys.append((s, q))
            return "SB-" + s

        def submit_sell(self, s, q):
            self.sells.append((s, q))
            return "SS-" + s

        def check_fill(self, o, d, q):
            return {"fullyFilled": True, "rejected": False, "filledQty": q,
                    "avgPrice": 1000.0, "pending": False}

        def current_price(self, s):
            return 1000.0

    dates = pd.date_range("2026-06-01", periods=60, freq="D")
    rng = np.random.default_rng(20260920)
    failed = 0

    def ok(cond, label):
        nonlocal failed
        if not cond:
            failed += 1
            print(f"  FAIL {label}")
        else:
            print(f"  ok   {label}")

    # 조용한 계열 + 마지막 완성일에 +20% 충격 하나, 그 뒤 형성 중 봉 하나
    quiet = 1000 * (1 + rng.normal(0, 0.005, len(dates))).cumprod()
    shock = quiet.copy()
    shock[-2] = shock[-3] * 1.20
    shock[-1] = shock[-2] * 1.01
    bars = {
        "KRW-BTC": pd.DataFrame({"close": shock}, index=dates),
        "KRW-ETH": pd.DataFrame({"close": quiet}, index=dates),
    }

    as_of = pick_as_of(bars)
    ok(as_of == dates[-2].strftime("%Y-%m-%d"), f"형성 중 봉을 뺀다 (as_of={as_of})")

    feats = rule.compute_features(bars["KRW-BTC"])
    ok(bool(rule.signal_fires(feats, as_of)), "+20% 충격이 신호를 낸다")
    ok(not rule.signal_fires(rule.compute_features(bars["KRW-ETH"]), as_of),
       "조용한 계열은 신호를 안 낸다")
    ok(pd.isna(rule.compute_features(bars["KRW-BTC"]).iloc[5]["threshold"]),
       "표본이 min_periods 미만이면 문턱이 NaN(신호 없음)")

    # shift(1) PIT 장치가 실제로 걸려 있는가 - 충격일 자신이 sigma 에 들어가면 안 된다
    r = bars["KRW-BTC"]["close"].pct_change()
    naive = (2.0 * r.rolling(30, min_periods=20).std()).loc[pd.Timestamp(as_of)]
    ok(float(feats.loc[pd.Timestamp(as_of), "threshold"]) < float(naive),
       "shift(1) 이 충격일을 자기 문턱에서 뺀다")

    # 늦게 돌면 진입을 건너뛴다
    late = datetime(2026, 7, 30, 5, 0, tzinfo=timezone.utc)   # 300분 경과 > 120
    positionStore.save(REPO_ROOT, STRATEGY_ID, {})
    b = FakeBroker()
    run(b, bars, late, execute=True, log=lambda *a: None)
    ok(b.buys == [], "maxEntryDelayMinutes 초과 시 매수가 안 나간다")

    # 제때 돌면 신호 종목만 산다
    on_time = datetime(2026, 7, 30, 0, 5, tzinfo=timezone.utc)
    positionStore.save(REPO_ROOT, STRATEGY_ID, {})
    b = FakeBroker()
    out = run(b, bars, on_time, execute=True, log=lambda *a: None)
    ok([m for m, _ in b.buys] == ["KRW-BTC"], f"신호 종목만 매수 ({b.buys})")
    ok(len(out["signals"]) == 1, "신호 1건")
    qty = b.buys[0][1] if b.buys else 0
    ok(abs(qty - PARAMS["position"]["notionalPerPosition"] / float(bars["KRW-BTC"]["close"].iloc[-2])) < 1e-9,
       f"소수 수량이 명목금액/가격 그대로 ({qty})")

    # dry-run 은 상태를 안 바꾼다
    positionStore.save(REPO_ROOT, STRATEGY_ID, {})
    b = FakeBroker()
    run(b, bars, on_time, execute=False, log=lambda *a: None)
    ok(b.buys == [] and positionStore.load(REPO_ROOT, STRATEGY_ID) == {},
       "dry-run 은 주문도 상태 변경도 없다")

    positionStore.save(REPO_ROOT, STRATEGY_ID, {})
    print(f"\n{'FAILED' if failed else 'PASSED'} - {failed} failure(s)")
    return 1 if failed else 0


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--execute", action="store_true", help="상태를 실제로 기록한다(기본은 dry-run)")
    ap.add_argument("--selftest", action="store_true", help="네트워크 없이 규칙·배관 확인")
    args = ap.parse_args()

    if args.selftest:
        return _selftest()

    from engine.live.upbitCandles import load_bars
    from engine.live.upbitPaperBroker import UpbitPaperBroker

    bars = load_bars(UNIVERSE, count=90)
    missing = sorted(set(UNIVERSE) - set(bars))
    if missing:
        print(f"[경고] 일봉을 못 받은 마켓 {len(missing)}건: {missing}")
    run(UpbitPaperBroker(), bars, datetime.now(timezone.utc), execute=args.execute)
    return 0


if __name__ == "__main__":
    sys.exit(main())
