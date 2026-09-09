"""sync-paper-state-oci.py 회귀 - 네트워크 없이 FakeOciTransport로."""
import importlib.util
import json
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent


def load_module(name):
    spec = importlib.util.spec_from_file_location(
        name.replace("-", "_"), REPO / "scripts" / (name + ".py"))
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


osmod = load_module("oci-object-storage")
syncmod = load_module("sync-paper-state-oci")

KST = timezone(timedelta(hours=9))
NOW = datetime(2026, 9, 9, 11, 0, tzinfo=KST)   # 테스트를 달력에 묶지 않는다


class RecordingTransport(osmod.FakeOciTransport):
    """list_names에 실제로 어떤 start가 들어갔는지 기록한다 - 창을 좁혔다는
    주장이 통과가 아니라 관측으로 확인돼야 한다(교훈72: 통과가 정보를 주는지
    먼저 묻는다). 이게 없으면 최적화를 지워도 테스트가 그대로 통과한다."""

    def __init__(self, existing=None):
        super().__init__(existing)
        self.list_calls = []

    def list_names(self, prefix=None, start=None):
        self.list_calls.append({"prefix": prefix, "start": start})
        return super().list_names(prefix=prefix, start=start)


def test_picks_latest_by_key_order():
    transport = osmod.FakeOciTransport({
        "paper-state/pbr_value_v1/20260904T090000.json": json.dumps({"v": "old"}).encode(),
        "paper-state/pbr_value_v1/20260904T091000.json": json.dumps({"v": "new"}).encode(),
    })
    with tempfile.TemporaryDirectory() as tmp:
        result = syncmod.run(transport, tmp, out=lambda *a: None, now=NOW)
        assert result["pbr_value_v1"] is True
        assert result["lowmom60_v1"] is False
        got = json.loads((Path(tmp) / "research/strategy-lab/data/paper/pbr_value_v1_positions.json")
                          .read_text(encoding="utf-8"))
        assert got == {"v": "new"}


def test_no_objects_for_strategy_is_reported_not_fabricated():
    transport = osmod.FakeOciTransport()
    with tempfile.TemporaryDirectory() as tmp:
        result = syncmod.run(transport, tmp, out=lambda *a: None, now=NOW)
        assert result == {s: False for s in syncmod.STRATEGIES}
        assert not (Path(tmp) / "research/strategy-lab/data/paper/pbr_value_v1_positions.json").exists()


def test_corrupt_object_is_rejected_not_written():
    transport = osmod.FakeOciTransport({
        "paper-state/pbr_value_v1/20260904T090000.json": b"{not valid json",
    })
    with tempfile.TemporaryDirectory() as tmp:
        result = syncmod.run(transport, tmp, out=lambda *a: None, now=NOW)
        assert result["pbr_value_v1"] is False
        assert not (Path(tmp) / "research/strategy-lab/data/paper/pbr_value_v1_positions.json").exists()



def test_recent_window_avoids_scanning_the_whole_prefix():
    """★ 2026-09-09. 이 버킷은 IAM이 DELETE를 안 줘서 객체가 계속 쌓인다
    (하루 약 24개/전략). 최신 하나를 찾으려고 prefix 전체를 훑으면 조회 비용이
    누적에 비례해 는다 - 최근 창부터 보면 누적과 무관하게 요청 1회로 끝난다."""
    old = {f"paper-state/pbr_value_v1/202601{d:02d}T090000.json": b'{"v": "ancient"}'
           for d in range(1, 29)}          # 8개월 전 객체 28개
    old["paper-state/pbr_value_v1/20260909T090000.json"] = json.dumps({"v": "new"}).encode()
    transport = RecordingTransport(old)
    with tempfile.TemporaryDirectory() as tmp:
        result = syncmod.run(transport, tmp, out=lambda *a: None, now=NOW)
        assert result["pbr_value_v1"] is True
        got = json.loads((Path(tmp) / "research/strategy-lab/data/paper/pbr_value_v1_positions.json")
                          .read_text(encoding="utf-8"))
        assert got == {"v": "new"}, got

    pbr_calls = [c for c in transport.list_calls if c["prefix"] == "paper-state/pbr_value_v1/"]
    assert len(pbr_calls) == 1, f"창 안에서 찾았으면 조회는 1회여야 한다: {pbr_calls}"
    assert pbr_calls[0]["start"] == "paper-state/pbr_value_v1/20260826", pbr_calls[0]
    # start가 실제로 좁혔는가 - 옛 객체는 후보에 들어오지도 않았어야 한다
    listed = transport.list_names(prefix="paper-state/pbr_value_v1/", start=pbr_calls[0]["start"])
    assert listed == {"paper-state/pbr_value_v1/20260909T090000.json"}, listed


def test_falls_back_to_full_scan_when_window_is_empty():
    """창이 비었다고 '없음'으로 단정하지 않는다(교훈57) - 파이프라인이 오래
    멈춰 있었을 수 있다. 느린 경로지만 그때는 이미 비정상이라 비용이 문제가
    아니고, 지어내지 않는 쪽이 중요하다."""
    transport = RecordingTransport({
        "paper-state/pbr_value_v1/20260101T090000.json": json.dumps({"v": "stale"}).encode(),
    })
    with tempfile.TemporaryDirectory() as tmp:
        result = syncmod.run(transport, tmp, out=lambda *a: None, now=NOW)
        assert result["pbr_value_v1"] is True
        got = json.loads((Path(tmp) / "research/strategy-lab/data/paper/pbr_value_v1_positions.json")
                          .read_text(encoding="utf-8"))
        assert got == {"v": "stale"}, got
    pbr_calls = [c for c in transport.list_calls if c["prefix"] == "paper-state/pbr_value_v1/"]
    assert [c["start"] for c in pbr_calls] == ["paper-state/pbr_value_v1/20260826", None], pbr_calls


def test_start_is_inclusive_and_lexicographic():
    """OCI list_objects의 start는 '이름 >= start'(포함)다. FakeOciTransport가
    그 의미를 그대로 흉내내야 위 두 테스트가 실물과 같은 것을 잰다."""
    t = osmod.FakeOciTransport({"p/a": b"1", "p/b": b"2", "p/c": b"3", "q/a": b"4"})
    assert t.list_names(prefix="p/", start="p/b") == {"p/b", "p/c"}
    assert t.list_names(prefix="p/", start="p/a") == {"p/a", "p/b", "p/c"}
    assert t.list_names(prefix="p/", start="p/z") == set()
    assert t.list_names(prefix="p/") == {"p/a", "p/b", "p/c"}


def run_all():
    tests = [v for k, v in globals().items() if k.startswith("test_")]
    for t in tests:
        t()
        print(f"  OK  {t.__name__}")
    print(f"{len(tests)} passed")
    return 0


if __name__ == "__main__":
    import sys
    sys.exit(run_all())
