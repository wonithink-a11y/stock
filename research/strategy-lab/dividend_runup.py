#!/usr/bin/env python3
"""고배당주 연말 랠리 — 사전등록 findings/dividend-runup-preregistration-2026-10.md 그대로.

    python research/strategy-lab/dividend_runup.py --selftest
    python research/strategy-lab/dividend_runup.py      # → findings/dividend-runup-results-2026-10.{md,json}
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
import krx_daily_panel as kp
import dividend_capture as dc

OUT = HERE / "findings" / "dividend-runup-results-2026-10"
SEED, REPS, COST = 20261009, 10000, 0.00335
WINDOWS = {"TRAIN": (2010, 2015), "VALID": (2016, 2019), "TEST": (2020, 2022), "REC": (2023, 2025)}


def window(dates, y):
    """(시작 행 = 11월 마지막 거래일, 끝 행 = 마지막 거래일 − 2)."""
    nov = np.flatnonzero((dates.year == y) & (dates.month == 11))
    D = int(np.flatnonzero(dates.year == y).max())
    return int(nov.max()), D - 2


def run():
    dates, tick, M, names, market = kp.build()
    R = kp.clean_returns(M["R"])
    ti = {t: j for j, t in enumerate(tick)}
    liq = pd.DataFrame(M["VAL"].astype(float)).rolling(20, min_periods=10).mean().to_numpy()
    traded = ~np.isnan(R)
    cs = np.vstack([np.zeros((1, R.shape[1])), np.cumsum(np.log1p(np.nan_to_num(R, nan=0.0)), axis=0)])
    ew_cs = np.r_[0.0, np.cumsum(np.log1p(np.nan_to_num(np.nanmean(R, axis=1))))]
    rng = np.random.default_rng(SEED)
    rows, null, nyr = [], np.zeros(REPS), 0
    for y in range(2010, 2026):
        f = dc.PBR / f"{y}-11.parquet"
        if not f.exists():
            continue
        s, e = window(dates, y)
        dv = pd.read_parquet(f).drop_duplicates("ticker").set_index("ticker")["DIV"]
        js, divs = [], []
        for t, d in dv.items():
            j = ti.get(t)
            if j is None or not (d >= dc.DIV_MIN) or t[-1] != "0" or dc.SPAC.search(names.get(t, "")):
                continue
            if traded[s, j] and liq[s, j] >= dc.LIQ:
                js.append(j)
                divs.append(d)
        js, divs = np.array(js), np.array(divs)
        L = e - s
        stock = np.exp(cs[e + 1, js] - cs[s + 1, js]) - 1
        mkt = np.exp(ew_cs[e + 1] - ew_cs[s + 1]) - 1
        ex = float(stock.mean() - mkt)
        rows.append(dict(year=y, n=len(js), ex=ex, ex_lo=float(stock[divs < 5].mean() - mkt), ex_hi=float(stock[divs >= 5].mean() - mkt)))
        if y <= 2022:
            yr = np.flatnonzero(dates.year == y)
            allowed = yr[~np.isin(dates[yr].month, [11, 12])]
            allowed = allowed[allowed + L + 1 < len(dates)]
            st = rng.choice(allowed, REPS)
            sn = (np.exp(cs[st + L + 1][:, js] - cs[st + 1][:, js]) - 1).mean(1) - (np.exp(ew_cs[st + L + 1] - ew_cs[st + 1]) - 1)
            null += sn
            nyr += 1
    null /= nyr
    df = pd.DataFrame(rows)
    df["win"] = df["year"].map(lambda y: next(w for w, (a, b) in WINDOWS.items() if a <= y <= b))
    bw = {w: float(df.loc[df["win"] == w, "ex"].mean()) for w in WINDOWS}
    m = float(df.loc[df["year"] <= 2022, "ex"].mean())
    p95 = float(np.percentile(null, 95))
    info = m > p95 and all(bw[w] > 0 for w in ("TRAIN", "VALID", "TEST"))
    econ = info and bw["VALID"] > COST and bw["TEST"] > COST
    verdict = "ECONOMIC" if econ else ("INFORMATION" if info else "REJECT")
    out = dict(verdict=verdict, mean=m, null95=p95, null_mean=float(null.mean()), by_win=bw, years=rows)
    OUT.with_suffix(".json").write_text(json.dumps(out, ensure_ascii=False, indent=1, default=float), encoding="utf-8")
    pc = lambda x: f"{x * 100:+.2f}%"
    L_ = ["---", "track: kr", "factor: dividend-runup", "date: 2026-10-09", f"verdict: {verdict}", "criteria_version: research-only (dividend-runup-preregistration-2026-10)",
          'conditions: ["11월 말 DIV ≥ 3% 보통주 등가중", "11월 마지막 거래일 → 마지막 거래일 − 2", "KRX 전종목 등가중 대비", "같은 해 다른 위치 10,000회 95백분위"]',
          "reason: >-", f"  신호: {'있음' if verdict != 'REJECT' else '없음'} · 경제성: {'통과' if verdict == 'ECONOMIC' else '미달'}. 2010~2022 평균 초과 {pc(m)}, 귀무 95백분위 {pc(p95)}. (스크립트 판정)", "---", "",
          "# 고배당주 연말 랠리 — 결과", "", "| 구간 | 평균 초과 |", "|---|---:|"] + [f"| {w} | {pc(v)} |" for w, v in bw.items()] + [
          "", f"귀무(같은 종목, 다른 위치) 평균 {pc(null.mean())} · 95백분위 {pc(p95)} · 판정 **{verdict}**.", "",
          "| 해 | 종목 수 | 초과 | DIV 3~5% | DIV ≥5% |", "|---|---:|---:|---:|---:|"] + [f"| {r['year']} | {r['n']} | {pc(r['ex'])} | {pc(r['ex_lo'])} | {pc(r['ex_hi'])} |" for r in rows]
    OUT.with_suffix(".md").write_text("\n".join(L_) + "\n", encoding="utf-8")
    print(verdict, pc(m), pc(p95), {w: pc(v) for w, v in bw.items()})
    return 0


def selftest():
    ok = True

    def check(name, cond):
        nonlocal ok
        ok &= bool(cond)
        print(("PASS " if cond else "FAIL ") + name)

    dates = pd.bdate_range("2020-10-01", "2020-12-31")
    s, e = window(dates, 2020)
    check("시작 = 11/30, 끝 = 12/29(마지막 12/31 − 2)", dates[s] == pd.Timestamp("2020-11-30") and dates[e] == pd.Timestamp("2020-12-29"))
    print("ALL PASS" if ok else "FAILED")
    return 0 if ok else 1


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--selftest", action="store_true")
    sys.exit(selftest() if ap.parse_args().selftest else run())
