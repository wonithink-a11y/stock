"""RSI2 과매도 → 5일 (미국·국내 지수) — E 탐색. 사전등록 findings/rsi2-index-explore-prereg-2026-11.md 그대로.
확인(C): --confirm 은 S&P500 1970~1989 단일 검정(R1·R2 중 미국 통과 칸만 — 호출자가 규칙을 고른다).

  python research/strategy-lab/rsi2_index_explore.py --selftest
  python research/strategy-lab/rsi2_index_explore.py
  python research/strategy-lab/rsi2_index_explore.py --confirm R1
"""
import argparse
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
from us_daily_yahoo import load      # noqa: E402
from trials import bh_with_prior      # noqa: E402

H, N_NULL, SEED, COST = 5, 20_000, 20261124, 0.0005
MKT = {"S&P500": ("^GSPC", "us"), "나스닥100": ("^NDX", "us"), "러셀2000": ("^RUT", "us"),
       "코스피": ("^KS11", "kr"), "코스닥": ("^KQ11", "kr")}
PRIOR = {"us": 72, "kr": 422}
PERIODS = [("~2015", "1900", "2015-12-31"), ("2016~23", "2016-01-01", "2023-12-31"), ("2024", "2024-01-01", "2024-12-31"), ("2025~", "2025-01-01", "2100")]


def rsi2(c):
    d = c.diff()
    up = d.clip(lower=0).ewm(alpha=0.5, adjust=False).mean()
    dn = (-d.clip(upper=0)).ewm(alpha=0.5, adjust=False).mean()
    return 100 - 100 / (1 + up / dn)


def signal(c, rule):
    s = rsi2(c) < 10
    if rule == "R1":
        s &= c > c.rolling(200).mean()
    return s.fillna(False)


def entries(sig, fr):
    """겹침 제거: 진입 후 H 거래일 안의 신호는 버린다. 5일 결과가 있는 날만."""
    out, nxt = [], -1
    v, ok = sig.to_numpy(), fr.notna().to_numpy()
    for i in range(len(v)):
        if v[i] and ok[i] and i >= nxt:
            out.append(i); nxt = i + H
    return out


def test(c, rule, rng):
    fr = c.shift(-H) / c - 1
    idx = entries(signal(c, rule), fr)
    ev = fr.iloc[idx]
    pool = fr.dropna().to_numpy()
    n = len(ev)
    if n < 5:
        return {"n": n}
    draws = pool[rng.integers(0, len(pool), size=(N_NULL, n))].mean(axis=1)
    p = (np.sum(draws >= ev.mean()) + 1) / (N_NULL + 1)
    r = {"n": n, "mean": ev.mean(), "null": draws.mean(), "p": p, "win": (ev > 0).mean()}
    for lab, a, b in PERIODS:
        e2 = ev[(ev.index >= a) & (ev.index <= b)]
        r[lab] = e2.mean() if len(e2) >= 3 else np.nan
    return r


def run():
    rng = np.random.default_rng(SEED)
    rows = []
    for name, (sym, smp) in MKT.items():
        c = load(sym)["close"].dropna()
        if smp == "us":
            c = c[c.index >= "1990-01-01"]               # 1970~1989 는 확인 전용
        for rule in ("R1", "R2"):
            rows.append({"시장": name, "표본": smp, "규칙": rule, **test(c, rule, rng)})
    for smp in ("us", "kr"):
        cells = [r for r in rows if r["표본"] == smp and r["n"] >= 5]
        adj, ok, m = bh_with_prior([r["p"] for r in cells], q=0.10, prior=PRIOR[smp])
        for r, a, o in zip(cells, adj, ok):
            r["p_bh"], r["pass"], r["m"] = a, o and r["mean"] > r["null"], m
    for r in rows:
        if r["n"] < 5:
            print(f"{r['시장']} {r['규칙']}: n={r['n']} 판정 불가"); continue
        per = " · ".join(f"{k} {r[k]:+.2%}" for k, *_ in PERIODS if pd.notna(r[k]))
        print(f"{r['시장']:<6} {r['규칙']}: n={r['n']} · 5일 {r['mean']:+.3%} (net {r['mean'] - COST:+.3%}) vs 무작위 {r['null']:+.3%}"
              f" · 승률 {r['win']:.0%} · p {r['p']:.5f} · BH {r['p_bh']:.4f}(m={r['m']}) → {'탐색 통과(사후)' if r['pass'] else '미통과'} | {per}")
    return rows


def confirm(rule):
    c = load("^GSPC")["close"].dropna()
    c = c[(c.index >= "1969-01-01") & (c.index <= "1990-01-10")]     # 200일선 예열 1969, 결과는 1970~1989 진입만
    rng = np.random.default_rng(SEED)
    fr = c.shift(-H) / c - 1
    idx = [i for i in entries(signal(c, rule), fr) if "1970-01-01" <= str(c.index[i].date()) <= "1989-12-31"]
    ev = fr.iloc[idx]
    pool = fr[(fr.index >= "1970-01-01") & (fr.index <= "1989-12-31")].dropna().to_numpy()
    draws = pool[rng.integers(0, len(pool), size=(N_NULL, len(ev)))].mean(axis=1)
    p = (np.sum(draws >= ev.mean()) + 1) / (N_NULL + 1)
    print(f"확인 S&P500 1970~1989 {rule}: n={len(ev)} · 5일 {ev.mean():+.3%} (net {ev.mean() - COST:+.3%}) vs 무작위 {draws.mean():+.3%}"
          f" · 승률 {(ev > 0).mean():.0%} · 단측 p {p:.5f} → {'확인됨' if (p <= 0.05 and ev.mean() > draws.mean() and len(ev) >= 5) else 'REJECT'}")


def selftest():
    c = pd.Series([10, 9, 8, 7, 8, 9, 10, 11, 12, 13, 12, 11, 10], dtype=float,
                  index=pd.bdate_range("2020-01-01", periods=13))
    r = rsi2(c)
    assert r.iloc[3] < 10 and r.iloc[9] > 90
    sig = pd.Series([True, True, False, False, False, False, True, False, False, False, False, False, False], index=c.index)
    fr = c.shift(-H) / c - 1
    assert entries(sig, fr) == [0, 6]                 # 1 은 보유 중이라 버림
    s1 = signal(pd.Series(np.r_[np.linspace(1, 300, 250), [290, 280]]), "R1")
    assert s1.iloc[-1]                                # 200일선 위에서 급락 → R1 참
    print("selftest 통과")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--selftest", action="store_true")
    ap.add_argument("--confirm", choices=["R1", "R2"])
    a = ap.parse_args()
    selftest() if a.selftest else (confirm(a.confirm) if a.confirm else run())
