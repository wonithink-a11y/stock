"""미국 ETF 30주선 기울기 스크립트의 self-check (네트워크 없음).

selftest() 는 실패를 예외가 아니라 종료코드로 돌려주므로 여기서 감싸 회귀에 잡히게 한다.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import us_etf_30wma_slope as m


def test_selftest():
    assert m.selftest() == 0


if __name__ == "__main__":
    test_selftest()
