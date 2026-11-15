"""S5 사후 평가 — 사건(후보 첫 날)의 5·20·60거래일 수익. 순수 함수. 계약: docs/AGENT_SPEC.md §3.6 · docs/VALIDATION.md §2.

- 진입 = 기록을 만든 날 **다음 거래일 종가**(후보는 저녁에 나온다 — 당일 종가는 살 수 없다).
- 기준 수익 = 같은 기간 관심종목(KR) 동일가중 평균. 저장소에 코스피·코스닥 지수 일별 시세가 없고,
  "뽑힌 20개가 뽑히지 않은 나머지보다 나았나"가 선별의 값을 묻는 질문이다.
- 비용 왕복 33.5bp 고정. 거래량 0(정지)·시세 없음은 ret 을 비운다(0 으로 채우지 않는다).
- 갈래별 평균은 여기서 내지 않는다 — 사전등록 판정 전에 중간 성과를 보지 않는다(judge 는 P6 등록 뒤에 연다).
"""
from __future__ import annotations

from typing import Dict, List, Optional

from . import events as E

COST_BP = 33.5
BENCHMARK = "KR_WATCHLIST_EW"
CALENDAR_TICKER = "005930"      # ponytail: 거래일 달력을 이 종목의 일봉 날짜로 삼는다. 이 종목이 정지되면 달력이 비니 그때 교체
PRODUCER = {"kind": "code", "name": "pipeline.outcomes", "version": "OC-1.0"}


def _series(px: Optional[dict]) -> Dict[str, tuple]:
    if not px:
        return {}
    days = px.get("d") or []
    return dict(zip(days, zip(px.get("c") or [], px.get("v") or [None] * len(days))))


def _r6(v):
    return None if v is None else round(v, 6)


def measure(cand: dict, prices: Dict[str, dict], at: str, done: set, commit: str = "") -> List[dict]:
    """한 사건의 만기 도래분 OUTCOME_MEASURED. done: 이미 로그에 있는 eventId(다시 재지 않는다)."""
    cal = (prices.get(CALENDAR_TICKER) or {}).get("d") or []
    after = [d for d in cal if d > cand["occurredAt"][:10].replace("-", "")]
    todo = [h for h in E.HORIZONS if E.out_id(cand["eventId"], h) not in done and len(after) > h]
    if not todo:
        return []
    entry, t = after[0], cand["ticker"]
    mine = _series(prices.get(t))
    kr = [_series(p) for p in prices.values() if p.get("market") == "KR"]
    out = []
    for h in todo:
        exit_ = after[h]
        e, x = mine.get(entry), mine.get(exit_)
        status = "no-price" if not (e and x and e[0] and x[0]) else "halted" if e[1] == 0 or x[1] == 0 else "ok"
        bench = [b[0] / a[0] - 1 for a, b in ((s.get(entry), s.get(exit_)) for s in kr)
                 if a and b and a[0] and b[0] and a[1] != 0 and b[1] != 0]
        bret = sum(bench) / len(bench) if bench else None
        ret = x[0] / e[0] - 1 if status == "ok" else None
        ex = ret - bret if ret is not None and bret is not None else None
        out.append(E.make("OUTCOME_MEASURED", event_id=E.out_id(cand["eventId"], h), ticker=t, market=cand["market"],
                          occurred_at=at, as_of=exit_, producer={**PRODUCER, **({"commit": commit} if commit else {})},
                          signal_id=cand["eventId"], evidence_ids=[f"px:{exit_}:{t}"],
                          payload={"horizon": h, "entryDate": entry, "exitDate": exit_, "entryPx": e[0] if e else None,
                                   "exitPx": x[0] if x else None, "ret": _r6(ret), "benchmark": BENCHMARK,
                                   "benchRet": _r6(bret), "excess": _r6(ex), "costBp": COST_BP,
                                   "netExcess": _r6(None if ex is None else ex - COST_BP / 1e4), "status": status}))
    return out


def judge(*_a, **_k):
    """사전등록(P6) 전에는 판정하지 않는다. 등록 뒤 그 파일의 조건으로만 연다."""
    raise SystemExit("판정 잠김 — 반증 가치 forward 사전등록(docs/VALIDATION.md §3) 전이다. 건수는 docs/data/pipeline/latest.json 의 counts.")
