#!/usr/bin/env python3
"""KRX 배당수익률 팩터 — 사전등록 findings/dividend-yield-preregistration-2026-10.md 그대로.

    python research/strategy-lab/dividend_yield_study.py --selftest
    python research/strategy-lab/dividend_yield_study.py      # → findings/dividend-yield-results-2026-10.{md,json}
"""
from __future__ import annotations

import argparse
import importlib
import json
import re
import sys
from pathlib import Path

import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent.parent
sys.path.insert(0, str(HERE))
DATA = HERE / "data" / "krx-pbr-history"
OUT = HERE / "findings" / "dividend-yield-results-2026-10"
LIQ, LIQ_REC, COST_BP, TOP_PCT, DOG_N, DOG_POOL = 1e8, 1e9, 33.5, 0.10, 30, 300
SEED, REPS, BOOT = 20261009, 1000, 2000
WINDOWS = {"TRAIN": ("2010-01", "2016-12"), "VALID": ("2017-01", "2020-12"), "TEST": ("2021-01", "2026-08")}
SPAC = re.compile(r"스팩|기업인수목적")


def win_of(m):
    return next((w for w, (a, b) in WINDOWS.items() if a <= m <= b), None)


def next_month(m):
    return (pd.Period(m, "M") + 1).strftime("%Y-%m")


def krx_monthly():
    own = importlib.import_module("14_own_pbr_band_oos")
    daily = pd.concat([pd.read_parquet(f) for f in sorted((DATA / "daily").glob("*.parquet"))], ignore_index=True)
    ret, me, _ = own.monthly_from_daily(daily)
    return ret, me


def a2_monthly():
    import surge_day_continuation as s
    dates, tick, raw = s.load_raw()
    C = pd.DataFrame(np.where(raw["close"] > 0, raw["close"], np.nan), index=dates, columns=tick)
    V = pd.DataFrame(np.where(raw["volume"] > 0, raw["volume"], np.nan), index=dates, columns=tick)
    per = dates.to_period("M").strftime("%Y-%m")
    me_rows = pd.Series(np.arange(len(dates))).groupby(per).max()
    close_me = C.iloc[me_rows.to_numpy()]
    close_me.index = me_rows.index
    last_valid = C.groupby(per).last()
    liq = (C * V).rolling(20, min_periods=1).mean().iloc[me_rows.to_numpy()]
    liq.index = me_rows.index
    return close_me, last_valid, liq


def names():
    import low52_fundamental_paths as l
    return l.universe_meta()[0]


def build_panel():
    pbr = pd.concat([pd.read_parquet(f).assign(month=f.stem) for f in sorted((DATA / "pbr").glob("*.parquet"))], ignore_index=True)
    pbr = pbr.drop_duplicates(["ticker", "month"]).set_index(["ticker", "month"])[["DIV", "PBR"]]
    kret, kme = krx_monthly()
    close_me, last_valid, liq = a2_monthly()
    nm = names()
    nm.update({t: n for (t, _), n in kme["ISU_NM"].items()})
    rows = []
    months = sorted(set(pbr.index.get_level_values("month")))
    for m in months:
        if m < "2010-01" or m > "2026-08":
            continue
        n1 = next_month(m)
        sub = pbr.xs(m, level="month")
        for t, r in sub.iterrows():
            if not (isinstance(t, str) and len(t) == 6 and t[-1] == "0") or SPAC.search(nm.get(t, "")):
                continue
            if m <= "2015-12":
                if (t, m) not in kme.index:
                    continue
                lq = kme.loc[(t, m), "liq20"]
            else:
                if t not in close_me.columns or m not in close_me.index or not np.isfinite(close_me.at[m, t]):
                    continue
                lq = liq.at[m, t]
            if n1 <= "2015-12":
                rn = kret.get((t, n1), np.nan)
            else:
                if t in close_me.columns and m in close_me.index and n1 in last_valid.index:
                    c0, c1 = close_me.at[m, t], last_valid.at[n1, t]
                    rn = c1 / c0 - 1 if np.isfinite(c0) and np.isfinite(c1) else np.nan
                else:
                    rn = np.nan
            rows.append((t, m, r["DIV"], r["PBR"], lq, rn))
    df = pd.DataFrame(rows, columns=["ticker", "month", "DIV", "PBR", "liq", "ret"])
    return df[df["ret"].notna()].reset_index(drop=True)


