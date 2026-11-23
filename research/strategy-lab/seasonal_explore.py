"""계절성 E — findings/seasonal-us-kr-explore-prereg-2026-11.md 그대로. --confirm H1|H2 = S&P500 1970~1989.
  python research/strategy-lab/seasonal_explore.py [--selftest | --confirm H1 [--alpha 0.05]]"""
import argparse, re, sys
from pathlib import Path
import numpy as np, pandas as pd
from scipy import stats
sys.path.insert(0, str(Path(__file__).resolve().parent))
from us_daily_yahoo import load
from trials import bh_with_prior
PR = {k: int(v) for k, v in re.findall(r"누적 (kr|us) (\d+)", (Path(__file__).parent / "findings/seasonal-us-kr-explore-prereg-2026-11.md").read_text(encoding="utf-8"))}
MKT = [("S&P500", "^GSPC", "us"), ("나스닥100", "^NDX", "us"), ("러셀2000", "^RUT", "us"), ("코스피", "^KS11", "kr"), ("코스닥", "^KQ11", "kr")]


def h1(c):
    m = c.resample("ME").last().pct_change().dropna()
    win = m[m.index.month.isin([11, 12, 1, 2, 3, 4])]
    smr = m[m.index.month.isin([5, 6, 7, 8, 9, 10])]
    t, p2 = stats.ttest_ind(win, smr, equal_var=False)
    return {"n": int(len(m) / 12), "a": win.mean(), "b": smr.mean(), "t": t, "p": p2 / 2 if t > 0 else 1 - p2 / 2, "detail": (win, smr)}


def thanksgiving(y):
    nov = pd.date_range(f"{y}-11-01", f"{y}-11-30")
    return [d for d in nov if d.weekday() == 3][3]


def h2(c):
    ev, base = [], []
    for y in range(c.index[0].year, c.index[-1].year):
        tg = thanksgiving(y)
        i0 = c.index.searchsorted(tg) - 1                       # 추수감사절 전 거래일
        jan = c.index[(c.index >= f"{y + 1}-01-01")]
        if i0 < 1 or len(jan) < 2 or c.index[i0].year != y:
            continue
        i1 = c.index.get_loc(jan[1])
        L = i1 - i0
        ev.append(c.iloc[i1] / c.iloc[i0] - 1)
        yr = c[(c.index >= f"{y}-01-01") & (c.index < c.index[i0])]
        blocks = [yr.iloc[k + L] / yr.iloc[k] - 1 for k in range(0, len(yr) - L, L)]
        if blocks:
            base.append(np.mean(blocks))
    ev, base = np.array(ev), np.array(base[:len(ev)])
    d = ev[:len(base)] - base
    t, p2 = stats.ttest_1samp(d, 0)
    return {"n": len(d), "a": ev.mean(), "b": base.mean(), "t": t, "p": p2 / 2 if t > 0 else 1 - p2 / 2, "pos": (ev > 0).mean()}


def run():
    rows = []
    for name, sym, smp in MKT:
        c = load(sym)["close"].dropna()
        if smp == "us":
            c = c[c.index >= "1990-01-01"]
        for hyp, f in (("H1", h1), ("H2", h2)):
            r = f(c)
            rows.append({"name": name, "smp": smp, "hyp": hyp, **r})
    for smp in ("us", "kr"):
        cs = [x for x in rows if x["smp"] == smp and x["n"] >= 5]
        adj, ok, m = bh_with_prior([x["p"] for x in cs], q=0.10, prior=PR[smp])
        for x, a_, o in zip(cs, adj, ok):
            extra = f" · 양수 {x['pos']:.0%}" if "pos" in x else ""
            print(f"[{smp}] {x['name']} {x['hyp']}: n={x['n']} · {x['a']:+.2%} vs {x['b']:+.2%}{extra} · t {x['t']:+.2f} · p {x['p']:.4f} · BH {a_:.4f}(m={m})"
                  f" → {'탐색 통과' if o and x['t'] > 0 else '미통과'}")


def confirm(hyp, alpha):
    c = load("^GSPC")["close"].dropna()
    c = c[(c.index >= "1969-12-01") & (c.index <= "1990-01-10")]
    r = (h1 if hyp == "H1" else h2)(c)
    print(f"확인 S&P500 1970~1989 {hyp}: n={r['n']} · {r['a']:+.2%} vs {r['b']:+.2%} · t {r['t']:+.2f} · 단측 p {r['p']:.4f} (기준 {alpha}) → {'확인됨' if r['p'] <= alpha and r['t'] > 0 else 'REJECT'}")


def selftest():
    assert thanksgiving(2026) == pd.Timestamp("2026-11-26") and thanksgiving(2024) == pd.Timestamp("2024-11-28")
    idx = pd.bdate_range("2000-01-01", "2004-12-31")
    c = pd.Series(np.exp(np.cumsum(np.where(idx.month.isin([11, 12, 1, 2, 3, 4]), 0.002, -0.001))), idx)
    assert h1(c)["t"] > 3
    print("selftest 통과")


if __name__ == "__main__":
    ap = argparse.ArgumentParser(); ap.add_argument("--selftest", action="store_true"); ap.add_argument("--confirm", choices=["H1", "H2"]); ap.add_argument("--alpha", type=float, default=0.05)
    a = ap.parse_args(); selftest() if a.selftest else (confirm(a.confirm, a.alpha) if a.confirm else run())
