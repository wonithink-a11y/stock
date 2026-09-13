#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""RV20 sizing 규칙(동결, futures-rv20-sizing-rule-freeze-2026-09-13.md,
Rule B: Q5->0x) 신호를 KIS 모의투자 선물 계좌에 실제로 반영하는 오케스트레이션.

절차(전부 이 순서를 지킨다 - 순서를 바꾸지 않는다):
1. rv20_sizing_paper_signal.compute_today_signal() - 동결 규칙 그대로,
   네트워크 없이 목표 익스포저(0/1x)를 계산.
2. KIS 계좌 잔고 조회(읽기 전용) - 현재 보유 계약 수 확인.
3. 전광판에서 오늘 front-month 계약 코드를 조회(읽기 전용).
4. 목표 계약수 - 현재 보유 = 주문 수량. 0이면 아무 것도 안 한다.
5. **기본값은 항상 dry-run**이다 - 실제 주문은 `--confirm-live`를
   명시적으로 줘야만 나간다. 이 스크립트는 자동화(cron/VM)에 연결돼
   있지 않다 - 매번 사람이 실행하고 사람이 --confirm-live를 붙인다.

    python rv20_paper_order.py --capital 250000000                # dry-run(기본)
    python rv20_paper_order.py --capital 250000000 --confirm-live  # 실제 주문
"""
import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from rv20_sizing_paper_signal import compute_today_signal
from engine.live.kisVtsFuturesClient import KisVtsFuturesClient, KisVtsFuturesError

MULT = 250_000.0


def current_position_qty(positions):
    """잔고 output1에서 순보유수량 합계(선물은 매수/매도 각각 행이 올 수 있어
    부호 있는 수량으로 합산 - 필드명은 실제 응답에서 확인, hldg_qty 계열
    없으면 0으로 취급하지 않고 예외를 낸다(교훈57 - 모르는 건 0이 아니다)."""
    if not positions:
        return 0
    qty_keys = [k for k in positions[0] if "qty" in k.lower()]
    if not qty_keys:
        raise KisVtsFuturesError(
            f"잔고 응답에 수량 필드를 못 찾음 - 필드 목록 확인 필요: {list(positions[0].keys())}")
    total = 0
    for p in positions:
        for k in qty_keys:
            v = p.get(k)
            if v not in (None, ""):
                try:
                    total += int(v)
                except ValueError:
                    pass
                break
    return total


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--capital", type=float, required=True, help="이 실험에 배정한 자본(원)")
    ap.add_argument("--confirm-live", action="store_true", help="실제로 주문을 낸다(기본은 dry-run)")
    args = ap.parse_args()

    print("=== 1) 동결 규칙 신호 계산 (네트워크 없음) ===")
    signal = compute_today_signal()
    print(f"기준일 {signal['asOfDate']}  percentile={signal['pctRv20Rolling252']:.3f}"
          f"  ->  목표 익스포저 {signal['targetWeight']}x")

    client = KisVtsFuturesClient()

    print("\n=== 2) 계좌 잔고 조회 (읽기 전용) ===")
    positions, summary = client.inquire_balance()
    held_qty = current_position_qty(positions)
    print(f"현재 보유 계약수: {held_qty}")

    print("\n=== 3) Front-month 계약 조회 (읽기 전용) ===")
    front = client.resolve_front_month()
    print(f"front: {front['name']} ({front['code']})  현재가 {front['price']}  "
          f"매도호가 {front['ask']}  매수호가 {front['bid']}  거래량 {front['volume']}")

    notional_per_contract = front["price"] * MULT
    target_notional = args.capital * signal["targetWeight"]
    target_qty = int(round(target_notional / notional_per_contract)) if notional_per_contract > 0 else 0
    delta = target_qty - held_qty

    print(f"\n=== 4) 목표 대비 차이 ===")
    print(f"배정자본 {args.capital:,.0f}원 / 계약당 명목가치 {notional_per_contract:,.0f}원"
          f"  ->  목표 계약수 {target_qty} (현재 {held_qty}, 차이 {delta:+d})")

    if delta == 0:
        print("\n조정 불필요 - 주문 없음.")
        return

    side = "BUY" if delta > 0 else "SELL"
    qty = abs(delta)
    # 즉시 체결 가능성을 높이려고 상대편 최우선호가를 지정가로 쓴다
    # (매수는 매도호가, 매도는 매수호가) - 시장가(NMPR_TYPE_CD=02) 지원
    # 여부가 모의투자에서 미검증이라 지정가로 우회하는 방식.
    limit_price = front["ask"] if side == "BUY" else front["bid"]

    print(f"\n=== 5) 주문 미리보기 ({'실주문' if args.confirm_live else 'DRY-RUN'}) ===")
    result = client.order(side, front["code"], qty, limit_price, dry_run=not args.confirm_live)
    print(f"side={side}  code={front['code']}  qty={qty}  limit_price={limit_price}"
          f"  (상대편 최우선호가 - 즉시체결 노림)")
    print("요청 바디:", result["requestBody"])
    if args.confirm_live:
        print("응답:", result.get("response", {}).get("msg1"))
        print("주문번호:", (result.get("response", {}).get("output") or {}).get("ODNO"))
    else:
        print("\n(dry-run - 아직 아무 것도 전송하지 않았다. --confirm-live를 붙이면 실제로 나간다.)")


if __name__ == "__main__":
    main()
