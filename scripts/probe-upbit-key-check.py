"""probe-upbit-key-check.py — 발급받은 UPBIT_ACCESS_KEY/UPBIT_SECRET_KEY가
유효한지 잔고 조회(GET /v1/accounts, 읽기 전용)로만 확인한다. 주문은
절대 내지 않는다 - 이 스크립트가 UpbitBroker(실전 주문 클래스)를 참조하는
일은 없다. scripts/setup-upbit-key.py로 먼저 .env에 키를 넣은 뒤 실행.

값은 절대 출력하지 않는다 - 잔고 통화별 보유량만 보여준다.

사용:
    python scripts/probe-upbit-key-check.py
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

try:
    client = UpbitClient()
    accounts = client.get_accounts()
except UpbitError as e:
    print("  [실패]", e)
    sys.exit(1)

print()
print("  업비트 키 확인 (읽기 전용 - 주문 없음)")
print()
if not accounts:
    print("  잔고가 비어 있습니다(정상 - 신규 계정일 수 있음).")
else:
    for a in accounts:
        print(f"  {a['currency']:6s}  보유 {a['balance']}  잠김 {a['locked']}")
print()
print("  [성공] 키가 유효합니다.")
