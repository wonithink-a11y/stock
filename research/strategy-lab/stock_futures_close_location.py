#!/usr/bin/env python3
"""주식선물 종가 위치 되돌림 — 사전등록 findings/stock-futures-close-location-preregistration-2026-10.md (커밋 8fb87410) 그대로.

    python research/strategy-lab/stock_futures_close_location.py --selftest
    python research/strategy-lab/stock_futures_close_location.py   # → findings/stock-futures-close-location-results-2026-10.{md,json}
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

OUT = HERE / "findings" / "stock-futures-close-location-results-2026-10"
MIN_VAL, Q, MIN_N, COST, STRESS = 1e9, 0.2, 20, 0.0020, 0.0040


def day_spread(u):
    """u: 하루 유니버스 DataFrame(clv, fr=선물 다음 날 수익, sr=현물 다음 날 수익, ticker). 반환 dict 또는 None."""
    if len(u) < MIN_N:
        return None
    u = u.sort_values(["clv", "ticker"])
    k = int(np.floor(len(u) * Q))
    lo, hi = u.iloc[:k], u.iloc[-k:]
    return dict(n=len(u), k=k, fut=lo.fr.mean() - hi.fr.mean(), spot=lo.sr.mean() - hi.sr.mean(),
                long_ex=lo.fr.mean() - u.fr.mean(), short_ex=u.fr.mean() - hi.fr.mean())


def build():
    import combined_rank_model as crm
    f = pd.concat([pd.read_parquet(p) for p in sorted((HERE / "data" / "stock-futures").glob("20*.parquet"))], ignore_index=True)
    f = f.sort_values(["ISU_CD", "BAS_DD"])
    days = sorted(f.BAS_DD.unique())
    nxt = {d: days[i + 1] for i, d in enumerate(days[:-1])}
    f["next_dd"] = f.BAS_DD.map(nxt)
    key = f.set_index(["BAS_DD", "ISU_CD"]).TDD_CLSPRC
    f["fut_next"] = [key.get((n, c), np.nan) for n, c in zip(f.next_dd, f.ISU_CD)]
    dates, tickers, C, O, H, L, V, common, isdel = crm.load_dense()
    di = {d.replace("-", ""): i for i, d in enumerate(dates)}
    ti = {t: j for j, t in enumerate(tickers)}
    rows = []
    for r in f.itertuples():
        i, j = di.get(r.BAS_DD), ti.get(r.ticker)
        if i is None or j is None or i + 1 >= len(dates):
            continue
        h, l, c = H[i, j], L[i, j], C[i, j]
        if not (h > l) or not np.isfinite(c):
            continue
        rows.append((r.BAS_DD, r.ticker, r.market, r.ACC_TRDVAL, (c - l) / (h - l), r.fut_next / r.TDD_CLSPRC - 1 if r.TDD_CLSPRC > 0 else np.nan,
                     C[i + 1, j] / c - 1, np.isfinite(r.fut_next)))
    return pd.DataFrame(rows, columns=["d", "ticker", "market", "val", "clv", "fr", "sr", "has_next"])


def mstats(s):
    m = s.groupby(s.index.str[:6]).mean()
    t = m.mean() / (m.std(ddof=1) / np.sqrt(len(m))) if len(m) > 1 else float("nan")
    return dict(mean_bp=float(s.mean() * 1e4), t=float(t), months=int(len(m)), pos=float((m > 0).mean()))


def run():
    x = build()
    total = len(x[x.val >= MIN_VAL])
    rolled = int((~x[x.val >= MIN_VAL].has_next).sum())
    u = x[(x.val >= MIN_VAL) & x.has_next & x.fr.notna() & x.sr.notna()]
    res = {d: r for d, g in u.groupby("d") if (r := day_spread(g))}
    D = pd.DataFrame(res).T
    D.index.name = "d"
    fut, spot = D.fut.astype(float), D.spot.astype(float)
    per = lambda s, a, b: s[(s.index >= a) & (s.index <= b)]
    A, B = per(fut, "20230101", "20241231"), per(fut, "20250101", "20991231")
    out = {"days": int(len(D)), "universe_mean": float(D.n.mean()), "rolled_share": rolled / max(total, 1),
           "fut": mstats(fut), "spot": mstats(spot), "A": mstats(A), "B": mstats(B),
           "net20": mstats(fut - COST), "net40": mstats(fut - STRESS),
           "long_ex": mstats(D.long_ex.astype(float)), "short_ex": mstats(D.short_ex.astype(float)),
           "years": {y: float(g.mean() * 1e4) for y, g in fut.groupby(fut.index.str[:4])}}
    for mkt in ("KOSPI", "KOSDAQ"):
        r2 = {d: r for d, g in u[u.market == mkt].groupby("d") if (r := day_spread(g))}
        if r2:
            out[f"mkt_{mkt}"] = mstats(pd.DataFrame(r2).T.fut.astype(float))
    info = out["fut"]["mean_bp"] > 0 and out["fut"]["t"] >= 2 and out["A"]["mean_bp"] > 0 and out["B"]["mean_bp"] > 0
    econ = info and out["A"]["mean_bp"] - COST * 1e4 > 0 and out["B"]["mean_bp"] - COST * 1e4 > 0
    out["verdict"] = "ECONOMIC" if econ else ("INFORMATION" if info else "REJECT")
    json.dump(out, open(OUT.with_suffix(".json"), "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    OUT.with_suffix(".md").write_text(render(out), encoding="utf-8")
    print(render(out))


def render(o):
    f = lambda s: f"{s['mean_bp']:+.1f}bp (t {s['t']:+.2f}, 양수 월 {s['pos']:.0%}, {s['months']}개월)"
    v = o["verdict"]
    L = ["---", "track: kr", "factor: stock-futures-close-location", "date: 2026-10-13", f"verdict: {v}",
         "criteria_version: research-only (stock-futures-close-location-preregistration-2026-10)",
         'conditions: ["KRX 주식선물 근월, 거래대금 ≥ 10억", "기초자산 CLV 하위 20% 매수 · 상위 20% 매도, 선물 종가 → 다음 날 종가", "2023-01 ~ 2026-10", "비용 하루 20bp(다리당 왕복 10bp 가정)"]',
         "reason: >-", f"  신호: {'있음' if v != 'REJECT' else '없음'} · 경제성: {'통과' if v == 'ECONOMIC' else '미달'}. 선물 매수−매도 {o['fut']['mean_bp']:+.1f}bp/일(t {o['fut']['t']:+.2f}) · "
         f"2023~24 {o['A']['mean_bp']:+.1f} · 2025~ {o['B']['mean_bp']:+.1f} · 비용 20bp 후 {o['net20']['mean_bp']:+.1f}. 비용은 가정(호가 자료 없음). (스크립트 판정)", "---", "",
         "# 주식선물로 종가 위치 되돌림 — 결과", "", "투자 자문이 아니다. `stock_futures_close_location.py` 출력.", "",
         f"거래일 {o['days']} · 하루 유니버스 평균 {o['universe_mean']:.0f}종목 · 근월 교체로 다음 날 같은 종목 가격이 없어 빠진 비율 {o['rolled_share']:.1%}", "",
         "| 항목 | 하루 평균 |", "|---|---|",
         f"| **선물 매수(저가 마감) − 매도(고가 마감)** | {f(o['fut'])} |", f"| 2023~24 | {f(o['A'])} |", f"| 2025~ | {f(o['B'])} |",
         f"| 비용 20bp 후 | {f(o['net20'])} |", f"| 비용 40bp 후(스트레스) | {f(o['net40'])} |",
         f"| 같은 날·같은 종목 **현물** 차이(비교) | {f(o['spot'])} |",
         f"| 매수 다리만(유니버스 대비) | {f(o['long_ex'])} |", f"| 매도 다리만(유니버스 대비) | {f(o['short_ex'])} |"]
    for mkt in ("KOSPI", "KOSDAQ"):
        if f"mkt_{mkt}" in o:
            L.append(f"| {mkt} 선물만 | {f(o[f'mkt_{mkt}'])} |")
    L += ["", "연도별(선물, bp/일): " + " · ".join(f"{y} {v:+.1f}" for y, v in o["years"].items()), "", f"판정: **{v}** — 비용은 가정이다. 다음 단계는 호가 실측.", ""]
    return "\n".join(L)


def selftest():
    u = pd.DataFrame({"ticker": [f"{i:06d}" for i in range(20)], "clv": np.linspace(0, 1, 20),
                      "fr": np.linspace(0.01, -0.01, 20), "sr": np.linspace(0.02, -0.02, 20)})
    r = day_spread(u)
    assert r["k"] == 4 and abs(r["fut"] - (u.fr.iloc[:4].mean() - u.fr.iloc[-4:].mean())) < 1e-12 and r["fut"] > 0
    assert day_spread(u.iloc[:19]) is None
    print("selftest 통과")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--selftest", action="store_true")
    selftest() if ap.parse_args().selftest else run()
