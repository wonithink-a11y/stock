#!/usr/bin/env python3
"""실패한 systemd 유닛을 텔레그램 '장애 전용' 방으로 알린다.

    python3 scripts/notify-unit-failure.py rv20-futures-paper-order.service
    python3 scripts/notify-unit-failure.py <unit> --dry-run    # 보내지 않고 출력만
    python3 scripts/notify-unit-failure.py --selftest          # 네트워크 없음

deploy/unit-failure-notify@.service 가 `OnFailure=` 로 이걸 부른다.

왜 필요한가(2026-09-20 실측): VM systemd 타이머는 실패해도 아무 데도 안 뜬다 —
GitHub Actions 의 notify-failure.yml 은 Actions 만 본다. 실제로 rv20 선물이
2026-09-18 09:36 에 KIS 잔고조회 타임아웃으로 죽었는데(ExecMainStatus=1) 주말 내내
아무도 몰랐다. CLAUDE.md 의 "VM 실패는 Actions 에 안 나타난다" 그대로다.

**메시지는 2~3줄이다**(2026-09-20 사용자 지시). 폰 알림으로 읽히는 것이 목적이고,
자세한 로그는 VM 에 있다(journalctl -u <unit>). 그래서 저널은 넉넉히 읽되
**원인을 말해주는 한 줄만** 싣는다.

**보내는 방은 콘텐츠 방과 분리한다.** 뉴스·공시·장중 급등락·로그인 알림이 같은
대화로 오고 있어서, 거기에 장애까지 섞으면 급한 것이 묻힌다. chat id 는
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

# 상한은 배달 실패를 막는 안전장치로만 남긴다 - 텔레그램은 4096자를 넘기면 HTTP 400 으로
# **배달 자체가 실패**한다(2026-09-11 intraday 가 이걸 맞았고 '채널 미설정'으로 오진했다).
# 목표 길이는 그보다 훨씬 짧다.
TELEGRAM_LIMIT = 600
JOURNAL_LINES = 40          # 읽어오는 양. 메시지에 싣는 것은 이 중 한 줄이다
ERROR_LINE_MAX = 300

# systemd 가 스스로 찍는 줄 - 무엇이 깨졌는지 말해주지 않으므로 건너뛴다
_NOISE = ("Starting ", "Finished ", "Deactivated successfully", "Consumed ",
          "Main process exited", "Failed with result", "Failed to start",
          "Scheduled restart", "Triggering OnFailure", "Succeeded.")
_ERRORISH = ("Error", "error", "Exception", "Traceback", "timed out", "Timeout",
             "timeout", "FAILED", "Failed", "failed", "Errno", "오류", "실패")


def _run(cmd):
    try:
        return subprocess.run(cmd, capture_output=True, text=True, timeout=15,
                              errors="replace").stdout.strip()
    except Exception as e:                       # noqa: BLE001
        return f"(조회 실패: {type(e).__name__})"


def log_path(unit, run=_run):
    """유닛이 stdout 을 보내는 파일 경로. 없으면 빈 문자열.

    ★ `systemctl show -p StandardOutput` 은 **모드만** 준다(실측: 값이 그냥 "append").
    경로는 유닛 파일 본문에만 있으므로 `systemctl cat` 에서 읽는다. 드롭인이 덮어쓸 수
    있으니 마지막 매치를 쓴다. 유닛 이름이나 로그 경로를 하드코딩하지 않는다.
    """
    text = run(["systemctl", "cat", unit])
    found = ""
    for line in text.splitlines():
        line = line.strip()
        if not line.startswith("StandardOutput="):
            continue
        val = line.split("=", 1)[1]
        for prefix in ("append:", "file:", "truncate:"):
            if val.startswith(prefix):
                found = val[len(prefix):].strip()
    return found


def collect(unit, run=_run):
    """유닛의 실패 사실과 마지막 로그를 모은다. 파생값을 저장하지 않고 그때그때 읽는다(교훈75).

    ★ 저널만 보면 안 된다(2026-09-20 실측). 이 저장소의 유닛 14개가 전부
    `StandardOutput=append:<파일>` 로 stdout 을 파일에 보내므로, 저널에는 systemd
    자체 줄만 남고 **진짜 트레이스백은 그 파일에 있다**. rv20 로 시험했을 때 알림이
    "(로그 없음)" 으로 나온 것이 이 때문이었다. 그래서 StandardOutput 을 읽어
    파일이면 그쪽을 먼저 본다 - 유닛 이름을 하드코딩하지 않고 systemd 가 말해주는
    경로를 쓴다(규칙: 경로를 하드코딩하지 않는다).
    """
    show = run(["systemctl", "show", unit, "--no-pager",
                "-p", "Result", "-p", "ExecMainStatus", "-p", "ExecMainExitTimestamp",
                "-p", "Description"])
    fields = dict(line.split("=", 1) for line in show.splitlines() if "=" in line)
    path = log_path(unit, run)
    log = run(["tail", "-n", str(JOURNAL_LINES), path]) if path else ""
    if not log.strip():          # 파일이 없거나 비었으면 저널로 물러선다
        log = run(["journalctl", "-u", unit, "-n", str(JOURNAL_LINES), "--no-pager", "-o", "cat"])
    return fields, log


def error_line(log):
    """로그에서 **원인을 말해주는 한 줄**만 고른다.

    파이썬 트레이스백은 마지막 줄이 `타입: 메시지` 라 가장 정보가 많다. systemd 자체
    줄은 무엇이 깨졌는지 말해주지 않으므로 건너뛴다. 오류처럼 보이는 줄이 하나도
    없으면 마지막 실내용 줄을 쓴다 - 없는 것을 지어내지 않는다(교훈57).
    """
    lines = [x.strip() for x in (log or "").splitlines() if x.strip()]
    meaningful = [x for x in lines if not any(n in x for n in _NOISE)]
    for x in reversed(meaningful):
        if any(k in x for k in _ERRORISH):
            return x[:ERROR_LINE_MAX]
    return meaningful[-1][:ERROR_LINE_MAX] if meaningful else "(로그 없음)"


def _short_time(stamp):
    """'Fri 2026-09-18 09:36:15 KST' -> '09-18 09:36'. 못 읽으면 원문을 그대로 둔다."""
    for tok in (stamp or "").split():
        if tok.count("-") == 2 and len(tok) == 10:
            rest = (stamp or "").split(tok, 1)[1].split()
            hhmm = rest[0][:5] if rest else ""
            return f"{tok[5:]} {hhmm}".strip()
    return (stamp or "").strip() or "(시각 없음)"


def build_message(unit, fields, log):
    """폰에서 한눈에 읽히는 3줄. 자세한 건 VM 에 있다(journalctl -u <unit>)."""
    name = unit[:-len(".service")] if unit.endswith(".service") else unit
    return "\n".join([
        f"[실패] {name}",
        f"종료 {fields.get('ExecMainStatus', '?')} · {_short_time(fields.get('ExecMainExitTimestamp'))}",
        error_line(log),
    ])[:TELEGRAM_LIMIT]


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

    # ★ 실제 systemd 동작을 그대로 흉내 낸다(2026-09-20 VM 실측):
    #   `show -p StandardOutput` 은 **모드만**("append") 주고 경로는 안 준다.
    #   경로는 `systemctl cat` 의 유닛 파일 본문에만 있다.
    #   이 둘을 구분하지 않으면 테스트가 구성상 통과해 버려 버그를 못 잡는다(교훈72).
    fake_show = ("Description=RV20 futures paper order\nResult=exit-code\n"
                 "StandardOutput=append\n"
                 "ExecMainStatus=1\nExecMainExitTimestamp=Fri 2026-09-18 09:36:15 KST")
    fake_cat = ("# /etc/systemd/system/rv20-futures-paper-order.service\n"
                "[Service]\nExecStart=/usr/bin/true\n"
                "StandardOutput=append:/home/ubuntu/logs/rv20.log\n"
                "StandardError=append:/home/ubuntu/logs/rv20.log\n")
    real_log = (
        "Starting rv20-futures-paper-order.service - RV20 futures...\n"
        "=== 2) 계좌 잔고 조회 (읽기 전용) ===\n"
        "Traceback (most recent call last):\n"
        "  File \"/home/ubuntu/collector-venv/lib/python3.12/site-packages/requests/adapters.py\", line 713\n"
        "requests.exceptions.ReadTimeout: HTTPSConnectionPool(host='openapivts.koreainvestment.com', "
        "port=29443): Read timed out. (read timeout=20)\n"
        "rv20-futures-paper-order.service: Main process exited, code=exited, status=1/FAILURE\n"
        "rv20-futures-paper-order.service: Failed with result 'exit-code'.\n"
        "rv20-futures-paper-order.service: Consumed 4.655s CPU time.\n")

    def fake_run(cmd):
        if cmd[:2] == ["systemctl", "show"]:
            return fake_show
        if cmd[:2] == ["systemctl", "cat"]:
            return fake_cat
        if cmd[0] == "tail":
            return real_log if cmd[-1] == "/home/ubuntu/logs/rv20.log" else ""
        return "Starting x\nFinished x"          # 저널에는 systemd 잡음만 있다

    fields, log = collect("rv20-futures-paper-order.service", run=fake_run)
    ok(fields["ExecMainStatus"] == "1", "systemctl show 파싱")
    # ★ 유닛이 stdout 을 파일로 보내면 저널이 아니라 그 파일을 읽어야 한다
    ok("ReadTimeout" in log, "StandardOutput=append: 의 로그 파일을 읽는다")

    def journal_only(cmd):
        if cmd[0] == "systemctl":
            return "Result=exit-code\nExecMainStatus=1"      # StandardOutput 없음
        return real_log if cmd[0] == "journalctl" else ""

    _f2, l2 = collect("x.service", run=journal_only)
    ok("ReadTimeout" in l2, "파일 경로가 없으면 저널로 물러선다")

    msg = build_message("rv20-futures-paper-order.service", fields, log)
    lines = msg.splitlines()
    ok(len(lines) <= 3, f"3줄 이내 ({len(lines)}줄)")
    ok(len(msg) <= TELEGRAM_LIMIT, f"길이 상한 이내 ({len(msg)}자)")
    ok(lines[0].endswith("rv20-futures-paper-order"), "1줄: 유닛 이름(.service 없이)")
    ok("종료 1" in lines[1] and "09-18 09:36" in lines[1], f"2줄: 종료코드·시각 ({lines[1]})")
    ok("ReadTimeout" in lines[2], "3줄: systemd 잡음이 아니라 진짜 원인")
    ok("Main process exited" not in msg and "Consumed" not in msg, "systemd 잡음 제외")
    ok("Traceback" not in lines[2], "트레이스백 머리말이 아니라 마지막 예외 줄")

    # 오류처럼 보이는 줄이 없으면 마지막 실내용 줄
    ok(error_line("Starting x\n평소 출력 한 줄\nFinished x") == "평소 출력 한 줄",
       "오류 줄이 없으면 마지막 실내용 줄")
    ok(error_line("") == "(로그 없음)", "로그가 비면 지어내지 않는다")

    # 아주 긴 한 줄도 상한을 넘기지 않는다
    huge = build_message("x.service", fields, "Error: " + "L" * 50000)
    ok(len(huge) <= TELEGRAM_LIMIT, f"긴 오류 줄이 잘린다 ({len(huge)}자)")
    ok(len(huge.splitlines()) <= 3, "잘려도 3줄")

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
