#!/usr/bin/env python3
"""VM 상태 스냅샷 — 폰(클라우드) 세션이 ssh 없이 VM 을 점검하게 한다(2026-11-01).

왜: 클라우드 세션은 HTTPS(443)만 나간다 — ssh(22)는 설정으로도 안 열린다(실측 github.com:22·VM:22 둘 다 막힘).
그래서 VM 이 5분마다 상태를 JSON 한 장으로 써 두고, 이미 있는 /research-data/ 통로(X-Data-Key)로 읽는다.
명령을 받아 실행하는 경로는 만들지 않는다 — VM 이 스스로 정해진 것만 쓴다(쓰기·주문 없음).

  python3 scripts/vm-status-snapshot.py              # VM: /srv/stock-data/bundles/_status/vm-status.json 갱신
  python3 scripts/vm-status-snapshot.py --stdout     # 쓰지 않고 출력만
  python3 scripts/vm-status-snapshot.py --selftest   # 네트워크·systemd 없이 가림·파싱 확인
  python scripts/research-data.py status [유닛]       # 클라우드·PC: 읽기

담는 것: 실패 유닛 · 프로젝트 타이머 마지막/다음 실행 · 서비스 결과 · 로그 마지막 줄(가림 처리) · ~/collector 커밋 ·
디스크·메모리 · 상태 파일 건수·수정 시각(값은 열지 않는다 — orderflow 는 2027-04 까지 건수만).
빼는 것: autotrader·실계좌 잔고 유닛의 로그 본문(금액은 지문으로만 보는 규칙 — 상태만 낸다).
"""
import json
import os
import re
import shutil
import socket
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

KST = ZoneInfo("Asia/Seoul")

HOME = Path.home()
REPO = Path(__file__).resolve().parent.parent
OUT = Path(os.environ.get("VM_STATUS_PATH") or "/srv/stock-data/bundles/_status/vm-status.json")
LOGS = HOME / "collector-venv" / "logs"
EXTRA_UNITS = ["kis-minute-history-api.service", "autotrader-web.service", "nginx.service"]
# 로그 본문을 내지 않는 유닛·로그 파일(이름 앞부분) — 실계좌 잔고·주문 금액
PRIVATE = ("autotrader", "kis-portfolio-holdings", "crypto-real-holdings")
LOG_LINES = 15
STATE_FILES = {   # 이름 → 경로. 줄 수(jsonl)·크기·수정 시각만
    "intraday-kr-snapshot": HOME / "collector-venv/intraday/kr-snapshot.json",
    "cbprem-trades": HOME / "collector-venv/cbprem-paper/trades.jsonl",
    "cbprem-runs": HOME / "collector-venv/cbprem-paper/runs.jsonl",
    "upbit-events": HOME / "collector-venv/upbit-events/events.jsonl",
    "yt-digest": HOME / "collector-venv/yt/digest.json",
    "pins": HOME / "collector-venv/pins/pins.json",
    "rv20-log": LOGS / "rv20-futures-paper-order.log",
}
COUNT_DIRS = {"orderflow-raw": HOME / "orderflow-raw", "minute-raw": HOME / "minute-raw"}

_REDACT = [
    (re.compile(r"\b\d{8,10}:[A-Za-z0-9_-]{30,}\b"), "***"),                                   # 텔레그램 봇 토큰
    (re.compile(r"(?i)\b(app_?key|app_?secret|secret|token|password|passwd|authorization|api[_-]?key|x-[a-z-]*key)"
                r"(\"?\s*[:=]\s*\"?|\s+)(bearer\s+)?[^\s\",}]+"), r"\1\2***"),
    (re.compile(r"[A-Za-z0-9+_-]{40,}={0,2}"), "***"),   # 긴 키 모양 문자열('/' 는 빼야 긴 경로가 안 가려진다)
]


def redact(s):
    for rx, rep in _REDACT:
        s = rx.sub(rep, s)
    return s


def run(cmd, timeout=20):
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        return r.stdout, (r.stderr.strip()[:200] or None) if r.returncode else None
    except Exception as e:  # noqa: BLE001 — 점검기는 죽지 않는다, 오류를 적는다
        return "", str(e)[:200]


def parse_show(text, names, props):
    """`systemctl show a b -p X,Y` 출력(빈 줄로 나뉜 블록, 이름 순서대로) → {이름: {X: 값}}."""
    blocks, cur = [], {}
    for line in text.splitlines():
        if not line.strip():
            if cur:
                blocks.append(cur)
                cur = {}
            continue
        k, _, v = line.partition("=")
        if k in props:
            cur[k] = v
    if cur:
        blocks.append(cur)
    return dict(zip(names, blocks)) if len(blocks) == len(names) else {}


def project_units():
    """저장소 deploy/ 의 유닛 이름(템플릿은 실제 인스턴스로) + 웹·nginx."""
    names = sorted(p.name for p in (REPO / "deploy").glob("*.timer") if "@" not in p.name)
    for p in (REPO / "deploy").glob("*@.timer"):
        out, _ = run(["systemctl", "list-units", "--all", "--plain", "--no-legend", p.name.replace("@.", "@*.")])
        names += [line.split()[0] for line in out.splitlines() if line.strip()]
    timers = names
    services = [t[:-6] + ".service" for t in timers] + EXTRA_UNITS
    return timers, services


def private(name):
    return name.startswith(PRIVATE)


def tail(path, n):
    try:
        with open(path, "rb") as f:
            f.seek(0, 2)
            f.seek(max(0, f.tell() - 64 * 1024))
            lines = f.read().decode("utf-8", "replace").splitlines()[-n:]
        return [redact(x)[:300] for x in lines]
    except OSError as e:
        return [f"(읽기 실패: {e.__class__.__name__})"]


