#!/usr/bin/env python3
"""LETF 마감 리밸런싱 반전 forward 기록. 사전등록 findings/letf-close-reversal-forward-preregistration-2026-11.md

    python research/strategy-lab/run_letf_reversal_forward.py            # 월간 점검(수 초, 야후 일봉) → reports/2026-11-letf-reversal-forward/ 커밋
    python research/strategy-lab/run_letf_reversal_forward.py --judge    # 1차 사건일 ≥60 ∧ 2027-08-30 · 최종 ≥120 ∧ 2028-05-30 전에는 건수만
    python research/strategy-lab/run_letf_reversal_forward.py --selftest

기록 전용 — 매매·알림 없음. 성숙한 사건(t+1 종가까지 나온 것)만 한 번 쓰고, 야후가 나중에 바꾸면 drift.jsonl 에만 남긴다.
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
OUT = HERE.parents[1] / "reports" / "2026-11-letf-reversal-forward"
START = pd.Timestamp("2026-11-30")                      # 사건 한국 거래일 t 의 하한
THR, COST = 0.03, 0.002354                              # |SMH 야간| 문턱 · 종가 단일가 왕복
GATE1, DATE1, GATE2, DATE2 = 60, pd.Timestamp("2027-08-30"), 120, pd.Timestamp("2028-05-30")
T1, T2, MIN_CTRL = 2.0, 1.75, 15
TARGET = {"000660": "000660.KS", "005930": "005930.KS"}
CTRL = {c: c + (".KQ" if c in ("196170", "386380", "086520", "036930", "179880") else ".KS") for c in
        "009150 005380 034020 402340 035420 042660 012450 006400 042700 196170 066570 386380 086520 105560 064350 272210 329180 000270 047040 010140 035720 036930 012330 179880 373220".split()}


def fetch(tickers: list[str]) -> pd.DataFrame:
    import yfinance as yf
    for n in range(4):
        try:
            x = yf.download(tickers, start="2026-11-16", auto_adjust=True, progress=False)["Close"]
            if isinstance(x, pd.Series):
                x = x.to_frame(tickers[0])
            x.index = pd.to_datetime(x.index).tz_localize(None)
            assert x.shape[0] > 3, "행 부족"                                          # 빈 응답을 성공으로 세지 않는다(교훈 81)
            return x
        except Exception:
            if n == 3:
                raise
            time.sleep(2 ** (n + 1))


def make_rows(px: pd.DataFrame, smh: pd.Series, today: pd.Timestamp) -> list[dict]:
    """px: 한국 종목·^KS11 종가(열=야후 티커), smh: 미국 SMH 종가. 성숙한 사건 행만."""
    kr = px["^KS11"].dropna().index
    kr, ret = kr[kr < today.normalize()], px.pct_change(fill_method=None)      # 오늘 행은 장중 미확정이라 쓰지 않는다
    us = smh.pct_change().dropna()
    rows = []
    for i in range(1, len(kr) - 1):
        t, prev, nxt = kr[i], kr[i - 1], kr[i + 1]
        if t < START:
            continue
        d = us.index[us.index < t]
        if len(d) == 0 or d[-1] < prev or abs(us[d[-1]]) < THR:     # 직전 미국 장이 직전 한국 장 뒤에 열렸고 3% 이상
            continue
        for grp, mp in (("target", TARGET), ("ctrl", CTRL)):
            for tk, yt in mp.items():
                if yt not in ret:
                    continue
                x = ret.at[t, yt] - ret.at[t, "^KS11"]
                y = ret.at[nxt, yt] - ret.at[nxt, "^KS11"]
                if np.isfinite(x) and np.isfinite(y) and x != 0:
                    rows.append(dict(date=str(t.date()), tk=tk, grp=grp, smhDate=str(d[-1].date()), smh=round(float(us[d[-1]]), 6),
                                     x=round(float(x), 8), y=round(float(y), 8), rev=round(float(-np.sign(x) * y), 8)))
    return rows


def nw_t(v: np.ndarray) -> float:
    """평균/표준오차, Newey-West lag 1(다음 날 겹침), 단측용 t."""
    n, m = len(v), v.mean()
    if n < 3:
        return float("nan")
    e = v - m
    var = (e @ e + 2 * (1 - 0.5) * (e[1:] @ e[:-1])) / n
    return float(m / np.sqrt(max(var, 1e-18) / n))


def daily(obs: list[dict]) -> pd.DataFrame:
    df = pd.DataFrame(obs)
    if df.empty:
        return pd.DataFrame(columns=["P", "C", "D"])
    P = df[df.grp == "target"].groupby("date")["rev"].mean()
    g = df[df.grp == "ctrl"].groupby("date")["rev"].agg(["mean", "count"])
    C = g["mean"].where(g["count"] >= MIN_CTRL)
    out = pd.DataFrame({"P": P}).join(C.rename("C"), how="left")
    out["D"] = out["P"] - out["C"]
    return out.sort_index()


def judge(obs: list[dict], today: pd.Timestamp) -> dict:
    d = daily(obs)
    n = int(d["P"].notna().sum())
    base = {"n": n, "startDate": str(START.date())}
    if not (n >= GATE1 and today >= DATE1):
        return base | {"judge": f"거부 — {n}/{GATE1} 사건일 · {today.date()} < {DATE1.date()}(사전등록 §3)"}
    final = n >= GATE2 and today >= DATE2
    thr = T2 if final else T1
    dd = d.dropna(subset=["P", "D"])
    mp, md = float(dd["P"].mean() - COST), float(dd["D"].mean())
    tp, td = nw_t((dd["P"] - COST).to_numpy()), nw_t(dd["D"].to_numpy())
    if mp <= 0 or md <= 0:
        v = "REJECT"
    elif tp >= thr and td >= thr:
        v = "SUPPORTED"
    else:
        v = "REJECT" if final else "계속"
    return base | {"stage": "최종" if final else "1차", "netMean": round(mp, 6), "diffMean": round(md, 6), "tNet": round(tp, 2),
                   "tDiff": round(td, 2), "nDiffDays": len(dd), "verdict": v}


def _read(name):
    p = OUT / name
    return [json.loads(l) for l in p.read_text(encoding="utf-8").splitlines() if l.strip()] if p.exists() else []


def _append(name, rows):
    if rows:
        OUT.mkdir(parents=True, exist_ok=True)
        with open(OUT / name, "a", encoding="utf-8") as f:
            for r in rows:
                f.write(json.dumps(r, ensure_ascii=False) + "\n")


def merge(obs, fresh):
    seen = {(o["date"], o["tk"]): o for o in obs}
    new, drift = [], []
    for r in fresh:
        o = seen.get((r["date"], r["tk"]))
        if o is None:
            new.append(r)
        elif abs(o["x"] - r["x"]) > 1e-6 or abs(o["y"] - r["y"]) > 1e-6:
            drift.append({"date": r["date"], "tk": r["tk"], "first": o, "now": r})
    return new, drift


def selftest() -> int:
    ok = 0
    kr = pd.bdate_range("2026-11-26", periods=6)                 # 11-26 ~ 12-03
    px = pd.DataFrame(100.0, index=kr, columns=["^KS11"] + list(TARGET.values()) + list(CTRL.values()))
    px.loc[kr[2], "000660.KS"] = 106.0                           # 11-30(t): 하이닉스 +6% (시장 0%) → X>0
    px.loc[kr[3], "000660.KS"] = 103.0                           # 12-01: 106→103 = −2.83% → 반전 +
    smh = pd.Series([100.0, 100.0, 94.0, 94.0, 94.0, 94.0, 94.0], index=pd.bdate_range("2026-11-25", periods=7))   # 11-27(d) −6%
    rows = make_rows(px, smh, pd.Timestamp("2026-12-10"))
    h = [r for r in rows if r["tk"] == "000660" and r["date"] == "2026-11-30"]
    assert len(h) == 1 and h[0]["rev"] > 0.028 and h[0]["smhDate"] == "2026-11-27", rows[:2]; ok += 1
    assert all(r["date"] >= "2026-11-30" for r in rows); ok += 1                                  # 시작일 전 사건 없음
    assert not [r for r in rows if r["tk"] == "005930"]; ok += 1                                  # X=0 이면 뺀다
    new, drift = merge(rows, [dict(h[0], x=h[0]["x"] + 0.01)])
    assert not new and len(drift) == 1; ok += 1                                                   # 처음 값은 고쳐 쓰지 않는다
    assert "거부" in judge(rows, pd.Timestamp("2027-01-01"))["judge"]; ok += 1                    # 판정 시점 전 거부
    rng = np.random.default_rng(1)
    obs = []
    for i, dt in enumerate(pd.bdate_range("2026-12-01", periods=130)):
        for tk in TARGET:
            obs.append(dict(date=str(dt.date()), tk=tk, grp="target", rev=float(rng.normal(0.02, 0.01))))
        for tk in list(CTRL)[:20]:
            obs.append(dict(date=str(dt.date()), tk=tk, grp="ctrl", rev=float(rng.normal(0.0, 0.01))))
    j = judge(obs, pd.Timestamp("2028-06-01"))
    assert j["verdict"] == "SUPPORTED" and j["stage"] == "최종", j; ok += 1
    obs2 = [dict(o, rev=-abs(o["rev"])) for o in obs]
    assert judge(obs2, pd.Timestamp("2028-06-01"))["verdict"] == "REJECT"; ok += 1
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
        print(json.dumps(judge(obs, today), ensure_ascii=False, indent=1, default=float))
        return 0
    names = ["^KS11"] + list(TARGET.values()) + list(CTRL.values())
    px = fetch(names)
    lost = [n for n in names if n not in px or px[n].dropna().empty]
    assert "^KS11" not in lost and not [n for n in TARGET.values() if n in lost], f"핵심 시세 없음 {lost}"
    smh = fetch(["SMH"])["SMH"].dropna()
    new, drift = merge(obs, make_rows(px, smh, today))
    _append("observations.jsonl", new)
    _append("drift.jsonl", drift)
    allobs = obs + new
    summ = {"runAt": time.strftime("%Y-%m-%dT%H:%M:%S%z"), "observations": len(allobs), "newObservations": len(new), "drift": len(drift),
            "lostTickers": lost, "lastPriceDate": str(px.index[-1].date()), **judge(allobs, today)}
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "_summary.json").write_text(json.dumps(summ, ensure_ascii=False, indent=1), encoding="utf-8")
    print(json.dumps(summ, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
