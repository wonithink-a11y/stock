#!/usr/bin/env python3
"""국내 업종 ETF 주간 역추세 — 사전등록 findings/sector-etf-weekly-reversal-preregistration-2026-10.md 그대로.

    python research/strategy-lab/sector_etf_weekly_reversal.py --selftest
    python research/strategy-lab/sector_etf_weekly_reversal.py      # → findings/sector-etf-weekly-reversal-results-2026-10.{md,json}
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
import etf_timing_lab as e

OUT = HERE / "findings" / "sector-etf-weekly-reversal-results-2026-10"
SECTORS = ["반도체", "은행", "자동차", "건설", "철강", "에너지화학", "헬스케어", "증권", "보험", "운송", "정보기술", "방송통신", "기계장비", "경기소비재", "필수소비재"]
K, MIN_SECT, COST = 3, 8, 0.0005
SEED, REPS = 20261009, 1000
WINDOWS = {"TRAIN": (2010, 2016), "VALID": (2017, 2020), "TEST": (2021, 2026)}
BAD = "레버리지|인버스|2X|선물"


def sector_closes(p):
    """주 마지막 거래일별 업종 대표 ETF(직전 20일 거래대금 합 최대)의 종가 수익 지수."""
    x = p[p["idx_name"].isin([f"KRX {s}" for s in SECTORS]) & ~p["name"].astype(str).str.contains(BAD) & (p["close"] > 0)].copy()
    x["sector"] = x["idx_name"].str[4:]
    x = x.sort_values(["code", "date"])
    x["ret"] = x.groupby("code")["close"].pct_change()
    x["val20"] = x.groupby("code")["val"].transform(lambda s: s.rolling(20, min_periods=5).sum())
    cal = pd.DatetimeIndex(sorted(p["date"].unique()))
    wk = pd.Series(cal.to_period("W-FRI"), index=cal)
    week_end = wk.groupby(wk.values).apply(lambda s: s.index.max())
    rets = x.pivot_table(index="date", columns="code", values="ret").reindex(cal)
    val20 = x.pivot_table(index="date", columns="code", values="val20").reindex(cal)
    sec_of = x.groupby("code")["sector"].first()
    return cal, week_end.to_list(), rets, val20, sec_of


def weekly_table(cal, week_ends, rets, val20, sec_of):
    """반환 list of (주말 t, {업종: (지난 5일 수익, 다음 주 수익)})."""
    rows = []
    pos = {d: i for i, d in enumerate(cal)}
    for a, b in zip(week_ends[:-1], week_ends[1:]):
        i, j = pos[a], pos[b]
        if i < 5:
            continue
        pick = {}
        for code, sec in sec_of.items():
            v = val20.iloc[i].get(code)
            if not np.isfinite(v):
                continue
            if sec not in pick or v > pick[sec][1]:
                pick[sec] = (code, v)
        d = {}
        for sec, (code, _) in pick.items():
            past = rets[code].iloc[i - 4:i + 1]
            nxt = rets[code].iloc[i + 1:j + 1]
            if past.notna().sum() >= 4 and nxt.notna().sum() >= 1:
                d[sec] = (float(np.prod(1 + past.fillna(0)) - 1), float(np.prod(1 + nxt.fillna(0)) - 1), code)
        if len(d) >= MIN_SECT:
            rows.append((a, d))
    return rows


def portfolio(rows, side="lo", k=K):
    out, prev = [], set()
    for a, d in rows:
        order = sorted(d, key=lambda s: d[s][0])
        sel = order[:k] if side == "lo" else order[-k:]
        cur = {d[s][2] for s in sel}
        to = 1.0 if not prev else len(cur - prev) / k
        r = np.mean([d[s][1] for s in sel])
        ew = np.mean([v[1] for v in d.values()])
        out.append((a, r, ew, to))
        prev = cur
    s = pd.DataFrame(out, columns=["date", "ret", "ew", "to"]).set_index("date")
    s["ex"] = s["ret"] - s["ew"]
    s["net_ex"] = s["ex"] - s["to"] * COST
    return s


def wsel(idx, w):
    a, b = WINDOWS[w]
    return (idx.year >= a) & (idx.year <= b)


def stats(r):
    eq = (1 + r).cumprod()
    return dict(cagr=float(eq.iloc[-1] ** (52 / len(r)) - 1), sharpe=float(r.mean() / r.std() * np.sqrt(52)), mdd=float((eq / eq.cummax() - 1).min()))


def run():
    p = e.load_panel()
    rows = weekly_table(*sector_closes(p))
    rng = np.random.default_rng(SEED)
    lo, hi = portfolio(rows, "lo"), portfolio(rows, "hi")
    tr = [(a, d) for a, d in rows if WINDOWS["TRAIN"][0] <= a.year <= WINDOWS["TRAIN"][1]]
    null = np.zeros(REPS)
    for a, d in tr:
        nx = np.array([v[1] for v in d.values()])
        idx = np.argsort(rng.random((REPS, len(nx))), axis=1)[:, :K]
        null += nx[idx].mean(1) - nx.mean()
    floor = float(np.percentile(null / max(len(tr), 1), 95))
    res = {}
    for nm, s in (("하위 3(역추세)", lo), ("상위 3(모멘텀, 기록)", hi)):
        res[nm] = {w: dict(weeks=int(wsel(s.index, w).sum()), ex=float(s["ex"][wsel(s.index, w)].mean()), net_ex=float(s["net_ex"][wsel(s.index, w)].mean()),
                           turnover=float(s["to"][wsel(s.index, w)].mean()), cell=stats(s["ret"][wsel(s.index, w)] - s["to"][wsel(s.index, w)] * COST),
                           ew=stats(s["ew"][wsel(s.index, w)])) for w in WINDOWS}
    r = res["하위 3(역추세)"]
    info = r["TRAIN"]["ex"] >= floor and r["VALID"]["ex"] > 0 and r["TEST"]["ex"] > 0
    econ = info and r["VALID"]["net_ex"] > 0 and r["TEST"]["net_ex"] > 0
    verdict = "ECONOMIC" if econ else ("INFORMATION" if info else "REJECT")
    nsect = pd.Series([len(d) for _, d in rows], index=[a for a, _ in rows])
    out = dict(verdict=verdict, floor=floor, res=res, n_sect={w: float(nsect[wsel(nsect.index, w)].mean()) for w in WINDOWS})
    OUT.with_suffix(".json").write_text(json.dumps(out, ensure_ascii=False, indent=1, default=float), encoding="utf-8")
    L = ["---", "track: kr", "factor: sector-etf-weekly-reversal", "date: 2026-10-09", f"verdict: {verdict}",
         "criteria_version: research-only (sector-etf-weekly-reversal-preregistration-2026-10)",
         'conditions: ["KRX 전통 업종 15개 대표 ETF", "지난 1주 하위 3 업종 등가중 1주 보유", "무작위 3 업종 1,000회 95백분위", "비용 5bp × 회전율"]',
         "reason: >-", f"  신호: {'있음' if verdict != 'REJECT' else '없음'} · 경제성: {'통과' if verdict == 'ECONOMIC' else '미달'}. (스크립트 판정, 바닥선 {floor * 1e4:+.1f}bp/주)", "---", "",
         "# 국내 업종 ETF 주간 역추세 — 결과", "", "| 칸 | 구간 | 주 | 업종 수(평균) | 주평균 초과 | 비용 후 | 회전율 | CAGR/샤프/MDD(비용 후) | 업종 등가중 CAGR/샤프/MDD |", "|---|---|---:|---:|---:|---:|---:|---|---|"]
    for nm, rr in res.items():
        for w in WINDOWS:
            x = rr[w]
            L.append(f"| {nm} | {w} | {x['weeks']} | {out['n_sect'][w]:.1f} | {x['ex'] * 1e4:+.1f}bp | {x['net_ex'] * 1e4:+.1f}bp | {x['turnover']:.2f} | "
                     f"{x['cell']['cagr'] * 100:+.1f}% / {x['cell']['sharpe']:.2f} / {x['cell']['mdd'] * 100:.1f}% | {x['ew']['cagr'] * 100:+.1f}% / {x['ew']['sharpe']:.2f} / {x['ew']['mdd'] * 100:.1f}% |")
    L += ["", f"판정: **{verdict}** (TRAIN 바닥선 {floor * 1e4:+.1f}bp/주)."]
    OUT.with_suffix(".md").write_text("\n".join(L) + "\n", encoding="utf-8")
    print(verdict, {nm: {w: round(rr[w]["ex"] * 1e4, 1) for w in WINDOWS} for nm, rr in res.items()}, "floor", round(floor * 1e4, 1))
    return 0


def selftest():
    ok = True

    def check(name, cond):
        nonlocal ok
        ok &= bool(cond)
        print(("PASS " if cond else "FAIL ") + name)

    d = {f"s{i}": (i / 100, 0.01 * (i % 3), f"c{i}") for i in range(10)}
    s = portfolio([(pd.Timestamp("2020-01-03"), d)], "lo")
    check("하위 3 = s0·s1·s2(지난주 수익 최저), 다음 주 수익 평균 (0+0.01+0.02)/3", abs(s["ret"].iloc[0] - 0.01) < 1e-12)
    check("첫 주 회전율 1", s["to"].iloc[0] == 1.0)
    print("ALL PASS" if ok else "FAILED")
    return 0 if ok else 1


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--selftest", action="store_true")
    sys.exit(selftest() if ap.parse_args().selftest else run())
