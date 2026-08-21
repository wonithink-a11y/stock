#!/usr/bin/env python
"""Paper Trading Engine 배관 검증 드라이버 - dummy_sma20을 여러 거래일에 걸쳐
run_once()로 반복 호출해 PENDING_ENTRY -> OPEN -> EXIT 전이와 재시작(restart)
안전성을 확인한다.

실제 운영에서는 이 스크립트가 하루 1회(장 마감 후) 딱 한 세션분만 호출되는
크론 잡이 된다 - 이 드라이버는 그걸 흉내 내 과거 날짜 구간을 하루씩 돌린다
(실시간 데이터 없이 로컬에서 배관을 검증하는 용도, A2a 과거 데이터만 읽는다).

  python run_paper_engine.py --start 2024-01-02 --end 2024-06-28
  python run_paper_engine.py --reset   # 포지션 상태 파일 삭제 후 처음부터

재시작 안전성 확인 방법: 같은 명령을 두 번 나눠 실행해도(--start를 중간
날짜로) 이전 실행이 남긴 state 파일을 이어받아 계속돼야 한다 - 이 스크립트
자체가 그걸 강제하지 않고 자연히 그렇게 되는지가 검증 대상이다.
"""
import argparse
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from engine.data.a2aProvider import A2aProvider  # noqa: E402
from engine.data.calendar import TradingCalendar  # noqa: E402
from engine.live import positionStore  # noqa: E402
from engine.live.paperEngine import run_once  # noqa: E402
from engine.runner import load_strategy  # noqa: E402


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--start", default="2024-01-02")
    ap.add_argument("--end", default="2024-03-29")
    ap.add_argument("--reset", action="store_true", help="포지션 상태 파일을 지우고 처음부터 시작")
    args = ap.parse_args()

    repo_root = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".."))
    rule = load_strategy("dummy_sma20", repo_root)
    strategy_id = rule.PARAMS["strategyId"]

    if args.reset:
        positionStore.save(repo_root, strategy_id, {})
        print("state reset:", strategy_id)

    calendar = TradingCalendar(repo_root=repo_root)
    sessions = calendar.sessions_between(args.start, args.end)
    print(f"running {len(sessions)} sessions: {args.start} ~ {args.end}")

    # 스모크 드라이버 전용 최적화 - 실운영 크론은 하루 1회만 부르므로 이 경로를
    # 안 탄다(run_once의 bars_by_ticker 인자가 None이면 그때그때 하루치만 읽음).
    a2a = A2aProvider(repo_root=repo_root, use_cache=True)
    bars_by_ticker = a2a.load(set(rule.PARAMS["testUniverse"]), calendar.days[0], args.end,
                               universe_hash="paper-skeleton-v0")

    all_events = []
    for as_of in sessions:
        events = run_once(repo_root, rule, as_of, bars_by_ticker=bars_by_ticker)
        all_events.extend(events)

    final_state = positionStore.load(repo_root, strategy_id)
    print("\n=== summary ===")
    print(f"total events: {len(all_events)}")
    for etype in ("INTENT_ENTRY", "FILL_ENTRY", "FILL_EXIT_STOP", "FILL_EXIT_TARGET", "FILL_EXIT_TIME_EXIT"):
        n = sum(1 for e in all_events if e["type"] == etype)
        print(f"  {etype}: {n}")
    realized_pnl = sum(e["pnl"] for e in all_events if "pnl" in e)
    print(f"  realized pnl: {round(realized_pnl, 2)}")
    print(f"  open/pending at end: {list(final_state.keys())}")
    print(f"  state file: research/strategy-lab/data/paper/{strategy_id}_positions.json")


if __name__ == "__main__":
    main()
