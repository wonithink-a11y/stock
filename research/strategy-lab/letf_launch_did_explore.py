#!/usr/bin/env python3
"""LETF 상장(2026-05-27) 이중차분 탐색(E). 사전등록 findings/letf-launch-did-explore-prereg-2026-11.md

    python research/strategy-lab/letf_launch_did_explore.py            # 실행(야후 일봉, 수 초) — 결과를 JSON 으로 출력
    python research/strategy-lab/letf_launch_did_explore.py --selftest
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
from run_letf_reversal_forward import CTRL, TARGET, COST, MIN_CTRL   # noqa: E402 (동결된 forward 코드는 고치지 않고 상수만 쓴다)


def fetch_range(tickers: list[str], start: str) -> pd.DataFrame:
    import time
    import yfinance as yf
    for n in range(4):
        try:
            x = yf.download(tickers, start=start, auto_adjust=True, progress=False)["Close"]
            if isinstance(x, pd.Series):
                x = x.to_frame(tickers[0])
            x.index = pd.to_datetime(x.index).tz_localize(None)
            assert x.shape[0] > 100, "행 부족"                                       # 빈 응답을 성공으로 세지 않는다(교훈 81)
            return x
        except Exception:
            if n == 3:
                raise
            time.sleep(2 ** (n + 1))

PRE0, PRE1, POST0, SEED, NPERM = "2025-01-02", "2026-05-26", "2026-05-28", 20261128, 10000
GRID = (0.03, 0.02)


def event_rows(px: pd.DataFrame, smh: pd.Series, thr: float) -> pd.DataFrame:
    kr = px["^KS11"].dropna().index
    kr = kr[kr < pd.Timestamp.now(tz="Asia/Seoul").tz_localize(None).normalize()]
    ret, us, rows = px.pct_change(fill_method=None), smh.pct_change().dropna(), []
    for i in range(1, len(kr) - 1):
        t, prev, nxt = kr[i], kr[i - 1], kr[i + 1]
        d = us.index[us.index < t]
        if not len(d) or d[-1] < prev or abs(us[d[-1]]) < thr:
            continue
        for grp, mp in (("target", TARGET), ("ctrl", CTRL)):
            for tk, yt in mp.items():
                if yt in ret:
                    x, y = ret.at[t, yt] - ret.at[t, "^KS11"], ret.at[nxt, yt] - ret.at[nxt, "^KS11"]
                    if np.isfinite(x) and np.isfinite(y) and x != 0:
                        rows.append((t, tk, grp, -np.sign(x) * y))
    return pd.DataFrame(rows, columns=["t", "tk", "grp", "rev"])


def daily(df: pd.DataFrame) -> pd.DataFrame:
    P = df[df.grp == "target"].groupby("t")["rev"].mean()
    g = df[df.grp == "ctrl"].groupby("t")["rev"].agg(["mean", "count"])
    out = pd.DataFrame({"P": P}).join(g["mean"].where(g["count"] >= MIN_CTRL).rename("C")).dropna()
    out["D"] = out["P"] - out["C"]
    return out


def did(d: pd.DataFrame, col: str = "D") -> tuple[float, int, int]:
    pre, post = d.loc[PRE0:PRE1, col], d.loc[POST0:, col]
    return float(post.mean() - pre.mean()), len(pre), len(post)


def perm_p(d: pd.DataFrame, rng) -> float:
    pre, post = d.loc[PRE0:PRE1, "D"].to_numpy(), d.loc[POST0:, "D"].to_numpy()
    obs, allv, n = post.mean() - pre.mean(), np.r_[pre, post], len(pre)
    hit = 0
    for _ in range(NPERM):
        rng.shuffle(allv)
        hit += (allv[n:].mean() - allv[:n].mean()) >= obs
    return (hit + 1) / (NPERM + 1)


def analyse(px, smh, thr, rng) -> dict:
    df = event_rows(px, smh, thr)
    d = daily(df)
    est, npre, npost = did(d)
    post = d.loc[POST0:]
    half = len(post) // 2
    per_stock = {}
    for tk in TARGET:
        s = df[df.tk == tk].set_index("t")["rev"]
        c = df[df.grp == "ctrl"].groupby("t")["rev"].mean()
        dd = (s - c).dropna()
        per_stock[tk] = float(dd.loc[POST0:].mean() - dd.loc[PRE0:PRE1].mean())
    return {"thr": thr, "nPre": npre, "nPost": npost, "did": round(est, 6), "p": perm_p(d, rng),
            "postP": round(float(post["P"].mean()), 6), "postNet": round(float(post["P"].mean() - COST), 6),
            "preP": round(float(d.loc[PRE0:PRE1, "P"].mean()), 6), "postC": round(float(post["C"].mean()), 6),
            "perStockDiD": {k: round(v, 6) for k, v in per_stock.items()},
            "halves": [round(float(post["D"].iloc[:half].mean()), 6), round(float(post["D"].iloc[half:].mean()), 6)],
            "hitPost": round(float((post["P"] > 0).mean()), 3), "period": {
                "2025": round(float(d.loc["2025-01-01":"2025-12-31", "D"].mean()), 6),
                "2026H1": round(float(d.loc["2026-01-01":"2026-05-26", "D"].mean()), 6),
                "2026H2": round(float(d.loc["2026-05-28":, "D"].mean()), 6)}}


def selftest() -> int:
    d = pd.DataFrame({"D": np.r_[np.zeros(40), np.full(30, 0.01)], "P": 0.0, "C": 0.0},
                     index=pd.to_datetime(list(pd.date_range("2025-02-03", periods=40, freq="7D")) + list(pd.date_range("2026-06-01", periods=30, freq="5D"))))
    est, a, b = did(d)
    assert abs(est - 0.01) < 1e-12 and a == 40 and b == 30
    assert perm_p(d, np.random.default_rng(1)) < 0.001
    assert perm_p(d.assign(D=0.0), np.random.default_rng(1)) > 0.5
    print("selftest OK (3)")
    return 0


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--selftest", action="store_true")
    if ap.parse_args().selftest:
        return selftest()
    names = ["^KS11"] + list(TARGET.values()) + list(CTRL.values())
    px, smh = fetch_range(names, "2024-12-01"), fetch_range(["SMH"], "2024-12-01")["SMH"].dropna()
    rng = np.random.default_rng(SEED)
    res = [analyse(px, smh, thr, rng) for thr in GRID]
    sys.path.insert(0, str(HERE))
    from trials import bh_with_prior
    adj, ok, m = bh_with_prior([r["p"] for r in res], "kr", 0.10)
    for r, a, o in zip(res, adj, ok):
        r["bhAdj"], r["bhPass"], r["m"] = round(a, 4), bool(o), m
    print(json.dumps({"lastPrice": str(px.index[-1].date()), "results": res}, ensure_ascii=False, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
