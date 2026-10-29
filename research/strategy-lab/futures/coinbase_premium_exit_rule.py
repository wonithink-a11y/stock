#!/usr/bin/env python3
"""코인베이스 프리미엄 — 청산 규칙 비교. 사전등록 findings/coinbase-premium-exit-rule-preregistration-2026-10.md.

    python research/strategy-lab/futures/coinbase_premium_exit_rule.py             # 판정(자료는 coinbase_premium·robustness --collect 산출물)
    python research/strategy-lab/futures/coinbase_premium_exit_rule.py --selftest
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import coinbase_premium as cp  # noqa: E402
import coinbase_premium_robustness as rb  # noqa: E402
from short_horizon_study import tstat  # noqa: E402

COST = 10.0
MAX_HOLD = 72
CELLS = {"T4": ("time", 4), "T12": ("time", 12), "T24": ("time", 24), "T48": ("time", 48), "T72": ("time", 72),
         "Z1.5": ("z", 1.5), "Z1.0": ("z", 1.0), "Z0.5": ("z", 0.5), "Z0.0": ("z", 0.0), "Zm0.5": ("z", -0.5)}
TRAIN_END = pd.Timestamp("2023-01-01", tz="UTC")
OOS_END = pd.Timestamp("2026-10-01", tz="UTC")


def simulate(z: pd.Series, px: pd.Series, rule: tuple, enter=lambda v: v >= cp.ZTH) -> pd.DataFrame:
    """z·px 는 같은 1시간 격자. 롱만, 보유 중 새 진입 없음. 청산 가격이 없으면 그 진입을 건너뛴다."""
    zv, pv, idx = z.to_numpy(), px.reindex(z.index).to_numpy(), z.index
    kind, arg = rule
    rows, i, n = [], 0, len(zv)
    while i < n:
        if not (np.isfinite(zv[i]) and enter(zv[i]) and np.isfinite(pv[i])):
            i += 1
            continue
        if kind == "time":
            j = i + arg
        else:
            j = i + MAX_HOLD
            for k in range(1, MAX_HOLD + 1):
                if i + k < n and np.isfinite(zv[i + k]) and zv[i + k] <= arg:
                    j = i + k
                    break
        if j >= n or not np.isfinite(pv[j]):
            i += 1
            continue
        rows.append((idx[i], idx[j], j - i, (pv[j] / pv[i] - 1) * 1e4 - COST))
        i = j                                   # 판 시각부터 다시 진입 가능
    return pd.DataFrame(rows, columns=["entry", "exit", "hours", "net"]).set_index("entry")


def stats(tr: pd.DataFrame, years: float) -> dict:
    if not len(tr):
        return {"n": 0}
    x = tr["net"]
    return {"n": int(len(x)), "per_year": round(len(x) / years, 1), "annual_net_bp": round(float(x.sum() / years), 0),
            "mean_bp": round(float(x.mean()), 1), "win_pct": round(float((x > 0).mean() * 100), 1),
            "avg_hours": round(float(tr["hours"].mean()), 1), "t": round(tstat(x.to_numpy()), 2)}


def monthly(tr: pd.DataFrame, months: pd.PeriodIndex) -> pd.Series:
    m = tr["net"].groupby(rb.month(tr.index)).sum() if len(tr) else pd.Series(dtype=float)
    return m.reindex(months, fill_value=0.0)


def periods(tr: pd.DataFrame, first: pd.Timestamp) -> dict:
    cuts = {"TRAIN": (first, TRAIN_END), "2023": (TRAIN_END, pd.Timestamp("2024-01-01", tz="UTC")),
            "2024": (pd.Timestamp("2024-01-01", tz="UTC"), pd.Timestamp("2025-01-01", tz="UTC")),
            "2025~": (pd.Timestamp("2025-01-01", tz="UTC"), OOS_END)}
    return {k: stats(tr[(tr.index >= a) & (tr.index < b)], (b - a).days / 365.25) for k, (a, b) in cuts.items()}


def main():
    cb, bn = (rb._read(cp.DATA / f"{n}.parquet") for n in ("cb_btc", "bn_btc"))
    up = rb._read(rb.ALTS / "upbit_btc.parquet")["open"]
    z = cp.zscore(cp.premium(cb, bn))
    first = max(z.first_valid_index(), up.index[0])
    z = z[z.index >= first]
    tr = {k: simulate(z, up, r) for k, r in CELLS.items()}
    tr = {k: v[v.index < OOS_END] for k, v in tr.items()}
    train_years = (TRAIN_END - first).days / 365.25
    train = {k: stats(v[v.index < TRAIN_END], train_years) for k, v in tr.items()}
    order = list(CELLS)
    pick = max(order, key=lambda k: (train[k]["annual_net_bp"], CELLS[k][0] == "time", -order.index(k)))
    months = pd.period_range("2023-01", "2026-09", freq="M")
    diff = monthly(tr[pick], months) - monthly(tr["T24"], months)
    if pick == "T24":
        verdict = "24시간 유지 (TRAIN 이 24시간을 골랐다)"
    elif diff.mean() > 0 and tstat(diff.to_numpy()) >= 2:
        verdict = "새 청산 규칙 후보"
    elif diff.mean() > 0:
        verdict = "INCONCLUSIVE — 24시간 유지"
    else:
        verdict = "REJECT — 24시간 유지"
    out = {"first": str(first), "train_years": round(train_years, 2), "train": train, "pick": pick,
           "confirm": {"months": len(months), "diff_monthly_bp": round(float(diff.mean()), 1), "t": round(tstat(diff.to_numpy()), 2),
                       "pick_monthly_bp": round(float(monthly(tr[pick], months).mean()), 1),
                       "t24_monthly_bp": round(float(monthly(tr["T24"], months).mean()), 1)},
           "verdict": verdict, "record": {}}
    out["record"]["all_cells_by_period"] = {k: periods(v, first) for k, v in tr.items()}
    # 알트 24종 — 고른 셀 − T24 월별 차이(코인 평균)
    per = []
    for coin in rb.COINS:
        c, b = rb._read(rb.ALTS / f"{coin}_cb.parquet"), rb._read(rb.ALTS / f"{coin}_bn.parquet")
        zc = cp.zscore(cp.premium(c, b))
        a, t24 = simulate(zc, b["open"], CELLS[pick]), simulate(zc, b["open"], CELLS["T24"])
        a, t24 = a[a.index < OOS_END], t24[t24.index < OOS_END]
        mm = pd.period_range(rb.month(zc.dropna().index[:1])[0], "2026-09", freq="M")
        per.append((monthly(a, mm) - monthly(t24, mm)).rename(coin))
    alt = pd.concat(per, axis=1).mean(axis=1)
    out["record"]["alts_pick_minus_t24"] = {
        k: {"months": int(len(x)), "bp": round(float(x.mean()), 1), "t": round(tstat(x.to_numpy()), 2)}
        for k, x in (("all", alt), ("TRAIN", alt[alt.index < pd.Period("2023-01", "M")]), ("2023~", alt[alt.index >= pd.Period("2023-01", "M")]))}
    low = simulate(z, up, ("time", 24), enter=lambda v: v <= -cp.ZTH)
    out["record"]["buy_when_low_z24h"] = periods(low[low.index < OOS_END], first)
    (HERE / "coinbase-premium-exit-rule.json").write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
    print(json.dumps(out, ensure_ascii=False, indent=1))


def selftest():
    idx = pd.date_range("2024-01-01", periods=200, freq="h", tz="UTC")
    z = pd.Series(0.0, index=idx)
    px = pd.Series(100.0, index=idx)
    z.iloc[10] = 2.5                       # 진입
    z.iloc[11:15] = [1.8, 1.2, 0.8, -0.2]  # 1.5 이하는 11시간, 1.0 이하는 12시간, 0 이하는 14시간
    px.iloc[11:] = 101.0
    t = simulate(z, px, ("z", 1.5))                                 # z(11)=1.8 > 1.5, z(12)=1.2 ≤ 1.5 → 12시(2시간)
    assert t.index[0] == idx[10] and t["exit"].iloc[0] == idx[12] and t["hours"].iloc[0] == 2, t
    assert simulate(z, px, ("z", 1.0))["hours"].iloc[0] == 3       # z(13)=0.8
    assert simulate(z, px, ("z", 0.0))["hours"].iloc[0] == 4       # z(14)=−0.2
    z2 = z.copy(); z2.iloc[11:] = 2.2                               # 안 내려오면 72시간
    assert simulate(z2, px, ("z", 1.0))["hours"].iloc[0] == MAX_HOLD
    t24 = simulate(z, px, ("time", 24))
    assert len(t24) == 1 and abs(t24["net"].iloc[0] - (100 - COST)) < 1e-9   # +1% − 10bp
    z3 = pd.Series(2.5, index=idx)                                  # 계속 신호 → 겹치지 않고 연달아
    t3 = simulate(z3, px, ("time", 24))
    assert ((t3.index[1:] - t3.index[:-1]) >= pd.Timedelta(hours=24)).all() and len(t3) >= 7
    low = simulate(-z, px, ("time", 24), enter=lambda v: v <= -2)
    assert len(low) == 1
    print("selftest 7/7 OK")


if __name__ == "__main__":
    selftest() if "--selftest" in sys.argv else main()
