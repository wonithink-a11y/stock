#!/usr/bin/env python3
"""월말 달러 forward 기록. 사전등록 findings/dollar-month-end-forward-preregistration-2026-11.md (blob 20fa8023)

    python research/strategy-lab/run_dollar_month_end_forward.py            # 월간 점검(월 1회면 충분, 수 초) → reports/ 커밋
    python research/strategy-lab/run_dollar_month_end_forward.py --judge    # 완결 월 ≥ 36 ∧ 36개월 전에는 건수만
    python research/strategy-lab/run_dollar_month_end_forward.py --selftest

월 E(bp) = −sign(^IXIC 전월말 → 마지막 거래일 전날 종가 수익) × DX-Y.NYB 마지막 거래일 일 수익 (탐색 dollar_month_end.py 와 같은 정의, 방향 고정).
기록 전용 — 매매·알림 없음. 관측 행은 처음 본 값을 한 번만 쓰고, 달라지면 drift.jsonl 에 남긴다.
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
OUT = ROOT / "reports" / "2026-11-dollar-month-end-forward"
FIRST = "2026-11"
GATE, EXT, COST_BP, ALPHA, NPERM, NBOOT, SEED, DRIFT_BP = 36, 60, 5.0, 0.05, 5000, 2000, 20261122, 0.5


def fetch(tk: str) -> pd.Series:
    import yfinance as yf
    for n in range(4):
        try:
            x = yf.download(tk, start="2026-09-01", auto_adjust=True, progress=False)
            x.columns = x.columns.get_level_values(0)
            s = x["Close"].dropna()
            s.index = pd.to_datetime(s.index).tz_localize(None).normalize()
            assert len(s) > 30, f"{tk} 행 {len(s)}"                                        # 빈 응답을 성공으로 세지 않는다(교훈 81)
            return s.sort_index()
        except Exception:
            if n == 3:
                raise
            time.sleep(2 ** (n + 1))


def month_rows(ix: pd.Series, dxy: pd.Series, alt: pd.Series | None, today_ny: pd.Timestamp) -> list[dict]:
    """완결 월(오늘 미국 동부 날짜의 달보다 앞선 달) 중 FIRST 이후. ix 거래일 달력 기준."""
    cur = today_ny.strftime("%Y-%m")
    keys = ix.index.strftime("%Y-%m")
    rows = []
    for k in sorted(set(keys)):
        if k < FIRST or k >= cur:
            continue
        idx = np.nonzero(keys == k)[0]
        if idx[0] == 0 or len(idx) < 5:
            continue
        d = ix.index
        n, n1, n3, prev = d[idx[-1]], d[idx[-2]], d[idx[-4]], d[idx[0] - 1]
        if n not in dxy.index or n1 not in dxy.index or n3 not in dxy.index:
            continue
        s = float(np.sign(ix[n1] / ix[prev] - 1))
        if s == 0:
            continue
        s3 = float(np.sign(ix[n3] / ix[prev] - 1))
        r1 = float(dxy[n] / dxy[n1] - 1)
        r3 = float(dxy[n] / dxy[n3] - 1)
        sa = float(np.sign(alt[n1] / alt[prev] - 1)) if alt is not None and n1 in alt.index and prev in alt.index else np.nan
        rows.append(dict(month=k, s=s, E=round(-s * r1 * 1e4, 6), r1=round(r1, 8),
                         E3=round(-s3 * r3 * 1e4, 6), Ealt=None if np.isnan(sa) else round(-sa * r1 * 1e4, 6), lastDay=str(n.date())))
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
        elif abs(o["E"] - r["E"]) > DRIFT_BP:
            drift.append({"month": r["month"], "first": o["E"], "now": r["E"]})
    return new, drift


def judge(obs: list[dict], today_ny: pd.Timestamp) -> dict:
    n = len(obs)
    if not n:
        return {"n": 0, "judge": "거부 — 관측 없음"}
    first = pd.Timestamp(FIRST + "-01")
    age = (today_ny - first).days
    stage = "EXT" if n >= EXT and age >= EXT * 30 else "MAIN" if n >= GATE and age >= GATE * 30 else None
    E = np.array([o["E"] for o in obs], float)
    if stage is None:
        return {"n": n, "ageDays": age, "meanBp": round(float(E.mean()), 1), "judge": f"거부 — 완결 월 {n}/{GATE} · {age}/{GATE * 30}일(사전등록 §2)"}
    rng = np.random.default_rng(SEED)
    s = np.array([o["s"] for o in obs], float)
    r1 = np.array([o["r1"] for o in obs], float)
    mean = float(E.mean())
    perm = np.array([np.mean(-rng.permutation(s) * r1) * 1e4 for _ in range(NPERM)])
    p = float((1 + np.sum(perm >= mean)) / (1 + NPERM))
    bs = [np.mean(rng.choice(E, n)) for _ in range(NBOOT)]
    v = "REJECT" if mean <= 0 else "CONFIRMED" if mean > COST_BP and p <= ALPHA else "INCONCLUSIVE"
    if v == "INCONCLUSIVE" and stage == "EXT":
        v = "INCONCLUSIVE(종결)"
    return {"n": n, "stage": stage, "meanBp": round(mean, 1), "ci95Bp": [round(float(np.percentile(bs, 2.5)), 1), round(float(np.percentile(bs, 97.5)), 1)],
            "pos": round(float((E > 0).mean() * 100)), "permP": round(p, 4), "verdict": v,
            "recordOnly": {"oppositeDirectionMeanBp": round(-mean, 1)}}


def selftest() -> int:
    ok = 0
    d = pd.bdate_range("2026-10-01", "2027-02-26")
    rng = np.random.default_rng(1)
    up = pd.Series(100 + np.arange(len(d)) * 0.5, index=d)                                   # 계속 상승 → 신호 s=+1
    dx = pd.Series(100 * (1 + rng.normal(0, 0.003, len(d))).cumprod(), index=d)
    rows = month_rows(up, dx, up, pd.Timestamp("2027-03-01"))
    assert [x["month"] for x in rows] == ["2026-11", "2026-12", "2027-01", "2027-02"], [x["month"] for x in rows]; ok += 1   # FIRST 이후 완결 월만
    assert len(month_rows(up, dx, None, pd.Timestamp("2027-02-10"))) == 3; ok += 1                                           # 진행 중인 달은 제외
    assert all(x["s"] == 1.0 for x in rows); ok += 1                                                                         # 상승장은 s=+1(달러 약세 베팅)
    last = d[(d.strftime("%Y-%m") == "2026-11")][-1]
    prev1 = d[(d.strftime("%Y-%m") == "2026-11")][-2]
    assert abs(rows[0]["E"] - (-(dx[last] / dx[prev1] - 1) * 1e4)) < 1e-4; ok += 1                                           # E = −s × 마지막 날 달러 수익
    new, drift = merge(rows[:2], rows[1:] + [dict(rows[0], E=rows[0]["E"] + 1.0)])
    assert [x["month"] for x in new] == ["2026-12", "2027-01", "2027-02"][1:] and len(drift) == 1; ok += 1                    # 처음 본 값은 고쳐 쓰지 않고 drift
    assert "거부" in judge(rows, pd.Timestamp("2030-01-01"))["judge"]; ok += 1                                                # 36개월 전엔 건수만
    fake = [dict(month=f"m{i}", s=float(rng.choice([-1, 1])), r1=0.0, E=8.0 + rng.normal(0, 3)) for i in range(40)]
    sgn = np.array([f["s"] for f in fake])
    ret = -sgn * 0.0008 + rng.normal(0, 0.0005, 40)                                          # 신호와 반대로 움직이는 달러
    for f, r in zip(fake, ret):
        f["r1"] = float(r)
        f["E"] = float(-f["s"] * r * 1e4)
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
    new, drift = merge(obs, month_rows(fetch("^IXIC"), fetch("DX-Y.NYB"), fetch("^GSPC"), today))
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
