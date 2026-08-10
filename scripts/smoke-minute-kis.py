"""smoke-minute-kis.py — Broad 전 마지막 관문. 한 줄로 GO/NO-GO를 판정한다.

기존 Collector를 고치지 않는다. transport를 감싸고 임시 경로를 주입할 뿐이다.

단계를 명확히 가른다
    REAL    실제 KIS 호출 10종목 1일치. 여기서만 네트워크가 나간다
    MOCK    fail-soft·resume. 가짜 transport로만 한다 -
            실패 주입을 실제 호출에 하면 KIS에 부하를 주고 재현도 안 된다
    MEM     수집 중 VmHWM
    MON     기존 stock-monitor 생존 (죽거나 OOM victim이면 NO-GO)

산출물은 전부 임시 영역에 쓰고 끝나면 지운다. 운영 데이터를 건드리지 않는다.
키는 어떤 경로로도 출력하지 않는다.
fail-soft: 어느 단계가 죽어도 나머지를 돌리고 그 사실을 판정에 남긴다.

사용:
    python3 scripts/smoke-minute-kis.py
    python3 scripts/smoke-minute-kis.py --date 2026-08-03 --json
    python3 scripts/smoke-minute-kis.py --selftest     # 네트워크 없이 자체 검증
"""

import argparse
import importlib.util
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(errors="replace")
    except Exception:
        pass

REPO = Path(__file__).resolve().parent.parent
KST = timezone(timedelta(hours=9))
DEFAULT_TICKERS = ["005930", "000660", "035420", "051910", "005380",
                   "000270", "068270", "105560", "055550", "012330"]


def now():
    return datetime.now(KST).strftime("%Y-%m-%dT%H:%M:%S+09:00")


def safe(fn, default=None):
    try:
        return fn()
    except Exception as e:
        return default if default is not None else {"_error": type(e).__name__}


def load_collector():
    spec = importlib.util.spec_from_file_location(
        "collect_minute_kis", REPO / "scripts" / "collect-minute-kis.py")
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


def vmhwm_mb():
    try:
        for line in open("/proc/self/status"):
            if line.startswith("VmHWM:"):
                return round(int(line.split()[1]) / 1024.0, 1)
    except Exception:
        pass
    try:
        import resource
        return round(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
                     / 1024.0, 1)
    except Exception:
        return None


def mem_available_mb():
    try:
        for line in open("/proc/meminfo"):
            if line.startswith("MemAvailable:"):
                return round(int(line.split()[1]) / 1024.0, 1)
    except Exception:
        return None


def ps_snapshot(pattern):
    """이름으로 프로세스를 찾는다. psutil을 요구하지 않는다."""
    def _():
        out = subprocess.run(["ps", "-eo", "pid,rss,comm,args"],
                             capture_output=True, text=True, timeout=10).stdout
        hits = []
        for line in out.splitlines()[1:]:
            if pattern.lower() in line.lower() and "smoke-minute" not in line:
                p = line.split(None, 3)
                if len(p) >= 3:
                    hits.append({"pid": p[0], "rssMB": round(int(p[1]) / 1024, 1),
                                 "comm": p[2]})
        return hits
    return safe(_, [])


def oom_events():
    """최근 OOM kill 흔적. 권한이 없으면 조용히 비운다."""
    def _():
        for cmd in (["dmesg", "-T"], ["journalctl", "-k", "-n", "500"]):
            r = subprocess.run(cmd, capture_output=True, text=True, timeout=15)
            if r.returncode == 0 and r.stdout:
                return [l[-160:] for l in r.stdout.splitlines()
                        if "Out of memory" in l or "oom-kill" in l.lower()][-5:]
        return []
    return safe(_, [])


# ---------------------------------------------------------------- transport

class CountingTransport:
    """실물을 감싸 응답 코드를 센다. Collector는 이것을 모른다."""

    def __init__(self, inner):
        self.inner = inner
        self.calls = 0
        self.msg_codes = {}
        self.http = {}

    def fetch(self, ticker, sent_date, hour, pol):
        self.calls += 1
        r = self.inner.fetch(ticker, sent_date, hour, pol)
        h = str(r.get("http") or ("transport" if r.get("transportError")
                                  else "?"))
        self.http[h] = self.http.get(h, 0) + 1
        mc = str(((r.get("body") or {}).get("msg_cd")) or "")
        if mc:
            self.msg_codes[mc] = self.msg_codes.get(mc, 0) + 1
        return r


