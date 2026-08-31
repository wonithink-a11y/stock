"""promote-minute-manifest.py — OCI에 오른 분봉 manifest를 검증해 저장소에 승격한다.

VM(collect-minute-kis.py)이 이미 인수 조건을 통과시켰다(§5) - 여기서 그것을
다시 계산하지 않는다. Actions는 검증에 필요한 원본(KIS 응답)을 본 적이 없으므로
잴 수단이 없다(교훈50) - CLAUDE.md "AI 협업 구조" §"manifest를 만드는 것과
승격하는 것은 다르다" 참고.

여기서 잴 수 있는 것은 "OCI에 올라온 바이트가 manifest가 말하는 그대로인가"
하나뿐이다 - sha256(조각별·결합)·행 수. manifest 자체가 옳은지가 아니라
manifest와 실제 객체가 갈리지 않았는가를 본다(교훈43). 하나라도 어긋나면 그
날짜는 승격하지 않는다 - "객체가 있다"가 "검증을 통과했다"로 읽히지 않게.

Raw parquet 자체는 저장소에 두지 않는다(§1) - 여기서 커밋하는 것은
data/backfill/minute/manifest/{date}.json 하나뿐이다.

사용:
    OCI_USER_OCID=... OCI_TENANCY_OCID=... ... \\
        python scripts/promote-minute-manifest.py --namespace ax4zjhxnmgyz
    python scripts/promote-minute-manifest.py --selftest
"""

import argparse
import hashlib
import importlib.util
import io
import json
import os
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
DEFAULT_BUCKET = "stock-minute-manifest"


def load_module(name):
    spec = importlib.util.spec_from_file_location(
        name.replace("-", "_"), REPO / "scripts" / (name + ".py"))
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


def sha256_bytes(b):
    return hashlib.sha256(b).hexdigest()


def combined_sha(parts):
    """collect-minute-kis.py의 combined_sha()와 정확히 같은 식. 갈리면
    Actions가 승격한 manifest의 sha256을 VM이 만든 것과 대조할 수 없다."""
    body = "\n".join(p["name"] + " " + p["sha256"]
                     for p in sorted(parts, key=lambda x: x["name"]))
    return sha256_bytes(body.encode("utf-8"))


def parquet_row_count(data):
    """행 수 재검증. sha256 대조가 이미 바이트 단위로 더 강한 검사라 이건
    이중 확인일 뿐이다 - pyarrow가 없거나 파싱이 안 되면 조용히 건너뛴다
    (sha256이 이미 일치를 확정했다면 그 이상은 파일 형식 문제이지
    전송·변조 문제가 아니다)."""
    try:
        import pyarrow.parquet as pq
    except ImportError:
        return None
    try:
        return pq.ParquetFile(io.BytesIO(data)).metadata.num_rows
    except Exception:
        return None


def verify_day(transport, date):
    """이 날짜의 OCI 객체가 manifest와 일치하는가. (통과, 이유, manifest)를 돌려준다."""
    mkey = "_manifest/" + date + ".json"
    try:
        raw = transport.get(mkey)
    except KeyError:
        return False, "manifest 객체가 없다", None

    man = json.loads(raw.decode("utf-8"))
    if not man.get("acceptancePassed"):
        return False, "manifest.acceptancePassed가 false다", man

    parts = man.get("parts") or []
    if not parts:
        return False, "parts가 비었다", man

    computed, total_rows = [], 0
    for p in parts:
        key = "date=" + date + "/" + p["name"]
        try:
            data = transport.get(key)
        except KeyError:
            return False, "part 객체가 없다: " + key, man
        got_sha = sha256_bytes(data)
        if got_sha != p.get("sha256"):
            return False, "part sha256 불일치: " + p["name"], man
        rows = parquet_row_count(data)
        if rows is not None and rows != p.get("rows"):
            return False, "part 행 수 불일치: " + p["name"], man
        total_rows += p.get("rows", 0)
        computed.append({"name": p["name"], "sha256": got_sha})

    if man.get("sha256") and combined_sha(computed) != man["sha256"]:
        return False, "결합 sha256 불일치", man
    if total_rows != man.get("rows"):
        return False, "조각 행 합이 manifest.rows와 다르다", man

    return True, None, man


def already_promoted_dates(manifest_dir):
    if not Path(manifest_dir).exists():
        return set()
    return {p.stem for p in Path(manifest_dir).glob("*.json")}


def run(transport, manifest_dir, days=None, out=print):
    all_dates = sorted({n[len("_manifest/"):-len(".json")]
                        for n in transport.list_names(prefix="_manifest/")
                        if n.endswith(".json")})
    have = already_promoted_dates(manifest_dir)
    todo = [d for d in all_dates if d not in have]
    if days:
        todo = todo[:days]

    if not todo:
        out("  승격할 것 없다")
        return 0

    Path(manifest_dir).mkdir(parents=True, exist_ok=True)
    promoted, failed = [], []
    for d in todo:
        ok, why, man = verify_day(transport, d)
        if ok:
            (Path(manifest_dir) / (d + ".json")).write_text(
                json.dumps(man, ensure_ascii=False, indent=2) + "\n",
                encoding="utf-8")
            promoted.append(d)
            out("  " + d + "  승격  rows=" + str(man.get("rows")))
        else:
            failed.append((d, why))
            out("  " + d + "  거부  " + why)

    out("")
    out("  승격 %d · 거부 %d" % (len(promoted), len(failed)))
    return 1 if failed else 0


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--days", type=int, default=None,
                    help="이번 실행에서 검증할 최대 날짜 수 (기본 전부)")
    ap.add_argument("--namespace")
    ap.add_argument("--bucket", default=DEFAULT_BUCKET)
    ap.add_argument("--manifest-dir")
    ap.add_argument("--selftest", action="store_true")
    args = ap.parse_args()

    if args.selftest:
        p = REPO / "scripts" / "test-promote-minute-manifest.py"
        if not p.exists():
            print("테스트 파일이 없다")
            sys.exit(1)
        spec = importlib.util.spec_from_file_location("t", p)
        t = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(t)
        sys.exit(t.run_all())

    ns = args.namespace or os.environ.get("OCI_NAMESPACE")
    if not ns:
        raise SystemExit("--namespace 또는 OCI_NAMESPACE 필요")

    osmod = load_module("oci-object-storage")
    cfg = osmod.config_from_env()
    transport = osmod.OciTransport(ns, args.bucket, auth="api_key", config=cfg)

    kis_mod = load_module("collect-minute-kis")
    pol = kis_mod.load_policy()
    manifest_dir = (Path(args.manifest_dir) if args.manifest_dir
                    else (REPO / pol["output"]["manifestDir"]))

    sys.exit(run(transport, manifest_dir, days=args.days))


if __name__ == "__main__":
    main()
