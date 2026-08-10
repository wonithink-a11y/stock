"""run-minute-daily.py — Broad 당일 증분을 매일 돌리는 러너 (MN-1.0 §6.3·§9)

수집기(collect-minute-kis.py)는 '하루치'를 안다. 이 스크립트는 '어느 하루를
돌려야 하는가'를 안다. 둘을 갈라 두는 이유는 수집기가 이미 검증된 표면이고,
운영 판단(무엇을 언제 몇 번)은 그것과 다른 속도로 바뀌기 때문이다.

왜 하루가 아니라 창(window)인가:
    오늘치가 장 마감 직후 바로 오지 않거나, 그날 밤 VM이 죽거나, 유량초과가
    몰려 인수 조건을 못 넘길 수 있다. 매 실행이 '오늘 하루'만 본다면 그런
    하루는 그대로 사라진다 - 246영업일 뒤에는 복구 경로가 없다.
    최근 N영업일 중 통과한 manifest가 없는 날을 오래된 것부터 채운다.
    그러면 하루의 실패가 다음 실행에서 저절로 메워진다.

건드리지 않는 것:
    - 통과한 manifest가 있는 날은 다시 돌지 않는다. 5% 예산 안의 미해결을
      쫓아가려면 manifest를 덮어써야 하는데, §4는 재수집을 '덮어쓰기'가
      아니라 '새 requestedAt의 버전'으로 정했다. 그 정책은 pendingT1이다.
    - 캘린더(A0.5 산출물)를 고치지 않는다. 캘린더가 못 덮는 날짜는
      평일 휴리스틱으로 후보에 넣고, 실제 휴장 여부는 수집기가 정찰로 답한다.

종료 코드
    0  전부 정상 (수집 성공 · 휴장 · 할 일 없음)
    1  인수 조건 실패가 하나 이상 있다
    2  실행 전 구성 오류 (키 없음 · 유니버스 비어 있음)

사용:
    python3 scripts/run-minute-daily.py
    python3 scripts/run-minute-daily.py --days 5 --dry-run
    python3 scripts/run-minute-daily.py --date 2026-08-07
    python3 scripts/run-minute-daily.py --selftest
"""

import argparse
import importlib.util
import json
import sys
import time
from datetime import date as _date, datetime, timedelta, timezone
from pathlib import Path

for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(errors="replace")
    except Exception:
        pass

REPO = Path(__file__).resolve().parent.parent
KST = timezone(timedelta(hours=9))


def load_collector():
    """하이픈이 든 파일명이라 import 문으로는 못 부른다."""
    spec = importlib.util.spec_from_file_location(
        "collect_minute_kis", REPO / "scripts" / "collect-minute-kis.py")
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


def now_kst():
    return datetime.now(KST)


# ---------------------------------------------------------------- 날짜 선택

def is_expected_trading_day(M, day, ctx):
    """그날 장이 섰을 것으로 보는가.

    캘린더가 덮으면 캘린더가 진실이다. 못 덮으면 평일만 후보로 둔다 -
    거친 쪽으로 틀리면 공휴일에 헛돌지만, 그 비용은 정찰 3종목이다.
    반대로 틀리면 그날치가 사라진다. 비대칭이라 거친 쪽을 고른다.
    """
    if M.calendar_covers(day, ctx):
        return day in ctx["tradingDays"]
    y, m, d = (int(x) for x in day.split("-"))
    return _date(y, m, d).weekday() < 5


def candidate_dates(M, ctx, now, days, after_hm):
    """수집 대상 후보. 최근 것부터 days개.

    장 마감 전에는 오늘을 후보로 넣지 않는다. 넣으면 전 종목이 빈 응답을
    내고 그날이 '휴장'으로 굳는다 - 성공 코드는 '내 질문에 답했다'를
    뜻하지 않는다(교훈81).
    """
    hh, _, mm = after_hm.partition(":")
    cut = now.date()
    if now.hour * 60 + now.minute < int(hh) * 60 + int(mm or 0):
        cut = cut - timedelta(days=1)

    out, d = [], cut
    for _ in range(days * 4 + 30):
        if len(out) >= days:
            break
        s = d.isoformat()
        if is_expected_trading_day(M, s, ctx):
            out.append(s)
        d -= timedelta(days=1)
    return out


def already_done(manifest_dir, day):
    """통과한 manifest가 있는가. manifest의 존재가 아니라 통과가 기준이다."""
    p = Path(manifest_dir) / (day + ".json")
    if not p.exists():
        return False, None
    try:
        m = json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return False, None
    return bool(m.get("acceptancePassed")), m


# ---------------------------------------------------------------- 실행

