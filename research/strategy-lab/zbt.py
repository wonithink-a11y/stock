"""ZBT(츠바이크 브레스 쓰러스트) 대용 — 사전등록 findings/zbt-preregistration-2026-11.md 그대로.

  python research/strategy-lab/zbt.py --selftest
  python research/strategy-lab/zbt.py            # 과거 구간 계산 + 건수·결과 표 출력
  python research/strategy-lab/zbt.py --judge    # n(과거+forward) < 8 이면 거부(사전등록 §6)

입력: data/us-pit/panel/prices.parquet(gitignore) · FRED SP500(fredgraph.csv, 2016-11-21~).
forward = 사전등록일(2026-11-23) 뒤 신호일. 패널이 그 뒤로 갱신돼야 셀 수 있다.
"""
import argparse, io, sys, urllib.request
from pathlib import Path
import numpy as np
import pandas as pd

HERE = Path(__file__).parent
PANEL = HERE / "data/us-pit/panel/prices.parquet"
FRED = "https://fred.stlouisfed.org/graph/fredgraph.csv?id=SP500"
LOW, HIGH, WIN, GAP, H = 0.40, 0.615, 10, 126, 63
NULL_N, SEED, COST = 1000, 20261123, 0.0005
START, PREREG = pd.Timestamp("2016-11-21"), pd.Timestamp("2026-11-23")
JUDGE_N = 8


def breadth(panel):
    p = panel.sort_values(["ticker", "start", "date"]).copy()
    p["ret"] = p.groupby(["ticker", "start"])["close"].pct_change()
    m = p[p["member"]].drop_duplicates(["ticker", "date"])
    up = (m["ret"] > 0).groupby(m["date"]).sum()
    dn = (m["ret"] < 0).groupby(m["date"]).sum()
    return (up / (up + dn)).dropna()


def ema10(r):
    a = 2 / (WIN + 1)
    v = r.to_numpy(float)
    e = np.full(len(v), np.nan)
    if len(v) < WIN:
        return pd.Series(e, r.index)
    e[WIN - 1] = v[:WIN].mean()
    for i in range(WIN, len(v)):
        e[i] = a * v[i] + (1 - a) * e[i - 1]
    return pd.Series(e, r.index)


def signals(e):
    """t0: E<0.40, t0+1..t0+10 안에 E>0.615 첫 날 = 신호. 직전 신호와 126거래일 미만이면 버림."""
    v, idx, out, last = e.to_numpy(), e.index, [], -10**9
    for t0 in range(len(v)):
        if not (v[t0] < LOW):
            continue
        for t1 in range(t0 + 1, min(t0 + WIN, len(v) - 1) + 1):
            if v[t1] > HIGH:
                if t1 - last >= GAP:
                    out.append(idx[t1]); last = t1
                break
    return out


def fwd_ret(px, d, h):
    i = px.index.searchsorted(d)
    if i >= len(px) or px.index[i] != d or i + h >= len(px):
        return np.nan
    return px.iloc[i + h] / px.iloc[i] - 1


def null_dist(px, n, rng):
    days = px.index[: len(px) - H]
    means = []
    while len(means) < NULL_N:
        pick = np.sort(rng.choice(len(days), n, replace=False))
        if n > 1 and np.diff(pick).min() < GAP:
            continue
        means.append(np.mean([px.iloc[i + H] / px.iloc[i] - 1 for i in pick]))
    return np.array(means)


def load_sp500():
    raw = urllib.request.urlopen(FRED, timeout=30).read().decode()
    s = pd.read_csv(io.StringIO(raw), na_values=".")
    s = s.set_index(pd.to_datetime(s.iloc[:, 0])).iloc[:, 1].dropna()
    return s[s.index >= START]


def verdict(n, sig_mean, pct, pos_share, net_mean, null_mean):
    if n < 5:
        return "INCONCLUSIVE"
    if pct < 95:
        return "REJECT"
    if pos_share < 0.6:
        return "REJECT"
    return "ECONOMIC" if net_mean > null_mean else "INFORMATION"


