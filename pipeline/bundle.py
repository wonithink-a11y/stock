"""S3-a 근거 묶음(BN-1.0) — LLM 이 보는 글의 전부. 순수 함수. 계약: docs/AGENT_SPEC.md §3.2.

숫자는 전부 코드가 계산해 글로 넣는다. 뉴스 본문·증권사 목표가·보유 정보는 넣지 않는다(절 종류가 닫힌 목록).
묶음은 나중에 재현할 수 없으므로(입력 파일이 매일 바뀐다) 만든 그대로 보관한다.
"""
from __future__ import annotations

import hashlib
import json
from datetime import datetime, timedelta
from typing import List, Optional

VERSION = "BN-1.0"
KINDS = ("score", "filing", "filing-title", "risk-state", "price", "context", "note")
MAX_FILING = 30
MAX_TITLES = 15
AXIS_KO = {"fundamental": "재무", "valuation": "가치", "technical": "기술", "supplyDemand": "수급"}


def _sec(eid: str, kind: str, text: str) -> dict:
    assert kind in KINDS
    return {"evidenceId": eid, "kind": kind, "text": text}


def _fmt(x) -> str:
    return f"{x:,.0f}" if abs(x) >= 1000 else f"{x:.1f}"


def price_facts(px: Optional[dict], as_of: str) -> Optional[str]:
    """기준일까지의 일봉으로 가격 사실 한 줄. 60일치가 안 되면 None(모르는 것을 지어내지 않는다)."""
    if not px:
        return None
    rows = [(d, h, l, c) for d, h, l, c in zip(px.get("d") or [], px.get("h") or [], px.get("l") or [], px.get("c") or [])
            if d <= as_of and c]
    if len(rows) < 61 or rows[-1][0] != as_of:
        return None
    c = [r[3] for r in rows]
    hi, lo = max(r[1] for r in rows), min(r[2] for r in rows)
    tr = [max(rows[i][1] - rows[i][2], abs(rows[i][1] - c[i - 1]), abs(rows[i][2] - c[i - 1])) for i in range(-14, 0)]
    pos = (c[-1] - lo) / (hi - lo) * 100 if hi > lo else None
    out = (f"기준일 {as_of} 종가 {_fmt(c[-1])}. 20일 평균 종가 {_fmt(sum(c[-20:]) / 20)}, 60일 평균 종가 {_fmt(sum(c[-60:]) / 60)}. "
           f"최근 20거래일 수익률 {(c[-1] / c[-21] - 1) * 100:.1f}%. 14일 평균 변동폭 {_fmt(sum(tr) / 14)}.")
    if pos is not None:
        out += f" 최근 {len(rows)}거래일 고가 {_fmt(hi)}·저가 {_fmt(lo)} 사이 위치 {pos:.0f}%."
    return out


def build(cand: dict, *, result: dict, decode: Optional[dict], state: Optional[dict], history: List[dict],
          prices: Optional[dict], rank_h5: Optional[dict] = None) -> dict:
    """cand: CANDIDATE_SELECTED 기록. result: latest-v2 의 그 종목 result. history: 공시 이벤트(EV-1.0) 목록."""
    t, as_of = cand["ticker"], cand["asOf"]
    p = cand["payload"]
    secs = []
    comp = " · ".join(f"{AXIS_KO.get(k, k)} {v}" for k, v in (result.get("components") or {}).items() if v is not None)
    top = " · ".join(f"{AXIS_KO.get(f['factor'], f['factor'])} {f['impact']:+}" for f in (result.get("topFactors") or [])
                     if f.get("impact") is not None)
    secs.append(_sec(f"score:{as_of}:{t}", "score",
                     f"최종 점수 {p['finalScore']} = 원점수 {p['rawScore']} − 위험 감점 {p['riskPenalty']}. "
                     f"적격 {p['eligible']}종목 중 {p['rank']}위. 축별 점수: {comp or '없음'}. "
                     f"점수 기여(평균 대비): {top or '없음'}. 데이터 커버리지 {p['coverage']}%."))
    items = [i for i in ((decode or {}).get("items") or []) if i.get("quote")][:MAX_FILING]
    if items:
        for n, i in enumerate(items):
            secs.append(_sec(f"decode:{t}:{decode['rceptNo']}#{n:02d}", "filing",
                             f"({decode.get('reportNm', '').strip()}) {i['quote']}"))
    else:
        secs.append(_sec(f"ctx:no-filing:{as_of}:{t}", "note", "공시 해독 없음 — 사업보고서 원문 인용이 이 묶음에 없다."))
    since = (datetime.strptime(as_of, "%Y%m%d") - timedelta(days=60)).strftime("%Y-%m-%d")
    seen = set()
    for ev in sorted(history, key=lambda e: e.get("sortKey", ""), reverse=True):
        no, day = (ev.get("payload") or {}).get("rceptNo"), (ev.get("occurredAt") or "")[:10]
        if not no or no in seen or not (since <= day <= f"{as_of[:4]}-{as_of[4:6]}-{as_of[6:]}"):
            continue
        seen.add(no)
        secs.append(_sec(f"dart:{no}", "filing-title", f"{day} 공시: {(ev['payload'].get('reportNm') or '').strip()}"))
        if len(seen) >= MAX_TITLES:
            break
    risks = (state or {}).get("riskStates") or []
    secs.append(_sec(f"state:{t}", "risk-state", "공시 위험 상태: " + (", ".join(risks) if risks else "없음") + "."))
    pf = price_facts(prices, as_of)
    secs.append(_sec(f"px:{as_of}:{t}", "price", pf) if pf
                else _sec(f"ctx:no-price:{as_of}:{t}", "note", "가격 사실 없음 — 기준일까지의 일봉이 부족하다."))
    rk = ((rank_h5 or {}).get("byTicker") or {}).get(t)
    rk_day = str((rank_h5 or {}).get("asOf") or "").replace("-", "")
    if rk and rk_day and rk_day <= as_of:                       # 기준일보다 뒤의 자료는 넣지 않는다
        secs.append(_sec(f"ctx:rank-h5:{rk_day}:{t}", "context",
                         f"5거래일 상대수익 예측 모델 백분위 {rk[0]} (관찰용 — 점수·후보 선별에 쓰이지 않는다)."))
    sha = hashlib.sha256(json.dumps(secs, ensure_ascii=False, sort_keys=True).encode("utf-8")).hexdigest()
    return {"bundleVersion": VERSION, "ticker": t, "name": result.get("name") or "", "asOf": as_of,
            "signalId": cand["eventId"], "sections": secs, "sha256": sha}


def render(b: dict) -> str:
    """LLM 에 주는 글 — 절마다 '[근거 id] 본문'."""
    return "\n".join(f"[{s['evidenceId']}] {s['text']}" for s in b["sections"])