class MockTransport:
    """MOCK 단계 전용. 실패 주입은 여기서만 한다."""

    def __init__(self, ok_tickers, fail_tickers, date, rows=30):
        self.ok = set(ok_tickers)
        self.fail = set(fail_tickers)
        self.date = date
        self.rows = rows
        self.seen = []

    def fetch(self, ticker, sent_date, hour, pol):
        self.seen.append(ticker)
        if ticker in self.fail:
            return {"transportError": "InjectedFailure"}
        grid = ["%02d%02d00" % divmod(m, 60)
                for m in range(9 * 60, 15 * 60 + 20)] + ["153000"]
        use = [h for h in grid[-self.rows:] if h <= hour][-120:]
        if not use:
            return {"http": 200, "body": {"rt_cd": "0", "msg_cd": "MCA00000",
                                          "output2": []}}
        b = 10000
        return {"http": 200, "body": {
            "rt_cd": "0", "msg_cd": "MCA00000", "output1": {},
            "output2": [{"stck_bsop_date": sent_date, "stck_cntg_hour": h,
                         "stck_oprc": str(b), "stck_hgpr": str(b + 10),
                         "stck_lwpr": str(b - 10), "stck_prpr": str(b + 3),
                         "cntg_vol": "10"} for h in reversed(use)]}}


# ---------------------------------------------------------------- 판정

class Judge:
    def __init__(self):
        self.checks = []

    def add(self, key, name, passed, detail=None, blocking=True):
        self.checks.append({"key": key, "항목": name,
                            "통과": bool(passed), "차단": blocking,
                            "실측": detail})

    def go(self):
        return all(c["통과"] for c in self.checks if c["차단"])


# ---------------------------------------------------------------- 단계

