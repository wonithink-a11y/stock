"""파이프라인 실행기 — GitHub Actions(pipeline.yml)만 data/pipeline/ 에 쓴다. 로컬은 --root 로 다른 곳에.

    python -m pipeline candidates [--root DIR] [--now 2026-11-16T20:45:00]
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

from . import candidates as C
from . import events as E

ROOT = Path(__file__).resolve().parent.parent
KST = timezone(timedelta(hours=9))


def diag_update(root: Path, day: str, section: str, data: dict) -> None:
    """data/pipeline/diagnostics/{날짜}.json 의 한 칸을 덮어쓴다. 후보 0건이어도 쓴다('안 돌았다'와 '없다'를 가른다)."""
    p = Path(root) / "diagnostics" / f"{day}.json"
    p.parent.mkdir(parents=True, exist_ok=True)
    d = json.loads(p.read_text(encoding="utf-8")) if p.exists() else {}
    d[section] = data
    p.write_text(json.dumps(d, ensure_ascii=False, indent=1, sort_keys=True) + "\n", encoding="utf-8", newline="\n")


def load_states() -> dict:
    out = {}
    for f in (ROOT / "data" / "state").glob("*.json"):
        out[f.stem] = json.loads(f.read_text(encoding="utf-8"))
    return out


def cmd_candidates(a, now):
    raw = (ROOT / "docs" / "data" / "latest-v2.json").read_bytes()
    evs, diag = C.select(json.loads(raw), hashlib.sha256(raw).hexdigest(), load_states(), now,
                         commit=os.environ.get("GITHUB_SHA", "")[:7])
    diag.update(E.append(evs, a.root / "events"), runAt=now.strftime("%Y-%m-%dT%H:%M:%S+09:00"))
    diag_update(a.root, now.strftime("%Y%m%d"), "candidates", diag)
    print(json.dumps(diag, ensure_ascii=False))


def main(argv=None):
    ap = argparse.ArgumentParser(prog="pipeline")
    ap.add_argument("cmd", choices=["candidates"])
    ap.add_argument("--root", type=Path, default=ROOT / "data" / "pipeline")
    ap.add_argument("--now", help="KST 시각(시험용). 기본은 지금")
    a = ap.parse_args(argv)
    now = datetime.fromisoformat(a.now).replace(tzinfo=KST) if a.now else datetime.now(KST)
    {"candidates": cmd_candidates}[a.cmd](a, now)


if __name__ == "__main__":
    sys.exit(main())
