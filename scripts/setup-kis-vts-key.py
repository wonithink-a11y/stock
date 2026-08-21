"""setup-kis-vts-key.py — KIS 모의투자(VTS) 앱키/앱시크릿/계좌번호를 .env에 넣는다.

setup-kis-key.py(라이브 KIS_APP_KEY/KIS_APP_SECRET)와 의도적으로 별개
스크립트다 — 실수로 라이브 키를 덮어쓰거나 두 값을 헷갈릴 여지를 코드
수준에서 없앤다. 변수명도 겹치지 않는다(KIS_VTS_*).

라이브용 스크립트의 클립보드 입력(붙여넣기 없이 복사만) 패턴을 그대로 쓴다 -
Windows의 getpass는 Ctrl+V를 제어문자로 읽어 붙여넣기가 깨진다(실측, 36자
키가 2자로 들어왔다). --from-file·docx 지원은 여기서는 뺐다(YAGNI) - 라이브
스크립트가 이미 있고, 이 세 값은 한 번에 클립보드로도 충분하다.

사용:
    python scripts/setup-kis-vts-key.py
"""

import os
import subprocess
import sys
from pathlib import Path

for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(errors="replace")
    except Exception:
        pass

REPO = Path(__file__).resolve().parent.parent
KEYS = ("KIS_VTS_APP_KEY", "KIS_VTS_APP_SECRET", "KIS_VTS_ACCOUNT_NO")
ENV_PATH = Path(os.environ.get("KIS_ENV_PATH") or (REPO / ".env")).expanduser()
SHOW_INPUT = ("--show" in sys.argv)


def say(msg=""):
    print(msg, flush=True)


def hold():
    if sys.stdin.isatty():
        try:
            input("  Enter를 누르면 창이 닫힙니다. ")
        except (EOFError, KeyboardInterrupt):
            pass


def fail(msg):
    say()
    say("  [중단] " + msg)
    say()
    hold()
    sys.exit(1)


def git_base():
    d = ENV_PATH.parent
    while not d.is_dir() and d.parent != d:
        d = d.parent
    return d


