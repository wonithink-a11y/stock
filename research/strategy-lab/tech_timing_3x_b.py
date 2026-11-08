#!/usr/bin/env python3
"""커뮤니티 17규칙 × NDX·SOX 합성 3배, 기존 54 + 17 = 71규칙 × 코스피 합성 2배 — 사전등록 findings/tech-timing-3x-b-preregistration-2026-11.md

    python research/strategy-lab/tech_timing_3x_b.py --selftest
    python research/strategy-lab/tech_timing_3x_b.py
"""
import argparse
import json
import sys
from collections import Counter
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
import tech_timing_3x as B  # noqa: E402  (동결된 1차 코드의 지표·상태기계·판정 재사용)

ROOT = B.ROOT


def lev_ret(close, lev, drag_year):
    return (lev * close.pct_change() - drag_year / 252).fillna(0.0).values


def wma(s, n):
    w = np.arange(1, n + 1)
    return s.rolling(n).apply(lambda x: (x * w).sum() / w.sum(), raw=True)


def community_rules(df: pd.DataFrame, vix_raw: pd.Series, lev: int) -> dict:
    c, h, l = df["Close"], df["High"], df["Low"]
    idx = df.index
    b = lambda s: s.fillna(False).values.astype(bool)
    i8 = lambda s: s.fillna(False).values.astype(np.int8)
    R = {}
    s200, s5 = B.sma(c, 200), B.sma(c, 5)
    r2 = B.rsi(c, 2)
    R["C1 RSI2추세"] = B.state(b((c > s200) & (r2 < 10)), b(c > s5))
    ibs = (c - l) / (h - l)
    R["C2 IBS"] = B.state(b(ibs < 0.2), b(c > h.shift()))
    R["C3 Double7"] = B.state(b((c <= c.rolling(7).min()) & (c > s200)), b(c >= c.rolling(7).max()))
    dn3 = (c < c.shift()) & (c.shift() < c.shift(2)) & (c.shift(2) < c.shift(3))
    R["C4 3일연속하락"] = B.state(b(dn3), b(c > s5))
    R["C5 SMA200밴드3%"] = B.state(b(c > 1.03 * s200), b(c < 0.97 * s200))
    ym = pd.Series(idx.year * 100 + idx.month, index=idx)
    last = ym != ym.shift(-1)
    def monthly(cond):
        sig = cond.astype(float).where(last)
        return i8(sig.ffill())
    R["C6 월말SMA210"] = monthly(c > B.sma(c, 210))
    R["C7 12개월모멘텀(월말)"] = monthly(c / c.shift(252) - 1 > 0)
    v = vix_raw.reindex(idx).ffill()
    dnv = (v < v.shift()) & (v.shift() < v.shift(2)) & (v.shift(2) < v.shift(3))
    R["C8 VIX>30후3일하락"] = B.state(b((v >= 30) & dnv), b(v < 20))
    v10 = B.sma(v, 10)
    R["C9 VIX스파이크"] = B.state(b(v >= 1.10 * v10), b(v < v10))
    R["C10 변동성관리"] = np.minimum(1.0, 20.0 / (lev * v)).fillna(0.0).values.astype(float)
    e20 = B.ema(c, 20)
    R["C12 켈트너"] = B.state(b(c > e20 + 2 * B.atr(df, 10)), b(c < e20))
    tp = (h + l + c) / 3
    mad = tp.rolling(20).apply(lambda x: np.abs(x - x.mean()).mean(), raw=True)
    cci = (tp - B.sma(tp, 20)) / (0.015 * mad)
    R["C13 CCI20"] = B.state(b(cci > 100), b(cci < 0))
    hh, ll = h.rolling(14).max(), l.rolling(14).min()
    wr = -100 * (hh - c) / (hh - ll)
    R["C14 윌리엄스%R"] = B.state(b(wr < -80), b(wr > -50))
    au = h.rolling(26).apply(lambda x: 100 * np.argmax(x) / 25, raw=True)
    ad = l.rolling(26).apply(lambda x: 100 * np.argmin(x) / 25, raw=True)
    R["C15 아룬25"] = i8((au > 70) & (ad < 30))
    r10 = c / c.shift(10) - 1
    R["C16 10일급락반등"] = B.state(b(r10 <= -0.05), b(r10 > 0))
    hma = wma(2 * wma(c, 25) - wma(c, 50), 7)
    R["C17 헐50기울기"] = i8(hma > hma.shift())
    R["C22 산타"] = ((idx.month == 12) & (idx.day >= 15) | (idx.month == 1) & (idx.day <= 5)).astype(np.int8)
    return R


