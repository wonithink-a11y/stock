"""setup-upbit-key.py — 업비트 Open API 액세스키/시크릿키를 .env에 넣는다.
scripts/setup-kis-key.py와 완전히 같은 구조(같은 실패 모드를 이미 겪고
고친 코드라 그대로 재사용) - 이름만 KIS_APP_KEY/SECRET에서
UPBIT_ACCESS_KEY/SECRET_KEY로 바꿨다.

왜 있는가:
    키를 파일에 직접 쓰면 오타, 따옴표, BOM, 줄바꿈으로 조용히 틀린다.
    프롬프트로 받아 정규화하고, 쓰기 전에 gitignore 여부를 실제로 확인한다.

이 스크립트는 키 값을 화면에 출력하지 않는다. getpass는 별표도 찍지 않으므로
입력 직후 길이를 알려준다. 보이지 않는 것과 안 들어간 것은 다르다.

사용:
    python scripts/setup-upbit-key.py

.env는 .gitignore에 있다. 그래도 매번 git check-ignore로 확인한다.
규율은 예외 경로를 막지 못한다(교훈65).

주의: 콘솔이 cp949일 수 있으므로 출력은 errors='replace'로 연다(교훈70).
      em-dash, 가운뎃점 같은 문자는 쓰지 않는다.
"""

import os
import re
import subprocess
import sys
from pathlib import Path

# 관측 경로는 자기 자신 때문에도 죽는다. 먼저 안전하게 연다.
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(errors="replace")
    except Exception:
        pass

REPO = Path(__file__).resolve().parent.parent
KEYS = ("UPBIT_ACCESS_KEY", "UPBIT_SECRET_KEY")

# 경로를 하드코딩하지 않는다. VM에서는 저장소 밖에 둘 수 있다.
#   UPBIT_ENV_PATH=~/collector-venv/.env python3 setup-upbit-key.py
ENV_PATH = Path(os.environ.get("UPBIT_ENV_PATH")
                or (REPO / ".env")).expanduser()


# 보이지 않으면 붙여넣기가 됐는지 알 수 없어 여러 번 누르게 된다 -
# 실측으로 36자 키가 72자(2회 붙여넣기)로 들어왔다. --show면 보여준다.
SHOW_INPUT = ("--show" in sys.argv)


def say(msg=""):
    print(msg, flush=True)


def hold():
    """창이 바로 닫혀 메시지를 못 읽는 일을 막는다."""
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
    """ENV_PATH의 가장 가까운 '존재하는' 조상. cwd로 폴백하지 않는다.

    폴백하면 대상이 저장소 밖인데도 저장소의 .env를 대신 검사해
    '무시됩니다'라는 거짓 안심을 준다 - 실제로 그렇게 나왔다.
    """
    d = ENV_PATH.parent
    while not d.is_dir() and d.parent != d:
        d = d.parent
    return d


def git_ok(args):
    """git 명령의 종료코드가 0인가."""
    try:
        r = subprocess.run(
            ["git"] + args, cwd=str(git_base()),
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        )
        return r.returncode == 0
    except FileNotFoundError:
        return False


def read_clipboard():
    """Windows 클립보드 원문을 읽는다. 실패하면 None."""
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


def read_secret(label, seen):
    """값을 받아 정규화한다. 붙여넣기 사고를 여기서 잡는다.

    클립보드에서 읽는다. 콘솔 붙여넣기를 거치지 않는 이유:
    Windows의 getpass는 msvcrt로 키를 한 글자씩 직접 읽으므로 Ctrl+V가
    붙여넣기가 아니라 제어문자 하나로 들어온다. 실측으로 36자 키가 2자가 됐다.
    사람에게 붙여넣기를 요구하지 않으면 그 실패 모드가 아예 없어진다.

    seen: 이미 받은 값들. 클립보드를 안 바꾸고 Enter만 누른 경우를 잡는다.
    tty가 아니면 stdin으로 내려온다(테스트 전용).
    """
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
                    raw = input("  " + label + " (붙여넣고 Enter, "
                                "화면에 보입니다): ")
                else:
                    import getpass
                    raw = getpass.getpass("  " + label + " (붙여넣고 Enter, "
                                          "화면에는 안 보입니다): ")
            except (EOFError, KeyboardInterrupt):
                fail("입력이 취소됐다.")
        else:
            say("  " + label + " [비대화형 stdin]")
            raw = sys.stdin.readline()
            if not raw:
                fail("입력이 취소됐다.")

        v = raw
        for junk in ("﻿", "​", "‌", "‍", " "):
            v = v.replace(junk, "")
        v = v.strip().strip('"').strip("'").strip()

        if not v:
            say("    [다시] 비어 있습니다. 붙여넣은 뒤 Enter를 누릅니다.")
            continue
        if any(c.isspace() for c in v):
            say("    [다시] 값 안에 공백이나 줄바꿈이 있습니다.")
            say("           액세스키와 시크릿키를 한 줄씩 따로 복사해서 넣습니다.")
            continue
        if v.split("=")[0] in KEYS:
            v = v.split("=", 1)[1].strip()
            if not v:
                say("    [다시] 값이 비어 있습니다.")
                continue
        half = len(v) // 2
        if len(v) % 2 == 0 and half >= 8 and v[:half] == v[half:]:
            say("    [다시] 같은 값이 두 번 붙었습니다 (" + str(len(v)) +
                "자 = " + str(half) + "자 x 2).")
            say("           붙여넣기가 두 번 들어갔습니다. 한 번만 넣습니다.")
            continue
        if v in seen:
            say("    [다시] 앞에서 받은 값과 같습니다.")
            say("           클립보드가 아직 안 바뀌었습니다. 다음 값을 복사한 뒤 Enter.")
            continue

        say("    받았습니다. 길이 " + str(len(v)) + "자")
        return v


