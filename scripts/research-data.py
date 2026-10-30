#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""연구 데이터 묶음 — PC 에서 VM 으로 올리고(push), 클라우드 세션이 VM 에서 받는다(get).

PC 에만 있던 연구 캐시(크립토 시세·.cache 패널·A4·ETF 분봉·DART 공시)를 폴더 단위 tar 묶음으로
VM /srv/stock-data/bundles/ 에 두고, nginx /research-data/ 가 키(X-Data-Key)로 내준다(읽기 전용).
설계: docs/control/연구데이터-VM보관-설계-2026-10-30.md

  python scripts/research-data.py list                  # VM 에 있는 묶음 목록
  python scripts/research-data.py get crypto-k1 a4      # 받기 → sha256 확인 → 원래 경로에 풀기 (all = 전부)
  python scripts/research-data.py push [이름…]           # PC 전용: 바뀐 묶음만 다시 묶어 VM 에 올린다(ssh stock-new)
  python scripts/research-data.py --selftest            # 네트워크 없이

★ 키는 환경변수 RESEARCH_DATA_KEY(또는 .env). 저장소·로그에 넣지 않는다(절대 규칙 2).
★ git 이 추적하는 파일·*.log·_rules*.json(원작자 재배포 금지)·prompts/opencode-in/opencode-out 은 묶지 않는다.
★ 결과 파일에 쓴 묶음의 sha256·builtAt 을 적는다 — 어느 시점 PC 스냅샷으로 돌렸는지가 재현성이다.
"""
import hashlib
import json
import os
import subprocess
import sys
import tarfile
import tempfile
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
KST = timezone(timedelta(hours=9))
URL = os.environ.get("RESEARCH_DATA_URL", "https://wonithink-stock.duckdns.org/research-data/")
SSH_HOST = os.environ.get("RESEARCH_DATA_SSH", "stock-new")
REMOTE = "/srv/stock-data"
STAMPS = REPO / ".cache" / "research-data-stamps.json"      # get 이 푼 묶음의 sha256 (/.cache 는 gitignore)
PUSHED = REPO / ".cache" / "research-data-push.json"        # push 가 올린 원본 지문

CRYPTO, CACHE, DATA = "research/strategy-lab/data/crypto", "research/strategy-lab/.cache", "research/strategy-lab/data"
REST, FILES = "REST", "FILES"      # REST = 같은 뿌리에서 다른 묶음이 안 가져간 폴더 전부 · FILES = 뿌리 바로 아래 파일
BUNDLES = {        # 이름: (뿌리, 폴더 목록 | REST | FILES) — 새 폴더가 생기면 REST 가 받는다
    "crypto-k1": (CRYPTO, ["k1"]),
    "crypto-1m": (CRYPTO, ["1m"]),
    "crypto-metrics": (CRYPTO, ["metrics"]),
    "crypto-basis": (CRYPTO, ["basis"]),
    "crypto-activity": (CRYPTO, ["activity"]),
    "crypto-small": (CRYPTO, REST),
    "cache-minute_raw": (CACHE, ["minute_raw"]),
    "cache-fwd_oos": (CACHE, ["fwd_oos"]),
    "cache-combined_rank": (CACHE, ["combined_rank"]),
    "cache-leadlag": (CACHE, ["leadlag"]),
    "cache-panels": (CACHE, FILES),
    "cache-small": (CACHE, REST),
    "a4": (DATA, ["a4"]),
    "etf-ohlc": (DATA, ["etf-ohlc"]),
    "dart": (DATA, ["dart_event_titles", "order-contracts"]),
}
SKIP_DIRS = {"prompts", "opencode-in", "opencode-out", "__pycache__"}


def skipped(rel):
    parts = rel.split("/")
    name = parts[-1]
    return (name.endswith((".log", ".part")) or name.startswith("_rules") or name.startswith("research-data-")
            or any(p in SKIP_DIRS for p in parts))


def bundle_files(repo, name, tracked=frozenset()):
    """묶음에 들어갈 파일(저장소 기준 posix 상대 경로) 정렬 목록."""
    root, sel = BUNDLES[name]
    base = Path(repo) / root
    if not base.is_dir():
        return []
    if sel == FILES:
        tops = [p for p in base.iterdir() if p.is_file()]
    else:
        if sel == REST:
            claimed = {d for r, s in BUNDLES.values() if r == root and isinstance(s, list) for d in s}
            dirs = [p for p in base.iterdir() if p.is_dir() and p.name not in claimed]
        else:
            dirs = [base / d for d in sel if (base / d).is_dir()]
        tops = [f for d in dirs for f in d.rglob("*") if f.is_file()]
    out = []
    for f in tops:
        rel = f.relative_to(repo).as_posix()
        if rel not in tracked and not skipped(rel):
            out.append(rel)
    return sorted(out)


def fingerprint(repo, files):
    h = hashlib.sha256()
    for rel in files:
        st = (Path(repo) / rel).stat()
        h.update(f"{rel}\t{st.st_size}\t{st.st_mtime_ns}\n".encode())
    return h.hexdigest()


def sha256_file(path):
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def build_tar(repo, files, out):
    def norm(ti):      # 소유자·사용자 이름을 지운다(PC 계정명이 묶음에 실리지 않게)
        ti.uid = ti.gid = 0
        ti.uname = ti.gname = ""
        return ti
    with tarfile.open(out, "w:gz", compresslevel=1) as tar:
        for rel in files:
            tar.add(str(Path(repo) / rel), arcname=rel, recursive=False, filter=norm)


def safe_extract(tar_path, repo, root):
    """뿌리 밖·절대 경로·'..'·링크·장치 파일이 하나라도 있으면 아무것도 풀지 않고 실패."""
    prefix = root.rstrip("/") + "/"
    with tarfile.open(tar_path, "r:*") as tar:
        members = tar.getmembers()
        for m in members:
            n = m.name
            if not (m.isfile() or m.isdir()):
                raise ValueError(f"파일·폴더가 아닌 항목: {n}")
            if n.startswith(("/", "\\")) or ":" in n or ".." in n.replace("\\", "/").split("/"):
                raise ValueError(f"위험한 경로: {n}")
            if not n.startswith(prefix):
                raise ValueError(f"묶음 뿌리({root}) 밖: {n}")
        kw = {"filter": "data"} if hasattr(tarfile, "data_filter") else {}
        tar.extractall(str(repo), members=members, **kw)
    return len(members)


def load_json(p, default):
    try:
        return json.loads(Path(p).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return default


def save_json(p, obj):
    Path(p).parent.mkdir(parents=True, exist_ok=True)
    Path(p).write_text(json.dumps(obj, ensure_ascii=False, indent=1), encoding="utf-8")


def data_key():
    k = os.environ.get("RESEARCH_DATA_KEY")
    if not k and (REPO / ".env").exists():
        for line in (REPO / ".env").read_text(encoding="utf-8").splitlines():
            a, _, v = line.partition("=")
            if a.strip() == "RESEARCH_DATA_KEY":
                k = v.strip().strip('"').strip("'")
    if not k:
        sys.exit("RESEARCH_DATA_KEY 가 없다 — 클라우드 환경 변수나 .env 에 넣는다(값을 대화에 붙이지 않는다).")
    return k


def http_get(path, key):
    req = urllib.request.Request(URL + path, headers={"X-Data-Key": key, "User-Agent": "stock-research-data/1"})
    return urllib.request.urlopen(req, timeout=60)


def remote_manifest(key):
    with http_get("manifest.json", key) as r:
        return {b["name"]: b for b in json.load(r)}


def cmd_list():
    man = remote_manifest(data_key())
    stamps = load_json(STAMPS, {})
    for n in sorted(man):
        b = man[n]
        here = "받음" if stamps.get(n) == b["sha256"] else ""
        print(f"{n:22} {b['bytes'] / 1e6:9.1f}MB {b['files']:6}개  {b['builtAt'][:16]}  {here}")


def cmd_get(names):
    key = data_key()
    man = remote_manifest(key)
    names = sorted(man) if names == ["all"] else names
    unknown = [n for n in names if n not in man]
    if unknown:
        sys.exit(f"VM 에 없는 묶음: {unknown} — list 로 확인")
    stamps = load_json(STAMPS, {})
    for n in names:
        b = man[n]
        if stamps.get(n) == b["sha256"]:
            print(f"{n}: 이미 받음(sha256 같음) — 건너뜀")
            continue
        fd, tmp = tempfile.mkstemp(suffix=".tar.gz")
        h, got = hashlib.sha256(), 0
        try:
            with os.fdopen(fd, "wb") as out, http_get(f"{n}.tar.gz", key) as r:
                for chunk in iter(lambda: r.read(1 << 20), b""):
                    out.write(chunk)
                    h.update(chunk)
                    got += len(chunk)
            if h.hexdigest() != b["sha256"]:
                sys.exit(f"{n}: sha256 불일치 — 받다 끊겼거나 VM 묶음이 바뀌는 중. 다시 실행")
            cnt = safe_extract(tmp, REPO, b["root"])
        finally:
            os.unlink(tmp)
        stamps[n] = b["sha256"]
        save_json(STAMPS, stamps)
        print(f"{n}: {got / 1e6:.1f}MB · {cnt}개 → {b['root']} (builtAt {b['builtAt']}, sha256 {b['sha256'][:12]})")


def ssh(cmd, data=None):
    r = subprocess.run(["ssh", SSH_HOST, cmd], input=data, capture_output=True)
    if r.returncode:
        raise RuntimeError(f"ssh 실패({cmd[:60]}…): {r.stderr.decode(errors='replace').strip()}")
    return r.stdout.decode()


def cmd_push(names):
    tracked = set(subprocess.run(["git", "ls-files", "-z"], cwd=REPO, capture_output=True, check=True)
                  .stdout.decode().split("\0"))
    raw = ssh(f"cat {REMOTE}/bundles/manifest.json 2>/dev/null || echo []")
    man = {b["name"]: b for b in json.loads(raw)}
    pushed = load_json(PUSHED, {})
    for n in names or list(BUNDLES):
        files = bundle_files(REPO, n, tracked)
        if not files:
            print(f"{n}: 파일 없음 — 건너뜀")
            continue
        fp = fingerprint(REPO, files)
        if pushed.get(n) == fp and n in man:
            print(f"{n}: 바뀐 것 없음 — 건너뜀")
            continue
        with tempfile.TemporaryDirectory() as td:
            tar = os.path.join(td, f"{n}.tar.gz")
            build_tar(REPO, files, tar)
            sha, size = sha256_file(tar), os.path.getsize(tar)
            print(f"{n}: {len(files)}개 · {size / 1e6:.1f}MB 올리는 중…", flush=True)
            part = f"{REMOTE}/incoming/{n}.tar.gz.part"
            subprocess.run(["scp", "-q", tar, f"{SSH_HOST}:{part}"], check=True)
        remote_sha = ssh(f"sha256sum {part}").split()[0]
        if remote_sha != sha:
            raise RuntimeError(f"{n}: VM 에 올라간 파일 sha256 불일치 — 교체하지 않음")
        ssh(f"mv {part} {REMOTE}/bundles/{n}.tar.gz")
        newest = max((REPO / f).stat().st_mtime for f in files)
        man[n] = {"name": n, "root": BUNDLES[n][0], "bytes": size, "sha256": sha, "files": len(files),
                  "builtAt": datetime.now(KST).isoformat(timespec="seconds"),
                  "srcNewest": datetime.fromtimestamp(newest, KST).isoformat(timespec="seconds")}
        body = json.dumps(sorted(man.values(), key=lambda b: b["name"]), ensure_ascii=False, indent=1).encode()
        ssh(f"cat > {REMOTE}/incoming/manifest.json.part && mv {REMOTE}/incoming/manifest.json.part {REMOTE}/bundles/manifest.json", body)
        pushed[n] = fp
        save_json(PUSHED, pushed)
        print(f"{n}: 완료 (sha256 {sha[:12]})")


def selftest():
    fails = []

    def ok(cond, msg):
        if not cond:
            fails.append(msg)

    # 같은 뿌리에서 두 묶음이 같은 폴더를 가져가지 않는다
    seen = {}
    for n, (r, s) in BUNDLES.items():
        for d in (s if isinstance(s, list) else []):
            ok((r, d) not in seen, f"폴더 중복: {r}/{d}")
            seen[(r, d)] = n

    with tempfile.TemporaryDirectory() as td:
        repo = Path(td) / "repo"
        files = {
            f"{CRYPTO}/k1/a.parquet": b"k1", f"{CRYPTO}/funding/f.json": b"fund", f"{CRYPTO}/funding/_rules_x.json": b"no",
            f"{CRYPTO}/upbit-listings/run.log": b"no", f"{CACHE}/minute_raw/d=1/m.parquet": b"m",
            f"{CACHE}/a2b/b.parquet": b"b", f"{CACHE}/a2b/tracked.json": b"git", f"{CACHE}/prompts/p.txt": b"no",
            f"{CACHE}/top.parquet": b"top", f"{CACHE}/run.log": b"no", f"{DATA}/a4/x.parquet": b"a4",
        }
        for rel, body in files.items():
            (repo / rel).parent.mkdir(parents=True, exist_ok=True)
            (repo / rel).write_bytes(body)
        tracked = {f"{CACHE}/a2b/tracked.json"}
        ok(bundle_files(repo, "crypto-k1", tracked) == [f"{CRYPTO}/k1/a.parquet"], "crypto-k1 구성")
        ok(bundle_files(repo, "crypto-small", tracked) == [f"{CRYPTO}/funding/f.json"], "crypto-small: k1 제외·_rules·log 제외")
        ok(bundle_files(repo, "cache-small", tracked) == [f"{CACHE}/a2b/b.parquet"], "cache-small: 추적 파일·prompts·minute_raw 제외")
        ok(bundle_files(repo, "cache-panels", tracked) == [f"{CACHE}/top.parquet"], "cache-panels: 뿌리 파일만·log 제외")
        ok(bundle_files(repo, "cache-minute_raw", tracked) == [f"{CACHE}/minute_raw/d=1/m.parquet"], "minute_raw 하위 폴더")
        ok(bundle_files(repo, "etf-ohlc", tracked) == [], "없는 폴더는 빈 목록")

        fl = bundle_files(repo, "crypto-small", tracked)
        fp1 = fingerprint(repo, fl)
        (repo / fl[0]).write_bytes(b"fund2")
        ok(fingerprint(repo, fl) != fp1, "내용·크기가 바뀌면 지문이 바뀐다")

        tar = Path(td) / "b.tar.gz"
        build_tar(repo, bundle_files(repo, "cache-small", tracked), tar)
        dest = Path(td) / "dest"
        ok(safe_extract(tar, dest, CACHE) == 1, "풀린 개수")
        ok((dest / CACHE / "a2b/b.parquet").read_bytes() == b"b", "왕복 내용 일치")
        with tarfile.open(tar) as t:
            ok(all(m.uname == "" and m.uid == 0 for m in t.getmembers()), "계정명 제거")

        def evil(name, kind=tarfile.REGTYPE):
            p = Path(td) / "evil.tar.gz"
            with tarfile.open(p, "w:gz") as t:
                ti = tarfile.TarInfo(name)
                ti.type = kind
                if kind == tarfile.SYMTYPE:
                    ti.linkname = "/etc/passwd"
                t.addfile(ti, None if kind != tarfile.REGTYPE else __import__("io").BytesIO(b""))
            try:
                safe_extract(p, dest, CACHE)
                return False
            except ValueError:
                return True
        ok(evil(f"{CACHE}/../../evil"), "'..' 거부")
        ok(evil("/abs/evil"), "절대 경로 거부")
        ok(evil(f"{CRYPTO}/k1/x"), "뿌리 밖 거부")
        ok(evil(f"{CACHE}/link", tarfile.SYMTYPE), "링크 거부")
        ok(not (Path(td) / "evil").exists(), "거부된 묶음은 아무것도 안 풀린다")

    ok(skipped("a/b/_rules_v4.json") and skipped("x/run.log") and not skipped("x/k.parquet"), "제외 규칙")
    for f in fails:
        print("FAIL", f)
    print(f"selftest {'OK' if not fails else 'FAIL'} ({len(fails)} 실패)")
    return 1 if fails else 0


def main(argv):
    if not argv or argv[0] in ("-h", "--help"):
        print(__doc__)
        return 0
    if argv[0] == "--selftest":
        return selftest()
    cmd, rest = argv[0], argv[1:]
    if cmd == "list":
        cmd_list()
    elif cmd == "get":
        if not rest:
            sys.exit("받을 묶음 이름을 적는다(또는 all) — list 로 확인")
        cmd_get(rest)
    elif cmd == "push":
        bad = [n for n in rest if n not in BUNDLES]
        if bad:
            sys.exit(f"모르는 묶음: {bad} — 가능: {', '.join(BUNDLES)}")
        cmd_push(rest)
    else:
        sys.exit(f"모르는 명령: {cmd}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
