#!/usr/bin/env python
"""ui/data/findings.json 빌더 - Strategy Lab findings/*.md 색인(리서치랩 탭).
순수 로컬 파일 읽기, KIS·시크릿 무관. 본문 전체를 그대로 담는다(76개 파일
합계 ~620KB라 별도 지연로딩 없이 한 파일로 충분) - 오픈코드 UI가 로컬
정적서버 없이 file://로 열려도 findings 폴더를 따로 fetch할 필요가 없다.

track/verdict/conditions/reason/수치 필드는 build_findings_registry.py의
파서를 그대로 재사용한다(2026-08-30, Rule Discovery Lab 대시보드와 데이터
중복 문제 해소 - 두 파서가 따로 놀면 한쪽만 고치고 잊어버리는 drift가 생김).

  python build_ui_findings.py
"""
import glob
import json
import os
import re
import sys

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
FINDINGS_DIR = os.path.join(REPO_ROOT, "research", "strategy-lab", "findings")
OUT_PATH = os.path.join(REPO_ROOT, "ui", "data", "findings.json")

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from build_findings_registry import (  # noqa: E402
    parse_frontmatter, parse_conditions, parse_float, strip_quotes,
    infer_track, infer_verdict, infer_category, NUMERIC_FIELDS,
)


def main():
    entries = []
    for path in sorted(glob.glob(os.path.join(FINDINGS_DIR, "**", "*.md"), recursive=True)):
        text = open(path, encoding="utf-8").read()
        first_line = text.splitlines()[0] if text else ""
        m = re.match(r"#\s+(.+)", first_line)
        title = m.group(1) if m else os.path.basename(path)
        date_match = re.search(r"\((\d{4}-\d{2}-\d{2})\)", title) or re.search(r"-(\d{4}-\d{2})\.md$", path)
        date = date_match.group(1) if date_match else None

        fm = parse_frontmatter(text)
        entry = {
            "file": os.path.relpath(path, REPO_ROOT).replace("\\", "/"),
            "title": title,
            "date": (fm or {}).get("date", date),
            "bodyMarkdown": text,
            "category": infer_category(text),
        }
        if fm and fm.get("verdict") in ("KEEP", "HOLD", "REJECT", "UNCLASSIFIED"):
            entry["track"] = fm.get("track", infer_track(os.path.basename(path)))
            entry["verdict"] = fm["verdict"]
            entry["original_verdict"] = fm.get("original_verdict")
            entry["criteria_version"] = fm.get("criteria_version")
            entry["conditions"] = parse_conditions(fm.get("conditions"))
            entry["reason"] = strip_quotes(fm.get("reason"))
            for f in NUMERIC_FIELDS:
                entry[f] = parse_float(fm.get(f))
        else:
            entry["track"] = infer_track(os.path.basename(path))
            entry["verdict"] = infer_verdict(text)
            entry["original_verdict"] = None
            entry["criteria_version"] = None
            entry["conditions"] = None
            entry["reason"] = None
            for f in NUMERIC_FIELDS:
                entry[f] = None
        entries.append(entry)
    entries.sort(key=lambda e: e.get("date") or "", reverse=True)

    os.makedirs(os.path.dirname(OUT_PATH), exist_ok=True)
    with open(OUT_PATH, "w", encoding="utf-8") as f:
        json.dump({"count": len(entries), "findings": entries}, f, ensure_ascii=False, indent=2)
    print(f"저장: {OUT_PATH} ({len(entries)}건)")


if __name__ == "__main__":
    main()
