#!/usr/bin/env python3
"""실패한 systemd 유닛을 텔레그램 '장애 전용' 방으로 알린다.

    python3 scripts/notify-unit-failure.py rv20-futures-paper-order.service
    python3 scripts/notify-unit-failure.py <unit> --dry-run    # 보내지 않고 출력만
    python3 scripts/notify-unit-failure.py --selftest          # 네트워크 없음

deploy/unit-failure-notify@.service 가 `OnFailure=` 로 이걸 부른다.

왜 필요한가(2026-09-20 실측): VM systemd 타이머는 실패해도 아무 데도 안 뜬다 —
GitHub Actions 의 notify-failure.yml 은 Actions 만 본다. 실제로 rv20 선물이
2026-09-18 09:36 에 KIS 잔고조회 타임아웃으로 죽었는데(ExecMainStatus=1) 아무도
몰랐다. CLAUDE.md 가 스스로 적어둔 "VM 실패는 Actions 에 안 나타난다"가 그대로
발생한 것이다.

**보내는 방은 콘텐츠 방과 분리한다.** 뉴스·공시·장중 급등락·로그인 알림이 같은
대화로 오고 있어서, 거기에 장애까지 섞으면 급한 것이 묻힌다. 그래서 chat id 는
`TELEGRAM_ALERT_CHAT_ID` 를 쓰고, 없으면 **`TELEGRAM_CHAT_ID` 로 흘려보내지 않고
실패한다** — 조용히 콘텐츠 방으로 새는 것이 분리 실패의 가장 흔한 모양이다.
"""
import argparse
import os
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(errors="replace")
    except Exception:
        pass

# 텔레그램 한 메시지 상한은 4096자다. 넘기면 HTTP 400 으로 **배달 자체가 실패**한다
# (2026-09-11 intraday-alert 가 133줄 메시지로 이걸 맞았고, 그때는 실패를 '채널
# 미설정'으로 오진했다). 여유를 두고 자른다.
TELEGRAM_LIMIT = 3900
JOURNAL_LINES = 15


def _run(cmd):
    try:
        return subprocess.run(cmd, capture_output=True, text=True, timeout=15,
                              errors="replace").stdout.strip()
    except Exception as e:                       # noqa: BLE001
        return f"(조회 실패: {type(e).__name__})"


def collect(unit, run=_run):
    """유닛의 실패 사실과 마지막 로그를 모은다. 파생값을 저장하지 않고 그때그때 읽는다(교훈75)."""
    show = run(["systemctl", "show", unit, "--no-pager",
                "-p", "Result", "-p", "ExecMainStatus", "-p", "ExecMainExitTimestamp",
                "-p", "Description"])
    fields = dict(line.split("=", 1) for line in show.splitlines() if "=" in line)
    log = run(["journalctl", "-u", unit, "-n", str(JOURNAL_LINES), "--no-pager", "-o", "cat"])
    return fields, log


def build_message(unit, fields, log, host=None):
    host = host or os.uname().nodename if hasattr(os, "uname") else "?"
    head = [
        f"🔴 VM 유닛 실패 — {unit}",
        f"호스트: {host}",
        f"설명: {fields.get('Description', '(없음)')}",
        f"결과: {fields.get('Result', '?')} · 종료코드 {fields.get('ExecMainStatus', '?')}",
        f"시각: {fields.get('ExecMainExitTimestamp') or '(없음)'}",
        "",
        "마지막 로그:",
    ]
    body = "\n".join(head)
    room = TELEGRAM_LIMIT - len(body) - 20
    if room > 0 and log:
        # 뒤에서부터 남긴다 - 예외는 끝에 있다
        trimmed = log if len(log) <= room else "…(앞부분 생략)\n" + log[-room:]
        body += "\n" + trimmed
    return body[:TELEGRAM_LIMIT]


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("unit", nargs="?", help="실패한 유닛 이름(예: rv20-futures-paper-order.service)")
    ap.add_argument("--dry-run", action="store_true", help="보내지 않고 메시지만 출력")
    ap.add_argument("--selftest", action="store_true", help="네트워크 없이 확인")
    args = ap.parse_args(argv)

    if args.selftest:
        return _selftest()
    if not args.unit:
        ap.error("unit 이 필요하다")

    fields, log = collect(args.unit)
    text = build_message(args.unit, fields, log)

    if args.dry_run:
        print(text)
        return 0

    token = os.environ.get("TELEGRAM_BOT_TOKEN")
    chat_id = os.environ.get("TELEGRAM_ALERT_CHAT_ID")
    if not token or not chat_id:
        # 콘텐츠 방(TELEGRAM_CHAT_ID)으로 대신 보내지 않는다 - 분리가 무너진다.
        print("TELEGRAM_BOT_TOKEN 또는 TELEGRAM_ALERT_CHAT_ID 가 없다 "
              "(값은 출력하지 않는다). 장애 알림을 보내지 못했다.", file=sys.stderr)
        return 2

    from autotrader.notify import send_telegram    # 기존 구현 재사용(토큰 누출 방지 포함)
    send_telegram(token, chat_id, text)
    print(f"장애 알림 전송: {args.unit}")
    return 0


def _selftest():
    failed = 0

    def ok(cond, label):
        nonlocal failed
        if cond:
            print(f"  ok   {label}")
        else:
            failed += 1
            print(f"  FAIL {label}")

    fake_show = ("Description=RV20 futures paper order\nResult=exit-code\n"
                 "ExecMainStatus=1\nExecMainExitTimestamp=Fri 2026-09-18 09:36:15 KST")

    def fake_run(cmd):
        return fake_show if cmd[0] == "systemctl" else "Traceback...\nReadTimeout"

    fields, log = collect("x.service", run=fake_run)
    ok(fields["ExecMainStatus"] == "1", "systemctl show 파싱")
    ok("ReadTimeout" in log, "journal 수집")

    msg = build_message("x.service", fields, log, host="stock")
    ok("🔴" in msg and "x.service" in msg, "헤더에 유닛 이름")
    ok("exit-code" in msg and "ReadTimeout" in msg, "결과와 로그가 함께 들어간다")

    # ★ 4096 초과는 배달 자체를 실패시킨다 - 반드시 잘려야 한다
    huge = build_message("x.service", fields, "L" * 50000, host="stock")
    ok(len(huge) <= TELEGRAM_LIMIT, f"긴 로그가 잘린다 ({len(huge)}자)")
    ok("x.service" in huge and "exit-code" in huge, "잘려도 헤더는 남는다")
    ok("…(앞부분 생략)" in huge, "생략 사실을 밝힌다")

    # 분리 보장: ALERT chat id 가 없으면 보내지 않고 실패한다
    saved = {k: os.environ.pop(k, None) for k in ("TELEGRAM_ALERT_CHAT_ID", "TELEGRAM_BOT_TOKEN")}
    os.environ["TELEGRAM_BOT_TOKEN"] = "dummy"
    try:
        rc = main(["x.service"])
    finally:
        for k, v in saved.items():
            os.environ.pop(k, None)
            if v is not None:
                os.environ[k] = v
    ok(rc == 2, "ALERT chat id 없으면 콘텐츠 방으로 안 보내고 실패(rc=2)")

    print(f"\n{'FAILED' if failed else 'PASSED'} - {failed} failure(s)")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