def git_ok(args):
    try:
        r = subprocess.run(["git"] + args, cwd=str(git_base()),
                            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        return r.returncode == 0
    except FileNotFoundError:
        return False


def read_clipboard():
    if os.name != "nt":
        return None
    try:
        r = subprocess.run(
            ["powershell", "-NoProfile", "-NonInteractive", "-Command", "Get-Clipboard -Raw"],
            capture_output=True, timeout=15,
        )
        if r.returncode != 0:
            return None
        return r.stdout.decode("utf-8", errors="replace")
    except Exception:
        return None


def clean(v):
    for junk in ("﻿", "​", "‌", "‍", " "):
        v = v.replace(junk, "")
    return v.strip().strip('"').strip("'").strip()


def read_secret(label, seen, allow_short=False):
    interactive = sys.stdin.isatty()
    use_clip = interactive and os.name == "nt" and not SHOW_INPUT
    while True:
        if use_clip:
            say("  " + label)
            say("    지금 그 값을 복사(Ctrl+C)한 뒤 여기서 Enter를 누릅니다.")
            try:
                input("    복사했으면 Enter: ")
            except (EOFError, KeyboardInterrupt):
                fail("입력이 취소됐다.")
            raw = read_clipboard()
            if raw is None:
                fail("클립보드를 읽지 못했다.")
        elif interactive:
            try:
                if SHOW_INPUT:
                    raw = input("  " + label + " (붙여넣고 Enter, 화면에 보입니다): ")
                else:
                    import getpass
                    raw = getpass.getpass("  " + label + " (붙여넣고 Enter, 화면에는 안 보입니다): ")
            except (EOFError, KeyboardInterrupt):
                fail("입력이 취소됐다.")
        else:
            say("  " + label + " [비대화형 stdin]")
            raw = sys.stdin.readline()
            if not raw:
                fail("입력이 취소됐다.")

        v = clean(raw)
        if not v:
            say("    [다시] 비어 있습니다.")
            continue
        if any(c.isspace() for c in v):
            say("    [다시] 값 안에 공백이나 줄바꿈이 있습니다. 한 줄씩 따로 넣습니다.")
            continue
        if v.split("=")[0] in KEYS:
            v = v.split("=", 1)[1].strip()
            if not v:
                say("    [다시] 값이 비어 있습니다.")
                continue
        half = len(v) // 2
        if len(v) % 2 == 0 and half >= 4 and v[:half] == v[half:]:
            say("    [다시] 같은 값이 두 번 붙었습니다(" + str(len(v)) + "자).")
            continue
        if v in seen:
            say("    [다시] 앞에서 받은 값과 같습니다. 클립보드가 아직 안 바뀌었습니다.")
            continue
        if not allow_short and len(v) < 8:
            say("    [주의] 값이 짧아 보입니다(" + str(len(v)) + "자). 그래도 계속 진행합니다.")

        say("    받았습니다. 길이 " + str(len(v)) + "자")
        return v


def mask(v):
    if len(v) <= 4:
        return "*" * len(v)
    return v[:4] + "*" * (len(v) - 4) + "  (" + str(len(v)) + "자)"


def main():
    say()
    say("  KIS 모의투자(VTS) 키 설정")
    say("  대상 파일: " + str(ENV_PATH))
    say("  주의: 이건 모의투자 전용 키입니다. 라이브 키(KIS_APP_KEY)와는")
    say("        완전히 별개로 KIS Developers에서 따로 발급받은 값이어야 합니다.")
    say()

    in_repo = git_ok(["rev-parse", "--is-inside-work-tree"])
    if in_repo:
        if not git_ok(["check-ignore", "-q", "--", str(ENV_PATH)]):
            fail(str(ENV_PATH) + " 가 .gitignore에 걸리지 않는다.\n"
                 "        이 저장소는 공개다. .gitignore를 먼저 고친다.")
    else:
        say("  [알림] git 저장소가 아닙니다. 파일 권한으로만 보호됩니다.")
        say()

    if os.name == "nt":
        say("  타이핑도 붙여넣기도 하지 않습니다. 복사만 하면 됩니다.")
    else:
        say("  터미널에 붙여넣고 Enter를 누릅니다. 화면에는 안 보입니다.")
    say()

    app_key = read_secret("1/3 모의투자 앱키(APP KEY)", set())
    app_secret = read_secret("2/3 모의투자 앱시크릿(APP SECRET)", {app_key})
    account_no = read_secret("3/3 모의투자 계좌번호 (예: 12345678-01)", {app_key, app_secret}, allow_short=True)

    if len({app_key, app_secret, account_no}) < 3:
        fail("입력한 세 값 중 서로 같은 것이 있다. 다시 확인한다.")

    lines = []
    if ENV_PATH.exists():
        say()
        say("  기존 .env를 발견했습니다. KIS_VTS_* 항목만 갱신하고 나머지는 보존합니다.")
        for line in ENV_PATH.read_text(encoding="utf-8").splitlines():
            name = line.split("=", 1)[0].strip()
            if name not in KEYS:
                lines.append(line)

    ENV_PATH.parent.mkdir(parents=True, exist_ok=True)
    lines.append("KIS_VTS_APP_KEY=" + app_key)
    lines.append("KIS_VTS_APP_SECRET=" + app_secret)
    lines.append("KIS_VTS_ACCOUNT_NO=" + account_no)

    with open(ENV_PATH, "w", encoding="utf-8", newline="\n") as f:
        f.write("\n".join(lines) + "\n")

    try:
        me = os.environ.get("USERNAME", "")
        if me and os.name == "nt":
            subprocess.run(["icacls", str(ENV_PATH), "/inheritance:r", "/grant:r", me + ":(R,W)"],
                            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except Exception:
        say("  [주의] 파일 권한 제한에 실패했습니다. 파일 자체는 정상입니다.")

    say()
    say("  완료")
    say("    KIS_VTS_APP_KEY      " + mask(app_key))
    say("    KIS_VTS_APP_SECRET   " + mask(app_secret))
    say("    KIS_VTS_ACCOUNT_NO   " + mask(account_no))
    say()

    if in_repo and git_ok(["ls-files", "--error-unmatch", str(ENV_PATH)]):
        say("  [경고] .env가 git에 추적되고 있습니다. 즉시 조치가 필요합니다.")
        say("         git rm --cached .env")
    elif in_repo:
        say("  .env는 git이 무시합니다. 커밋되지 않습니다.")

    say()
    hold()


if __name__ == "__main__":
    main()
