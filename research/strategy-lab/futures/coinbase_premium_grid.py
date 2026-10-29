#!/usr/bin/env python3
"""코인베이스 프리미엄 — 진입·청산 점수대 40셀 격자. 사전등록 findings/coinbase-premium-grid-preregistration-2026-10.md.

    python research/strategy-lab/futures/coinbase_premium_grid.py
    python research/strategy-lab/futures/coinbase_premium_grid.py --selftest
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
import coinbase_premium_exit_rule as er  # noqa: E402  simulate·stats·monthly 그대로(955d188)
import coinbase_premium_robustness as rb  # noqa: E402
from short_horizon_study import tstat  # noqa: E402

ENTRIES = [1.0, 1.5, 2.0, 2.5, 3.0]
EXITS = {"T12": ("time", 12), "T24": ("time", 24), "T48": ("time", 48), "T72": ("time", 72),
         "Z1.0": ("z", 1.0), "Z0.5": ("z", 0.5), "Z0.0": ("z", 0.0), "Zm0.5": ("z", -0.5)}
BASE = (2.0, "T24")
OOS_FROM = er.TRAIN_END
MONTHS = pd.period_range("2023-01", "2026-09", freq="M")


def cells():
    return [(e, x) for e in ENTRIES for x in EXITS]


def run_cell(z, px, cell) -> pd.DataFrame:
    e, x = cell
    tr = er.simulate(z, px, EXITS[x], enter=lambda v, e=e: v >= e)
    return tr[tr.index < er.OOS_END]


def pick_cell(train: dict) -> tuple:
    order = list(EXITS)
    return max(train, key=lambda c: (train[c]["annual_net_bp"], -abs(c[0] - 2.0), EXITS[c[1]][0] == "time", -order.index(c[1])))


def name(c) -> str:
    return f"E{c[0]}·{c[1]}"


def main():
    cb, bn = (rb._read(cp.DATA / f"{n}.parquet") for n in ("cb_btc", "bn_btc"))
    up = rb._read(rb.ALTS / "upbit_btc.parquet")["open"]
    z = cp.zscore(cp.premium(cb, bn))
    first = max(z.first_valid_index(), up.index[0])
    z = z[z.index >= first]
    ty = (er.TRAIN_END - first).days / 365.25
    oy = (er.OOS_END - OOS_FROM).days / 365.25
    tr = {c: run_cell(z, up, c) for c in cells()}
    train = {c: er.stats(v[v.index < er.TRAIN_END], ty) for c, v in tr.items()}
    oos = {c: er.stats(v[v.index >= OOS_FROM], oy) for c, v in tr.items()}
    late = {c: er.stats(v[v.index >= pd.Timestamp("2025-01-01", tz="UTC")], (er.OOS_END - pd.Timestamp("2025-01-01", tz="UTC")).days / 365.25)
            for c, v in tr.items()}
    pick = pick_cell(train)
    diff = er.monthly(tr[pick], MONTHS) - er.monthly(tr[BASE], MONTHS)
    t_btc = tstat(diff.to_numpy())
    # 알트 24종 2023~ 차이
    per = []
    for coin in rb.COINS:
        c, b = rb._read(rb.ALTS / f"{coin}_cb.parquet"), rb._read(rb.ALTS / f"{coin}_bn.parquet")
        zc = cp.zscore(cp.premium(c, b))
        mm = MONTHS[MONTHS >= rb.month(zc.dropna().index[:1])[0]]
        if not len(mm):
            continue
        per.append((er.monthly(run_cell(zc, b["open"], pick), mm) - er.monthly(run_cell(zc, b["open"], BASE), mm)).rename(coin))
    alt = pd.concat(per, axis=1).mean(axis=1) if per else pd.Series(dtype=float)
    if pick == BASE:
        verdict = "지금 규칙 유지 (TRAIN 이 지금 규칙을 골랐다)"
    elif diff.mean() > 0 and t_btc >= 2 and alt.mean() > 0:
        verdict = "새 규칙 후보"
    elif diff.mean() > 0:
        verdict = "INCONCLUSIVE — 지금 규칙 유지"
    else:
        verdict = "REJECT — 지금 규칙 유지"
    oos_rank = sorted(oos, key=lambda c: -oos[c]["annual_net_bp"]).index(pick) + 1
    by_entry = {}
    for e in ENTRIES:
        best = max((c for c in cells() if c[0] == e), key=lambda c: train[c]["annual_net_bp"])
        by_entry[str(e)] = {"best_train_cell": name(best), "train_annual_bp": train[best]["annual_net_bp"], "oos_annual_bp": oos[best]["annual_net_bp"]}
    out = {"pick": name(pick), "verdict": verdict, "base": name(BASE),
           "confirm": {"btc_diff_monthly_bp": round(float(diff.mean()), 1), "btc_t": round(t_btc, 2),
                       "alts_2023on_diff_monthly_bp": round(float(alt.mean()), 1), "alts_t": round(tstat(alt.to_numpy()), 2),
                       "alts_months": int(len(alt))},
           "pick_train": train[pick], "base_train": train[BASE], "pick_oos": oos[pick], "base_oos": oos[BASE],
           "record": {"pick_oos_rank_of_40": oos_rank, "pick_2025on": late[pick], "base_2025on": late[BASE], "best_by_entry": by_entry,
                      "heatmap_train_annual_bp": {name(c): train[c]["annual_net_bp"] for c in cells()},
                      "heatmap_oos_annual_bp": {name(c): oos[c]["annual_net_bp"] for c in cells()},
                      "heatmap_2025on_annual_bp": {name(c): late[c].get("annual_net_bp") for c in cells()},
                      "trades_per_year_train": {name(c): train[c].get("per_year") for c in cells()},
                      "win_pct_oos": {name(c): oos[c].get("win_pct") for c in cells()},
                      "avg_hours_oos": {name(c): oos[c].get("avg_hours") for c in cells()}}}
    (HERE / "coinbase-premium-grid.json").write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
    print(json.dumps({k: out[k] for k in ("pick", "verdict", "confirm")}, ensure_ascii=False, indent=1))


def selftest():
    assert len(cells()) == 40 and BASE in cells()
    fake = {c: {"annual_net_bp": 100.0} for c in cells()}
    assert pick_cell(fake) == (2.0, "T12")                      # 동점 → E 2.0, 고정 시간, 짧은 보유
    fake[(3.0, "Zm0.5")] = {"annual_net_bp": 500.0}
    assert pick_cell(fake) == (3.0, "Zm0.5")                     # 최대값 우선
    idx = pd.date_range("2024-01-01", periods=100, freq="h", tz="UTC")
    z = pd.Series(0.0, index=idx); z.iloc[[5, 40]] = [1.2, 2.6]
    px = pd.Series(100.0, index=idx)
    assert len(run_cell(z, px, (1.0, "T24"))) == 2 and len(run_cell(z, px, (2.5, "T24"))) == 1 and len(run_cell(z, px, (3.0, "T24"))) == 0
    print("selftest 4/4 OK")


if __name__ == "__main__":
    selftest() if "--selftest" in sys.argv else main()
