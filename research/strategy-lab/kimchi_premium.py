#!/usr/bin/env python3
"""김치 프리미엄 → 비트코인 30일 — 사전등록 findings/kimchi-premium-preregistration-2026-10.md 그대로.

    python research/strategy-lab/kimchi_premium.py --selftest
    python research/strategy-lab/kimchi_premium.py      # → findings/kimchi-premium-results-2026-10.{md,json}

환율: data/kimchi/dexkous.parquet(FRED DEXKOUS — 새로 받기는 시간 초과라 저장소 사본, 2026-08-21 까지). KP 는 환율이 있는 날까지만 계산한다.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
D = HERE / "data" / "kimchi"
OUT = HERE / "findings" / "kimchi-premium-results-2026-10"
LOOK, LOOK_MIN, QH, QL, H, GAP = 365, 300, 0.90, 0.10, 30, 30
SEED, REPS, MIN_EP = 20261009, 1000, 5
WINDOWS = {"TRAIN": ("2018-10-01", "2020-12-31"), "VALID": ("2021-01-01", "2022-12-31"), "TEST": ("2023-01-01", "2026-12-31")}


def premium(coin):
    up = pd.read_parquet(D / f"upbit_KRW-{coin}.parquet").set_index("date")["close"]
    bn = pd.read_parquet(D / f"binance_{coin}USDT.parquet").set_index("date")["close"]
    fx = pd.read_parquet(D / "dexkous.parquet").set_index("date")["fx"].sort_index()
    idx = up.index.intersection(bn.index)
    fx_prev = pd.Series(fx.reindex(fx.index.union(idx)).ffill().shift(1).reindex(idx).to_numpy(), index=idx)   # d 이전 마지막 영업일 환율
    fx_prev[idx > fx.index.max() + pd.Timedelta(days=3)] = np.nan
    kp = up.reindex(idx) / (bn.reindex(idx) * fx_prev) - 1
    return kp.dropna(), bn


def signals(kp):
    hi = kp.shift(1).rolling(LOOK, min_periods=LOOK_MIN).quantile(QH)
    lo = kp.shift(1).rolling(LOOK, min_periods=LOOK_MIN).quantile(QL)
    return {"KPH": kp >= hi, "KPL": kp <= lo}


def episodes(mask, gap=GAP):
    out, last = [], None
    for d in mask[mask].index:
        if last is None or (d - last).days > gap:
            out.append(d)
            last = d
    return out


def fwd(bn, h):
    return bn.shift(-h) / bn - 1


def win_of(d):
    return next((w for w, (a, b) in WINDOWS.items() if pd.Timestamp(a) <= d <= pd.Timestamp(b)), None)


def evaluate(kp, bn, rng, h=H):
    f = fwd(bn, h).reindex(kp.index)
    res = {}
    for cell, m in signals(kp).items():
        ev = [d for d in episodes(m) if win_of(d) and np.isfinite(f.get(d, np.nan))]
        by = {}
        for w, (a, b) in WINDOWS.items():
            ew = [d for d in ev if win_of(d) == w]
            pool = f[(f.index >= a) & (f.index <= b)].dropna()
            by[w] = dict(n=len(ew), mean=float(f[ew].mean()) if ew else np.nan, base=float(pool.mean()), ex=float(f[ew].mean() - pool.mean()) if ew else np.nan)
        allpool = f[[win_of(d) is not None for d in f.index]].dropna().to_numpy()
        n = len(ev)
        null = rng.choice(allpool, (REPS, n)).mean(1) - allpool.mean() if n else np.array([np.nan])
        ex_all = float(f[ev].mean() - allpool.mean()) if n else np.nan
        lo, hi = np.percentile(null, [1, 99])
        enough = all(by[w]["n"] >= MIN_EP for w in WINDOWS)
        sign = -1 if cell == "KPH" else 1
        ok = enough and (ex_all < lo if sign < 0 else ex_all > hi) and all(np.sign(by[w]["ex"]) == sign for w in WINDOWS)
        res[cell] = dict(n=n, ex_all=ex_all, null=[float(lo), float(hi)], by_win=by, verdict="CONFIRMED" if ok else ("INCONCLUSIVE(표본 부족)" if not enough else "NONE"),
                         dates=[str(d.date()) for d in ev])
    return res


def run():
    rng = np.random.default_rng(SEED)
    kp, bn = premium("BTC")
    res = evaluate(kp, bn, rng)
    kpe, bne = premium("ETH")
    rec = {"ETH 30일": evaluate(kpe, bne, rng), "BTC 7일": evaluate(kp, bn, rng, 7), "BTC 90일": evaluate(kp, bn, rng, 90)}
    f30 = fwd(bn, H).reindex(kp.index)
    absr = {}
    for nm, m in (("KP ≥ 5%", kp >= 0.05), ("KP ≤ −1%", kp <= -0.01)):
        ev = [d for d in episodes(m) if np.isfinite(f30.get(d, np.nan))]
        absr[nm] = dict(n=len(ev), mean=float(f30[ev].mean()) if ev else np.nan, base=float(f30.dropna().mean()))
    summ = dict(mean=float(kp.mean()), median=float(kp.median()), max=float(kp.max()), max_date=str(kp.idxmax().date()), min=float(kp.min()), min_date=str(kp.idxmin().date()),
                range=[str(kp.index.min().date()), str(kp.index.max().date())],
                yearly={int(y): float(v) for y, v in kp.groupby(kp.index.year).mean().items()})
    out = dict(res=res, rec=rec, abs=absr, kp=summ)
    OUT.with_suffix(".json").write_text(json.dumps(out, ensure_ascii=False, indent=1, default=float), encoding="utf-8")
    pc = lambda x: "" if x is None or not np.isfinite(x) else f"{x * 100:+.1f}%"
    v = {k: r["verdict"] for k, r in res.items()}
    L = ["---", "track: crypto", "factor: kimchi-premium", "date: 2026-10-09", f"verdict: {'CONFIRMED' if 'CONFIRMED' in v.values() else 'NONE'}",
         "criteria_version: research-only (kimchi-premium-preregistration-2026-10)",
         'conditions: ["업비트 KRW ÷ (바이낸스 USDT × FRED 원/달러 전일) − 1", "KP ≥ 365일 90백분위(KPH)·≤ 10백분위(KPL) → BTC 30일", "무작위 날짜 1,000회 1·99백분위, 에피소드 30일"]',
         "reason: >-", "  " + " · ".join(f"{k} {x}" for k, x in v.items()) + ". (스크립트 판정)", "---", "",
         "# 김치 프리미엄 → 비트코인 30일 — 결과", "",
         f"KP {summ['range'][0]} ~ {summ['range'][1]}: 평균 {pc(summ['mean'])} · 중앙 {pc(summ['median'])} · 최고 {pc(summ['max'])}({summ['max_date']}) · 최저 {pc(summ['min'])}({summ['min_date']}).",
         "연도별 평균: " + " · ".join(f"{y} {pc(x)}" for y, x in summ["yearly"].items()), "",
         "| 칸 | 에피소드 | 전체 초과(30일) | 귀무 1·99백분위 | TRAIN | VALID | TEST | 판정 |", "|---|---:|---:|---|---|---|---|---|"]
    for k, r in res.items():
        L.append(f"| {k} | {r['n']} | {pc(r['ex_all'])} | {pc(r['null'][0])} · {pc(r['null'][1])} | " +
                 " | ".join(f"{pc(r['by_win'][w]['ex'])}({r['by_win'][w]['n']})" for w in WINDOWS) + f" | **{r['verdict']}** |")
    L += ["", "## 기록", ""]
    for nm, rr in rec.items():
        L.append(f"- {nm}: " + " · ".join(f"{k} {r['n']}건 초과 {pc(r['ex_all'])} ({' / '.join(pc(r['by_win'][w]['ex']) for w in WINDOWS)})" for k, r in rr.items()))
    L.append("- 절대 문턱: " + " · ".join(f"{k} {r['n']}건 30일 {pc(r['mean'])}(전체 평균 {pc(r['base'])})" for k, r in absr.items()))
    for k, r in res.items():
        L.append(f"- {k} 신호일: " + ", ".join(r["dates"]))
    OUT.with_suffix(".md").write_text("\n".join(L) + "\n", encoding="utf-8")
    for k, r in res.items():
        print(k, r["verdict"], r["n"], pc(r["ex_all"]), {w: (r["by_win"][w]["n"], pc(r["by_win"][w]["ex"])) for w in WINDOWS})
    print(summ["mean"], summ["max"], summ["max_date"])
    return 0


def selftest():
    ok = True

    def check(name, cond):
        nonlocal ok
        ok &= bool(cond)
        print(("PASS " if cond else "FAIL ") + name)

    idx = pd.date_range("2020-01-01", periods=10, freq="D")
    m = pd.Series([False, True, True, False] + [False] * 6, index=idx)
    check("에피소드 30일 — 첫 신호만", episodes(m) == [idx[1]])
    check("구간", win_of(pd.Timestamp("2021-05-01")) == "VALID" and win_of(pd.Timestamp("2018-01-01")) is None)
    print("ALL PASS" if ok else "FAILED")
    return 0 if ok else 1


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--selftest", action="store_true")
    sys.exit(selftest() if ap.parse_args().selftest else run())
