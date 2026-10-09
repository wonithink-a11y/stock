#!/usr/bin/env python3
"""쿨라마기 돌파 — 크립토 새 표본. 사전등록 findings/qullamaggie-breakout-crypto-preregistration-2026-10.md 그대로.

국내판 qullamaggie_breakout 의 setup_ok·simulate·month_series·block_ci 를 그대로 쓴다(바꾼 것: 상위 10%·유동성 없음·비용 20bp).

    python research/strategy-lab/qullamaggie_breakout_crypto.py --selftest
    python research/strategy-lab/qullamaggie_breakout_crypto.py
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

OUT = HERE / "findings" / "qullamaggie-breakout-crypto-results-2026-10"
COST, TOP, MIN_N, SEED = 0.002, 0.10, 8, 20261010
WIN = {"TRAIN": (2018, 2021), "TEST": (2022, 2026)}


def load():
    fr = {}
    for f in sorted((HERE / "data" / "crypto" / "daily-binance").glob("*.parquet")):
        fr[f.stem.replace("USDT", "")] = pd.read_parquet(f)
    for c in ("BTC", "ETH"):
        fr[c] = pd.read_parquet(HERE / "data" / "leveraged-etf" / f"{c}-USD.parquet")
    dates = pd.DatetimeIndex(sorted(set().union(*[pd.to_datetime(d["date"]).dt.tz_localize(None).dt.normalize() for d in fr.values()])))
    tick = sorted(fr)
    M = {k: np.full((len(dates), len(tick)), np.nan) for k in ("open", "high", "low", "close")}
    for j, t in enumerate(tick):
        d = fr[t].copy()
        d["date"] = pd.to_datetime(d["date"]).dt.tz_localize(None).dt.normalize()
        d = d.drop_duplicates("date").set_index("date")
        ii = dates.get_indexer(d.index)
        for k in M:
            M[k][ii, j] = d[k].astype(float).to_numpy()
    return dates, tick, M


def signals(dates, M):
    O, H, L, C = (np.where(M[k] > 0, M[k], np.nan) for k in ("open", "high", "low", "close"))
    D, N = C.shape
    leader = np.zeros((D, N), bool)
    cnt = (~np.isnan(C)).sum(1)
    for k in (21, 63, 126):
        r = C / qb.s.sh(C, -k) - 1
        q = np.nanquantile(np.where(cnt[:, None] >= MIN_N, r, np.nan), 1 - TOP, axis=1, keepdims=True)
        leader |= (r >= q) & (cnt[:, None] >= MIN_N)
    S10, S20 = qb.roll(C, 10, "mean"), qb.roll(C, 20, "mean")
    adr = qb.roll(H / L - 1, 20, "mean")
    B = qb.roll(H, 10, "max")
    cond = np.zeros((D, N), bool)
    cond[1:] = (leader & (C >= S20) & (S20 >= qb.s.sh(S20, -5)))[:-1]
    Bt = np.vstack([np.full((1, N), np.nan), B[:-1]])
    adr_t = np.vstack([np.full((1, N), np.nan), adr[:-1]])
    brk = cond & (H > Bt)
    brk[:130] = False
    lead_t = np.zeros((D, N), bool)
    lead_t[1:] = leader[:-1]
    lead_t[:130] = False
    return dict(O=O, H=H, L=L, C=C, S10=S10, S20=S20, Bt=Bt, adr_t=adr_t, brk=brk, lead_t=lead_t)


def run():
    dates, tick, M = load()
    G = signals(dates, M)
    O, H, L, C = G["O"], G["H"], G["L"], G["C"]
    busy, trades = np.full(C.shape[1], -1), []
    for t, j in zip(*np.nonzero(G["brk"])):
        if t <= busy[j] or not qb.setup_ok(H, L, C, t, j):
            continue
        entry, stop = max(O[t, j], G["Bt"][t, j]), L[t, j]
        if np.isnan(entry) or np.isnan(G["adr_t"][t, j]) or (entry - stop) / entry > G["adr_t"][t, j]:
            continue
        r = qb.simulate(O, H, L, C, G["S10"], G["S20"], t, j, entry, stop)
        if r is None:
            continue
        busy[j] = t + r[1]
        trades.append(dict(date=str(dates[t].date()), ticker=tick[j], ret=r[0], hold=r[1], risk=(entry - stop) / entry))
    T = pd.DataFrame(trades)
    y = pd.to_datetime(T["date"]).dt.year
    T["win"] = np.select([(y >= a) & (y <= b) for a, b in WIN.values()], list(WIN), "")
    T = T[T["win"] != ""]
    rng = np.random.default_rng(SEED)
    nul, yr = [], dates.year.to_numpy()
    for w, (a, b) in WIN.items():
        cand = np.argwhere(G["lead_t"] & ((yr >= a) & (yr <= b))[:, None])
        nt = int((T["win"] == w).sum())
        if nt == 0 or len(cand) == 0:
            continue
        for t, j in cand[rng.choice(len(cand), min(len(cand), nt * 5), replace=False)]:
            e, st = O[t, j], L[t, j]
            if np.isnan(e) or np.isnan(st) or np.isnan(G["adr_t"][t, j]) or (e - st) / e > G["adr_t"][t, j]:
                continue
            r = qb.simulate(O, H, L, C, G["S10"], G["S20"], t, j, e, st)
            if r is not None:
                nul.append(dict(date=str(dates[t].date()), ret=r[0], win=w))
    Nl = pd.DataFrame(nul)
    T["net"], Nl["net"] = T["ret"] - COST, Nl["ret"] - COST
    res, rng2 = {}, np.random.default_rng(SEED + 1)
    for w in WIN:
        d = T[T["win"] == w]
        if d.empty:
            continue
        ms = qb.month_series(d)
        lo, hi = qb.block_ci(ms.to_numpy(), rng2)
        nd = Nl[Nl["win"] == w]
        res[w] = dict(n=len(d), months=len(ms), gross=float(ms.mean() + COST), net=float(ms.mean()), lo=lo, hi=hi,
                      null=float(qb.month_series(nd).mean()) if len(nd) else float("nan"), null_n=len(nd),
                      winrate=float((d["net"] > 0).mean()), avg_win=float(d.loc[d["net"] > 0, "net"].mean()), avg_loss=float(d.loc[d["net"] <= 0, "net"].mean()),
                      hold_med=float(d["hold"].median()))
    tr, te = res.get("TRAIN"), res.get("TEST")
    if not tr or tr["n"] < 30:
        verdict = "판정 불가"
    elif tr["net"] > 0 and tr["lo"] > 0 and tr["net"] > tr["null"]:
        verdict = "ECONOMIC" if te and te["net"] > 0 and te["net"] > te["null"] else "INFORMATION"
    else:
        verdict = "REJECT"
    pc = lambda x: "" if x is None or pd.isna(x) else f"{x * 100:+.2f}%"
    sig = "있음" if verdict in ("INFORMATION", "ECONOMIC") else "없음"
    L_ = ["---", "track: crypto", "factor: qullamaggie-breakout-crypto", "date: 2026-10-10", f"verdict: {verdict}",
          "criteria_version: research-only (qullamaggie-breakout-crypto-preregistration-2026-10)", "reason: >-",
          f"  신호: {sig} · 경제성: {'통과' if verdict == 'ECONOMIC' else '미달'}. 거래 {len(T)}건, TRAIN net {pc(tr['net'] if tr else None)}(N1 {pc(tr['null'] if tr else None)}) · "
          f"TEST net {pc(te['net'] if te else None)}(N1 {pc(te['null'] if te else None)}). 비용 20bp.", "---", "",
          "# 쿨라마기 돌파 — 크립토 새 표본 결과", "",
          "| 구간 | 거래 | 월 | gross | 비용 후 net | net 90% | 손익분기 | N1 net | 승률 | 평균 이익 | 평균 손실 | 보유 중앙 |", "|---|---:|---:|---:|---:|---|---:|---:|---:|---:|---:|---:|"]
    for w, r in res.items():
        L_.append(f"| {w} | {r['n']} | {r['months']} | {pc(r['gross'])} | {pc(r['net'])} | [{pc(r['lo'])}, {pc(r['hi'])}] | {r['gross'] * 1e4:+.0f}bp | {pc(r['null'])} ({r['null_n']}) | "
                  f"{r['winrate']:.0%} | {pc(r['avg_win'])} | {pc(r['avg_loss'])} | {r['hold_med']:.0f}일 |")
    by = T.groupby(pd.to_datetime(T["date"]).dt.year)["net"].agg(["size", "mean"])
    L_ += ["", f"판정 **{verdict}** (사전등록 §4).", "", "| 해 | 거래 | net 평균 |", "|---|---:|---:|"] + [f"| {y_} | {r['size']} | {pc(r['mean'])} |" for y_, r in by.iterrows()]
    L_ += ["", "종목별 거래 수: " + " · ".join(f"{k} {v}" for k, v in T["ticker"].value_counts().items()), ""]
    OUT.with_suffix(".md").write_text("\n".join(L_), encoding="utf-8")
    OUT.with_suffix(".json").write_text(json.dumps(dict(verdict=verdict, windows=res), ensure_ascii=False, indent=1, default=float), encoding="utf-8")
    print("\n".join(L_))
    return 0


def selftest():
    dates = pd.date_range("2020-01-01", periods=300)
    M = {k: np.full((300, 10), 100.0) for k in ("open", "high", "low", "close")}
    M["close"][:, 0] = np.linspace(100, 400, 300)                  # 0번이 가장 많이 오름
    G = signals(dates, M)
    ok = G["lead_t"][200, 0] and not G["lead_t"][200, 5] and not G["brk"][:130].any()
    print("selftest", "ok" if ok else "FAIL")
    return 0 if ok else 1


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--selftest", action="store_true")
    sys.exit(selftest() if ap.parse_args().selftest else run())
