#!/usr/bin/env python3
"""HFEA(주식 3배 + 채권 3배) — 사전등록 findings/hfea-preregistration-2026-11.md"""
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
import tech_timing_3x as B  # noqa: E402

PER = {"2002-08~2012": ("2002-08-01", "2012-12-31"), "2013~2019": ("2013-01-01", "2019-12-31"), "2020~2026-11": ("2020-01-01", "2026-12-31")}
DRAG = 0.03 / 252


def load_tr(tk):
    f = B.CACHE / f"{tk}_tr.parquet"
    if f.exists():
        return pd.read_parquet(f)["Close"]
    import yfinance as yf
    d = yf.download(tk, start="2002-01-01", end="2026-11-07", progress=False, auto_adjust=True)
    d.columns = [c[0] if isinstance(c, tuple) else c for c in d.columns]
    d = d[["Close"]].dropna()
    d.index = pd.to_datetime(d.index).tz_localize(None)
    d.to_parquet(f)
    return d["Close"]


def sim(rs, rb, ke, kb, we, wb, filt, sig):
    n = len(rs)
    E, Bd, C = we, wb, 1 - we - wb
    on = True
    out = np.zeros(n)
    for i in range(n):
        if filt:
            ns = bool(sig[i])
            if ns != on:
                tot = E + Bd + C
                if not ns:
                    C += E
                    E = 0.0
                else:
                    mv = min(C, we * tot)
                    E += mv
                    C -= mv
                C -= 0.001 * (E if ns else C * 0)  # 전환 비용 근사(주식 슬리브 기준)
                on = ns
        pre = E + Bd + C
        E *= 1 + (ke * rs[i] - (DRAG if ke > 1 else 0))
        Bd *= 1 + (kb * rb[i] - (DRAG if kb > 1 else 0))
        post = E + Bd + C
        out[i] = post / pre - 1
        if i + 1 < n and (rs_idx[i].month in (3, 6, 9, 12)) and rs_idx[i + 1].month != rs_idx[i].month:
            tot = E + Bd + C
            E = (we * tot) if on else 0.0
            Bd = wb * tot
            C = tot - E - Bd
    return out


def metrics(r, idx, a, b):
    m = (idx >= a) & (idx <= b)
    x = r[m]
    eq = np.cumprod(1 + x)
    yrs = len(x) / 252
    pk = np.maximum.accumulate(np.concatenate([[1.0], eq]))[1:]
    return dict(cagr=round((eq[-1] ** (1 / yrs) - 1) * 100, 1), sharpe=round(x.mean() / x.std() * np.sqrt(252), 2), mdd=round((eq / pk - 1).min() * 100))


def main() -> int:
    global rs_idx
    spy, tlt = load_tr("SPY"), load_tr("TLT")
    df = pd.concat([spy, tlt], axis=1, join="inner").dropna()
    df.columns = ["SPY", "TLT"]
    df = df[(df.index >= "2002-08-01") & (df.index <= B.END)]
    rs_idx = df.index
    rs, rb = df["SPY"].pct_change().fillna(0).values, df["TLT"].pct_change().fillna(0).values
    sma200 = df["SPY"].rolling(200).mean()
    sig = (df["SPY"] > sma200).shift(1).fillna(True).values      # 전일 종가 신호
    S = {
        "SPY 1배": sim(rs, rb, 1, 1, 1.0, 0.0, False, sig),
        "60/40 (SPY/TLT) 분기": sim(rs, rb, 1, 1, 0.6, 0.4, False, sig),
        "SPY 3배 보유": sim(rs, rb, 3, 1, 1.0, 0.0, False, sig),
        "HFEA 55/45": sim(rs, rb, 3, 3, 0.55, 0.45, False, sig),
        "HFEA + SMA200 필터": sim(rs, rb, 3, 3, 0.55, 0.45, True, sig),
    }
    out = {k: {p: metrics(v, df.index, *rg) for p, rg in PER.items()} for k, v in S.items()}
    print("기간", df.index[0].date(), "~", df.index[-1].date())
    for k, v in out.items():
        print(f"{k:22s}", " | ".join(f"{p} {m['cagr']}/{m['mdd']}/{m['sharpe']}" for p, m in v.items()))
    ref = out["60/40 (SPY/TLT) 분기"]
    verdict = {}
    for k in ("HFEA 55/45", "HFEA + SMA200 필터"):
        verdict[k] = all(out[k][p]["sharpe"] >= ref[p]["sharpe"] and out[k][p]["mdd"] >= -50 for p in PER)
    print("INFORMATION 충족", verdict)
    out["_verdict"] = verdict
    (B.ROOT / "findings" / "hfea-results.json").write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main())