def file_info(p):
    try:
        st = p.stat()
    except OSError:
        return None
    info = {"bytes": st.st_size, "mtime": datetime.fromtimestamp(st.st_mtime, KST).strftime("%Y-%m-%d %H:%M")}
    if p.suffix == ".jsonl":
        with open(p, "rb") as f:
            info["lines"] = sum(1 for _ in f)
    return info


def snapshot():
    t0 = time.time()
    timers, services = project_units()
    tp = ["ActiveState", "UnitFileState", "LoadState", "LastTriggerUSec", "NextElapseUSecRealtime", "Result"]
    sp = ["ActiveState", "SubState", "Result", "ExecMainStatus", "ExecMainExitTimestamp", "UnitFileState", "LoadState"]
    tout, terr = run(["systemctl", "show", *timers, "-p", ",".join(tp)])
    sout, serr = run(["systemctl", "show", *services, "-p", ",".join(sp)])
    failed, ferr = run(["systemctl", "--failed", "--no-legend", "--plain"])
    git, _ = run(["git", "-C", str(HOME / "collector"), "log", "-1", "--format=%h %cd %s", "--date=format:%m-%d %H:%M"])
    gst, _ = run(["git", "-C", str(HOME / "collector"), "status", "-sb"])
    journal = {}
    for s in services:
        if private(s):
            continue
        out, err = run(["journalctl", "-u", s, "-n", "5", "--no-pager", "-o", "short-iso"])
        journal[s] = [redact(x)[:300] for x in out.splitlines()] if not err else [f"(journal 읽기 실패: {err})"]
    logs = {p.stem: tail(p, LOG_LINES) for p in sorted(LOGS.glob("*.log")) if not private(p.stem)} if LOGS.exists() else {}
    du = shutil.disk_usage("/")
    mem = {}
    try:
        for line in Path("/proc/meminfo").read_text().splitlines():
            k, v = line.split(":")
            if k in ("MemTotal", "MemAvailable"):
                mem[k] = int(v.split()[0]) // 1024
        load = Path("/proc/loadavg").read_text().split()[:3]
    except OSError:
        load = None
    return {
        "host": socket.gethostname(),
        "atKST": datetime.now(KST).strftime("%Y-%m-%d %H:%M:%S"),
        "failed": [line.split()[0] for line in failed.splitlines() if line.strip()],
        "errors": {k: v for k, v in {"timers": terr, "services": serr, "failed": ferr}.items() if v},
        "timers": parse_show(tout, timers, tp),
        "services": parse_show(sout, services, sp),
        "git": {"head": git.strip(), "status": gst.splitlines()[:3]},
        "disk": {"totalGB": round(du.total / 1e9, 1), "usedGB": round(du.used / 1e9, 1), "freeGB": round(du.free / 1e9, 1)},
        "memMB": mem, "load": load,
        "files": {k: file_info(p) for k, p in STATE_FILES.items()},
        "dirCounts": {k: (len(list(p.iterdir())) if p.is_dir() else None) for k, p in COUNT_DIRS.items()},
        "journal": journal, "logs": logs,
        "private": "autotrader·실계좌 잔고 유닛은 상태만(로그 본문 없음)",
        "tookSec": round(time.time() - t0, 1),
    }


def selftest():
    fails = []

    def ok(c, m):
        if not c:
            fails.append(m)
    ok(redact("token=abc123 done") == "token=*** done", redact("token=abc123 done"))
    ok("***" in redact("bot 1234567890:AAH" + "x" * 33) and "AAH" not in redact("bot 1234567890:AAH" + "x" * 33), "telegram")
    ok(redact('{"appsecret": "Zz9"}') == '{"appsecret": "***"}', redact('{"appsecret": "Zz9"}'))
    ok(redact("Authorization: Bearer eyJabc") == "Authorization: ***", redact("Authorization: Bearer eyJabc"))
    ok(redact("X-Data-Key: 0f0f") == "X-Data-Key: ***", redact("X-Data-Key: 0f0f"))
    ok(redact("주문번호 0000001627 percentile 0.353 → 1.0x") == "주문번호 0000001627 percentile 0.353 → 1.0x", "평문 보존")
    ok("***" in redact("k " + "a1B2" * 12), "긴 키")
    ok(redact("/home/ubuntu/collector-venv/intraday/kr-snapshot.json") == "/home/ubuntu/collector-venv/intraday/kr-snapshot.json", "경로 보존")
    show = "ActiveState=active\nResult=success\n\nActiveState=failed\nResult=exit-code\n"
    ok(parse_show(show, ["a.timer", "b.timer"], {"ActiveState", "Result"})["b.timer"]["Result"] == "exit-code", "parse_show")
    ok(parse_show(show, ["a.timer"], {"ActiveState"}) == {}, "블록 수가 다르면 이름을 붙이지 않는다")
    ok(private("autotrader-web.service") and private("crypto-real-holdings@upbit.service") and not private("rv20-futures-paper-order"), "private")
    for f in fails:
        print("FAIL", f)
    print(f"selftest {'OK' if not fails else 'FAIL'} ({len(fails)} 실패)")
    return 1 if fails else 0


def main(argv):
    if "--selftest" in argv:
        return selftest()
    snap = snapshot()
    text = json.dumps(snap, ensure_ascii=False, indent=1)
    if "--stdout" in argv:
        print(text)
        return 0
    OUT.parent.mkdir(parents=True, exist_ok=True)
    tmp = OUT.with_suffix(".tmp")
    tmp.write_text(text, encoding="utf-8")
    tmp.replace(OUT)          # 읽는 쪽이 반쪽 파일을 받지 않게
    print(f"{OUT} {len(text) // 1024}KB · failed {len(snap['failed'])} · {snap['tookSec']}s")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
