#!/usr/bin/env python3
"""장 초반 무리형 vs 단독형 강세 — 사전등록 findings/early-session-herd-preregistration-2026-10.md (커밋 225edefc) 그대로.

    python research/strategy-lab/early_session_herd.py --selftest
    python research/strategy-lab/early_session_herd.py           # → findings/early-session-herd-results-2026-10.{md,json}

사건 표는 .cache/early_herd_events.parquet 에 날짜별로 쌓는다(재실행 시 이어서).
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
import why_surge as ws  # noqa: E402

OUT = HERE / "findings" / "early-session-herd-results-2026-10"
EV = HERE / ".cache" / "early_herd_events.parquet"
COST = 33.5
MIN_CAP, R_MIN, R_LIMIT, PEER_MOVE, PEER_SHARE, MIN_PEERS, GAP_SHARE = 2e11, 0.05, 0.295, 0.02, 0.3, 5, 0.7
SPLIT = "20260301"


def daily_table():
    fs = sorted(glob.glob(str(HERE / "data" / "krx-daily-ext" / "2025-0[789].parquet"))) + \
        sorted(glob.glob(str(HERE / "data" / "krx-daily-ext" / "2025-1*.parquet"))) + sorted(glob.glob(str(HERE / "data" / "krx-daily-ext" / "2026-*.parquet")))
    e = pd.concat([pd.read_parquet(f, columns=["BAS_DD", "ISU_CD", "TDD_CLSPRC", "FLUC_RT", "MKTCAP"]) for f in fs], ignore_index=True)
    e["r"] = pd.to_numeric(e.FLUC_RT, errors="coerce") / 100
    e["prev"] = e.TDD_CLSPRC / (1 + e.r)
    e = e.sort_values(["ISU_CD", "BAS_DD"])
    e["cap0"] = e.groupby("ISU_CD").MKTCAP.shift(1)
    # t+1..t+5 누적(종가 기준)
    lr = np.log1p(e.r.clip(-0.31, 0.31))
    e["fwd5"] = np.expm1(e.groupby("ISU_CD")["r"].transform(lambda s: np.log1p(s.clip(-0.31, 0.31)).shift(-1).rolling(5).sum().shift(-4)))
    del lr
    return e.set_index(["BAS_DD", "ISU_CD"])


def classify(r0910, gap, shares_n):
    share, n = shares_n
    if gap > 0 and gap >= GAP_SHARE * r0910:
        return "갭형"
    if n < MIN_PEERS:
        return "판정불가"
    return "무리형" if share >= PEER_SHARE else "단독형"


def day_events(date, nxt_open, D, sub, sec):
    m = ws.minutes(date)
    if m is None:
        return []
    m = m[m.ticker.str.endswith("0")]
    first = m.sort_values("hm").groupby("ticker").first()
    last = m.sort_values("hm").groupby("ticker").last()
    at = m[m.hm <= "09:10"].sort_values("hm").groupby("ticker").last()
    try:
        dd = D.xs(date, level=0)
    except KeyError:
        return []
    prev = dd.prev.reindex(at.index)
    r10 = (at.close / prev - 1).dropna()
    peers_of = {}
    rows = []
    cand = r10[(r10 >= R_MIN) & (r10 < R_LIMIT)]
    for t, rv in cand.items():
        cap0 = dd.cap0.get(t, np.nan)
        if not (cap0 >= MIN_CAP):
            continue
        ps = set()
        for g in sub.get(t, ()):
            ps |= {x for x, gs in sub.items() if g in gs}
        if sec.get(t):
            ps |= {x for x, s in sec.items() if s == sec[t]}
        ps.discard(t)
        mv = r10.reindex(list(ps)).dropna()
        share = float((mv >= PEER_MOVE).mean()) if len(mv) else 0.0
        gap = first.open.get(t, np.nan) / prev[t] - 1
        kind = classify(rv, gap, (share, len(mv)))
        p0 = at.close[t]
        rc = last.close.get(t, np.nan) / p0 - 1
        no = nxt_open.get(t, np.nan) / p0 - 1 if nxt_open is not None else np.nan
        f5 = dd.fwd5.get(t, np.nan)
        r5 = (last.close[t] / p0) * (1 + f5) - 1 if np.isfinite(f5) else np.nan
        rows.append(dict(date=date, ticker=t, r0910=rv, gap=gap, share=share, npeers=len(mv), kind=kind, ret_close=rc, ret_next_open=no, ret_5d=r5))
    return rows


def build_events():
    days = sorted(p.name[5:].replace("-", "") for p in ws.MIN.glob("date=*"))
    done = pd.read_parquet(EV) if EV.exists() else pd.DataFrame()
    seen = set(done.date) if len(done) else set()
    D = daily_table()
    sub, sec = ws.peer_map()
    rows = []
    for i, d in enumerate(days):
        if d in seen:
            continue
        nxt = None
        if i + 1 < len(days):
            mn = ws.minutes(days[i + 1])
            if mn is not None:
                nxt = mn.sort_values("hm").groupby("ticker").open.first()
        rows += day_events(d, nxt, D, sub, sec)
        if (i + 1) % 20 == 0:
            df = pd.concat([done, pd.DataFrame(rows)], ignore_index=True)
            df.to_parquet(EV)
            print(f"  {i + 1}/{len(days)} 사건 {len(df)}", flush=True)
    df = pd.concat([done, pd.DataFrame(rows)], ignore_index=True)
    df.to_parquet(EV)
    return df


def stats(x, col):
    if x.empty:
        return dict(n=0)
    day = x.groupby("date")[col].mean()
    mo = day.groupby(day.index.str[:6]).mean()
    n = len(mo)
    t = mo.mean() / (mo.std(ddof=1) / np.sqrt(n)) if n > 1 and mo.std(ddof=1) > 0 else float("nan")
    return dict(n=int(len(x)), days=int(len(day)), months=n, mean_bp=float(mo.mean() * 1e4), t=float(t),
                median_bp=float(x[col].median() * 1e4), win=float((x[col] > 0).mean()))


def run():
    ev = build_events()
    ev = ev.dropna(subset=["ret_close"])
    halves = {"앞(2025-08~2026-02)": ev[ev.date < SPLIT], "뒤(2026-03~10)": ev[ev.date >= SPLIT]}
    out = {"events": int(len(ev)), "kinds": ev.kind.value_counts().to_dict(), "cells": {}}
    for k in ("무리형", "단독형", "갭형", "판정불가"):
        x = ev[ev.kind == k]
        out["cells"][k] = {"all": {c: stats(x, c) for c in ("ret_close", "ret_next_open", "ret_5d")},
                           "halves": {h: stats(v[v.kind == k], "ret_close") for h, v in halves.items()}}
    hd = {h: (stats(v[v.kind == "무리형"], "ret_close").get("mean_bp", np.nan) - stats(v[v.kind == "단독형"], "ret_close").get("mean_bp", np.nan)) for h, v in halves.items()}
    h = out["cells"]["무리형"]
    a = h["all"]["ret_close"]
    info = a.get("mean_bp", -1) > 0 and a.get("t", 0) >= 2 and all(v.get("mean_bp", -1) > 0 for v in h["halves"].values()) and all(d > 0 for d in hd.values())
    econ = info and all(v.get("mean_bp", -1) - COST > 0 for v in h["halves"].values())
    out["verdict"] = "ECONOMIC" if econ else ("INFORMATION" if info else "REJECT")
    out["herd_minus_solo"] = hd
    bins = pd.cut(ev[ev.kind.isin(["무리형", "단독형"])].share, [-0.01, 0.1, 0.3, 0.5, 1.01], labels=["0~10%", "10~30%", "30~50%", "50%↑"])
    out["by_share"] = ev[ev.kind.isin(["무리형", "단독형"])].groupby(bins, observed=True).ret_close.agg(["size", "mean", "median"]).mul([1, 1e4, 1e4]).round(1).to_dict("index")
    json.dump(out, open(OUT.with_suffix(".json"), "w", encoding="utf-8"), ensure_ascii=False, indent=1, default=str)
    OUT.with_suffix(".md").write_text(render(out), encoding="utf-8")
    print(render(out))


def f(x):
    return "—" if x is None or not np.isfinite(x) else f"{x:+.1f}"


def render(o):
    c = o["cells"]
    v = o["verdict"]
    L = ["---", "track: kr", "factor: early-session-herd", "date: 2026-10-13", f"verdict: {v}",
         "criteria_version: research-only (early-session-herd-preregistration-2026-10)",
         'conditions: ["분봉 281거래일, 09:10 전일 대비 +5%↑(시총 2,000억↑)", "무리형 = 동료 +2%↑ 비율 ≥ 30% · 단독형 · 갭형", "09:10 종가 → 당일 종가, 비용 33.5bp", "두 반기 모두 통과"]',
         "reason: >-", f"  신호: {'있음' if v != 'REJECT' else '없음'} · 경제성: {'통과' if v == 'ECONOMIC' else '미달'}. 무리형 09:10→종가 {f(c['무리형']['all']['ret_close'].get('mean_bp'))}bp "
         f"(t {f(c['무리형']['all']['ret_close'].get('t'))}) · 단독형 {f(c['단독형']['all']['ret_close'].get('mean_bp'))}bp · 갭형 {f(c['갭형']['all']['ret_close'].get('mean_bp'))}bp. (스크립트 판정)",
         "---", "", "# 장 초반 무리형 vs 단독형 강세 — 결과", "", f"투자 자문이 아니다. 사건 {o['events']}건: " + " · ".join(f"{k} {n}" for k, n in o["kinds"].items()), "",
         "## 1. 09:10 진입 수익 (월평균들의 평균 bp, 비용 전)", "", "| 유형 | 사건 | → 당일 종가 | t | 중앙값 | 승률 | → 다음 날 시가 | → 5일 뒤 종가 | 앞 반기(종가) | 뒤 반기(종가) |", "|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|"]
    for k, x in c.items():
        a = x["all"]
        hv = list(x["halves"].values())
        L.append(f"| {k} | {a['ret_close'].get('n', 0)} | {f(a['ret_close'].get('mean_bp'))} | {f(a['ret_close'].get('t'))} | {f(a['ret_close'].get('median_bp'))} | "
                 f"{a['ret_close'].get('win', float('nan')):.0%} | {f(a['ret_next_open'].get('mean_bp'))} | {f(a['ret_5d'].get('mean_bp'))} | {f(hv[0].get('mean_bp'))} | {f(hv[1].get('mean_bp'))} |")
    L += ["", f"무리형 − 단독형(종가): " + " · ".join(f"{h} {f(d)}bp" for h, d in o["herd_minus_solo"].items()), f"비용 {COST}bp. 판정: **{v}**", "",
          "## 2. 동료 동반 비율별(무리형+단독형, 09:10→종가)", "", "| 동반 비율 | 사건 | 평균 bp | 중앙값 bp |", "|---|---:|---:|---:|"]
    for k, r in o["by_share"].items():
        L.append(f"| {k} | {int(r['size'])} | {r['mean']:+.1f} | {r['median']:+.1f} |")
    return "\n".join(L) + "\n"


def selftest():
    assert classify(0.10, 0.08, (0.0, 10)) == "갭형"
    assert classify(0.10, 0.02, (0.35, 10)) == "무리형"
    assert classify(0.10, 0.02, (0.25, 10)) == "단독형"
    assert classify(0.10, 0.02, (0.9, 4)) == "판정불가"
    print("selftest 통과")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--selftest", action="store_true")
    selftest() if ap.parse_args().selftest else run()
