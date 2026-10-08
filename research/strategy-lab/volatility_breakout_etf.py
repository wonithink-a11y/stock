#!/usr/bin/env python3
"""변동성 돌파(래리 윌리엄스) — KODEX 200 — 사전등록 findings/volatility-breakout-etf-preregistration-2026-10.md 그대로.

    python research/strategy-lab/volatility_breakout_etf.py --selftest
    python research/strategy-lab/volatility_breakout_etf.py      # → findings/volatility-breakout-etf-results-2026-10.{md,json}
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

OUT = HERE / "findings" / "volatility-breakout-etf-results-2026-10"
K, COST, STRESS_COST, TICK = 0.5, 0.0005, 0.0010, 5.0
SEED, REPS = 20261009, 1000
WINDOWS = {"TRAIN": (2010, 2016), "VALID": (2017, 2020), "TEST": (2021, 2026)}


def bars(panel, code):
    c = panel[panel["code"] == code].set_index("date").sort_index()
    c = c[(c["open"] > 0) & (c["high"] > 0) & (c["low"] > 0) & (c["close"] > 0)].copy()
    gap = c["idx"].pct_change() - c["nav"].pct_change()
    c["dist"] = gap.where((gap > e.DIST_TH) & (gap < 0.2), 0.0).fillna(0.0) if code in e.DIST_CODES else 0.0
    return c


def trades(c, k=K, ma5=False, tick=0.0, cost=COST):
    """반환: DataFrame(진입일 index, ret) — 다음 날 시가 청산, 분배락 복원."""
    trig = c["open"] + k * (c["high"] - c["low"]).shift(1)
    hit = c["high"] >= trig
    if ma5:
        hit &= c["open"] > c["close"].shift(1).rolling(5).mean()
    entry = np.maximum(c["open"], trig) + tick
    exit_ = c["open"].shift(-1)
    ret = exit_ / entry - 1 + c["dist"].shift(-1).fillna(0.0) * c["close"] / entry - cost
    return pd.DataFrame({"ret": ret[hit & exit_.notna() & trig.notna()]})


def oo_returns(c):
    return (c["open"].shift(-1) / c["open"] - 1 + c["dist"].shift(-1).fillna(0.0) * c["close"] / c["open"]).dropna()


def win_sel(idx, w):
    a, b = WINDOWS[w]
    return (idx.year >= a) & (idx.year <= b)


def summarize(c, t, rng, gross_t=None):
    oo = oo_returns(c)
    out = {}
    for w in WINDOWS:
        tr = t[win_sel(t.index, w)]["ret"]
        g = (gross_t[win_sel(gross_t.index, w)]["ret"] if gross_t is not None else tr)
        pool = oo[win_sel(oo.index, w)].to_numpy()
        n = len(tr)
        null = rng.choice(pool, (REPS, n)).mean(1) if n else np.array([np.nan])
        daily = pd.Series(0.0, index=oo.index[win_sel(oo.index, w)])
        daily.loc[daily.index.intersection(tr.index)] = tr.reindex(daily.index.intersection(tr.index)).to_numpy()
        eq = (1 + daily).cumprod()
        yrs = len(daily) / 252
        out[w] = dict(n=n, per_year=n / yrs if yrs else np.nan, mean=float(tr.mean()), median=float(tr.median()), win=float((tr > 0).mean()),
                      gross_mean=float(g.mean()), excess=float(g.mean() - pool.mean()), null_p95=float(np.percentile(null - pool.mean(), 95)),
                      cagr=float(eq.iloc[-1] ** (1 / yrs) - 1) if yrs else np.nan, sharpe=float(daily.mean() / daily.std() * np.sqrt(252)),
                      mdd=float((eq / eq.cummax() - 1).min()), bh_sharpe=float(pool.mean() / pool.std() * np.sqrt(252)),
                      bh_cagr=float(np.prod(1 + pool) ** (1 / yrs) - 1) if yrs else np.nan, breakeven_bp=float(g.mean() * 1e4))
    return out


def run():
    p = e.load_panel()
    rng = np.random.default_rng(SEED)
    c = bars(p, e.K200)
    gross = trades(c, cost=0.0)
    base = summarize(c, trades(c), rng, gross)
    stress = summarize(c, trades(c, tick=TICK, cost=STRESS_COST), rng, gross)
    floor = base["TRAIN"]["null_p95"]
    info = base["TRAIN"]["excess"] >= floor and base["VALID"]["excess"] > 0 and base["TEST"]["excess"] > 0
    econ = info and all(base[w]["mean"] > 0 and stress[w]["mean"] > 0 for w in ("VALID", "TEST"))
    verdict = "ECONOMIC" if econ else ("INFORMATION" if info else "REJECT")
    grid = {k: summarize(c, trades(c, k), rng, trades(c, k, cost=0.0))["TRAIN"]["excess"] for k in (0.3, 0.4, 0.5, 0.6, 0.7)}
    kbest = max(grid, key=grid.get)
    opt = dict(chosen=kbest, train=grid, oos={w: summarize(c, trades(c, kbest), rng, trades(c, kbest, cost=0.0))[w]["excess"] for w in ("VALID", "TEST")})
    rec = {"5일선 필터": summarize(c, trades(c, ma5=True), rng, trades(c, ma5=True, cost=0.0))}
    for code, nm in ((e.KQ150, "코스닥150"), ("122630", "KODEX 레버리지")):
        cc = bars(p, code)
        rec[nm] = summarize(cc, trades(cc), rng, trades(cc, cost=0.0))
    out = dict(verdict=verdict, base=base, stress=stress, opt=opt, rec=rec)
    OUT.with_suffix(".json").write_text(json.dumps(out, ensure_ascii=False, indent=1, default=float), encoding="utf-8")
    OUT.with_suffix(".md").write_text(render(out), encoding="utf-8")
    print(verdict, {w: (base[w]["n"], round(base[w]["excess"] * 1e4, 1), round(base[w]["mean"] * 1e4, 1)) for w in WINDOWS}, "floor", round(floor * 1e4, 1))
    print("opt", kbest, {k: round(v * 1e4, 1) for k, v in grid.items()}, {w: round(v * 1e4, 1) for w, v in opt["oos"].items()})
    return 0


def bp(x):
    return "" if x is None or not np.isfinite(x) else f"{x * 1e4:+.1f}bp"


def render(o):
    v = o["verdict"]
    L = ["---", "track: kr", "factor: volatility-breakout-etf", "date: 2026-10-09", f"verdict: {v}",
         "criteria_version: research-only (volatility-breakout-etf-preregistration-2026-10)",
         'conditions: ["KODEX 200 일봉 2010~2026-10", "트리거 = 시가 + 0.5 × 전일 변동폭, 다음 날 시가 청산", "무작위 날짜 시가→다음 시가 1,000회 95백분위", "비용 5bp, 스트레스 +1호가·10bp"]',
         "reason: >-", f"  신호: {'있음' if v != 'REJECT' else '없음'} · 경제성: {'통과' if v == 'ECONOMIC' else '미달'}. (스크립트 판정)", "---", "",
         "# 변동성 돌파(래리 윌리엄스) — KODEX 200 — 결과", "",
         "| 구간 | 거래 | 연 거래 | 거래당 gross 초과(무작위 대비) | 바닥선 | 비용 후 거래당 평균 | 중앙 | 승률 | 스트레스 평균 | 손익분기 | 전략 CAGR/샤프/MDD | 보유 CAGR/샤프 |",
         "|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---|---|"]
    for w in WINDOWS:
        b, s = o["base"][w], o["stress"][w]
        L.append(f"| {w} | {b['n']} | {b['per_year']:.0f} | {bp(b['excess'])} | {bp(b['null_p95']) if w == 'TRAIN' else ''} | {bp(b['mean'])} | {bp(b['median'])} | {b['win']:.0%} | "
                 f"{bp(s['mean'])} | {b['breakeven_bp']:+.1f}bp | {b['cagr'] * 100:+.1f}% / {b['sharpe']:.2f} / {b['mdd'] * 100:.1f}% | {b['bh_cagr'] * 100:+.1f}% / {b['bh_sharpe']:.2f} |")
    L += ["", f"## 기록", "", f"- k 최적화(TRAIN 초과): " + " · ".join(f"{k} {bp(x)}" for k, x in o["opt"]["train"].items()) +
          f" → 고른 k {o['opt']['chosen']} 의 VALID {bp(o['opt']['oos']['VALID'])} · TEST {bp(o['opt']['oos']['TEST'])}."]
    for nm, r in o["rec"].items():
        L.append(f"- {nm}: " + " · ".join(f"{w} 거래 {r[w]['n']} 초과 {bp(r[w]['excess'])} 비용 후 평균 {bp(r[w]['mean'])}" for w in WINDOWS))
    return "\n".join(L) + "\n"


def selftest():
    ok = True

    def check(name, cond):
        nonlocal ok
        ok &= bool(cond)
        print(("PASS " if cond else "FAIL ") + name)

    idx = pd.bdate_range("2020-01-01", periods=4)
    c = pd.DataFrame({"open": [100, 100, 101, 105.0], "high": [102, 104, 101.5, 106], "low": [98, 99, 100, 104], "close": [101, 103, 101, 105], "dist": 0.0}, index=idx)
    t = trades(c, 0.5, cost=0.0)
    # 1일: 트리거 100 + 0.5×4 = 102, 고가 104 ≥ 102 → 102 에 사서 2일 시가 101 → −0.98%
    check("돌파 날 트리거 가격 진입·다음 날 시가 청산", list(t.index) == [idx[1]] and abs(t["ret"].iloc[0] - (101 / 102 - 1)) < 1e-12)
    c2 = c.copy()
    c2.loc[idx[1], "open"] = 103.0
    t2 = trades(c2, 0.5, cost=0.0)
    check("시가 103 → 트리거 105 > 고가 104 → 그날 거래 없음", idx[1] not in t2.index)
    print("ALL PASS" if ok else "FAILED")
    return 0 if ok else 1


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--selftest", action="store_true")
    sys.exit(selftest() if ap.parse_args().selftest else run())
