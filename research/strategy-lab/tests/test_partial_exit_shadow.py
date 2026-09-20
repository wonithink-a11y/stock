"""부분 익절 그림자의 판정·중복 append·잔여 수익률 self-check (네트워크 없음).

pytest 는 run_partial_exit_shadow.selftest() 를 자동으로 안 부르므로(assert 기반이라
실패하면 예외가 난다) 여기서 한 번 감싼다 - 안 그러면 회귀에 안 잡힌다.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import run_partial_exit_shadow as shadow


def test_selftest():
    shadow.selftest()


if __name__ == "__main__":
    test_selftest()
