#!/usr/bin/env python3
"""200일선 레버리지(Gayed LRS) — 사전등록 findings/leverage-long-run-preregistration-2026-10.md 그대로.

    python research/strategy-lab/leverage_long_run.py --selftest
    python research/strategy-lab/leverage_long_run.py          # → findings/leverage-long-run-results-2026-10.{md,json}
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
OUT = HERE / "findings" / "leverage-long-run-results-2026-10"
PT, LE = HERE / "data" / "pension-test", HERE / "data" / "leveraged-etf"
COST, SEED, REPS, BLOCK = 0.001, 20261010, 2000, 12
OOS = ("2016-01-04", "2026-09-28")


def px(path):
    d = pd.read_parquet(path)
    if "date" in d:
        d = d.set_index(pd.to_datetime(d["date"]))
    d.index = pd.to_datetime(d.index).tz_localize(None).normalize()
    return d["close"].astype(float).sort_index()


def lrs(sig_close, lev_ret, cash_ret, band=0.0):
    """t−1 종가 신호(SMA200 ± band) → t 하루 보유. 전환일에 비용. 반환 (일수익, 보유 여부)."""
    sma = sig_close.rolling(200, min_periods=200).mean()
    above = sig_close > sma * (1 + band)
    below = sig_close < sma * (1 - band)
    st, pos = [], False
    for a, b, m in zip(above, below, sma):
        if np.isnan(m):
            st.append(np.nan); continue
        pos = True if a else False if b else pos
        st.append(pos)
    st = pd.Series(st, index=sig_close.index).shift(1)              # 하루 늦춤
    ok = st.notna() & lev_ret.notna() & cash_ret.notna()
    s = st[ok].astype(bool)
    r = np.where(s, lev_ret[ok], cash_ret[ok])
    sw = s.ne(s.shift(1)) & s.shift(1).notna()
    r = r - sw.to_numpy() * COST
    return pd.Series(r, index=s.index), s


def mstats(d, cash_m):
    m = (1 + d).resample("ME").prod() - 1
    ex = (m - cash_m.reindex(m.index).fillna(0)).dropna()
    w = (1 + d).cumprod()
    yrs = len(d) / 252
    return dict(cagr=float(w.iloc[-1] ** (1 / yrs) - 1), vol=float(d.std() * np.sqrt(252)), mdd=float((w / w.cummax() - 1).min()),
                sharpe=float(ex.mean() / ex.std() * np.sqrt(12))), ex


def boot(a, b, rng):
    x = np.c_[a, b]; n = len(x); nb = int(np.ceil(n / BLOCK))
    st = rng.integers(0, n - BLOCK + 1, (REPS, nb))
    sh = lambda v: v.mean() / v.std() * np.sqrt(12)
    d = [sh(x[np.concatenate([np.arange(s0, s0 + BLOCK) for s0 in row])[:n], 0]) - sh(x[np.concatenate([np.arange(s0, s0 + BLOCK) for s0 in row])[:n], 1]) for row in st]
    return float(np.percentile(d, 5)), float(np.percentile(d, 95))


def run():
    spy, sso, upro = px(PT / "SPY.parquet"), px(LE / "SSO.parquet"), px(LE / "UPRO.parquet")
    qqq, qld = px(LE / "QQQ.parquet"), px(LE / "QLD.parquet")
    irx = px(PT / "_IRX.parquet")
    idx = spy.index.intersection(sso.index)
    cash = (irx.reindex(spy.index).ffill() / 100 / 252).shift(1)
    cash_m = (1 + cash).resample("ME").prod() - 1
    rr = lambda s_: s_.pct_change()
    a_ = slice(*OOS)
    res, tbl = {}, {}

    def cell(name, sig, lev, rng_=a_):
        r, s = lrs(sig, rr(lev).reindex(sig.index), cash.reindex(sig.index))
        r = r.loc[rng_]
        st, ex = mstats(r, cash_m)
        s2 = s.loc[rng_]
        st.update(switches=int((s2 != s2.shift(1)).sum() - 1), in_mkt=float(s2.mean()))
        return r, st, ex

    C, tbl["C LRS 2배(SSO)"], exC = cell("C", spy, sso)
    A = rr(spy).loc[a_].dropna()
    tbl["A SPY 보유"], exA = mstats(A, cash_m)
    B = rr(sso).loc[a_].dropna()
    tbl["B SSO 보유"], _ = mstats(B, cash_m)
    _, tbl["기록: LRS 1배(SPY)"], _ = cell("1x", spy, spy)
    _, tbl["기록: LRS 3배(UPRO)"], _ = cell("3x", spy, upro)
    tbl["기록: UPRO 보유"], _ = mstats(rr(upro).loc[a_].dropna(), cash_m)
    _, tbl["기록: 나스닥 LRS 2배(QLD)"], _ = cell("qld", qqq, qld)
    tbl["기록: QLD 보유"], _ = mstats(rr(qld).loc[a_].dropna(), cash_m)
    tbl["기록: QQQ 보유"], _ = mstats(rr(qqq).loc[a_].dropna(), cash_m)
    _, tbl["기록: 2006-06~2015 LRS 2배(SSO)"], _ = cell("pre", spy, sso, slice("2006-06-22", "2015-12-31"))
    tbl["기록: 2006-06~2015 SPY 보유"], _ = mstats(rr(spy).loc["2006-06-22":"2015-12-31"].dropna(), cash_m)
    for band in (0.01, 0.03):
        r, s = lrs(spy, rr(sso).reindex(spy.index), cash.reindex(spy.index), band=band)
        tbl[f"기록: 띠 ±{band:.0%}"], _ = mstats(r.loc[a_], cash_m)
    # 국내: 122630 레버리지, 신호 KODEX200(069500)
    try:
        p = pd.read_parquet(HERE / ".cache" / "etf_panel.parquet")
        k200 = p[p["code"] == "069500"].set_index("date")["close"].astype(float).sort_index()
        klev = p[p["code"] == "122630"].set_index("date")["close"].astype(float).sort_index()
        kc = pd.Series(0.02 / 252, index=k200.index)                      # 국내 현금 연 2% 가정(기록 전용)
        rk, sk = lrs(k200, klev.pct_change().reindex(k200.index), kc)
        tbl["기록: 국내 LRS(122630, 현금 연 2%)"], _ = mstats(rk.loc[a_], kc.resample("ME").sum())
        tbl["기록: 국내 KODEX 200 보유"], _ = mstats(k200.pct_change().loc[a_].dropna(), kc.resample("ME").sum())
        tbl["기록: 국내 122630 보유"], _ = mstats(klev.pct_change().loc[a_].dropna(), kc.resample("ME").sum())
    except Exception as e:                                                 # 국내는 기록 전용 — 실패해도 판정과 무관
        tbl["기록: 국내"] = dict(err=str(e))
    j = exC.index.intersection(exA.index)
    lo, hi = boot(exC[j].to_numpy(), exA[j].to_numpy(), np.random.default_rng(SEED))
    c, a, b = tbl["C LRS 2배(SSO)"], tbl["A SPY 보유"], tbl["B SSO 보유"]
    sup = c["cagr"] > a["cagr"] and c["mdd"] > b["mdd"] and c["sharpe"] > a["sharpe"]
    verdict = "ROBUST" if sup and lo > 0 else "SUPPORTED" if sup else "NOT SUPPORTED"
    yearly = pd.DataFrame({"LRS": (1 + C).groupby(C.index.year).prod() - 1, "SPY": (1 + A).groupby(A.index.year).prod() - 1, "SSO": (1 + B).groupby(B.index.year).prod() - 1})
    pc = lambda x: f"{x * 100:+.1f}%"
    L = ["---", "track: us", "factor: leverage-long-run", "date: 2026-10-10", f"verdict: {verdict}",
         "criteria_version: research-only (leverage-long-run-preregistration-2026-10)", "reason: >-",
         f"  논문 발표 뒤 2016-01~2026-09: LRS 2배 연 {pc(c['cagr'])}·낙폭 {pc(c['mdd'])}·Sharpe {c['sharpe']:.2f} vs SPY 보유 {pc(a['cagr'])}·{pc(a['mdd'])}·{a['sharpe']:.2f} "
         f"vs SSO 보유 {pc(b['cagr'])}·{pc(b['mdd'])}. ΔSharpe 90% [{lo:+.2f}, {hi:+.2f}].", "---", "",
         "# 200일선 레버리지(LRS) — 결과", "", "| 전략 | 연수익 | 변동성 | 최대낙폭 | Sharpe | 전환 | 시장 안 |", "|---|---:|---:|---:|---:|---:|---:|"]
    for k, x in tbl.items():
        if "err" in x:
            L.append(f"| {k} | 오류 {x['err'][:60]} | | | | | |"); continue
        L.append(f"| {k} | {pc(x['cagr'])} | {pc(x['vol'])} | {pc(x['mdd'])} | {x['sharpe']:.2f} | {x.get('switches', '')} | {format(x['in_mkt'], '.0%') if 'in_mkt' in x else ''} |")
    L += ["", f"판정 **{verdict}** (사전등록 §4). ΔSharpe(C−A) 12개월 블록 90% [{lo:+.2f}, {hi:+.2f}].", "",
          "| 해 | LRS 2배 | SPY | SSO |", "|---|---:|---:|---:|"] + [f"| {y} | {pc(r.LRS)} | {pc(r.SPY)} | {pc(r.SSO)} |" for y, r in yearly.iterrows()]
    OUT.with_suffix(".md").write_text("\n".join(L) + "\n", encoding="utf-8")
    OUT.with_suffix(".json").write_text(json.dumps(dict(verdict=verdict, ci=[lo, hi], table=tbl), ensure_ascii=False, indent=1), encoding="utf-8")
    print("\n".join(L))
    return 0


def selftest():
    i = pd.bdate_range("2020-01-01", periods=205)
    sig = pd.Series(100.0, index=i); sig.iloc[200:] = 110.0      # 200행부터 위
    lev = pd.Series(0.02, index=i); cash = pd.Series(0.0001, index=i)
    r, s = lrs(sig, lev, cash)
    ok = (not s.loc[i[200]]) and s.loc[i[201]] and abs(r.loc[i[201]] - (0.02 - COST)) < 1e-12 and abs(r.loc[i[202]] - 0.02) < 1e-12 and abs(r.loc[i[200]] - 0.0001) < 1e-12
    print("selftest", "ok" if ok else "FAIL")
    return 0 if ok else 1


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--selftest", action="store_true")
    sys.exit(selftest() if ap.parse_args().selftest else run())
