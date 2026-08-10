"""alive-monitor.py — 수집이 멈춘 것을 늦게 아는 문제를 막는다.

**기존 코드를 고치지 않는다.** Collector가 이미 남기는 산출물만 읽는다 -
manifest와 resume 상태다. 관측을 위해 수집기에 훅을 박으면 관측이 수집을
망가뜨릴 수 있다(교훈63).

무엇을 보는가:
    expectedDate               오늘 수집했어야 하는 영업일
    lastManifestAt             마지막 manifest가 생긴 시각
    lastSuccessfulCollectionAt 인수 조건을 통과한 마지막 수집
    completedCount             그날 해결된 종목 수 (OK + GAP)
    failureCount               미해결 종목 수

판정은 상태를 저장하지 않고 매번 계산한다(교훈54). 'complete'를 파일에 두면
그것을 맞추려고 상태를 다시 쓰게 되고, 그때 사실이 흔들린다.

fail-soft: 어떤 경로에서도 예외를 던지지 않는다. 감시기가 죽으면 감시가
사라지는데, 그것이 감시 대상의 죽음보다 늦게 발견된다.

종료 코드
    0  OK          기대한 수집이 끝났다
    1  STALE       기한이 지났는데 없다 / 인수 조건 실패 / 미해결 과다
    2  PENDING     아직 기한 전이다 (알림 대상이 아니다)

사용:
    python3 scripts/alive-monitor.py
    python3 scripts/alive-monitor.py --deadline 18:00 --json
    python3 scripts/alive-monitor.py --selftest
"""

import argparse
import json
import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(errors="replace")
    except Exception:
        pass

REPO = Path(__file__).resolve().parent.parent
KST = timezone(timedelta(hours=9))

DEFAULT_MANIFEST = REPO / "data" / "backfill" / "minute" / "manifest"
DEFAULT_STATE = REPO / "data" / "minute" / "_state"
DEFAULT_CALENDAR = REPO / "data" / "backfill" / "calendar.json"


def now_kst():
    return datetime.now(KST)


def safe(fn, default=None):
    """fail-soft의 단일 창구. 감시기는 어떤 이유로도 죽지 않는다."""
    try:
        return fn()
    except Exception:
        return default


def load_trading_days(path):
    def _():
        d = json.loads(Path(path).read_text(encoding="utf-8"))
        return set(d.get("tradingDays") or [])
    return safe(_, set()) or set()


def expected_date(now, trading_days):
    """오늘 수집했어야 하는 영업일.

    캘린더가 있으면 그것이 진실이다. 없으면 주말만 제외한다 -
    거친 쪽으로 틀리면 공휴일에 거짓 경보가 난다. 그래서 캘린더가
    없다는 사실 자체를 보고에 남긴다(모르는 것은 0이 아니다, 교훈57).
    """
    d = now.date()
    if trading_days:
        for i in range(0, 15):
            cand = (d - timedelta(days=i)).isoformat()
            if cand in trading_days:
                return cand, "calendar"
        return None, "calendar-miss"
    for i in range(0, 15):
        c = d - timedelta(days=i)
        if c.weekday() < 5:
            return c.isoformat(), "weekday-heuristic"
    return None, "unknown"


def read_manifest(manifest_dir, date):
    def _():
        p = Path(manifest_dir) / (date + ".json")
        if not p.exists():
            return None
        m = json.loads(p.read_text(encoding="utf-8"))
        m["_mtime"] = datetime.fromtimestamp(p.stat().st_mtime,
                                             KST).isoformat()
        return m
    return safe(_)


def read_state(state_dir, date):
    def _():
        p = Path(state_dir) / ("state-" + date + ".json")
        if not p.exists():
            return None
        st = json.loads(p.read_text(encoding="utf-8"))
        st["_mtime"] = datetime.fromtimestamp(p.stat().st_mtime,
                                              KST).isoformat()
        return st
    return safe(_)


def latest_manifest(manifest_dir):
    def _():
        files = sorted(Path(manifest_dir).glob("*.json"))
        if not files:
            return None, None
        newest = max(files, key=lambda p: p.stat().st_mtime)
        m = json.loads(newest.read_text(encoding="utf-8"))
        return (m, datetime.fromtimestamp(newest.stat().st_mtime,
                                          KST).isoformat())
    return safe(_, (None, None)) or (None, None)


def tally(state):
    """상태에서 해결/미해결을 센다. 사실만 세고 판정하지 않는다."""
    if not state:
        return {"completed": None, "failed": None, "symbols": None}
    syms = state.get("symbols") or {}
    done = sum(1 for v in syms.values()
               if v.get("status") in ("OK", "GAP"))
    fail = sum(1 for v in syms.values() if v.get("status") == "UNRESOLVED")
    return {"completed": done, "failed": fail, "symbols": len(syms)}


