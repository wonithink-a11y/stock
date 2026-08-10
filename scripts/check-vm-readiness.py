"""check-vm-readiness.py — 수집 VM이 Collector를 감당하는지 잰다.

**저장소 없이도 돈다.** 이 파일 하나만 VM에 올려서 실행하면 된다.
stdlib만 쓰고, pyarrow는 있으면 검사하고 없으면 없다고 보고한다.

왜 필요한가:
    개발 환경(Windows·Python 3.13·pyarrow 25)과 운영 환경(Ubuntu 20.04·
    Python 3.8·pyarrow 구버전)이 다르다. 결정적 쓰기 같은 성질은 pyarrow
    버전의 함수라 옮긴 자리에서 다시 재야 한다 - 대조군이 같은 경로인지
    먼저 확인한다(교훈52).

사용:
    python3 scripts/check-vm-readiness.py
    python3 scripts/check-vm-readiness.py --symbols 200 --candles 370
    python3 scripts/check-vm-readiness.py --json > readiness.json
"""

import argparse
import hashlib
import json
import os
import platform
import shutil
import sys
import tempfile
from pathlib import Path

RESULT = {"checks": [], "info": {}}


def add(name, status, detail=None):
    """status: PASS · FAIL · WARN · SKIP"""
    RESULT["checks"].append({"항목": name, "상태": status, "실측": detail})


def peak_rss_mb():
    """리눅스는 /proc에서 피크 RSS를 그대로 준다. 의존성이 필요 없다."""
    try:
        for line in open("/proc/self/status"):
            if line.startswith("VmHWM:"):
                return int(line.split()[1]) / 1024.0
    except Exception:
        pass
    try:
        import resource
        v = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
        return v / 1024.0 if sys.platform != "darwin" else v / 1048576.0
    except Exception:
        return None


