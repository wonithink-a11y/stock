#!/usr/bin/env python3
"""코인베이스 프리미엄 알트 횡단면 → 다음 24시간. 사전등록 findings/coinbase-premium-xs-preregistration-2026-10.md.

    python research/strategy-lab/futures/coinbase_premium_xs.py             # 판정(새 수집 없음)
    python research/strategy-lab/futures/coinbase_premium_xs.py --selftest
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
import coinbase_premium as cp  # noqa: E402  premium·zscore·split·period (20401a4)
import coinbase_premium_robustness as rb  # noqa: E402
from short_horizon_study import null_bar, tstat  # noqa: E402

SEED = 20261107
H = pd.Timedelta(hours=1)
HALF, MIN_N = 5.0, 8
START, END = pd.Timestamp("2021-01-01", tz="UTC"), pd.Timestamp("2026-10-01", tz="UTC")


def panel() -> tuple[pd.DataFrame, pd.DataFrame]:
    zs, op = {}, {}
    for coin in rb.COINS:
        c, b = rb._read(rb.ALTS / f"{coin}_cb.parquet"), rb._read(rb.ALTS / f"{coin}_bn.parquet")
        zs[coin] = cp.zscore(cp.premium(c, b))
        op[coin] = b["open"]
    return pd.DataFrame(zs), pd.DataFrame(op)


def portfolio(z: pd.DataFrame, op: pd.DataFrame, delay: int = 0, frac: float = 1 / 3, long_only: bool = False) -> pd.DataFrame:
    days = pd.date_range(START, END - pd.Timedelta(days=1), freq="D")
    rows, prev = [], pd.Series(dtype=float)
    for T in days:
        if T not in z.index:
            continue
        zz = z.loc[T]
        p0, p1 = op.reindex([T + delay * H]).iloc[0], op.reindex([T + (delay + 24) * H]).iloc[0]
        ok = zz.notna() & p0.notna() & p1.notna()
        n = int(ok.sum())
        if n < MIN_N:
            prev = pd.Series(dtype=float)
            continue
        r = (p1[ok] / p0[ok] - 1)
        order = zz[ok].sort_values()
        k = math.ceil(n * frac)
        top, bot = order.index[-k:], order.index[:k]
        w = pd.Series(0.0, index=order.index)
        if long_only:
            w[top] += 1 / k
            w -= 1 / n
            gross = r[top].mean() - r.mean()
        else:
            w[top], w[bot] = 1 / k, -1 / k
            gross = r[top].mean() - r[bot].mean()
        turn = float((w.reindex(w.index.union(prev.index), fill_value=0) - prev.reindex(w.index.union(prev.index), fill_value=0)).abs().sum())
        rows.append((T, n, gross * 1e4, HALF * turn, (r[top].mean() - r.mean()) * 1e4, (r.mean() - r[bot].mean()) * 1e4))
        prev = w
    return pd.DataFrame(rows, columns=["T", "n", "gross", "cost", "long_leg", "short_leg"]).set_index("T")


def judge(f: pd.DataFrame, bar: float) -> dict:
    sp = f.index.map(cp.split)
    parts = {k: f[sp == k] for k in ("TRAIN", "VALID", "TEST")}
    tr = parts["TRAIN"]["gross"].to_numpy()
    s = int(np.sign(tr.mean())) or 1
    info = bool(abs(tstat(tr)) >= bar and all(len(parts[k]) and np.sign(parts[k]["gross"].mean()) == s for k in ("VALID", "TEST")))
    oos = f[sp != "TRAIN"]
    g = s * oos["gross"].to_numpy()
    n1, n2 = g - oos["cost"].to_numpy(), g - 2 * oos["cost"].to_numpy()
    eco = bool(info and n1.mean() > 0 and n2.mean() > 0)
    rob = bool(eco and tstat(n1) >= 2)
    rng = np.random.default_rng(SEED)
    ci = [round(float(np.percentile([rng.choice(g, len(g)).mean() for _ in range(2000)], q)), 1) for q in (2.5, 97.5)]
    v = "판정불가" if len(parts["TEST"]) < 20 else "ROBUST" if rob else "ECONOMIC" if eco else "INFORMATION" if info else "REJECT"
    return {"verdict": v, "sign": s, "t_train": round(tstat(tr), 2),
            **{k: {"days": int(len(x)), "coins_avg": round(float(x["n"].mean()), 1), "gross_bp": round(float(x["gross"].mean()), 1),
                   "t": round(tstat(x["gross"].to_numpy()), 2)} for k, x in parts.items()},
            "oos_gross_ci95": ci, "cost_bp_per_day": round(float(oos["cost"].mean()), 1), "net_bp": round(float(n1.mean()), 1),
            "net_stress_bp": round(float(n2.mean()), 1), "t_net": round(tstat(n1), 2),
            "breakeven_cost_multiple": round(float(g.mean() / oos["cost"].mean()), 2) if oos["cost"].mean() > 0 else None,
            "periods_bp": {k: {"n": int(len(x)), "bp": round(float(s * x["gross"].mean()), 1), "t": round(tstat(s * x["gross"].to_numpy()), 2)} for k, x in f.groupby(f.index.map(cp.period))},
            "yearly": {int(y): round(float(s * x["gross"].mean()), 1) for y, x in f.groupby(f.index.year)},
            "legs_bp": {k: {"long_minus_ew": round(float(x["long_leg"].mean()), 1), "ew_minus_short": round(float(x["short_leg"].mean()), 1)} for k, x in parts.items()}}


def brief(f: pd.DataFrame) -> dict:
    return {k: {"days": int(len(x)), "bp": round(float(x["gross"].mean()), 1), "t": round(tstat(x["gross"].to_numpy()), 2), "cost": round(float(x["cost"].mean()), 1)}
            for k, x in f.groupby(f.index.map(cp.split))}


def main():
    z, op = panel()
    f = portfolio(z, op)
    rng = np.random.default_rng(SEED)
    bar = null_bar([f[f.index.map(cp.split) == "TRAIN"]["gross"].to_numpy()], rng)
    out = {"bar": round(bar, 2), "coins": list(rb.COINS), "X1": judge(f, bar)}
    out["record"] = {"delay1h": brief(portfolio(z, op, delay=1)), "long_only_top_minus_ew": brief(portfolio(z, op, long_only=True)),
                     "halves": brief(portfolio(z, op, frac=0.5))}
    (HERE / "coinbase-premium-xs.json").write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
    print(json.dumps(out, ensure_ascii=False, indent=1))


def selftest():
    ok = 0
    T0 = pd.Timestamp("2022-01-01", tz="UTC")
    hrs = pd.date_range(T0, periods=72, freq="h")
    coins = [f"C{i}" for i in range(9)]
    z = pd.DataFrame({c: float(i) for i, c in enumerate(coins)}, index=hrs)
    op = pd.DataFrame({c: 100.0 for c in coins}, index=hrs)
    op.loc[T0 + 24 * H, "C8"] = 110.0                                  # 최상위 z 코인 +10%
    op.loc[T0 + 24 * H, "C0"] = 95.0                                   # 최하위 −5%
    global START, END
    s0, e0 = START, END
    START, END = T0, T0 + pd.Timedelta(days=2)
    try:
        f = portfolio(z, op)
        assert len(f) == 2 and f["n"].iloc[0] == 9 and f["cost"].iloc[1] == 0.0; ok += 1   # 둘째 날 비중 그대로 → 비용 0
        assert abs(f["gross"].iloc[0] - ((0.10 / 3) - (-0.05 / 3)) * 1e4) < 1e-6; ok += 1   # k=3 등가중
        assert abs(f["cost"].iloc[0] - HALF * 2.0) < 1e-9; ok += 1                # 첫날 진입: 비중 합 2
        z2 = z.copy(); z2.loc[T0, "C8"] = np.nan; z2.loc[T0, "C7"] = np.nan
        f2 = portfolio(z2, op)
        assert T0 not in f2.index and abs(f2["cost"].iloc[0] - HALF * 2.0) < 1e-9; ok += 1   # 7개 → 그날 없음, 다음 날 새 진입
    finally:
        START, END = s0, e0
    print(f"selftest {ok}/4 OK")


if __name__ == "__main__":
    if "--selftest" in sys.argv:
        selftest()
    else:
        main()
