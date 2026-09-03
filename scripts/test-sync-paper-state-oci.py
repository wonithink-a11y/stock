"""sync-paper-state-oci.py 회귀 - 네트워크 없이 FakeOciTransport로."""
import importlib.util
import json
import tempfile
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


def test_picks_latest_by_key_order():
    transport = osmod.FakeOciTransport({
        "paper-state/pbr_value_v1/20260904T090000.json": json.dumps({"v": "old"}).encode(),
        "paper-state/pbr_value_v1/20260904T091000.json": json.dumps({"v": "new"}).encode(),
    })
    with tempfile.TemporaryDirectory() as tmp:
        result = syncmod.run(transport, tmp, out=lambda *a: None)
        assert result["pbr_value_v1"] is True
        assert result["lowmom60_v1"] is False
        got = json.loads((Path(tmp) / "research/strategy-lab/data/paper/pbr_value_v1_positions.json")
                          .read_text(encoding="utf-8"))
        assert got == {"v": "new"}


def test_no_objects_for_strategy_is_reported_not_fabricated():
    transport = osmod.FakeOciTransport()
    with tempfile.TemporaryDirectory() as tmp:
        result = syncmod.run(transport, tmp, out=lambda *a: None)
        assert result == {"pbr_value_v1": False, "lowmom60_v1": False}
        assert not (Path(tmp) / "research/strategy-lab/data/paper/pbr_value_v1_positions.json").exists()


def test_corrupt_object_is_rejected_not_written():
    transport = osmod.FakeOciTransport({
        "paper-state/pbr_value_v1/20260904T090000.json": b"{not valid json",
    })
    with tempfile.TemporaryDirectory() as tmp:
        result = syncmod.run(transport, tmp, out=lambda *a: None)
        assert result["pbr_value_v1"] is False
        assert not (Path(tmp) / "research/strategy-lab/data/paper/pbr_value_v1_positions.json").exists()


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
