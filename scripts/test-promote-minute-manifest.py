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


def closed_day(date, transport, verdict="CLOSED_CONFIRMED", rows=0):
    """휴장일. 수집기는 acceptance를 통과시키되 조각을 만들지 않는다."""
    man = {"date": date, "acceptancePassed": True, "parts": [],
           "rows": rows, "sha256": None, "dayVerdict": verdict}
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

        # 8 휴장일 - 조각이 없는 것이 정상이다. 거부가 아니라 승격이다.
        #   (거부하면 백로그에 영원히 남아 매 실행을 붉게 만든다. 실제로
        #    2026-08-17이 5회 연속 job을 붉게 만들었다)
        tr6 = osmod.FakeOciTransport()
        closed_day("2026-08-17", tr6)
        ok, why, man = M.verify_day(tr6, "2026-08-17")
        check("휴장일(CLOSED_CONFIRMED)이 통과한다", ok and why is None, why)
        tr6b = osmod.FakeOciTransport()
        closed_day("2026-08-17", tr6b, verdict="CLOSED_INFERRED")
        ok, why, _ = M.verify_day(tr6b, "2026-08-17")
        check("휴장일(CLOSED_INFERRED)이 통과한다", ok and why is None, why)

        # 9 UNKNOWN은 휴장이 아니다 - 장애와 휴장을 구분 못 한 상태다(교훈57)
        tr7 = osmod.FakeOciTransport()
        closed_day("2026-08-20", tr7, verdict="UNKNOWN")
        ok, why, _ = M.verify_day(tr7, "2026-08-20")
        check("dayVerdict=UNKNOWN + 조각 없음은 여전히 거부된다",
              not ok and "parts" in why, why)
        tr7b = osmod.FakeOciTransport()
        closed_day("2026-08-21", tr7b, verdict=None)
        ok, why, _ = M.verify_day(tr7b, "2026-08-21")
        check("dayVerdict 없음 + 조각 없음은 여전히 거부된다",
              not ok and "parts" in why, why)

        # 10 휴장이라면서 rows가 있다 - 모순이다. 통과시키지 않는다
        tr8 = osmod.FakeOciTransport()
        closed_day("2026-08-22", tr8, rows=17)
        ok, why, _ = M.verify_day(tr8, "2026-08-22")
        check("CLOSED_*인데 rows>0인 모순은 거부된다",
              not ok and "parts" in why, why)

        # 11 run() — 휴장일도 파일로 남고(다시 안 본다) job은 붉어지지 않는다
        tr9 = osmod.FakeOciTransport()
        good_day("2026-08-18", tr9, osmod)
        closed_day("2026-08-17", tr9)
        mandir2 = tmp / "manifest2"
        code = M.run(tr9, mandir2, out=lambda s: None)
        check("휴장일만 섞인 실행의 exit code가 0", code == 0, code)
        check("휴장일이 manifest 파일로 남는다",
              (mandir2 / "2026-08-17.json").exists()
              and (mandir2 / "2026-08-18.json").exists(),
              list(mandir2.glob("*.json")))
        written = json.loads((mandir2 / "2026-08-17.json").read_text("utf-8"))
        check("남은 휴장 manifest가 rows=0·dayVerdict를 그대로 담는다",
              written["rows"] == 0
              and written["dayVerdict"] == "CLOSED_CONFIRMED", written)
        M.run(tr9, mandir2, out=lambda s: None)
        check("휴장일이 백로그에서 빠진다(재실행해도 다시 안 본다)",
              len(list(mandir2.glob("*.json"))) == 2,
              list(mandir2.glob("*.json")))

        # 12 combined_sha가 collect-minute-kis.py와 정확히 같은 알고리즘
        kismod = load("collect-minute-kis")
        sample = [{"name": "b.parquet", "sha256": "22"},
                  {"name": "a.parquet", "sha256": "11"}]
        check("combined_sha가 VM 쪽 구현과 동일",
              M.combined_sha(sample) == kismod.combined_sha(sample))

        # 13 저장소 구멍 검사 — 2026-09-10 사고(워크플로 녹색 · 데이터 없음)
        cal = ["2026-09-01", "2026-09-02", "2026-09-03", "2026-09-04",
               "2026-09-07", "2026-09-08", "2026-09-09", "2026-09-10"]
        full = set(cal)
        check("구멍이 없으면 빈 목록",
              M.repo_holes(full, cal, "2026-09-10") == [])
        check("실종된 날을 집어낸다",
              M.repo_holes(full - {"2026-09-04", "2026-09-07"}, cal,
                           "2026-09-10") == ["2026-09-04", "2026-09-07"])
        check("가장 최근 거래일은 grace 로 봐준다(아직 안 올 수 있다)",
              M.repo_holes(full - {"2026-09-10"}, cal, "2026-09-10") == [])
        check("미래 거래일은 후보가 아니다",
              M.repo_holes(full - {"2026-09-09", "2026-09-10"}, cal,
                           "2026-09-08") == [])
        check("lookback 밖의 옛 구멍은 영원히 붉지 않다",
              M.repo_holes(full - {"2026-09-01"}, cal, "2026-09-10",
                           lookback=3) == [])

        # 구멍이 있으면 '승격할 것 없다' 경로에서도 exit 1 이다.
        # 이 경로가 이번 사고에서 6일간 녹색이었다.
        tr13 = osmod.FakeOciTransport()
        mandir13 = tmp / "m13"
        mandir13.mkdir()
        for d in cal[:-2]:
            (mandir13 / (d + ".json")).write_text("{}", encoding="utf-8")
        check("구멍이 있으면 승격할 게 없어도 exit 1",
              M.run(tr13, mandir13, out=lambda s: None, trading_days=cal,
                    today="2026-09-10") == 1)
        check("구멍이 없으면 그대로 exit 0",
              M.run(tr13, mandir13, out=lambda s: None, trading_days=cal,
                    today="2026-09-09") == 0)

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
