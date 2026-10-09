#!/usr/bin/env python3
"""EP(실적 갭 + 20일선 추적) — 사전등록 findings/episodic-pivot-preregistration-2026-10.md 그대로.

    python research/strategy-lab/episodic_pivot.py --selftest
    python research/strategy-lab/episodic_pivot.py          # → findings/episodic-pivot-results-2026-10.{md,json}
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
import qullamaggie_breakout as qb  # noqa: E402

s = qb.s
OUT = HERE / "findings" / "episodic-pivot-results-2026-10"
QD = HERE / "data" / "quarterly-multi"
COST, SEED = 0.00335, 20261010
WIN = {"TRAIN": (2016, 2020), "VALID": (2021, 2022), "TEST": (2023, 2025)}


def surprise(r):
    """당기 순이익 > 0 ∧ YoY ≥ +50%(전년 ≤ 0 이면 흑자 전환) ∧ 매출 YoY ≥ +20%."""
    ni, rv = r.get("net_income") or {}, r.get("revenue") or {}
    c, p, rc, rp = ni.get("cur"), ni.get("prev"), rv.get("cur"), rv.get("prev")
    if None in (c, p, rc, rp) or c <= 0 or rp <= 0:
        return False
    return (p <= 0 or c / p - 1 >= 0.5) and rc / rp - 1 >= 0.2


def reports():
    best = {}
    for code in ("11013", "11012", "11014", "11011"):
        for l in open(QD / f"quarterly-multi-panel-{code}.jsonl", encoding="utf-8"):
            r = json.loads(l)
            k = (r["ticker"], r["year"], r["reprt"])
            if k not in best or (best[k]["fsDiv"] != "CFS" and r["fsDiv"] == "CFS"):
                best[k] = r
    return list(best.values())


def run():
    dates, tick, raw = s.load_raw()
    P = s.derive(raw, dates)
    O, H, L, C, V = P["On"], P["Hn"], P["Ln"], P["Cn"], P["Vn"]
    D, N = C.shape
    ti = {t: j for j, t in enumerate(tick)}
    tv = pd.DataFrame(C * V).rolling(20, min_periods=15).mean().to_numpy()
    vavg = pd.DataFrame(V).rolling(20, min_periods=15).mean().to_numpy()
    S10, S20 = qb.roll(C, 10, "mean"), qb.roll(C, 20, "mean")
    r63 = C / s.sh(C, -63) - 1
    ev = []
    for r in reports():
        j = ti.get(r["ticker"])
        if j is None:
            continue
        tF = int(np.searchsorted(dates, pd.Timestamp(r["availableFrom"])))
        for t in range(tF, min(tF + 3, D)):
            if t < 64 or np.isnan(O[t, j]) or np.isnan(C[t - 1, j]):
                continue
            if O[t, j] / C[t - 1, j] - 1 >= 0.10 and V[t, j] >= 3 * vavg[t - 1, j] and tv[t - 1, j] >= 2e9 and C[t - 1, j] >= 1000:
                ev.append(dict(t=t, j=j, sur=surprise(r), low=bool(r63[t - 1, j] <= 0.30), reprt=r["reprt"]))
                break                                                # 창 안 첫 갭일만
    E = pd.DataFrame(ev).sort_values(["t", "j"])
    E["year"] = dates[E["t"].to_numpy()].year
    E = E[(E["year"] >= 2016) & (E["year"] <= 2025)]

    def trade(t, j, entry, stop, trail):
        return qb.simulate(O, H, L, C, S10, S20, t, j, entry, stop, trail=trail, partial=False)

    def book(rows, mode="close", trail="s20"):
        busy, out = np.full(N, -1), []
        for x in rows.itertuples():
            t, j = int(x.t), int(x.j)
            if t <= busy[j]:
                continue
            if mode == "close":
                entry, stop, t0 = C[t, j], L[t, j], t
            else:                                                    # 다음 날 시가
                if t + 1 >= D or np.isnan(O[t + 1, j]):
                    continue
                entry, stop, t0 = O[t + 1, j], L[t, j], t
            r = trade(t0, j, entry, stop, trail)
            if r is None:
                continue
            busy[j] = t0 + r[1]
            out.append(dict(date=str(dates[t].date()), ticker=tick[j], ret=r[0], hold=r[1], year=int(x.year)))
        df = pd.DataFrame(out)
        if len(df):
            df["net"] = df["ret"] - COST
            df["win"] = np.select([(df["year"] >= a) & (df["year"] <= b) for a, b in WIN.values()], list(WIN), "")
        return df

    main = book(E[E["sur"] & E["low"]])
    null = book(E[~E["sur"] & E["low"]])
    var = {"10일선": book(E[E["sur"] & E["low"]], trail="s10"), "다음날 시가": book(E[E["sur"] & E["low"]], mode="open"),
           "덜 오름 조건 없이": book(E[E["sur"]])}
    rng = np.random.default_rng(SEED + 1)
    res = {}
    for w in WIN:
        d, nd = main[main["win"] == w], null[null["win"] == w]
        if d.empty:
            continue
        ms = qb.month_series(d)
        lo, hi = qb.block_ci(ms.to_numpy(), rng)
        gl, gh = qb.block_ci((ms + COST).to_numpy(), rng)
        res[w] = dict(n=len(d), months=len(ms), gross=float(ms.mean() + COST), gross_lo=gl, gross_hi=gh, net=float(ms.mean()), lo=lo, hi=hi,
                      null=float(qb.month_series(nd).mean()) if len(nd) else float("nan"), null_n=len(nd),
                      winrate=float((d["net"] > 0).mean()), avg_win=float(d.loc[d["net"] > 0, "net"].mean()), avg_loss=float(d.loc[d["net"] <= 0, "net"].mean()),
                      hold_med=float(d["hold"].median()))
    verdict = qb.decide(res.get("TRAIN"), res.get("VALID"), res.get("TEST"), res.get("TRAIN", {}).get("n", 0))
    pc = lambda x: "" if x is None or pd.isna(x) else f"{x * 100:+.2f}%"
    tr = res.get("TRAIN", {})
    L_ = ["---", "track: kr", "factor: episodic-pivot", "date: 2026-10-10", f"verdict: {verdict}",
          "criteria_version: research-only (episodic-pivot-preregistration-2026-10)", "reason: >-",
          f"  신호: {'있음' if verdict in ('INFORMATION', 'ECONOMIC') else '없음'} · 경제성: {'통과' if verdict == 'ECONOMIC' else '미달'}. 거래 {len(main)}건, "
          f"TRAIN net {pc(tr.get('net'))}(실적 없는 갭 N1 {pc(tr.get('null'))}) · VALID {pc(res.get('VALID', {}).get('net'))} · TEST {pc(res.get('TEST', {}).get('net'))}. 비용 33.5bp.", "---", "",
          "# EP(실적 갭 + 20일선 추적) — 결과", "", f"갭일 사건 {len(E)}건(실적 서프라이즈 {int(E['sur'].sum())} · 덜 오름 {int(E['low'].sum())}).", "",
          "| 구간 | 거래 | 월 | gross 평균(90%) | 비용 후 net | net 90% | 손익분기 | N1 실적 없는 갭 net | 승률 | 평균 이익 | 평균 손실 | 보유 중앙 |",
          "|---|---:|---:|---|---:|---|---:|---:|---:|---:|---:|---:|"]
    for w, r in res.items():
        L_.append(f"| {w} | {r['n']} | {r['months']} | {pc(r['gross'])} [{pc(r['gross_lo'])}, {pc(r['gross_hi'])}] | {pc(r['net'])} | [{pc(r['lo'])}, {pc(r['hi'])}] | "
                  f"{r['gross'] * 1e4:+.0f}bp | {pc(r['null'])} ({r['null_n']}) | {r['winrate']:.0%} | {pc(r['avg_win'])} | {pc(r['avg_loss'])} | {r['hold_med']:.0f}일 |")
    L_ += ["", f"판정 **{verdict}** (사전등록 §5).", "", "## 기록 (판정 불사용)", "", "변형 거래 평균 net (TRAIN / VALID / TEST): " +
           " · ".join(f"{k} " + " / ".join(pc(v.loc[v['win'] == w, 'net'].mean()) if len(v) else "" for w in WIN) + f" ({len(v)}건)" for k, v in var.items()), "",
           "| 해 | 거래 | net 평균 | 승률 | N1 거래 | N1 net |", "|---|---:|---:|---:|---:|---:|"]
    for y in range(2016, 2026):
        d, nd = main[main["year"] == y], null[null["year"] == y]
        L_.append(f"| {y} | {len(d)} | {pc(d['net'].mean()) if len(d) else ''} | {(d['net'] > 0).mean():.0%} | {len(nd)} | {pc(nd['net'].mean()) if len(nd) else ''} |" if len(d) else f"| {y} | 0 | | | {len(nd)} | |")
    OUT.with_suffix(".md").write_text("\n".join(L_) + "\n", encoding="utf-8")
    OUT.with_suffix(".json").write_text(json.dumps(dict(verdict=verdict, windows=res), ensure_ascii=False, indent=1, default=float), encoding="utf-8")
    print("\n".join(L_))
    return 0


def selftest():
    mk = lambda c, p, rc, rp: {"net_income": {"cur": c, "prev": p}, "revenue": {"cur": rc, "prev": rp}}
    ok = surprise(mk(150, 100, 121, 100)) and surprise(mk(10, -5, 130, 100)) and not surprise(mk(140, 100, 130, 100)) \
        and not surprise(mk(150, 100, 110, 100)) and not surprise(mk(-1, -5, 130, 100)) and not surprise(mk(None, 1, 1, 1))
    print("selftest", "ok" if ok else "FAIL")
    return 0 if ok else 1


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--selftest", action="store_true")
    sys.exit(selftest() if ap.parse_args().selftest else run())
