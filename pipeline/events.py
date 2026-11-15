"""파이프라인 기록(AE-1.0) — 봉투·payload 검증, 결정적 id·sortKey, 추가 전용 로그. 순수 함수 + 파일 쓰기 하나.

계약: docs/AGENT_SPEC.md §1~§4 · 근거: docs/ARCHITECTURE.md §3.
- 멱등은 커서가 아니라 eventId 중복 거부다(여러 단계가 다른 시각에 쓴다 — 늦게 온 기록도 쓰인다).
- 검증에 하나라도 실패하면 아무것도 쓰지 않는다. 파생 상태는 저장하지 않고 fold() 로 읽을 때 접는다.
- 논리·반증(LLM) 기록은 contextOnly=true 여야 하고 선언 안 된 payload 키는 거부한다(점수로 새는 칸이 없다).
"""
from __future__ import annotations

import json
import os
import re
from pathlib import Path
from typing import Dict, Iterable, List, Optional

SCHEMA = "AE-1.0"
ROOT = Path(__file__).resolve().parent.parent
EVENTS_DIR = ROOT / "data" / "pipeline" / "events"

# type → (sourceTeam, sortKey 단계, 필수 payload 키)
TYPES = {
    "CANDIDATE_SELECTED": ("scoring", "20", ("ruleVersion", "rank", "of", "eligible", "finalScore", "rawScore",
                                             "riskPenalty", "coverage", "enginePolicies", "inputSha256")),
    "THESIS_WRITTEN": ("thesis", "30", ("bundleSha256", "claims", "summary", "verification")),
    "REBUTTAL_WRITTEN": ("rebuttal", "40", ("bundleSha256", "thesisEventId", "counters", "invalidations", "flag",
                                            "verification")),
    "INVALIDATION_TRIGGERED": ("monitor", "50", ("rebuttalEventId", "invalidationId", "check", "observed",
                                                 "daysSinceSignal")),
    "OUTCOME_MEASURED": ("eval", "60", ("horizon", "entryDate", "exitDate", "entryPx", "exitPx", "ret", "benchmark",
                                        "benchRet", "excess", "costBp", "netExcess", "status")),
}
LLM_TEAMS = ("thesis", "rebuttal")
ENVELOPE = ("eventSchemaVersion", "eventId", "ticker", "market", "type", "occurredAt", "sortKey", "asOf", "sourceTeam",
            "source", "producer", "signalId", "evidenceIds", "contextOnly", "payload")
EVIDENCE_PREFIXES = ("score", "state", "dart", "decode", "px", "ctx", "news", "thesis", "rebut", "cand")
TICKER = {"KR": re.compile(r"^[0-9A-Z]{6}$"), "US": re.compile(r"^[A-Z.\-]{1,10}$")}
_AT = re.compile(r"^(\d{4})-(\d\d)-(\d\d)T(\d\d):(\d\d):(\d\d)\+09:00$")
FLAGS = ("none", "caution", "thesis-weak")
CLAIM_KEYS = {"id", "kind", "claim", "quote", "evidenceId"}
COUNTER_KEYS = {"id", "targets", "claim", "quote", "evidenceId"}
OUTCOME_STATUS = ("ok", "halted", "delisted", "no-price")
HORIZONS = (5, 20, 60)


# ------------------------------------------------------------------ 무효 조건(닫힌 목록)
def _num(v) -> bool:
    return isinstance(v, (int, float)) and not isinstance(v, bool)


CHECKS = {
    "risk-state-added": lambda c: True,
    "score-below": lambda c: _num(c.get("value")),
    "close-below-ma": lambda c: c.get("ma") in (20, 60, 120) and isinstance(c.get("days"), int) and 1 <= c["days"] <= 10,
    "drawdown-from-signal": lambda c: _num(c.get("pct")) and 0 < c["pct"] < 100,
    "candidate-dropped": lambda c: isinstance(c.get("days"), int) and 1 <= c["days"] <= 60,
    "manual": lambda c: True,
}
CHECK_PARAMS = {"risk-state-added": (), "score-below": ("value",), "close-below-ma": ("ma", "days"),
                "drawdown-from-signal": ("pct",), "candidate-dropped": ("days",), "manual": ()}


