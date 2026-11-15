"""파이프라인 실행기 — GitHub Actions(pipeline.yml)만 data/pipeline/ · docs/data/pipeline/ 에 쓴다. 로컬은 --root 로 다른 곳에.

    python -m pipeline candidates   점수 상위 후보(CR-1.0)
    python -m pipeline agents       새 사건에 논리·반증 주석 (GEMINI_API_KEY 없으면 건너뛴다)
    python -m pipeline monitor      무효 조건 점검
    python -m pipeline outcomes     만기 도래분 사후 수익
    python -m pipeline view         화면용 latest.json 전체 재생성
    python -m pipeline notify       텔레그램 한 줄 요약 (토큰 없으면 건너뛴다)
  공통: [--root DIR] [--now 2026-11-16T20:45:00] · agents: [--max N] [--model M]
"""
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

from . import candidates as C
from . import events as E

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "docs" / "data"
DEFAULT_ROOT = ROOT / "data" / "pipeline"
KST = timezone(timedelta(hours=9))
COMMIT = os.environ.get("GITHUB_SHA", "")[:7]


def _json(path: Path):
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else None


def _at(now) -> str:
    return now.strftime("%Y-%m-%dT%H:%M:%S+09:00")


def diag_update(root: Path, day: str, section: str, data: dict) -> None:
    """data/pipeline/diagnostics/{날짜}.json 의 한 칸을 덮어쓴다. 0건이어도 쓴다('안 돌았다'와 '없다'를 가른다)."""
    p = Path(root) / "diagnostics" / f"{day}.json"
    p.parent.mkdir(parents=True, exist_ok=True)
    d = _json(p) or {}
    d[section] = data
    p.write_text(json.dumps(d, ensure_ascii=False, indent=1, sort_keys=True) + "\n", encoding="utf-8", newline="\n")
    print(section, json.dumps(data, ensure_ascii=False))


def _results() -> dict:
    return {r["result"]["ticker"]: r for r in (_json(DATA / "latest-v2.json") or {}).get("results") or []
            if r.get("market") == "KR"}


def _prices() -> dict:
    return (_json(DATA / "prices.json") or {}).get("byTicker") or {}


def _starts(log):
    """사건의 첫 날인 후보들(주석·점검·평가의 대상)."""
    ids = E.episode_starts(log)
    return [e for e in log if e["type"] == "CANDIDATE_SELECTED" and e["eventId"] in ids]


def cmd_candidates(a, now):
    raw = (DATA / "latest-v2.json").read_bytes()
    states = {f.stem: _json(f) for f in (ROOT / "data" / "state").glob("*.json")}
    evs, diag = C.select(json.loads(raw), hashlib.sha256(raw).hexdigest(), states, now, commit=COMMIT)
    diag.update(E.append(evs, a.root / "events"), runAt=_at(now))
    diag_update(a.root, now.strftime("%Y%m%d"), "candidates", diag)


def cmd_agents(a, now):
    """오늘 뽑힌 새 사건에만 주석을 단다 — 지난 후보를 소급하지 않는다(다음 날 쓴 논리는 다음 날 정보를 본 것이다)."""
    from . import agents as A
    from . import bundle as B
    day = now.strftime("%Y-%m-%d")
    log = E.read(a.root / "events")
    cands = sorted((e for e in _starts(log) if e["occurredAt"][:10] == day), key=lambda e: e["payload"]["rank"])
    key = A.dg.load_env().get("GEMINI_API_KEY")
    if not cands or not key:
        return diag_update(a.root, now.strftime("%Y%m%d"), "agents", {"candidates": len(cands), "noKey": not key, "skipped": True})
    results, prices, rank = _results(), _prices(), _json(DATA / "rank-h5.json")
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
            b = B.build(c, result=r["result"], decode=_json(DATA / "decode" / f"{t}.json"),
                        state=_json(ROOT / "data" / "state" / f"{t}.json"), history=hist, prices=prices.get(t), rank_h5=rank)
            f.parent.mkdir(parents=True, exist_ok=True)
            f.write_text(json.dumps(b, ensure_ascii=False, indent=1) + "\n", encoding="utf-8", newline="\n")
        bundles[c["eventId"]] = b
        usable.append(c)
    evs, diag = A.run(usable, bundles, {e["eventId"] for e in log},
                      call=lambda text, schema: A.dg.gemini(text, key, a.model, schema=schema, temperature=0)[0],
                      now=lambda: _at(datetime.now(KST)), model=a.model, commit=COMMIT, max_n=a.max)
    diag.update(E.append(evs, a.root / "events"), bundleSkipped=len(cands) - len(usable))
    diag_update(a.root, now.strftime("%Y%m%d"), "agents", diag)


