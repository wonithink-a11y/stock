"""반증 깃발 변별력 forward — G0(운영 품질)·기준선 사실·판정. 순수 함수.

사전등록: research/strategy-lab/findings/pipeline-rebuttal-forward-preregistration-2026-11.md (f7c22327, 동결).
이 파일의 문턱·갈래·시점은 그 문서의 것이다 — 바꾸지 않는다. 판정 조건 전에는 건수만 낸다(갈래별 평균을 계산하지 않는다).
"""
from __future__ import annotations

import random
from datetime import date, datetime
from typing import Dict, List, Optional

from . import events as E

SEED, BOOT, PERM = 20261116, 2000, 500
COST = 0.00335                                   # KR 연속 시장 왕복 33.5bp
G0_DAYS, G0_QUOTE, G0_RECORD, G0_CHECKABLE, G0_STALE_MAX = 20, 0.80, 0.85, 0.50, 2
G0_DEADLINE = "2027-11-16"
MIN_DAYS, MIN_DROP, MIN_WEEKS, MAX_DAYS = 365, 60, 40, 1095
CODE_BOTTOM = 0.30


# ------------------------------------------------------------------ 기준선 사실(후보를 뽑는 날 적는다)
def baseline_facts(cands: List[dict], prices: Dict[str, dict]) -> Dict[str, dict]:
    """그날 후보 전부의 가격 사실과 코드 깃발. 일봉이 모자라면 known=False(모르는 것을 깃발로 만들지 않는다)."""
    out, known = {}, []
    for c in cands:
        px = prices.get(c["ticker"]) or {}
        rows = [(d, x) for d, x in zip(px.get("d") or [], px.get("c") or []) if d <= c["asOf"] and x]
        if len(rows) < 61 or rows[-1][0] != c["asOf"]:
            out[c["ticker"]] = {"known": False}
            continue
        cl = [x for _, x in rows]
        out[c["ticker"]] = {"known": True, "close": cl[-1], "ma60": round(sum(cl[-60:]) / 60, 4), "ret20": round(cl[-1] / cl[-21] - 1, 6)}
        known.append(c["ticker"])
    for i, t in enumerate(sorted(known, key=lambda t: (out[t]["ret20"], t)), 1):
        f = out[t]
        f["ret20Rank"] = i
        f["drop"] = bool(f["close"] < f["ma60"] or i / len(cands) <= CODE_BOTTOM)
    return out


# ------------------------------------------------------------------ G0 — 어느 갈래·어느 날부터가 표본인가
def g0(diags: Dict[str, dict]) -> dict:
    """diags: 'YYYYMMDD' → 그날 진단. → {arm, sampleStart, arms:{갈래: {days, passed, …}}}"""
    by_arm: Dict[tuple, List[str]] = {}
    for day in sorted(diags):
        a = (diags[day] or {}).get("agents") or {}
        if isinstance(a.get("thesis"), dict) and a.get("promptVersion") and a.get("model"):
            by_arm.setdefault((a["promptVersion"], a["model"]), []).append(day)
    arms = {}
    for arm, days in by_arm.items():
        info = {"days": min(len(days), G0_DAYS), "passed": None}
        if len(days) >= G0_DAYS:
            win = days[:G0_DAYS]
            ag = [diags[d]["agents"] for d in win]
            s = lambda f: sum(f(x) or 0 for x in ag)                                     # noqa: E731
            cands, inv = s(lambda x: x.get("candidates")), s(lambda x: x["rebuttal"].get("invalidations"))
            total = s(lambda x: x["thesis"].get("claimsTotal"))
            m = {"quote": s(lambda x: x["thesis"].get("claimsKept")) / total if total else 0.0,
                 "thesisRate": s(lambda x: x["thesis"].get("written")) / cands if cands else 0.0,
                 "rebuttalRate": s(lambda x: x["rebuttal"].get("written")) / cands if cands else 0.0,
                 "checkable": 1 - s(lambda x: x["rebuttal"].get("manual")) / inv if inv else 0.0,
                 "staleDays": sum(1 for d in diags if win[0] <= d <= win[-1]
                                  and ((diags[d] or {}).get("candidates") or {}).get("staleScoreSkip"))}
            info.update(window=[win[0], win[-1]], metrics={k: round(v, 4) for k, v in m.items()},
                        passed=bool(m["quote"] >= G0_QUOTE and m["thesisRate"] >= G0_RECORD and m["rebuttalRate"] >= G0_RECORD
                                    and m["checkable"] >= G0_CHECKABLE and m["staleDays"] <= G0_STALE_MAX))
        arms[arm] = info
    done = sorted((i["window"][1], arm) for arm, i in arms.items() if i["passed"])
    if not done:
        return {"arm": None, "sampleStart": None, "arms": {f"{a[0]}|{a[1]}": i for a, i in arms.items()}}
    end, arm = done[0]
    start = date.fromordinal(datetime.strptime(end, "%Y%m%d").date().toordinal() + 1).isoformat()
    return {"arm": list(arm), "sampleStart": start, "arms": {f"{a[0]}|{a[1]}": i for a, i in arms.items()}}


