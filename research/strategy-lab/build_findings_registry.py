"""findings/*.md 전체를 스캔해 findings/_registry.jsonl을 만든다.

목적: Claude가 "뭘 이미 해봤는지" 확인하려고 findings 파일 수백 개를 다시
읽지 않아도 되게. 신규(2026-08-29 이후, frontmatter 있음) 파일은 정확히
읽고, 구 파일은 파일명/키워드로 best-effort 분류해 UNCLASSIFIED로 남긴다
(교훈57 - 모르는 것은 0이 아니다, 억지로 KEEP/REJECT를 지어내지 않는다).

사용법: python build_findings_registry.py [--findings-dir DIR]
"""
import argparse
import json
import re
from datetime import datetime, timezone
from pathlib import Path

TRACK_PREFIXES = [
    ("crypto", re.compile(r"^crypto[-_]", re.I)),
    ("macro", re.compile(r"^(macro|market-regime|vix)[-_]", re.I)),
    ("us", re.compile(r"^us[-_]", re.I)),
]

REJECT_KEYWORDS = ["기각", "반려", "채택 불가", "REJECT", "탈락", "폐기"]
KEEP_KEYWORDS = ["KEEP", "PASS", "채택(", "채택 확정", "채택되었"]
HOLD_KEYWORDS = ["판단보류", "보류", "HOLD", "연구 후보", "미확정", "미착수"]

NUMERIC_FIELDS = ["cagr", "sharpe", "mdd", "win_rate", "n", "t_stat"]
VALID_VERDICTS = ("KEEP", "HOLD", "REJECT", "UNCLASSIFIED")

FRONTMATTER_RE = re.compile(r"^---\s*\n(.*?)\n---\s*\n", re.S)
FIELD_RE = re.compile(
    r"^(track|factor|date|verdict|criteria_version|conditions|original_verdict|reason|"
    + "|".join(NUMERIC_FIELDS) + r"):\s*(.+?)\s*$",
    re.M,
)


def infer_track(name: str) -> str:
    for track, pat in TRACK_PREFIXES:
        if pat.match(name):
            return track
    return "kr"  # 이 저장소는 KR이 기본 - crypto/macro/us만 접두사로 걸러냄


def infer_verdict(text: str) -> str:
    head = text[:4000]  # 결론은 보통 앞쪽/끝쪽 - 앞부분만 봐도 대부분 잡힘, 전체는 findings가 길어 낭비
    tail = text[-2000:]
    scope = head + tail
    if any(k in scope for k in REJECT_KEYWORDS):
        return "REJECT"
    if any(k in scope for k in KEEP_KEYWORDS):
        return "KEEP"
    if any(k in scope for k in HOLD_KEYWORDS):
        return "HOLD"
    return "UNCLASSIFIED"


def parse_frontmatter(text: str):
    m = FRONTMATTER_RE.match(text)
    if not m:
        return None
    fields = dict(FIELD_RE.findall(m.group(1)))
    return fields or None


def strip_quotes(raw: str):
    """reason처럼 자유텍스트 필드는 YAML 관례상 큰따옴표로 감싸 쓰기 쉽다 -
    한 겹만 벗긴다(정규식 파서라 실제 YAML 인용해제는 안 함, 교훈57 - 못 벗기면 원문 그대로)."""
    if raw and len(raw) >= 2 and raw[0] == '"' and raw[-1] == '"':
        return raw[1:-1]
    return raw


def parse_conditions(raw: str):
    """frontmatter의 conditions 줄(JSON 배열 리터럴 한 줄)을 파싱. 형식이 안 맞으면
    억지로 고치지 않고 None - 교훈57, 모르는 것은 0이 아니다."""
    if not raw:
        return None
    try:
        parsed = json.loads(raw)
        return parsed if isinstance(parsed, list) else None
    except json.JSONDecodeError:
        return None


def parse_float(raw: str):
    if raw is None:
        return None
    try:
        return float(raw)
    except ValueError:
        return None


def build_entry(path: Path, findings_root: Path) -> dict:
    rel = path.relative_to(findings_root).as_posix()
    text = path.read_text(encoding="utf-8", errors="replace")
    mtime = datetime.fromtimestamp(path.stat().st_mtime, tz=timezone.utc).isoformat()
    fm = parse_frontmatter(text)
    if fm and fm.get("verdict") in VALID_VERDICTS:
        entry = {
            "file": rel,
            "track": fm.get("track", infer_track(path.name)),
            "verdict": fm["verdict"],
            "original_verdict": fm.get("original_verdict"),
            "date": fm.get("date"),
            "mtime": mtime,
            "criteria_version": fm.get("criteria_version"),
            "conditions": parse_conditions(fm.get("conditions")),
            "reason": strip_quotes(fm.get("reason")),
            "source": "frontmatter",
        }
        entry.update({f: parse_float(fm.get(f)) for f in NUMERIC_FIELDS})
        return entry
    entry = {
        "file": rel,
        "track": infer_track(path.name),
        "verdict": infer_verdict(text),
        "original_verdict": None,
        "date": None,
        "mtime": mtime,
        "criteria_version": None,
        "conditions": None,
        "reason": None,
        "source": "best_effort_keyword_scan",
    }
    entry.update({f: None for f in NUMERIC_FIELDS})
    return entry


def build_registry(findings_root: Path) -> list:
    """findings_root 아래 *.md 전체를 스캔해 entry 리스트를 반환 - 대시보드 서버(serve.py)가
    요청마다 이걸 호출해 재스캔한다."""
    return [
        build_entry(path, findings_root)
        for path in sorted(findings_root.rglob("*.md"))
    ]


def write_registry(entries: list, out_path: Path) -> None:
    with out_path.open("w", encoding="utf-8") as f:
        for e in entries:
            f.write(json.dumps(e, ensure_ascii=False) + "\n")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--findings-dir", default=str(Path(__file__).parent / "findings"))
    args = ap.parse_args()

    findings_root = Path(args.findings_dir)
    out_path = findings_root / "_registry.jsonl"

    entries = build_registry(findings_root)
    write_registry(entries, out_path)

    by_verdict = {}
    for e in entries:
        by_verdict[e["verdict"]] = by_verdict.get(e["verdict"], 0) + 1
    print(f"{len(entries)}개 파일 스캔 -> {out_path}")
    for v, c in sorted(by_verdict.items()):
        print(f"  {v}: {c}")


if __name__ == "__main__":
    main()
