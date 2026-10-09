#!/usr/bin/env python3
"""S&P500 환노출 vs 환헤지 — 사전등록 findings/sp500-fx-hedge-preregistration-2026-10.md 그대로.

    python research/strategy-lab/sp500_fx_hedge.py --selftest
    python research/strategy-lab/sp500_fx_hedge.py          # → findings/sp500-fx-hedge-results-2026-10.{md,json}
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
OUT = HERE / "findings" / "sp500-fx-hedge-results-2026-10"
PANEL = HERE / ".cache" / "etf_panel.parquet"
SEED, REPS, BLOCK = 20261010, 2000, 12
START, END, SPLIT = "2011-08", "2026-09", "2019-01"
TH, LOOK = 1.10, 36


def sharpe(r):
    r = np.asarray(r, float)
    return float(r.mean() / r.std(ddof=1) * np.sqrt(12)) if len(r) > 2 and r.std() > 0 else np.nan


def stats(r):
    r = pd.Series(r).dropna()
    w = (1 + r).cumprod()
    return dict(cagr=float(w.iloc[-1] ** (12 / len(r)) - 1), vol=float(r.std() * np.sqrt(12)), sharpe=sharpe(r),
                mdd=float((w / w.cummax() - 1).min()), worst12=float(((1 + r).rolling(12).apply(np.prod, raw=True) - 1).min()))


def switch(usd_level, H, U, th=TH, look=LOOK):
    """월말 USD 수준 > 직전 look 개월 평균 × th 이면 다음 달 H, 아니면 U. 평균이 없는 달은 NaN."""
    avg = usd_level.rolling(look, min_periods=look).mean()
    hedge = (usd_level > avg * th).shift(1)
    out = pd.Series(np.where(hedge == True, H, U), index=H.index)  # noqa: E712
    out[avg.shift(1).isna()] = np.nan
    return out, hedge


def boot_dsharpe(a, b, rng):
    x = np.c_[a, b]
    n = len(x)
    nb = int(np.ceil(n / BLOCK))
    st = rng.integers(0, n - BLOCK + 1, (REPS, nb))
    d = []
    for row in st:
        idx = np.concatenate([np.arange(s0, s0 + BLOCK) for s0 in row])[:n]
        d.append(sharpe(x[idx, 0]) - sharpe(x[idx, 1]))
    return float(np.percentile(d, 5)), float(np.percentile(d, 95))


def run():
    p = pd.read_parquet(PANEL)
    w = p[p["code"].isin(["143850", "138230", "148070"])].pivot_table(index="date", columns="code", values="close").resample("ME").last()
    m = w.pct_change()
    m.index = m.index.to_period("M")
    lvl = w["138230"].copy(); lvl.index = lvl.index.to_period("M")
    H, USD, BND = m["143850"], m["138230"], m["148070"]
    U = (1 + H) * (1 + USD) - 1
    sel = (m.index >= pd.Period(START)) & (m.index <= pd.Period(END))
    H, U, USD, BND, lvl_s = H[sel], U[sel], USD[sel], BND[sel], lvl[(lvl.index <= pd.Period(END))]
    SW, hedge = switch(lvl_s, H.reindex(lvl_s.index), U.reindex(lvl_s.index))
    SW = SW.reindex(H.index)
    halves = {"전체": H.index >= pd.Period(START), "앞 2011-08~2018-12": H.index < pd.Period(SPLIT), "뒤 2019-01~2026-09": H.index >= pd.Period(SPLIT)}
    tab = {k: dict(H=stats(H[s]), U=stats(U[s])) for k, s in halves.items()}
    c1 = all(tab[k]["U"]["vol"] < tab[k]["H"]["vol"] and tab[k]["U"]["mdd"] > tab[k]["H"]["mdd"] for k in list(halves)[1:])
    ok = SW.notna()
    rng = np.random.default_rng(SEED)
    lo, hi = boot_dsharpe(SW[ok].to_numpy(), U[ok].to_numpy(), rng)
    ds = {k: sharpe(SW[ok & s]) - sharpe(U[ok & s]) for k, s in halves.items()}
    halves_pos = all(ds[k] > 0 for k in list(halves)[1:])
    c2 = "CANDIDATE" if lo > 0 and halves_pos else "REJECT" if hi < 0 else "INCONCLUSIVE"
    rec = {}
    for th in (1.05, 1.15):
        s2, _ = switch(lvl_s, H.reindex(lvl_s.index), U.reindex(lvl_s.index), th=th)
        s2 = s2.reindex(H.index)
        rec[f"th{th}"] = sharpe(s2[ok]) - sharpe(U[ok])
    down = H <= -0.05
    yearly = pd.DataFrame({"H": (1 + H).groupby(H.index.year).prod() - 1, "U": (1 + U).groupby(U.index.year).prod() - 1})
    # 60/40 연 1회 리밸런스
    def sixty(eq):
        b = BND.reindex(eq.index)
        v, out, we = 1.0, [], 0.6
        for i, (re, rb) in enumerate(zip(eq, b)):
            if np.isnan(rb):
                out.append(np.nan); continue
            if eq.index[i].month == 1:
                we = 0.6
            r = we * re + (1 - we) * rb
            we = we * (1 + re) / (1 + r)
            out.append(r)
        return pd.Series(out, index=eq.index)
    s60 = {"U": stats(sixty(U).dropna()), "H": stats(sixty(H).dropna())}
    pc = lambda x: f"{x * 100:+.1f}%"
    L = ["---", "track: kr", "factor: sp500-fx-hedge", "date: 2026-10-10", f"verdict: {c2}",
         "criteria_version: research-only (sp500-fx-hedge-preregistration-2026-10)", "reason: >-",
         f"  C1(환노출이 변동성·낙폭 작음, 두 구간) {'SUPPORTED' if c1 else 'NOT SUPPORTED'} · C2(달러 비쌀 때 헤지 전환) {c2} — ΔSharpe 90% [{lo:+.2f}, {hi:+.2f}].", "---", "",
         "# S&P500 환노출 vs 환헤지 — 결과", "",
         "| 구간 | 종류 | 연수익 | 변동성 | Sharpe | 최대낙폭 | 최악 12개월 |", "|---|---|---:|---:|---:|---:|---:|"]
    for k, d in tab.items():
        for nm, lab in (("U", "환노출(합성)"), ("H", "환헤지(H)")):
            x = d[nm]
            L.append(f"| {k} | {lab} | {pc(x['cagr'])} | {pc(x['vol'])} | {x['sharpe']:.2f} | {pc(x['mdd'])} | {pc(x['worst12'])} |")
    L += ["", f"**C1 {'SUPPORTED' if c1 else 'NOT SUPPORTED'}** — 사전등록 §3.", "",
          f"## C2 — 달러가 36개월 평균보다 10% 넘게 비쌀 때 헤지로 전환", "",
          f"- 비교 {int(ok.sum())}개월(2014-08~) · 헤지로 있던 달 {int((hedge.reindex(H.index) == True).sum())}개월.",  # noqa: E712
          f"- Sharpe: 전환 {sharpe(SW[ok]):.2f} vs 항상 환노출 {sharpe(U[ok]):.2f} vs 항상 헤지 {sharpe(H[ok]):.2f}. ΔSharpe(전환 − 환노출) 전체 {ds['전체']:+.2f} · 앞 {ds[list(halves)[1]]:+.2f} · 뒤 {ds[list(halves)[2]]:+.2f}.",
          f"- 12개월 블록 부트스트랩 90% [{lo:+.2f}, {hi:+.2f}] → **{c2}**.",
          f"- 기록(판정 불사용): 문턱 1.05 ΔSharpe {rec['th1.05']:+.2f} · 1.15 {rec['th1.15']:+.2f}.", "",
          "## 기록", "",
          f"- S&P(H)가 −5% 이하인 달 {int(down.sum())}개월: 그달 달러 평균 {pc(USD[down].mean())} · 환노출 평균 {pc(U[down].mean())} vs 헤지 {pc(H[down].mean())}.",
          f"- 월수익 상관 S&P(H)·달러 {np.corrcoef(H, USD)[0, 1]:+.2f}.",
          f"- 60/40(국고채10년 40%, 1월 리밸런스, 2011-10~): 환노출 연 {pc(s60['U']['cagr'])}·변동성 {pc(s60['U']['vol'])}·낙폭 {pc(s60['U']['mdd'])}·Sharpe {s60['U']['sharpe']:.2f} "
          f"vs 헤지 연 {pc(s60['H']['cagr'])}·변동성 {pc(s60['H']['vol'])}·낙폭 {pc(s60['H']['mdd'])}·Sharpe {s60['H']['sharpe']:.2f}.", "",
          "| 해 | 환노출 | 환헤지 | 차이 |", "|---|---:|---:|---:|"] + [f"| {y} | {pc(r.U)} | {pc(r.H)} | {pc(r.U - r.H)} |" for y, r in yearly.iterrows()]
    L += ["", "## 한계", "", "- 합성 환노출은 실제 환노출 ETF 보다 연 0.5% 남짓 낮다(선물 ETF 보수 이중) — 환노출에 불리한 쪽.",
          "- 15년·규칙 판정 검출력이 낮다. 환헤지 비용은 한·미 금리차에 달렸다 — 2022~ 미국 금리가 더 높아 헤지 비용이 컸다.", ""]
    OUT.with_suffix(".md").write_text("\n".join(L), encoding="utf-8")
    OUT.with_suffix(".json").write_text(json.dumps(dict(c1=c1, c2=c2, ci=[lo, hi], dsharpe=ds, table=tab, sixty=s60, rec=rec), ensure_ascii=False, indent=1), encoding="utf-8")
    print("\n".join(L))
    return 0


def selftest():
    idx = pd.period_range("2010-01", periods=40, freq="M")
    lvl = pd.Series(100.0, index=idx); lvl.iloc[38] = 120.0
    H = pd.Series(0.01, index=idx); U = pd.Series(0.02, index=idx)
    sw, hedge = switch(lvl, H, U)
    ok = sw.iloc[:36].isna().all() and sw.iloc[37] == 0.02 and sw.iloc[39] == 0.01 and sw.iloc[38] == 0.02
    st = stats(pd.Series([0.1, -0.5, 0.2]))
    ok &= abs(st["mdd"] - (-0.5)) < 1e-12
    print("selftest", "ok" if ok else "FAIL")
    return 0 if ok else 1


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--selftest", action="store_true")
    sys.exit(selftest() if ap.parse_args().selftest else run())