def judge(now, deadline_hm, exp_date, manifest, state, max_unresolved_rate):
    """매번 계산한다. 저장하지 않는다."""
    reasons = []
    if not exp_date:
        return "STALE", ["기대 영업일을 정하지 못했다"]

    hh, _, mm = deadline_hm.partition(":")
    deadline = now.replace(hour=int(hh), minute=int(mm or 0),
                           second=0, microsecond=0)
    past_deadline = now >= deadline

    if manifest is None:
        if past_deadline:
            return "STALE", ["기한(%s)이 지났는데 %s manifest가 없다"
                             % (deadline_hm, exp_date)]
        return "PENDING", ["아직 기한 전이다 (%s)" % deadline_hm]

    if manifest.get("date") != exp_date:
        reasons.append("manifest 날짜가 기대와 다르다: %s != %s"
                       % (manifest.get("date"), exp_date))
    if not manifest.get("acceptancePassed"):
        reasons.append("인수 조건 실패로 기록됐다")
    if manifest.get("writerError"):
        reasons.append("writerError: " + str(manifest["writerError"])[:80])

    t = tally(state)
    if t["symbols"]:
        rate = (t["failed"] or 0) / t["symbols"]
        if rate > max_unresolved_rate:
            reasons.append("미해결 비율 %.3f > 상한 %.3f"
                           % (rate, max_unresolved_rate))

    if manifest.get("rows", 0) <= 0:
        reasons.append("행이 0이다")

    return ("STALE" if reasons else "OK"), (reasons or ["정상"])


def run(args):
    now = args._now or now_kst()
    tds = load_trading_days(args.calendar)
    exp, how = expected_date(now, tds)
    man = read_manifest(args.manifest, exp) if exp else None
    st = read_state(args.state, exp) if exp else None
    newest, newest_at = latest_manifest(args.manifest)
    t = tally(st)

    status, reasons = judge(now, args.deadline, exp, man, st,
                            args.max_unresolved_rate)

    report = {
        "schemaVersion": "ALIVE-1.0",
        "checkedAt": now.isoformat(),
        "status": status,
        "reasons": reasons,
        "expectedDate": exp,
        "expectedDateSource": how,
        "calendarLoaded": bool(tds),
        "lastManifestAt": (man or {}).get("_mtime") or newest_at,
        "lastSuccessfulCollectionAt": (
            newest_at if (newest or {}).get("acceptancePassed") else None),
        "lastSuccessfulDate": (
            (newest or {}).get("date")
            if (newest or {}).get("acceptancePassed") else None),
        "completedCount": t["completed"],
        "failureCount": t["failed"],
        "symbolCount": t["symbols"],
        "rows": (man or {}).get("rows"),
        "acceptancePassed": (man or {}).get("acceptancePassed"),
        "manifestDir": str(args.manifest),
        "stateDir": str(args.state),
    }
    return report


def emit(report, as_json):
    if as_json:
        print(json.dumps(report, ensure_ascii=False, indent=2))
        return
    r = report
    print()
    print("  분봉 수집 감시  " + r["checkedAt"])
    print("  상태            " + r["status"])
    for x in r["reasons"]:
        print("                  - " + x)
    print()
    rows = [
        ("기대 영업일", str(r["expectedDate"]) + "  (" +
         r["expectedDateSource"] + ")"),
        ("마지막 manifest", str(r["lastManifestAt"])),
        ("마지막 성공 수집", str(r["lastSuccessfulCollectionAt"]) +
         ("  " + str(r["lastSuccessfulDate"])
          if r["lastSuccessfulDate"] else "")),
        ("해결 종목", str(r["completedCount"])),
        ("미해결 종목", str(r["failureCount"])),
        ("행", str(r["rows"])),
        ("인수 조건", str(r["acceptancePassed"])),
    ]
    for k, v in rows:
        print("  " + k.ljust(18) + v)
    print()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--manifest", default=str(DEFAULT_MANIFEST))
    ap.add_argument("--state", default=str(DEFAULT_STATE))
    ap.add_argument("--calendar", default=str(DEFAULT_CALENDAR))
    ap.add_argument("--deadline", default="18:00",
                    help="이 시각까지 그날 manifest가 없으면 STALE")
    ap.add_argument("--max-unresolved-rate", type=float, default=0.05)
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--selftest", action="store_true")
    args = ap.parse_args()
    args._now = None

    # 경로는 환경변수로도 받는다. 하드코딩하지 않는다(VM 운영 기준 8).
    args.manifest = os.environ.get("MINUTE_MANIFEST_DIR", args.manifest)
    args.state = os.environ.get("MINUTE_STATE_DIR", args.state)

    if args.selftest:
        import importlib.util
        p = REPO / "scripts" / "test-alive-monitor.py"
        if not p.exists():
            print("테스트 파일이 없다")
            return 1
        spec = importlib.util.spec_from_file_location("t", p)
        t = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(t)
        return t.run_all(sys.modules[__name__])

    report = safe(lambda: run(args))
    if report is None:
        # 감시기 자신이 실패해도 조용히 죽지 않는다.
        report = {"schemaVersion": "ALIVE-1.0", "status": "STALE",
                  "reasons": ["감시기 자체가 실패했다"],
                  "checkedAt": now_kst().isoformat()}
    emit(report, args.json)
    return {"OK": 0, "STALE": 1, "PENDING": 2}.get(report["status"], 1)


if __name__ == "__main__":
    sys.exit(main())
