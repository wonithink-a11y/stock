"""upload-minute-oci.py — 분봉 raw+manifest를 OCI Object Storage로 올린다 (MN-1.0 §1.1)

VM 블록 볼륨이 사라지면 같이 사라지므로 사본을 별도로 둔다(§1.1). 이 스크립트는
"복사"가 아니라 승격 파이프라인의 첫 단이다 - GitHub Actions(promote-minute-
manifest.py)가 이 버킷을 읽어 manifest만 저장소에 커밋한다(§1, raw는 저장소 밖).

여기서 raw를 검증하지 않는다. 검증(acceptance)은 이미 수집기가 했다(§5) - 여기는
통과한 결과를 옮기기만 한다. `_manifest/*.json`(통과분만 존재, `_failed/`는 별도
디렉터리라 여기서 안 보인다)을 훑는 것 자체가 "통과한 날짜만 올린다"는 필터다.

업로드 순서: 조각(parts)을 먼저, manifest는 마지막에. manifest 객체의 존재가
"이 날짜가 완전히 올라갔다"는 뜻이 되게 한다 - collect-minute-kis.py의 manifest
계약(교훈43)과 같은 원칙을 업로드 단계에도 그대로 적용한 것이다. 중간에 죽어도
다음 실행이 이어받는다(이미 있는 조각은 건너뛴다).

버킷의 IAM 정책은 OVERWRITE·DELETE를 의도적으로 안 준다(2026-08-30 확정) -
그러므로 이미 올라간 날짜를 다시 올리려 하면 조용히 성공하는 대신 명시적으로
실패한다. 이 스크립트가 재시도 가능한 것은 '멱등'이지 '덮어쓰기'가 아니다.

사용:
    python scripts/upload-minute-oci.py --namespace ax4zjhxnmgyz
    python scripts/upload-minute-oci.py --date 2026-08-31 --namespace ax4zjhxnmgyz
    python scripts/upload-minute-oci.py --all --namespace ax4zjhxnmgyz   # 첫 백필용
    python scripts/upload-minute-oci.py --selftest
"""

import argparse
import importlib.util
import json
import os
import sys
import time
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
DEFAULT_BUCKET = "stock-minute-manifest"


def load_module(name):
    """하이픈이 든 파일명이라 import 문으로는 못 부른다(run-minute-daily.py와 동일)."""
    spec = importlib.util.spec_from_file_location(
        name.replace("-", "_"), REPO / "scripts" / (name + ".py"))
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


def candidate_dates(manifest_dir, uploaded, limit=None):
    """로컬에 통과 manifest가 있고 아직 안 올라간 날짜. 오래된 것부터 -
    사라질 위험이 큰 쪽(VM이 죽으면 통째로 사라지는 쪽)이 먼저다."""
    dates = sorted(p.stem for p in Path(manifest_dir).glob("*.json")
                   if p.stem not in uploaded)
    return dates[:limit] if limit else dates


def upload_day(transport, date, raw_root, manifest_dir, out=print):
    man_path = Path(manifest_dir) / (date + ".json")
    man = json.loads(man_path.read_text(encoding="utf-8"))
    part_dir = Path(raw_root) / ("date=" + date)
    existing = transport.list_names(prefix="date=" + date + "/")

    n_uploaded = 0
    for p in man.get("parts", []):
        key = "date=" + date + "/" + p["name"]
        if key in existing:
            continue
        f = part_dir / p["name"]
        if not f.exists():
            raise SystemExit("part 파일이 로컬에 없다: " + str(f))
        transport.put(key, f.read_bytes())
        n_uploaded += 1

    mkey = "_manifest/" + date + ".json"
    if mkey not in transport.list_names(prefix=mkey):
        transport.put(mkey, man_path.read_bytes())
    out("  " + date + "  올림  조각 새로 %d/%d" %
        (n_uploaded, len(man.get("parts", []))))


def run(transport, manifest_dir, raw_root, days=None, date=None,
        budget_minutes=30.0, out=print):
    uploaded = {n[len("_manifest/"):-len(".json")]
               for n in transport.list_names(prefix="_manifest/")
               if n.endswith(".json")}

    if date:
        if date in uploaded:
            out("  건너뜀   " + date + "  이미 올라감")
            return 0
        todo = [date]
    else:
        todo = candidate_dates(manifest_dir, uploaded, days)

    if not todo:
        out("  올릴 것 없다")
        return 0

    started = time.time()
    for d in todo:
        if (time.time() - started) / 60.0 > budget_minutes:
            out("  [예산] %.0f분을 넘겨 남은 날짜는 다음 실행으로 넘긴다: %s"
                % (budget_minutes, d))
            break
        upload_day(transport, d, raw_root, manifest_dir, out=out)
    return 0


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--date")
    ap.add_argument("--days", type=int, default=5,
                    help="이번 실행에서 올릴 최대 날짜 수 (기본 5)")
    ap.add_argument("--all", action="store_true",
                    help="--days 무시하고 밀린 것 전부 (첫 백필용)")
    ap.add_argument("--budget-minutes", type=float, default=30.0)
    ap.add_argument("--namespace")
    ap.add_argument("--bucket", default=DEFAULT_BUCKET)
    ap.add_argument("--raw-root")
    ap.add_argument("--manifest-dir")
    ap.add_argument("--selftest", action="store_true")
    args = ap.parse_args()

    if args.selftest:
        p = REPO / "scripts" / "test-upload-minute-oci.py"
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
    transport = osmod.OciTransport(ns, args.bucket, auth="instance_principal")

    kis_mod = load_module("collect-minute-kis")
    pol = kis_mod.load_policy()
    raw, _state, mandir = kis_mod.env_paths(pol)
    raw_root = Path(args.raw_root) if args.raw_root else raw
    manifest_dir = Path(args.manifest_dir) if args.manifest_dir else mandir

    days = None if args.all else args.days
    sys.exit(run(transport, manifest_dir, raw_root, days=days, date=args.date,
                budget_minutes=args.budget_minutes))


if __name__ == "__main__":
    main()
