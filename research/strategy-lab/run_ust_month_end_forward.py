#!/usr/bin/env python3
"""미국 국채 월말 효과 forward 기록. 사전등록 findings/us-treasury-month-end-forward-preregistration-2026-11.md

    python research/strategy-lab/run_ust_month_end_forward.py            # 월간 점검(월 1회면 충분, 수 초) → reports/ 커밋
    python research/strategy-lab/run_ust_month_end_forward.py --judge    # 완결 월 ≥ 48 ∧ 48개월 전에는 건수만
    python research/strategy-lab/run_ust_month_end_forward.py --selftest

월 E = IEF 마지막 3거래일 일 수익 합 − 같은 달 나머지 평균 × 3 (탐색 us_treasury_month_end.py 와 같은 정의). 기록 전용 — 매매·알림 없음.
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
OUT = ROOT / "reports" / "2026-11-ust-month-end-forward"
FIRST = "2026-11"
GATE, EXT, COST_BP, ALPHA, NPERM, NBOOT, SEED, DRIFT_BP = 48, 72, 5.0, 0.05, 4000, 2000, 20261117, 0.5
W = 3


def fetch() -> pd.Series:
    import yfinance as yf
    for n in range(4):
        try:
            x = yf.download("IEF", start="2026-01-01", auto_adjust=True, progress=False)
            x.columns = x.columns.get_level_values(0)
            s = x["Close"].dropna()
            assert len(s) > 100, f"IEF 행 {len(s)}"                                        # 빈 응답을 성공으로 세지 않는다(교훈 81)
            return s.pct_change().dropna()
        except Exception:
            if n == 3:
                raise
            time.sleep(2 ** (n + 1))


def month_rows(r: pd.Series, today_ny: pd.Timestamp) -> list[dict]:
    """완결 월(오늘 미국 동부 날짜의 달보다 앞선 달) 중 FIRST 이후. E 와 그 달 모든 연속 W일 창 E."""
    cur = today_ny.strftime("%Y-%m")
    rows = []
    for k, g in r.groupby(r.index.strftime("%Y-%m")):
        if k < FIRST or k >= cur or len(g) < 15:
            continue
        v = g.to_numpy()
        csum = np.r_[0.0, np.cumsum(v)]
        wsum = csum[W:] - csum[:-W]
        E_all = wsum - W * (csum[-1] - wsum) / (len(v) - W)
        rows.append(dict(month=k, E=round(float(E_all[-1]), 8), n=len(v), alls=[round(float(x), 8) for x in E_all]))
    return rows


def _read(name):
    p = OUT / name
    return [json.loads(l) for l in p.read_text(encoding="utf-8").splitlines() if l.strip()] if p.exists() else []


def _append(name, rows):
    if rows:
        OUT.mkdir(parents=True, exist_ok=True)
        with open(OUT / name, "a", encoding="utf-8") as f:
            for r in rows:
                f.write(json.dumps(r, ensure_ascii=False) + "\n")


def merge(obs: list[dict], fresh: list[dict]):
    seen = {o["month"]: o for o in obs}
    new, drift = [], []
    for r in fresh:
        o = seen.get(r["month"])
        if o is None:
            new.append(r)
        elif abs(o["E"] - r["E"]) * 1e4 > DRIFT_BP:
            drift.append({"month": r["month"], "first": o["E"], "now": r["E"]})
    return new, drift


def judge(obs: list[dict], today_ny: pd.Timestamp) -> dict:
    n = len(obs)
    if not n:
        return {"n": 0, "judge": "거부 — 관측 없음"}
    first = pd.Timestamp(FIRST + "-01")
    age = (today_ny - first).days
    stage = "EXT" if n >= EXT and age >= EXT * 30 else "MAIN" if n >= GATE and age >= GATE * 30 else None
    E = np.array([o["E"] for o in obs])
    if stage is None:
        return {"n": n, "ageDays": age, "meanBp": round(float(E.mean()) * 1e4, 1), "judge": f"거부 — 완결 월 {n}/{GATE} · {age}/{GATE * 30}일(사전등록 §2)"}
    rng = np.random.default_rng(SEED)
    mean = float(E.mean())
    perm = np.array([np.mean([o["alls"][rng.integers(0, len(o["alls"]))] for o in obs]) for _ in range(NPERM)])
    p = float((1 + np.sum(perm >= mean)) / (1 + NPERM))
    bs = [np.mean(rng.choice(E, n)) for _ in range(NBOOT)]
    v = "REJECT" if mean <= 0 else "CONFIRMED" if mean * 1e4 > COST_BP and p <= ALPHA else "INCONCLUSIVE"
    if v == "INCONCLUSIVE" and stage == "EXT":
        v = "INCONCLUSIVE(종결)"
    return {"n": n, "stage": stage, "meanBp": round(mean * 1e4, 1), "ci95Bp": [round(float(np.percentile(bs, 2.5)) * 1e4, 1), round(float(np.percentile(bs, 97.5)) * 1e4, 1)],
            "pos": round(float((E > 0).mean() * 100)), "permP": round(p, 4), "verdict": v}


def selftest() -> int:
    ok = 0
    d = pd.bdate_range("2026-10-01", "2027-02-26")
    rng = np.random.default_rng(1)
    r = pd.Series(rng.normal(0, 0.003, len(d)), index=d)
    ends = r.groupby([r.index.year, r.index.month]).tail(3).index
    r[ends] += 0.01
    rows = month_rows(r, pd.Timestamp("2027-03-01"))
    assert [x["month"] for x in rows] == ["2026-11", "2026-12", "2027-01", "2027-02"], [x["month"] for x in rows]; ok += 1   # FIRST 이후 완결 월만
    assert len(month_rows(r, pd.Timestamp("2027-02-10"))) == 3; ok += 1                                                      # 진행 중인 달은 제외
    assert all(abs(x["alls"][-1] - x["E"]) < 1e-12 for x in rows) and rows[0]["E"] > 0.01; ok += 1                          # 마지막 창 = 관측 E
    new, drift = merge(rows[:2], rows[1:] + [dict(rows[0], E=rows[0]["E"] + 0.001)])
    assert [x["month"] for x in new] == ["2027-01", "2027-02"] and len(drift) == 1; ok += 1                                  # 처음 본 값은 고쳐 쓰지 않고 drift
    assert "거부" in judge(rows, pd.Timestamp("2030-01-01"))["judge"]; ok += 1                                               # 48개월 전엔 건수만
    fake = [dict(month=f"m{i}", E=0.002 + rng.normal(0, 0.003), alls=list(rng.normal(0, 0.003, 18))) for i in range(60)]
    j = judge(fake, pd.Timestamp("2031-12-01"))
    assert j["verdict"] == "CONFIRMED" and j["stage"] == "MAIN", j; ok += 1
    print(f"selftest OK ({ok})")
    return 0


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
    new, drift = merge(obs, month_rows(fetch(), today))
    _append("observations.jsonl", new)
    _append("drift.jsonl", drift)
    allobs = obs + new
    summ = {"runAt": time.strftime("%Y-%m-%dT%H:%M:%S%z"), "observations": len(allobs), "newObservations": len(new), "drift": len(drift),
            "judge": judge(allobs, today).get("judge", "판정 가능")}
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "_summary.json").write_text(json.dumps(summ, ensure_ascii=False, indent=1), encoding="utf-8")
    print(json.dumps(summ, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
