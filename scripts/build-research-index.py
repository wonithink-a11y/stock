#!/usr/bin/env python3
"""연구 결과 목록 → docs/data/research-index.json (대시보드 '연구 목록' 탭용).
research/strategy-lab/findings/_registry.jsonl 이 정본이다(build_findings_registry.py 가 만든다). 판정이 선언된 결과만 담고,
사전등록 문서·미분류는 개수만 센다. 맥락·기록 전용 — 점수·매매 불사용(절대 규칙 1).

    python scripts/build-research-index.py            # 쓰기
    python scripts/build-research-index.py --selftest
"""
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
REG = ROOT / "research" / "strategy-lab" / "findings" / "_registry.jsonl"
OUT = ROOT / "docs" / "data" / "research-index.json"

OK = {"ROBUST", "ECONOMIC", "PASS", "CONFIRMED", "EXECUTABLE", "CONSISTENT", "KEEP", "GO", "근거 유지", "SUPPORTED"}
NO = {"REJECT", "NONE", "REVERSE", "FAIL", "NOT SUPPORTED", "편향 큼"}
INFO = {"INFORMATION", "INFORMATION-ONLY", "EXPLORATORY", "RECORD-ONLY", "REFERENCE", "DRAFT", "DATA_PATH_CONFIRMED", "요약 문서 신뢰도 높음"}
SKIP = {"PREREGISTERED", "UNCLASSIFIED"}


def kind(v):
    if v in OK:
        return "ok"
    if v in NO:
        return "no"
    if v in INFO:
        return "info"
    return "mid"   # INCONCLUSIVE·HOLD·판정 불가·MIXED·SENSITIVE·CAUTION·PENDING …


def title(f):
    t = re.sub(r"\.md$", "", f)
    t = re.sub(r"-(results|result)?-?20\d\d-\d\d$", "", t)
    return t


def build(rows):
    items, skipped = [], {"PREREGISTERED": 0, "UNCLASSIFIED": 0}
    for r in rows:
        v = r.get("verdict") or ""
        if v in SKIP:
            skipped[v] += 1
            continue
        reason = re.sub(r"\s+", " ", (r.get("reason") or "")).strip()
        items.append(dict(f=r["file"], t=title(r["file"]), d=r.get("date") or "", v=v, k=kind(v), tr=r.get("track") or "", s=reason[:230]))
    items.sort(key=lambda x: x["d"], reverse=True)
    return dict(n=len(items), prereg=skipped["PREREGISTERED"], unclassified=skipped["UNCLASSIFIED"], items=items)


def selftest():
    assert kind("ROBUST") == "ok" and kind("REJECT") == "no" and kind("INCONCLUSIVE") == "mid" and kind("EXPLORATORY") == "info"
    assert title("condition-grid-l3-results-2026-11.md") == "condition-grid-l3"
    d = build([dict(file="a-results-2026-11.md", verdict="REJECT", date="2026-11-01", reason="x  y"), dict(file="b.md", verdict="PREREGISTERED")])
    assert d["n"] == 1 and d["prereg"] == 1 and d["items"][0]["s"] == "x y"
    print("OK")


def main():
    if "--selftest" in sys.argv:
        return selftest()
    rows = [json.loads(l) for l in REG.read_text(encoding="utf-8").splitlines() if l.strip()]
    d = build(rows)
    OUT.write_text(json.dumps(d, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    print(f"research-index.json: 결과 {d['n']}건 (사전등록 {d['prereg']} · 미분류 {d['unclassified']} 제외) {OUT.stat().st_size // 1024}KB")


if __name__ == "__main__":
    main()
