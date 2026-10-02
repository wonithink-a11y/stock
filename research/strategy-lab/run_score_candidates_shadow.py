#!/usr/bin/env python3
"""점수 후보 3종(M0 KR-2.4 · M1 가치 100 · M2 가치 50:기술 20) 병행 관찰 — 스냅샷 생성기.

사전등록: findings/score-candidates-shadow-preregistration-2026-10.md (이 문서가 이 코드보다 우선한다).
**탐색 후보이며 사전 선택된 검증 모델이 아니다.** 운영 점수·정책·portfolio 는 건드리지 않는다.

하는 일: A5 PIT 패널(data/backfill/scores)에서 동결일(2026-10-02) 이후의 주간 스냅샷일마다
  모집단(PIT 가치·기술 점수가 있는 ACTIVE/NORMAL 종목)을 정하고, 세 모델의 상위/하위 20% 목록을 **고정 저장**한다.
하지 않는 일: **미래 수익률을 읽거나 계산하지 않는다**(fwd 필드를 버린다). 과거 스냅샷을 고치지 않는다(추가 전용).
  후보 정의를 바꾸지 않는다 - 정의 파일 sha256 이 이 파일의 상수와 다르면 거부한다.

사용
  python run_score_candidates_shadow.py --selftest            # 네트워크·저장소 데이터 없이 돈다
  python run_score_candidates_shadow.py --dry-run --date 2026-09-03 --out 경로   # 기계 점검. 참고 전용(reference), 저장소에 안 쓴다
  python run_score_candidates_shadow.py --snapshot            # 정식. 정의·코드·문서가 커밋된 깨끗한 상태에서만, 새 스냅샷일만 추가

월간 점검: A2a·A5 갱신이 끝난 뒤 --snapshot 을 돌리고 snapshots.jsonl 을 커밋한다. 성과 부착(--evaluate)은 첫 성숙 뒤 별도 구현.

구현 세부(사전등록에 없는 것, 문서와 충돌하면 문서가 이긴다)
  - snapshots.jsonl 은 줄 = 스냅샷일 1개(종목별·모델별 줄이 아니다): 모집단 행 전체의 축 원점수와 모델별 상/하위 목록을 한 줄에 담는다.
    종목×모델 줄로 쓰면 월 ~16k줄이 되어 공개 저장소에 무겁다. 정보는 같고 모델 점수는 축 원점수+동결 공식으로 재현된다.
  - 점수는 소수 6자리로 반올림한 뒤 정렬한다(플랫폼별 부동소수점 순서 차이 방지). 동점은 티커 오름차순.
  - 패널 행에는 pitViolation 이 저장되지 않는다(A5 가 critical 위반 행을 쓰지 않는다) -> 제외 건수는 0 으로 둔다.
"""
import argparse
import gzip
import hashlib
import json
import math
import subprocess
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parent.parent
SHADOW_DIR = HERE / "reports" / "2026-10-score-candidates-shadow"
DEF_PATH = SHADOW_DIR / "candidate-models.v1.json"
SNAP_PATH = SHADOW_DIR / "snapshots.jsonl"
PREREG = HERE / "findings" / "score-candidates-shadow-preregistration-2026-10.md"
SCORES_DIR = REPO / "data" / "backfill" / "scores"
CALENDAR = REPO / "data" / "backfill" / "calendar.json"

FREEZE_DATE = "2026-10-02"
# 정의 파일(LF 정규화 바이트)의 sha256 - 정의를 바꾸면 이 상수와 어긋나 기록이 거부된다.
EXPECTED_DEF_SHA256 = "1648a84d3025f68c1e30492f167d123c49ebbc64280d1bf5a28f1653e95ab092"
AXIS_KEY = {"fundamental": "F", "valuation": "V", "technical": "T"}
MIN_ROWS_PER_DATE = 200


# ---------------------------------------------------------------- 정의·검사
def sha256_lf(path: Path) -> str:
    """CRLF 를 LF 로 정규화한 바이트의 sha256 - 플랫폼(autocrlf)에 따라 해시가 갈리지 않게."""
    return hashlib.sha256(path.read_bytes().replace(b"\r\n", b"\n")).hexdigest()


def load_definition() -> dict:
    got = sha256_lf(DEF_PATH)
    if got != EXPECTED_DEF_SHA256:
        raise SystemExit(f"후보 정의 파일의 sha256 이 동결값과 다르다 - 기록 거부\n  기대 {EXPECTED_DEF_SHA256}\n  실제 {got}")
    return json.loads(DEF_PATH.read_text(encoding="utf-8"))


