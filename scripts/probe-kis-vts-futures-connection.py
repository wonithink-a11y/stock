"""probe-kis-vts-futures-connection.py — KIS 모의투자(VTS) 국내선물옵션
연결 확인. 읽기 전용(잔고 조회만, 주문 API는 호출하지 않는다).

`probe-kis-vts-connection.py`(국내주식)와 같은 목적·같은 원칙이다 -
이 스크립트가 성공해야만 다음 단계(실제 주문, rv20_sizing_paper_signal.py
+ kisVtsFuturesClient.order)로 넘어간다. 선물 계좌는 주식 계좌와 완전히
별도(앱키·계좌번호·계좌상품코드 "03")라 별도 스모크테스트가 필요하다.

입력: .env의 KIS_VTS_FUTURES_APP_KEY · KIS_VTS_FUTURES_APP_SECRET ·
      KIS_VTS_FUTURES_ACCOUNT_NO (scripts/setup-keys-interactive.py로 채운다)
출력: 예수금·평가금 요약만(화면에 전체 응답 원문은 안 찍는다).

사용:
    python scripts/probe-kis-vts-futures-connection.py
"""
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "research" / "strategy-lab"))

for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(errors="replace")
    except Exception:
        pass

from engine.live.kisVtsFuturesClient import KisVtsFuturesClient, KisVtsFuturesError


def main():
    print("KIS 모의투자(VTS) 선물옵션 연결 확인 - 읽기 전용(잔고 조회만)\n")
    try:
        client = KisVtsFuturesClient()
    except KisVtsFuturesError as e:
        print(f"[중단] {e}")
        sys.exit(1)

    print(f"  계좌: {client.cano}-{client.acnt_prdt_cd}")
    try:
        positions, summary = client.inquire_balance()
    except KisVtsFuturesError as e:
        print(f"[실패] {e}")
        sys.exit(1)

    print(f"\n[성공] 토큰 발급 + 잔고 조회 완료")
    print(f"  보유 종목 수: {len(positions)}")
    # 예수금·평가금 필드명은 실제 응답을 받아봐야 확정된다(공식 예제에
    # docstring만 있고 output2 필드 스키마 예시가 없었다, 2026-09-13 확인) -
    # 여기서는 summary dict를 그대로 몇 개만 보여준다(값 자체는 모의투자라
    # 민감정보 아니지만, 원칙대로 전체 원문은 안 찍는다).
    interesting_keys = [k for k in summary if any(
        s in k.lower() for s in ("dnca", "evlu", "amt", "profit", "pnl"))]
    if interesting_keys:
        print("  요약(추정 필드):")
        for k in interesting_keys[:10]:
            print(f"    {k} = {summary[k]}")
    else:
        print(f"  요약 키 목록(필드명 확인용): {list(summary.keys())[:20]}")
    print("\n다음 단계: rv20_sizing_paper_signal.py로 목표 계약수를 계산한 뒤,"
          " kisVtsFuturesClient.order(..., dry_run=True)로 요청 바디를 먼저 눈으로 확인한다.")


if __name__ == "__main__":
    main()
