"""분기 순이익 가속(ACC2) 결과 스크립트의 self-check (네트워크·캐시 없음). selftest 는 종료코드를 돌려주므로 감싼다."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import quarterly_acceleration_event as m


def test_selftest():
    assert m.selftest() == 0


if __name__ == "__main__":
    test_selftest()
