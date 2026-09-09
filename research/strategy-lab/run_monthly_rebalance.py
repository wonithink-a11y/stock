#!/usr/bin/env python
"""월별 리밸런싱 스케줄러 - pbr_value_v1·lowmom60_v1을 KIS 모의투자 계좌에
실제로 태운다. Paper Trading Engine 4단계(2026-08-24, 사용자 승인 후 착수).

  python run_monthly_rebalance.py --strategy pbr_value_v1 --as-of 2026-09-01 --capital 5000000
  python run_monthly_rebalance.py --strategy pbr_value_v1 --as-of 2026-09-01 --capital 5000000 --enable-live-orders

기본은 dry-run - poll_once가 enable_live_orders=False로 불려 즉시 반환하고
broker를 한 번도 안 부른다(2026-08-21에 이미 검증된 그 스위치, 이 스크립트가
새로 만든 게 아니다). scan_rebalance_signals()는 dry-run이든 아니든 항상
로컬 상태(research/strategy-lab/data/paper/*.json)에 PENDING_ENTRY 의도를
기록한다 - scan_signals()의 기존 동작과 동일한 관례(신호 스캔은 매일 1회
확정 기록, 주문 게이트는 poll 쪽에만 있음). 잘못 기록됐다면 그냥 JSON
파일이니 positionStore.save(repo_root, strategy_id, {})로 되돌리면 된다 -
KIS에는 아무 것도 안 나간다.

실거래(제출->체결확인)는 비동기라 한 번 호출로 안 끝난다 - PENDING_ENTRY가
ENTRY_SUBMITTED를 거쳐 OPEN이 되려면, 그리고 나중에 EXIT_SUBMITTED가
종료되려면 이 스크립트를 리밸런싱일 근처 며칠에 걸쳐 반복 실행해야 한다
(poll_once 자체의 설계, engine/live/paperEngine.py 참고). 한 번 실행하고
끝나는 스크립트가 아니다.

전제조건 (사람이 먼저 확인 - 이 스크립트는 아무 것도 자동 갱신하지 않는다):
  1. data/backfill/price/a2a가 --as-of 날짜까지 갱신돼 있어야 한다
     (.github/workflows/price-a2a.yml 수동 트리거, workflow_dispatch 전용 -
     상시 갱신 아님).
  2. pbr_value_v1이면 `node scripts/build-a5-valuation-panel.js --end <날짜>`로
     valuation-panel.jsonl도 먼저 확장해야 한다.
  3. 두 전략 다 `python strategies/<id>/build_selection.py --end <날짜>`로
     selection.json을 그 날짜까지 재계산해 둬야 한다. --as-of가
     selection.json에 없으면 target이 빈 리스트라 아무 것도 안 산다 -
     조용히 넘어가는 게 잘못된 종목을 사는 것보다 낫다(아래 확인).
"""
import argparse
import importlib
import os
import sys
from datetime import datetime, timedelta, timezone

_THIS_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, _THIS_DIR)
REPO_ROOT = os.path.dirname(os.path.dirname(_THIS_DIR))
KST = timezone(timedelta(hours=9))

from engine.live.paperEngine import poll_once, scan_rebalance_signals  # noqa: E402


LATEST_LOOKBACK_DAYS = 40      # 연휴 + 갱신 지연을 넉넉히 덮는다


