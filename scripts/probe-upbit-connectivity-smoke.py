"""probe-upbit-connectivity-smoke.py — 키 없이 업비트 공개 API(시세·캔들)만
확인한다. UpbitClient의 공개 경로가 살아있는지 보는 1회성 정찰 스크립트
(probe-kis-vts-* 명명 관례와 동일).

사용:
    python scripts/probe-upbit-connectivity-smoke.py
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

from engine.live.upbitClient import UpbitClient, UpbitError  # noqa: E402

MARKET = "KRW-BTC"

client = UpbitClient()

print()
print("  업비트 공개 API 연결 확인 (키 불필요)")
print()

try:
    price = client.get_ticker(MARKET)
    print(f"  1) 현재가  {MARKET} = {price:,.0f} KRW")
except UpbitError as e:
    print("  [실패] 시세 조회:", e)
    sys.exit(1)

try:
    candles = client.get_candles_days(MARKET, count=5)
    print(f"  2) 일봉 {len(candles)}개 수신, 최신: "
          f"{candles[0]['candle_date_time_kst']}  종가 {candles[0]['trade_price']:,.0f}")
except UpbitError as e:
    print("  [실패] 캔들 조회:", e)
    sys.exit(1)

print()
print("  [성공] 공개 API 정상.")
