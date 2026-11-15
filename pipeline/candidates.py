"""S2 후보 선별 — 규칙 CR-1.0 (docs/AGENT_SPEC.md §3.1, 사용자 GO 2026-11-15). 순수 함수.

입력은 점수 엔진 산출물(latest-v2.json)과 공시 위험 상태뿐이다. LLM 주석·관찰용 순위는 읽지 않는다
(scripts/test-pipeline-isolation.py 가 이 파일을 검사한다).
"""
from __future__ import annotations

from collections import Counter
from datetime import datetime
from typing import Dict, List, Tuple

from . import events as E

RULE = "CR-1.0"
N = 20
MAX_AGE_DAYS = 4          # ponytail: 달력일 기준(주말+휴일 하루). 긴 연휴 뒤 첫날은 후보를 건너뛴다 — 거래일 달력이 생기면 교체
BAD_FLAGS = {"MISSING_DATA", "PARTIAL_CALCULATION", "LOW_CONFIDENCE", "VERY_LOW_CONFIDENCE"}   # 엔진이 판정한 결과만 읽는다
PRODUCER = {"kind": "code", "name": "pipeline.candidates", "version": RULE}


def _flags(result: dict) -> set:
    return {f if isinstance(f, str) else str((f or {}).get("code")) for f in (result.get("flags") or [])}


def select(latest_v2: dict, input_sha256: str, states: Dict[str, dict], now: datetime, n: int = N,
           commit: str = "") -> Tuple[List[dict], dict]:
    """→ (CANDIDATE_SELECTED 기록들, 진단). states: ticker → data/state 의 상태(없으면 위험 없음)."""
    kr = [r for r in latest_v2.get("results") or [] if r.get("market") == "KR"]
    cutoffs = Counter(str((r.get("meta") or {}).get("dataCutoff")) for r in kr)
    diag = {"ruleVersion": RULE, "universe": len(kr), "eligible": 0, "candidates": 0, "asOf": None,
            "staleScoreSkip": False, "excluded": {}}
    as_of = max((c for c in cutoffs if c.isdigit() and len(c) == 8), default=None)
    if not as_of:
        diag["staleScoreSkip"] = True
        diag["why"] = "점수 파일에 dataCutoff 가 없다"
        return [], diag
    diag["asOf"] = as_of
    age = (now.date() - datetime.strptime(as_of, "%Y%m%d").date()).days
    if age > MAX_AGE_DAYS or age < 0:
        diag["staleScoreSkip"] = True
        diag["why"] = f"점수 기준일 {as_of} 이 실행일보다 {age}일 앞 — 낡은 점수로 후보를 내지 않는다"
        return [], diag

    excluded: Counter = Counter()
    rows = []
    for r in kr:
        res, meta = r.get("result") or {}, r.get("meta") or {}
        t, st = res.get("ticker"), states.get(res.get("ticker")) or {}
        fs = res.get("finalScore")
        why = ("ticker" if not (isinstance(t, str) and E.TICKER["KR"].match(t))
               else "stale" if str(meta.get("dataCutoff")) != as_of
               else "null-score" if not E._num(fs)                      # 모르는 것은 0 이 아니다
               else "trade-not-allowed" if res.get("tradeAllowed") is not True
               else "trading-state" if res.get("tradingState") != "NORMAL"
               else "risk-state" if (st.get("riskStates") or st.get("tradingState", "NORMAL") != "NORMAL"
                                     or st.get("listingStatus", "NORMAL") != "NORMAL")
               else "low-confidence" if (_flags(res) & BAD_FLAGS
                                         or not E._num((res.get("confidence") or {}).get("coverage")))
               else None)
        if why:
            excluded[why] += 1
        else:
            rows.append((res, meta))
    rows.sort(key=lambda x: (-x[0]["finalScore"], x[0]["ticker"]))      # 동률은 ticker 오름차순 — 결정적
    picked = rows[:n]
    at = now.strftime("%Y-%m-%dT%H:%M:%S+09:00")
    producer = {**PRODUCER, **({"commit": commit} if commit else {})}
    out = []
    for i, (res, meta) in enumerate(picked, 1):
        t = res["ticker"]
        sid = E.cand_id(as_of, RULE, t)
        out.append(E.make("CANDIDATE_SELECTED", event_id=sid, ticker=t, market="KR", occurred_at=at, as_of=as_of,
                          producer=producer, signal_id=sid, evidence_ids=[f"score:{as_of}:{t}", f"state:{t}"],
                          payload={"ruleVersion": RULE, "rank": i, "of": len(picked), "eligible": len(rows),
                                   "finalScore": res["finalScore"], "rawScore": res.get("rawScore"),
                                   "riskPenalty": res.get("riskPenalty"), "coverage": res["confidence"]["coverage"],
                                   "enginePolicies": meta.get("policies") or {}, "inputSha256": input_sha256}))
    diag.update(eligible=len(rows), candidates=len(out), excluded=dict(sorted(excluded.items())))
    return out, diag