def run(judge=False):
    panel = pd.read_parquet(PANEL)
    r = breadth(panel)
    e = ema10(r)
    sig = [d for d in signals(e) if d >= START]
    px = load_sp500()
    past = [d for d in sig if d < PREREG]
    fwd = [d for d in sig if d >= PREREG]
    print(f"패널 {r.index.min().date()}~{r.index.max().date()} · SP500 {px.index.min().date()}~{px.index.max().date()}")
    print(f"E10 min {e.min():.3f} max {e.max():.3f} · <0.40 일수 {(e < LOW).sum()} · >0.615 일수 {(e > HIGH).sum()}")
    print(f"신호 과거 {len(past)} · forward {len(fwd)}")
    if judge and len(sig) < JUDGE_N:
        raise SystemExit(f"--judge 거부: n={len(sig)} < {JUDGE_N} (사전등록 §6)")
    rows = []
    for d in sig:
        rows.append({"date": d.date(), "E": round(e[d], 3),
                     **{f"r{h}": fwd_ret(px, d, h) for h in (21, 63, 126, 252)}})
    tab = pd.DataFrame(rows)
    if len(tab):
        print(tab.to_string(index=False, float_format=lambda x: f"{x:+.4f}"))
    done = tab.dropna(subset=["r63"]) if len(tab) else tab
    n = len(done)
    if n == 0:
        print("63거래일 완료 신호 0건 → INCONCLUSIVE"); return
    nd = null_dist(px, n, np.random.default_rng(SEED))
    m = done["r63"].mean()
    pct = (nd < m).mean() * 100
    pos = (done["r63"] > 0).mean()
    print(f"n={n} · 신호 평균 63일 {m:+.4f} · 귀무 평균 {nd.mean():+.4f} (95백분위 {np.percentile(nd, 95):+.4f}) · "
          f"백분위 {pct:.1f} · 양수 비율 {pos:.0%} · net {m - COST:+.4f} · 손익분기 {(m - nd.mean()) * 1e4:+.0f}bp")
    print("판정(규칙):", verdict(n, m, pct, pos, m - COST, nd.mean()))


def selftest():
    e = pd.Series([0.5] * 10 + [0.35, 0.5, 0.62, 0.7] + [0.5] * 200 + [0.3, 0.62] + [0.5] * 10,
                  index=pd.bdate_range("2020-01-01", periods=226))
    s = signals(e)
    assert len(s) == 2 and s[0] == e.index[12] and s[1] == e.index[215], s
    e2 = e.copy(); e2.iloc[115] = 0.3; e2.iloc[116] = 0.7  # 126일 안의 두 번째 신호는 버림
    assert signals(e2) == [e.index[12], e.index[215]], signals(e2)
    near = pd.Series([0.5] * 10 + [0.35] + [0.5] * 10 + [0.7], index=pd.bdate_range("2020-01-01", periods=22))
    assert signals(near) == [], "10거래일 넘어 도달하면 신호 아님"
    x = pd.Series(np.r_[np.ones(10) * 0.5, 1.0])
    assert abs(ema10(x).iloc[-1] - (0.5 + 2 / 11 * 0.5)) < 1e-12
    pnl = pd.DataFrame({"date": pd.to_datetime(["2020-01-01", "2020-01-02"] * 3),
                        "close": [10, 11, 10, 9, 10, 10], "ticker": ["A", "A", "B", "B", "C", "C"],
                        "start": "x", "member": True})
    b = breadth(pnl)
    assert len(b) == 1 and b.iloc[0] == 0.5  # 상승1 하락1 보합1(제외)
    assert verdict(4, 1, 99, 1, 1, 0) == "INCONCLUSIVE" and verdict(5, 1, 90, 1, 1, 0) == "REJECT"
    assert verdict(5, 1, 96, 0.5, 1, 0) == "REJECT" and verdict(5, 1, 96, 0.8, 1, 0) == "ECONOMIC"
    print("selftest 통과")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--selftest", action="store_true")
    ap.add_argument("--judge", action="store_true")
    a = ap.parse_args()
    selftest() if a.selftest else run(a.judge)
