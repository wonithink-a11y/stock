#!/usr/bin/env python3
"""점수 불반영 격리 회귀(docs/AGENT_SPEC.md §5 겹 3) — 점수·선별 코드는 주석 로그를 읽을 수 없다.

절대 규칙 1: 논리·반증(LLM 주석)은 맥락용이다. 점수·후보 선별 소스에 주석 로그 경로나 주석 타입이 나타나면 실패한다.
대상 파일이 없어도 실패한다(조용히 건너뛰면 이 검사는 늘 초록이 된다).

    python scripts/test-pipeline-isolation.py
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

# 점수 엔진 쪽: 파이프라인 자체를 몰라야 한다
SCORING = ["lib/scoringEngine.js", "lib/validator.js", "scripts/analyze.js", "scripts/build-rank-h5.py"]
SCORING_BANNED = ["pipeline/events", "data/pipeline", "pipeline.events", "agent-events", "THESIS_", "REBUTTAL_",
                  "contextOnly"]
# 후보 선별: 로그에 '쓰기'는 하지만 주석을 '읽기'는 못 한다
SELECT = ["pipeline/candidates.py"]
SELECT_BANNED = ["THESIS_", "REBUTTAL_", "events.read", "E.read", "fold(", "bundles", "rank-h5", "decode"]

failed = 0
for files, banned, required in ((SCORING, SCORING_BANNED, True), (SELECT, SELECT_BANNED, False)):
    for rel in files:
        p = ROOT / rel
        if not p.exists():
            if required or (ROOT / "pipeline" / "candidates.py").exists():
                failed += 1
                print(f"  FAIL 대상 파일 없음: {rel}")
            continue                                   # pipeline/candidates.py 는 P2 에서 생긴다 — 생기면 반드시 검사된다
        src = p.read_text(encoding="utf-8")
        for s in banned:
            if s in src:
                failed += 1
                print(f"  FAIL {rel} 에 {s!r} — 주석이 점수·선별로 새는 길")

print(f"test-pipeline-isolation: {'FAIL ' + str(failed) if failed else 'ok'}")
sys.exit(1 if failed else 0)