def phase_real(M, J, args, tmp, report):
    """실제 KIS 10종목. 네트워크는 여기서만 나간다."""
    env = {}
    p = Path(os.environ.get("KIS_ENV_PATH") or (REPO / ".env")).expanduser()
    if p.exists():
        for line in p.read_text(encoding="utf-8").splitlines():
            k, _, v = line.partition("=")
            env[k.strip()] = v.strip()
    key = os.environ.get("KIS_APP_KEY") or env.get("KIS_APP_KEY")
    sec = os.environ.get("KIS_APP_SECRET") or env.get("KIS_APP_SECRET")
    cache = Path(os.environ.get("KIS_TOKEN_CACHE")
                 or (REPO / ".token_cache_kis.json"))

    if not key or not sec:
        J.add("kis_auth", "KIS 인증", False,
              {"why": "앱키가 없다. setup-kis-key.py를 먼저 돌린다"})
        return None
    if not cache.exists():
        J.add("kis_auth", "KIS 인증", False,
              {"why": "토큰 캐시가 없다: " + str(cache)})
        return None
    tok = safe(lambda: json.loads(cache.read_text(encoding="utf-8"))["accessToken"])
    if not isinstance(tok, str):
        J.add("kis_auth", "KIS 인증", False, {"why": "토큰 캐시를 읽지 못했다"})
        return None
    J.add("kis_auth", "KIS 인증", True, {"tokenLen": len(tok)})

    pol = M.load_policy()
    tr = CountingTransport(M.KisTransport(key, sec, tok))
    t0 = time.time()
    res = safe(lambda: M.run_day(
        tr, args.tickers, args.date, pol, M.load_context(),
        tmp / "raw", tmp / "state",
        run={"host": "smoke"}, keep_rows=False))
    elapsed = round(time.time() - t0, 1)

    if not isinstance(res, dict) or "manifest" not in res:
        J.add("real_run", "실데이터 10종목 수집", False,
              {"why": "수집이 예외로 끝났다", "detail": str(res)[:120]})
        return None

    man = res["manifest"]
    report["real"] = {
        "date": man["date"], "symbols": man["symbols"], "rows": man["rows"],
        "parts": len(man.get("parts") or []), "elapsedSec": elapsed,
        "calls": tr.calls, "httpCodes": tr.http, "msgCodes": tr.msg_codes,
        "gapReasons": man.get("gapReasons"), "unresolved": man.get("unresolved"),
        "acceptancePassed": man.get("acceptancePassed"),
        "writerError": man.get("writerError"),
    }

    J.add("real_run", "실데이터 10종목 수집", man["symbols"] == len(args.tickers),
          {"symbols": man["symbols"], "expected": len(args.tickers)})
    J.add("acceptance", "인수 조건 통과", bool(man.get("acceptancePassed")),
          {"failed": [c["항목"] for c in man.get("acceptance", [])
                      if not c["통과"]]})
    J.add("writer", "parquet writer 오류 없음", not man.get("writerError"),
          {"writerError": man.get("writerError")})

    # manifest ↔ parquet 실측 대조
    def verify_parquet():
        raw = man.get("rawPath")
        if not raw:
            return {"why": "rawPath 없음"}
        import pyarrow.parquet as pq
        t = pq.read_table(Path(raw))
        part_sum = sum(p["rows"] for p in man["parts"])
        recomputed = M.combined_sha(
            [{"name": p["name"],
              "sha256": M.sha256_bytes((Path(raw) / p["name"]).read_bytes())}
             for p in man["parts"]])
        return {"parquetRows": t.num_rows, "manifestRows": man["rows"],
                "partSum": part_sum, "schema": t.column_names,
                "shaMatch": recomputed == man["sha256"]}

    v = safe(verify_parquet, {})
    report["parquet"] = v
    J.add("rows_match", "manifest ↔ parquet 행 수 일치",
          v.get("parquetRows") == man["rows"] == v.get("partSum"), v)
    J.add("hash_match", "결합 sha256 재계산 일치", v.get("shaMatch") is True, v)
    J.add("schema_match", "스키마가 계약 순서 그대로",
          v.get("schema") == M.SCHEMA, {"got": v.get("schema")})

    # EGW00201 처리 — 발생 여부가 아니라 '오분류가 없는가'가 기준이다
    egw = tr.msg_codes.get("EGW00201", 0)
    misclass = [{"ticker": o.ticker, "gapReason": o.gap_reason,
                 "failureClass": o.failure_class}
                for o in res["outcomes"]
                if o.status == "GAP"
                and o.failure_class in ("RATE_LIMIT", "NETWORK", "HTTP_ERROR")]
    report["egw00201"] = {"count": egw, "misclassified": misclass}
    J.add("egw_handling",
          "EGW00201 오분류 없음 (일시적 장애를 GAP으로 굳히지 않는다)",
          not misclass, {"egw00201": egw, "misclassified": misclass[:3]})

    return res


