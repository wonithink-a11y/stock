"""probe-kis-vts-poll-once-smoke.py — 실제 KisVtsBroker로 poll_once() 상태기계
전체를 KIS 모의투자 계좌에서 1회 왕복 검증한다.

이전 스모크 테스트(probe-kis-vts-order-smoke.py)는 KisVtsClient의 주문
API가 동작하는지만 확인했다. 이건 다르다 - engine/live/paperEngine.py의
poll_once() 자체(PENDING_ENTRY -> ENTRY_SUBMITTED -> OPEN -> EXIT_SUBMITTED
-> 삭제 상태기계, 중복주문 방지, 체결확인)가 실제 KIS 응답을 받아 그대로
작동하는지를 검증 대상으로 삼는다.

dummy_sma20 1종목(005930) 1주로 제한. 신호 스캔(scan_signals)은 안 쓴다 -
A2a 과거 데이터가 오늘자까지 없어 실신호를 만들 수 없으므로, PENDING_ENTRY를
이 스크립트가 직접 심는다(이건 poll_once() 검증용이지 신호 로직 검증이
아니다). OPEN 전이 후에는 stop_price를 일부러 현재가보다 훨씬 위로 올려
즉시 STOP 청산이 나가게 만든다 - 실제 시세가 움직이길 기다리지 않고도
EXIT_SUBMITTED 경로까지 확인하기 위해서다.

사용자 명시 승인(2026-08-21, "실제 KisVtsBroker로 poll_once() 검증") 후 실행.

사용:
    python scripts/probe-kis-vts-poll-once-smoke.py
"""
import os
import sys
import time
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "research" / "strategy-lab"))

for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(errors="replace")
    except Exception:
        pass

from engine.live import positionStore  # noqa: E402
from engine.live.kisVtsBroker import KisVtsBroker, KisVtsError  # noqa: E402
from engine.live.paperEngine import poll_once  # noqa: E402

STRATEGY_ID = "dummy_sma20_poll_smoke"
SYMBOL = "005930"


class SmokeRule:
    PARAMS = {
        "strategyId": STRATEGY_ID,
        "testUniverse": [SYMBOL],
        "risk": {"stopPct": 0.05, "targetPct": 0.10, "maxHoldingSessions": 20},
        "position": {"notionalPerPosition": 10000000, "maxPositions": 1},
    }


def wait_until(condition_fn, max_polls, label):
    for i in range(1, max_polls + 1):
        events = poll_once(str(REPO), SmokeRule(), broker, log=print, enable_live_orders=True)
        state = positionStore.load(str(REPO), STRATEGY_ID)
        pos = state.get(SYMBOL)
        print(f"  poll #{i}: status={pos['status'] if pos else '(없음)'}")
        if condition_fn(pos):
            return pos
        time.sleep(2)
    print(f"[중단] {label} - {max_polls}번 poll 안에 도달 못함")
    sys.exit(1)


try:
    broker = KisVtsBroker()
except KisVtsError as e:
    print("[중단]", e)
    sys.exit(1)

print()
print("  poll_once() 실제 KIS 모의투자 왕복 검증")
print("  전략:", STRATEGY_ID, "· 종목:", SYMBOL, "· 수량: 1")
print()

positionStore.save(str(REPO), STRATEGY_ID, {})

print("0) PENDING_ENTRY 직접 심기 (scan_signals 대신 - 실신호가 없어서)")
positionStore.save(str(REPO), STRATEGY_ID,
                    {SYMBOL: {"status": "PENDING_ENTRY", "quantity": 1, "intent_date": "2026-08-21"}})

print()
print("1) poll_once() 반복 -> ENTRY_SUBMITTED -> OPEN 확인")
pos = wait_until(lambda p: p and p["status"] == "OPEN", max_polls=8, label="OPEN 전이")
print("   OPEN 확인. entry_price=", pos["entry_price"], "stop=", pos["stop_price"], "target=", pos["target_price"])

print()
print("2) stop_price를 현재가보다 훨씬 위로 강제 조정 (즉시 STOP 유도)")
state = positionStore.load(str(REPO), STRATEGY_ID)
state[SYMBOL]["stop_price"] = state[SYMBOL]["entry_price"] * 10  # 무슨 가격이든 이 아래
positionStore.save(str(REPO), STRATEGY_ID, state)

print()
print("3) poll_once() 반복 -> EXIT_SUBMITTED -> 체결확인(삭제) 확인")
wait_until(lambda p: p is None, max_polls=8, label="포지션 종료(삭제)")

print()
print("[성공] PENDING_ENTRY -> ENTRY_SUBMITTED -> OPEN -> EXIT_SUBMITTED -> 종료")
print("       실제 KisVtsBroker로 poll_once() 상태기계 전체 검증 완료.")

holdings, cash, _ = broker.client.inquire_balance()
print("       최종 실계좌 확인: 보유", SYMBOL, "=",
      next((h["hldg_qty"] for h in holdings if h["pdno"] == SYMBOL), "0"), "· 예수금=", cash)