# ------------------------------------------------------------------ 표본·갈래
def rows(log: List[dict], baselines: Dict[str, dict], arm, start: str) -> List[dict]:
    """표본 사건마다 한 줄: 깃발(LLM·코드)과 h20. start 이후에 기록된 사건만."""
    starts, folded = E.episode_starts(log), E.fold(log)
    out = []
    for sid in sorted(starts):
        f = folded[sid]
        c = f["candidate"]
        if c["occurredAt"][:10] < start:
            continue
        rb = next((r for r in f["rebuttal"] if [r["producer"]["promptVersion"], r["producer"]["model"]] == list(arm)), None)
        o = f["outcomes"].get(20)
        b = (baselines.get(c["asOf"]) or {}).get(c["ticker"]) or {}
        entry = o["payload"]["entryDate"] if o else None
        wk = None
        if entry:
            y, w, _ = datetime.strptime(entry, "%Y%m%d").isocalendar()
            wk = f"{y}-{w:02d}"
        out.append({"signalId": sid, "ticker": c["ticker"], "entry": entry, "week": wk,
                    "status": o["payload"]["status"] if o else "pending",
                    "excess": o["payload"]["excess"] if o and o["payload"]["status"] == "ok" else None,
                    "llm": None if not rb else "keep" if rb["payload"]["flag"] == "none" else "drop",
                    "code": None if not b.get("known") else "drop" if b["drop"] else "keep"})
    return out


def counts(rs: List[dict]) -> dict:
    ok = [r for r in rs if r["excess"] is not None]
    n = lambda k, v: sum(1 for r in ok if r[k] == v)                                     # noqa: E731
    status: Dict[str, int] = {}
    for r in rs:
        status[r["status"]] = status.get(r["status"], 0) + 1
    return {"events": len(rs), "status": dict(sorted(status.items())), "ok": len(ok),
            "llmKeep": n("llm", "keep"), "llmDrop": n("llm", "drop"), "llmUnrecorded": n("llm", None),
            "codeKeep": n("code", "keep"), "codeDrop": n("code", "drop"), "codeUnknown": n("code", None),
            "weeks": len({r["week"] for r in ok})}


# ------------------------------------------------------------------ 통계
def _d(rs, key) -> Optional[float]:
    k = [r["excess"] for r in rs if r[key] == "keep"]
    d = [r["excess"] for r in rs if r[key] == "drop"]
    return sum(k) / len(k) - sum(d) / len(d) if k and d else None


def _pct(xs: List[float], q: float) -> float:
    xs = sorted(xs)
    return xs[min(len(xs) - 1, int(q * len(xs)))]


