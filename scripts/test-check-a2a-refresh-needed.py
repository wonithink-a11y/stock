"""check-a2a-refresh-needed.py 회귀 - scripts/test-*.py 자동 발견에 걸리게 하는 얇은 래퍼.

게이트가 틀리면 두 방향으로 조용히 아프다: true 로 굳으면 매일 122MB 씩 저장소가
불고, false 로 굳으면 이번 달 A2a 가 영영 안 받아져 selection 이 못 만들어지고
페이퍼 엔진이 그 달에 멈춘다.
"""
import importlib.util
import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
_spec = importlib.util.spec_from_file_location(
    "check_a2a", os.path.join(_HERE, "check-a2a-refresh-needed.py"))
m = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(m)

m._selftest()

# 래퍼가 실제로 무언가를 재는지 확인한다(교훈72 - 통과가 정보를 주는가).
assert m.decide("2026-09-30", "2026-10-01")[0] is True, "새 달이면 수집해야 한다"
assert m.decide("2026-10-01", "2026-10-05")[0] is False, "같은 달은 한 번만"
print("check-a2a-refresh-needed: OK")