def phase_mock(M, J, args, tmp, report):
    """fail-soft · resume. 실패 주입은 여기서만 한다."""
    pol = M.load_policy()
    pol["retry"]["maxAttempts"] = 2
    pol["retry"]["backoffBaseSeconds"] = 0.0
    ctx = {"tradingDays": {args.date}, "listedAt": {}, "delistedAt": {}}
    tick = ["M%05d" % i for i in range(10)]
    bad = {tick[3]}

    # fail-soft: 한 종목이 죽어도 나머지가 끝나야 한다
    mt = MockTransport(set(tick) - bad, bad, M.compact(args.date))
    r1 = safe(lambda: M.run_day(mt, tick, args.date, pol, ctx,
                                tmp / "mraw", tmp / "mstate",
                                sleeper=lambda s: None, keep_rows=False))
    if not isinstance(r1, dict) or "outcomes" not in r1:
        J.add("failsoft", "fail-soft", False, {"why": "예외로 끝났다"})
        return
    ok = [o for o in r1["outcomes"] if o.status == "OK"]
    un = [o for o in r1["outcomes"] if o.status == "UNRESOLVED"]
    report["mock"] = {"ok": len(ok), "unresolved": len(un),
                      "unresolvedTickers": [o.ticker for o in un]}
    J.add("failsoft", "fail-soft (1종목 실패가 나머지를 멈추지 않는다)",
          len(ok) == 9 and len(un) == 1 and un[0].ticker == tick[3],
          {"ok": len(ok), "unresolved": [o.ticker for o in un]})
    J.add("failsoft_class", "실패가 UNRESOLVED로 남는다 (GAP 아님)",
          bool(un) and un[0].gap_reason is None
          and un[0].failure_class == "NETWORK",
          {"gapReason": un[0].gap_reason if un else None,
           "failureClass": un[0].failure_class if un else None})

    # resume: 2차 실행이 완료 종목을 다시 부르지 않아야 한다
    mt2 = MockTransport(set(tick), set(), M.compact(args.date))
    r2 = safe(lambda: M.run_day(mt2, tick, args.date, pol, ctx,
                                tmp / "mraw", tmp / "mstate", resume=True,
                                sleeper=lambda s: None, keep_rows=False))
    recalled = sorted({t for t in mt2.seen if t in {o.ticker for o in ok}})
    report["resume"] = {"recalled": recalled,
                        "calledTickers": sorted(set(mt2.seen))}
    J.add("resume", "resume (완료 종목 재호출 0)", not recalled,
          {"recalled": recalled[:5]})
    J.add("resume_progress", "resume가 남은 종목은 처리한다",
          isinstance(r2, dict) and tick[3] in set(mt2.seen),
          {"called": sorted(set(mt2.seen))[:5]})


def phase_mem(J, args, report, peak):
    avail = mem_available_mb()
    limit = args.mem_limit or (round(avail * 0.5, 1) if avail else None)
    report["memory"] = {"peakVmHWM_MB": peak, "memAvailableMB": avail,
                        "limitMB": limit}
    if peak is None or limit is None:
        J.add("memory", "메모리 피크", True,
              {"why": "리눅스가 아니라 측정 불가 — VM에서 다시 잰다",
               "peak": peak, "limit": limit}, blocking=False)
    else:
        J.add("memory", "피크 VmHWM ≤ 가용 메모리의 50%", peak <= limit,
              {"peakMB": peak, "limitMB": limit, "availableMB": avail})


def phase_monitor(J, args, report, before):
    after = ps_snapshot(args.monitor_pattern)
    ooms = oom_events()
    before_pids = {p["pid"] for p in before}
    after_pids = {p["pid"] for p in after}
    survived = before_pids and before_pids <= after_pids
    report["monitor"] = {
        "pattern": args.monitor_pattern,
        "before": before, "after": after,
        "died": sorted(before_pids - after_pids),
        "oomEvents": ooms,
    }
    if not before:
        J.add("monitor_alive", "기존 모니터 생존", True,
              {"why": "패턴에 맞는 프로세스를 찾지 못했다 — 판정하지 않는다",
               "pattern": args.monitor_pattern}, blocking=False)
    else:
        J.add("monitor_alive", "기존 모니터가 살아 있다", bool(survived),
              {"before": len(before), "after": len(after),
               "died": sorted(before_pids - after_pids)})
    J.add("no_oom", "OOM kill 없음", not ooms, {"events": ooms[:2]})


