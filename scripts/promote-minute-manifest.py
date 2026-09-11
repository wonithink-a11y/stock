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
from datetime import datetime, timedelta, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
KST = timezone(timedelta(hours=9))
DEFAULT_BUCKET = "stock-minute-manifest"

# collect-minute-kis.py의 day_verdict()가 내는 값 중 '장이 안 섰다'를
# 뜻하는 것. UNKNOWN은 여기 없다 - 그것은 장애와 휴장을 구분하지 못한
# 상태이지 휴장이 아니다.
CLOSED_VERDICTS = ("CLOSED_CONFIRMED", "CLOSED_INFERRED")


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
        # 휴장일은 조각이 없는 것이 정상이다. 그 경계는 수집기가 이미
        # 갈라 뒀다(교훈75) - '조회했더니 장이 안 섰다'(CLOSED_*)와
        # '조회하지 못했다'(UNKNOWN)는 다르다. 후자는 여전히 거부다:
        # 모르는 것은 0이 아니다(교훈57).
        #
        # 거부가 아니라 승격으로 보내는 이유: 거부하면 이 날짜가
        # 백로그에 영원히 남아 매 실행을 붉게 만든다. 영원히 참인
        # 경고는 모두가 무시하는 법을 배운다 - 실제로 2026-08-17
        # (광복절 대체공휴일)이 5회 연속 job을 붉게 만들었다. manifest를
        # 쓰면 저장소가 "그날은 봤고 장이 안 섰다"를 기록한다 - 날짜가
        # 아예 없는 것과 구분된다(교훈75).
        if man.get("dayVerdict") in CLOSED_VERDICTS and not man.get("rows"):
            return True, None, man
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


def repo_holes(have, trading_days, today, lookback=10, grace=1):
    """저장소에 뚫린 구멍. '무엇이 실패했나'가 아니라 '무엇이 없나'를 본다.

    워크플로가 전부 녹색인데 데이터가 없을 수 있다 - VM 실패는 Actions 에
    아예 나타나지 않는다(2026-09-10 실측: 09-04·09-07 2일이 6일간 조용히
    없었다). 실패를 감시하면 그 경로만 잡지만 결과를 감시하면 원인과
    무관하게 잡는다 - VM 죽음·수집 FAIL·OCI 업로드 중단·승격 거부 전부.

    grace: 가장 최근 거래일은 아직 안 올라왔을 수 있다(VM 18:00 → 승격
        19:30 KST). 하루 늦게 알리는 대신 거짓 경보를 안 낸다.
    lookback: 못 메우는 하루가 영원히 붉은 경고가 되지 않게 창을 둔다 -
        영원히 참인 경고는 모두가 무시하는 법을 배운다(CLAUDE.md).
        캘린더가 최근을 못 덮으면 창이 그만큼 일찍 끝난다(거짓 경보 없음).
    """
    days = [d for d in sorted(trading_days) if d <= today]
    if grace:
        days = days[:-grace]
    return [d for d in days[-lookback:] if d not in have]


def run(transport, manifest_dir, days=None, out=print, trading_days=None,
        today=None):
    all_dates = sorted({n[len("_manifest/"):-len(".json")]
                        for n in transport.list_names(prefix="_manifest/")
                        if n.endswith(".json")})
    have = already_promoted_dates(manifest_dir)
    todo = [d for d in all_dates if d not in have]
    if days:
        todo = todo[:days]

    def holes_after(code):
        if not trading_days:
            return code
        h = repo_holes(already_promoted_dates(manifest_dir), trading_days,
                       today or datetime.now(KST).date().isoformat())
        if not h:
            return code
        out("")
        out("  [구멍] 최근 거래일 중 저장소에 manifest 가 없는 날: " + ", ".join(h))
        out("         OCI 에도 없으면 VM 쪽이다 - Actions 에는 안 나타난다.")
        out("         복구: VM 에서 run-minute-daily.py --date <날짜>")
        return 1

    if not todo:
        out("  승격할 것 없다")
        return holes_after(0)

    Path(manifest_dir).mkdir(parents=True, exist_ok=True)
    promoted, closed, failed = [], [], []
    for d in todo:
        ok, why, man = verify_day(transport, d)
        if ok:
            (Path(manifest_dir) / (d + ".json")).write_text(
                json.dumps(man, ensure_ascii=False, indent=2) + "\n",
                encoding="utf-8")
            if man.get("parts"):
                promoted.append(d)
                out("  " + d + "  승격  rows=" + str(man.get("rows")))
            else:
                closed.append(d)
                out("  " + d + "  휴장  " + str(man.get("dayVerdict")))
        else:
            failed.append((d, why))
            out("  " + d + "  거부  " + why)

    out("")
    out("  승격 %d · 휴장 %d · 거부 %d"
        % (len(promoted), len(closed), len(failed)))
    return holes_after(1 if failed else 0)


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

    # 캘린더가 없으면 구멍 검사를 건너뛴다 - 모르는 것은 0이 아니다(교훈57).
    try:
        cal = kis_mod.load_context()["tradingDays"]
    except Exception as e:
        print("  [구멍검사 생략] 캘린더를 못 읽었다: " + str(e))
        cal = None

    sys.exit(run(transport, manifest_dir, days=args.days, trading_days=cal))


if __name__ == "__main__":
    main()
