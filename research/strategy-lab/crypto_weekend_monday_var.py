#!/usr/bin/env python3
"""주말 크립토 변동성 → 월요일 SPY 변동성. 사전등록 findings/crypto-weekend-monday-var-preregistration-2026-11.md

    python research/strategy-lab/crypto_weekend_monday_var.py            # 결과 JSON + 요약 (수 초, SPY·GLD·TLT 는 yfinance 공개)
    python research/strategy-lab/crypto_weekend_monday_var.py --selftest

y = ln Parkinson 분산(월요일). HAR(전 거래일·5일·22일) + 주말 크립토 요인 F(expanding z). (a) POST OLS 의 F 계수 단측 HAC p, (b) expanding OOS QLIKE + DM. 기록 전용.
"""
from __future__ import annotations

import argparse
import json
import math
import sys
from pathlib import Path

import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
CRYPTO = HERE / "data" / "crypto" / "daily-binance-ohlcv"
OUT_JSON = HERE / "findings" / "crypto-weekend-monday-var-results.json"
COINS, POST_START, FIRST_OBS, NW_LAG, ALPHA, ALPHA_OOS = ("BTCUSDT", "ETHUSDT", "XRPUSDT"), "2024-01-01", "2021-10-01", 4, 0.05 / 12, 0.05
K = 4 * math.log(2)


def pk(h, l):
    return np.log(h / l) ** 2 / K


def pnorm_upper(z: float) -> float:
    return 0.5 * math.erfc(z / math.sqrt(2))


def hac_se(X, e, lag=NW_LAG):
    n = len(e)
    XtXi = np.linalg.inv(X.T @ X)
    S = (X * e[:, None]).T @ (X * e[:, None])
    for l in range(1, lag + 1):
        w = 1 - l / (lag + 1)
        G = (X[l:] * e[l:, None]).T @ (X[:-l] * e[:-l, None])
        S += w * (G + G.T)
    return np.sqrt(np.diag(XtXi @ S @ XtXi))


def build(target: pd.DataFrame, crypto: dict[str, pd.DataFrame], friday=False, coins=COINS) -> pd.DataFrame:
    v = pk(target["High"], target["Low"]).dropna()
    v = v[v > 0]
    idx = v.index
    cv = {c: pk(crypto[c]["high"], crypto[c]["low"]) for c in coins}
    rows = []
    for i in range(22, len(idx)):
        t = idx[i]
        if t.weekday() != 0 or t < pd.Timestamp("2020-12-01"):
            continue
        days = [t - pd.Timedelta(days=3)] if friday else [t - pd.Timedelta(days=2), t - pd.Timedelta(days=1)]   # 직전 금요일 / 직전 토·일 (UTC 일봉)
        try:
            f = np.mean([np.log(np.mean([cv[c][d] for d in days])) for c in coins])
        except KeyError:
            continue
        rows.append(dict(date=t, y=np.log(v.iloc[i]), d=np.log(v.iloc[i - 1]), w=np.log(v.iloc[i - 5:i].mean()), m=np.log(v.iloc[i - 22:i].mean()), Fraw=f))
    D = pd.DataFrame(rows).reset_index(drop=True)
    mu = D.Fraw.expanding().mean().shift(1)
    sd = D.Fraw.expanding().std().shift(1)
    D["F"] = (D.Fraw - mu) / sd
    D.loc[D.index < 52, "F"] = np.nan                                                    # 직전 52주 미만이면 요인 없음
    return D.dropna(subset=["F"]).reset_index(drop=True)


def evaluate(D: pd.DataFrame) -> dict:
    post = D.date >= pd.Timestamp(POST_START)
    Xc = ["d", "w", "m"]
    P = D[post]
    X = np.column_stack([np.ones(len(P))] + [P[c] for c in Xc] + [P.F])
    b = np.linalg.lstsq(X, P.y.to_numpy(), rcond=None)[0]
    e = P.y.to_numpy() - X @ b
    se = hac_se(X, e)
    g, tg = float(b[-1]), float(b[-1] / se[-1])
    out = dict(nPost=int(post.sum()), nPre=int((~post).sum()), g=round(g, 4), gHacT=round(tg, 2), pGreater=round(pnorm_upper(tg), 5),
               pctPerSd=round((math.exp(g) - 1) * 100, 1), ci95=[round(g - 1.96 * se[-1], 4), round(g + 1.96 * se[-1], 4)])
    # OOS QLIKE: 각 POST 월요일에 이전 모든 관측으로 적합
    dl = []
    for i in np.nonzero(post.to_numpy())[0]:
        tr = D.iloc[:i]
        if len(tr) < 60:
            continue
        def fit(cols):
            Xt = np.column_stack([np.ones(len(tr))] + [tr[c] for c in cols])
            bt = np.linalg.lstsq(Xt, tr.y.to_numpy(), rcond=None)[0]
            sm = np.mean(np.exp(tr.y.to_numpy() - Xt @ bt))
            xr = np.array([1.0] + [D.iloc[i][c] for c in cols])
            return math.exp(float(xr @ bt)) * sm
        y = math.exp(D.iloc[i].y)
        def ql(f):
            r = y / f
            return r - math.log(r) - 1
        dl.append(ql(fit(Xc)) - ql(fit(Xc + ["F"])))
    dl = np.array(dl)
    if len(dl) > 20:
        Xd = np.ones((len(dl), 1))
        se_d = hac_se(Xd, dl - dl.mean())[0]
        tdm = float(dl.mean() / se_d)
        out.update(nOos=len(dl), qlikeGain=round(float(dl.mean()), 5), dmT=round(tdm, 2), pOos=round(pnorm_upper(tdm), 5))
    return out


