"""Double 7 지수 — E (findings/double7-explore-prereg-2026-11.md) · --confirm = S&P500 1970~1989."""
import argparse, re, sys
from pathlib import Path
import numpy as np, pandas as pd
from scipy import stats
sys.path.insert(0, str(Path(__file__).resolve().parent))
from us_daily_yahoo import load
from trials import bh_with_prior
PR = {k: int(v) for k, v in re.findall(r"누적 (kr|us) (\d+)", (Path(__file__).parent / "findings/double7-explore-prereg-2026-11.md").read_text(encoding="utf-8"))}
MKT = [("S&P500", "^GSPC", "us"), ("나스닥100", "^NDX", "us"), ("러셀2000", "^RUT", "us"), ("코스피", "^KS11", "kr"), ("코스닥", "^KQ11", "kr")]


def trades(c):
    ent = ((c > c.rolling(200).mean()) & (c <= c.rolling(7).min())).to_numpy()
    ext = (c >= c.rolling(7).max()).to_numpy()
    out, i, n = [], 0, len(c)
    while i < n:
        if ent[i]:
            j = i + 1
            while j < n and not ext[j]:
                j += 1
            if j >= n:
                break
            out.append((c.index[i], c.iloc[j] / c.iloc[i] - 1, j - i)); i = j + 1
        else:
            i += 1
    return pd.DataFrame(out, columns=["d", "r", "days"])


def test(c, lo=None, hi=None):
    t = trades(c)
    if lo:
        t = t[(t.d >= lo) & (t.d <= hi)]
        c2 = c[(c.index >= lo) & (c.index <= hi)]
    else:
        c2 = c
    L = max(1, int(round(t.days.mean())))
    base = (c2.shift(-L) / c2 - 1).dropna()
    tt, p2 = stats.ttest_ind(t.r, base, equal_var=False)
    return t, base.mean(), tt, (p2 / 2 if tt > 0 else 1 - p2 / 2)


def run():
    rows = []
    for name, sym, smp in MKT:
        c = load(sym)["close"].dropna()
        if smp == "us":
            c = c[c.index >= "1989-01-01"]                 # 200일 예열 1989, 진입은 1990~
            t, b, tt, p = test(c, "1990-01-01", "2100-01-01")
        else:
            t, b, tt, p = test(c)
        rows.append((name, smp, t, b, tt, p))
    for smp in ("us", "kr"):
        cs = [x for x in rows if x[1] == smp]
        adj, ok, m = bh_with_prior([x[5] for x in cs], q=0.10, prior=PR[smp])
        for (name, _, t, b, tt, p), a_, o in zip(cs, adj, ok):
            print(f"[{smp}] {name}: 거래 {len(t)} · 평균 {t.r.mean():+.2%}(보유 {t.days.mean():.1f}일) vs 아무 때 {b:+.2%} · 승률 {(t.r > 0).mean():.0%}"
                  f" · t {tt:+.2f} · p {p:.5f} · BH {a_:.4f}(m={m}) → {'탐색 통과(사후)' if o and tt > 0 else '미통과'}")


def confirm():
    c = load("^GSPC")["close"].dropna()
    c = c[(c.index >= "1969-01-01") & (c.index <= "1990-03-01")]
    t, b, tt, p = test(c, "1970-01-01", "1989-12-31")
    print(f"확인 S&P500 1970~1989 Double 7: 거래 {len(t)} · 평균 {t.r.mean():+.2%} vs 아무 때 {b:+.2%} · 승률 {(t.r > 0).mean():.0%} · t {tt:+.2f} · 단측 p {p:.4f}"
          f" → {'확인됨' if p <= 0.05 and tt > 0 and len(t) >= 5 else 'REJECT'}")


def selftest():
    c = pd.Series(np.r_[np.linspace(100, 200, 220), [195, 190, 185, 186, 188, 192, 196, 201, 205]], pd.bdate_range("2000-01-01", periods=229))
    t = trades(c)
    assert len(t) >= 1 and t.r.iloc[0] > 0
    print("selftest 통과")


if __name__ == "__main__":
    ap = argparse.ArgumentParser(); ap.add_argument("--selftest", action="store_true"); ap.add_argument("--confirm", action="store_true")
    a = ap.parse_args(); selftest() if a.selftest else (confirm() if a.confirm else run())
