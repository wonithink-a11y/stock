#!/usr/bin/env python3
"""실적 발표 프리미엄(정기보고서 접수일) — 사전등록 findings/earnings-announcement-premium-preregistration-2026-10.md 그대로.

    python research/strategy-lab/earnings_announcement_premium.py --selftest
    python research/strategy-lab/earnings_announcement_premium.py      # → findings/earnings-announcement-premium-results-2026-10.{md,json}
"""
from __future__ import annotations

import argparse
import glob
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import krx_daily_panel as kp

OUT = HERE / "findings" / "earnings-announcement-premium-results-2026-10"
PANELS = sorted(glob.glob(str(HERE / "data" / "quarterly-multi" / "quarterly-multi-panel-*.jsonl"))) + [str(HERE / "data" / "quarterly-multi" / "recent-2026" / "panel-recent.jsonl")]
END_MONTH = {"11013": "03", "11012": "06", "11014": "09", "11011": "12"}
PRE, POST, EXCL, COST = 5, 1, 10, 0.00335
SEED, REPS, BOOT, BLOCK = 20261009, 500, 2000, 6
WINDOWS = {"TRAIN": (2016, 2019), "VALID": (2020, 2022), "TEST": (2023, 2026)}


def win_of(y):
    return next((w for w, (a, b) in WINDOWS.items() if a <= y <= b), None)


def load_filings():
    seen, rows = set(), []
    for p in PANELS:
        if not Path(p).exists():
            continue
        for line in open(p, encoding="utf-8"):
            r = json.loads(line)
            t, d, dt, rp = r.get("ticker"), r.get("availableFrom"), r.get("dt") or "", r.get("reprt")
            try:
                end = dt.split("~")[1].strip().replace(".", "")
            except Exception:
                continue
            if not t or not d or end[4:6] != END_MONTH.get(rp):
                continue
            if (t, d) in seen:
                continue
            seen.add((t, d))
            rows.append((t, pd.Timestamp(d), rp))
    return rows


def window_excess(cs, ew_cs, e, j):
    a, b = e - PRE, e + POST
    return np.exp(cs[b + 1, j] - cs[a, j]) - np.exp(ew_cs[b + 1] - ew_cs[a])


