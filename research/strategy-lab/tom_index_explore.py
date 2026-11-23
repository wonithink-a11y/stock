"""월말·월초(TOM) 지수 효과 — E 탐색 (findings/tom-index-explore-prereg-2026-11.md 그대로). --confirm = S&P500 1970~1989.
  python research/strategy-lab/tom_index_explore.py [--selftest | --confirm]"""
import argparse, sys
from pathlib import Path
import numpy as np, pandas as pd
from scipy import stats
sys.path.insert(0, str(Path(__file__).resolve().parent))
from us_daily_yahoo import load
from trials import bh_with_prior
MKT = {"코스피": ("^KS11", "kr"), "코스닥": ("^KQ11", "kr"), "S&P500": ("^GSPC", "us"), "나스닥100": ("^NDX", "us"), "러셀2000": ("^RUT", "us")}
P = [("~2015", "1900", "2015-12-31"), ("2016~23", "2016-01-01", "2023-12-31"), ("2024", "2024-01-01", "2024-12-31"), ("2025~", "2025-01-01", "2100")]
import re
PR = {k: int(v) for k, v in re.findall(r"누적 (kr|us) (\d+)", (Path(__file__).parent / "findings/tom-index-explore-prereg-2026-11.md").read_text(encoding="utf-8"))}


def tom_flag(idx):
    per = idx.to_period("M")
    s = pd.Series(0, idx)
    pos = s.groupby(per).cumcount()
    last = s.groupby(per).cumcount(ascending=False) == 0
    return (last | (pos <= 2)).to_numpy()


def test(r):
    f = tom_flag(r.index)
    a, b = r[f], r[~f]
    t, p2 = stats.ttest_ind(a, b, equal_var=False)
    p = p2 / 2 if t > 0 else 1 - p2 / 2
    return {"a": a.mean(), "b": b.mean(), "t": t, "p": p, "r": r, "f": f}


def run():
    rows = []
    for name, (sym, smp) in MKT.items():
        c = load(sym)["close"].dropna()
        if smp == "us":
            c = c[c.index >= "1990-01-01"]
        rows.append({"name": name, "smp": smp, **test(c.pct_change().dropna())})
    for smp in ("kr", "us"):
        cs = [x for x in rows if x["smp"] == smp]
        adj, ok, m = bh_with_prior([x["p"] for x in cs], q=0.10, prior=PR[smp])
        for x, a_, o in zip(cs, adj, ok):
            r, f = x["r"], x["f"]
            per = " · ".join(f"{k} {(r[f & (r.index >= s) & (r.index <= e)].mean() - r[~f & (r.index >= s) & (r.index <= e)].mean()) * 1e4:+.1f}bp" for k, s, e in P)
            tm = (1 + r[f]).groupby(r[f].index.to_period("M")).prod() - 1
            print(f"[{smp}] {x['name']}: TOM {x['a']*1e4:+.1f}bp vs 나머지 {x['b']*1e4:+.1f}bp · t {x['t']:+.2f} · p {x['p']:.5f} · BH {a_:.4f}(m={m})"
                  f" → {'탐색 통과(사후)' if o and x['t'] > 0 else '미통과'} · TOM 묶음 {tm.mean():+.2%}(net {tm.mean()-0.0005:+.2%}, 양수 {(tm>0).mean():.0%}) | {per}")


def confirm():
    c = load("^GSPC")["close"].dropna()
    r = c.pct_change().dropna()
    r = r[(r.index >= "1970-01-01") & (r.index <= "1989-12-31")]
    x = test(r)
    print(f"확인 S&P500 1970~1989: TOM {x['a']*1e4:+.1f}bp vs {x['b']*1e4:+.1f}bp · t {x['t']:+.2f} · 단측 p {x['p']:.4f} → {'확인됨' if x['p'] <= 0.05 and x['t'] > 0 else 'REJECT'}")


FWD_START, FWD_MONTHS = "2026-12-01", 36


def forward(judge=False):
    """확인(C) forward — tom-kr-forward-prereg-2026-11.md. 2026-12 이후 국내 2지수만, 36개월 전 판정 거부."""
    for name in ("코스피", "코스닥"):
        c = load(MKT[name][0])["close"].dropna()
        r = c.pct_change().dropna()
        r = r[r.index >= FWD_START]
        months = r.index.to_period("M").nunique()
        if not judge or months < FWD_MONTHS:
            print(f"{name}: forward {months}개월 (판정은 {FWD_MONTHS}개월 뒤)" + (" — 판정 거부" if judge else ""))
            continue
        x = test(r)
        print(f"{name} forward 판정: TOM {x['a']*1e4:+.1f}bp vs {x['b']*1e4:+.1f}bp · t {x['t']:+.2f} · 단측 p {x['p']:.4f} → {'확인됨' if x['p'] <= 0.05 and x['t'] > 0 else 'REJECT'}")


def selftest():
    idx = pd.bdate_range("2020-01-01", "2020-03-31")
    f = tom_flag(idx)
    d = pd.Series(f, idx)
    assert d["2020-01-31"] and d["2020-02-03"] and d["2020-02-05"] and not d["2020-02-06"] and d["2020-01-01"]
    print("selftest 통과")


if __name__ == "__main__":
    ap = argparse.ArgumentParser(); ap.add_argument("--selftest", action="store_true"); ap.add_argument("--confirm", action="store_true")
    ap.add_argument("--forward", action="store_true"); ap.add_argument("--judge", action="store_true")
    a = ap.parse_args()
    selftest() if a.selftest else (confirm() if a.confirm else (forward(a.judge) if a.forward else run()))
