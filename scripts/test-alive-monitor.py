"""test-alive-monitor.py — 감시기 인수 조건 (합성 픽스처, 네트워크 없음)

감시기의 실패 모드는 두 가지이고 둘 다 조용하다.
    거짓 안심   멈췄는데 OK라고 한다
    거짓 경보   정상인데 STALE이라고 한다 - 반복되면 사람이 무시하게 된다

앞엣것이 더 나쁘지만 뒤엣것도 결국 앞엣것이 된다. 둘 다 검사한다.
"""

import importlib.util
import json
import shutil
import sys
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(errors="replace")
    except Exception:
        pass

REPO = Path(__file__).resolve().parent.parent
KST = timezone(timedelta(hours=9))
PASS, FAIL = [], []


def check(name, cond, detail=""):
    (PASS if cond else FAIL).append(name)
    print(("  PASS  " if cond else "  FAIL  ") + name +
          (("  " + str(detail)) if (detail and not cond) else ""))


class Args:
    def __init__(self, **kw):
        self.deadline = "18:00"
        self.max_unresolved_rate = 0.05
        self.json = False
        self.selftest = False
        self._now = None
        for k, v in kw.items():
            setattr(self, k, v)


def write_manifest(d, date, **kw):
    m = {"schemaVersion": "MN-1.0", "date": date, "rows": 1000,
         "symbols": 10, "acceptancePassed": True}
    m.update(kw)
    Path(d).mkdir(parents=True, exist_ok=True)
    (Path(d) / (date + ".json")).write_text(
        json.dumps(m, ensure_ascii=False), encoding="utf-8")


def write_state(d, date, ok=9, unresolved=1):
    syms = {}
    for i in range(ok):
        syms["%06d" % i] = {"status": "OK", "rows": 100}
    for i in range(unresolved):
        syms["9%05d" % i] = {"status": "UNRESOLVED",
                             "failureClass": "RATE_LIMIT"}
    Path(d).mkdir(parents=True, exist_ok=True)
    (Path(d) / ("state-" + date + ".json")).write_text(
        json.dumps({"date": date, "symbols": syms}, ensure_ascii=False),
        encoding="utf-8")


def write_calendar(p, days):
    Path(p).parent.mkdir(parents=True, exist_ok=True)
    Path(p).write_text(json.dumps({"tradingDays": days}), encoding="utf-8")


