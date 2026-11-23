"""진바닥 조건 E 탐색 — 사전등록 findings/true-bottom-explore-prereg-2026-11.md 그대로 (RP-2.0 시범).

  python research/strategy-lab/true_bottom_explore.py --selftest
  python research/strategy-lab/true_bottom_explore.py
"""
import argparse
import sys
from pathlib import Path

import numpy as np
import pandas as pd

HERE = Path(__file__).parent
sys.path.insert(0, str(HERE))
from zbt import PANEL, START, load_sp500          # noqa: E402  같은 패널·지수 로더 재사용
from trials import bh_with_prior                   # noqa: E402

DD = (-0.10, -0.22)
BR = (0.40, 0.20)
DEBOUNCE, H, NULL_N, SEED, COST, PRIOR = 21, 63, 2000, 20261124, 0.0005, 37   # PRIOR = 사전등록 시점 누적 us


def features(panel):
    p = panel.sort_values(["ticker", "start", "date"]).copy()
    p["ma50"] = p.groupby(["ticker", "start"])["close"].transform(lambda s: s.rolling(50).mean())
    m = p[p["member"] & p["ma50"].notna()].drop_duplicates(["ticker", "date"])
    breadth = (m["close"] > m["ma50"]).groupby(m["date"]).mean()
    a = panel[panel["ticker"] == "AAPL"].drop_duplicates("date").set_index("date")["close"].sort_index()
    dd = a / a.rolling(252, min_periods=252).max() - 1
    return pd.DataFrame({"dd": dd, "br": breadth}).dropna()


def onsets(flag, gap=DEBOUNCE):
    """참이고 직전 gap 거래일 동안 참이 아니었던 날."""
    v = flag.to_numpy(bool)
    out = []
    for i in range(len(v)):
        if v[i] and not v[max(0, i - gap):i].any():
            out.append(flag.index[i])
    return out


def fwd(px, d, h):
    i = px.index.searchsorted(d)
    if i >= len(px) or i + h >= len(px):
        return np.nan
    return px.iloc[i + h] / px.iloc[i] - 1


def null_means(pool_idx, px, n, rng, gap=DEBOUNCE):
    out = []
    while len(out) < NULL_N:
        pick = np.sort(rng.choice(pool_idx, n, replace=False))
        if n > 1 and np.diff(pick).min() < gap:
            continue
        out.append(np.mean([px.iloc[i + H] / px.iloc[i] - 1 for i in pick]))
    return np.array(out)


def run():
    f = features(pd.read_parquet(PANEL))
    px = load_sp500()
    f = f[(f.index >= START)]
    end = f.index.max()
    pool = np.arange(len(px))[(px.index <= end)[: len(px)]]
    pool = pool[pool + H < len(px)]
    spx_dd = px / px.rolling(252, min_periods=1).max() - 1
    matched = pool[(spx_dd.iloc[pool] <= -0.08).to_numpy()]
    print(f"구간 {f.index.min().date()}~{end.date()} · 애플 낙폭 최저 {f.dd.min():.1%} · 50일선 위 비율 최저 {f.br.min():.1%}")
    rows, ps = [], []
    rng = np.random.default_rng(SEED)
    for d_ in DD:
        for b_ in BR:
            ev = [d for d in onsets((f.dd <= d_) & (f.br <= b_)) if not np.isnan(fwd(px, d, H))]
            r63 = np.array([fwd(px, d, H) for d in ev])
            n = len(ev)
            row = {"칸": f"낙폭≤{d_:.0%}·비율≤{b_:.0%}", "n": n, "dates": [str(d.date()) for d in ev]}
            if n >= 1:
                nm = null_means(pool, px, n, rng)
                row.update(mean=r63.mean(), null=nm.mean(), p=(np.sum(nm >= r63.mean()) + 1) / (NULL_N + 1),
                           pos=(r63 > 0).mean(), r21=np.nanmean([fwd(px, d, 21) for d in ev]),
                           r126=np.nanmean([fwd(px, d, 126) for d in ev]))
                if len(matched) >= n:
                    mm = null_means(matched, px, n, rng, gap=1)
                    row["matched"] = mm.mean()
            rows.append(row)
            ps.append(row.get("p", 1.0) if n >= 10 else None)
    testable = [i for i, p in enumerate(ps) if p is not None]
    adj, ok, m = bh_with_prior([ps[i] for i in testable], q=0.10, prior=PRIOR)
    for k, i in enumerate(testable):
        rows[i]["p_bh"], rows[i]["pass"] = adj[k], ok[k] and rows[i]["mean"] > rows[i]["null"]
    print(f"BH 가족 m = {len(testable)} 시험 + 누적 {PRIOR} (사건 <10 칸은 시험 아님 → 판정 불가)")
    for r in rows:
        if r["n"] == 0:
            print(f"{r['칸']}: 사건 0"); continue
        tag = ("통과(후보)" if r.get("pass") else "미통과") if r["n"] >= 10 else "판정 불가(n<10)"
        print(f"{r['칸']}: n={r['n']} · 63일 {r['mean']:+.2%} (net {r['mean'] - COST:+.2%}) vs 무작위 {r['null']:+.2%}"
              f" · 매칭(S&P −8%↓) {r.get('matched', float('nan')):+.2%} · p {r['p']:.3f} · BH {r.get('p_bh', float('nan')):.3f}"
              f" · 양수 {r['pos']:.0%} · 21일 {r['r21']:+.2%} · 126일 {r['r126']:+.2%} → {tag}")
        print("   " + ", ".join(r["dates"]))
    return rows


def selftest():
    idx = pd.bdate_range("2020-01-01", periods=60)
    flag = pd.Series(False, idx); flag.iloc[[5, 6, 20, 45]] = True
    assert onsets(flag) == [idx[5], idx[45]], onsets(flag)        # 6·20 은 직전 21일 안에 참이 있어 제외
    px = pd.Series(np.arange(1, 101, dtype=float), pd.bdate_range("2020-01-01", periods=100))
    assert abs(fwd(px, px.index[0], 63) - 63) < 1e-12 and np.isnan(fwd(px, px.index[50], 63))
    pan = pd.DataFrame({"date": list(pd.bdate_range("2020-01-01", periods=300)) * 2,
                        "close": list(np.linspace(100, 200, 300)) + list(np.linspace(200, 100, 300)),
                        "ticker": ["AAPL"] * 300 + ["X"] * 300, "start": "s", "member": True})
    f = features(pan)
    assert abs(f["br"].iloc[-1] - 0.5) < 1e-12           # AAPL 상승(위)·X 하락(아래)
    assert f["dd"].iloc[-1] == 0
    print("selftest 통과")


if __name__ == "__main__":
    ap = argparse.ArgumentParser(); ap.add_argument("--selftest", action="store_true")
    selftest() if ap.parse_args().selftest else run()
