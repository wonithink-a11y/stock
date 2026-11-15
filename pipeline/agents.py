"""S3-b/c 논리·반증 주석 — Gemini(무료 등급)가 쓰고 코드가 인용을 대조한다. 계약: docs/AGENT_SPEC.md §3.3·§3.4·§6.1·§7.

- LLM 이 보는 것은 근거 묶음뿐이고, 인용이 그 절에 글자 그대로 없으면 그 항목은 탈락이다(믿지 않고 검사한다).
- 같은 후보·지시문·모델은 한 번만 쓴다(eventId). 다시 뽑아 고르지 않는다. 그날 못 쓴 후보를 다음 날 소급하지 않는다.
- 출력은 주석이다. 후보를 빼거나 순위를 바꾸는 칸이 없다(절대 규칙 1).
호출·재시도·인용 대조는 scripts/decode-gemini.py 의 것을 불러 쓴다(복사하지 않는다).
"""
from __future__ import annotations

import importlib.util
import time
import urllib.error
from pathlib import Path
from typing import Callable, Dict, List, Optional, Tuple

from . import bundle as B
from . import events as E

ROOT = Path(__file__).resolve().parent.parent
PROMPT_VERSION = "v1"
PROMPTS = Path(__file__).resolve().parent / "prompts"
CLAIM_KINDS = ("business", "growth", "quality", "valuation", "momentum")
CALL_GAP_SEC = 4.5            # 무료 등급 분당 15 요청(실측 2026-09-26) 아래로
MAX_COUNTERS, MAX_INVALIDATIONS, MAX_MANUAL = 5, 4, 1

_spec = importlib.util.spec_from_file_location("decode_gemini", ROOT / "scripts" / "decode-gemini.py")
dg = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(dg)

_S = {"type": "STRING"}
THESIS_SCHEMA = {"type": "OBJECT", "required": ["claims", "summary"], "properties": {
    "summary": _S,
    "claims": {"type": "ARRAY", "items": {"type": "OBJECT", "required": ["kind", "claim", "quote", "evidenceId"],
               "properties": {"kind": {"type": "STRING", "enum": list(CLAIM_KINDS)}, "claim": _S, "quote": _S,
                              "evidenceId": _S}}}}}
REBUTTAL_SCHEMA = {"type": "OBJECT", "required": ["counters", "invalidations", "flag"], "properties": {
    "flag": {"type": "STRING", "enum": list(E.FLAGS)},
    "counters": {"type": "ARRAY", "items": {"type": "OBJECT", "required": ["targets", "claim", "quote", "evidenceId"],
                 "properties": {"targets": _S, "claim": _S, "quote": _S, "evidenceId": _S}}},
    "invalidations": {"type": "ARRAY", "items": {"type": "OBJECT", "required": ["text", "kind"], "properties": {
        "text": _S, "kind": {"type": "STRING", "enum": list(E.CHECKS)}, "value": {"type": "NUMBER"},
        "ma": {"type": "INTEGER"}, "days": {"type": "INTEGER"}, "pct": {"type": "NUMBER"}}}}}}


def prompt(name: str) -> str:
    return (PROMPTS / f"{name}.{PROMPT_VERSION}.txt").read_text(encoding="utf-8")


def _verify(rows, bundle: dict, extra: Callable[[dict], Optional[str]] = lambda r: None) -> Tuple[List[dict], List[dict]]:
    """→ (통과 항목(원본 dict), 탈락 [{n, why}]). 인용은 **그 항목이 가리킨 절**에 있어야 한다."""
    text = {s["evidenceId"]: s["text"] for s in bundle["sections"]}
    kept, dropped = [], []
    for n, r in enumerate(rows if isinstance(rows, list) else []):
        r = r if isinstance(r, dict) else {}
        src = text.get(r.get("evidenceId"))
        why = ("evidence-id-unknown" if src is None
               else "empty" if not all(isinstance(r.get(k), str) and r[k].strip() for k in ("claim", "quote"))
               else extra(r))
        if not why:
            bad = dg.check(r, dg.squash(src))
            why = None if not bad else "number-not-in-quote" if "숫자" in bad else "quote-not-found"
        if why:
            dropped.append({"n": n, "why": why})
        else:
            kept.append(r)
    return kept, dropped


