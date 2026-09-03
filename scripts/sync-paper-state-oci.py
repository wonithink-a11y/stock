"""sync-paper-state-oci.py — OCI에 오른 페이퍼 트레이딩 상태 중 전략별
최신 것만 내려받아 research/strategy-lab/data/paper/에 놓는다.

promote-minute-manifest.py와 달리 sha256/행수 검증이 없다 - positionStore는
VM 하나(collector-venv)만 쓰는 몇 KB짜리 JSON이라 분봉 parquet처럼 다단계
전송 손상을 걱정할 이유가 없다(교훈50 - 잴 게 없으면 안 잰다). "검증"은
JSON 파싱 성공 여부 하나뿐 - 깨진 객체면 그 전략만 건너뛰고 이전 커밋된
값을 그대로 둔다(fail-soft, 절대 규칙 1 - 지어내지 않는다).

내려받은 상태 파일 자체는 커밋하지 않는다(positionStore 관례 그대로,
.gitignore 대상) - 이 스크립트를 부른 워크플로가 build_ui_feed.py로
ui/data/positions.json을 만들 때 로컬에서 한 번 쓰고 버릴 재료일 뿐이다.

사용:
    python scripts/sync-paper-state-oci.py --namespace ax4zjhxnmgyz
    python scripts/sync-paper-state-oci.py --selftest
"""
import argparse
import importlib.util
import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
DEFAULT_BUCKET = "stock-minute-manifest"
STRATEGIES = ["pbr_value_v1", "lowmom60_v1"]


def load_module(name):
    spec = importlib.util.spec_from_file_location(
        name.replace("-", "_"), REPO / "scripts" / (name + ".py"))
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


def latest_key(transport, strategy):
    keys = sorted(transport.list_names(prefix=f"paper-state/{strategy}/"))
    return keys[-1] if keys else None


def sync_one(transport, strategy, out_dir, out=print):
    key = latest_key(transport, strategy)
    if key is None:
        out(f"  {strategy}  없음 - OCI에 올라온 상태 없음(아직 신호가 안 났거나 relay 전)")
        return False
    raw = transport.get(key)
    try:
        json.loads(raw)  # 파싱만 확인 - 내용을 해석하지 않는다(교훈50)
    except (ValueError, UnicodeDecodeError) as e:
        out(f"  {strategy}  거부 - {key} 파싱 실패: {e}")
        return False
    dest = Path(out_dir) / f"{strategy}_positions.json"
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_bytes(raw)
    out(f"  {strategy}  받음  {key}")
    return True


def run(transport, repo_root, out=print):
    out_dir = Path(repo_root) / "research/strategy-lab/data/paper"
    return {s: sync_one(transport, s, out_dir, out=out) for s in STRATEGIES}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--namespace")
    ap.add_argument("--bucket", default=DEFAULT_BUCKET)
    ap.add_argument("--selftest", action="store_true")
    args = ap.parse_args()

    if args.selftest:
        p = REPO / "scripts" / "test-sync-paper-state-oci.py"
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
    cfg = osmod.config_from_env()
    transport = osmod.OciTransport(ns, args.bucket, auth="api_key", config=cfg)
    run(transport, REPO)


if __name__ == "__main__":
    main()