def select(g, cell, liq_min=LIQ):
    u = g[g["liq"] >= liq_min]
    if cell == "V1":
        d = u[u["DIV"] > 0]
        k = max(int(round(len(d) * TOP_PCT)), 1)
        return d.nlargest(k, "DIV")
    if cell == "V2":
        pool = u.nlargest(DOG_POOL, "liq")
        return pool[pool["DIV"] > 0].nlargest(DOG_N, "DIV")
    if cell == "PBR10":
        d = u[u["PBR"] > 0]
        return d.nsmallest(max(int(round(len(d) * TOP_PCT)), 1), "PBR")
    if cell == "V1_ex10":
        d = u[(u["DIV"] > 0) & (u["DIV"] < 10)]
        return d.nlargest(max(int(round(len(d) * TOP_PCT)), 1), "DIV")
    raise ValueError(cell)


def series(df, cell, liq_min=LIQ):
    out, prev, picks = [], set(), {}
    for m, g in df.groupby("month"):
        u = g[g["liq"] >= LIQ]
        sel = select(g, cell, liq_min)
        if len(sel) == 0:
            continue
        cur = set(sel["ticker"])
        to = 1.0 if not prev else len(cur - prev) / len(cur)
        out.append((m, float(sel["ret"].mean()), float(u["ret"].mean()), to, len(sel)))
        prev, picks[m] = cur, cur
    s = pd.DataFrame(out, columns=["month", "ret", "ew", "turnover", "n"]).set_index("month")
    s["ex"] = s["ret"] - s["ew"]
    s["net_ex"] = s["ex"] - s["turnover"] * COST_BP / 1e4
    return s, picks


def stats(r):
    r = r.dropna()
    if len(r) < 12:
        return dict(cagr=np.nan, sharpe=np.nan, mdd=np.nan)
    eq = (1 + r).cumprod()
    return dict(cagr=float(eq.iloc[-1] ** (12 / len(r)) - 1), sharpe=float(r.mean() / r.std() * np.sqrt(12)), mdd=float((eq / eq.cummax() - 1).min()))


def wmask(idx, w):
    a, b = WINDOWS[w]
    return (idx >= a) & (idx <= b)


def random_floor(df, sizes, rng):
    """sizes: {cell: Series(month → n)} → 두 칸 TRAIN 월평균 초과 최댓값의 1,000회 분포."""
    out = np.zeros((REPS, len(sizes)))
    for m, g in df.groupby("month"):
        if not wmask(pd.Index([m]), "TRAIN")[0]:
            continue
        u = g[g["liq"] >= LIQ]["ret"].to_numpy()
        ew = u.mean()
        for c, (cell, sz) in enumerate(sizes.items()):
            k = int(sz.get(m, 0))
            if k == 0 or k > len(u):
                continue
            idx = np.argsort(rng.random((REPS, len(u))), axis=1)[:, :k]
            out[:, c] += u[idx].mean(1) - ew
    ntr = {cell: int(wmask(sz.index, "TRAIN").sum()) for cell, sz in sizes.items()}
    out /= np.array([max(ntr[c], 1) for c in sizes])
    return out.max(1)


def boot_ci(x, rng):
    x = x.dropna().to_numpy()
    b = rng.choice(x, (BOOT, len(x))).mean(1)
    return [float(np.percentile(b, 2.5)), float(np.percentile(b, 97.5))]


