#!/usr/bin/env python3
"""보통주·우선주 괴리 스위칭 — 사전등록 findings/pref-common-switch-preregistration-2026-10.md 그대로.

    python research/strategy-lab/pref_common_switch.py --selftest
    python research/strategy-lab/pref_common_switch.py      # → findings/pref-common-switch-results-2026-10.{md,json}
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

OUT = HERE / "findings" / "pref-common-switch-results-2026-10"
Z, LOOK, LOOK_MIN, H, GAP, EXCL = 2.0, 250, 200, 20, 40, 20
LIQ_P, LIQ_C, COST = 3e8, 1e9, 0.00335
SEED, REPS, BOOT, BLOCK = 20261009, 1000, 2000, 6
WINDOWS = {"TRAIN": (2010, 2017), "VALID": (2018, 2021), "TEST": (2022, 2026)}


def win_of(y):
    return next((w for w, (a, b) in WINDOWS.items() if a <= y <= b), None)


def pairs(tick):
    s = set(tick)
    return [(p, p[:5] + "0") for p in tick if p[-1] != "0" and p[:5] + "0" in s]


def zscore(s):
    mu = s.shift(1).rolling(LOOK, min_periods=LOOK_MIN).mean()
    sd = s.shift(1).rolling(LOOK, min_periods=LOOK_MIN).std()
    return (s - mu) / sd


def crossings(z, side, z_th=Z):
    if side == "cheap":
        return (z <= -z_th) & (z.shift(1) > -z_th)
    return (z >= z_th) & (z.shift(1) < z_th)


def dedup_idx(ix, gap=GAP):
    keep, last = [], -10 ** 9
    for i in ix:
        if i - last > gap:
            keep.append(i)
            last = i
    return keep


def season_ok(d):
    return not ((d.month == 12) or (d.month == 1 and d.day <= 10))


def analyze(dates, tick, M, z_th=Z, h=H):
    ti = {t: j for j, t in enumerate(tick)}
    R, VAL = M["R"], M["VAL"]
    L = np.cumsum(np.log1p(np.nan_to_num(R, nan=0.0)), axis=0)
    liq = pd.DataFrame(VAL).rolling(20, min_periods=10).mean().to_numpy()
    traded = ~np.isnan(R)
    events = {"cheap": [], "rich": []}
    pool = {}
    for p, c in pairs(tick):
        jp, jc = ti[p], ti[c]
        both = traded[:, jp] & traded[:, jc]
        if both.sum() < LOOK_MIN + h + 2:
            continue
        s = pd.Series(np.where(both, L[:, jp] - L[:, jc], np.nan))
        z = zscore(s)
        elig = both & (liq[:, jp] >= LIQ_P) & (liq[:, jc] >= LIQ_C) & np.array([season_ok(d) for d in dates])
        T = len(dates)
        valid_out = np.zeros(T, bool)
        valid_out[: T - h - 1] = True
        rel = np.full(T, np.nan)
        t = np.arange(T - h - 1)
        dp = np.exp(L[t + 1 + h, jp] - L[t + 1, jp]) - 1
        dc = np.exp(L[t + 1 + h, jc] - L[t + 1, jc]) - 1
        rel[t] = dp - dc
        ok = elig & valid_out & np.isfinite(rel)
        ev_idx = set()
        for side in ("cheap", "rich"):
            cr = crossings(z, side, z_th).to_numpy()
            ix = dedup_idx(np.flatnonzero(cr & ok))
            for i in ix:
                events[side].append((p, i, dates[i], rel[i] if side == "cheap" else -rel[i]))
                ev_idx.update(range(i - EXCL, i + EXCL + 1))
        cand = np.array([i for i in np.flatnonzero(ok) if i not in ev_idx])
        pool[p] = (cand, rel)
    return events, pool


def summarize(ev, pool, side, rng):
    df = pd.DataFrame(ev, columns=["pair", "i", "date", "rel"])
    if df.empty:
        return None
    df["win"] = df["date"].dt.year.map(win_of)
    df["mi"] = (df["date"].dt.year - 2010) * 12 + df["date"].dt.month - 1
    null = np.zeros(REPS)
    for _, r in df.iterrows():
        cand, rel = pool[r["pair"]]
        if len(cand) == 0:
            null += np.nan
            continue
        x = rel[rng.choice(cand, REPS)]
        null += x if side == "cheap" else -x
    null /= len(df)
    mm = df.groupby("mi")["rel"].mean().sort_index()
    nb = int(np.ceil(len(mm) / BLOCK))
    st = rng.integers(0, max(len(mm) - BLOCK + 1, 1), (BOOT, nb))
    idx = (st[:, :, None] + np.arange(BLOCK)).reshape(BOOT, -1)[:, : len(mm)]
    boot = mm.to_numpy()[np.minimum(idx, len(mm) - 1)].mean(1)
    out = dict(n=len(df), pairs=int(df["pair"].nunique()), mean=float(df["rel"].mean()), median=float(df["rel"].median()), win=float((df["rel"] > 0).mean()),
               null_99=float(np.nanpercentile(null, 99)), null_mean=float(np.nanmean(null)),
               ci=[float(np.percentile(boot, 2.5)), float(np.percentile(boot, 97.5))],
               by_win={w: dict(n=int((df["win"] == w).sum()), mean=float(df.loc[df["win"] == w, "rel"].mean())) for w in WINDOWS},
               top_pairs=df.groupby("pair")["rel"].agg(["count", "mean"]).sort_values("count", ascending=False).head(10).round(4).reset_index().values.tolist())
    info = out["mean"] > out["null_99"] and all(out["by_win"][w]["mean"] > 0 for w in WINDOWS) and out["ci"][0] > 0
    econ = info and all(out["by_win"][w]["mean"] > COST for w in ("VALID", "TEST"))
    out["verdict"] = "ECONOMIC" if econ else ("INFORMATION" if info else "REJECT")
    return out


def run():
    dates, tick, M, names, market = kp.build()
    rng = np.random.default_rng(SEED)
    ev, pool = analyze(dates, tick, M)
    res = {side: summarize(ev[side], pool, side, rng) for side in ("cheap", "rich")}
    rec = {}
    for zt in (1.5, 2.5):
        e2, p2 = analyze(dates, tick, M, z_th=zt)
        rec[f"z{zt}"] = {sd: (lambda r: None if r is None else dict(n=r["n"], mean=r["mean"], by_win={w: r["by_win"][w]["mean"] for w in WINDOWS}))(summarize(e2[sd], p2, sd, rng)) for sd in ("cheap", "rich")}
    out = dict(res=res, rec=rec, n_pairs=len(pairs(tick)), dates=[str(dates[0].date()), str(dates[-1].date())],
               names={p: names.get(p, "") for p in {r[0] for side in ev for r in ev[side]}})
    OUT.with_suffix(".json").write_text(json.dumps(out, ensure_ascii=False, indent=1, default=float), encoding="utf-8")
    OUT.with_suffix(".md").write_text(render(out), encoding="utf-8")
    for side, r in res.items():
        print(side, None if r is None else (r["verdict"], r["n"], round(r["mean"] * 1e4, 1), {w: round(r["by_win"][w]["mean"] * 1e4, 1) for w in WINDOWS}, round(r["null_99"] * 1e4, 1)))
    return 0


def bp(x):
    return "" if x is None or not np.isfinite(x) else f"{x * 1e4:+.0f}bp"


def render(o):
    v = {k: (r or {}).get("verdict", "자료 없음") for k, r in o["res"].items()}
    pos = [k for k, x in v.items() if x in ("INFORMATION", "ECONOMIC")]
    L = ["---", "track: kr", "factor: pref-common-switch", "date: 2026-10-09",
         f"verdict: {'ECONOMIC' if 'ECONOMIC' in v.values() else ('INFORMATION' if pos else 'REJECT')}",
         "criteria_version: research-only (pref-common-switch-preregistration-2026-10)",
         'conditions: ["KRX 일별 전종목 2010~2026, FLUC_RT 지수", "괴리 z(250일) ±2 처음 넘음 → 20거래일 상대 수익", "같은 짝 무작위 날짜 1,000회 99백분위", "갈아타기 비용 33.5bp"]',
         "reason: >-", f"  신호: {'있음(' + '·'.join(pos) + ')' if pos else '없음'} · 경제성: {'통과' if 'ECONOMIC' in v.values() else '미달'}. "
         + " · ".join(f"P-{k} {x}" for k, x in v.items()) + ". (스크립트 판정)", "---", "",
         "# 보통주·우선주 괴리 스위칭 — 결과", "", f"자료 {o['dates'][0]} ~ {o['dates'][1]} · 우선주 짝 {o['n_pairs']}개.", "",
         "| 칸 | 사건 | 짝 | 평균 상대 수익 [블록 95%] | 중앙 | 승률 | 귀무 평균·99백분위 | TRAIN | VALID | TEST | 판정 |", "|---|---:|---:|---|---:|---:|---|---:|---:|---:|---|"]
    for k, r in o["res"].items():
        if r is None:
            continue
        L.append(f"| P-{k} | {r['n']} | {r['pairs']} | {bp(r['mean'])} [{bp(r['ci'][0])}, {bp(r['ci'][1])}] | {bp(r['median'])} | {r['win']:.0%} | {bp(r['null_mean'])} · {bp(r['null_99'])} | "
                 + " | ".join(f"{bp(r['by_win'][w]['mean'])}({r['by_win'][w]['n']})" for w in WINDOWS) + f" | **{r['verdict']}** |")
    L += ["", "P-cheap = 우선주가 평소보다 싸졌을 때 우선주로(결과 = 우선주 − 보통주), P-rich = 비싸졌을 때 보통주로(결과 = 보통주 − 우선주). 갈아타기 비용 33.5bp 는 빼지 않은 값.", "",
          "## 기록", ""]
    for zt, rr in o["rec"].items():
        L.append(f"- {zt}: " + " · ".join(f"P-{sd} {'' if r is None else str(r['n']) + '건 ' + bp(r['mean']) + ' (' + ' / '.join(bp(r['by_win'][w]) for w in WINDOWS) + ')'}" for sd, r in rr.items()))
    for k, r in o["res"].items():
        if r:
            L.append(f"- P-{k} 사건 많은 짝: " + " · ".join(f"{o['names'].get(p, p)} {int(n)}건 {bp(m)}" for p, n, m in r["top_pairs"]))
    return "\n".join(L) + "\n"


def selftest():
    ok = True

    def check(name, cond):
        nonlocal ok
        ok &= bool(cond)
        print(("PASS " if cond else "FAIL ") + name)

    check("짝 찾기: 005935 → 005930, 00104K → 001040", pairs(["005930", "005935", "001040", "00104K", "123455"]) == [("005935", "005930"), ("00104K", "001040")])
    z = pd.Series([0, -1, -2.5, -2.6, -1, -2.1])
    check("처음 넘는 날만(2, 5)", np.flatnonzero(crossings(z, "cheap")).tolist() == [2, 5])
    check("에피소드 40일", dedup_idx([1, 10, 45, 50, 100]) == [1, 45, 100])
    check("배당 계절 제외", not season_ok(pd.Timestamp("2020-12-15")) and not season_ok(pd.Timestamp("2021-01-05")) and season_ok(pd.Timestamp("2021-01-11")))
    print("ALL PASS" if ok else "FAILED")
    return 0 if ok else 1


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--selftest", action="store_true")
    sys.exit(selftest() if ap.parse_args().selftest else run())
