"""upload-paper-state-oci.py 회귀 - 네트워크 없이 FakeOciTransport로."""
import importlib.util
import json
import tempfile
from datetime import datetime
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent


def load_module(name):
    spec = importlib.util.spec_from_file_location(
        name.replace("-", "_"), REPO / "scripts" / (name + ".py"))
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


osmod = load_module("oci-object-storage")
upmod = load_module("upload-paper-state-oci")


def test_uploads_existing_state():
    with tempfile.TemporaryDirectory() as tmp:
        state_dir = Path(tmp) / "research/strategy-lab/data/paper"
        state_dir.mkdir(parents=True)
        (state_dir / "pbr_value_v1_positions.json").write_text(
            json.dumps({"005930": {"status": "OPEN"}}), encoding="utf-8")
        # lowmom60_v1은 로컬 파일이 아직 없는 상태(첫 신호 전) 시나리오

        transport = osmod.FakeOciTransport()
        upmod.run(transport, tmp, out=lambda *a: None)

        keys = transport.list_names(prefix="paper-state/pbr_value_v1/")
        assert len(keys) == 1, keys
        assert transport.list_names(prefix="paper-state/lowmom60_v1/") == set()
        got = json.loads(list(transport.objects[k] for k in keys)[0])
        assert got == {"005930": {"status": "OPEN"}}


def test_skips_missing_state():
    with tempfile.TemporaryDirectory() as tmp:
        transport = osmod.FakeOciTransport()
        upmod.run(transport, tmp, out=lambda *a: None)
        assert transport.puts == []


def test_timestamp_keys_are_unique_and_sortable():
    with tempfile.TemporaryDirectory() as tmp:
        state_dir = Path(tmp) / "research/strategy-lab/data/paper"
        state_dir.mkdir(parents=True)
        p = state_dir / "pbr_value_v1_positions.json"
        p.write_text("{}", encoding="utf-8")

        transport = osmod.FakeOciTransport()
        t1 = datetime(2026, 9, 4, 9, 0, 0)
        t2 = datetime(2026, 9, 4, 9, 10, 0)
        upmod.upload_state(transport, "pbr_value_v1", p, now=t1, out=lambda *a: None)
        upmod.upload_state(transport, "pbr_value_v1", p, now=t2, out=lambda *a: None)

        keys = sorted(transport.list_names(prefix="paper-state/pbr_value_v1/"))
        assert len(keys) == 2, keys
        assert keys[0] < keys[1]  # 문자열 정렬이 시간 순서와 일치


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
