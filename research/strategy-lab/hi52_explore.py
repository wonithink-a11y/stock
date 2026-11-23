"""국내 52주 고가 근접 — E 탐색 (사전등록 findings/hi52-kr-explore-prereg-2026-11.md 그대로). 미국은 비교 칸.
확인(C): --confirm 은 국내 2010-01~2016-01 홀드아웃(krx-pbr-history/daily)에서 롱 온리 칸 단일 검정.

  python research/strategy-lab/hi52_explore.py --selftest
  python research/strategy-lab/hi52_explore.py
  python research/strategy-lab/hi52_explore.py --confirm
"""
import argparse
import sys
from pathlib import Path

import numpy as np
import pandas as pd
from scipy import stats

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE)); sys.path.insert(0, str(HERE.parent / "sandbox"))
from trials import bh_with_prior                 # noqa: E402
from cross_section_us_kr import us_panel, kr_panel   # noqa: E402

PRIOR = {"kr": 433, "us": 86}
COST = {"kr": 0.00335, "us": 0.0005}
PERIODS = [("2016~23", "1900", "2023-12-31"), ("2024", "2024-01-01", "2024-12-31"), ("2025~", "2025-01-01", "2100")]


def monthly(ret, close, mem, exclude=()):
    days = ret.index
    ends = pd.Series(days, index=days).groupby(days.to_period("M")).last().values
    hi = close / close.rolling(252, min_periods=240).max()
    rows, prev_top = [], set()
    for a, b in zip(ends[:-1], ends[1:]):
        x = hi.loc[a][mem.loc[a]].dropna()
        x = x[~x.index.isin(exclude)]
        if len(x) < 50:
            continue
        nxt = (1 + ret.loc[(ret.index > a) & (ret.index <= b), x.index].fillna(0)).prod() - 1
        q = pd.qcut(x.rank(method="first"), 5, labels=False)
        top = set(x.index[q == 4])
        turn = 1 - len(top & prev_top) / max(len(top), 1)
        prev_top = top
        rows.append((b, nxt[q == 4].mean() - nxt[q == 0].mean(), nxt[q == 4].mean() - nxt.mean(), turn))
    return pd.DataFrame(rows, columns=["date", "ls", "lo", "turn"]).set_index("date")


def cell(s):
    t = s.mean() / (s.std(ddof=1) / np.sqrt(len(s)))
    return {"n": len(s), "mean": s.mean(), "t": t, "p": 1 - stats.t.cdf(t, len(s) - 1)}


def kr_holdout_panel():
    fs = sorted((HERE / "data/krx-pbr-history/daily").glob("*.parquet"))
    d = pd.concat(pd.read_parquet(f, columns=["BAS_DD", "ISU_CD", "TDD_CLSPRC", "FLUC_RT", "ACC_TRDVAL"]) for f in fs)
    d["date"] = pd.to_datetime(d["BAS_DD"].astype(str))
    for c in ("TDD_CLSPRC", "FLUC_RT", "ACC_TRDVAL"):
        d[c] = pd.to_numeric(d[c].astype(str).str.replace(",", ""), errors="coerce")
    d = d.drop_duplicates(["ISU_CD", "date"])
    ret = d.pivot(index="date", columns="ISU_CD", values="FLUC_RT") / 100
    ret = ret.where(ret.abs() < 0.16)                    # 2015-06 전 가격제한폭 ±15%
    close = d.pivot(index="date", columns="ISU_CD", values="TDD_CLSPRC")
    liq = d.pivot(index="date", columns="ISU_CD", values="ACC_TRDVAL").rolling(20, min_periods=15).mean()
    return ret, close, liq.rank(axis=1, ascending=False) <= 500


def run():
    out = {}
    for smp, loader in (("kr", kr_panel), ("us", us_panel)):
        m = monthly(*loader())
        out[smp] = m
        cells = [("5−1", m.ls), ("롱온리−유니버스", m.lo)]
        res = [cell(s) for _, s in cells]
        adj, ok, fam = bh_with_prior([r["p"] for r in res], q=0.10, prior=PRIOR[smp])
        for (lab, s), r, a, o in zip(cells, res, adj, ok):
            per = " · ".join(f"{k} {s[(s.index >= x) & (s.index <= y)].mean():+.2%}" for k, x, y in PERIODS)
            net = f" · net {(s - m.turn * COST[smp]).mean():+.2%} (월 회전율 {m.turn.mean():.0%})" if lab != "5−1" else ""
            print(f"[{smp}] {lab}: n={r['n']} · 월 {r['mean']:+.2%} · t {r['t']:+.2f} · p {r['p']:.5f} · BH {a:.4f}(m={fam})"
                  f" → {'탐색 통과(사후)' if o and r['mean'] > 0 else '미통과'}{net} | {per}")
    semis = set(pd.read_parquet(HERE / "data/factor-panel/kr-monthly-v1.parquet", columns=["ticker", "sector"])
                .query("sector.str.contains('반도체')", engine="python").ticker)
    mx = monthly(*kr_panel(), exclude=semis)
    print(f"[kr 반도체 제외·진단] 5−1 월 {mx.ls.mean():+.2%} · 롱온리 {mx.lo.mean():+.2%} (반도체 {len(semis)}종목 제외)")


def confirm():
    m = monthly(*kr_holdout_panel())
    m = m[(m.index >= "2011-02-01") & (m.index <= "2015-12-31")]
    r = cell(m.lo)
    net = (m.lo - m.turn * COST["kr"]).mean()
    print(f"확인 국내 2011-02~2015-12 롱온리−유니버스: n={r['n']} · 월 {r['mean']:+.2%} (net {net:+.2%}) · t {r['t']:+.2f} · 단측 p {r['p']:.4f}"
          f" → {'확인됨' if r['p'] <= 0.05 and r['mean'] > 0 else 'REJECT'} | 5−1 기록 {m.ls.mean():+.2%}")


def selftest():
    idx = pd.bdate_range("2020-01-01", periods=300)
    cols = [f"S{i}" for i in range(60)]
    rng = np.random.default_rng(0)
    ret = pd.DataFrame(rng.normal(0, 0.01, (300, 60)), idx, cols)
    close = (1 + ret).cumprod()
    mem = pd.DataFrame(True, idx, cols)
    m = monthly(ret, close, mem)
    assert len(m) >= 1 and m.turn.between(0, 1).all()
    r = cell(pd.Series([0.01, 0.02, 0.03, 0.01, 0.02]))
    assert r["t"] > 0 and 0 < r["p"] < 0.01
    print("selftest 통과")


if __name__ == "__main__":
    ap = argparse.ArgumentParser(); ap.add_argument("--selftest", action="store_true"); ap.add_argument("--confirm", action="store_true")
    a = ap.parse_args()
    selftest() if a.selftest else (confirm() if a.confirm else run())