def run():
    df = build_panel()
    rng = np.random.default_rng(SEED)
    cells, picks = {}, {}
    for c in ("V1", "V2", "PBR10", "V1_ex10"):
        cells[c], picks[c] = series(df, c)
    cells["V1_liq10"], _ = series(df, "V1", LIQ_REC)
    null = random_floor(df, {c: cells[c]["n"] for c in ("V1", "V2")}, rng)
    floor = float(np.percentile(null, 95))
    res, verdict = {}, {}
    for c, s in cells.items():
        res[c] = {}
        for w in WINDOWS:
            m = wmask(s.index, w)
            res[c][w] = dict(ex=float(s["ex"][m].mean()), net_ex=float(s["net_ex"][m].mean()), months=int(m.sum()), turnover=float(s["turnover"][m].mean()),
                             cell=stats(s["ret"][m] - s["turnover"][m] * COST_BP / 1e4), ew=stats(s["ew"][m]), ci=boot_ci(s["ex"][m], rng),
                             breakeven_bp=float(s["ex"][m].mean() / s["turnover"][m].mean() * 1e4) if s["turnover"][m].mean() > 0 else np.nan)
        s2 = s[s.index >= "2024-01"]
        res[c]["2024~"] = dict(ex=float(s2["ex"].mean()), net_ex=float(s2["net_ex"].mean()), months=len(s2))
        res[c]["years"] = s["ex"].groupby(s.index.str[:4]).sum().round(4).to_dict()
    for c in ("V1", "V2"):
        r = res[c]
        info = r["TRAIN"]["ex"] >= floor and r["VALID"]["ex"] > 0 and r["TEST"]["ex"] > 0
        econ = info and r["VALID"]["net_ex"] > 0 and r["TEST"]["net_ex"] > 0
        verdict[c] = "ECONOMIC" if econ else ("INFORMATION" if info else "REJECT")
    jac = [len(picks["V1"][m] & picks["PBR10"][m]) / len(picks["V1"][m] | picks["PBR10"][m]) for m in picks["V1"] if m in picks["PBR10"]]
    diff = (cells["V1"]["ret"] - cells["PBR10"]["ret"]).dropna()
    rec = dict(jaccard_v1_pbr10=float(np.mean(jac)), v1_minus_pbr10={w: float(diff[wmask(diff.index, w)].mean()) for w in WINDOWS},
               universe_n=float(df[df["liq"] >= LIQ].groupby("month").size().mean()), months=[df["month"].min(), df["month"].max()])
    out = dict(verdict=verdict, floor=floor, res=res, rec=rec)
    OUT.with_suffix(".json").write_text(json.dumps(out, ensure_ascii=False, indent=1, default=float), encoding="utf-8")
    OUT.with_suffix(".md").write_text(render(out), encoding="utf-8")
    for c in res:
        print(c, verdict.get(c, "기록"), {w: (round(res[c][w]["ex"] * 1e4, 1), round(res[c][w]["net_ex"] * 1e4, 1)) for w in WINDOWS})
    print("floor bp", round(floor * 1e4, 1), "jaccard", round(rec["jaccard_v1_pbr10"], 2))
    return 0


def bp(x):
    return "" if x is None or not np.isfinite(x) else f"{x * 1e4:+.0f}bp"


def pc(x):
    return "" if x is None or not np.isfinite(x) else f"{x * 100:+.1f}%"


