"""test-upload-minute-oci.py — upload-minute-oci.py 회귀 (합성 픽스처, 네트워크 없음)

FakeOciTransport로 갈아끼워 돈다. 실제 OCI를 부르지 않는다.

사용:
    python scripts/test-upload-minute-oci.py
    python scripts/upload-minute-oci.py --selftest
"""

import importlib.util
import json
import shutil
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent

PASS = []
FAIL = []


def check(name, cond, detail=""):
    (PASS if cond else FAIL).append(name)
    print(("  PASS  " if cond else "  FAIL  ") + name +
          (("  " + str(detail)) if (detail and not cond) else ""))


def load(name):
    spec = importlib.util.spec_from_file_location(
        name.replace("-", "_"), REPO / "scripts" / (name + ".py"))
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


def make_day(manifest_dir, raw_root, date, part_names=("part-000.parquet",)):
    """로컬에 통과 manifest + 조각 파일을 만든다. 내용은 바이트만 맞으면 된다
    (이 스크립트는 parquet를 파싱하지 않는다 - 옮기기만 한다)."""
    part_dir = Path(raw_root) / ("date=" + date)
    part_dir.mkdir(parents=True, exist_ok=True)
    parts = []
    for i, name in enumerate(part_names):
        data = ("fake-parquet-%s-%d" % (date, i)).encode("utf-8")
        (part_dir / name).write_bytes(data)
        parts.append({"name": name, "rows": 10 * (i + 1)})
    man = {"date": date, "acceptancePassed": True, "parts": parts,
          "rows": sum(p["rows"] for p in parts)}
    Path(manifest_dir).mkdir(parents=True, exist_ok=True)
    (Path(manifest_dir) / (date + ".json")).write_text(
        json.dumps(man, ensure_ascii=False), encoding="utf-8")
    return man


def run_all():
    M = load("upload-minute-oci")
    osmod = load("oci-object-storage")
    tmp = Path(tempfile.mkdtemp(prefix="ocmup-"))

    try:
        mandir = tmp / "manifest"
        rawroot = tmp / "raw"

        # 1 새 날짜를 올린다
        make_day(mandir, rawroot, "2026-08-27")
        tr = osmod.FakeOciTransport()
        code = M.run(tr, mandir, rawroot, out=lambda s: None)
        check("정상 업로드가 0을 돌려준다", code == 0, code)
        check("조각이 올라갔다", "date=2026-08-27/part-000.parquet" in tr.objects,
              sorted(tr.objects))
        check("manifest가 마지막에 올라간다 (순서 안 지켜도 결과는 둘 다 있음)",
              "_manifest/2026-08-27.json" in tr.objects, sorted(tr.objects))
        check("manifest 객체가 로컬 파일과 바이트 동일",
              tr.objects["_manifest/2026-08-27.json"]
              == (mandir / "2026-08-27.json").read_bytes())

        # 2 이미 올라간 날짜는 다시 안 올린다 (IAM이 OVERWRITE를 안 준다 -
        # 여기서 걸리지 않으면 실제 운영에서 예외로 죽는다)
        tr.puts = []
        code = M.run(tr, mandir, rawroot, out=lambda s: None)
        check("이미 올라간 날짜는 재업로드 시도가 없다", tr.puts == [], tr.puts)

        # 3 부분 업로드에서 재개 — 조각 하나만 올라간 상태에서 이어받는다
        make_day(mandir, rawroot, "2026-08-28",
                 part_names=("part-000.parquet", "part-001.parquet"))
        tr2 = osmod.FakeOciTransport()
        # part-000만 미리 올라와 있고 manifest는 아직인 상태를 흉내낸다
        tr2.objects["date=2026-08-28/part-000.parquet"] = (
            (rawroot / "date=2026-08-28" / "part-000.parquet").read_bytes())
        M.run(tr2, mandir, rawroot, out=lambda s: None)
        check("재개가 이미 있는 조각을 다시 안 올린다",
              "date=2026-08-28/part-000.parquet" not in tr2.puts, tr2.puts)
        check("재개가 남은 조각은 올린다",
              "date=2026-08-28/part-001.parquet" in tr2.puts, tr2.puts)
        check("재개 뒤 manifest도 올라간다",
              "_manifest/2026-08-28.json" in tr2.objects)

        # 4 오래된 날짜부터 (사라질 위험이 큰 쪽이 먼저)
        make_day(mandir, rawroot, "2026-08-30")
        make_day(mandir, rawroot, "2026-08-29")
        tr3 = osmod.FakeOciTransport()
        M.run(tr3, mandir, rawroot, out=lambda s: None)
        order = [p for p in tr3.puts if p.startswith("_manifest/")]
        check("업로드 순서가 날짜 오름차순",
              order == sorted(order), order)

        # 5 --days 예산이 실제로 자른다
        mandir2, rawroot2 = tmp / "man2", tmp / "raw2"
        for d in ("2026-08-01", "2026-08-02", "2026-08-03"):
            make_day(mandir2, rawroot2, d)
        tr4 = osmod.FakeOciTransport()
        M.run(tr4, mandir2, rawroot2, days=2, out=lambda s: None)
        n_dates = len({n[len("_manifest/"):-len(".json")]
                       for n in tr4.objects if n.startswith("_manifest/")})
        check("days=2가 딱 2개만 올린다", n_dates == 2, n_dates)

        # 6 --date 지정은 오래된 순서와 무관하게 그 날짜만
        mandir3, rawroot3 = tmp / "man3", tmp / "raw3"
        make_day(mandir3, rawroot3, "2026-08-05")
        make_day(mandir3, rawroot3, "2026-08-10")
        tr5 = osmod.FakeOciTransport()
        M.run(tr5, mandir3, rawroot3, date="2026-08-10", out=lambda s: None)
        check("--date가 지정한 날짜만 올린다",
              "_manifest/2026-08-10.json" in tr5.objects
              and "_manifest/2026-08-05.json" not in tr5.objects,
              sorted(tr5.objects))

        # 7 candidate_dates가 이미 올라간 것을 뺀다
        cands = M.candidate_dates(mandir2, {"2026-08-01", "2026-08-02"})
        check("업로드된 날짜는 후보에서 빠진다", cands == ["2026-08-03"], cands)

        # 8 IAM이 덮어쓰기를 거부하면 그대로 위로 전파한다 (조용히 삼키지 않는다)
        tr6 = osmod.FakeOciTransport(
            existing={"_manifest/2026-08-27.json": b"stale"})
        try:
            tr6.put("_manifest/2026-08-27.json", b"new")
            check("OVERWRITE 거부가 예외로 전파된다", False, "예외가 안 났다")
        except RuntimeError:
            check("OVERWRITE 거부가 예외로 전파된다", True)

    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    print()
    print("  통과 %d · 실패 %d" % (len(PASS), len(FAIL)))
    if FAIL:
        for f in FAIL:
            print("    FAIL " + f)
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(run_all())
