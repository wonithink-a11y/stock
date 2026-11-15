"""파이프라인 실행기 — GitHub Actions(pipeline.yml)만 data/pipeline/ 에 쓴다. 로컬은 --root 로 다른 곳에.

    python -m pipeline candidates [--root DIR] [--now 2026-11-16T20:45:00]
    python -m pipeline agents     [--root DIR] [--max N] [--model M]      (GEMINI_API_KEY 없으면 건너뛴다)
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


def _json(path: Path):
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else None


def cmd_agents(a, now):
    """오늘 뽑힌 후보에만 주석을 단다 — 지난 후보를 소급하지 않는다(다음 날 쓴 논리는 다음 날 정보를 본 것이다)."""
    from . import agents as A
    from . import bundle as B
    day = now.strftime("%Y-%m-%d")
    log = E.read(a.root / "events")
    cands = sorted((e for e in log if e["type"] == "CANDIDATE_SELECTED" and e["occurredAt"][:10] == day),
                   key=lambda e: e["payload"]["rank"])
    key = A.dg.load_env().get("GEMINI_API_KEY")
    if not cands or not key:
        diag = {"candidates": len(cands), "noKey": not key, "skipped": True}
        diag_update(a.root, now.strftime("%Y%m%d"), "agents", diag)
        print(json.dumps(diag, ensure_ascii=False))
        return
    data = ROOT / "docs" / "data"
    results = {r["result"]["ticker"]: r for r in _json(data / "latest-v2.json")["results"] if r.get("market") == "KR"}
    prices, rank = (_json(data / "prices.json") or {}).get("byTicker") or {}, _json(data / "rank-h5.json")
    bundles, usable = {}, []
    for c in cands:
        t, r = c["ticker"], results.get(c["ticker"])
        if not r or str(r["meta"].get("dataCutoff")) != c["asOf"]:
            continue                                            # 점수 파일이 후보 뒤에 바뀌었다 — 다른 기준일의 글을 붙이지 않는다
        f = a.root / "bundles" / c["asOf"] / f"{t}.json"
        if f.exists():                                          # 묶음은 만든 그대로 둔다(다시 만들지 않는다)
            b = _json(f)
        else:
            hist = [json.loads(x) for h in (ROOT / "data" / "state-history").glob(f"*/{t}.jsonl")
                    for x in h.read_text(encoding="utf-8").splitlines() if x.strip()]
            b = B.build(c, result=r["result"], decode=_json(data / "decode" / f"{t}.json"),
                        state=_json(ROOT / "data" / "state" / f"{t}.json"), history=hist, prices=prices.get(t), rank_h5=rank)
            f.parent.mkdir(parents=True, exist_ok=True)
            f.write_text(json.dumps(b, ensure_ascii=False, indent=1) + "\n", encoding="utf-8", newline="\n")
        bundles[c["eventId"]] = b
        usable.append(c)
    evs, diag = A.run(usable, bundles, {e["eventId"] for e in log},
                      call=lambda text, schema: A.dg.gemini(text, key, a.model, schema=schema, temperature=0)[0],
                      now=lambda: datetime.now(KST).strftime("%Y-%m-%dT%H:%M:%S+09:00"), model=a.model,
                      commit=os.environ.get("GITHUB_SHA", "")[:7], max_n=a.max)
    diag.update(E.append(evs, a.root / "events"), bundleSkipped=len(cands) - len(usable))
    diag_update(a.root, now.strftime("%Y%m%d"), "agents", diag)
    print(json.dumps(diag, ensure_ascii=False))


def main(argv=None):
    ap = argparse.ArgumentParser(prog="pipeline")
    ap.add_argument("cmd", choices=["candidates", "agents"])
    ap.add_argument("--max", type=int, default=20, help="주석을 달 후보 수 상한(무료 한도 보호)")
    ap.add_argument("--model", default="gemini-3.5-flash-lite")
    ap.add_argument("--root", type=Path, default=ROOT / "data" / "pipeline")
    ap.add_argument("--now", help="KST 시각(시험용). 기본은 지금")
    a = ap.parse_args(argv)
    now = datetime.fromisoformat(a.now).replace(tzinfo=KST) if a.now else datetime.now(KST)
    {"candidates": cmd_candidates, "agents": cmd_agents}[a.cmd](a, now)


if __name__ == "__main__":
    sys.exit(main())
