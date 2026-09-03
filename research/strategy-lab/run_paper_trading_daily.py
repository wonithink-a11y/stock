#!/usr/bin/env python
"""일별 페이퍼 트레이딩 폴링 - VM 크론 진입점 (Paper Trading Engine 5단계).

run_monthly_rebalance.py(4단계, 2026-08-24)를 매일 반복 호출하는 얇은
래퍼일 뿐이다 - 새 신호 로직은 없다. "이번 달 리밸런싱일"(월 첫 거래일)을
캘린더에서 계산해 pbr_value_v1·lowmom60_v1 두 전략에 그대로 넘긴다.

selection.json에 이번 달이 아직 없으면(A2a·build_selection.py 월간
리프레시가 안 됐으면) run_monthly_rebalance.py가 스스로 "아무 것도 안 함"
으로 조용히 넘어간다(기존 동작, 이 스크립트가 새로 판단하지 않는다) -
그래서 이 스크립트를 매일(장중 여러 번) 그냥 반복 실행해도 안전하다:
- 리밸런싱일이 아직 준비 안 됐으면: 조용히 스킵
- 이미 처리된 상태(포지션 OPEN, 신규 진입 없음)면: scan은 no-op,
  poll_once는 stop/target/time·재선택 여부만 확인

월간 리프레시(A2a 새로고침 -> valuation-panel.js -> build_selection.py)는
이 스크립트가 자동으로 하지 않는다 - run_monthly_rebalance.py 자신의
전제조건 그대로, 사람이 매달 먼저 확인한다.

  python run_paper_trading_daily.py                  # 실주문
  python run_paper_trading_daily.py --dry-run
"""
import argparse
import os
import subprocess
import sys
from datetime import datetime, timedelta, timezone

_THIS_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, _THIS_DIR)
REPO_ROOT = os.path.dirname(os.path.dirname(_THIS_DIR))
KST = timezone(timedelta(hours=9))

STRATEGIES = [("pbr_value_v1", 5_000_000), ("lowmom60_v1", 5_000_000)]


def this_month_rebalance_date():
    from engine.data.calendar import TradingCalendar
    calendar = TradingCalendar(repo_root=REPO_ROOT)
    ym = datetime.now(KST).strftime("%Y-%m")
    days = calendar.sessions_between(f"{ym}-01", f"{ym}-31")
    return days[0] if days else None


def _selftest():
    d = this_month_rebalance_date()
    assert d is not None, "캘린더에서 이번 달 거래일을 못 찾음"
    assert d[:7] == datetime.now(KST).strftime("%Y-%m"), f"이번 달이 아닌 날짜: {d}"
    print(f"selftest OK - this_month_rebalance_date() = {d}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--selftest", action="store_true")
    args = ap.parse_args()

    if args.selftest:
        _selftest()
        return

    as_of = this_month_rebalance_date()
    if as_of is None:
        print("이번 달 거래일이 캘린더에 없음 - 스킵")
        return

    for strategy, capital in STRATEGIES:
        cmd = [sys.executable, os.path.join(_THIS_DIR, "run_monthly_rebalance.py"),
               "--strategy", strategy, "--as-of", as_of, "--capital", str(capital)]
        if not args.dry_run:
            cmd.append("--enable-live-orders")
        print(f"=== {strategy} ({as_of}) ===")
        subprocess.run(cmd, cwd=_THIS_DIR, check=False)


if __name__ == "__main__":
    main()
