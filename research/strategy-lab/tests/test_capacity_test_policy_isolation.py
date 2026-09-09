"""run_capacity_test.py 가 라이브 policy.json 을 건드리지 않는지 지킨다.

원래는 policy.json 을 policy_100.json 으로 덮어쓰고 finally 에서 되돌렸다.
크래시는 finally 가 막지만 경합은 못 막는다 - 페이퍼 엔진이 10분마다 같은
파일을 읽으므로, 30분짜리 캐패시티 실행 중에 실주문이 100포지션 정책으로
나간다. 지금은 load_strategy 로 모듈을 새로 만들어 PARAMS 만 메모리에서
바꾼다. 이 테스트는 그 전제 두 개를 고정한다.
"""
import json
import os
import sys

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
LAB = os.path.join(REPO_ROOT, "research", "strategy-lab")
sys.path.insert(0, LAB)

from engine.runner import load_strategy

POLICY = os.path.join(LAB, "strategies", "factor_earnings_yield_v1", "policy.json")


def test_params_are_per_load_and_never_written_back():
    """PARAMS 를 고쳐도 (a) 파일이 안 바뀌고 (b) 다음 load 에 안 샌다."""
    before = open(POLICY, encoding="utf-8").read()

    a = load_strategy("factor_earnings_yield_v1", REPO_ROOT)
    original = a.PARAMS["portfolio"]["maxPositions"]
    a.PARAMS["portfolio"]["maxPositions"] = 999

    b = load_strategy("factor_earnings_yield_v1", REPO_ROOT)
    assert b.PARAMS["portfolio"]["maxPositions"] == original, \
        "load_strategy 가 PARAMS 를 공유한다 - 인메모리 오버라이드가 다른 실행에 샌다"
    assert open(POLICY, encoding="utf-8").read() == before, "policy.json 이 바뀌었다"


def test_capacity_script_has_no_policy_write():
    """되돌아오는 걸 막는 트립와이어. 파일 복사로 정책을 바꾸는 방식 금지."""
    src = open(os.path.join(LAB, "run_capacity_test.py"), encoding="utf-8").read()
    assert "shutil" not in src, "run_capacity_test.py 가 다시 파일을 복사한다"
    for n in (20, 50, 100):
        assert not os.path.exists(
            os.path.join(LAB, "strategies", "factor_earnings_yield_v1", f"policy_{n}.json")
        ), f"policy_{n}.json 이 되살아났다 - 인메모리 오버라이드면 필요 없다"

    # policy_30.json 은 이 스크립트와 무관하게 살아 있어야 한다 -
    # market_comparison_kr_2026_09.py 가 동결 기준본으로 읽는다.
    assert os.path.exists(
        os.path.join(LAB, "strategies", "factor_earnings_yield_v1", "policy_30.json")
    ), "policy_30.json 이 사라졌다 - market_comparison_kr_2026_09.py 가 깨진다"


if __name__ == "__main__":
    test_params_are_per_load_and_never_written_back()
    test_capacity_script_has_no_policy_write()
    print("OK")
