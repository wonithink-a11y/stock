"""test-run-minute-daily.py — 상시 러너 회귀 (합성 픽스처, 네트워크 없음)

러너가 답하는 질문은 하나다: **오늘 어느 날짜를 돌려야 하는가.**
그 답이 틀리면 수집기가 아무리 정확해도 하루가 사라진다. 그래서 여기서
재는 것은 수집 품질이 아니라 날짜 선택과 재시도 경계다.

사용:
    python scripts/test-run-minute-daily.py
    python scripts/run-minute-daily.py --selftest
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

PASS = []
FAIL = []


def check(name, cond, detail=""):
    (PASS if cond else FAIL).append(name)
    print(("  PASS  " if cond else "  FAIL  ") + name +
          (("  " + str(detail)) if (detail and not cond) else ""))


def load(name, fn):
    spec = importlib.util.spec_from_file_location(name, REPO / "scripts" / fn)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


class Args:
    def __init__(self, **kw):
        self.days = 3
        self.date = None
        self.after = "16:05"
        self.budget_minutes = 180.0
        self.force = False
        self.dry_run = False
        self.quiet = True
        self.json = False
        for k, v in kw.items():
            setattr(self, k, v)


def at(s):
    return datetime.strptime(s, "%Y-%m-%d %H:%M").replace(tzinfo=KST)


def run_all(R=None):
    if R is None:
        R = load("run_minute_daily", "run-minute-daily.py")
    M = load("collect_minute_kis", "collect-minute-kis.py")
    tmp = Path(tempfile.mkdtemp(prefix="mindaily-"))

    # 캘린더가 2026-08-04까지만 덮는다. 실운영이 서 있는 자리와 같다 -
    # A0.5 캘린더는 매일 갱신되지 않으므로 '그 뒤'가 정상 상태다.
    ctx = {"tradingDays": {"2026-07-31", "2026-08-03", "2026-08-04"},
           "calendarFrom": "2026-07-31", "calendarTo": "2026-08-04",
           "listedAt": {}, "delistedAt": {}}
    empty_ctx = {"tradingDays": set(), "calendarFrom": None,
                 "calendarTo": None, "listedAt": {}, "delistedAt": {}}

    try:
        # 1 장 마감 전에는 오늘을 후보에 넣지 않는다
        # 넣으면 전 종목이 빈 응답을 내고 그날이 휴장으로 굳는다(교훈81).
        early = R.candidate_dates(M, ctx, at("2026-08-12 09:30"), 1, "16:05")
        late = R.candidate_dates(M, ctx, at("2026-08-12 16:30"), 1, "16:05")
        check("마감 전에는 오늘이 후보가 아니다",
              early == ["2026-08-11"], early)
        check("마감 후에는 오늘이 후보다", late == ["2026-08-12"], late)

        # 2 캘린더 범위 밖은 평일 휴리스틱으로 후보에 넣는다
        # 여기서 빠뜨리면 캘린더가 낡은 동안의 모든 날이 조용히 사라진다.
        got = R.candidate_dates(M, ctx, at("2026-08-12 17:00"), 4, "16:05")
        check("범위 밖 평일이 후보에 들어간다",
              got == ["2026-08-12", "2026-08-11", "2026-08-10",
                      "2026-08-07"], got)
        check("주말은 후보가 아니다",
              not any(d in ("2026-08-08", "2026-08-09") for d in got), got)

        # 3 캘린더가 덮는 구간에서는 캘린더가 진실이다
        got = R.candidate_dates(M, ctx, at("2026-08-04 17:00"), 3, "16:05")
        check("범위 안에서는 캘린더의 비거래일을 건너뛴다",
              got == ["2026-08-04", "2026-08-03", "2026-07-31"], got)

        # 4 캘린더가 아예 없어도 멈추지 않는다
        got = R.candidate_dates(M, empty_ctx, at("2026-08-12 17:00"), 2,
                                "16:05")
        check("캘린더가 없으면 평일로 후보를 만든다",
              got == ["2026-08-12", "2026-08-11"], got)

        # 5 통과한 manifest가 있는 날은 다시 돌지 않는다
        md = tmp / "man"
        md.mkdir(parents=True, exist_ok=True)
        (md / "2026-08-11.json").write_text(json.dumps(
            {"date": "2026-08-11", "acceptancePassed": True, "rows": 100,
             "dayVerdict": "TRADING_OBSERVED"}), encoding="utf-8")
        todo, skip = R.plan(M, Args(days=3), ctx, md, at("2026-08-12 17:00"))
        check("통과한 날은 건너뛴다", "2026-08-11" not in todo, todo)
        check("건너뛴 이유가 보고된다",
              any(s["date"] == "2026-08-11" for s in skip), skip)
        check("오래된 것부터 돈다 (사라질 위험이 큰 쪽이 먼저)",
              todo == sorted(todo) and todo == ["2026-08-10", "2026-08-12"],
              todo)

        # 6 실패한 manifest는 통과가 아니다 — 다음 실행이 이어받는다
        # 이것이 자가 치유의 실체다. 하루의 실패가 그날로 끝나면 안 된다.
        (md / "2026-08-10.json").write_text(json.dumps(
            {"date": "2026-08-10", "acceptancePassed": False}),
            encoding="utf-8")
        todo, _ = R.plan(M, Args(days=3), ctx, md, at("2026-08-12 17:00"))
        check("인수 조건 실패한 날은 다시 돈다", "2026-08-10" in todo, todo)
        ok, _ = R.already_done(md, "2026-08-11")
        no, _ = R.already_done(md, "2026-08-10")
        check("판정 기준은 파일 존재가 아니라 acceptancePassed",
              ok and not no, (ok, no))
        miss, _ = R.already_done(md, "2026-08-07")
        check("manifest가 없으면 안 한 것이다", not miss)

        # 7 깨진 manifest를 '통과'로 읽지 않는다
        (md / "2026-08-07.json").write_text("{not json",
                                            encoding="utf-8")
        bad, _ = R.already_done(md, "2026-08-07")
        check("읽을 수 없는 manifest는 통과가 아니다", not bad)

        # 8 --date는 창을 무시하고 그 날짜만 본다
        todo, _ = R.plan(M, Args(date="2026-07-31"), ctx, md,
                         at("2026-08-12 17:00"))
        check("--date가 창을 대신한다", todo == ["2026-07-31"], todo)
        todo, _ = R.plan(M, Args(date="2026-08-11", force=True), ctx, md,
                         at("2026-08-12 17:00"))
        check("--force가 통과한 날도 다시 돌린다",
              todo == ["2026-08-11"], todo)

        # 9 --days가 창의 크기를 정한다
        got = R.candidate_dates(M, ctx, at("2026-08-12 17:00"), 10, "16:05")
        check("--days만큼 영업일을 센다 (달력일이 아니다)",
              len(got) == 10 and "2026-08-08" not in got, got)

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
