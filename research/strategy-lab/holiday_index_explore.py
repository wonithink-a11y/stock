"""연휴 직전 지수 효과 — E (findings/holiday-index-explore-prereg-2026-11.md 그대로). --confirm = S&P500 1970~1989 (직전 3일).
  python research/strategy-lab/holiday_index_explore.py [--selftest | --confirm]"""
import argparse, re, sys
from pathlib import Path
import numpy as np, pandas as pd
from scipy import stats
sys.path.insert(0, str(Path(__file__).resolve().parent))
from us_daily_yahoo import load
from trials import bh_with_prior
PR = {k: int(v) for k, v in re.findall(r"누적 (kr|us) (\d+)", (Path(__file__).parent / "findings/holiday-index-explore-prereg-2026-11.md").read_text(encoding="utf-8"))}
CELLS = [("코스피", "^KS11", "kr", 2, 1), ("코스닥", "^KQ11", "kr", 2, 1), ("S&P500", "^GSPC", "us", 1, 3), ("나스닥100", "^NDX", "us", 1, 3)]
P = [("~2015", "1900", "2015-12-31"), ("2016~23", "2016-01-01", "2023-12-31"), ("2024", "2024-01-01", "2024-12-31"), ("2025~", "2025-01-01", "2100")]


def events(c, k, h):
    idx = c.index
    gap = np.array([len(pd.bdate_range(a, b)) - 2 for a, b in zip(idx[:-1], idx[1:])] + [0])
    ev = {}
    for i in np.where(gap >= k)[0]:
        if i - h >= 0:
            ev[idx[i]] = c.iloc[i] / c.iloc[i - h] - 1     # 직전 h 거래일 누적(연휴 직전 거래일 종가까지)
    return pd.Series(ev)


def test(c, k, h):
    ev = events(c, k, h)
    base = (c / c.shift(h) - 1).dropna()
    t, p2 = stats.ttest_ind(ev, base, equal_var=False)
    return ev, base, t, (p2 / 2 if t > 0 else 1 - p2 / 2)


def run():
    rows = []
    for name, sym, smp, k, h in CELLS:
        c = load(sym)["close"].dropna()
        if smp == "us":
            c = c[c.index >= "1990-01-01"]
        ev, base, t, p = test(c, k, h)
        rows.append((name, smp, ev, base, t, p))
    for smp in ("kr", "us"):
        cs = [x for x in rows if x[1] == smp]
        adj, ok, m = bh_with_prior([x[5] for x in cs], q=0.10, prior=PR[smp])
        for (name, _, ev, base, t, p), a_, o in zip(cs, adj, ok):
            per = " · ".join(f"{lab} {ev[(ev.index >= s) & (ev.index <= e)].mean():+.2%}(n{len(ev[(ev.index >= s) & (ev.index <= e)])})" for lab, s, e in P)
            print(f"[{smp}] {name}: n={len(ev)} · 사건 {ev.mean():+.2%} (net {ev.mean()-0.0005:+.2%}) vs 기준 {base.mean():+.2%} · 양수 {(ev>0).mean():.0%}"
                  f" · t {t:+.2f} · p {p:.5f} · BH {a_:.4f}(m={m}) → {'탐색 통과(사후)' if o and t > 0 else '미통과'} | {per}")


def confirm():
    c = load("^GSPC")["close"].dropna()
    c = c[(c.index >= "1969-12-01") & (c.index <= "1990-01-05")]
    ev, base, t, p = test(c, 1, 3)
    ev = ev[(ev.index >= "1970-01-01") & (ev.index <= "1989-12-31")]
    base = base[(base.index >= "1970-01-01") & (base.index <= "1989-12-31")]
    t, p2 = stats.ttest_ind(ev, base, equal_var=False); p = p2 / 2 if t > 0 else 1 - p2 / 2
    print(f"확인 S&P500 1970~1989 연휴 직전 3일: n={len(ev)} · {ev.mean():+.2%} vs {base.mean():+.2%} · t {t:+.2f} · 단측 p {p:.4f} → {'확인됨' if p <= 0.05 and t > 0 else 'REJECT'}")


FWD_START, FWD_MONTHS, FWD_MIN = "2026-12-01", 60, 8


def forward(judge=False):
    """확인(C) forward — holiday-kosdaq-forward-prereg-2026-11.md. 2026-12 이후 코스닥 긴 연휴 직전 하루."""
    c = load("^KQ11")["close"].dropna()
    ev, base, _, _ = test(c, 2, 1)
    ev, base = ev[ev.index >= FWD_START], base[base.index >= FWD_START]
    months = base.index.to_period("M").nunique()
    if not judge or months < FWD_MONTHS or len(ev) < FWD_MIN:
        print(f"코스닥 forward {months}개월 · 사건 {len(ev)} (판정: {FWD_MONTHS}개월 ∧ 사건 ≥ {FWD_MIN})" + (" — 판정 거부" if judge else "")); return
    t, p2 = stats.ttest_ind(ev, base, equal_var=False); p = p2 / 2 if t > 0 else 1 - p2 / 2
    print(f"코스닥 forward 판정: n={len(ev)} {ev.mean():+.2%} vs {base.mean():+.2%} · 단측 p {p:.4f} → {'확인됨' if p <= 0.05 and t > 0 else 'REJECT'}")


def selftest():
    idx = pd.DatetimeIndex(["2020-01-20", "2020-01-21", "2020-01-22", "2020-01-28", "2020-01-29"])   # 23~27 휴장(평일 3일)
    c = pd.Series([100, 101, 102, 103, 104.0], idx)
    ev = events(c, 2, 1)
    assert list(ev.index) == [pd.Timestamp("2020-01-22")] and abs(ev.iloc[0] - (102 / 101 - 1)) < 1e-12
    print("selftest 통과")


if __name__ == "__main__":
    ap = argparse.ArgumentParser(); ap.add_argument("--selftest", action="store_true"); ap.add_argument("--confirm", action="store_true")
    ap.add_argument("--forward", action="store_true"); ap.add_argument("--judge", action="store_true")
    a = ap.parse_args()
    selftest() if a.selftest else (confirm() if a.confirm else (forward(a.judge) if a.forward else run()))