def make_thesis(cand: dict, bundle: dict, out: dict, model: str, at: str, commit: str = "") -> Optional[dict]:
    """LLM 출력 → THESIS_WRITTEN 기록. 통과 항목이 없으면 None(기록을 쓰지 않는다)."""
    kept, dropped = _verify(out.get("claims"), bundle, lambda r: None if r.get("kind") in CLAIM_KINDS else "kind-unknown")
    if not kept:
        return None
    claims = [{"id": f"T{i}", "kind": r["kind"], "claim": r["claim"].strip(), "quote": r["quote"].strip(),
               "evidenceId": r["evidenceId"]} for i, r in enumerate(kept, 1)]
    summary = out.get("summary") if isinstance(out.get("summary"), str) else ""
    quoted = {n.replace(",", "") for c in claims for n in dg.numbers(c["quote"])}
    if any(n.replace(",", "") not in quoted for n in dg.numbers(summary)):
        summary = ""                                            # 인용에 없는 숫자가 든 요약은 싣지 않는다
    return E.make("THESIS_WRITTEN", event_id=E.thesis_id(cand["eventId"], PROMPT_VERSION, model), ticker=cand["ticker"],
                  market=cand["market"], occurred_at=at, as_of=cand["asOf"], producer=_producer(model, commit),
                  signal_id=cand["eventId"], evidence_ids=sorted({c["evidenceId"] for c in claims}),
                  payload={"bundleSha256": bundle["sha256"], "claims": claims, "summary": summary.strip(),
                           "verification": {"claimsTotal": len(kept) + len(dropped), "claimsKept": len(kept),
                                            "dropped": [{"id": f"#{d['n']}", "why": d["why"]} for d in dropped]}})


def make_rebuttal(cand: dict, bundle: dict, thesis: dict, out: dict, model: str, at: str, commit: str = "") -> Optional[dict]:
    ids = {c["id"] for c in thesis["payload"]["claims"]}
    kept, dropped = _verify((out.get("counters") or [])[:MAX_COUNTERS], bundle,
                            lambda r: None if r.get("targets") in ids else "target-unknown")
    counters = [{"id": f"R{i}", "targets": r["targets"], "claim": r["claim"].strip(), "quote": r["quote"].strip(),
                 "evidenceId": r["evidenceId"]} for i, r in enumerate(kept, 1)]
    inv, manual = [], 0
    for r in out.get("invalidations") if isinstance(out.get("invalidations"), list) else []:
        if not (isinstance(r, dict) and isinstance(r.get("text"), str) and r["text"].strip()):
            continue
        kind = r.get("kind")
        params = {k: r.get(k) for k in E.CHECK_PARAMS.get(kind, ())}
        for k in ("ma", "days"):                                # 모델이 정수를 60.0 으로 내기도 한다(실측 2026-11-15)
            if isinstance(params.get(k), float) and params[k].is_integer():
                params[k] = int(params[k])
        check = E.normalize_check({"kind": kind, **params})
        if check["kind"] == "score-below" and not check["value"] < cand["payload"]["finalScore"]:
            check = {"kind": "manual"}                          # 이미 닿아 있는 조건은 조건이 아니다
        manual += check["kind"] == "manual"
        if check["kind"] == "manual" and manual > MAX_MANUAL:
            continue
        inv.append({"id": f"I{len(inv) + 1}", "text": r["text"].strip()[:200], "check": check})
        if len(inv) >= MAX_INVALIDATIONS:
            break
    if not counters and not inv:
        return None
    flag = out.get("flag") if out.get("flag") in E.FLAGS else "none"
    if flag != "none" and not counters:
        flag = "none"                                           # 통과한 반박이 없는데 깃발만 선 경우 — 근거 없는 깃발은 내린다
    return E.make("REBUTTAL_WRITTEN", event_id=E.rebut_id(cand["eventId"], PROMPT_VERSION, model), ticker=cand["ticker"],
                  market=cand["market"], occurred_at=at, as_of=cand["asOf"], producer=_producer(model, commit),
                  signal_id=cand["eventId"],
                  evidence_ids=[thesis["eventId"]] + sorted({c["evidenceId"] for c in counters}),
                  payload={"bundleSha256": bundle["sha256"], "thesisEventId": thesis["eventId"], "counters": counters,
                           "invalidations": inv, "flag": flag,
                           "verification": {"countersTotal": len(kept) + len(dropped), "countersKept": len(kept),
                                            "dropped": [{"id": f"#{d['n']}", "why": d["why"]} for d in dropped]}})


