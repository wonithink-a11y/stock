"""pytest 가 조용히 초록이 되는 것을 막는다.

이 디렉터리의 테스트 다수는 `ok(name, cond)` 헬퍼를 쓴다. 그 헬퍼는 **예외를
내지 않고** 모듈 전역 `failed` 를 1 올리기만 한다 - 실패를 한 번에 다 보여주려는
설계이고, 스크립트로 돌리면 `main()` 이 `SystemExit(1)` 을 내서 제대로 붉어진다.

그런데 pytest 는 `main()` 을 안 부른다. 그래서 체크가 깨져도 `test_*` 함수가
예외 없이 끝나기만 하면 통과로 잡혔다 - 2026-09-11 실측으로 **9개 파일 212건**이
그렇게 안 보였고, 실제로 한 번 속았다(paperEngine 수정 직후 "42 passed" 를
받았는데 체크는 깨져 있었다). 교훈72 - 통과가 정보를 주는지 먼저 묻는다.

각 테스트 전후로 그 모듈의 `failed` 를 재서 늘었으면 그 테스트를 실패로 바꾼다.
테스트 파일 9개를 하나도 안 건드리고 한 곳에서 닫는다. `failed` 전역이 없는
모듈은 손대지 않는다 - 평범한 assert 기반 테스트의 동작은 그대로다.

★ 판정을 **report 단계**에서 바꾼다. `pytest_runtest_teardown` 에서 실패시키는
첫 구현은 pytest 내부 SetupState 를 깨뜨려 "previous item was not torn down
properly" 로 **다음 테스트까지 ERROR** 를 냈다(2026-09-11 실측). 여기서는
call 단계의 결과만 고쳐 쓰므로 번짐이 없고 FAILED 로 정직하게 뜬다.
"""
import pytest

_BEFORE = "_ok_failed_before"


def _counter_module(item):
    """이 item 이 counting ok() 를 쓰는 모듈에 속하면 그 모듈을 준다."""
    mod = getattr(item, "module", None)
    n = getattr(mod, "failed", None)
    # bool 은 int 의 서브클래스라 명시적으로 배제한다.
    if isinstance(n, int) and not isinstance(n, bool):
        return mod
    return None


def pytest_runtest_setup(item):
    mod = _counter_module(item)
    if mod is not None:
        setattr(item, _BEFORE, mod.failed)


@pytest.hookimpl(wrapper=True)
def pytest_runtest_makereport(item, call):
    report = yield
    before = getattr(item, _BEFORE, None)
    if report.when != "call" or not report.passed or before is None:
        return report
    after = _counter_module(item).failed
    if after > before:
        report.outcome = "failed"
        report.longrepr = (
            "ok() 체크 %d건이 실패했다 (모듈 누적 %d -> %d).\n"
            "실패한 줄은 captured stdout 의 'FAIL ' 에 있다.\n"
            "  python %s   로 돌리면 그대로 보인다."
            % (after - before, before, after, item.module.__file__))
    return report
