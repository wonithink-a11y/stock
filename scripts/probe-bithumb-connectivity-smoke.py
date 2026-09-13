"""probe-bithumb-connectivity-smoke.py — 키 없이 빗썸 공개 API(시세·호가)만
확인한다. BithumbClient의 공개 경로가 살아있는지 보는 1회성 정찰 스크립트
(probe-upbit-connectivity-smoke.py와 동일 관례).

사용:
    python scripts/probe-bithumb-connectivity-smoke.py
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

from engine.live.bithumbClient import BithumbClient, BithumbError  # noqa: E402

MARKET = "KRW-BTC"

client = BithumbClient()

print()
print("  빗썸 공개 API 연결 확인 (키 불필요)")
print()

try:
    price = client.get_ticker(MARKET)
    print(f"  1) 현재가  {MARKET} = {price:,.0f} KRW")
except BithumbError as e:
    print("  [실패] 시세 조회:", e)
    sys.exit(1)

try:
    book = client.get_orderbook(MARKET)
    units = book.get("orderbook_units", [])
    top = units[0] if units else {}
    print(f"  2) 호가 {len(units)}단계 수신, 1호가 매도 "
          f"{top.get('ask_price', '?'):,.0f} / 매수 {top.get('bid_price', '?'):,.0f}")
except BithumbError as e:
    print("  [실패] 호가 조회:", e)
    sys.exit(1)

print()
print("  [성공] 공개 API 정상.")