def run():
    dates, tick, M, names, market = kp.build()
    R = kp.clean_returns(M["R"])
    T = len(dates)
    ti = {t: j for j, t in enumerate(tick)}
    cs = np.vstack([np.zeros((1, R.shape[1])), np.cumsum(np.log1p(np.nan_to_num(R, nan=0.0)), axis=0)])
    ew_cs = np.r_[0.0, np.cumsum(np.log1p(np.nan_to_num(np.nanmean(R, axis=1))))]
    traded = ~np.isnan(R)
    mcap = M["MCAP"].astype(float)
    ev = []
    for t, d, rp in load_filings():
        j = ti.get(t)
        if j is None:
            continue
        e = int(np.searchsorted(dates, d))
        if e - PRE - 1 < 0 or e + 10 >= T or not traded[e, j]:
            continue
        cap = mcap[e - PRE - 1, j]
        med = np.nanmedian(mcap[e - PRE - 1][traded[e - PRE - 1]])
        ev.append(dict(t=t, j=j, e=e, date=dates[e], rp=rp, win=win_of(dates[e].year), ex=float(window_excess(cs, ew_cs, e, j)),
                       pre10=float(np.exp(cs[e, j] - cs[e - 10, j]) - np.exp(ew_cs[e] - ew_cs[e - 10])) if e >= 10 else np.nan,
                       d01=float(np.exp(cs[e + 2, j] - cs[e, j]) - np.exp(ew_cs[e + 2] - ew_cs[e])),
                       post=float(np.exp(cs[e + 11, j] - cs[e + 2, j]) - np.exp(ew_cs[e + 11] - ew_cs[e + 2])),
                       big=bool(np.isfinite(cap) and cap > med)))
    df = pd.DataFrame(ev)
    df = df[df["win"].notna()]
    rng = np.random.default_rng(SEED)
    null = np.zeros(REPS)
    n_used = 0
    for j, g in df.groupby("j"):
        es = g["e"].to_numpy()
        cand = np.flatnonzero(traded[:, j])
        cand = cand[(cand - PRE >= 0) & (cand + POST + 1 < T)]
        far = np.ones(len(cand), bool)
        for e in es:
            far &= np.abs(cand - e) > EXCL
        cand = cand[far]
        if len(cand) == 0:
            continue
        us = cand[rng.integers(0, len(cand), (REPS, len(es)))]
        null += window_excess(cs, ew_cs, us, j).sum(1)
        n_used += len(es)
    null /= max(n_used, 1)
    df["mi"] = (df["date"].dt.year - 2016) * 12 + df["date"].dt.month - 1
    mm = df.groupby("mi")["ex"].mean().sort_index()
    nb = int(np.ceil(len(mm) / BLOCK))
    st = rng.integers(0, len(mm) - BLOCK + 1, (BOOT, nb))
    idx = np.minimum((st[:, :, None] + np.arange(BLOCK)).reshape(BOOT, -1)[:, : len(mm)], len(mm) - 1)
    boot = mm.to_numpy()[idx].mean(1)
    ci = [float(np.percentile(boot, 2.5)), float(np.percentile(boot, 97.5))]
    m = float(df["ex"].mean())
    bw = {w: dict(n=int((df["win"] == w).sum()), ex=float(df.loc[df["win"] == w, "ex"].mean())) for w in WINDOWS}
    p99 = float(np.percentile(null, 99))
    info = m > p99 and all(bw[w]["ex"] > 0 for w in WINDOWS) and ci[0] > 0
    econ = info and all(bw[w]["ex"] > COST for w in ("VALID", "TEST"))
    verdict = "ECONOMIC" if econ else ("INFORMATION" if info else "REJECT")
    rec = dict(by_type={"사업보고서": float(df.loc[df["rp"] == "11011", "ex"].mean()), "분기·반기": float(df.loc[df["rp"] != "11011", "ex"].mean())},
               by_size={"시총 상위 절반": float(df.loc[df["big"], "ex"].mean()), "하위 절반": float(df.loc[~df["big"], "ex"].mean())},
               split={"e−10~e−1": float(df["pre10"].mean()), "e~e+1": float(df["d01"].mean()), "e+2~e+10": float(df["post"].mean())},
               median=float(df["ex"].median()), win=float((df["ex"] > 0).mean()))
    out = dict(verdict=verdict, n=len(df), mean=m, null=[float(null.mean()), p99], ci=ci, by_win=bw, rec=rec)
    OUT.with_suffix(".json").write_text(json.dumps(out, ensure_ascii=False, indent=1, default=float), encoding="utf-8")
    pc = lambda x: f"{x * 100:+.2f}%"
    L = ["---", "track: kr", "factor: earnings-announcement-premium", "date: 2026-10-09", f"verdict: {verdict}",
         "criteria_version: research-only (earnings-announcement-premium-preregistration-2026-10)",
         'conditions: ["정기보고서 접수일 e, 창 e−5~e+1 초과(KRX 전종목 등가중 대비)", "같은 종목 다른 날 500회 99백분위", "TRAIN 2016~19 / VALID 2020~22 / TEST 2023~26"]',
         "reason: >-", f"  신호: {'있음' if verdict != 'REJECT' else '없음'} · 경제성: {'통과' if verdict == 'ECONOMIC' else '미달'}. 평균 {pc(m)}, 귀무 99백분위 {pc(p99)}. (스크립트 판정)", "---", "",
         "# 실적 발표 프리미엄(정기보고서 접수일) — 결과", "",
         f"| 사건 | 7일 창 초과 평균 [블록 95%] | 중앙 | 양 비율 | 귀무 평균 · 99백분위 | TRAIN | VALID | TEST | 판정 |", "|---:|---|---:|---:|---|---:|---:|---:|---|",
         f"| {len(df):,} | {pc(m)} [{pc(ci[0])}, {pc(ci[1])}] | {pc(rec['median'])} | {rec['win']:.0%} | {pc(null.mean())} · {pc(p99)} | " +
         " | ".join(f"{pc(bw[w]['ex'])}({bw[w]['n']:,})" for w in WINDOWS) + f" | **{verdict}** |", "",
         "## 기록", "", "- 보고서 종류별: " + " · ".join(f"{k} {pc(v)}" for k, v in rec["by_type"].items()),
         "- 시가총액별: " + " · ".join(f"{k} {pc(v)}" for k, v in rec["by_size"].items()),
         "- 창 나눔: " + " · ".join(f"{k} {pc(v)}" for k, v in rec["split"].items())]
    OUT.with_suffix(".md").write_text("\n".join(L) + "\n", encoding="utf-8")
    print(verdict, len(df), pc(m), {w: pc(bw[w]["ex"]) for w in WINDOWS}, "null99", pc(p99), rec)
    return 0


def selftest():
    ok = True

    def check(name, cond):
        nonlocal ok
        ok &= bool(cond)
        print(("PASS " if cond else "FAIL ") + name)

    R = np.zeros((20, 1))
    R[10, 0] = 0.05
    cs = np.vstack([np.zeros((1, 1)), np.cumsum(np.log1p(R), axis=0)])
    ew_cs = np.zeros(21)
    check("창 e−5~e+1 에 e=9 → 10일째 +5% 포함", abs(window_excess(cs, ew_cs, 9, 0) - 0.05) < 1e-12)
    check("창 밖(e=16, 창 11~17) → 0", abs(window_excess(cs, ew_cs, 16, 0)) < 1e-12)
    print("ALL PASS" if ok else "FAILED")
    return 0 if ok else 1


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--selftest", action="store_true")
    sys.exit(selftest() if ap.parse_args().selftest else run())