def verdict(r) -> str:
    a = r["g"] > 0 and r["pGreater"] <= ALPHA
    b = r.get("qlikeGain", 0) > 0 and r.get("pOos", 1) <= ALPHA_OOS
    if a and b:
        return "신호 있음"
    if a or b:
        return "INFORMATION"
    return "REJECT"


def selftest() -> int:
    ok = 0
    rng = np.random.default_rng(1)
    n = 260
    dates = pd.bdate_range("2021-09-06", periods=n * 5)[::5][:n]                            # 월요일들
    def make(gt):
        F = rng.normal(0, 1, n)
        ar = np.zeros(n)
        for i in range(1, n):
            ar[i] = 0.5 * ar[i - 1] + rng.normal(0, 0.3)
        y = -9 + ar + gt * F + rng.normal(0, 0.3, n)
        D = pd.DataFrame(dict(date=dates, y=y, d=np.r_[y[0], y[:-1]], w=pd.Series(y).rolling(5, min_periods=1).mean().shift(1).bfill().to_numpy(),
                              m=pd.Series(y).rolling(22, min_periods=1).mean().shift(1).bfill().to_numpy(), F=F))
        return D[D.date >= "2021-10-01"].reset_index(drop=True)
    r = evaluate(make(0.4))
    assert r["g"] > 0.2 and r["pGreater"] < 0.001 and r["qlikeGain"] > 0 and verdict(r) == "신호 있음", r; ok += 1       # 심은 효과는 잡힌다
    r0 = evaluate(make(0.0))
    assert verdict(r0) != "신호 있음", r0; ok += 1                                                                  # 심지 않으면 안 잡힌다
    assert abs(pnorm_upper(0) - 0.5) < 1e-12 and pnorm_upper(3) < 0.0014; ok += 1
    print(f"selftest OK ({ok})")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--selftest", action="store_true")
    if ap.parse_args().selftest:
        return selftest()
    import yfinance as yf
    def ohlc(tk):
        x = yf.download(tk, start="2020-06-01", auto_adjust=False, progress=False)
        x.columns = x.columns.get_level_values(0)
        x = x[["High", "Low"]].dropna()
        assert len(x) > 1000, f"{tk} 행 {len(x)}"                                           # 빈 응답을 성공으로 세지 않는다(교훈 81)
        return x
    crypto = {c: pd.read_parquet(CRYPTO / f"{c}.parquet") for c in COINS}
    for c in crypto:
        crypto[c].index = pd.to_datetime(crypto[c].index).normalize()
    out = {}
    spy = ohlc("SPY")
    D = build(spy, crypto)
    r = evaluate(D)
    out["SPY(판정)"] = dict(result=r, signal=verdict(r))
    print("SPY(판정):", r, "→", verdict(r), f"| 표본 {D.date.min().date()}~{D.date.max().date()} {len(D)}주")
    pre = D[D.date < pd.Timestamp(POST_START)]
    Xp = np.column_stack([np.ones(len(pre))] + [pre[c] for c in ("d", "w", "m", "F")])
    bp = np.linalg.lstsq(Xp, pre.y.to_numpy(), rcond=None)[0]
    sep = hac_se(Xp, pre.y.to_numpy() - Xp @ bp)
    out["PRE 구간 g(기록)"] = dict(n=len(pre), g=round(float(bp[-1]), 4), hacT=round(float(bp[-1] / sep[-1]), 2))
    print("PRE:", out["PRE 구간 g(기록)"])
    rec = {}
    for nm in ("GLD", "TLT"):
        Dx = build(ohlc(nm), crypto)
        rec[nm] = evaluate(Dx)
    rec["금요일 크립토 요인(SPY)"] = evaluate(build(spy, crypto, friday=True))
    for c in COINS:
        rec[f"{c} 단독(SPY)"] = evaluate(build(spy, crypto, coins=(c,)))
    out["기록전용"] = rec
    for k, v in rec.items():
        print("기록", k, {a: v[a] for a in ("g", "gHacT", "pGreater", "qlikeGain", "pOos") if a in v})
    OUT_JSON.write_text(json.dumps(out, ensure_ascii=False, indent=1, default=float), encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main())