def evaluate(df, rules: dict, lev: int, drag: float):
    idx = df.index
    r3 = lev_ret(df["Close"], lev, drag)
    start = 252
    bh = np.ones(len(idx))
    rng = np.random.default_rng(B.SEED)
    bounds = {}
    for k, (s, e) in B.PERIODS.items():
        ii = np.where((idx >= s) & (idx <= e))[0]
        ii = ii[ii >= start]
        bounds[k] = (ii[0], ii[-1] + 1) if len(ii) else None
    bh_r = B.strat_ret(bh, r3)
    bh_m = {k: B.metrics(bh_r[a:b], bh[a:b]) for k, (a, b) in bounds.items() if bounds[k]}
    res = {}
    for rn, pos in rules.items():
        pos = np.asarray(pos, dtype=float)
        sr = B.strat_ret(pos, r3)
        row = {}
        for k, bd in bounds.items():
            if not bd:
                continue
            a, b = bd
            m = B.metrics(sr[a:b], pos[a:b])
            m["dSharpe"] = round(m["sharpe"] - bh_m[k]["sharpe"], 3)
            m["p"] = B.perm_p(pos, r3, a, b, rng)
            row[k] = m
        res[rn] = row
    return res, bh_m, bounds


def selftest() -> int:
    fails = []
    def ck(n, c):
        print(("ok   " if c else "FAIL ") + n)
        if not c: fails.append(n)
    ck("2배 일수익", abs(lev_ret(pd.Series([100.0, 101.0]), 2, 0.02)[1] - (0.02 - 0.02 / 252)) < 1e-12)
    w = wma(pd.Series(np.arange(1.0, 11.0)), 3)
    ck("WMA 계산", abs(w.iloc[-1] - (8 * 1 + 9 * 2 + 10 * 3) / 6) < 1e-12)
    idx = pd.bdate_range("2020-01-01", periods=300)
    df = pd.DataFrame({"Open": 100.0, "High": 101.0 + np.arange(300) * .01, "Low": 99.0 + np.arange(300) * .01, "Close": 100.0 + np.arange(300) * .01}, index=idx)
    vix = pd.Series(18.0, index=idx)
    R = community_rules(df, vix, 3)
    ck("규칙 17개", len(R) == 17)
    ck("길이 일치", all(len(v) == 300 for v in R.values()))
    ck("변동성관리 VIX18·3배 → 비중 min(1,20/54)", abs(R["C10 변동성관리"][-1] - 20 / 54) < 1e-9)
    print("FAIL" if fails else "OK")
    return 1 if fails else 0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--selftest", action="store_true")
    if ap.parse_args().selftest:
        return selftest()
    vix = B.load("^VIX")["Close"]
    out = {}
    jobs = [("A NDX3x", "^NDX", 3, 0.03, False), ("A SOX3x", "^SOX", 3, 0.03, False), ("B KOSPI2x", "^KS11", 2, 0.02, True)]
    for name, tk, lev, drag, with_base in jobs:
        df = B.load(tk)
        df = df[df.index <= B.END]
        vv = vix.shift(1) if tk == "^KS11" else vix       # 코스피는 직전 미국 종가
        rules = {}
        if with_base:
            rules.update(B.build_rules(df, vv))
        rules.update(community_rules(df, vv, lev))
        res, bh_m, bounds = evaluate(df, rules, lev, drag)
        cls = {k: B.classify(v, bh_m) for k, v in res.items()}
        tools = [k for k, v in res.items() if B.tool_flag(v, bh_m)]
        check = None
        if tk == "^KS11":
            rp = pd.read_parquet(ROOT / "data" / "leveraged-etf" / "122630.KS.parquet").set_index("date")["close"]
            j = pd.concat([pd.Series(lev_ret(df["Close"], lev, drag), index=df.index), rp.pct_change()], axis=1, join="inner").dropna()
            j.columns = ["syn", "real"]
            check = dict(corr=round(float(j.corr().iloc[0, 1]), 4), n=len(j), cum_syn=round(float((1 + j["syn"]).prod()), 2), cum_real=round(float((1 + j["real"]).prod()), 2))
        out[name] = dict(bh=bh_m, rules=res, cls=cls, tools=tools, synth_check=check,
                         bounds={k: [str(df.index[a]), str(df.index[b - 1])] for k, (a, b) in bounds.items() if bounds[k]})
        print(f"\n=== {name} 규칙 {len(rules)}개  합성검증 {check}")
        print("보유", {k: (float(v['cagr']), float(v['sharpe']), float(v['mdd'])) for k, v in bh_m.items()})
        print("판정 수", dict(Counter(cls.values())), " 낙폭도구:", tools)
        for k in ("TRAIN", "VALID", "TEST"):
            if k in bh_m:
                print(f"  {k}: ΔSharpe>0 {sum(1 for r in res.values() if r[k]['dSharpe'] > 0)}/{len(res)}  (Δ≥.10∧p≤.01) {sum(1 for r in res.values() if r[k]['dSharpe'] >= .10 and r[k]['p'] <= .01)}")
        top = sorted(res.items(), key=lambda kv: -min(kv[1][k]["dSharpe"] for k in kv[1]))[:8]
        for rn, v in top:
            print(f"  {rn:24s} " + " | ".join(f"{k} Δ{v[k]['dSharpe']:+.2f} p{v[k]['p']:.3f} C{v[k]['cagr']:.0f} M{v[k]['mdd']:.0f}" for k in v) + f" → {cls[rn]}")
    (ROOT / "findings" / "tech-timing-3x-b-results.json").write_text(json.dumps(out, ensure_ascii=False, indent=1, default=float), encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main())