def clean(s):
    """BOM, 제로폭 문자, 따옴표를 걷어낸다."""
    for junk in ("﻿", "​", "‌", "‍", "\xa0"):
        s = s.replace(junk, "")
    return s.strip().strip('"').strip("'").strip()


def read_docx(path):
    """docx에서 문단 텍스트만 뽑는다. 외부 의존성을 쓰지 않는다."""
    import zipfile
    from xml.sax.saxutils import unescape

    try:
        with zipfile.ZipFile(path) as z:
            xml = z.read("word/document.xml").decode("utf-8", errors="replace")
    except KeyError:
        fail("docx 안에 word/document.xml이 없다. 진짜 docx가 맞는지 본다.")
    except Exception as e:
        fail("docx를 열지 못했다: " + str(e))

    xml = re.sub(r"</w:(p|tr)>", "\n", xml)
    xml = re.sub(r"</w:tc>", "\t", xml)
    xml = re.sub(r"<w:tab[^>]*/>", "\t", xml)
    xml = re.sub(r"<[^>]+>", "", xml)
    return unescape(xml)


def read_from_file(path):
    """키가 담긴 텍스트 파일에서 두 값을 뽑는다. 값은 절대 출력 안 함."""
    if not path.exists():
        fail("파일이 없다: " + str(path))

    if path.suffix.lower() == ".docx":
        text = read_docx(path)
    else:
        try:
            text = path.read_text(encoding="utf-8-sig", errors="replace")
        except Exception as e:
            fail("파일을 읽지 못했다: " + str(e))

    labelled = {}
    tokens = []
    for line in text.splitlines():
        line = clean(line)
        if not line:
            continue

        for sep in ("=", ":"):
            if sep in line:
                name, _, val = line.partition(sep)
                name = name.strip().lower().replace("_", "").replace(" ", "")
                val = clean(val)
                if val and " " not in val:
                    if name in ("upbitaccesskey", "accesskey", "access", "액세스키"):
                        labelled["key"] = val
                    elif name in ("upbitsecretkey", "secretkey", "secret", "시크릿키"):
                        labelled["secret"] = val
                break

        for p in [clean(x) for x in line.split()]:
            lab = re.match(r"^[A-Za-z_][A-Za-z0-9_]{0,24}[=:](.+)$", p)
            if lab:
                p = clean(lab.group(1))
            if len(p) >= 16:
                tokens.append(p)

    if "key" in labelled and "secret" in labelled:
        k, s = labelled["key"], labelled["secret"]
        say("  파일에서 라벨로 두 값을 찾았습니다.")
    else:
        uniq = []
        for t in tokens:
            if t not in uniq:
                uniq.append(t)
        if len(uniq) < 2:
            fail("파일에서 값 두 개를 찾지 못했다. 찾은 개수: " + str(len(uniq)))
        if len(uniq) > 2:
            fail("파일에서 값 후보가 " + str(len(uniq)) + "개 나왔다. "
                 "키 두 줄만 남기고 다시 저장한다.")
        # 업비트 액세스키/시크릿키는 둘 다 uuid 형태라 길이로 못 가른다 -
        # 파일에 등장하는 순서(액세스키 먼저 발급/표시)를 그대로 쓴다.
        k, s = uniq[0], uniq[1]
        say("  파일에서 값 두 개를 찾았습니다. 등장 순서대로 액세스키/시크릿키로 봅니다.")

    if k == s:
        fail("두 값이 같다.")

    say("    액세스키    길이 " + str(len(k)) + "자")
    say("    시크릿키    길이 " + str(len(s)) + "자")
    return k, s