def meminfo():
    out = {}
    try:
        for line in open("/proc/meminfo"):
            k, _, v = line.partition(":")
            if k in ("MemTotal", "MemAvailable", "SwapTotal"):
                out[k] = int(v.split()[0]) / 1024.0
    except Exception:
        pass
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--symbols", type=int, default=200,
                    help="한 조각의 종목 수 (정책 flushEverySymbols)")
    ap.add_argument("--candles", type=int, default=370)
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()

    say = (lambda *a: None) if args.json else print

    # ---- 1 런타임 -------------------------------------------------------
    py = sys.version_info
    RESULT["info"]["python"] = "%d.%d.%d" % py[:3]
    RESULT["info"]["platform"] = platform.platform()
    RESULT["info"]["machine"] = platform.machine()
    add("Python 3.8 이상", py >= (3, 8), RESULT["info"]["python"])
    if py < (3, 9):
        add("pyarrow 최신 사용 가능 (3.9 이상)", "WARN",
            "3.8이라 pyarrow는 구버전으로 고정된다. 아래 결정성 검사를 반드시 본다")

    # ---- 2 메모리·디스크 -------------------------------------------------
    mi = meminfo()
    RESULT["info"]["mem"] = mi
    if mi:
        say("  MemTotal %.0f MB · MemAvailable %.0f MB · Swap %.0f MB"
            % (mi.get("MemTotal", 0), mi.get("MemAvailable", 0),
               mi.get("SwapTotal", 0)))
        add("가용 메모리 300MB 이상",
            mi.get("MemAvailable", 0) >= 300,
            {"available": round(mi.get("MemAvailable", 0))})
        if mi.get("SwapTotal", 0) < 1:
            add("스왑이 있다", "WARN",
                "스왑 0. 피크가 튀면 OOM killer가 기존 모니터를 먼저 죽일 수 있다")
    else:
        add("메모리 정보", "SKIP", "/proc/meminfo 없음 (리눅스가 아니다)")

    du = shutil.disk_usage(".")
    RESULT["info"]["diskFreeGB"] = round(du.free / 1e9, 1)
    add("디스크 여유 5GB 이상", du.free >= 5e9,
        {"freeGB": RESULT["info"]["diskFreeGB"],
         "note": "Broad 연 1.52GB"})

    # ---- 3 requests -----------------------------------------------------
    try:
        import requests
        RESULT["info"]["requests"] = requests.__version__
        add("requests 설치됨", True, requests.__version__)
    except ImportError:
        add("requests 설치됨", False, "pip install requests")

    # ---- 4 pyarrow ------------------------------------------------------
    try:
        import pyarrow as pa
        import pyarrow.parquet as pq
        RESULT["info"]["pyarrow"] = pa.__version__
        add("pyarrow 설치됨", True, pa.__version__)
    except ImportError as e:
        add("pyarrow 설치됨", False,
            {"error": str(e),
             "fix": "pip install --no-cache-dir 'pyarrow<17'  "
                    "(Python 3.8은 17 이상을 못 쓴다. --no-cache-dir가 "
                    "1GB에서 OOM을 막는다)"})
        finish(args, say)
        return 1

    codecs = []
    for c in ("zstd", "snappy", "gzip"):
        try:
            codecs.append(c) if pa.Codec.is_available(c) else None
        except Exception:
            pass
    RESULT["info"]["codecs"] = codecs
    add("zstd 코덱 사용 가능", "zstd" in codecs,
        {"available": codecs,
         "note": "없으면 정책의 compression을 snappy로 내려야 한다"})

    # ---- 5 parquet 왕복 + 결정성 (이 버전에서 다시 잰다) -----------------
    grid = ["%02d%02d00" % divmod(m, 60)
            for m in range(9 * 60, 15 * 60 + 20)] + ["153000"]
    use = grid[-args.candles:]
    rows = []
    for i in range(args.symbols):
        tk = "%06d" % i
        for h in use:
            rows.append({"ticker": tk,
                         "ts": "2026-08-03T" + h[:2] + ":" + h[2:4] + "+09:00",
                         "open": 10000, "high": 10010, "low": 9990,
                         "close": 10003, "volume": 100})
    schema = ["ticker", "ts", "open", "high", "low", "close", "volume"]
    comp = "zstd" if "zstd" in codecs else "snappy"

    tmp = Path(tempfile.mkdtemp(prefix="vmready-"))
    try:
        tb = pa.table({k: [r[k] for r in rows] for k in schema})
        f1 = tmp / "a.parquet"
        pq.write_table(tb, f1, compression=comp)
        sz = f1.stat().st_size
        RESULT["info"]["batchRows"] = len(rows)
        RESULT["info"]["batchBytes"] = sz
        RESULT["info"]["bytesPerRow"] = round(sz / len(rows), 2)

        back = pq.read_table(f1)
        add("parquet 왕복 행 수", back.num_rows == len(rows),
            {"rows": back.num_rows})
        add("parquet 스키마 순서 보존", back.column_names == schema,
            back.column_names)
        add("ticker 6자 유지",
            all(len(x) == 6 for x in back.column("ticker").to_pylist()[:100]))

        f2 = tmp / "b.parquet"
        pq.write_table(pa.table({k: [r[k] for r in rows] for k in schema}),
                       f2, compression=comp)
        h1 = hashlib.sha256(f1.read_bytes()).hexdigest()
        h2 = hashlib.sha256(f2.read_bytes()).hexdigest()
        det = h1 == h2
        add("결정적 쓰기 (같은 입력 → 같은 바이트)", det,
            {"pyarrow": pa.__version__, "compression": comp,
             "note": "비결정적이면 manifest의 sha256으로 재빌드 동일성을 "
                     "증명할 수 없다. MN-1.0 §5를 고쳐야 한다"})
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    # ---- 6 피크 RSS ------------------------------------------------------
    peak = peak_rss_mb()
    RESULT["info"]["peakRssMB"] = round(peak, 1) if peak else None
    if peak:
        avail = mi.get("MemAvailable", 0)
        add("한 조각 처리 피크 RSS가 가용 메모리의 절반 이하",
            (not avail) or peak <= avail * 0.5,
            {"peakMB": round(peak, 1), "availableMB": round(avail),
             "note": "이 값이 Collector 한 조각의 실제 상한이다. "
                     "하루치를 다 모으지 않으므로 여기서 더 커지지 않는다"})
        say("  피크 RSS %.1f MB (조각 %d종목 x %d캔들 = %d행)"
            % (peak, args.symbols, args.candles, len(rows)))

    # ---- 7 자격증명 (값은 보지 않는다) -----------------------------------
    env_ok = bool(os.environ.get("KIS_APP_KEY"))
    # KIS_ENV_PATH를 보지 않으면 cwd의 .env만 찾는다. VM은 키를
    # ~/collector-venv/.env에 두므로 있는데도 FAIL이 났다 -
    # smoke는 PASS인데 readiness만 FAIL이면 그 불일치가 단서다.
    dotenv = Path(os.environ.get("KIS_ENV_PATH") or ".env").expanduser()
    if not env_ok and dotenv.exists():
        try:
            env_ok = any(l.startswith("KIS_APP_KEY=") and len(l) > 20
                         for l in dotenv.read_text(encoding="utf-8").splitlines())
        except Exception:
            pass
    add("KIS 앱키가 환경에 있다", env_ok,
        {"note": "값은 확인하지 않는다. 없으면 setup-kis-key.py를 쓴다"})

    return finish(args, say)


def finish(args, say):
    fails = [c for c in RESULT["checks"] if c["상태"] is False
             or c["상태"] == "FAIL"]
    warns = [c for c in RESULT["checks"] if c["상태"] == "WARN"]
    RESULT["passed"] = not fails
    if args.json:
        print(json.dumps(RESULT, ensure_ascii=False, indent=2))
        return 0 if not fails else 1

    print()
    for c in RESULT["checks"]:
        s = c["상태"]
        tag = ("PASS" if s is True else "FAIL" if s is False else s)
        print("  " + tag.ljust(5) + c["항목"])
        if tag != "PASS" and c["실측"] is not None:
            print("        " + json.dumps(c["실측"], ensure_ascii=False)[:220])
    print()
    print("  " + ("준비됨" if not fails else "미준비 — FAIL %d건" % len(fails))
          + (" · 경고 %d건" % len(warns) if warns else ""))
    print()
    return 0 if not fails else 1


if __name__ == "__main__":
    sys.exit(main())