def _producer(model: str, commit: str) -> dict:
    return {"kind": "llm", "name": "pipeline.agents", "version": "1", "model": model, "promptVersion": PROMPT_VERSION,
            **({"commit": commit} if commit else {})}


def run(cands: List[dict], bundles: Dict[str, dict], existing: set, *, call: Callable, now: Callable[[], str],
        model: str, commit: str = "", sleep: Callable = time.sleep, max_n: int = 20) -> Tuple[List[dict], dict]:
    """후보마다 논리 → 반증. call(prompt, schema) → dict. existing: 로그에 이미 있는 eventId(한도를 아끼려고 미리 건너뛴다).

    → (기록들, 진단). 한도 오류(429)는 그 후보부터 전부 건너뛴다. 그 밖의 실패는 그 후보만.
    """
    diag = {"model": model, "promptVersion": PROMPT_VERSION, "candidates": len(cands), "skippedExisting": 0, "quotaSkipped": 0,
            "thesis": {"written": 0, "failed": 0, "claimsTotal": 0, "claimsKept": 0},
            "rebuttal": {"written": 0, "failed": 0, "flags": {f: 0 for f in E.FLAGS}, "invalidations": 0, "manual": 0}}
    out, calls = [], 0

    def ask(text, schema):
        nonlocal calls
        if calls:
            sleep(CALL_GAP_SEC)
        calls += 1
        return call(text, schema)

    for i, c in enumerate(cands[:max_n]):
        b = bundles[c["eventId"]]
        tid, rid = E.thesis_id(c["eventId"], PROMPT_VERSION, model), E.rebut_id(c["eventId"], PROMPT_VERSION, model)
        if tid in existing:                                      # 논리가 이미 있으면 그 후보는 끝난 것이다(반증만 다시 뽑지 않는다)
            diag["skippedExisting"] += 1
            continue
        fmt = dict(name=b["name"], ticker=c["ticker"], asOf=c["asOf"], bundle=B.render(b))
        step = "thesis"
        try:
            th = make_thesis(c, b, ask(prompt("thesis").format(**fmt), THESIS_SCHEMA), model, now(), commit)
            if not th:
                diag["thesis"]["failed"] += 1
                continue
            v = th["payload"]["verification"]
            diag["thesis"].update(written=diag["thesis"]["written"] + 1, claimsTotal=diag["thesis"]["claimsTotal"] + v["claimsTotal"],
                                  claimsKept=diag["thesis"]["claimsKept"] + v["claimsKept"])
            out.append(th)
            step = "rebuttal"
            claims = "\n".join(f"{x['id']} ({x['kind']}) {x['claim']}" for x in th["payload"]["claims"])
            rb = make_rebuttal(c, b, th, ask(prompt("rebuttal").format(claims=claims, **fmt), REBUTTAL_SCHEMA), model, now(), commit)
            if not rb or rid in existing:
                diag["rebuttal"]["failed"] += 1
                continue
            r = diag["rebuttal"]
            r["written"] += 1
            r["flags"][rb["payload"]["flag"]] += 1
            r["invalidations"] += len(rb["payload"]["invalidations"])
            r["manual"] += sum(x["check"]["kind"] == "manual" for x in rb["payload"]["invalidations"])
            out.append(rb)
        except urllib.error.HTTPError as e:
            if e.code == 429:                                    # 한도 — 남은 후보는 오늘 쓰지 않는다(내일 소급도 안 한다)
                diag["quotaSkipped"] = len(cands[:max_n]) - i
                break
            diag[step]["failed"] += 1
        except Exception:                                        # noqa: BLE001 — 한 종목의 실패가 전체를 멈추지 않는다
            diag[step]["failed"] += 1
    return out, diag
