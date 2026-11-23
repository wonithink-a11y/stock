"""지수 스윙 규칙 2종 — E (findings/index-swing-rules-explore-prereg-2026-11.md) · --confirm = S&P500 1970~1989 (통과 규칙만)."""
import argparse, re, sys
from pathlib import Path
import numpy as np, pandas as pd
from scipy import stats
sys.path.insert(0, str(Path(__file__).resolve().parent))
from us_daily_yahoo import load
from trials import bh_with_prior
PR = {k: int(v) for k, v in re.findall(r"누적 (kr|us) (\d+)", (Path(__file__).parent / "findings/index-swing-rules-explore-prereg-2026-11.md").read_text(encoding="utf-8"))}
MKT = [("S&P500", "^GSPC", "us"), ("나스닥100", "^NDX", "us"), ("러셀2000", "^RUT", "us"), ("코스피", "^KS11", "kr"), ("코스닥", "^KQ11", "kr")]
COST = 0.0005
PER = [("~2015", "1900", "2015-12-31"), ("2016~23", "2016-01-01", "2023-12-31"), ("2024", "2024-01-01", "2024-12-31"), ("2025~", "2025-01-01", "2100")]


def sig(d, rule):
    c, h, l = d.close, d.high, d.low
    m5 = c.rolling(5).mean()
    if rule == "A":
        dn = lambda s: (s < s.shift(1)) & (s.shift(1) < s.shift(2)) & (s.shift(2) < s.shift(3))
        return (c > c.rolling(200).mean()) & (c < m5) & dn(h) & dn(l), c > m5
    m20, m10 = c.rolling(20).mean(), c.rolling(10).mean()
    return (c > m20) & (c.shift(1) <= m20.shift(1)), c < m10


def trades(c, ent, ext):
    e, x = ent.to_numpy(), ext.to_numpy()
    out, i, n = [], 0, len(c)
    while i < n:
        if e[i]:
            j = i + 1
            while j < n and not x[j]:
                j += 1
            if j >= n:
                break
            out.append((c.index[i], c.iloc[j] / c.iloc[i] - 1, j - i)); i = j + 1
        else:
            i += 1
    return pd.DataFrame(out, columns=["d", "r", "days"])


def get(sym):
    d = load(sym).dropna(subset=["close"])
    return d[(d.high > 0) & (d.low > 0)]


def test(d, rule, lo, hi):
    t = trades(d.close, *sig(d, rule))
    t = t[(t.d >= lo) & (t.d <= hi)]
    c2 = d.close[(d.index >= lo) & (d.index <= hi)]
    L = max(1, int(round(t.days.mean())))
    base = (c2.shift(-L) / c2 - 1).dropna()
    tt, p2 = stats.ttest_ind(t.r, base, equal_var=False)
    return t, base.mean(), tt, (p2 / 2 if tt > 0 else 1 - p2 / 2), c2


def line(t, b, c2):
    ann = (1 + t.r - COST).prod() ** (252 / len(c2)) - 1
    bh = (c2.iloc[-1] / c2.iloc[0]) ** (252 / len(c2)) - 1
    tt = t.set_index("d").r
    per = " · ".join(f"{k} {tt[(tt.index >= a) & (tt.index <= z)].mean():+.2%}" for k, a, z in PER if len(tt[(tt.index >= a) & (tt.index <= z)]) >= 5)
    return (f"거래 {len(t)} · 평균 {t.r.mean():+.2%}(보유 {t.days.mean():.1f}일) vs 아무 때 {b:+.2%} · 승률 {(t.r > 0).mean():.0%}"
            f" · 노출 {t.days.sum() / len(c2):.0%} · 연 net {ann:+.1%} vs 보유 {bh:+.1%} | {per}")


def run():
    rows = []
    for rule in "AB":
        for name, sym, smp in MKT:
            d = get(sym)
            lo = "1990-01-01" if smp == "us" else "1900-01-01"
            if smp == "us":
                d = d[d.index >= "1989-01-01"]
            rows.append((rule, name, smp) + test(d, rule, lo, "2100-01-01"))
    for smp in ("us", "kr"):
        cs = [x for x in rows if x[2] == smp]
        adj, ok, m = bh_with_prior([x[6] for x in cs], q=0.10, prior=PR[smp])
        for (rule, name, _, t, b, tt, p, c2), a_, o in zip(cs, adj, ok):
            print(f"[{smp}] {rule} {name}: {line(t, b, c2)} · t {tt:+.2f} · p {p:.5f} · BH {a_:.4f}(m={m}) → {'탐색 통과(사후)' if o and tt > 0 and len(t) >= 5 else '미통과'}")


def confirm(rule):
    d = get("^GSPC")
    d = d[(d.index >= "1969-01-01") & (d.index <= "1990-03-01")]
    t, b, tt, p, c2 = test(d, rule, "1970-01-01", "1989-12-31")
    print(f"확인 S&P500 1970~1989 규칙 {rule}: {line(t, b, c2)} · t {tt:+.2f} · 단측 p {p:.4f} → {'확인됨' if p <= 0.05 and tt > 0 and len(t) >= 5 else 'REJECT'}")


def selftest():
    idx = pd.bdate_range("2000-01-01", periods=230)
    c = pd.Series(np.r_[np.linspace(100, 200, 220), [199, 198, 197, 198, 202, 206, 207, 208, 209, 210]], idx)
    d = pd.DataFrame({"close": c, "high": c * 1.01, "low": c * 0.99})
    t = trades(d.close, *sig(d, "A"))
    assert len(t) == 1 and t.d.iloc[0] == idx[222] and t.r.iloc[0] > 0, t
    tb = trades(d.close, *sig(d, "B"))
    assert (tb.days > 0).all()
    print("selftest 통과")


if __name__ == "__main__":
    ap = argparse.ArgumentParser(); ap.add_argument("--selftest", action="store_true"); ap.add_argument("--confirm", choices=["A", "B"])
    a = ap.parse_args(); selftest() if a.selftest else (confirm(a.confirm) if a.confirm else run())
