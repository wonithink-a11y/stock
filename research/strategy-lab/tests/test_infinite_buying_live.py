"""무한매수 슬리브 라이브 경로 회귀 — 러너·해외주식 클라이언트.

둘 다 자체 selftest 가 완결돼 있고(네트워크·규칙파일 없이 돈다) 여기서 pytest 에
태워 자동 발견 밖을 닫는다(CLAUDE.md 규칙 8).

★ 이 파일이 지키는 가장 중요한 성질은 **주문이 실수로 나가지 않는다**는 것이다.
   `place()` 의 기본이 dry_run 이고, 러너는 `--execute` 없이는 접수하지 않는다.
   되돌릴 수 없는 부작용이라 통과가 정보를 주는 검사다(교훈61).
"""
import importlib.util
import sys
from pathlib import Path

import pytest

LAB = Path(__file__).resolve().parents[1]
if str(LAB) not in sys.path:
    sys.path.insert(0, str(LAB))


def _load(name: str, rel: str):
    spec = importlib.util.spec_from_file_location(name, LAB / rel)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


def test_runner_selftest(capsys):
    mod = _load("run_infinite_buying_daily", "run_infinite_buying_daily.py")
    rc = mod.selftest()
    out = capsys.readouterr().out
    assert rc == 0, f"러너 selftest 실패:\n{out}"


def test_overseas_client_selftest(capsys):
    from engine.live.kisVtsOverseasClient import selftest

    rc = selftest()
    out = capsys.readouterr().out
    assert rc == 0, f"해외주식 클라이언트 selftest 실패:\n{out}"


def test_order_never_fires_without_explicit_opt_in():
    """dry_run 기본값이 사라지면 붉어진다. 이게 뚫리면 조용히 실주문이 나간다."""
    import inspect

    from engine.live.kisVtsOverseasClient import KisVtsOverseasClient

    sig = inspect.signature(KisVtsOverseasClient.place)
    assert sig.parameters["dry_run"].default is True


def test_paper_mode_never_imports_broker():
    """페이퍼 모드는 주문 경로를 아예 건드리지 않아야 한다.

    브로커 import 가 `run_vts` 안에 있는지 본다 — 모듈 최상단으로 올라오면
    페이퍼 실행만으로도 자격증명을 읽고 계좌를 치게 된다.
    """
    src = (LAB / "run_infinite_buying_daily.py").read_text(encoding="utf-8")
    head = src[: src.index("def run_vts")]
    assert "kisVtsOverseasClient" not in head


def test_modes_do_not_share_state():
    """paper 와 vts 는 규칙이 다르게 도므로(LOC vs 지정가) 상태를 섞으면 안 된다."""
    mod = _load("run_infinite_buying_daily", "run_infinite_buying_daily.py")
    assert mod.state_path("TQQQ", "paper") != mod.state_path("TQQQ", "vts")
    assert mod.state_path("TQQQ", "paper") != mod.state_path("SOXL", "paper")


@pytest.mark.parametrize("bad", ["34", "31", "32", "33", "01"])
def test_only_limit_orders_accepted(bad):
    """모의투자는 지정가(00)만 받는다. LOC(34) 등을 조용히 통과시키면 주문이 거절된다."""
    from engine.live.kisVtsOverseasClient import KisVtsOverseasClient

    class _Stub(KisVtsOverseasClient):
        def __init__(self):
            pass

        def _acct(self):
            return {"CANO": "1", "ACNT_PRDT_CD": "01"}

    with pytest.raises(ValueError):
        _Stub().place("BUY", "TQQQ", 1, 10.0, ord_dvsn=bad)
