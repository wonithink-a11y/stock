#!/usr/bin/env python3
"""알트 거래량 충격 횡단면 → 다음 1주. 사전등록 findings/crypto-volume-premium-preregistration-2026-10.md.

    python research/strategy-lab/futures/crypto_volume_premium.py             # 판정(새 수집 없음)
    python research/strategy-lab/futures/crypto_volume_premium.py --selftest
"""
from __future__ import annotations

import json
import math
import sys
from pathlib import Path

import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import coinbase_premium as cp  # noqa: E402
import coinbase_premium_robustness as rb  # noqa: E402
from coinbase_premium_xs import judge  # noqa: E402  (546525a 동결본 — 열 이름 gross·cost·n·long_leg·short_leg 공유)
from crypto_rv_jump import _ms, _read_zip  # noqa: E402
from short_horizon_study import null_bar, tstat  # noqa: E402

SEED = 20261108
HALF, MIN_N, BASE_W, MIN_BARS = 5.0, 8, 8, 150
START, END = pd.Timestamp("2020-01-05", tz="UTC"), pd.Timestamp("2026-10-01", tz="UTC")
BASES = sorted({f.name.split("USDT-1h")[0] for f in (rb.ALTS / "raw").glob("*USDT-1h-*.zip")})


def load(base: str) -> pd.DataFrame:
    fr = []
    for f in sorted((rb.ALTS / "raw").glob(f"{base}USDT-1h-*.zip")):
        d = _read_zip(f)
        fr.append(pd.DataFrame({"open": d[1].to_numpy(float), "qv": d[7].to_numpy(float)}, index=_ms(d[0])))
    df = pd.concat(fr).sort_index()
    return df[~df.index.duplicated(keep="last")]


def weekly(df: pd.DataFrame, weeks: pd.DatetimeIndex) -> pd.DataFrame:
    """주 시작 W_k → open(W_k), Q_k = [W_{k−1}, W_k) 거래대금 합(봉 150개 이상)."""
    wk = df.index.floor("D") - pd.to_timedelta((df.index.dayofweek + 1) % 7, unit="D")   # 그 봉이 속한 주의 일요일
    g = df["qv"].groupby(wk)
    q = g.sum().where(g.count() >= MIN_BARS)
    q.index = q.index + pd.Timedelta(weeks=1)                     # [W, W+1주) 합 → W+1 주 시작에 알려짐
    return pd.DataFrame({"open": df["open"].reindex(weeks), "Q": q.reindex(weeks)}, index=weeks)


def shock(Q: pd.Series) -> pd.Series:
    base = Q.shift(1).rolling(BASE_W, min_periods=BASE_W).mean()
    return np.log(Q / base)


def portfolio(v: pd.DataFrame, op: pd.DataFrame, hold: int = 1, frac: float = 1 / 3, long_only: bool = False, step: int = 1) -> pd.DataFrame:
    rows, prev = [], pd.Series(dtype=float)
    weeks = v.index[(v.index >= START)]
    for i in range(0, len(weeks), step):
        W = weeks[i]
        W2 = W + pd.Timedelta(weeks=hold)
        if W2 > END:
            break
        p0, p1 = op.loc[W], op.reindex([W2]).iloc[0]
        ok = v.loc[W].notna() & p0.notna() & p1.notna()
        n = int(ok.sum())
        if n < MIN_N:
            prev = pd.Series(dtype=float)
            continue
        r = p1[ok] / p0[ok] - 1
        order = v.loc[W][ok].sort_values()
        m = math.ceil(n * frac)
        top, bot = order.index[-m:], order.index[:m]
        w = pd.Series(0.0, index=order.index)
        if long_only:
            w[top] += 1 / m
            w -= 1 / n
            gross = r[top].mean() - r.mean()
        else:
            w[top], w[bot] = 1 / m, -1 / m
            gross = r[top].mean() - r[bot].mean()
        u = w.index.union(prev.index)
        turn = float((w.reindex(u, fill_value=0) - prev.reindex(u, fill_value=0)).abs().sum())
        rows.append((W, n, gross * 1e4, HALF * turn, (r[top].mean() - r.mean()) * 1e4, (r.mean() - r[bot].mean()) * 1e4))
        prev = w
    return pd.DataFrame(rows, columns=["T", "n", "gross", "cost", "long_leg", "short_leg"]).set_index("T")


def brief(f: pd.DataFrame) -> dict:
    return {k: {"weeks": int(len(x)), "bp": round(float(x["gross"].mean()), 1), "t": round(tstat(x["gross"].to_numpy()), 2), "cost": round(float(x["cost"].mean()), 1)}
            for k, x in f.groupby(f.index.map(cp.split))}


def main():
    weeks = pd.date_range(pd.Timestamp("2017-12-31", tz="UTC"), END, freq="W-SUN")
    v, op = {}, {}
    for b in BASES:
        w = weekly(load(b), weeks)
        v[b], op[b] = shock(w["Q"]), w["open"]
    v, op = pd.DataFrame(v), pd.DataFrame(op)
    f = portfolio(v, op)
    rng = np.random.default_rng(SEED)
    bar = null_bar([f[f.index.map(cp.split) == "TRAIN"]["gross"].to_numpy()], rng)
    out = {"bar": round(bar, 2), "coins": BASES, "V1": judge(f, bar)}
    past = op / op.shift(1) - 1
    rc = [v.loc[W].rank().corr(past.loc[W].rank()) for W in f.index if v.loc[W].notna().sum() >= MIN_N]
    out["record"] = {"hold2w_biweekly": brief(portfolio(v, op, hold=2, step=2)), "long_only_top_minus_ew": brief(portfolio(v, op, long_only=True)),
                     "rankcorr_shock_vs_lastweek_ret": round(float(np.nanmean(rc)), 3)}
    (HERE / "crypto-volume-premium.json").write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
    print(json.dumps(out, ensure_ascii=False, indent=1))


def selftest():
    ok = 0
    hrs = pd.date_range("2024-01-07", periods=24 * 21, freq="h", tz="UTC")          # 일요일 시작 3주
    df = pd.DataFrame({"open": 1.0, "qv": 1.0}, index=hrs)
    df.loc[df.index >= pd.Timestamp("2024-01-14", tz="UTC"), "qv"] = 2.0
    weeks = pd.date_range("2024-01-07", "2024-02-04", freq="W-SUN", tz="UTC")
    w = weekly(df, weeks)
    assert np.isnan(w.loc[pd.Timestamp("2024-01-07", tz="UTC"), "Q"]); ok += 1           # 그 전 주 자료 없음
    assert w.loc[pd.Timestamp("2024-01-14", tz="UTC"), "Q"] == 168.0 and w.loc[pd.Timestamp("2024-01-21", tz="UTC"), "Q"] == 336.0; ok += 1
    Q = pd.Series([1.0] * 8 + [2.0], index=pd.date_range("2024-01-07", periods=9, freq="W-SUN", tz="UTC"))
    assert abs(shock(Q).iloc[-1] - np.log(2.0)) < 1e-12 and np.isnan(shock(Q).iloc[-2]); ok += 1   # 8주 기준, 현재 제외
    print(f"selftest {ok}/3 OK")


if __name__ == "__main__":
    if "--selftest" in sys.argv:
        selftest()
    else:
        main()