def check_ok(check) -> bool:
    if not isinstance(check, dict) or check.get("kind") not in CHECKS:
        return False
    return set(check) == {"kind", *CHECK_PARAMS[check["kind"]]} and bool(CHECKS[check["kind"]](check))


def normalize_check(check) -> dict:
    """LLM 이 쓴 조건을 닫힌 목록으로. 목록 밖·범위 밖은 버리지 않고 manual 로 내린다(글은 사람에게 쓸모가 있다)."""
    return check if check_ok(check) else {"kind": "manual"}


# ------------------------------------------------------------------ id · sortKey
def sort_key(occurred_at: str, stage: str, ticker: str, seq: int = 0) -> str:
    m = _AT.match(occurred_at or "")
    if not m:
        raise ValueError(f"occurredAt 은 KST ISO8601(+09:00) 초 단위: {occurred_at!r}")
    return f"{''.join(m.groups()[:3])}T{''.join(m.groups()[3:])}:{stage}:{ticker}:{seq:02d}"


def cand_id(as_of: str, rule: str, ticker: str) -> str:
    return f"cand:{as_of}:{rule}:{ticker}"


def thesis_id(signal_id: str, prompt_version: str, model: str) -> str:
    return f"thesis:{signal_id}:{prompt_version}:{model}"


def rebut_id(signal_id: str, prompt_version: str, model: str) -> str:
    return f"rebut:{signal_id}:{prompt_version}:{model}"


def inval_id(rebuttal_event_id: str, invalidation_id: str) -> str:
    return f"inval:{rebuttal_event_id}#{invalidation_id}"


def out_id(signal_id: str, horizon: int) -> str:
    return f"out:{signal_id}:h{horizon}"


def make(type_: str, *, event_id: str, ticker: str, market: str, occurred_at: str, as_of: str, producer: dict,
         signal_id: str, evidence_ids: List[str], payload: dict, seq: int = 0) -> dict:
    """봉투를 채워 검증까지 끝낸 기록을 돌려준다. sourceTeam·sortKey·contextOnly 는 type 에서 정해진다."""
    if type_ not in TYPES:
        raise ValueError(f"모르는 type: {type_!r}")
    team, stage, _ = TYPES[type_]
    e = {"eventSchemaVersion": SCHEMA, "eventId": event_id, "ticker": ticker, "market": market, "type": type_,
         "occurredAt": occurred_at, "sortKey": sort_key(occurred_at, stage, ticker, seq), "asOf": as_of,
         "sourceTeam": team, "source": "pipeline", "producer": producer, "signalId": signal_id,
         "evidenceIds": list(evidence_ids), "contextOnly": team in LLM_TEAMS, "payload": payload}
    validate(e)
    return e


# ------------------------------------------------------------------ 검증
def _fail(e, why):
    raise ValueError(f"{why} (eventId={e.get('eventId') if isinstance(e, dict) else None!r})")


def _items(e, name, keys, allow_empty=False):
    rows = e["payload"][name]
    if not isinstance(rows, list) or (not rows and not allow_empty):
        _fail(e, f"payload.{name} 은 비지 않은 배열")
    for r in rows:
        if not isinstance(r, dict) or set(r) != keys or not all(isinstance(r[k], str) and r[k] for k in keys):
            _fail(e, f"payload.{name} 항목의 키는 {sorted(keys)} (전부 비지 않은 문자열)")
    return rows


def _verification(e, total, kept, n_kept):
    v = e["payload"]["verification"]
    if not isinstance(v, dict) or set(v) != {total, kept, "dropped"} or not isinstance(v["dropped"], list):
        _fail(e, f"payload.verification 의 키는 {total}·{kept}·dropped")
    if v[kept] != n_kept or v[total] != n_kept + len(v["dropped"]):
        _fail(e, "payload.verification 건수가 본문과 안 맞는다(코드가 센 값이어야 한다)")


