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


# strategy_id -> 확정된 factor 파라미터. policy.json 의 factor 블록은 엔진이
# 읽지 않고(선택 로직이 selection.json 에 구워져 있다) build_selection*.py 가
# 오프라인으로 읽는다 - 그래서 여기가 틀어져도 런타임은 조용하다. 실제로
# pbr_value_v1_combined 는 KEEP finding 이 "nDrop=2 선택"이라고 적은 채
# 실물은 3 으로 돌고 있었고(2026-09-08 발견), maxPositions tripwire 는
# portfolio 블록만 봐서 못 잡았다. 확정값만 등록한다 - 미확정 전략은
# 넣지 않는다(확정 안 된 값을 pin 하면 테스트가 미해결을 축복한다).
EXPECTED_FACTOR_PARAMS = {
    # nDrop=3 확정(2026-09-08 사용자). 근거: dropout policy 의 nDropNote(Qlib
    # 예제와 같은 topN 10% 비율)라는 사전 근거 + 재현에서 TRAIN 최선이 2<->3
    # 으로 뒤집혀 차이가 노이즈 + OOS 부호반전 0건은 두 값 모두 유지.
    # 경위: findings/pbr-reproducibility-anchor-2026-09.md §4
    "pbr_value_v1_combined": {"nDrop": 3, "maxExclusionPercentile": 0.8, "topN": 30},
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


def test_factor_params_match_confirmed_values():
    """확정된 factor 파라미터가 policy.json 과 구워진 selection 양쪽에서 유지되는지."""
    for sid, expected in EXPECTED_FACTOR_PARAMS.items():
        with open(os.path.join(_LAB, "strategies", sid, "policy.json"), encoding="utf-8") as f:
            factor = json.load(f)["factor"]
        for key, want in expected.items():
            assert factor.get(key) == want, (
                f"{sid}: policy factor.{key}={factor.get(key)}, 확정값={want}. "
                "build_selection*.py 재생성이 덮었거나 손편집이 어긋났다.")

    # policy 만 맞고 selection 이 옛 값으로 구워져 있으면 라이브는 옛 값으로 돈다.
    # combined 는 dropout selection 을 상류로 쓰므로 nDrop 은 그쪽에 기록된다.
    with open(os.path.join(_LAB, "strategies", "pbr_value_v1_dropout", "selection.json"),
              encoding="utf-8") as f:
        dropout = json.load(f)
    assert dropout.get("nDrop") == EXPECTED_FACTOR_PARAMS["pbr_value_v1_combined"]["nDrop"], (
        f"pbr_value_v1_dropout/selection.json 의 nDrop={dropout.get('nDrop')} 이 "
        "확정값과 다르다 - 구워진 selection 이 정본이므로 라이브가 이 값으로 돈다.")