def committed_clean(p: Path) -> bool:
    rel = str(p.relative_to(REPO)).replace("\\", "/")
    tracked = subprocess.run(["git", "ls-files", "--error-unmatch", rel], cwd=REPO, capture_output=True).returncode == 0
    dirty = subprocess.run(["git", "status", "--porcelain", "--", rel], cwd=REPO, capture_output=True, text=True).stdout.strip()
    return tracked and not dirty


# ---------------------------------------------------------------- 계산 (순수 함수)
def raw_axes(c: dict, axis_weights: dict) -> dict:
    """패널 c(재정규화된 기여도)를 축 원점수로 되돌린다: raw = c × (존재하는 축 가중치 합) / W[축]."""
    present = [a for a in axis_weights if c.get(a) is not None]
    s = sum(axis_weights[a] for a in present)
    return {a: round(c[a] * s / axis_weights[a], 6) for a in present}


def model_score(model: dict, fin: float, ax: dict):
    if model["kind"] == "fin":
        return round(fin, 6)
    w = model["weights"]
    if any(a not in ax for a in w):
        return None
    return round(sum(w[a] * ax[a] for a in w) / sum(w.values()), 6)


def select_lists(scored: list, frac: float) -> dict:
    """scored: [(ticker, score)]. 점수 내림차순(동점은 티커 오름차순) 정렬 뒤 앞/뒤 ceil(frac·N)."""
    order = sorted(scored, key=lambda x: (-x[1], x[0]))
    n = math.ceil(frac * len(order))
    return {"top": [t for t, _ in order[:n]], "bottom": [t for t, _ in order[-n:]] if n else []}


def build_snapshot(date: str, rows: list, definition: dict, def_sha: str, panel_sha: dict) -> dict:
    """rows: 그 날짜의 패널 행들(fwd 등 미래 정보는 읽지 않는다). 반환: 스냅샷 1줄."""
    aw = definition["axisWeights"]
    pop = definition["population"]
    excl = {"notActive": 0, "tradingState": 0, "noFin": 0, "noValuation": 0, "noTechnical": 0}
    kept = []
    for r in rows:
        if r.get("listingStatus") != pop["listingStatus"]:
            excl["notActive"] += 1; continue
        if r.get("tradingState") != pop["tradingState"]:
            excl["tradingState"] += 1; continue
        if pop.get("requireFin") and r.get("fin") is None:
            excl["noFin"] += 1; continue
        c = r.get("c") or {}
        if c.get("valuation") is None:
            excl["noValuation"] += 1; continue
        if c.get("technical") is None:
            excl["noTechnical"] += 1; continue
        kept.append((r["t"], r["fin"], raw_axes(c, aw)))
    kept.sort(key=lambda x: x[0])
    models_out = {}
    for m in definition["models"]:
        scored = [(t, model_score(m, fin, ax)) for t, fin, ax in kept]
        assert all(s is not None for _, s in scored), "모집단 안에서 점수가 없는 종목이 있다"
        models_out[m["id"]] = select_lists(scored, definition["topFraction"])
    return {
        "date": date, "defSha256": def_sha, "panelFiles": panel_sha, "reference": False,
        "population": {"n": len(kept), "rowsInPanel": len(rows), "excluded": excl, "pitViolationExcluded": 0},
        "rows": [[t, ax.get("fundamental"), ax["valuation"], ax["technical"], fin] for t, fin, ax in kept],
        "models": models_out,
    }


# ---------------------------------------------------------------- 패널 읽기 (미래 정보는 즉시 버린다)
KEEP = ("t", "fin", "c", "listingStatus", "tradingState")


def read_panel_date(date: str):
    path = SCORES_DIR / f"{date[:4]}.jsonl.gz"
    rows = []
    with gzip.open(path, "rt", encoding="utf-8") as f:
        for i, line in enumerate(f):
            if i == 0:
                continue
            r = json.loads(line)
            if r["d"] == date:
                rows.append({k: r.get(k) for k in KEEP})   # fwd·fwdStatus·exit* 는 복사하지 않는다
    return rows, hashlib.sha256(path.read_bytes()).hexdigest()


def snapshot_days() -> list:
    return json.loads(CALENDAR.read_text(encoding="utf-8"))["snapshotDays"]