def _resolve_as_of(rule, wanted):
    """'latest' 면 오늘부터 거슬러 올라가며 selection.json 에 실제로 있는 첫
    리밸런싱일을 찾는다. 캘린더를 따로 안 읽는다 - selection.json 에 있는 날짜가
    곧 그 전략의 리밸런싱일이라, 갱신이 밀렸는지도 이 한 번의 조회로 드러난다.

    ★ 못 찾으면 None 을 돌려주고 호출부가 스킵한다. 아무 날짜나 골라 굴리면
    '어제 신호로 오늘 산다'가 조용히 굳는다(교훈57 - 모르는 건 0이 아니다).
    """
    if wanted != "latest":
        return wanted
    d = datetime.now(KST).date()
    for _ in range(LATEST_LOOKBACK_DAYS):
        s = d.isoformat()
        if rule.selected_symbols(s):
            return s
        d -= timedelta(days=1)
    return None


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--strategy", required=True,
                     choices=["pbr_value_v1", "lowmom60_v1", "pbr_value_v1_combined",
                              "factor_earnings_yield_v1", "foreign_flow5d_v1"])
    ap.add_argument("--as-of", required=True,
                     help="이번 리밸런싱일 (YYYY-MM-DD, selection.json에 있어야 함). "
                          "'latest' 를 주면 selection.json 에 있는 오늘 이하의 최신 "
                          "리밸런싱일을 스스로 찾는다 - 일별 전략용.")
    ap.add_argument("--fixed-hold", action="store_true",
                     help="is_still_selected 를 넘기지 않는다. 보유일수가 고정인 전략"
                          "(foreign_flow5d_v1 = 5세션 고정)은 '다음 리밸런싱에도 뽑혔나'로 "
                          "청산하면 안 된다 - 일별이라 대부분 다음 날 목록에서 빠지고, "
                          "그러면 5세션 고정보유라는 검증된 계약이 깨진다.")
    ap.add_argument("--capital", type=int, required=True, help="이 전략에 배정된 가상자금(원)")
    ap.add_argument("--entry-slices", type=int, default=1,
                    help="목표수량을 며칠에 나눠 살지(기본 1=하루에 전량). 시장충격은 하루 "
                         "참여율의 함수라 자금이 크면 늘린다 - findings/sizing-position-"
                         "count-capacity-2026-09.md 정정 절")
    ap.add_argument("--enable-live-orders", action="store_true",
                     help="실제 KIS 모의투자 주문을 낸다. 없으면 dry-run(broker 전혀 안 부름).")
    args = ap.parse_args()

    rule = importlib.import_module(f"strategies.{args.strategy}.rule")
    strategy_id = rule.PARAMS["strategyId"]

    as_of = _resolve_as_of(rule, args.as_of)
    if as_of is None:
        print(f"[latest] selection.json 에 최근 {LATEST_LOOKBACK_DAYS}일 내 리밸런싱일이 "
              f"없다 - '{strategy_id}' 스킵. 갱신이 밀린 것이지 신호가 없는 게 아니다.")
        return
    args.as_of = as_of

    target = rule.selected_symbols(args.as_of)
    if not target:
        print(f"[{args.as_of}] '{strategy_id}' selection.json에 이 날짜가 없음 - "
              f"build_selection.py --end {args.as_of}로 먼저 확장했는지 확인. 아무 것도 안 함.")
        return
    print(f"[{args.as_of}] {strategy_id} 이번 달 선택 {len(target)}종목")

    events = scan_rebalance_signals(REPO_ROOT, rule, args.as_of, args.capital, log=print,
                                     entry_slices=args.entry_slices)
    print(f"신규 진입 의도(로컬 상태 기록) {len(events)}건 - "
          f"나머지는 이미 보유중이거나 슬롯예산/가격데이터 부족으로 스킵")

    if not args.enable_live_orders:
        print("[dry-run] --enable-live-orders 없음 - KIS에는 아무 것도 안 나갔다.")
        return

    # 고정 보유 전략은 이 콜백을 넘기지 않는다 - poll_once 가 그 분기를 통째로
    # 건너뛰고 stop/target/시간청산만 본다(기존 dummy_sma20 경로와 동일).
    is_still_selected = (None if args.fixed_hold
                          else (lambda symbol: rule.still_selected(symbol, args.as_of)))  # noqa: E731
    from engine.live.kisVtsBroker import KisVtsBroker  # dry-run 경로는 KIS 토큰 자체가 필요 없게 지연 임포트
    broker = KisVtsBroker()
    poll_events = poll_once(REPO_ROOT, rule, broker, log=print, enable_live_orders=True,
                             is_still_selected=is_still_selected)
    print(f"poll_once 이벤트 {len(poll_events)}건 - PENDING_ENTRY/EXIT_SUBMITTED가 남아있으면 "
          f"이 스크립트를 다시 실행해 체결을 계속 확인해야 한다.")


if __name__ == "__main__":
    main()
