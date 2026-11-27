"""화면용 파생 파일 docs/data/pipeline/latest.json — 로그에서 매번 전체를 다시 접는다(증분 갱신 없음). 계약: docs/AGENT_SPEC.md §9.

시각 필드가 없다 — 로그가 같으면 바이트가 같다. 갈래별 평균 수익은 싣지 않는다(판정 전 중간 성과 비열람), 건수만.
"""
from __future__ import annotations

from collections import Counter
from typing import Dict, List

from . import events as E

RECENT_RUNS = 60     # 최근 60번 실행 안에 시작한 사건만 싣는다
NOTE = "관찰용 — 논리·반증은 LLM 주석이고 점수·후보 선별·주문에 쓰이지 않는다. 인용은 코드가 근거 묶음과 대조해 통과한 것만."


def ex_group(latest_v2: dict, groups: Dict[str, str], states: Dict[str, dict], now, as_of: str,
             group: str = "금융", n: int = 20) -> List[dict]:
    """화면 전용 보조 목록 — 업종 `group`(sector-strength 의 g) 을 뺀 점수 상위 n. 후보(CR-1.0)·주석·평가에 닿지 않는다.

    적격 기준은 후보 규칙과 같다(C.select 를 그대로 쓴다). 후보 기준일이 `as_of` 와 다르면 빈 목록 —
    다른 날 점수를 오늘 목록에 섞지 않는다. 업종을 모르는 종목은 빼지 않는다(모르는 것은 금융이 아니다) — group 이 None 으로 남는다.
    """
    from . import candidates as C
    evs, _ = C.select(latest_v2, "", states, now, n=10 ** 6)
    if not evs or evs[0]["asOf"] != as_of:
        return []
    rows = [e for e in evs if groups.get(e["ticker"]) != group]
    return [{"rank": i, "overallRank": e["payload"]["rank"], "ticker": e["ticker"], "finalScore": e["payload"]["finalScore"],
             "group": groups.get(e["ticker"]), "inTop20": e["payload"]["rank"] <= C.N}
            for i, e in enumerate(rows[:n], 1)]


def build(log: List[dict], names: Dict[str, str]) -> dict:
    cands = [e for e in log if e["type"] == "CANDIDATE_SELECTED"]
    if not cands:
        return {"asOf": None, "note": NOTE, "today": [], "episodes": [], "counts": {}}
    runs = sorted({c["asOf"] for c in cands})
    starts, folded = E.episode_starts(cands), E.fold(log)
    latest, since = runs[-1], runs[-RECENT_RUNS:][0]
    start_of = {}                                                 # ticker → 진행 중 사건의 signalId(가장 최근 시작)
    for c in sorted(cands, key=lambda c: c["asOf"]):
        if c["eventId"] in starts:
            start_of[c["ticker"]] = c["eventId"]
    today = [{"ticker": c["ticker"], "name": names.get(c["ticker"], ""), "rank": c["payload"]["rank"],
              "finalScore": c["payload"]["finalScore"], "signalId": c["eventId"], "isNew": c["eventId"] in starts,
              "episodeSignalId": start_of.get(c["ticker"])}
             for c in sorted((c for c in cands if c["asOf"] == latest), key=lambda c: c["payload"]["rank"])]
    eps, flags, kinds, prefixes, status = [], Counter(), Counter(), Counter(), Counter()
    for sid in sorted(starts):
        f = folded[sid]
        c, th, rb = f["candidate"], (f["thesis"] or [None])[0], (f["rebuttal"] or [None])[0]
        flags[rb["payload"]["flag"] if rb else "미기록"] += 1
        for i in (rb["payload"]["invalidations"] if rb else []):
            kinds[i["check"]["kind"]] += 1
        for x in (th["payload"]["claims"] if th else []):
            prefixes[x["evidenceId"].split(":")[0]] += 1
        for o in f["outcomes"].values():
            status[f"h{o['payload']['horizon']}:{o['payload']['status']}"] += 1
        if c["asOf"] < since:
            continue
        hit = {i["payload"]["invalidationId"]: i for i in f["invalidations"]}
        eps.append({
            "signalId": sid, "ticker": c["ticker"], "name": names.get(c["ticker"], ""), "asOf": c["asOf"],
            "rank": c["payload"]["rank"], "finalScore": c["payload"]["finalScore"],
            "thesis": th and {"eventId": th["eventId"], "model": th["producer"]["model"], "summary": th["payload"]["summary"],
                              "claims": th["payload"]["claims"],
                              "verification": {k: th["payload"]["verification"][k] for k in ("claimsTotal", "claimsKept")}},
            "rebuttal": rb and {"eventId": rb["eventId"], "flag": rb["payload"]["flag"], "counters": rb["payload"]["counters"],
                                "invalidations": [{**i, "triggeredAt": hit[i["id"]]["occurredAt"][:10] if i["id"] in hit else None,
                                                   "observed": hit[i["id"]]["payload"]["observed"] if i["id"] in hit else None}
                                                  for i in rb["payload"]["invalidations"]]},
            "outcomes": {f"h{h}": {k: o["payload"][k] for k in ("entryDate", "exitDate", "ret", "benchRet", "excess", "status")}
                         for h, o in sorted(f["outcomes"].items())}})
    eps.sort(key=lambda e: (e["asOf"], -e["rank"]), reverse=True)
    return {"asOf": latest, "note": NOTE, "today": today, "episodes": eps,
            "counts": {"runs": len(runs), "candidates": len(cands), "episodes": len(starts), "flags": dict(sorted(flags.items())),
                       "invalidationKinds": dict(sorted(kinds.items())), "claimEvidence": dict(sorted(prefixes.items())),
                       "triggered": sum(len(folded[s]["invalidations"]) for s in starts), "outcomes": dict(sorted(status.items()))}}