def plan(M, args, ctx, manifest_dir, now):
    if args.date:
        cands = [M.dashed(args.date)]
    else:
        cands = candidate_dates(M, ctx, now, args.days, args.after)

    todo, skip = [], []
    for d in cands:
        done, man = already_done(manifest_dir, d)
        if done and not args.force:
            skip.append({"date": d, "why": "manifest 통과",
                         "verdict": (man or {}).get("dayVerdict"),
                         "rows": (man or {}).get("rows")})
        else:
            todo.append(d)
    todo.sort()          # 오래된 것부터. 사라질 위험이 큰 쪽이 먼저다
    return todo, skip


def run(M, args, out=print):
    pol = M.load_policy()
    ctx = M.load_context()
    raw, state, mandir = M.env_paths(pol)
    now = now_kst()

    todo, skip = plan(M, args, ctx, mandir, now)

    out("")
    out("  분봉 Broad 상시 수집   " + now.strftime("%Y-%m-%dT%H:%M:%S+09:00"))
    out("  raw      " + str(raw))
    out("  manifest " + str(mandir))
    out("  캘린더    ~" + str(ctx.get("calendarTo")) +
        ("  (그 뒤는 평일 휴리스틱)" if ctx.get("calendarTo") else "  (없음)"))
    for s in skip:
        out("  건너뜀   " + s["date"] + "  " + s["why"] +
            "  " + str(s.get("verdict") or "") + " rows=" + str(s.get("rows")))
    if not todo:
        out("  할 일 없다")
        out("")
        return 0, []

    tickers = M.broad_tickers()
    if not tickers:
        out("  [중단] 유니버스가 비었다 - A1a current.jsonl을 확인한다")
        return 2, []
    out("  대상     " + ", ".join(todo) + "   종목 " + str(len(tickers)))
    out("")

    if args.dry_run:
        out("  --dry-run: 부르지 않았다")
        return 0, []

    started = time.time()
    results, bad = [], 0
    for d in todo:
        if (time.time() - started) / 60.0 > args.budget_minutes:
            out("  [예산] " + str(args.budget_minutes) + "분을 넘겨 남은 날짜는 "
                "다음 실행으로 넘긴다: " + d)
            break
        t0 = time.time()
        # --force는 '다시 받는다'는 뜻이다. resume을 켠 채로 다시 돌면
        # 상태가 전부 완료라 아무것도 안 부르고 행 0으로 인수 조건만 깬다.
        res = M.collect_one_day(
            d, tickers, pol=pol, ctx=ctx, resume=not args.force,
            paths=(raw, state, mandir), source="broad:a1a",
            progress=(None if args.quiet else
                      (lambda i, n: out("    %d/%d" % (i, n)))))
        man = res["manifest"]
        line = {
            "date": d,
            "verdict": man.get("dayVerdict"),
            "rows": man.get("rows"),
            "symbols": man.get("symbols"),
            "withRows": man.get("symbolsWithRows"),
            "notQueried": man.get("symbolsNotQueried"),
            "unresolved": man.get("unresolved"),
            "passed": bool(res["acceptancePassed"]),
            "elapsedSec": round(time.time() - t0, 1),
            "manifest": res.get("manifestPath"),
        }
        results.append(line)
        if not line["passed"]:
            bad += 1
        out("  " + d + "  " + str(line["verdict"]).ljust(18) +
            ("PASS" if line["passed"] else "FAIL") +
            "  rows=" + str(line["rows"]) +
            "  종목=" + str(line["withRows"]) + "/" + str(line["symbols"]) +
            "  " + str(line["elapsedSec"]) + "s")
        if not line["passed"]:
            for c in man.get("acceptance", []):
                if not c["통과"]:
                    out("        FAIL " + c["항목"] + "  " +
                        json.dumps(c["실측"], ensure_ascii=False)[:140])

    out("")
    return (1 if bad else 0), results


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--days", type=int, default=3,
                    help="최근 몇 영업일을 후보로 볼 것인가 (기본 3)")
    ap.add_argument("--date", help="이 날짜만 돌린다")
    ap.add_argument("--after", default="16:05",
                    help="이 시각 전에는 오늘을 후보에 넣지 않는다 (KST)")
    ap.add_argument("--budget-minutes", type=float, default=180.0)
    ap.add_argument("--force", action="store_true",
                    help="통과한 manifest가 있어도 전부 다시 받는다 (덮어쓴다)")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--quiet", action="store_true")
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--selftest", action="store_true")
    args = ap.parse_args()

    if args.selftest:
        p = REPO / "scripts" / "test-run-minute-daily.py"
        if not p.exists():
            print("테스트 파일이 없다")
            return 1
        spec = importlib.util.spec_from_file_location("t", p)
        t = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(t)
        return t.run_all(sys.modules[__name__])

    M = load_collector()
    try:
        code, results = run(M, args)
    except SystemExit as e:
        # 키·계약 같은 구성 오류다. 수집 실패와 구분한다.
        print("  [중단] " + str(e))
        return 2
    if args.json:
        print(json.dumps(results, ensure_ascii=False, indent=2))
    return code


if __name__ == "__main__":
    sys.exit(main())
