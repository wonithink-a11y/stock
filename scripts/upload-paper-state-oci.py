"""upload-paper-state-oci.py — 페이퍼 트레이딩 상태(positionStore)를 OCI
Object Storage로 올린다. 분봉 승격 파이프라인(VM -> Object Storage -> Actions
-> commit, CLAUDE.md "정본을 쓰는 주체는 하나다")과 같은 원칙, 같은 버킷
(stock-minute-manifest, IAM 정책이 버킷명 기준이라 새 prefix를 써도 콘솔
작업 없이 그대로 통한다) - 다른 건 이 상태가 하루 여러 번(장중 10분 간격)
바뀐다는 점뿐이다.

버킷 IAM이 OVERWRITE를 안 준다(upload-minute-oci.py와 동일 제약) - 그래서
매번 새 타임스탬프 키로 올린다(paper-state/{strategy}/{YYYYmmddTHHMMSS}.json).
Actions 쪽(sync-paper-state-oci.py)이 전략별 최신 것만 골라 쓴다.

ponytail: 정리(오래된 객체 삭제) 없음 - IAM이 DELETE도 안 줘서 이 스크립트가
할 수 있는 일이 아니다. 누적이 문제되면 OCI 콘솔에서 버킷 lifecycle 정책을
추가하는 게 맞는 해결책(콘솔 작업, Claude가 못 함).

사용 (VM, run_paper_trading_daily.py가 매 실행 끝에 호출):
    python scripts/upload-paper-state-oci.py --namespace ax4zjhxnmgyz
    python scripts/upload-paper-state-oci.py --selftest
"""
import argparse
import importlib.util
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
DEFAULT_BUCKET = "stock-minute-manifest"
STRATEGIES = ["pbr_value_v1", "lowmom60_v1", "pbr_value_v1_combined",
              "factor_earnings_yield_v1", "foreign_flow5d_v1"]
KST = timezone(timedelta(hours=9))


def load_module(name):
    spec = importlib.util.spec_from_file_location(
        name.replace("-", "_"), REPO / "scripts" / (name + ".py"))
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


def upload_state(transport, strategy, state_path, now=None, out=print, prefix="paper-state"):
    """state_path가 없으면(아직 신호가 한 번도 안 났다) 조용히 건너뛴다 -
    빈 상태를 굳이 올릴 이유가 없다.

    prefix: "paper-state"(positionStore) 또는 "paper-orders"(주문 원장 -
    주문번호->전략 매핑, positionStore.record_order 가 쓴다). 둘 다 누적본
    전체를 매번 올리므로 받는 쪽은 최신 하나만 보면 된다."""
    if not state_path.exists():
        out(f"  {strategy}  건너뜀 - 로컬 상태 파일 없음 ({prefix})")
        return False
    ts = (now or datetime.now(KST)).strftime("%Y%m%dT%H%M%S")
    key = f"{prefix}/{strategy}/{ts}.json"
    transport.put(key, state_path.read_bytes())
    out(f"  {strategy}  올림  {key}")
    return True


# (파일 접미사, OCI prefix). 원장은 주문이 한 번이라도 나간 뒤에야 생기므로
# 없는 것이 정상이다 - upload_state 가 건너뛴다.
KINDS = [("positions", "paper-state"), ("orders", "paper-orders")]


def run(transport, repo_root, out=print):
    paper_dir = Path(repo_root) / "research/strategy-lab/data/paper"
    for strategy in STRATEGIES:
        for suffix, prefix in KINDS:
            upload_state(transport, strategy, paper_dir / f"{strategy}_{suffix}.json",
                          out=out, prefix=prefix)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--namespace")
    ap.add_argument("--bucket", default=DEFAULT_BUCKET)
    ap.add_argument("--selftest", action="store_true")
    args = ap.parse_args()

    if args.selftest:
        p = REPO / "scripts" / "test-upload-paper-state-oci.py"
        if not p.exists():
            print("테스트 파일이 없다")
            sys.exit(1)
        spec = importlib.util.spec_from_file_location("t", p)
        t = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(t)
        sys.exit(t.run_all())

    import os
    ns = args.namespace or os.environ.get("OCI_NAMESPACE")
    if not ns:
        raise SystemExit("--namespace 또는 OCI_NAMESPACE 필요")

    osmod = load_module("oci-object-storage")
    transport = osmod.OciTransport(ns, args.bucket, auth="instance_principal")
    run(transport, REPO)


if __name__ == "__main__":
    main()
