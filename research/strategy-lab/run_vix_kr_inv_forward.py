#!/usr/bin/env python3
"""VIX 한국 지수 R1(kr)·인버스 B(inv) forward 기록. 사전등록 findings/vix-kr-inverse-forward-preregistration-2026-11.md

    python research/strategy-lab/run_vix_kr_inv_forward.py            # 월간 점검(자주 돌려도 됨, 수 초) → reports/ 커밋
    python research/strategy-lab/run_vix_kr_inv_forward.py --judge    # 성숙 250거래일 ∧ 12개월 전에는 건수만
    python research/strategy-lab/run_vix_kr_inv_forward.py --selftest

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
OUT = ROOT / "reports" / "2026-11-vix-kr-inv-forward"
START = pd.Timestamp("2026-11-18")
COST, ALPHA, PERM, SEED = 0.0005, 0.05 / 4, 4000, 20261117
GATE, MONTHS, EXT, EXT_MONTHS, MIN_FLAT, MIN_ENTRY = 250, 12, 500, 24, 10, 3
KR = {"^KS11": "KOSPI", "^KQ11": "KOSDAQ"}


def fetch(tk: str, adj: bool = True) -> pd.DataFrame:
    import yfinance as yf
    for n in range(4):
        try:
            x = yf.download(tk, start="2010-06-01", auto_adjust=adj, progress=False)
            x.columns = x.columns.get_level_values(0)
            x = x[["Open", "Close"]].dropna().rename(columns={"Open": "O", "Close": "C"})
            assert len(x) > 1000, f"{tk} 행 {len(x)}"                              # 빈 응답을 성공으로 세지 않는다(교훈 81)
            return x
        except Exception:
            if n == 3:
                raise
            time.sleep(2 ** (n + 1))


def positions(vix: np.ndarray, arm: str) -> np.ndarray:
    """T[t] = 봉 t 종가 뒤 목표 포지션. kr: ≤14 현금 / ≥20 매수, 사이 유지, 매수로 시작. inv: ≥20 매수 / ≤16 현금, 현금으로 시작."""
    T, cur = np.zeros(len(vix)), 1.0 if arm == "kr" else 0.0
    T[0] = cur
    for i in range(1, len(vix)):
        v = vix[i]
        if not np.isnan(v):
            if arm == "kr":
                cur = 0.0 if v <= 14 else 1.0 if v >= 20 else cur
            else:
                cur = 1.0 if (cur == 0 and v >= 20) else 0.0 if (cur == 1 and v <= 16) else cur
        T[i] = cur
    return T


def rows_for(arm: str, mk: str, f: pd.DataFrame, vix: pd.Series, init: float) -> list[dict]:
    sig = vix.reindex(vix.index.union(f.index)).ffill().reindex(f.index)            # 같은 달력일(없으면 직전) 미국 VIX
    if arm == "kr":                                                                 # 원 연구와 같이 2011-01-03 직전 봉에서 매수로 시작
        i0 = int(f.index.searchsorted(pd.Timestamp("2011-01-03")))
        f, sig = f.iloc[i0 - 1:], sig.iloc[i0 - 1:]
    T = positions(sig.to_numpy(float), arm)
    O, C = f["O"].to_numpy(float), f["C"].to_numpy(float)
    gon, gid = O[1:] / C[:-1] - 1, C[1:] / O[1:] - 1
    s1, s2 = T[:-1], np.r_[init, T[:-2]]                                            # s1 = 봉 t 시가 이후, s2 = 밤사이(전전 신호)
    today = pd.Timestamp.now(tz="Asia/Seoul").tz_localize(None).normalize()
    return [dict(arm=arm, mk=mk, date=str(d.date()), s1=float(a), s2=float(b), gon=round(float(g), 8), gid=round(float(h), 8))
            for d, a, b, g, h in zip(f.index[1:], s1, s2, gon, gid) if START <= d < today]


def rule_ret(g):
    gon, gid, s1, s2 = (np.array([r[k] for r in g], float) for k in ("gon", "gid", "s1", "s2"))
    return (1 + s2 * gon) * (1 + s1 * gid) - 1 - COST * np.abs(s1 - s2), (1 + gon) * (1 + gid) - 1


def sharpe(r):
    sd = r.std(ddof=1)
    return float(r.mean() / sd * np.sqrt(252)) if len(r) > 2 and sd > 0 else 0.0


def mdd(r):
    eq = np.cumprod(1 + r)
    return float((eq / np.maximum.accumulate(eq) - 1).min())


def perm_p(groups, sh_obs, rng):
    """관측 창 포지션 열을 같은 폭으로 원형 이동 → (대상 평균) 규칙 샤프가 관측 이상인 비율."""
    n = min(len(g) for g in groups)
    arr = [tuple(np.array([r[x] for r in g], float) for x in ("gon", "gid", "s1", "s2")) for g in groups]
    hit = 0
    for _ in range(PERM):
        k = int(rng.integers(21, n - 21))
        sh = []
        for gon, gid, s1, s2 in arr:
            a, b = np.roll(s1, k), np.roll(s2, k)
            sh.append(sharpe((1 + b * gon) * (1 + a * gid) - 1 - COST * np.abs(a - b)))
        hit += float(np.mean(sh)) >= sh_obs
    return (hit + 1) / (PERM + 1)


def judge(arm: str, obs: list[dict], today: pd.Timestamp) -> dict:
    g = {mk: sorted([o for o in obs if o["arm"] == arm and o["mk"] == mk], key=lambda o: o["date"]) for mk in
         sorted({o["mk"] for o in obs if o["arm"] == arm})}
    if not g:
        return {"n": 0, "judge": "거부 — 관측 없음"}
    n = min(len(v) for v in g.values())
    age = (today - START).days
    stage = "EXT" if n >= EXT and age >= EXT_MONTHS * 30 else "MAIN" if n >= GATE and age >= MONTHS * 30 else None
    flat = sum(o["s1"] == 0 for v in g.values() for o in v)
    entries = sum(o["s1"] > o["s2"] for v in g.values() for o in v)
    if stage is None:
        return {"n": n, "ageDays": age, "flatDays": flat, "entries": entries, "judge": f"거부 — {n}/{GATE} 거래일 · {age}/{MONTHS * 30}일(사전등록 §4)"}
    if (arm == "kr" and flat < MIN_FLAT) or (arm == "inv" and entries < MIN_ENTRY):
        return {"n": n, "flatDays": flat, "entries": entries, "judge": "판정 불가 — 규칙이 거의 작동하지 않음(연장 시점까지 대기)"}
    res = {mk: rule_ret(v) for mk, v in g.items()}
    dsh = float(np.mean([sharpe(r) - sharpe(b) for r, b in res.values()]))
    sh_obs = float(np.mean([sharpe(r) for r, _ in res.values()]))
    p = perm_p(list(g.values()), sh_obs, np.random.default_rng(SEED))
    if arm == "kr":
        better = all(mdd(r) > mdd(b) for r, b in res.values())
        v = "CONFIRMED" if dsh > 0 and better and p <= ALPHA else "REJECT" if dsh <= 0 else "INCONCLUSIVE"
    else:
        r, b = next(iter(res.values()))
        total = float(np.prod(1 + r) - 1)
        v = "CONFIRMED" if dsh > 0 and total > 0 and p <= ALPHA else "REJECT" if dsh <= 0 and total <= 0 else "INCONCLUSIVE"
    if v == "INCONCLUSIVE" and stage == "EXT":
        v = "INCONCLUSIVE(종결)"
    return {"n": n, "stage": stage, "flatDays": flat, "entries": entries, "dSharpe": round(dsh, 3), "permP": round(p, 4), "verdict": v}


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
    seen = {(o["arm"], o["mk"], o["date"]): o for o in obs}
    new, drift = [], []
    for r in fresh:
        o = seen.get((r["arm"], r["mk"], r["date"]))
        if o is None:
            new.append(r)
        elif o["s1"] != r["s1"] or o["s2"] != r["s2"] or abs(o["gon"] - r["gon"]) > 1e-6 or abs(o["gid"] - r["gid"]) > 1e-6:
            drift.append({"date": r["date"], "mk": r["mk"], "first": o, "now": r})
    return new, drift


def selftest() -> int:
    ok = 0
    v = np.array([15, 21, 18, 15, 13, 19, 21, 25.0])
    assert list(positions(v, "kr")) == [1, 1, 1, 1, 0, 0, 1, 1], positions(v, "kr"); ok += 1       # ≤14 현금, ≥20 매수
    assert list(positions(v, "inv")) == [0, 1, 1, 0, 0, 0, 1, 1], positions(v, "inv"); ok += 1     # ≥20 매수 ≤16 현금
    mk = lambda i, s1, s2, gon, gid: dict(arm="inv", mk="SVXY", date=str(pd.Timestamp("2026-11-18") + pd.Timedelta(days=i))[:10], s1=s1, s2=s2, gon=gon, gid=gid)
    r, b = rule_ret([mk(0, 1.0, 0.0, 0.01, 0.02)])
    assert abs(r[0] - (1.02 - 1 - COST)) < 1e-12 and abs(b[0] - (1.01 * 1.02 - 1)) < 1e-12; ok += 1   # 밤사이는 이전(현금), 장중은 신규 + 전환 비용
    new, drift = merge([mk(0, 1, 0, 0.01, 0.02)], [mk(0, 1, 0, 0.01, 0.02), mk(1, 0, 1, 0.0, 0.0), mk(0, 1, 0, 0.011, 0.02)])
    assert len(new) == 1 and len(drift) == 1; ok += 1                                               # 처음 본 값은 고쳐 쓰지 않고 drift 로
    assert "거부" in judge("inv", [mk(0, 1, 0, 0.01, 0.02)], pd.Timestamp("2027-06-01"))["judge"]; ok += 1
    rng = np.random.default_rng(3)
    d = pd.bdate_range("2026-11-18", periods=300)
    s1 = np.ones(300); s1[100:130] = 0
    s2 = np.r_[1.0, s1[:-1]]
    gon = rng.normal(0.0003, 0.004, 300); gid = rng.normal(0.0003, 0.004, 300)
    gon[100:130] = gid[100:130] = -0.02                                                             # 비운 동안 급락 → 규칙이 낫다
    fake = [dict(arm="kr", mk=m, date=str(x.date()), s1=float(a), s2=float(b), gon=float(g), gid=float(h))
            for m in ("^KS11", "^KQ11") for x, a, b, g, h in zip(d, s1, s2, gon, gid)]
    j = judge("kr", fake, pd.Timestamp("2028-01-01"))
    assert j["verdict"] == "CONFIRMED", j; ok += 1
    flat_ok = [dict(o, s1=1.0, s2=1.0) for o in fake]
    assert "판정 불가" in judge("kr", flat_ok, pd.Timestamp("2028-01-01"))["judge"]; ok += 1           # 현금 날 10일 미만
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
    today = pd.Timestamp.now(tz="Asia/Seoul").tz_localize(None).normalize()
    if a.judge:
        print(json.dumps({arm: judge(arm, obs, today) for arm in ("kr", "inv")}, ensure_ascii=False, indent=1, default=float))
        return 0
    vix = fetch("^VIX", adj=False)["C"]
    fresh = [r for tk, nm in KR.items() for r in rows_for("kr", tk, fetch(tk), vix, 1.0)]
    fresh += rows_for("inv", "SVXY", fetch("SVXY"), vix, 0.0)
    new, drift = merge(obs, fresh)
    _append("observations.jsonl", new)
    _append("drift.jsonl", drift)
    allobs = obs + new
    summ = {"runAt": time.strftime("%Y-%m-%dT%H:%M:%S%z"), "observations": len(allobs), "newObservations": len(new), "drift": len(drift),
            **{arm: judge(arm, allobs, today).get("judge", "판정 가능") for arm in ("kr", "inv")}}
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "_summary.json").write_text(json.dumps(summ, ensure_ascii=False, indent=1), encoding="utf-8")
    print(json.dumps(summ, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
