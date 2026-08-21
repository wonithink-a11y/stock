"""probe-kis-vts-order-smoke.py — KIS 모의투자 실제 주문 1건 왕복 스모크 테스트.

Paper Trading Engine 3단계 - engine/live/kisVtsClient.py를 통해 005930
(삼성전자) 1주를 시장가로 실제 매수한 뒤, 잔고에 반영됐는지 확인하고,
같은 수량을 다시 매도해 계좌를 원상태(보유 0)로 되돌린다. 모의투자
계좌(가상자금)에만 영향을 준다 - 실계좌는 이 스크립트가 아예 모른다.

사용자 명시 승인(2026-08-21, "응진행해줘") 후 실행. 장 시간 외에는 주문이
거부될 수 있다 - 그것도 정상 응답이고 배관이 작동한다는 뜻이다(거부
사유가 명확한 에러로 돌아온다는 것 자체가 확인 대상 중 하나).

사용:
    python scripts/probe-kis-vts-order-smoke.py
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

from engine.live.kisVtsClient import KisVtsClient, KisVtsError  # noqa: E402

SYMBOL = "005930"  # 삼성전자 - 유동성 최상, 스모크 테스트에 안전한 선택
QTY = 1


def main():
    try:
        client = KisVtsClient()
    except KisVtsError as e:
        print("[중단]", e)
        sys.exit(1)

    print()
    print("  KIS 모의투자 주문 왕복 스모크 테스트")
    print("  종목:", SYMBOL, "· 수량:", QTY, "· 시장가")
    print()

    print("1) 매수 전 잔고 확인")
    holdings, cash, eval_total = client.inquire_balance()
    print("   보유종목:", len(holdings), "· 예수금:", cash)
    before_qty = next((h["hldg_qty"] for h in holdings if h["pdno"] == SYMBOL), "0")

    print()
    print("2) 시장가 매수 주문 제출")
    try:
        buy_resp = client.order_cash("BUY", SYMBOL, QTY)
    except KisVtsError as e:
        print("[실패]", e)
        print("   (장 시간 외 거부 등 정상 응답일 수 있다 - 에러 메시지가 명확하면 배관 자체는 확인된 것)")
        sys.exit(1)
    order_no = buy_resp.get("output", {}).get("ODNO")
    print("   주문 접수됨. 주문번호:", order_no)

    print()
    print("3) 체결 확인 대기 (3초)")
    time.sleep(3)
    holdings, cash, eval_total = client.inquire_balance()
    after_qty = next((h["hldg_qty"] for h in holdings if h["pdno"] == SYMBOL), "0")
    print("   매수 후 보유수량:", after_qty, "(매수 전:", before_qty, ")")
    if int(after_qty) <= int(before_qty):
        print("   [주의] 아직 잔고에 반영 안 됨 - 체결까지 시간이 더 걸릴 수 있다. 되팔기는 건너뛴다.")
        sys.exit(0)

    print()
    print("4) 같은 수량 시장가 매도 (계좌를 원상태로)")
    try:
        sell_resp = client.order_cash("SELL", SYMBOL, QTY)
    except KisVtsError as e:
        print("[실패] 매도 주문 실패 - 수동으로 정리 필요:", e)
        sys.exit(1)
    print("   매도 접수됨. 주문번호:", sell_resp.get("output", {}).get("ODNO"))

    print()
    print("5) 최종 잔고 확인 (3초 대기)")
    time.sleep(3)
    holdings, cash, eval_total = client.inquire_balance()
    final_qty = next((h["hldg_qty"] for h in holdings if h["pdno"] == SYMBOL), "0")
    print("   최종 보유수량:", final_qty, "· 예수금:", cash)

    print()
    print("[성공] 매수->체결확인->매도 왕복 전부 정상 동작." if final_qty == "0"
          else "[부분성공] 매수/매도는 됐으나 최종 수량이 0이 아니다 - 수동 확인 필요.")


if __name__ == "__main__":
    main()
