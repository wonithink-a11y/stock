"""확장 연간 재무 수집기의 순수 함수 self-check (네트워크 없음). selftest 는 종료코드를 돌려주므로 감싼다."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import build_extended_financials_panel as m


def test_selftest():
    assert m.selftest() == 0


if __name__ == "__main__":
    test_selftest()
