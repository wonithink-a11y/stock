#!/usr/bin/env python3
"""VIX 기간구조 T2 forward 기록. 사전등록 findings/vix-term-t2-forward-preregistration-2026-10.md.

    python research/strategy-lab/run_vix_term_t2_forward.py            # 월간 점검(더 자주 돌려도 된다, 수 초) → reports/ 커밋
    python research/strategy-lab/run_vix_term_t2_forward.py --judge    # 성숙 250거래일 ∧ 12개월 전에는 건수만
    python research/strategy-lab/run_vix_term_t2_forward.py --selftest

상태·초과수익·성과는 vix_term_structure(3d40c89c)의 states / excess / perf 를 그대로 쓴다. 기록 전용 — 매매·알림 없음.
"""
from __future__ import annotations

import argparse
import json
import sys
import time
import urllib.request
from pathlib import Path

import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(HERE))
import champion_shortterm_usfut as us  # noqa: E402
import vix_term_structure as vt  # noqa: E402  동결 규칙

OUT = ROOT / "reports" / "2026-10-vix-term-t2-forward"
START = pd.Timestamp("2026-11-02")
GATE, MONTHS, EXT, EXT_MONTHS, MIN_FLAT = 250, 12, 500, 24, 10
URL = "https://query1.finance.yahoo.com/v8/finance/chart/{t}?period1={p1}&period2={p2}&interval=1d&events=div%2Csplit&includeAdjustedClose=true"


def fetch_df() -> pd.DataFrame:
    p2 = int(time.time())
    p1 = p2 - 3 * 366 * 86400
    bodies = {}
    for k, sym in vt.SYMS.items():
        url = URL.format(t=urllib.request.quote(sym), p1=p1, p2=p2)
        for n in range(4):
            try:
                body = urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"}), timeout=60).read()
                break
            except Exception:
                if n == 3:
                    raise
                time.sleep(2 ** (n + 1))
        res = json.loads(body)["chart"]["result"][0]
        assert res["meta"]["symbol"] == sym, res["meta"]["symbol"]          # 응답이 요청 종목인지(교훈 81)
        bodies[k] = body
    spy = us.parse(bodies["SPY"])
    vix, v3, irx = (vt.close_series(bodies[k]) for k in ("VIX", "VIX3M", "IRX"))
    return pd.DataFrame({"o": spy.o}).join(pd.DataFrame({"vix": vix, "v3": v3, "irx": irx}), how="left")


def rows_from(df: pd.DataFrame) -> list[dict]:
    S, R, pct = vt.states(df)
    x = vt.excess(df)
    out = []
    for d in df.index[df.index >= START]:
        if pd.isna(x.get(d)):
            continue                                                        # 미성숙(O_{t+2} 없음)
        out.append({"date": str(d.date()), "R": None if pd.isna(R[d]) else round(float(R[d]), 6),
                    "pct": None if pd.isna(pct[d]) else round(float(pct[d]), 6), "s": int(S["T2"][d]), "x": round(float(x[d]), 8)})
    return out


def _read(name):
    p = OUT / name
    return [json.loads(l) for l in p.read_text(encoding="utf-8").splitlines() if l.strip()] if p.exists() else []


def _append(name, rows):
    if rows:
        OUT.mkdir(parents=True, exist_ok=True)
        with open(OUT / name, "a", encoding="utf-8") as f:
            for r in rows:
                f.write(json.dumps(r, ensure_ascii=False) + "\n")


def merge(obs: list[dict], fresh: list[dict]) -> tuple[list[dict], list[dict]]:
    seen = {o["date"]: o for o in obs}
    new, drift = [], []
    for r in fresh:
        o = seen.get(r["date"])
        if o is None:
            new.append(r)
        elif o["s"] != r["s"] or abs(o["x"] - r["x"]) > 1e-6:
            drift.append({"date": r["date"], "first": o, "now": r})
    return new, drift


