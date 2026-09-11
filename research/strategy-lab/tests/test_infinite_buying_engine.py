"""분할매수 사이클 엔진 회귀 — `infinite_buying_engine.py` 의 selftest 를 pytest 에 태운다.

엔진의 selftest 는 합성 규칙(`_synth()`)으로 돌아 **규칙 파일이 없어도** 완결된다.
그래서 이 테스트는 로컬 전용 규칙 JSON 에 의존하지 않는다 — 저장소만 clone 해도 돈다.

selftest 를 여기서 한 번 더 부르는 이유: `scripts/test-*` 자동 발견 범위 밖이라
아무도 안 돌려주기 때문이다(CLAUDE.md 규칙 8 — npm 이 아니라 자동 발견이 없다).
"""
import importlib.util
import sys
from pathlib import Path

import pytest

ENGINE = Path(__file__).resolve().parents[1] / "infinite_buying_engine.py"


def _load():
    spec = importlib.util.spec_from_file_location("infinite_buying_engine", ENGINE)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    # dataclass 가 cls.__module__ 로 sys.modules 를 되짚으므로 exec 전에 등록한다.
    sys.modules["infinite_buying_engine"] = mod
    spec.loader.exec_module(mod)
    return mod


def test_engine_selftest_passes(capsys):
    rc = _load().selftest()
    out = capsys.readouterr().out
    assert rc == 0, f"engine selftest 실패:\n{out}"
    assert "FAIL" not in out


def test_rules_have_no_defaults_hidden_in_code():
    """규칙 값이 코드 기본값으로 새지 않는지 본다.

    `Rules` 의 규칙 필드는 반드시 호출자가 줘야 한다 — 기본값이 생기는 순간
    '규칙은 JSON 이 갖는다'가 조용히 거짓이 된다.
    """
    import dataclasses

    e = _load()
    required = {
        "ticker", "splits", "base_pct", "tick", "star_slope", "quarter_frac",
        "reverse_enter_t", "reverse_sell_div", "reverse_buy_frac", "reverse_star_window",
    }
    fields = {f.name: f for f in dataclasses.fields(e.Rules)}
    for name in sorted(required):
        assert fields[name].default is dataclasses.MISSING, f"{name} 에 코드 기본값이 생겼다"


def test_ladder_is_off_unless_asked():
    """출처가 엇갈리는 항목(하단 사다리)은 기본이 꺼짐이어야 한다.

    켜고 끄는 것이 결과를 바꾸므로, 조용히 켜져 있으면 '규칙대로 돌렸다'가 거짓이 된다.
    """
    e = _load()
    r = e._synth()
    assert r.ladder_tiers == 0
    s = e.State(cash=10_000.0, t=8.0, qty=10, cost=1000.0)
    assert not [o for o in e.plan_orders(s, r, [100.0]) if o[2] and o[2] < e.avg(s) * 0.9]


@pytest.mark.parametrize("splits", [20, 30, 40])
def test_star_line_crosses_zero_at_half(splits):
    """전·후반 경계는 분할수와 무관하게 T = N/2 다. 분할수를 늘려도 기전이 안 흔들린다."""
    e = _load()
    r = e.Rules(ticker="X", splits=splits, base_pct=15.0, tick=0.01, star_slope=2.0,
                quarter_frac=0.25, reverse_enter_t=1.0, reverse_sell_div=2.0,
                reverse_buy_frac=0.25, reverse_star_window=5)
    assert e.star_pct(0, r) == pytest.approx(15.0)
    assert e.star_pct(splits / 2, r) == pytest.approx(0.0)
    assert e.star_pct(splits, r) == pytest.approx(-15.0)