def validate(e: dict) -> None:
    """계약 위반이면 ValueError. 통과하면 None."""
    if not isinstance(e, dict):
        _fail({}, "기록은 객체")
    if set(e) != set(ENVELOPE):
        _fail(e, f"봉투 키 불일치: 빠짐 {sorted(set(ENVELOPE) - set(e))} · 모름 {sorted(set(e) - set(ENVELOPE))}")
    if e["eventSchemaVersion"] != SCHEMA or e["source"] != "pipeline":
        _fail(e, "eventSchemaVersion·source 고정값 위반")
    if e["type"] not in TYPES:
        _fail(e, f"모르는 type: {e['type']!r}")
    team, stage, required = TYPES[e["type"]]
    if e["sourceTeam"] != team:
        _fail(e, f"{e['type']} 의 sourceTeam 은 {team}")
    if e["contextOnly"] is not (team in LLM_TEAMS):
        _fail(e, "contextOnly 는 논리·반증이면 true, 코드 단계면 false")
    if e["market"] not in TICKER or not isinstance(e["ticker"], str) or not TICKER[e["market"]].match(e["ticker"]):
        _fail(e, f"market·ticker 형식 위반: {e['market']!r} {e['ticker']!r}")
    for k in ("eventId", "signalId"):
        if not isinstance(e[k], str) or not e[k] or "\n" in e[k]:
            _fail(e, f"{k} 는 비지 않은 한 줄 문자열")
    m = _AT.match(e["occurredAt"] if isinstance(e["occurredAt"], str) else "")
    if not m:
        _fail(e, "occurredAt 은 KST ISO8601(+09:00) — UTC·오프셋 없는 값 거부")
    if not isinstance(e["asOf"], str) or not re.match(r"^\d{8}$", e["asOf"]) or e["asOf"] > "".join(m.groups()[:3]):
        _fail(e, "asOf 는 YYYYMMDD 이고 occurredAt 날짜 이하(미래 자료 금지)")
    if not isinstance(e["sortKey"], str) or not re.match(
            re.escape(sort_key(e["occurredAt"], stage, e["ticker"]))[:-2] + r"\d\d$", e["sortKey"]):
        _fail(e, "sortKey 가 occurredAt·단계·ticker 와 안 맞는다")
    p = e["producer"]
    if not isinstance(p, dict) or p.get("kind") not in ("code", "llm", "claude-session") \
            or not all(isinstance(p.get(k), str) and p.get(k) for k in ("name", "version")):
        _fail(e, "producer 는 {kind: code|llm|claude-session, name, version}")
    if (p["kind"] != "code") is not (team in LLM_TEAMS):
        _fail(e, "producer.kind 가 단계와 안 맞는다(논리·반증만 llm|claude-session)")
    need = {"kind", "name", "version"} | ({"model", "promptVersion"} if p["kind"] != "code" else set())
    if not need <= set(p) or not set(p) <= need | {"commit"} or not all(isinstance(v, str) and v for v in p.values()):
        _fail(e, f"producer 키는 {sorted(need)} (+commit)")
    ev = e["evidenceIds"]
    if not isinstance(ev, list) or not ev or not all(
            isinstance(x, str) and ":" in x and x.split(":", 1)[0] in EVIDENCE_PREFIXES for x in ev):
        _fail(e, f"evidenceIds 는 비지 않은 배열이고 접두사는 {EVIDENCE_PREFIXES}")
    pl = e["payload"]
    if not isinstance(pl, dict) or set(pl) != set(required):
        _fail(e, f"payload 키 불일치: 빠짐 {sorted(set(required) - set(pl or {}))} · "
                 f"선언 안 됨 {sorted(set(pl or {}) - set(required))}")
    t = e["type"]
    if t == "CANDIDATE_SELECTED":
        if e["signalId"] != e["eventId"]:
            _fail(e, "후보의 signalId 는 자기 eventId")
        if not _num(pl["finalScore"]) or not isinstance(pl["rank"], int) or not 1 <= pl["rank"] <= pl["of"]:
            _fail(e, "후보는 finalScore(숫자)·rank(1..of) 필수 — null 점수는 후보가 못 된다")
    elif t == "THESIS_WRITTEN":
        rows = _items(e, "claims", CLAIM_KEYS)
        _verification(e, "claimsTotal", "claimsKept", len(rows))
        if not isinstance(pl["summary"], str):
            _fail(e, "payload.summary 는 문자열")
    elif t == "REBUTTAL_WRITTEN":
        rows = _items(e, "counters", COUNTER_KEYS, allow_empty=True)
        _verification(e, "countersTotal", "countersKept", len(rows))
        inv = pl["invalidations"]
        if not isinstance(inv, list) or (not inv and not rows):
            _fail(e, "반증은 counters 또는 invalidations 가 하나는 있어야 한다")
        for i in inv:
            if not isinstance(i, dict) or set(i) != {"id", "text", "check"} or not check_ok(i["check"]) \
                    or not all(isinstance(i[k], str) and i[k] for k in ("id", "text")):
                _fail(e, "invalidations 항목은 {id, text, check} 이고 check 는 닫힌 목록")
        if pl["flag"] not in FLAGS:
            _fail(e, f"flag 는 {FLAGS} 중 하나(숫자 신뢰도는 받지 않는다)")
    elif t == "INVALIDATION_TRIGGERED":
        if not check_ok(pl["check"]) or pl["check"]["kind"] == "manual":
            _fail(e, "닿음 기록의 check 는 닫힌 목록이고 manual 은 점검 대상이 아니다")
    elif t == "OUTCOME_MEASURED":
        if pl["horizon"] not in HORIZONS or pl["status"] not in OUTCOME_STATUS:
            _fail(e, f"horizon 은 {HORIZONS}, status 는 {OUTCOME_STATUS}")
        if (pl["status"] == "ok") is not _num(pl["ret"]):
            _fail(e, "status=ok 면 ret 은 숫자, 아니면 null(0 으로 채우지 않는다)")


