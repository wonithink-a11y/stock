#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""뉴스 그림자 — 기록 전용 (사전등록 findings/disclosure-news-score-ab-preregistration-2026-10.md §4).

docs/data/news.json 의 good/bad 기사(제목에 종목명이 든 국내 종목만)를 원자료 그대로 쌓는다.
git 이력(2026-07-20~, 6시간 간격 스냅샷)에서 PIT 로 복원하고 현재 파일을 더한다. 중복은 (종목, 링크)로 거른다.
사건 정의(거래일 매핑·5거래일 군집 제거)·수익률·판정은 여기서 하지 않는다 — 양쪽 방향 각 150건이 쌓인 뒤 1회(사전등록 §4).
점수·매매에 쓰지 않는다(절대 규칙 1).

    python research/strategy-lab/run_news_shadow.py
"""
import json
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[1]
OUT = HERE / "reports" / "2026-10-news-shadow" / "observations.jsonl"
NEWS = "docs/data/news.json"
KST = timezone(timedelta(hours=9))


def git(*a):
    return subprocess.run(["git", *a], cwd=REPO, capture_output=True, text=True, encoding="utf-8").stdout


def extract(d):
    """news.json dict → [(종목, 행 dict)] — 국내 종목, level != neutral, 제목에 종목명."""
    rows = []
    for t, v in (d.get("byTicker") or {}).items():
        if v.get("market") != "KR":
            continue
        for it in v.get("items", []):
            if it.get("level") in ("good", "bad") and v.get("name") and v["name"] in (it.get("title") or ""):
                p = datetime.fromisoformat(it["pubDate"].replace("Z", "+00:00")).astimezone(KST)
                rows.append({"ticker": t, "pubKST": p.strftime("%Y-%m-%dT%H:%M"), "level": it["level"],
                             "flags": it.get("flags", []), "link": it.get("originallink") or it.get("link"),
                             "title": (it.get("title") or "")[:80]})
    return rows


def main():
    seen, rows = set(), []
    if OUT.exists():
        for line in OUT.read_text(encoding="utf-8").splitlines():
            r = json.loads(line)
            seen.add((r["ticker"], r["link"]))
            rows.append(r)
    n0 = len(rows)
    hashes = git("log", "--format=%H", "--reverse", "--", NEWS).split()
    snaps = [json.loads(git("show", f"{h}:{NEWS}")) for h in hashes]
    snaps.append(json.loads((REPO / NEWS).read_text(encoding="utf-8")))
    for d in snaps:
        for r in extract(d):
            k = (r["ticker"], r["link"])
            if k not in seen:
                seen.add(k)
                rows.append(r)
    rows.sort(key=lambda r: (r["pubKST"], r["ticker"]))
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text("\n".join(json.dumps(r, ensure_ascii=False) for r in rows) + "\n", encoding="utf-8")
    good = sum(r["level"] == "good" for r in rows)
    print(f"스냅샷 {len(snaps)}개 · 새 기사 {len(rows) - n0}건 · 누적 {len(rows)}건 (good {good} · bad {len(rows) - good}) · "
          f"{rows[0]['pubKST'][:10] if rows else '-'} ~ {rows[-1]['pubKST'][:10] if rows else '-'} · 판정은 양쪽 각 150건(사건 기준) 이후 1회 — 그 전엔 기록만")
    return 0


if __name__ == "__main__":
    sys.exit(main())