def stats(rs: List[dict], semis: set) -> dict:
    ok = [r for r in rs if r["excess"] is not None]
    weeks: Dict[str, List[dict]] = {}
    for r in ok:
        weeks.setdefault(r["week"], []).append(r)
    names = sorted(weeks)
    rng = random.Random(SEED)
    bl, bc, bd, skipped = [], [], [], 0
    for _ in range(BOOT):
        s = [r for w in (rng.choice(names) for _ in names) for r in weeks[w]]
        a, b = _d(s, "llm"), _d(s, "code")
        if a is None or b is None:
            skipped += 1
            continue
        bl.append(a)
        bc.append(b)
        bd.append(a - b)
    rng = random.Random(SEED)
    perm = []
    for _ in range(PERM):
        s = []
        for w in names:
            lab = [r["llm"] for r in weeks[w] if r["llm"]]
            rng.shuffle(lab)
            it = iter(lab)
            s += [{**r, "llm": next(it)} if r["llm"] else r for r in weeks[w]]
        d = _d(s, "llm")
        if d is not None:
            perm.append(d)
    entries = sorted(r["entry"] for r in ok)
    mid = entries[len(entries) // 2]
    ci = lambda xs: [round(_pct(xs, 0.05), 6), round(_pct(xs, 0.95), 6)] if xs else None  # noqa: E731
    r6 = lambda v: None if v is None else round(v, 6)                                    # noqa: E731
    return {"dLlm": r6(_d(ok, "llm")), "dCode": r6(_d(ok, "code")), "ciLlm": ci(bl), "ciCode": ci(bc), "ciDiff": ci(bd),
            "bootSkipped": skipped, "floor": r6(_pct(perm, 0.95)) if perm else None,
            "firstHalf": r6(_d([r for r in ok if r["entry"] < mid], "llm")),
            "secondHalf": r6(_d([r for r in ok if r["entry"] >= mid], "llm")),
            "exSemis": r6(_d([r for r in ok if r["ticker"] not in semis], "llm"))}


def verdict(s: dict) -> dict:
    d, fl, ci = s["dLlm"], s["floor"], s["ciDiff"]
    if d is None or fl is None:
        return {"verdict": "INCONCLUSIVE", "signal": "측정 불가", "economic": "미달"}
    if d <= fl:
        return {"verdict": "REJECT", "signal": "없음", "economic": "미달"}
    if not (ci and ci[0] > 0 and d >= COST):
        return {"verdict": "INFORMATION", "signal": "있음", "economic": "미달"}
    robust = all(x is not None and x > 0 for x in (s["firstHalf"], s["secondHalf"], s["exSemis"]))
    return {"verdict": "ROBUST" if robust else "ECONOMIC", "signal": "있음", "economic": "통과"}


def run(log: List[dict], diags: Dict[str, dict], baselines: Dict[str, dict], today: str, semis: set) -> dict:
    """today: 'YYYY-MM-DD'. 조건 전에는 locked=True 와 건수만 — 평균은 계산하지 않는다."""
    g = g0(diags)
    if not g["arm"]:
        late = today > G0_DEADLINE
        return {"locked": not late, "g0": g, **({"verdict": "INCONCLUSIVE", "why": "운영 품질(G0) 미달"} if late else
                                               {"why": "G0 를 통과한 갈래가 아직 없다"})}
    rs = rows(log, baselines, g["arm"], g["sampleStart"])
    c = counts(rs)
    days = (date.fromisoformat(today) - date.fromisoformat(g["sampleStart"])).days
    need = {"days": [days, MIN_DAYS], "llmDrop": [c["llmDrop"], MIN_DROP], "weeks": [c["weeks"], MIN_WEEKS]}
    base = {"g0": {"arm": g["arm"], "sampleStart": g["sampleStart"]}, "counts": c, "need": need}
    if not all(a >= b for a, b in need.values()):
        if days > MAX_DAYS:
            return {"locked": False, "verdict": "INCONCLUSIVE", "why": "마감(1,095일)까지 표본 조건 미달", **base}
        return {"locked": True, "why": "판정 조건 미달 — 건수만", **base}
    s = stats(rs, semis)
    return {"locked": False, **verdict(s), "stats": s, **base}
