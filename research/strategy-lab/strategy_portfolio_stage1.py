#!/usr/bin/env python3
"""전략 포트폴리오 1단계 — 월간 수익 상관. 사전등록 findings/strategy-portfolio-stage1-preregistration-2026-10.md (커밋 0e312a79) 그대로.

    python research/strategy-lab/strategy_portfolio_stage1.py --selftest
    python research/strategy-lab/strategy_portfolio_stage1.py          # → findings/strategy-portfolio-stage1-results-2026-10.{md,json}

월수익 계열은 .cache/strategy_portfolio_stage1.parquet(gitignore)에만 둔다 — S3·S4 는 로컬 전용 규칙에서 나온 값이다.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE / "futures"))

OUT = HERE / "findings" / "strategy-portfolio-stage1-results-2026-10"
CACHE = HERE / ".cache" / "strategy_portfolio_stage1.parquet"
FX = HERE / "data" / "market-regime" / "dexkous_raw.parquet"
SLEEVES = ["S1", "S2", "S3", "S4", "S5"]
NAMES = {"S1": "PBR 결합", "S2": "RV20 규칙 B", "S3": "무한매수 TQQQ", "S4": "무한매수 SOXL", "S5": "ETF 6종 1/6",
         "R1": "KODEX 200", "R2": "국내 등가중", "S1x": "PBR − 등가중"}
SAME, INDEP = 0.7, 0.5


def monthly(level: pd.Series) -> pd.Series:
    """일별(또는 월별) 수준 → 달력 월 마지막 값 → 월수익. 인덱스 = Period[M]."""
    lv = level.dropna()
    lv.index = pd.DatetimeIndex(lv.index)
    m = lv.groupby(lv.index.to_period("M")).last()
    return m.pct_change().dropna()


# ───────────────────── 계열 ─────────────────────
def s1_r2():
    import pbr_vs_ew_monthly_mtm as pm
    from engine.portfolio.portfolio import PortfolioConfig
    out = {}
    for key, sid in (("S1", "pbr_value_v1_combined"), ("R2", "ew_benchmark_liquid_v1")):
        base = pm.run_smoke(sid, pm.START, pm.END, pm.REPO_ROOT)
        p = base["params"]["portfolio"]
        cfg = PortfolioConfig(initial_capital=p["initialCapital"], max_positions=p["maxPositions"], equal_weight=p["equalWeight"],
                              fractional_shares=p["fractionalShares"], tie_break=p["tieBreak"])
        _, snaps = pm.schedule_with_monthly_mtm(base["resolved"], cfg, base["bars_by_ticker"], base["calendar"], pm.START, pm.END)
        lv = pd.Series([e for _, e in snaps], index=pd.to_datetime([d for d, _ in snaps]))
        lv = pd.concat([pd.Series([float(p["initialCapital"])], index=[lv.index[0] - pd.offsets.MonthEnd(1)]), lv])
        out[key] = monthly(lv)
    return out


def s2():
    import stage5_1_volatility_event_study as s51
    import stage5_3_sizing_backtest as s53
    fr = s51.front_series(s51.load())
    d, _, _ = s51.process(fr)
    cts = fr[~fr["roll"]].copy()
    bt = s53.run_sizing(cts, d["pct_rv20_rol"], "defensive")
    return monthly(pd.Series(bt["nav"], index=bt["idx"]))


def fx_monthly():
    x = pd.read_parquet(FX)
    return monthly(pd.Series(x["value"].to_numpy(float), index=pd.to_datetime(x["date"])))


def s3_s4():
    import infinite_buying_engine as eng
    import realistic_fill_model as rf
    out = {}
    for key, tk in (("S3", "TQQQ"), ("S4", "SOXL")):
        r = eng.Rules.load(rf.RULES, tk, rf.SPLITS)
        candles = rf.load_engine_candles(tk)
        tr: list = []
        with rf.use_realistic_fill():
            eng.backtest(candles, r, plan_fn=eng.plan_orders, trace=tr)
        lv = pd.Series([t["equity"] for t in tr], index=pd.to_datetime([t["date"] for t in tr]))
        out[key + "usd"] = monthly(lv)
    return out


def s5_r1():
    import etf_timing_lab as e
    import multiasset_tsmom as ma
    panel = e.load_panel()
    cal = pd.DatetimeIndex(sorted(panel.loc[panel["code"] == e.K200, "date"]))
    R = pd.DataFrame({a: e.tr_returns(panel, a, cal) for a in ma.ASSETS}, index=cal)
    ok = R.notna().all(1)
    s5 = (1 + R[ok].mean(1)).cumprod()
    r1 = (1 + R[e.K200].fillna(0)).cumprod()
    return {"S5": monthly(s5), "R1": monthly(r1)}


def to_krw(usd: pd.Series, fx: pd.Series) -> pd.Series:
    f = fx.reindex(usd.index)
    return ((1 + usd) * (1 + f) - 1).dropna()


def build():
    if CACHE.exists():
        return pd.read_parquet(CACHE)
    cols = {}
    cols.update(s1_r2())
    cols["S2"] = s2()
    fx = fx_monthly()
    for k, v in s3_s4().items():
        cols[k] = v
        cols[k[:2]] = to_krw(v, fx)
    cols.update(s5_r1())
    df = pd.DataFrame(cols)
    df.index = df.index.astype(str)
    CACHE.parent.mkdir(exist_ok=True)
    df.to_parquet(CACHE)
    return df


# ───────────────────── 통계 · 판정 ─────────────────────
def stats(r: pd.Series) -> dict:
    r = r.dropna()
    eq = (1 + r).cumprod()
    yrs = len(r) / 12
    return dict(cagr=float(eq.iloc[-1] ** (1 / yrs) - 1), vol=float(r.std() * np.sqrt(12)),
                sharpe=float(r.mean() / r.std() * np.sqrt(12)) if r.std() > 0 else None, mdd=float((eq / eq.cummax() - 1).min()), n=int(len(r)))


def groups(C: pd.DataFrame) -> list[list[str]]:
    """상관 ≥ SAME 인 칸을 같은 원천으로 묶는다(연결 성분)."""
    left, out = list(C.index), []
    while left:
        g, stack = [], [left.pop(0)]
        while stack:
            a = stack.pop()
            g.append(a)
            for b in list(left):
                if C.loc[a, b] >= SAME:
                    left.remove(b)
                    stack.append(b)
        out.append(sorted(g))
    return out


def max_independent(C: pd.DataFrame, reps: list[str], sharpe: dict) -> list[str]:
    """대표 칸들 중 샤프 > 0 이고 서로 상관이 모두 ≤ INDEP 인 가장 큰 부분집합(전수, 칸 ≤ 5)."""
    from itertools import combinations
    cand = [x for x in reps if (sharpe.get(x) or 0) > 0]
    for k in range(len(cand), 0, -1):
        for sub in combinations(cand, k):
            if all(C.loc[a, b] <= INDEP for a, b in combinations(sub, 2)):
                return list(sub)
    return []


def decide(C: pd.DataFrame, sharpe: dict) -> dict:
    gs = groups(C)
    reps = [max(g, key=lambda x: sharpe.get(x) or -9) for g in gs]
    ind = max_independent(C.loc[reps, reps], reps, sharpe)
    return dict(groups=gs, reps=reps, independent=ind, go=len(ind) >= 3)


def run():
    df = build()
    common = df[SLEEVES].dropna()
    D = df.loc[common.index]
    C = common.corr()
    st = {k: stats(D[k]) for k in SLEEVES + ["R1", "R2"]}
    D["S1x"] = D["S1"] - D["R2"]
    st["S1x"] = stats(D["S1x"])
    dec = decide(C, {k: st[k]["sharpe"] for k in SLEEVES})
    down = D["R1"] < 0
    Cd = common[down].corr()
    yr = pd.PeriodIndex(common.index, freq="M").year
    C1, C2 = common[yr <= 2020].corr(), common[yr >= 2021].corr()
    Cs = common.corr("spearman")
    refc = D[SLEEVES + ["R1", "R2", "S1x"]].corr()[["R1", "R2", "S1x"]].loc[SLEEVES]
    usd = D[["S3usd", "S4usd"]].join(common[["S1", "S2", "S5"]]).corr().loc[["S3usd", "S4usd"]]
    warn = [(a, b, float(C.loc[a, b]), float(Cd.loc[a, b])) for i, a in enumerate(SLEEVES) for b in SLEEVES[i + 1:] if Cd.loc[a, b] - C.loc[a, b] >= 0.2]
    out = dict(period=[common.index[0], common.index[-1]], months=int(len(common)), corr=C.round(4).to_dict(), corr_down=Cd.round(4).to_dict(),
               down_months=int(down.sum()), corr_2016_2020=C1.round(4).to_dict(), corr_2021=C2.round(4).to_dict(), corr_spearman=Cs.round(4).to_dict(),
               corr_ref=refc.round(4).to_dict(), corr_usd=usd.round(4).to_dict(), stats=st, decision=dec, down_warnings=warn)
    OUT.with_suffix(".json").write_text(json.dumps(out, ensure_ascii=False, indent=1, default=float), encoding="utf-8")

    def mat(M, rows=SLEEVES, cols=SLEEVES):
        L = ["| | " + " | ".join(NAMES.get(c, c) for c in cols) + " |", "|---|" + "---:|" * len(cols)]
        L += [f"| {NAMES[r]} | " + " | ".join(f"{M.loc[r, c]:+.2f}" for c in cols) + " |" for r in rows]
        return L
    pc = lambda x: f"{x * 100:+.1f}%"
    verdict = "GO" if dec["go"] else "STOP"
    L = ["---", "track: multi", "factor: strategy-portfolio-stage1", "date: 2026-10-09", f"verdict: {verdict}",
         "criteria_version: research-only (strategy-portfolio-stage1-preregistration-2026-10)",
         'conditions: ["S1 PBR 결합 · S2 RV20 규칙 B · S3/S4 무한매수 V4.0 TQQQ/SOXL(10bp, KRW 환산) · S5 ETF 6종 1/6", "공통 구간 월수익 피어슨 상관", "같은 원천 ≥ 0.7 · 독립 ≤ 0.5 · 독립 3개 이상이면 2단계 GO"]',
         "reason: >-", f"  독립 원천 {len(dec['independent'])}개({', '.join(NAMES[x] for x in dec['independent'])}) → 2단계 {verdict}. (스크립트 판정)", "---", "",
         "# 전략 포트폴리오 1단계 — 월간 수익 상관 결과", "",
         f"공통 구간 {common.index[0]} ~ {common.index[-1]} · {len(common)}개월. 계열 정의는 사전등록 §1.", "", "## 1. 상관 (피어슨, 주 판정)", ""] + mat(C) + [
         "", f"같은 원천 묶음(≥ {SAME}): " + " · ".join("{" + ", ".join(NAMES[x] for x in g) + "}" for g in dec["groups"]),
         f"서로 ≤ {INDEP} 이고 샤프 > 0 인 최대 묶음: **{', '.join(NAMES[x] for x in dec['independent']) or '없음'}** → 2단계 **{verdict}**", "",
         "## 2. 칸별 성과 (공통 구간, 각자의 비용 가정 — 사전등록 §4)", "", "| 칸 | 연수익 | 변동성 | 샤프 | MDD |", "|---|---:|---:|---:|---:|"]
    L += [f"| {NAMES[k]} | {pc(v['cagr'])} | {pc(v['vol'])} | {v['sharpe']:.2f} | {pc(v['mdd'])} |" for k, v in st.items()]
    L += ["", f"## 3. 기록 — 하락장 상관 (KODEX 200 이 음인 {int(down.sum())}개월)", ""] + mat(Cd)
    L += ["", "하락장에서 0.2 이상 더 붙는 쌍: " + ("; ".join(f"{NAMES[a]}–{NAMES[b]} {c:+.2f} → {d:+.2f}" for a, b, c, d in warn) or "없음")]
    L += ["", "## 4. 기록 — 구간별 상관", "", "2016~2020:", ""] + mat(C1) + ["", "2021~:", ""] + mat(C2)
    L += ["", "## 5. 기록 — 시장·초과분과의 상관", ""] + mat(refc, SLEEVES, ["R1", "R2", "S1x"])
    L += ["", "## 6. 기록 — 무한매수 USD 그대로", "", "| | PBR 결합 | RV20 | ETF 6종 |", "|---|---:|---:|---:|"]
    L += [f"| {k} | {usd.loc[k, 'S1']:+.2f} | {usd.loc[k, 'S2']:+.2f} | {usd.loc[k, 'S5']:+.2f} |" for k in ("S3usd", "S4usd")]
    L += ["", "## 7. 기록 — 스피어먼", ""] + mat(Cs)
    OUT.with_suffix(".md").write_text("\n".join(L) + "\n", encoding="utf-8")
    print("\n".join(L[12:]))
    return 0


def selftest():
    ok = True

    def check(n, c):
        nonlocal ok
        ok &= bool(c)
        print(("PASS " if c else "FAIL ") + n)

    lv = pd.Series([100, 101, 110, 99, 121], index=pd.to_datetime(["2020-01-30", "2020-01-31", "2020-02-28", "2020-03-02", "2020-03-31"]))
    m = monthly(lv)
    check("월말 마지막 값 기준 월수익", list(m.index.astype(str)) == ["2020-02", "2020-03"] and abs(m.iloc[0] - 110 / 101 + 1) < 1e-12 and abs(m.iloc[1] - 1.1 + 1) < 1e-12)
    check("KRW 환산", abs(to_krw(pd.Series([0.1]), pd.Series([0.05])).iloc[0] - 0.155) < 1e-12)
    idx = list("ABCDE")
    C = pd.DataFrame(np.eye(5), index=idx, columns=idx)
    C.loc["A", "B"] = C.loc["B", "A"] = 0.8
    C.loc["C", "D"] = C.loc["D", "C"] = 0.6
    sh = dict(A=1.0, B=0.5, C=0.4, D=0.3, E=-0.1)
    d = decide(C, sh)
    check("≥0.7 묶음 · 대표 = 샤프 큰 칸", ["A", "B"] in d["groups"] and "A" in d["reps"] and "B" not in d["reps"])
    check("독립 묶음: C·D 는 0.6 이라 하나만, E 는 샤프 음 → {A, C} 2개 → STOP", sorted(d["independent"]) == ["A", "C"] and not d["go"])
    C.loc["C", "D"] = C.loc["D", "C"] = 0.4
    check("C·D 0.4 면 {A, C, D} 3개 → GO", decide(C, sh)["go"])
    print("ALL PASS" if ok else "FAILED")
    return 0 if ok else 1


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--selftest", action="store_true")
    sys.exit(selftest() if ap.parse_args().selftest else run())