# ---------------------------------------------------------------- 실행

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--date")
    ap.add_argument("--tickers")
    ap.add_argument("--mem-limit", type=float,
                    help="MB. 생략하면 MemAvailable의 50%%")
    ap.add_argument("--monitor-pattern", default="stock-monitor")
    ap.add_argument("--keep", action="store_true", help="임시 산출물 보존")
    ap.add_argument("--skip-real", action="store_true")
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--selftest", action="store_true")
    args = ap.parse_args()

    M = load_collector()

    if not args.date:
        cal = REPO / "data" / "backfill" / "calendar.json"
        td = safe(lambda: json.loads(cal.read_text(encoding="utf-8"))
                  ["tradingDays"], [])
        args.date = td[-1] if td else datetime.now(KST).strftime("%Y-%m-%d")
    args.tickers = ([t.strip() for t in args.tickers.split(",") if t.strip()]
                    if args.tickers else DEFAULT_TICKERS)

    if args.selftest:
        return selftest(M, args)

    J = Judge()
    report = {"schemaVersion": "SMOKE-1.0", "startedAt": now(),
              "date": args.date, "tickerCount": len(args.tickers)}
    tmp = Path(tempfile.mkdtemp(prefix="smoke-minute-"))
    before = ps_snapshot(args.monitor_pattern)

    try:
        if not args.skip_real:
            phase_real(M, J, args, tmp, report)
        else:
            J.add("kis_auth", "KIS 인증", True, {"skipped": True},
                  blocking=False)
        phase_mock(M, J, args, tmp, report)
        phase_mem(J, args, report, vmhwm_mb())
        phase_monitor(J, args, report, before)
    finally:
        if args.keep:
            report["tmp"] = str(tmp)
        else:
            shutil.rmtree(tmp, ignore_errors=True)

    report["checks"] = J.checks
    report["decision"] = "GO" if J.go() else "NO-GO"
    report["finishedAt"] = now()

    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=2))
    else:
        emit(report)
    return 0 if J.go() else 1


def emit(r):
    print()
    print("  분봉 수집 smoke  " + r["startedAt"])
    print("  일자 " + str(r["date"]) + " · 종목 " + str(r["tickerCount"]))
    print()
    for c in r["checks"]:
        d = c["실측"] or {}
        skipped = isinstance(d, dict) and ("why" in d or d.get("skipped"))
        # '측정하지 못해 통과'를 그냥 PASS로 보여주면 거짓 안심이 된다.
        tag = ("SKIP" if (c["통과"] and skipped)
               else "PASS" if c["통과"]
               else "FAIL" if c["차단"] else "WARN")
        print("  " + tag.ljust(5) + c["항목"])
        if (not c["통과"] or skipped) and c["실측"] is not None:
            print("        " + json.dumps(c["실측"], ensure_ascii=False)[:200])
    print()
    for k in ("real", "parquet", "memory", "mock", "resume", "egw00201"):
        if k in r:
            print("  " + k.ljust(10) +
                  json.dumps(r[k], ensure_ascii=False)[:180])
    print()
    print("  판정  " + r["decision"])
    print()


def selftest(M, args):
    """자체 인수 조건. 네트워크 없이 판정 로직이 실제로 잡는지 본다."""
    P, F = [], []

    def ck(name, cond, detail=""):
        (P if cond else F).append(name)
        print(("  PASS  " if cond else "  FAIL  ") + name +
              (("  " + str(detail)) if (detail and not cond) else ""))

    tmp = Path(tempfile.mkdtemp(prefix="smoke-self-"))
    try:
        J = Judge()
        rep = {}
        args.date = "2026-08-03"
        phase_mock(M, J, args, tmp, rep)
        keys = {c["key"]: c for c in J.checks}
        ck("fail-soft 판정이 통과로 나온다", keys["failsoft"]["통과"],
           keys["failsoft"]["실측"])
        ck("실패가 GAP이 아니라 UNRESOLVED로 분류된다",
           keys["failsoft_class"]["통과"], keys["failsoft_class"]["실측"])
        ck("resume 판정이 통과로 나온다", keys["resume"]["통과"],
           keys["resume"]["실측"])
        ck("resume가 남은 종목을 처리한다", keys["resume_progress"]["통과"])

        # 판정기가 실제로 실패를 잡는가 - 통과만 보면 게이트가 죽어도 모른다
        J2 = Judge()
        J2.add("x", "차단 항목 실패", False, None, blocking=True)
        ck("차단 항목이 실패하면 NO-GO", not J2.go())
        J3 = Judge()
        J3.add("y", "비차단 항목 실패", False, None, blocking=False)
        ck("비차단 항목 실패는 GO를 막지 않는다", J3.go())

        ck("임시 경로를 쓴다 (운영 산출물 미오염)",
           str(tmp) not in str(REPO / "data"))
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    print()
    print("  통과 %d · 실패 %d" % (len(P), len(F)))
    return 1 if F else 0


if __name__ == "__main__":
    sys.exit(main())
