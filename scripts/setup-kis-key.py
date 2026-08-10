"""setup-kis-key.py — KIS 앱키/앱시크릿을 .env에 넣는다.

왜 있는가:
    키를 파일에 직접 쓰면 오타, 따옴표, BOM, 줄바꿈으로 조용히 틀린다.
    프롬프트로 받아 정규화하고, 쓰기 전에 gitignore 여부를 실제로 확인한다.

이 스크립트는 키 값을 화면에 출력하지 않는다. getpass는 별표도 찍지 않으므로
입력 직후 길이를 알려준다. 보이지 않는 것과 안 들어간 것은 다르다.

사용:
    python scripts/setup-kis-key.py

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
KEYS = ("KIS_APP_KEY", "KIS_APP_SECRET")

# 경로를 하드코딩하지 않는다. VM에서는 저장소 밖에 둘 수 있다.
#   KIS_ENV_PATH=~/collector-venv/.env python3 setup-kis-key.py
ENV_PATH = Path(os.environ.get("KIS_ENV_PATH")
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
        # 콘솔 코드페이지가 무엇이든 깨지지 않게 관대하게 디코드한다.
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
    # 클립보드 경로는 Windows 전용이다. POSIX에서는 getpass가 tty 라인
    # 편집기를 거치므로 붙여넣기가 정상 동작한다 - Windows에서만 msvcrt가
    # 키를 한 글자씩 읽어 Ctrl+V가 제어문자로 들어왔다.
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

        # BOM과 제로폭 문자를 먼저 걷어낸다. 이것이 남으면 뒤의 검사가 통째로
        # 뚫린다 - 'KIS_APP_KEY=' 접두사 검사가 BOM 하나에 무력화됐다.
        # 웹 페이지에서 복사할 때 실제로 섞여 들어온다.
        v = raw
        for junk in ("﻿", "​", "‌", "‍", " "):
            v = v.replace(junk, "")
        v = v.strip().strip('"').strip("'").strip()

        if not v:
            say("    [다시] 비어 있습니다. 붙여넣은 뒤 Enter를 누릅니다.")
            continue
        if any(c.isspace() for c in v):
            # 두 줄을 한 번에 붙여넣은 경우가 대부분이다.
            say("    [다시] 값 안에 공백이나 줄바꿈이 있습니다.")
            say("           앱키와 시크릿을 한 줄씩 따로 복사해서 넣습니다.")
            continue
        if v.split("=")[0] in KEYS:
            # 'KIS_APP_KEY=abc' 통째로 복사한 경우. 값만 살려서 쓴다.
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
    """docx에서 문단 텍스트만 뽑는다. 외부 의존성을 쓰지 않는다.

    docx는 zip이고 본문은 word/document.xml이다. 문단 </w:p> 경계를 줄바꿈으로
    바꾸고 태그를 지운다. 서식은 버린다 - 여기서 필요한 것은 값뿐이다.
    """
    import re
    import zipfile
    from xml.sax.saxutils import unescape

    try:
        with zipfile.ZipFile(path) as z:
            xml = z.read("word/document.xml").decode("utf-8", errors="replace")
    except KeyError:
        fail("docx 안에 word/document.xml이 없다. 진짜 docx가 맞는지 본다.")
    except Exception as e:
        fail("docx를 열지 못했다: " + str(e))

    # 표 셀과 탭도 값 경계다. 공백으로 바꿔 토큰이 붙지 않게 한다.
    xml = re.sub(r"</w:(p|tr)>", "\n", xml)
    xml = re.sub(r"</w:tc>", "\t", xml)
    xml = re.sub(r"<w:tab[^>]*/>", "\t", xml)
    xml = re.sub(r"<[^>]+>", "", xml)
    return unescape(xml)


def read_from_file(path):
    """키가 담긴 텍스트 파일에서 두 값을 뽑는다.

    사람이 만든 메모 파일을 받는다. 형식을 강제하지 않는다.
    이 함수는 값을 절대 출력하지 않는다 - 길이만 보고한다.
    """
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

        # 'KIS_APP_KEY=값' / 'appkey: 값' / 'APP KEY 값' 형태를 먼저 본다.
        for sep in ("=", ":"):
            if sep in line:
                name, _, val = line.partition(sep)
                name = name.strip().lower().replace("_", "").replace(" ", "")
                val = clean(val)
                if val and " " not in val:
                    if name in ("kisappkey", "appkey", "key", "앱키"):
                        labelled["key"] = val
                    elif name in ("kisappsecret", "appsecret", "secret", "앱시크릿"):
                        labelled["secret"] = val
                break

        # 라벨이 없어도 토큰처럼 생긴 줄은 후보로 모은다.
        for p in [clean(x) for x in line.split()]:
            # 'NAME=값' 형태면 값만 취한다. 그러나 값 안의 '='는 버리지 않는다 -
            # KIS 앱시크릿은 base64라 '='로 끝난다. 이것을 구분자로 읽어
            # 180자 시크릿을 통째로 탈락시킨 적이 있다.
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
        # 앱시크릿이 앱키보다 훨씬 길다. 길이로 가른다.
        k, s = sorted(uniq, key=len)
        say("  파일에서 값 두 개를 찾았습니다. 긴 쪽을 시크릿으로 봅니다.")

    if k == s:
        fail("두 값이 같다.")

    say("    앱키      길이 " + str(len(k)) + "자")
    say("    시크릿    길이 " + str(len(s)) + "자")
    return k, s


def mask(v):
    if len(v) <= 4:
        return "*" * len(v)
    return v[:4] + "*" * (len(v) - 4) + "  (" + str(len(v)) + "자)"


def main():
    say()
    say("  KIS 앱키 설정")
    say("  대상 파일: " + str(ENV_PATH))
    say()

    # 1. 쓰기 전에 gitignore를 확인한다. 커밋 가능하면 여기서 멈춘다.
    #    수집 VM처럼 저장소가 아닌 곳에서도 돌아야 하므로, '저장소가 아니다'와
    #    '저장소인데 무시되지 않는다'를 가른다. 뒤엣것만 중단 사유다.
    in_repo = git_ok(["rev-parse", "--is-inside-work-tree"])
    if in_repo:
        if not git_ok(["check-ignore", "-q", "--", str(ENV_PATH)]):
            fail(str(ENV_PATH) + " 가 .gitignore에 걸리지 않는다.\n"
                 "        이 저장소는 공개다. .gitignore를 먼저 고친다.")
    else:
        say("  [알림] git 저장소가 아닙니다. 커밋 위험은 없지만")
        say("         파일 권한으로만 보호됩니다.")
        say()

    # 2. 값을 받는다. 파일 모드가 주어지면 그쪽이 우선이다.
    src_file = None
    for i, a in enumerate(sys.argv[1:]):
        if a == "--from-file" and i + 2 <= len(sys.argv[1:]):
            src_file = Path(sys.argv[i + 2]).expanduser()

    if src_file is not None:
        app_key, app_secret = read_from_file(src_file)
    else:
        say("  KIS Developers에서 발급받은 값 두 개를 차례로 넣습니다.")
        # 안내는 실제로 타는 경로와 같아야 한다. Windows는 클립보드를 읽고
        # POSIX는 붙여넣기를 받는다 - 문구가 어긋나면 사람이 엉뚱한 조작을 한다.
        if os.name == "nt":
            say("  타이핑도 붙여넣기도 하지 않습니다. 복사만 하면 됩니다.")
        else:
            say("  터미널에 붙여넣고 Enter를 누릅니다. 화면에는 안 보입니다.")
            say("  PC의 .env에서 값을 옮기려면 아래가 더 간단합니다:")
            say("    scp <PC경로>/.env ubuntu@<VM>:~/collector-venv/.env")
        say()
        app_key = read_secret("1/2 앱키(APP KEY)", set())
        app_secret = read_secret("2/2 앱시크릿(APP SECRET)", {app_key})

    if app_key == app_secret:
        fail("두 값이 같다. 앱키와 시크릿을 다시 확인한다.")

    # 길이는 막지 않고 알리기만 한다.
    # KIS가 형식을 바꿔도 스크립트가 먼저 죽지 않게 한다.
    if len(app_key) < 20:
        say("  [주의] 앱키가 짧아 보입니다.")
    if len(app_secret) < 50:
        say("  [주의] 시크릿이 짧아 보입니다.")

    # 3. 기존 .env의 다른 키를 보존하며 병합한다.
    lines = []
    if ENV_PATH.exists():
        say()
        say("  기존 .env를 발견했습니다. KIS 항목만 갱신하고 나머지는 보존합니다.")
        for line in ENV_PATH.read_text(encoding="utf-8").splitlines():
            name = line.split("=", 1)[0].strip()
            if name not in KEYS:
                lines.append(line)

    ENV_PATH.parent.mkdir(parents=True, exist_ok=True)
    lines.append("KIS_APP_KEY=" + app_key)
    lines.append("KIS_APP_SECRET=" + app_secret)

    # Path.write_text의 newline 인자는 3.10부터다. VM은 3.8이라 open으로 쓴다.
    # 문법 검사(ast feature_version)로는 이런 API 차이가 안 잡힌다.
    with open(ENV_PATH, "w", encoding="utf-8", newline="\n") as f:
        f.write("\n".join(lines) + "\n")

    # 4. 파일 권한을 현재 사용자로 좁힌다. 실패해도 치명적이지 않다.
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

    # 5. 결과 확인. 값은 앞 4자만 보인다.
    say()
    say("  완료")
    say("    KIS_APP_KEY     " + mask(app_key))
    say("    KIS_APP_SECRET  " + mask(app_secret))
    say()

    # 6. 마지막으로 실제 git 상태를 본다.
    if in_repo and git_ok(["ls-files", "--error-unmatch", str(ENV_PATH)]):
        say("  [경고] .env가 git에 추적되고 있습니다. 즉시 조치가 필요합니다.")
        say("         git rm --cached .env")
    elif in_repo:
        say("  .env는 git이 무시합니다. 커밋되지 않습니다.")
    else:
        say("  git 저장소 밖입니다. 파일 권한으로 보호됩니다.")

    # 7. 원본 파일은 남겨두지 않는다. 키가 두 곳에 있으면 관리 지점이 둘이다.
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
                # 지우기 전에 내용을 덮어쓴다. 삭제만으로는 블록이 남는다.
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
