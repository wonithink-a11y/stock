"""setup-kis-vts-key.py — KIS 모의투자(VTS) 앱키/앱시크릿/계좌번호를 .env에 넣는다.

setup-kis-key.py(라이브 KIS_APP_KEY/KIS_APP_SECRET)와 의도적으로 별개
스크립트다 — 실수로 라이브 키를 덮어쓰거나 두 값을 헷갈릴 여지를 코드
수준에서 없앤다. 변수명도 겹치지 않는다(KIS_VTS_*).

라이브용 스크립트의 클립보드 입력(붙여넣기 없이 복사만) 패턴을 그대로 쓴다 -
Windows의 getpass는 Ctrl+V를 제어문자로 읽어 붙여넣기가 깨진다(실측, 36자
키가 2자로 들어왔다).

--from-file 모드: 터미널 입력이 익숙하지 않으면 저장소 루트에 값 세 개를
적은 텍스트 파일을 두고 이 스크립트로 흡수시킬 수 있다. 파일 이름을
`KIS-VTS-Key.txt`처럼 지으면 .gitignore의 `/KIS*Key*` 규칙에 이미 걸려
커밋될 일이 없다 - 그래도 이 스크립트가 성공적으로 읽은 뒤에는 원본을
0바이트로 덮어쓰고 지운다(라이브 스크립트와 같은 패턴). Claude는 이 파일을
직접 읽지 않는다 - 오직 이 스크립트(사람이 실행)만 읽고, 화면에는 길이만
보인다.

사용:
    python scripts/setup-kis-vts-key.py
    python scripts/setup-kis-vts-key.py --from-file KIS-VTS-Key.txt
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


def clean_line(s):
    for junk in ("﻿", "​", "‌", "‍", "\xa0"):
        s = s.replace(junk, "")
    return s.strip().strip('"').strip("'").strip()


def read_from_file(path):
    """라벨 붙은 세 줄을 읽는다(앱키/앱시크릿/계좌번호). 값을 출력하지 않는다 -
    길이만 보고한다. 계좌번호는 짧고(예: 8자리+상품코드 2자리) 앱키·시크릿과
    길이로 구분이 안 되므로, 원본 스크립트의 '길이로 자동 구분'은 여기선 안
    쓰고 라벨을 요구한다 - 잘못 배정되면 잘못된 계좌에 주문이 나갈 수 있다."""
    if not path.exists():
        fail("파일이 없다: " + str(path))
    try:
        text = path.read_text(encoding="utf-8-sig", errors="replace")
    except Exception as e:
        fail("파일을 읽지 못했다: " + str(e))

    # 시크릿 값 자체가 base64라 '='로 끝나는 경우가 흔하다(원본
    # setup-kis-key.py가 이미 겪은 함정) - '='를 값 안의 문자로 잘못 나누면
    # 시크릿이 통째로 탈락한다. 그래서 ':'를 우선 구분자로 쓰고, '='는 그
    # 줄에 ':'가 아예 없을 때만, 그것도 앞부분이 라벨처럼 생긴(공백 없는
    # 짧은 영문/밑줄) 경우에만 쓴다.
    found = {}
    for line in text.splitlines():
        line = clean_line(line)
        if not line:
            continue
        name, val = None, None
        if ":" in line:
            name, _, val = line.partition(":")
        elif "=" in line:
            head, _, tail = line.partition("=")
            if head.strip().replace("_", "").replace(" ", "").isalpha() and len(head.strip()) <= 24:
                name, val = head, tail
        if name is None:
            continue
        name = name.strip().lower().replace("_", "").replace(" ", "")
        val = clean_line(val)
        if not val:
            continue
        if name in ("kisvtsappkey", "appkey", "key", "앱키"):
            found["key"] = val
        elif name in ("kisvtsappsecret", "appsecret", "secret", "앱시크릿"):
            found["secret"] = val
        elif name in ("kisvtsaccountno", "account", "accountno", "계좌", "계좌번호"):
            found["account"] = val

    missing = [n for n in ("key", "secret", "account") if n not in found]
    if missing:
        fail("파일에서 라벨을 못 찾았다: " + ", ".join(missing) + ".\n"
             "        파일에 KEY: ... / SECRET: ... / ACCOUNT: ... 형태로 한 줄씩 적는다.")

    say("  파일에서 라벨로 세 값을 찾았습니다.")
    say("    앱키      길이 " + str(len(found["key"])) + "자")
    say("    시크릿    길이 " + str(len(found["secret"])) + "자")
    say("    계좌번호  길이 " + str(len(found["account"])) + "자")
    return found["key"], found["secret"], found["account"]


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

    src_file = None
    for i, a in enumerate(sys.argv[1:]):
        if a == "--from-file" and i + 2 <= len(sys.argv[1:]):
            src_file = Path(sys.argv[i + 2]).expanduser()

    if src_file is not None:
        app_key, app_secret, account_no = read_from_file(src_file)
    else:
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

    if src_file is not None and src_file.exists():
        say()
        say("  원본 파일이 남아 있습니다: " + str(src_file))
        say("  값은 이미 .env로 옮겨졌습니다. 원본을 지우는 것이 안전합니다.")
        ans = ""
        if sys.stdin.isatty():
            try:
                ans = input("  지울까요? [y/N]: ").strip().lower()
            except (EOFError, KeyboardInterrupt):
                ans = ""
        if ans == "y":
            try:
                size = src_file.stat().st_size
                with open(src_file, "wb") as f:
                    f.write(b"\x00" * size)
                    f.flush()
                    os.fsync(f.fileno())
                src_file.unlink()
                say("  원본을 덮어쓰고 삭제했습니다.")
            except Exception as e:
                say("  [주의] 삭제 실패: " + str(e))
        else:
            say("  남겨뒀습니다. 직접 지우시는 것을 권합니다(.gitignore에는 걸려 있습니다).")

    say()
    hold()


if __name__ == "__main__":
    main()