def existing_dates(path: Path, def_sha: str) -> set:
    if not path.exists():
        return set()
    out = set()
    for ln, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if not line.strip():
            continue
        r = json.loads(line)
        if r.get("defSha256") != def_sha:
            raise SystemExit(f"기존 스냅샷 {ln}번째 줄의 정의 해시가 현재와 다르다 - 중단")
        out.add(r["date"])
    return out


def append_snapshot(path: Path, snap: dict):
    """추가 전용 - 기존 바이트를 건드리지 않는다."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "a", encoding="utf-8", newline="\n") as f:
        f.write(json.dumps(snap, ensure_ascii=False, separators=(",", ":")) + "\n")


# ---------------------------------------------------------------- 명령
def cmd_snapshot():
    for p in (DEF_PATH, Path(__file__).resolve(), PREREG):
        if not committed_clean(p):
            print(f"{p.name} 가 커밋되지 않았거나 수정 중 - 스냅샷을 만들지 않는다")
            return 2
    definition = load_definition()
    def_sha = EXPECTED_DEF_SHA256
    have = existing_dates(SNAP_PATH, def_sha)
    last_panel = max(int(p.stem.split(".")[0]) for p in SCORES_DIR.glob("*.jsonl.gz"))
    todo = [d for d in snapshot_days() if d >= FREEZE_DATE and d not in have and int(d[:4]) <= last_panel]
    made = 0
    for d in todo:
        rows, sha = read_panel_date(d)
        if len(rows) < MIN_ROWS_PER_DATE:
            print(f"{d}: 패널 행 {len(rows)}개 - 아직 A5 가 이 날짜를 채우지 않았다(건너뜀)")
            continue
        snap = build_snapshot(d, rows, definition, def_sha, {str(d[:4]): sha})
        append_snapshot(SNAP_PATH, snap)
        made += 1
        print(f"{d}: 모집단 {snap['population']['n']} (패널 {len(rows)}) · 상위 {len(snap['models']['M0']['top'])}")
    print(f"추가 {made}건 / 대기 {len(todo) - made}건 / 기존 {len(have)}건")
    return 0


def cmd_dry_run(date: str, out: str):
    definition = load_definition()
    rows, sha = read_panel_date(date)
    snap = build_snapshot(date, rows, definition, EXPECTED_DEF_SHA256, {str(date[:4]): sha})
    snap["reference"] = True            # 참고 전용 - 정식 기록이 아니다
    outp = Path(out)
    if str(outp.resolve()).startswith(str(SHADOW_DIR.resolve())):
        raise SystemExit("--dry-run 은 스냅샷 디렉터리에 쓰지 않는다")
    outp.parent.mkdir(parents=True, exist_ok=True)
    outp.write_text(json.dumps(snap, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"dry-run {date}: 모집단 {snap['population']['n']} / 패널 {len(rows)} · 제외 {snap['population']['excluded']} -> {outp}")
    return 0


# ---------------------------------------------------------------- selftest
def selftest():
    def ok(cond, msg):
        if not cond:
            print("selftest 실패:", msg); sys.exit(1)

    aw = {"fundamental": 0.3, "valuation": 0.5, "technical": 0.2}
    # 1) 재정규화 역산 왕복: 축 원점수 -> 존재 축 가중 재정규화 기여도 -> raw 복원
    def forward(ax):
        s = sum(aw[a] for a in ax)
        return {a: round(ax[a] * aw[a] / s, 1) for a in ax}   # 패널 c 는 소수 1자리
    for ax in ({"fundamental": 60.0, "valuation": 40.0, "technical": 80.0}, {"valuation": 70.0, "technical": 30.0}):
        back = raw_axes(forward(ax), aw)
        ok(all(abs(back[a] - ax[a]) < 0.5 for a in ax), f"원점수 복원 {ax} -> {back}")   # 1자리 반올림 허용오차
    # 2) 정렬·동점·n
    sel = select_lists([("B", 1.0), ("A", 1.0), ("C", 0.5), ("D", 2.0), ("E", 0.1)], 0.2)
    ok(sel["top"] == ["D"] and sel["bottom"] == ["E"], f"top/bottom {sel}")
    sel = select_lists([(f"T{i:02d}", float(i % 3)) for i in range(11)], 0.2)   # ceil(2.2)=3, 동점은 티커 오름차순
    ok(len(sel["top"]) == 3 and sel["top"] == sorted(sel["top"]) == ["T02", "T05", "T08"], f"동점 규칙 {sel['top']}")
    # 3) 세 모델이 같은 모집단을 쓴다 + fwd 를 읽지 않는다(없어도, 독이 들어 있어도 같은 결과)
    definition = json.loads(DEF_PATH.read_text(encoding="utf-8"))
    def row(t, fin, c, **kw):
        r = {"t": t, "fin": fin, "c": c, "listingStatus": "ACTIVE", "tradingState": "NORMAL"}
        r.update(kw); return r
    rows = [row(f"{i:06d}", 50 + i, {"fundamental": 10 + i * 0.1, "valuation": 20 + i * 0.3, "technical": 8 + (i % 5)}) for i in range(25)]
    rows += [row("900001", 55, {"fundamental": 5.0, "valuation": None, "technical": 9.0}),            # 가치 없음 -> 제외
             row("900002", 55, {"fundamental": 5.0, "valuation": 9.0, "technical": 9.0}, listingStatus="DELISTED"),
             row("900003", 55, {"fundamental": 5.0, "valuation": 9.0, "technical": 9.0}, tradingState="HALTED"),
             row("900004", None, {"fundamental": 5.0, "valuation": 9.0, "technical": 9.0})]
    clean = build_snapshot("2026-10-09", rows, definition, "x", {})
    poisoned = build_snapshot("2026-10-09", [dict(r, fwd={"d20": 999}, fwdStatus={"d20": "OK"}) for r in rows], definition, "x", {})
    ok(clean == poisoned, "미래 수익률 필드가 결과에 영향을 준다")
    ok("fwd" not in json.dumps(clean), "스냅샷에 fwd 가 들어갔다")
    ok(clean["population"]["n"] == 25 and clean["population"]["excluded"] == {"notActive": 1, "tradingState": 1, "noFin": 1, "noValuation": 1, "noTechnical": 0},
       f"모집단 집계 {clean['population']}")
    pops = {m: len(v["top"]) for m, v in clean["models"].items()}
    ok(set(pops.values()) == {5}, f"세 모델의 상위 개수가 같아야 한다 {pops}")
    tickers = {r[0] for r in clean["rows"]}
    ok(all(set(v["top"]) <= tickers and set(v["bottom"]) <= tickers for v in clean["models"].values()), "목록이 모집단 밖 종목을 담았다")
    # 4) 정의 해시: CRLF/LF 같음, 내용이 달라지면 달라짐
    with tempfile.TemporaryDirectory() as td:
        a, b = Path(td) / "a.json", Path(td) / "b.json"
        a.write_bytes(b'{"x":1}\n'); b.write_bytes(b'{"x":1}\r\n')
        ok(sha256_lf(a) == sha256_lf(b), "CRLF 정규화")
        b.write_bytes(b'{"x":2}\n')
        ok(sha256_lf(a) != sha256_lf(b), "내용이 다르면 해시도 다르다")
        # 5) 추가 전용: 기존 바이트 불변, 정의 해시 불일치 거부
        sp = Path(td) / "snap.jsonl"
        append_snapshot(sp, {"date": "2026-10-09", "defSha256": "h"})
        before = sp.read_bytes()
        append_snapshot(sp, {"date": "2026-10-16", "defSha256": "h"})
        ok(sp.read_bytes().startswith(before), "기존 바이트가 바뀌었다")
        ok(existing_dates(sp, "h") == {"2026-10-09", "2026-10-16"}, "기존 날짜 읽기")
        try:
            existing_dates(sp, "other"); ok(False, "해시 불일치를 거부해야 한다")
        except SystemExit:
            pass
    # 6) 실제 정의 파일이 동결 해시와 같다
    ok(sha256_lf(DEF_PATH) == EXPECTED_DEF_SHA256, "정의 파일이 동결 해시와 다르다")
    ok(definition["freezeDate"] == FREEZE_DATE, "동결일 불일치")
    # 7) committed_clean: 추적되지 않는 파일은 거부
    ok(not committed_clean(HERE / "reports" / "__no_such_tracked_file__.tmp"), "추적 안 되는 파일을 clean 으로 본다")
    print("selftest OK - run_score_candidates_shadow")
    return 0


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--selftest", action="store_true")
    ap.add_argument("--snapshot", action="store_true")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--date")
    ap.add_argument("--out")
    a = ap.parse_args()
    if a.selftest:
        return selftest()
    if a.dry_run:
        if not (a.date and a.out):
            ap.error("--dry-run 은 --date 와 --out 이 필요하다")
        return cmd_dry_run(a.date, a.out)
    if a.snapshot:
        return cmd_snapshot()
    ap.print_help()
    return 1


if __name__ == "__main__":
    sys.exit(main())
