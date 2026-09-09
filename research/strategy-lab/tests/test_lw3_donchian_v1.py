"""LW3 (래리 윌리엄스 3박자) 신호 계약 테스트.

이 전략의 결론은 '필터를 하나씩 더했을 때 성과가 어떻게 변하는가'로 나온다.
그러니 재야 할 것은 성과가 아니라 **필터가 실제로 필터로 작동하는가**다 -
꺼도 켜도 같은 신호가 나오면 ablation 이 통째로 무의미해진다.

ablation 스크립트가 PARAMS 를 인메모리로 바꿔 쓰므로 여기서도 같은 방식으로
바꾼다(라이브 policy.json 을 건드리지 않는다 - 2026-09-10 capacity test 교훈).
"""
import copy
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import numpy as np
import pandas as pd

from engine.data.pit import PITBars
from engine.runner import load_strategy

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.dirname(os.path.abspath(__file__)))))


def _rule(**overrides):
    """매번 새 모듈. load_strategy 가 exec_module 로 별도 인스턴스를 만든다."""
    r = load_strategy("lw3_donchian_v1", REPO_ROOT)
    r.PARAMS = copy.deepcopy(r.PARAMS)
    for path, value in overrides.items():
        node = r.PARAMS
        keys = path.split(".")
        for k in keys[:-1]:
            node = node[k]
        node[keys[-1]] = value
    return r


def _bars(n=400, seed=1):
    rnd = np.random.RandomState(seed)
    close = pd.Series(10000 + rnd.randn(n).cumsum() * 120).clip(lower=500)
    high = close + rnd.rand(n) * 90 + 5
    low = (close - rnd.rand(n) * 90 - 5).clip(lower=1)
    vol = pd.Series(rnd.randint(1000, 200000, n).astype("float64"))
    idx = pd.bdate_range("2016-01-04", periods=n)
    return pd.DataFrame({"open": close.values, "high": high.values,
                         "low": low.values, "close": close.values,
                         "volume": vol.values}, index=idx)


def test_filters_actually_narrow_the_signal_set():
    """A ⊇ B ⊇ D. 부분집합이 아니거나 셋이 같으면 ablation 이 아무 것도 안 잰다."""
    bars = _bars()
    a = _rule(**{"filters.volume": False, "filters.lwti": False})
    b = _rule(**{"filters.volume": True, "filters.lwti": False})
    d = _rule(**{"filters.volume": True, "filters.lwti": True})
    sa, sb, sd = ({s.signal_date for s in r.generate_signals("T", r.compute_features(bars))}
                  for r in (a, b, d))
    assert sd <= sb <= sa, (len(sa), len(sb), len(sd))
    assert len(sa) > len(sb) > len(sd) > 0, (len(sa), len(sb), len(sd))


def test_transition_mode_is_stricter_than_state_mode():
    bars = _bars(seed=4)
    st = _rule(**{"signal.lwtiMode": "state"})
    tr = _rule(**{"signal.lwtiMode": "transition"})
    s_st = {s.signal_date for s in st.generate_signals("T", st.compute_features(bars))}
    s_tr = {s.signal_date for s in tr.generate_signals("T", tr.compute_features(bars))}
    assert s_tr <= s_st and len(s_tr) < len(s_st), (len(s_st), len(s_tr))


def test_stop_distance_is_always_positive_on_a_signal():
    """close > donchian_high >= donchian_mid 이므로 구조적으로 참이다.
    참이 아니면 손절이 진입가 위에 놓여 거래 자체가 성립하지 않는다."""
    for seed in (1, 2, 3, 9):
        r = _rule()
        f = r.compute_features(_bars(seed=seed))
        fired = r.signal_mask(f)
        assert fired.sum() > 0
        assert (f.loc[fired, "stop_distance"] > 0).all()
        assert (f.loc[fired, "donchian_high"] >= f.loc[fired, "donchian_mid"]).all()


def test_evaluate_at_matches_generate_signals_exactly():
    """PIT 경로와 벌크 경로가 같은 식이어야 한다. 갈리면 어느 쪽이 보고된
    숫자를 만들었는지 알 수 없게 된다."""
    for mode in ("state", "transition"):
        r = _rule(**{"signal.lwtiMode": mode})
        bars = _bars(seed=6)
        f = r.compute_features(bars)
        bulk = {s.signal_date for s in r.generate_signals("T", f)}
        pit = set()
        for i in range(1, len(f)):
            date, prev = f.index[i], f.index[i - 1]
            sig = r.evaluate_at(PITBars(f, date), "T", date.strftime("%Y-%m-%d"), prev)
            if sig:
                pit.add(sig.signal_date)
        assert bulk == pit, (mode, sorted(bulk ^ pit)[:5])


def test_features_are_causal():
    """미래 봉을 바꿔도 과거 신호가 변하면 안 된다."""
    r = _rule()
    bars = _bars(seed=8)
    base = r.signal_mask(r.compute_features(bars))
    cut = 300
    tampered = bars.copy()
    tampered.iloc[cut + 1:] *= 4
    after = r.signal_mask(r.compute_features(tampered))
    pd.testing.assert_series_equal(base.iloc[:cut + 1], after.iloc[:cut + 1])


def test_risk_spec_uses_donchian_mid_distance_and_2r():
    r = _rule()
    f = r.compute_features(_bars())
    row = f.loc[r.signal_mask(f)].iloc[0]
    spec = r.risk_spec_for(row)
    assert spec.stop_distance == float(row["close"] - row["donchian_mid"])
    assert spec.reward_risk == 2.0
    assert spec.max_holding_sessions == 60


def test_policy_is_not_registered_as_production():
    """연구 전용이다. config/policies/registry.json 에 새면 하류가 읽는다."""
    import json
    reg = os.path.join(REPO_ROOT, "config", "policies", "registry.json")
    with open(reg, encoding="utf-8") as f:
        assert "lw3_donchian" not in f.read(), "연구 전략이 registry 에 등록됐다"
    assert json.load(open(os.path.join(
        os.path.dirname(os.path.abspath(__file__)), "..", "strategies",
        "lw3_donchian_v1", "policy.json"), encoding="utf-8")
    )["status"] == "RESEARCH_ONLY"


if __name__ == "__main__":
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()
            print("  PASS  " + name)
    print("\n  LW3 신호 계약 테스트 통과")
