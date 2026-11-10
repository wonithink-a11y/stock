#!/usr/bin/env python3
"""바이낸스 신규 상장 꼬리 조건 forward 기록. 사전등록 findings/binance-listing-tail-forward-preregistration-2026-11.md.

    python research/strategy-lab/run_binance_listing_tail_forward.py            # 월간 점검(#25 다음) → reports/ 커밋
    python research/strategy-lab/run_binance_listing_tail_forward.py --judge    # 성숙 80 ∧ 주 칸 30 ∧ 6개월 전에는 건수만
    python research/strategy-lab/run_binance_listing_tail_forward.py --selftest

사건은 forward #25(run_binance_listing_forward.py)의 events.json 을 읽기만 한다. 기록 전용 — 매매·알림 없음.
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(HERE))
import run_binance_listing_forward as f25  # noqa: E402  open_on 등(읽기 전용 재사용)

SRC = ROOT / "reports" / "2026-10-binance-listing-forward" / "events.json"
OUT = ROOT / "reports" / "2026-11-binance-listing-tail-forward"
D = pd.Timedelta(days=1)
PUMP, BIGPUMP, TAIL, BIG = 5000.0, 10000.0, 3000.0, 10000.0
GATE, GATE_CELL, EXT, EXT_CELL, MONTHS = 80, 30, 160, 60, 6


def mature(events: list[dict], done: set, now: pd.Timestamp, open_fn) -> list[dict]:
    rows = []
    for e in events:
        if e["sym"] in done:
            continue
        L = pd.Timestamp(e["L"], tz="UTC")
        t0, t1 = L + D, L + 8 * D
        if now < t1 + pd.Timedelta(hours=1):
            continue
        pL, p0, p1, b0, b1 = open_fn(e["sym"], L), open_fn(e["sym"], t0), open_fn(e["sym"], t1), open_fn("BTCUSDT", t0), open_fn("BTCUSDT", t1)
        ok = bool(all(np.isfinite([pL, p0, p1, b0, b1])))
        rel = round(((p1 / p0 - 1) - (b1 / b0 - 1)) * 1e4, 2) if ok else None
        day1 = round((p0 / pL - 1) * 1e4, 2) if ok else None
        rows.append({"sym": e["sym"], "L": e["L"], "ok": ok, "day1Bp": day1, "relBp": rel, "tail": bool(ok and rel >= TAIL), "big": bool(ok and rel >= BIG),
                     "stockLike": bool(e["base"].endswith("B") and e["base"][:-1].isalpha() and len(e["base"]) <= 6), "recordedAt": now.isoformat()})
    return rows


def judge(obs: list[dict], today: pd.Timestamp) -> dict:
    from scipy.stats import fisher_exact
    ok = [o for o in obs if o["ok"]]
    if not ok:
        return {"n": 0, "judge": "거부 — 관측 없음"}
    pump = [o for o in ok if o["day1Bp"] >= PUMP]
    rest = [o for o in ok if o["day1Bp"] < PUMP]
    first = min(pd.Timestamp(o["L"], tz="UTC") for o in ok)
    age = (today - first).days
    info = {"n": len(ok), "pump": len(pump), "missing": sum(1 for o in obs if not o["ok"]), "ageDays": age,
            "tail_pump": sum(o["tail"] for o in pump), "tail_rest": sum(o["tail"] for o in rest)}
    if len(ok) < GATE or len(pump) < GATE_CELL or age < MONTHS * 30:
        return {**info, "judge": f"거부 — 성숙 {len(ok)}/{GATE} · 주 칸 {len(pump)}/{GATE_CELL} · {age}/{MONTHS * 30}일(사전등록 §2)"}
    a, b, c, d = info["tail_pump"], len(pump) - info["tail_pump"], info["tail_rest"], len(rest) - info["tail_rest"]
    rate_p, rate_r = a / len(pump), (c / len(rest) if rest else 0.0)
    p = float(fisher_exact([[a, b], [c, d]], alternative="greater")[1]) if rest else 1.0
    if rate_p <= rate_r:
        v = "REJECT"
    elif p <= 0.05:
        v = "CONFIRMED"
    else:
        v = "INCONCLUSIVE — 연장" if not (len(ok) >= EXT and len(pump) >= EXT_CELL) else "REJECT"
    return {**info, "rate_pump": round(rate_p, 4), "rate_rest": round(rate_r, 4), "p_one_sided": round(p, 4), "verdict": v}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--judge", action="store_true")
    ap.add_argument("--selftest", action="store_true")
    a = ap.parse_args()
    if a.selftest:
        return selftest()
    OUT.mkdir(parents=True, exist_ok=True)
    obs_f = OUT / "observations.jsonl"
    obs = [json.loads(x) for x in obs_f.read_text(encoding="utf-8").splitlines()] if obs_f.exists() else []
    if a.judge:
        print(json.dumps(judge(obs, pd.Timestamp.now(tz="UTC")), ensure_ascii=False, indent=1))
        return 0
    events = json.loads(SRC.read_text(encoding="utf-8")) if SRC.exists() else []
    now = pd.Timestamp(datetime.now(timezone.utc))
    rows = mature(events, {o["sym"] for o in obs}, now, f25.open_on)
    with open(obs_f, "a", encoding="utf-8") as f:
        for r in rows:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    allobs = obs + rows
    big_pump = sum(1 for o in allobs if o["ok"] and o["day1Bp"] >= BIGPUMP)
    print(json.dumps({"events": len(events), "newObservations": len(rows), "bigPumpCell": big_pump, "bigTails": sum(1 for o in allobs if o["big"]), "judge": judge(allobs, now)}, ensure_ascii=False))
    return 0


def selftest():
    ok = 0
    ev = [{"base": "BBB", "sym": "BBBUSDT", "L": "2026-11-10"}]
    px = {("BBBUSDT", "2026-11-10"): 100.0, ("BBBUSDT", "2026-11-11"): 160.0, ("BBBUSDT", "2026-11-18"): 240.0, ("BTCUSDT", "2026-11-11"): 10.0, ("BTCUSDT", "2026-11-18"): 10.0}
    of = lambda s, t: px.get((s, t.strftime("%Y-%m-%d")), float("nan"))  # noqa: E731
    assert mature(ev, set(), pd.Timestamp("2026-11-17", tz="UTC"), of) == []; ok += 1
    r = mature(ev, set(), pd.Timestamp("2026-11-19", tz="UTC"), of)
    assert r[0]["ok"] and abs(r[0]["day1Bp"] - 6000) < 1e-6 and abs(r[0]["relBp"] - 5000) < 1e-6 and r[0]["tail"] and not r[0]["big"]; ok += 1
    assert mature(ev, {"BBBUSDT"}, pd.Timestamp("2026-12-01", tz="UTC"), of) == []; ok += 1
    assert "거부" in judge(r, pd.Timestamp("2026-12-01", tz="UTC"))["judge"]; ok += 1
    obs = [{"sym": f"S{i}", "L": str((pd.Timestamp("2026-11-01") + pd.Timedelta(days=i)).date()), "ok": True, "day1Bp": 6000.0 if i % 2 == 0 else 100.0,
            "relBp": 4000.0 if (i % 2 == 0 and i % 4 == 0) else 500.0, "tail": bool(i % 2 == 0 and i % 4 == 0), "big": False} for i in range(100)]
    assert judge(obs, pd.Timestamp("2027-06-01", tz="UTC"))["verdict"] == "CONFIRMED"; ok += 1     # 주 칸 50건 중 25 꼬리 vs 밖 0
    print(f"selftest {ok}/5 OK")
    return 0


if __name__ == "__main__":
    sys.exit(main())
