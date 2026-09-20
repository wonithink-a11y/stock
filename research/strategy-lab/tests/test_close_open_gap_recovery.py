"""O5(갭하락 후 종가 회복) 결과 스크립트의 self-check (네트워크·캐시 없음). selftest 는 종료코드를 돌려주므로 감싼다."""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "futures"))

import close_open_gap_recovery as m


def test_selftest():
    assert m.selftest() == 0


if __name__ == "__main__":
    test_selftest()
