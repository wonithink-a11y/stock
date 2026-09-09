#!/usr/bin/env python3
"""A2a 재수집이 이번 달에 필요한지 판정한다 (price-a2a.yml 의 게이트).

왜 게이트가 필요한가
--------------------
A2a 는 매 실행이 **전 연도 파일을 다시 쓴다.** "현재 상장분"만 담는 정의라
상장폐지분이 과거에서도 빠지고 KRX 수정주가 재산정이 소급되기 때문이다 -
실측 2026-09-03 커밋에서 2014년 파일까지 바뀌었다(4,794,388 -> 4,180,193 bytes).
한 번에 약 122MB 의 새 blob 이 생긴다.

그래서 일간 스케줄은 못 붙인다: 122MB x 250거래일 = **연 30GB**, 저장소 .git 이
지금 1.6GB 다. 월 1회면 연 1.5GB 로 지금 수동 주기와 같다.

cron 은 "매월 첫 거래일"을 표현할 수 없으므로 1~5일에 걸어두고 이 게이트로
한 번만 실제 수집한다.

판정
----
**이번 달 데이터가 이미 하루라도 들어 있으면 스킵.** 캘린더를 안 본다 -
calendar.json 은 하루 늦게 갱신돼서(실측: 선언 08:00 UTC, 실제 12:26~15:45 UTC)
매월 1일 저녁에는 아직 그 달을 모른다. 캘린더에 의존하면 첫 거래일 수집이
하루 밀리고, 그만큼 리밸런싱 진입도 밀린다.

사용법
------
  python scripts/check-a2a-refresh-needed.py            # needed=true/false 출력
  python scripts/check-a2a-refresh-needed.py --selftest
"""
import json
import os
import sys
from datetime import datetime, timedelta, timezone

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DIAGNOSTICS = os.path.join(REPO_ROOT, "data", "backfill", "price", "a2a", "_diagnostics.json")
KST = timezone(timedelta(hours=9))


def decide(actual_data_to, today):
    """(needed, 이유). actual_data_to 가 없으면(첫 수집) 무조건 필요하다 -
    모르는 것을 '최신'으로 읽지 않는다(교훈57)."""
    if not actual_data_to:
        return True, "A2a 산출물이 없다(첫 수집)"
    if actual_data_to[:7] < today[:7]:
        return True, f"이번 달({today[:7]}) 데이터가 없다 - 현재 {actual_data_to} 까지"
    return False, f"이미 {actual_data_to} 까지 있다 - 이번 달 수집 완료"


def _selftest():
    assert decide("2026-09-30", "2026-10-01") == (True, decide("2026-09-30", "2026-10-01")[1])
    assert decide("2026-09-30", "2026-10-01")[0] is True
    assert decide("2026-10-01", "2026-10-02")[0] is False      # 같은 달 - 스킵
    assert decide("2026-10-01", "2026-10-31")[0] is False      # 달 끝까지 스킵
    assert decide(None, "2026-10-01")[0] is True               # 첫 수집
    assert decide("", "2026-10-01")[0] is True
    # 연말/연초 경계 - 문자열 비교가 12월->1월에서 뒤집히지 않아야 한다
    assert decide("2026-12-30", "2027-01-04")[0] is True
    assert decide("2027-01-04", "2027-01-29")[0] is False
    print("selftest OK - decide()")


def main():
    if "--selftest" in sys.argv:
        _selftest()
        return 0
    actual = None
    if os.path.exists(DIAGNOSTICS):
        with open(DIAGNOSTICS, encoding="utf-8") as f:
            actual = json.load(f).get("actualDataTo")
    today = datetime.now(KST).strftime("%Y-%m-%d")
    needed, why = decide(actual, today)
    print(f"needed={'true' if needed else 'false'}")
    print(f"reason={why}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