def judge(obs: list[dict], today: pd.Timestamp) -> dict:
    n = len(obs)
    if not n:
        return {"n": 0, "judge": "거부 — 관측 없음"}
    first = pd.Timestamp(min(o["date"] for o in obs))
    age = (today - first).days
    flat = sum(1 for o in obs if o["s"] == 0)
    stage = "EXT" if n >= EXT and age >= EXT_MONTHS * 30 else "MAIN" if n >= GATE and age >= MONTHS * 30 else None
    if stage is None:
        return {"n": n, "ageDays": age, "flatDays": flat, "judge": f"거부 — {n}/{GATE} 거래일 · {age}/{MONTHS * 30}일(사전등록 §2)"}
    if flat < MIN_FLAT:
        return {"n": n, "flatDays": flat, "judge": "판정 불가 — 비운 날 10일 미만(연장 시점까지 대기)"}
    obs = sorted(obs, key=lambda o: o["date"])
    x = np.array([o["x"] for o in obs])
    s = np.array([o["s"] for o in obs], float)
    t2, hold = vt.perf(x, s, vt.FEE), vt.perf(x, np.ones(len(x)), 0.0)
    ds = t2["sharpe"] - hold["sharpe"]
    better_mdd = t2["mdd"] > hold["mdd"]
    v = "CONFIRMED" if ds > 0 and better_mdd else "REJECT" if ds <= 0 and not better_mdd else "INCONCLUSIVE"
    if v == "INCONCLUSIVE" and stage == "EXT":
        v = "INCONCLUSIVE(종결)"
    return {"n": n, "stage": stage, "flatDays": flat, "dSharpe": round(ds, 3), "T2": t2, "hold": hold, "verdict": v}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--judge", action="store_true")
    ap.add_argument("--selftest", action="store_true")
    a = ap.parse_args()
    if a.selftest:
        return selftest()
    obs = _read("observations.jsonl")
    today = pd.Timestamp.now(tz="America/New_York").tz_localize(None).normalize()
    if a.judge:
        print(json.dumps(judge(obs, today), ensure_ascii=False, indent=1, default=float))
        return 0
    new, drift = merge(obs, rows_from(fetch_df()))
    _append("observations.jsonl", new)
    _append("drift.jsonl", drift)
    allobs = obs + new
    summ = {"runAt": time.strftime("%Y-%m-%dT%H:%M:%S%z"), "observations": len(allobs), "newObservations": len(new),
            "drift": len(drift), "flatDays": sum(1 for o in allobs if o["s"] == 0), "judge": judge(allobs, today).get("judge")}
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "_summary.json").write_text(json.dumps(summ, ensure_ascii=False, indent=1), encoding="utf-8")
    print(json.dumps(summ, ensure_ascii=False))
    return 0


def selftest():
    ok = 0
    o = [{"date": "2026-11-02", "s": 1, "x": 0.001}]
    new, drift = merge(o, [{"date": "2026-11-02", "s": 1, "x": 0.001}, {"date": "2026-11-03", "s": 0, "x": -0.002}])
    assert [r["date"] for r in new] == ["2026-11-03"] and not drift; ok += 1
    _, drift = merge(o, [{"date": "2026-11-02", "s": 0, "x": 0.001}])
    assert len(drift) == 1; ok += 1                                         # 처음 본 값은 고쳐 쓰지 않고 drift 로
    assert "거부" in judge(o, pd.Timestamp("2027-01-01"))["judge"]; ok += 1
    rng = np.random.default_rng(3)
    d = pd.bdate_range("2026-11-02", periods=260)
    x = rng.normal(0.0003, 0.01, 260)
    s = np.ones(260)
    s[100:130] = 0
    x[100:130] = -0.02                                                      # 비운 동안 급락 → T2 가 낫다
    fake = [{"date": str(dd.date()), "s": int(ss), "x": float(xx)} for dd, ss, xx in zip(d, s, x)]
    j = judge(fake, pd.Timestamp("2027-12-01"))
    assert j["verdict"] == "CONFIRMED", j; ok += 1
    fake2 = [dict(f, s=1) if i % 7 else dict(f, s=0) for i, f in enumerate(fake)]
    for f in fake2[100:130]:
        f["s"] = 1                                                          # 급락 때 들고 있음
    assert judge(fake2, pd.Timestamp("2027-12-01"))["verdict"] in ("REJECT", "INCONCLUSIVE"); ok += 1
    print(f"selftest OK ({ok})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
