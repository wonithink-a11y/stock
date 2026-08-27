"""setup-keys-interactive.py — 여러 서비스(KIS 실전·KIS 모의·업비트·DART·
KRX·한국은행) 키를 한 번의 실행으로 순서대로 물어보며 .env에 넣는다.

setup-all-keys.py(파일 통째로 자동 파싱)가 2026-08-27에 실제로 키 두 개를
화면에 그대로 노출시키는 사고를 냈다(값 안의 base64 "=" 패딩을 구분자로
착각) - 그 사고 이후 만든 안전한 대안이다. 이 스크립트는 파일을 파싱하지
않는다 - setup-kis-key.py/setup-upbit-key.py와 똑같이, 서비스별로 값을
하나씩 클립보드로만 받는다(Windows: 복사만 하면 붙여넣기 없이 자동으로
읽는다 - getpass가 Ctrl+V를 깨뜨리는 문제를 피하는 이미 검증된 방법).

각 항목은 건너뛸 수 있다 - 없는 키는 Enter 대신 's'를 입력한다. 건너뛴
항목은 기존 .env 값을 그대로 둔다(지우지 않는다).

값은 화면에 안 보인다(길이만). 사용:
    python scripts/setup-keys-interactive.py
    (또는 저장소 루트의 setup-keys.bat 더블클릭)
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
ENV_PATH = Path(os.environ.get("KEYS_ENV_PATH") or (REPO / ".env")).expanduser()

# (서비스 표시명, [(env 변수명, 항목 라벨), ...])
SERVICES = [
    ("KIS 실전계좌", [
        ("KIS_APP_KEY", "앱키(APP KEY)"),
        ("KIS_APP_SECRET", "앱시크릿(APP SECRET)"),
        ("KIS_ACCOUNT_NO", "계좌번호(예: 12345678-01) - 지금은 이걸 쓰는 코드가 없다, 미리 저장만"),
    ]),
    ("KIS 모의투자(VTS)", [
        ("KIS_VTS_APP_KEY", "앱키(APP KEY)"),
        ("KIS_VTS_APP_SECRET", "앱시크릿(APP SECRET)"),
        ("KIS_VTS_ACCOUNT_NO", "계좌번호(예: 12345678-01)"),
    ]),
    ("업비트", [
        ("UPBIT_ACCESS_KEY", "액세스키(Access Key)"),
        ("UPBIT_SECRET_KEY", "시크릿키(Secret Key)"),
    ]),
    ("DART", [
        ("DART_API_KEY", "API 키"),
    ]),
    ("KRX Open API", [
        ("KRX_OPENAPI_KEY", "API 키"),
    ]),
    ("한국은행 ECOS", [
        ("ECOS_API_KEY", "API 키"),
    ]),
]


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
            ["powershell", "-NoProfile", "-NonInteractive",
             "-Command", "Get-Clipboard -Raw"],
            capture_output=True, timeout=15,
        )
        if r.returncode != 0:
            return None
        return r.stdout.decode("utf-8", errors="replace")
    except Exception:
        return None


def mask(v):
    if len(v) <= 4:
        return "*" * len(v)
    return v[:4] + "*" * (len(v) - 4) + "  (" + str(len(v)) + "자)"


def read_one(env_name, label, seen):
    """반환: 값(str) 또는 None(건너뜀). seen은 이번 실행에서 이미 받은
    값들 - 클립보드를 안 바꾸고 또 Enter만 누른 실수를 잡는다."""
    interactive = sys.stdin.isatty()
    use_clip = interactive and os.name == "nt"
    while True:
        say(f"  {env_name}  ({label})")
        if use_clip:
            say("    있으면: 값을 복사(Ctrl+C)한 뒤 Enter.  없으면: 's' 입력 후 Enter(건너뜀).")
            try:
                cmd = input("    > ").strip()
            except (EOFError, KeyboardInterrupt):
                fail("입력이 취소됐다.")
            if cmd.lower() in ("s", "skip"):
                say("    건너뜀.")
                say()
                return None
            raw = read_clipboard()
            if raw is None:
                fail("클립보드를 읽지 못했다.")
        elif interactive:
            try:
                import getpass
                raw = getpass.getpass("    붙여넣고 Enter(화면에 안 보임), 없으면 's': ")
            except (EOFError, KeyboardInterrupt):
                fail("입력이 취소됐다.")
            if raw.strip().lower() in ("s", "skip"):
                say("    건너뜀.")
                say()
                return None
        else:
            say("    [비대화형 stdin]")
            raw = sys.stdin.readline()
            if not raw or raw.strip().lower() in ("s", "skip"):
                say("    건너뜀.")
                say()
                return None

        v = raw
        for junk in ("﻿", "​", "‌", "‍", " "):
            v = v.replace(junk, "")
        v = v.strip().strip('"').strip("'").strip()

        if not v:
            say("    [다시] 비어 있다. 복사 후 Enter, 또는 's'로 건너뛴다.")
            say()
            continue
        if any(c.isspace() for c in v):
            say("    [다시] 값 안에 공백/줄바꿈이 있다. 한 값만 복사한다.")
            say()
            continue
        if v.split("=")[0].replace("_", "").replace(" ", "").upper() == env_name.replace("_", ""):
            v = v.split("=", 1)[1].strip() if "=" in v else v
            if not v:
                say("    [다시] 값이 비어 있다.")
                say()
                continue
        half = len(v) // 2
        if len(v) % 2 == 0 and half >= 8 and v[:half] == v[half:]:
            say(f"    [다시] 같은 값이 두 번 붙었다({len(v)}자 = {half}자 x 2). 한 번만 복사한다.")
            say()
            continue
        if v in seen:
            say("    [다시] 앞서 받은 값과 같다. 클립보드가 안 바뀌었다 - 다음 값을 복사한다.")
            say()
            continue

        say("    받음. 길이 " + str(len(v)) + "자")
        say()
        return v


def main():
    say()
    say("  키 일괄 설정 (서비스별로 하나씩, 없으면 's'로 건너뜀)")
    say("  대상 파일: " + str(ENV_PATH))
    say()

    in_repo = git_ok(["rev-parse", "--is-inside-work-tree"])
    if in_repo:
        if not git_ok(["check-ignore", "-q", "--", str(ENV_PATH)]):
            fail(str(ENV_PATH) + " 가 .gitignore에 걸리지 않는다.\n"
                 "        이 저장소는 공개다. .gitignore를 먼저 고친다.")
    else:
        say("  [알림] git 저장소가 아닙니다. 파일 권한으로만 보호됩니다.")
        say()

    collected = {}
    seen_values = set()
    for service_name, fields in SERVICES:
        say(f"--- {service_name} ---")
        for env_name, label in fields:
            v = read_one(env_name, label, seen_values)
            if v is not None:
                collected[env_name] = v
                seen_values.add(v)

    if not collected:
        say("  아무 값도 받지 않았다. .env를 바꾸지 않았다.")
        say()
        hold()
        return

    lines = []
    if ENV_PATH.exists():
        for line in ENV_PATH.read_text(encoding="utf-8").splitlines():
            name = line.split("=", 1)[0].strip()
            if name not in collected:
                lines.append(line)
    for name, val in collected.items():
        lines.append(name + "=" + val)

    ENV_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(ENV_PATH, "w", encoding="utf-8", newline="\n") as f:
        f.write("\n".join(lines) + "\n")

    try:
        me = os.environ.get("USERNAME", "")
        if me and os.name == "nt":
            subprocess.run(["icacls", str(ENV_PATH), "/inheritance:r",
                             "/grant:r", me + ":(R,W)"],
                            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except Exception:
        say("  [주의] 파일 권한 제한에 실패했습니다. 파일 자체는 정상입니다.")

    say("  완료 - " + str(len(collected)) + "개 항목을 넣었다:")
    for name in sorted(collected):
        say("    " + name.ljust(20) + mask(collected[name]))
    say()

    if in_repo and git_ok(["ls-files", "--error-unmatch", str(ENV_PATH)]):
        say("  [경고] .env가 git에 추적되고 있습니다. 즉시 조치가 필요합니다.")
        say("         git rm --cached .env")
    elif in_repo:
        say("  .env는 git이 무시합니다. 커밋되지 않습니다.")
    else:
        say("  git 저장소 밖입니다. 파일 권한으로 보호됩니다.")

    say()
    hold()


if __name__ == "__main__":
    main()
