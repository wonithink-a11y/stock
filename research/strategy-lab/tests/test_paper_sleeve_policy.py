"""라이브 페이퍼 슬리브의 슬롯 파라미터 tripwire.

build_factor_selection.py 류는 selection 리프레시마다 policy.json 을 통째로
재생성한다. 2026-09-04 커밋 bcb3c8a 에서 그 재생성이 maxPositions 를 30 -> 200
으로 조용히 밀었고, paperEngine.py:229 가 이 값으로 슬롯예산(capital //
maxPositions)을 잡는 탓에 모의계좌가 333만원이 아니라 50만원 슬롯으로 돌았다.
커밋 메시지에도 없었고 4일 동안 아무도 못 봤다.

아래 표는 '검증된 백테스트가 쓴 값'이다. 재생성이든 손편집이든 다시 밀면 이
테스트가 깨진다. 전략을 실제로 바꿀 때만 이 표를 같이 고친다.
"""
import json
import os
import re

_LAB = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# strategy_id -> 검증된 maxPositions
EXPECTED_MAX_POSITIONS = {
    "pbr_value_v1": 30,
    "lowmom60_v1": 30,
    "pbr_value_v1_combined": 30,
    "factor_earnings_yield_v1": 30,
}


def _live_sleeves():
    """run_paper_trading_daily.py 의 STRATEGIES 를 읽는다. import 하지 않는다 -
    이 테스트는 정책 파일만 보면 되고 엔진을 끌고 올 이유가 없다."""
    src = open(os.path.join(_LAB, "run_paper_trading_daily.py"), encoding="utf-8").read()
    block = re.search(r"^STRATEGIES = \[(.*?)^\]", src, re.S | re.M).group(1)
    return re.findall(r'\(\s*"([^"]+)"\s*,\s*([\d_]+)\s*,', block)


def test_every_live_sleeve_is_covered():
    """새 슬리브를 라이브에 붙이면 이 표에도 등록하게 만든다."""
    live = {sid for sid, _ in _live_sleeves()}
    assert live == set(EXPECTED_MAX_POSITIONS), (
        f"라이브 슬리브와 표가 어긋난다: 표에만={set(EXPECTED_MAX_POSITIONS) - live} "
        f"라이브에만={live - set(EXPECTED_MAX_POSITIONS)}")


def test_slot_budget_matches_validated_backtest():
    for sid, capital in _live_sleeves():
        path = os.path.join(_LAB, "strategies", sid, "policy.json")
        with open(path, encoding="utf-8") as f:
            portfolio = json.load(f)["portfolio"]
        mp = portfolio["maxPositions"]
        assert mp == EXPECTED_MAX_POSITIONS[sid], (
            f"{sid}: maxPositions={mp}, 검증값={EXPECTED_MAX_POSITIONS[sid]}. "
            "policy 재생성이 portfolio 블록을 덮었을 수 있다 "
            "(build_factor_selection.py 의 preserve 블록 확인).")
        # 슬롯예산은 라이브 배선이 실제로 쓰는 값이다(paperEngine.py:229).
        assert int(capital) // mp >= 1_000_000, (
            f"{sid}: 슬롯예산 {int(capital) // mp:,}원 - 1주도 못 사는 종목이 대량 발생한다.")