# ------------------------------------------------------------------ 로그
def _files(root: Path, ticker: Optional[str] = None) -> List[Path]:
    root = Path(root)
    return sorted(root.glob(f"*/{ticker or '*'}.jsonl")) if root.is_dir() else []


def read(root=EVENTS_DIR, ticker: Optional[str] = None) -> List[dict]:
    """sortKey 순. 로그의 순서가 아니라 sortKey 가 시간순이다(늦게 쓰인 기록이 뒤에 붙어 있을 수 있다)."""
    out = []
    for f in _files(root, ticker):
        out += [json.loads(line) for line in f.read_text(encoding="utf-8").splitlines() if line.strip()]
    return sorted(out, key=lambda e: e["sortKey"])


def append(events: Iterable[dict], root=EVENTS_DIR) -> Dict[str, int]:
    """전부 검증한 뒤에만 쓴다. 이미 있는 eventId 는 쓰지 않고 센다. → {"written", "duplicates"}"""
    events = list(events)
    for e in events:
        validate(e)
    if os.environ.get("PIPELINE_FAIL_INJECTION") == "gate-test":      # 한 방향 훅 — 실패만 만들 수 있다
        raise RuntimeError("PIPELINE_FAIL_INJECTION=gate-test — 아무것도 쓰지 않았다")
    root, seen, written, dup = Path(root), {}, 0, 0
    for e in events:
        t = e["ticker"]
        if t not in seen:                                              # 해를 넘겨 다시 재는 기록도 잡게 그 종목의 전 연도를 본다
            seen[t] = {x["eventId"] for x in read(root, t)}
        if e["eventId"] in seen[t]:
            dup += 1
            continue
        seen[t].add(e["eventId"])
        f = root / e["occurredAt"][:4] / f"{t}.jsonl"
        f.parent.mkdir(parents=True, exist_ok=True)
        with f.open("a", encoding="utf-8", newline="\n") as fh:
            fh.write(json.dumps(e, ensure_ascii=False, sort_keys=True) + "\n")
        written += 1
    return {"written": written, "duplicates": dup}


def fold(events: Iterable[dict]) -> Dict[str, dict]:
    """signalId → 후보의 현재 모습. 저장하지 않는다 — 매번 로그에서 접는다."""
    out: Dict[str, dict] = {}
    for e in sorted(events, key=lambda x: x["sortKey"]):
        s = out.setdefault(e["signalId"], {"candidate": None, "thesis": [], "rebuttal": [], "invalidations": [],
                                           "outcomes": {}})
        t = e["type"]
        if t == "CANDIDATE_SELECTED":
            s["candidate"] = e
        elif t == "THESIS_WRITTEN":
            s["thesis"].append(e)
        elif t == "REBUTTAL_WRITTEN":
            s["rebuttal"].append(e)
        elif t == "INVALIDATION_TRIGGERED":
            s["invalidations"].append(e)
        else:
            s["outcomes"][e["payload"]["horizon"]] = e
    return out