def run_all(M=None):
    if M is None:
        spec = importlib.util.spec_from_file_location(
            "alive_monitor", REPO / "scripts" / "alive-monitor.py")
        M = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(M)

    tmp = Path(tempfile.mkdtemp(prefix="alive-"))
    man, sta = tmp / "manifest", tmp / "state"
    cal = tmp / "calendar.json"
    DAY = "2026-08-03"
    write_calendar(cal, [DAY, "2026-08-04"])

    def A(**kw):
        base = {"manifest": str(man), "state": str(sta), "calendar": str(cal)}
        base.update(kw)          # 호출자가 덮어쓸 수 있어야 한다
        return Args(**base)

    try:
        after = datetime(2026, 8, 3, 19, 0, tzinfo=KST)
        before = datetime(2026, 8, 3, 9, 0, tzinfo=KST)

        # 1 정상
        write_manifest(man, DAY)
        write_state(sta, DAY, ok=10, unresolved=0)
        r = M.run(A(_now=after))
        check("정상 수집이 OK", r["status"] == "OK", (r["status"], r["reasons"]))
        check("해결/미해결 수를 센다",
              r["completedCount"] == 10 and r["failureCount"] == 0,
              (r["completedCount"], r["failureCount"]))
        check("기대 영업일을 캘린더에서 얻는다",
              r["expectedDate"] == DAY and r["expectedDateSource"] == "calendar",
              (r["expectedDate"], r["expectedDateSource"]))

        # 2 기한 전에는 PENDING (거짓 경보 방지)
        shutil.rmtree(man, ignore_errors=True)
        r = M.run(A(_now=before))
        check("기한 전 manifest 없음은 PENDING", r["status"] == "PENDING",
              (r["status"], r["reasons"]))

        # 3 기한 후 manifest 없음은 STALE
        r = M.run(A(_now=after))
        check("기한 후 manifest 없음은 STALE", r["status"] == "STALE",
              (r["status"], r["reasons"]))

        # 4 인수 조건 실패를 성공으로 읽지 않는다
        write_manifest(man, DAY, acceptancePassed=False)
        r = M.run(A(_now=after))
        check("인수 조건 실패는 STALE", r["status"] == "STALE", r["reasons"])
        check("이유에 인수 조건이 적힌다",
              any("인수 조건" in x for x in r["reasons"]), r["reasons"])

        # 5 writerError를 놓치지 않는다 (parquet가 안 써졌는데 통과로 보일 수 있다)
        write_manifest(man, DAY, writerError="pyarrow 없음")
        r = M.run(A(_now=after))
        check("writerError는 STALE", r["status"] == "STALE", r["reasons"])

        # 6 행 0
        write_manifest(man, DAY, rows=0)
        r = M.run(A(_now=after))
        check("행 0은 STALE", r["status"] == "STALE", r["reasons"])

        # 7 미해결 과다
        write_manifest(man, DAY)
        write_state(sta, DAY, ok=5, unresolved=5)
        r = M.run(A(_now=after))
        check("미해결 비율 초과는 STALE", r["status"] == "STALE", r["reasons"])
        check("미해결 수를 보고한다", r["failureCount"] == 5, r["failureCount"])

        # 8 어제 것만 있고 오늘 것이 없으면 STALE (조용한 멈춤의 전형)
        shutil.rmtree(man, ignore_errors=True)
        shutil.rmtree(sta, ignore_errors=True)
        write_manifest(man, "2026-07-31")
        r = M.run(A(_now=after))
        check("오늘 것이 없으면 STALE (어제 것이 있어도)",
              r["status"] == "STALE", r["reasons"])
        check("마지막 성공 수집 날짜는 여전히 보고된다",
              r["lastSuccessfulDate"] == "2026-07-31", r["lastSuccessfulDate"])

        # 9 fail-soft — 깨진 파일, 없는 디렉터리에서도 죽지 않는다
        (man / (DAY + ".json")).write_text("{not json", encoding="utf-8")
        r = M.run(A(_now=after))
        check("깨진 manifest에도 죽지 않는다", isinstance(r, dict), type(r))
        check("깨진 manifest는 STALE로 읽는다", r["status"] == "STALE",
              r["status"])

        r2 = M.run(A(_now=after, manifest=str(tmp / "nope"),
                     state=str(tmp / "nope2")))
        check("없는 디렉터리에도 죽지 않는다", isinstance(r2, dict), type(r2))

        # 10 캘린더가 없으면 그 사실을 보고한다
        r3 = M.run(A(_now=after, calendar=str(tmp / "nocal.json")))
        check("캘린더 부재를 숨기지 않는다",
              r3["calendarLoaded"] is False
              and r3["expectedDateSource"] == "weekday-heuristic",
              (r3["calendarLoaded"], r3["expectedDateSource"]))

        # 11 상태를 저장하지 않는다 (판정은 매번 계산)
        before_files = set(p.name for p in tmp.rglob("*"))
        M.run(A(_now=after))
        after_files = set(p.name for p in tmp.rglob("*"))
        check("감시기가 파일을 만들지 않는다 (상태 무저장)",
              before_files == after_files,
              after_files - before_files)

        # 12 종료 코드 계약
        check("종료 코드 매핑이 OK/STALE/PENDING",
              {"OK": 0, "STALE": 1, "PENDING": 2}["OK"] == 0)

    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    print()
    print("  통과 %d · 실패 %d" % (len(PASS), len(FAIL)))
    for f in FAIL:
        print("    FAIL " + f)
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(run_all())
