"""selection 빌더의 기본 END 가 코드에 박혀 있지 않은지 self-check.

왜 있나(2026-09-09 실측): 기본값이 "2026-08-14" 로 박혀 있었다. 그 날짜가 지난
뒤 인자 없이 돌렸더니 **라이브 리밸런싱일(2026-09-01)이 통째로 빠진**
selection.json 이 생성됐다. 그 파일로는 run_monthly_rebalance.py 가 "이 날짜가
없음"으로 조용히 종료하고 poll_once 를 아예 안 불러 청산·체결확인까지 멈춘다.

매달 자동으로 돌 스크립트라 기준일을 손으로 적으면 안 된다 - 캘린더의 마지막
거래일을 쓴다. 이 테스트는 그 규율을 강제한다.
"""
import importlib.util
import json
import os
import re
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
LAB = os.path.dirname(_HERE)
REPO_ROOT = os.path.dirname(os.path.dirname(LAB))

# 라이브 페이퍼 4전략이 실제로 읽는 selection 을 만드는 빌더들
LIVE_BUILDERS = [
    "strategies/pbr_value_v1/build_selection.py",
    "strategies/lowmom60_v1/build_selection.py",
    "build_factor_selection.py",
    "strategies/foreign_flow5d_v1/build_selection.py",   # 단기 관측 슬리브(일별)
    # combined 의 baseline - 여기가 밀리면 combined 도 같이 밀린다
    "strategies/pbr_value_v1_dropout/build_selection_dropout.py",
]
FROZEN_DATE_DEFAULT = re.compile(r'^END\s*=.*else\s*"\d{4}-\d{2}-\d{2}"', re.M)

passed, failed = 0, 0


def ok(name, cond, detail=""):
    global passed, failed
    if cond:
        passed += 1
    else:
        failed += 1
        print(f"  FAIL  {name}  {detail}")


def test_no_frozen_end_default():
    for rel in LIVE_BUILDERS:
        src = open(os.path.join(LAB, rel), encoding="utf-8").read()
        m = FROZEN_DATE_DEFAULT.search(src)
        ok(f"{rel}: 기본 END 가 박힌 날짜가 아니다", m is None, m.group(0) if m else "")
        ok(f"{rel}: _default_end() 를 쓴다", "_default_end()" in src)


def test_default_end_is_calendar_last_session():
    """캘린더의 마지막 거래일과 일치해야 한다 - 그래야 이번 달 리밸런싱일이
    빠지지 않는다."""
    with open(os.path.join(REPO_ROOT, "data", "backfill", "calendar.json"),
              encoding="utf-8") as f:
        last = json.load(f)["tradingDays"][-1]
    spec = importlib.util.spec_from_file_location(
        "_bs", os.path.join(LAB, "strategies/pbr_value_v1/build_selection.py"))
    mod = importlib.util.module_from_spec(spec)
    # exec_module 은 main() 까지 안 돌린다(if __name__ 가드) - 상수만 읽는다
    sys.path.insert(0, LAB)
    try:
        spec.loader.exec_module(mod)
    finally:
        sys.path.remove(LAB)
    ok("END 기본값 == 캘린더 마지막 거래일", mod.END == last, (mod.END, last))
    ok("그 값이 이번 달을 포함한다", mod.END[:7] >= last[:7], mod.END)



# 라이브 슬리브의 rule.py 가 엔진에 제공해야 하는 진입점.
# hold_sessions 는 월별 교체매매 4슬리브만 - foreign_flow5d_v1 은 5세션 고정이라
# 정책 기본값이 정답이고 이 함수가 없는 게 맞다.
RULE_ACCESSORS = {
    "pbr_value_v1": ["selected_symbols", "still_selected", "hold_sessions"],
    "lowmom60_v1": ["selected_symbols", "still_selected", "hold_sessions"],
    "pbr_value_v1_combined": ["selected_symbols", "still_selected", "hold_sessions"],
    "factor_earnings_yield_v1": ["selected_symbols", "still_selected", "hold_sessions"],
    "foreign_flow5d_v1": ["selected_symbols", "still_selected"],
}


def test_live_rules_expose_engine_accessors():
    for sid, names in RULE_ACCESSORS.items():
        src = open(os.path.join(LAB, "strategies", sid, "rule.py"), encoding="utf-8").read()
        for n in names:
            ok(f"{sid}.rule.{n}", f"def {n}(" in src)


def test_generator_template_keeps_hold_sessions():
    """★ 2026-09-09. build_factor_selection.py 는 rule.py 를 템플릿에서 **매번 새로
    쓴다.** 그 템플릿에 hold_sessions 가 없어서, selection 을 갱신할 때마다 그날
    넣은 보유일수 수정이 factor_earnings_yield_v1 에서 조용히 지워졌다(실측:
    재생성 후 rule.py 에서 13줄 삭제). 자동화가 매달 이걸 돌리므로 템플릿 쪽에서
    막는다 - 41a5732 가 portfolio 블록을 보존하게 만든 것과 같은 자리다."""
    src = open(os.path.join(LAB, "build_factor_selection.py"), encoding="utf-8").read()
    ok("생성기 템플릿에 hold_sessions 가 있다", "def hold_sessions(" in src)
    ok("생성기 템플릿에 still_selected 가 있다", "def still_selected(" in src)



def test_node_valuation_panel_has_no_frozen_end():
    """★ 2026-09-09 CI 5회차. 체인의 **첫 단계**인 node 패널 빌더에도 박힌 기본
    종료일('2026-08-14')이 있었다. Python 빌더 넷만 고쳤더니 자동 갱신이 패널을
    2026-08-03 까지만 만들었고, 그 위에 얹힌 pbr_value_v1 이 128개월 -> 127개월로
    줄어 라이브 리밸런싱일(2026-09-01)이 통째로 빠졌다. 여기가 잘리면 pbr 계열
    selection 이 전부 잘린다."""
    src = open(os.path.join(os.path.dirname(os.path.dirname(LAB)), "scripts",
                            "build-a5-valuation-panel.js"), encoding="utf-8").read()
    m = re.search(r"const END = argEnd \|\| '\d{4}-\d{2}-\d{2}'", src)
    ok("node 패널 빌더에 박힌 종료일이 없다", m is None, m.group(0) if m else "")
    ok("node 패널 빌더가 defaultEnd() 를 쓴다", "defaultEnd()" in src)


if __name__ == "__main__":
    test_no_frozen_end_default()
    test_default_end_is_calendar_last_session()
    test_live_rules_expose_engine_accessors()
    test_generator_template_keeps_hold_sessions()
    test_node_valuation_panel_has_no_frozen_end()
    print(f"test_selection_builder_defaults: {passed} passed, {failed} failed")
    sys.exit(1 if failed else 0)
