"""test-promote-minute-manifest.py — promote-minute-manifest.py 회귀 (합성 픽스처, 네트워크 없음)

FakeOciTransport로 갈아끼워 돈다. 실제 OCI를 부르지 않는다.

사용:
    python scripts/test-promote-minute-manifest.py
    python scripts/promote-minute-manifest.py --selftest
"""

import hashlib
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


def sha(b):
    return hashlib.sha256(b).hexdigest()


def good_day(date, transport, osmod, n_parts=2):
    """올바른 하루를 transport에 미리 채운다. (manifest dict)를 돌려준다."""
    parts_meta, computed = [], []
    for i in range(n_parts):
        data = ("part-%s-%d" % (date, i)).encode("utf-8")
        name = "part-%03d.parquet" % i
        transport.objects["date=" + date + "/" + name] = data
        parts_meta.append({"name": name, "rows": 5 * (i + 1), "sha256": sha(data)})
        computed.append({"name": name, "sha256": sha(data)})
    kismod = load("collect-minute-kis")
    combined = kismod.combined_sha(computed)
    man = {"date": date, "acceptancePassed": True, "parts": parts_meta,
          "rows": sum(p["rows"] for p in parts_meta), "sha256": combined}
    transport.objects["_manifest/" + date + ".json"] = (
        json.dumps(man, ensure_ascii=False).encode("utf-8"))
    return man


def run_all():
    M = load("promote-minute-manifest")
    osmod = load("oci-object-storage")
    tmp = Path(tempfile.mkdtemp(prefix="ocmprom-"))

    try:
        # 1 정상 하루 — 검증 통과, 승격
        tr = osmod.FakeOciTransport()
        good_day("2026-08-27", tr, osmod)
        ok, why, man = M.verify_day(tr, "2026-08-27")
        check("정상 하루가 검증을 통과한다", ok and why is None, why)
        check("manifest 내용이 그대로 온다", man["date"] == "2026-08-27", man)

        # 2 sha256이 실제와 다르면 거부 (조각 바이트가 변조됐다고 가정)
        tr2 = osmod.FakeOciTransport()
        good_day("2026-08-28", tr2, osmod)
        tr2.objects["date=2026-08-28/part-000.parquet"] = b"corrupted"
        ok, why, _ = M.verify_day(tr2, "2026-08-28")
        check("조각 sha256 불일치가 거부된다", not ok and "sha256" in why, why)

        # 3 acceptancePassed=false면 애초에 올라오면 안 되지만, 방어적으로도 거부
        tr3 = osmod.FakeOciTransport()
        good_day("2026-08-29", tr3, osmod)
        man3 = json.loads(tr3.objects["_manifest/2026-08-29.json"])
        man3["acceptancePassed"] = False
        tr3.objects["_manifest/2026-08-29.json"] = (
            json.dumps(man3, ensure_ascii=False).encode("utf-8"))
        ok, why, _ = M.verify_day(tr3, "2026-08-29")
        check("acceptancePassed=false가 거부된다",
              not ok and "acceptancePassed" in why, why)

        # 4 part 객체 자체가 없으면 거부
        tr4 = osmod.FakeOciTransport()
        good_day("2026-08-30", tr4, osmod)
        del tr4.objects["date=2026-08-30/part-001.parquet"]
        ok, why, _ = M.verify_day(tr4, "2026-08-30")
        check("part 객체 누락이 거부된다", not ok and "없다" in why, why)

        # 5 manifest 자체가 없으면 거부
        ok, why, man = M.verify_day(osmod.FakeOciTransport(), "2026-09-01")
        check("manifest 없음이 거부된다", not ok and man is None, (ok, why, man))

        # 6 run() — 통과한 것만 저장소에 쓴다, 실패한 것은 안 쓴다
        tr5 = osmod.FakeOciTransport()
        good_day("2026-08-27", tr5, osmod)
        good_day("2026-08-28", tr5, osmod)
        tr5.objects["date=2026-08-28/part-000.parquet"] = b"corrupted"
        mandir = tmp / "manifest"
        code = M.run(tr5, mandir, out=lambda s: None)
        check("실패가 섞이면 exit code가 1", code == 1, code)
        check("통과한 날짜만 파일로 남는다",
              (mandir / "2026-08-27.json").exists()
              and not (mandir / "2026-08-28.json").exists(),
              list(mandir.glob("*.json")))

        # 7 이미 승격된 날짜는 재실행해도 다시 안 쓴다 (멱등)
        M.run(tr5, mandir, out=lambda s: None)
        check("이미 승격된 날짜(2026-08-27)를 건너뛴다",
              len(list(mandir.glob("*.json"))) == 1)

        # 8 combined_sha가 collect-minute-kis.py와 정확히 같은 알고리즘
        kismod = load("collect-minute-kis")
        sample = [{"name": "b.parquet", "sha256": "22"},
                  {"name": "a.parquet", "sha256": "11"}]
        check("combined_sha가 VM 쪽 구현과 동일",
              M.combined_sha(sample) == kismod.combined_sha(sample))

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