def mask(v):
    if len(v) <= 4:
        return "*" * len(v)
    return v[:4] + "*" * (len(v) - 4) + "  (" + str(len(v)) + "자)"


def main():
    say()
    say("  업비트 API 키 설정")
    say("  대상 파일: " + str(ENV_PATH))
    say()

    in_repo = git_ok(["rev-parse", "--is-inside-work-tree"])
    if in_repo:
        if not git_ok(["check-ignore", "-q", "--", str(ENV_PATH)]):
            fail(str(ENV_PATH) + " 가 .gitignore에 걸리지 않는다.\n"
                 "        이 저장소는 공개다. .gitignore를 먼저 고친다.")
    else:
        say("  [알림] git 저장소가 아닙니다. 커밋 위험은 없지만")
        say("         파일 권한으로만 보호됩니다.")
        say()

    src_file = None
    for i, a in enumerate(sys.argv[1:]):
        if a == "--from-file" and i + 2 <= len(sys.argv[1:]):
            src_file = Path(sys.argv[i + 2]).expanduser()

    if src_file is not None:
        access_key, secret_key = read_from_file(src_file)
    else:
        say("  업비트 마이페이지 > Open API 관리에서 발급받은 값 두 개를 차례로 넣습니다.")
        if os.name == "nt":
            say("  타이핑도 붙여넣기도 하지 않습니다. 복사만 하면 됩니다.")
        else:
            say("  터미널에 붙여넣고 Enter를 누릅니다. 화면에는 안 보입니다.")
        say()
        access_key = read_secret("1/2 액세스키(Access Key)", set())
        secret_key = read_secret("2/2 시크릿키(Secret Key)", {access_key})

    if access_key == secret_key:
        fail("두 값이 같다. 액세스키와 시크릿키를 다시 확인한다.")

    # 업비트 키는 둘 다 uuid(36자) 형태다 - 길이 검사는 참고용 경고만.
    if len(access_key) < 20:
        say("  [주의] 액세스키가 짧아 보입니다.")
    if len(secret_key) < 20:
        say("  [주의] 시크릿키가 짧아 보입니다.")

    lines = []
    if ENV_PATH.exists():
        say()
        say("  기존 .env를 발견했습니다. 업비트 항목만 갱신하고 나머지는 보존합니다.")
        for line in ENV_PATH.read_text(encoding="utf-8").splitlines():
            name = line.split("=", 1)[0].strip()
            if name not in KEYS:
                lines.append(line)

    ENV_PATH.parent.mkdir(parents=True, exist_ok=True)
    lines.append("UPBIT_ACCESS_KEY=" + access_key)
    lines.append("UPBIT_SECRET_KEY=" + secret_key)

    with open(ENV_PATH, "w", encoding="utf-8", newline="\n") as f:
        f.write("\n".join(lines) + "\n")

    try:
        me = os.environ.get("USERNAME", "")
        if me and os.name == "nt":
            subprocess.run(
                ["icacls", str(ENV_PATH), "/inheritance:r",
                 "/grant:r", me + ":(R,W)"],
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            )
    except Exception:
        say("  [주의] 파일 권한 제한에 실패했습니다. 파일 자체는 정상입니다.")

    say()
    say("  완료")
    say("    UPBIT_ACCESS_KEY  " + mask(access_key))
    say("    UPBIT_SECRET_KEY  " + mask(secret_key))
    say()

    if in_repo and git_ok(["ls-files", "--error-unmatch", str(ENV_PATH)]):
        say("  [경고] .env가 git에 추적되고 있습니다. 즉시 조치가 필요합니다.")
        say("         git rm --cached .env")
    elif in_repo:
        say("  .env는 git이 무시합니다. 커밋되지 않습니다.")
    else:
        say("  git 저장소 밖입니다. 파일 권한으로 보호됩니다.")

    if src_file is not None and src_file.exists():
        say()
        say("  원본 파일이 남아 있습니다: " + str(src_file))
        say("  이 파일은 .gitignore 밖이고 권한도 넓습니다. 지우는 것이 안전합니다.")
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
            say("  남겨뒀습니다. 직접 지우시는 것을 권합니다.")

    say()
    hold()


if __name__ == "__main__":
    main()