def render(o):
    v = o["verdict"]
    pos = [k for k, x in v.items() if x != "REJECT"]
    L = ["---", "track: kr", "factor: dividend-yield", "date: 2026-10-09",
         f"verdict: {'ECONOMIC' if 'ECONOMIC' in v.values() else ('INFORMATION' if pos else 'REJECT')}",
         "criteria_version: research-only (dividend-yield-preregistration-2026-10)",
         'conditions: ["KRX DIV 월말 단면 2010-01~2026-08, 폐지 포함", "유동성 1억, 보통주, 스팩 제외", "기준 = 유니버스 등가중", "비용 = 회전율 × 33.5bp", "무작위 포트폴리오 1,000회 95백분위 바닥선"]',
         "reason: >-", f"  신호: {'있음(' + '·'.join(pos) + ')' if pos else '없음'} · 경제성: {'통과' if 'ECONOMIC' in v.values() else '미달'}. "
         + " · ".join(f"{k} {x}" for k, x in v.items()) + f". (스크립트 판정, 가족 바닥선 {bp(o['floor'])})", "---", "",
         "# KRX 배당수익률 팩터 — 결과", "", f"수치는 `dividend_yield_study.py` 가 계산한 값 그대로. 형성월 {o['rec']['months'][0]} ~ {o['rec']['months'][1]}, 유니버스 평균 {o['rec']['universe_n']:.0f}종목/월.", "",
         "## 1. 월평균 초과(유니버스 등가중 대비)", "",
         "| 칸 | 구간 | 달 | gross 초과 [95%] | 비용 후 초과 | 손익분기 비용 | 월 회전율 | 칸 CAGR/샤프/MDD(비용 후) | 등가중 CAGR/샤프/MDD | 판정 |", "|---|---|---:|---|---:|---:|---:|---|---|---|"]
    for c, r in o["res"].items():
        for w in WINDOWS:
            e = r[w]
            L.append(f"| {c} | {w} | {e['months']} | {bp(e['ex'])} [{bp(e['ci'][0])}, {bp(e['ci'][1])}] | {bp(e['net_ex'])} | {e['breakeven_bp']:.0f}bp | {e['turnover']:.2f} | "
                     f"{pc(e['cell']['cagr'])} / {e['cell']['sharpe']:.2f} / {pc(e['cell']['mdd'])} | {pc(e['ew']['cagr'])} / {e['ew']['sharpe']:.2f} / {pc(e['ew']['mdd'])} | "
                     f"{'**' + v[c] + '**' if c in v and w == 'TRAIN' else ''} |")
    L += ["", f"가족 바닥선(무작위 같은 크기, TRAIN 월평균 초과 두 칸 최댓값 95백분위): {bp(o['floor'])}.", "",
          "## 2. 기록", "", f"- V1 과 저PBR 하위 10% 월별 겹침(자카드) 평균 {o['rec']['jaccard_v1_pbr10']:.2f}. V1 − 저PBR10 월평균: " +
          " · ".join(f"{w} {bp(x)}" for w, x in o['rec']['v1_minus_pbr10'].items()) + ".",
          "- 2024~(밸류업 이후): " + " · ".join(f"{c} {bp(r['2024~']['ex'])}(비용 후 {bp(r['2024~']['net_ex'])}, {r['2024~']['months']}달)" for c, r in o["res"].items()), "",
          "### 연도별 초과 합", "", "| 칸 | " + " | ".join(sorted(o["res"]["V1"]["years"])) + " |", "|---|" + "---:|" * len(o["res"]["V1"]["years"])]
    for c, r in o["res"].items():
        L.append(f"| {c} | " + " | ".join(pc(r['years'].get(y, np.nan)) for y in sorted(o["res"]["V1"]["years"])) + " |")
    return "\n".join(L) + "\n"


def selftest():
    ok = True

    def check(name, cond):
        nonlocal ok
        ok &= bool(cond)
        print(("PASS " if cond else "FAIL ") + name)

    g = pd.DataFrame({"ticker": [f"{i:05d}0" for i in range(20)], "month": "2020-01", "DIV": np.r_[np.arange(10, 0, -1), np.zeros(10)],
                      "PBR": np.arange(1, 21) / 10, "liq": np.r_[np.full(15, 2e8), np.full(5, 5e7)], "ret": 0.0})
    check("V1: DIV>0 10개 중 상위 10% = 1개(DIV 10)", select(g, "V1")["DIV"].tolist() == [10.0])
    check("유동성 1억 미만 제외", "000190" not in set(select(g, "PBR10")["ticker"]))
    check("V2: 유동성 상위 300 안 DIV 상위(최대 30, DIV>0 만)", len(select(g, "V2")) == 10)
    check("다음 달 계산", next_month("2015-12") == "2016-01")
    print("ALL PASS" if ok else "FAILED")
    return 0 if ok else 1


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--selftest", action="store_true")
    sys.exit(selftest() if ap.parse_args().selftest else run())
