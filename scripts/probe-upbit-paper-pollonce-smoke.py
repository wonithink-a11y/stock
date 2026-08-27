"""probe-upbit-paper-pollonce-smoke.py — UpbitPaperBroker로 poll_once() 상태
기계 전체를 실제 업비트 공개 시세로 1회 왕복 검증한다. 키 불필요, 진짜
주문 없음(probe-kis-vts-poll-once-smoke.py와 같은 구조, 업비트-연동-
2026-08-27 계획 문서 "검증 방법" 3번).

PENDING_ENTRY를 이 스크립트가 직접 심는다(scan_signals 대신 - 배관 검증이
목적이지 신호 로직 검증이 아니다, KIS 스모크와 동일 이유). OPEN 전이 후에는
stop_price를 현재가보다 훨씬 위로 올려 즉시 STOP 청산을 유도한다.

사용:
    python scripts/probe-upbit-paper-pollonce-smoke.py
"""
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
from engine.live.paperEngine import poll_once  # noqa: E402
from engine.live.upbitPaperBroker import UpbitPaperBroker  # noqa: E402

STRATEGY_ID = "upbit_paper_pollonce_smoke"
MARKET = "KRW-BTC"


class SmokeRule:
    PARAMS = {
        "strategyId": STRATEGY_ID,
        "testUniverse": [MARKET],
        "risk": {"stopPct": 0.05, "targetPct": 0.10, "maxHoldingSessions": 20},
        "position": {"notionalPerPosition": 10000, "maxPositions": 1},
    }


def wait_until(condition_fn, max_polls, label):
    for i in range(1, max_polls + 1):
        events = poll_once(str(REPO), SmokeRule(), broker, log=print, enable_live_orders=True)
        state = positionStore.load(str(REPO), STRATEGY_ID)
        pos = state.get(MARKET)
        print(f"  poll #{i}: status={pos['status'] if pos else '(없음)'}")
        if condition_fn(pos):
            return pos
        time.sleep(1)
    print(f"[중단] {label} - {max_polls}번 poll 안에 도달 못함")
    sys.exit(1)


broker = UpbitPaperBroker()

print()
print("  poll_once() 업비트 모의(로컬 시뮬레이션) 왕복 검증")
print("  전략:", STRATEGY_ID, "· 마켓:", MARKET, "· 수량: 0.0001")
print()

positionStore.save(str(REPO), STRATEGY_ID, {})

print("0) PENDING_ENTRY 직접 심기 (scan_signals 대신 - 배관 검증이 목적)")
positionStore.save(str(REPO), STRATEGY_ID,
                    {MARKET: {"status": "PENDING_ENTRY", "quantity": 0.0001, "intent_date": "2026-08-27"}})

print()
print("1) poll_once() 반복 -> ENTRY_SUBMITTED -> OPEN 확인")
pos = wait_until(lambda p: p and p["status"] == "OPEN", max_polls=5, label="OPEN 전이")
print("   OPEN 확인. entry_price=", pos["entry_price"], "stop=", pos["stop_price"], "target=", pos["target_price"])

print()
print("2) stop_price를 현재가보다 훨씬 위로 강제 조정 (즉시 STOP 유도)")
state = positionStore.load(str(REPO), STRATEGY_ID)
state[MARKET]["stop_price"] = state[MARKET]["entry_price"] * 10
positionStore.save(str(REPO), STRATEGY_ID, state)

print()
print("3) poll_once() 반복 -> EXIT_SUBMITTED -> 체결확인(삭제) 확인")
wait_until(lambda p: p is None, max_polls=5, label="포지션 종료(삭제)")

print()
print("[성공] PENDING_ENTRY -> ENTRY_SUBMITTED -> OPEN -> EXIT_SUBMITTED -> 종료")
print("       UpbitPaperBroker로 poll_once() 상태기계 전체 검증 완료(실제 주문 없음).")
