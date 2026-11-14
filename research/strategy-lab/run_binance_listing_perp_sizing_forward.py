#!/usr/bin/env python3
"""바이낸스 신규 상장 7일 숏 무기한 — 크기·손절 forward 기록. 사전등록 findings/binance-listing-perp-sizing-forward-preregistration-2026-11.md (fa652a7d).

BL7 forward 의 사건 목록(reports/2026-10-binance-listing-forward/events.json, 읽기만)을 재사용해 무기한 1시간봉·펀딩을 기록하고, 성숙 40건 ∧ 6개월 전에는 판정을 거부한다.
격자·시뮬레이션·문턱은 futures/binance_listing_perp_sizing.py(9998570e) 그대로. 기록 전용 — 매매·알림 없음.

    python research/strategy-lab/run_binance_listing_perp_sizing_forward.py            # 기록(더 자주 돌려도 됨) → reports/ 커밋
    python research/strategy-lab/run_binance_listing_perp_sizing_forward.py --judge    # 성숙 40 ∧ 6개월 전에는 건수만
    python research/strategy-lab/run_binance_listing_perp_sizing_forward.py --selftest
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
sys.path.insert(0, str(HERE / "futures"))
sys.path.insert(0, str(HERE))
import binance_listing as bl  # noqa: E402
import binance_listing_perp as bp  # noqa: E402
import binance_listing_perp_sizing as sz  # noqa: E402
import run_binance_listing_forward as fw  # noqa: E402

SRC = ROOT / "reports" / "2026-10-binance-listing-forward" / "events.json"
OUT = ROOT / "reports" / "2026-11-binance-listing-perp-sizing-forward"
UMD = "https://data.binance.vision/data/futures/um/daily"
FAPI = "https://fapi.binance.com/fapi/v1/fundingRate"
D, HR, HOLD = sz.D, sz.HR, sz.HOLD
GATE, MONTHS, REC_MIN, DEADLINE, MIN_BASE = 40, 6, 15, pd.Timestamp("2027-11-30", tz="UTC"), 6
REC = (0.30, True, 0.02)                                       # 추천 칸: +30% 손절 · 급등 건너뜀 · 2%
PREV = HERE / "futures" / "binance-listing-perp-sizing.json"


def perp_symbol(base: str, dirs: set) -> str | None:
    return next((s for s in (f"{base}USDT", f"1000{base}USDT") if s in dirs), None)


def daily_frame(sym: str, days: list[str]) -> pd.DataFrame:
    fr = []
    for d in days:
        r = bp._csv(f"{UMD}/klines/{sym}/1h/{sym}-1h-{d}.zip")
        if len(r):
            fr.append(pd.DataFrame({"open": r[1].astype(float).to_numpy(), "high": r[2].astype(float).to_numpy()}, index=bp._ms(r[0])))
    return pd.concat(fr).sort_index() if fr else pd.DataFrame(columns=["open", "high"])


def funding_rows(sym: str, lo: pd.Timestamp, hi: pd.Timestamp) -> list[list]:
    j = bl._get(FAPI, params={"symbol": sym, "startTime": int(lo.timestamp() * 1000), "endTime": int(hi.timestamp() * 1000), "limit": 1000}).json()
    return [[int(x["fundingTime"]), float(x["fundingRate"])] for x in j] if isinstance(j, list) else []


def first_perp_bar(sym: str) -> pd.Timestamp | None:
    _, keys = bl._list(f"data/futures/um/daily/klines/{sym}/1h/")
    days = sorted(k.rsplit("-1h-", 1)[1][:10] for k in keys if k.endswith(".zip"))
    if not days:
        return None
    d = daily_frame(sym, days[:1])
    return d.index[0] if len(d) else None


def observe(ev: dict, now: pd.Timestamp, dirs: set) -> dict | None:
    L = pd.Timestamp(ev["L"], tz="UTC")
    t0 = L + D
    if now < t0 + 9 * D:                                        # E+168시간 + 일 파일 공개까지
        return None
    rec = {"sym": ev["sym"], "L": ev["L"], "recordedAt": now.isoformat()}
    ps = perp_symbol(ev["base"], dirs)
    if ps is None:
        return {**rec, "status": "NO_PERP"}
    f = first_perp_bar(ps)
    if f is None:
        return {**rec, "status": "NO_PERP"}
    g = sz.classify(f.normalize(), t0)
    if g == "X":
        return {**rec, "status": "X", "perp": ps}
    E = t0 if g == "C" else f + HR
    days = [d.strftime("%Y-%m-%d") for d in pd.date_range(E.normalize(), (E + HOLD * HR).normalize(), freq="D")]
    px, btc = daily_frame(ps, days), daily_frame("BTCUSDT", days)
    idx = pd.date_range(E, periods=HOLD + 1, freq="h")
    o, hi, b = px["open"].reindex(idx), px["high"].reindex(idx), btc["open"].reindex(idx)
    if o.isna().any() or hi.iloc[:HOLD].isna().any() or b.isna().any():
        return {**rec, "status": "DATA_MISSING", "perp": ps, "grp": g}
    s0, s1 = fw.open_on(ev["sym"], L), fw.open_on(ev["sym"], t0)
    day1 = float(s1 / s0 - 1) if np.isfinite(s0) and np.isfinite(s1) else None
    fu = funding_rows(ps, E, E + HOLD * HR)
    return {**rec, "status": "OK", "perp": ps, "grp": g, "E": E.isoformat(), "day1": day1, "pump": bool(day1 is not None and day1 >= sz.PUMP),
            "open": [float(x) for x in o], "high": [float(x) for x in hi.iloc[:HOLD]], "btc": [float(x) for x in b], "fu": fu}


def rebuild(o: dict) -> dict:
    E = pd.Timestamp(o["E"])
    idx = pd.date_range(E, periods=HOLD + 1, freq="h")
    px = pd.DataFrame({"open": o["open"], "high": o["high"] + [np.nan]}, index=idx)
    btc = pd.Series(o["btc"], index=idx)
    fu = pd.DataFrame({"rate": [r for _, r in o["fu"]], "ivl": 8.0}, index=pd.to_datetime([t for t, _ in o["fu"]], unit="ms", utc=True)) if o["fu"] else pd.DataFrame(columns=["rate", "ivl"])
    r = {"sym": o["sym"], "E": E, "pump": o["pump"], "L": pd.Timestamp(o["L"], tz="UTC")}
    for s in sz.STOPS:
        for slip in (sz.SLIP, sz.SLIP_S):
            r[(s, slip)] = sz.build_event(px, fu, btc, E, s, slip)
    return r


def judge(obs: list[dict], today: pd.Timestamp) -> dict:
    ok = [o for o in obs if o.get("status") == "OK"]
    cnt = {k: sum(1 for o in obs if o.get("status") == k) for k in ("OK", "NO_PERP", "X", "DATA_MISSING")}
    if not ok:
        return {"counts": cnt, "judge": "거부 — 성숙 무기한 건 없음"}
    first = min(pd.Timestamp(o["E"]) for o in ok)
    age = (today - first).days
    if len(ok) < GATE or age < MONTHS * 30:
        tail = " — 마감 2027-11-30 이후에도 40건 미만이면 INCONCLUSIVE 종결" if today >= DEADLINE and len(ok) < GATE else ""
        return {"counts": cnt, "n": len(ok), "ageDays": age, "judge": f"거부 — {len(ok)}/{GATE} 건 · {age}/{MONTHS * 30}일(사전등록 §3){tail}"}
    rows = [rebuild(o) for o in ok]
    rows = [r for r in rows if all(r[k] is not None for k in r if isinstance(k, tuple))]
    for r in rows:
        r["Ei"] = int((r["E"] - first) / HR)
    T = max(r["Ei"] for r in rows) + HOLD + 2
    cells = {}
    for s in sz.STOPS:
        for skip in (False, True):
            for f in sz.FRACS:
                a, st = sz.simulate(rows, T, s, skip, f, sz.COST, sz.SLIP), sz.simulate(rows, T, s, skip, f, sz.COST_S, sz.SLIP_S)
                cells[sz.cell_name(s, skip, f)] = {"final": round(a["final"], 3), "mdd": round(a["mdd"], 3), "worst1Pct": round(a["worst1"] * 100, 2), "n": a["n"], "stressFinal": round(st["final"], 3),
                                                   "A": bool(a["final"] > 1 and st["final"] > 1), "B": bool(a["mdd"] <= sz.MDD_MAX), "C": bool(a["worst1"] >= -sz.LOSS_MAX)}
    prev = json.loads(PREV.read_text(encoding="utf-8"))["passed"]
    rc = cells[sz.cell_name(*REC)]
    abc = lambda v: v["A"] and v["B"] and v["C"]  # noqa: E731
    n_pass = sum(abc(cells[k]) for k in prev if k in cells)
    if not (rc["B"] and rc["C"]) or rc["stressFinal"] <= 1.0:
        v = "REJECT"
    elif abc(rc) and n_pass >= MIN_BASE and rc["n"] >= REC_MIN:
        v = "CONFIRMED"
    else:
        v = "INCONCLUSIVE"
    return {"counts": cnt, "n": len(ok), "recommended": rc, "originalPassedStillPass": f"{n_pass}/{len(prev)}", "verdict": v, "cells": cells}


def load_obs() -> list[dict]:
    f = OUT / "observations.jsonl"
    return [json.loads(x) for x in f.read_text(encoding="utf-8").splitlines()] if f.exists() else []


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--judge", action="store_true")
    ap.add_argument("--selftest", action="store_true")
    a = ap.parse_args()
    if a.selftest:
        return selftest()
    OUT.mkdir(parents=True, exist_ok=True)
    obs = load_obs()
    now = pd.Timestamp(datetime.now(timezone.utc))
    if a.judge:
        j = judge(obs, now)
        j.pop("cells", None)
        print(json.dumps(j, ensure_ascii=False, indent=1))
        return 0
    events = json.loads(SRC.read_text(encoding="utf-8")) if SRC.exists() else []
    done = {o["sym"] for o in obs}
    dirs, _ = bl._list("data/futures/um/daily/klines/")
    dirset = {d.rstrip("/").split("/")[-1] for d in dirs}
    new = []
    for e in events:
        if e["sym"] in done:
            continue
        r = observe(e, now, dirset)
        if r:
            new.append(r)
    with open(OUT / "observations.jsonl", "a", encoding="utf-8") as f:
        for r in new:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    j = judge(obs + new, now)
    j.pop("cells", None)
    print(json.dumps({"events": len(events), "newObservations": [(r["sym"], r["status"]) for r in new], "judge": j}, ensure_ascii=False))
    return 0


def selftest():
    dirs = {"AAAUSDT", "1000BBBUSDT"}
    assert perp_symbol("AAA", dirs) == "AAAUSDT" and perp_symbol("BBB", dirs) == "1000BBBUSDT" and perp_symbol("CCC", dirs) is None
    now = pd.Timestamp("2026-11-14", tz="UTC")
    assert observe({"sym": "ZZZUSDT", "base": "ZZZ", "L": "2026-11-10"}, now, dirs) is None            # 아직 성숙 전
    assert observe({"sym": "CCCUSDT", "base": "CCC", "L": "2026-10-01"}, now, dirs)["status"] == "NO_PERP"
    assert "거부" in judge([], now)["judge"]
    E = pd.Timestamp("2026-10-03", tz="UTC")
    o = {"sym": "AAAUSDT", "L": "2026-10-02", "status": "OK", "E": E.isoformat(), "pump": False, "open": [100.0] * (HOLD + 1), "high": [100.0] * HOLD, "btc": [50.0] * (HOLD + 1), "fu": []}
    o["open"][HOLD] = 80.0
    r = rebuild(o)
    assert abs(r[(None, sz.SLIP)]["real"] - 0.2) < 1e-9 and r[(0.3, sz.SLIP)]["stopped"] is False
    j = judge([o], now)
    assert "거부" in j["judge"] and j["n"] == 1
    print("selftest OK")
    return 0


if __name__ == "__main__":
    sys.exit(main())