def cmd_monitor(a, now):
    from . import monitor as M
    log = E.read(a.root / "events")
    folded, done = E.fold(log), {e["eventId"] for e in log}
    cands = [e for e in log if e["type"] == "CANDIDATE_SELECTED"]
    runs = sorted({c["asOf"] for c in cands})
    picked = {(c["asOf"], c["ticker"]) for c in cands}
    results, prices = _results(), _prices()
    cal = (prices.get("005930") or {}).get("d") or []
    out, diag = [], {"checked": 0, "triggered": [], "unknown": 0, "expired": 0}
    for c in _starts(log):
        rb = (folded[c["eventId"]]["rebuttal"] or [None])[0]
        if not rb:
            continue
        t, sig = c["ticker"], c["asOf"]
        since = sum(1 for d in cal if d > sig)
        if since > M.WINDOW:
            diag["expired"] += 1
            continue
        px = prices.get(t) or {}
        closes = [(d, x) for d, x in zip(px.get("d") or [], px.get("c") or []) if x]
        r = results.get(t)
        missed = 0
        for d in reversed([d for d in runs if d > sig]):
            if (d, t) in picked:
                break
            missed += 1
        st = _json(ROOT / "data" / "state" / f"{t}.json") or {}
        for inv in rb["payload"]["invalidations"]:
            eid = E.inval_id(rb["eventId"], inv["id"])
            if inv["check"]["kind"] == "manual" or eid in done:
                continue
            diag["checked"] += 1
            obs = M.check(inv["check"], closes=closes, signal_day=sig, risk_states=st.get("riskStates") or [],
                          final_score=(r or {}).get("result", {}).get("finalScore"), runs_missed=missed)
            if obs == M.UNKNOWN:
                diag["unknown"] += 1
            elif obs:
                as_of = min(closes[-1][0] if closes else sig, now.strftime("%Y%m%d"))
                out.append(E.make("INVALIDATION_TRIGGERED", event_id=eid, ticker=t, market=c["market"], occurred_at=_at(now),
                                  as_of=as_of, producer={"kind": "code", "name": "pipeline.monitor", "version": "MN-1.0",
                                                         **({"commit": COMMIT} if COMMIT else {})},
                                  signal_id=c["eventId"], evidence_ids=[rb["eventId"], f"px:{as_of}:{t}"],
                                  payload={"rebuttalEventId": rb["eventId"], "invalidationId": inv["id"], "check": inv["check"],
                                           "observed": obs, "daysSinceSignal": since}))
                diag["triggered"].append({"ticker": t, "name": px.get("name", ""), "text": inv["text"]})
    diag.update(E.append(out, a.root / "events"))
    diag_update(a.root, now.strftime("%Y%m%d"), "monitor", diag)


def cmd_outcomes(a, now):
    from . import outcomes as O
    log = E.read(a.root / "events")
    done, prices = {e["eventId"] for e in log}, _prices()
    evs = [o for c in _starts(log) for o in O.measure(c, prices, _at(now), done, COMMIT)]
    diag_update(a.root, now.strftime("%Y%m%d"), "outcomes", {"measured": len(evs), **E.append(evs, a.root / "events")})


def _view_path(a) -> Path:
    return DATA / "pipeline" / "latest.json" if a.root == DEFAULT_ROOT else a.root / "latest.json"


def cmd_view(a, now):
    from . import view as V
    v = V.build(E.read(a.root / "events"), {t: p.get("name", "") for t, p in _prices().items()})
    p = _view_path(a)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(v, ensure_ascii=False, indent=1, sort_keys=True) + "\n", encoding="utf-8", newline="\n")
    print("view", json.dumps(v["counts"], ensure_ascii=False))


def message(view: dict, diag: dict) -> str:
    """새 사건이나 무효 조건 닿음이 있을 때만 글이 나온다(없으면 빈 문자열 — 매일 같은 알림을 보내지 않는다)."""
    new = [x for x in view.get("today") or [] if x["isNew"]]
    trig = (diag.get("monitor") or {}).get("triggered") or []
    if not new and not trig:
        return ""
    eps = {e["signalId"]: e for e in view.get("episodes") or []}
    ko = {"none": "", "caution": " ⚠주의", "thesis-weak": " ⚠약함"}
    lines = [f"[파이프라인] 기준일 {view['asOf']} · 후보 {len(view['today'])} · 새 사건 {len(new)} · 무효 조건 닿음 {len(trig)}"]
    for x in new:
        rb = (eps.get(x["signalId"]) or {}).get("rebuttal")
        lines.append(f"· {x['rank']}위 {x['name']}({x['ticker']}) {x['finalScore']}{ko.get(rb['flag'], '') if rb else ' (주석 없음)'}")
    lines += [f"✖ {t['name']}({t['ticker']}) — {t['text']}" for t in trig]
    lines.append("관찰용 — 주석은 점수·주문에 쓰이지 않는다. 계획은 웹에서 직접 정한다.")
    return "\n".join(lines)


def cmd_notify(a, now):
    text = message(_json(_view_path(a)) or {}, _json(a.root / "diagnostics" / f"{now.strftime('%Y%m%d')}.json") or {})
    token, chat = os.environ.get("TELEGRAM_BOT_TOKEN"), os.environ.get("TELEGRAM_CHAT_ID")
    if not (text and token and chat):
        print("notify skipped", {"text": bool(text), "token": bool(token and chat)})
        return
    spec = importlib.util.spec_from_file_location("send_telegram_report", ROOT / "scripts" / "send-telegram-report.py")
    tg = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(tg)
    tg.send(token, chat, text)
    print("notify sent", len(text))


CMDS = {"candidates": cmd_candidates, "agents": cmd_agents, "monitor": cmd_monitor, "outcomes": cmd_outcomes,
        "view": cmd_view, "notify": cmd_notify}


def main(argv=None):
    ap = argparse.ArgumentParser(prog="pipeline")
    ap.add_argument("cmd", choices=list(CMDS))
    ap.add_argument("--max", type=int, default=20, help="주석을 달 후보 수 상한(무료 한도 보호)")
    ap.add_argument("--model", default="gemini-3.5-flash-lite")
    ap.add_argument("--root", type=Path, default=DEFAULT_ROOT)
    ap.add_argument("--now", help="KST 시각(시험용). 기본은 지금")
    a = ap.parse_args(argv)
    now = datetime.fromisoformat(a.now).replace(tzinfo=KST) if a.now else datetime.now(KST)
    CMDS[a.cmd](a, now)


if __name__ == "__main__":
    sys.exit(main())
