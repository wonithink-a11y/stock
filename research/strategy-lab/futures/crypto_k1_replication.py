#!/usr/bin/env python3
"""K1 롱숏 쏠림 역행 — 다른 코인 재현 1차 판정 (사전등록 findings/crypto-k1-replication-preregistration-2026-09.md).

신호 정의(pct_prev·seq·aggregate)는 crypto_positioning_study / crypto_short_horizon 에서 import — 재구현하지 않는다.
  python research/strategy-lab/futures/crypto_k1_replication.py
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from crypto_positioning_study import pct_prev  # noqa: E402
from crypto_short_horizon import COST_N, DATA, aggregate, seq, split  # noqa: E402
from short_horizon_study import tstat  # noqa: E402

K1 = DATA / "k1"
HOLD = 12
LIQ_USD = 20e6
SEED = 20260929


def coin_frame(sym):
    p = pd.read_parquet(K1 / "mark1h" / f"{sym}.parquet")
    p.index = pd.to_datetime(p["open_time"].astype("int64"), unit="ms", utc=True)
    f = pd.DataFrame({"p": p["mark_open"].astype(float)})
    f = f[~f.index.duplicated()].sort_index().asfreq("1h")
    m = pd.read_parquet(K1 / "metrics" / f"{sym}.parquet")
    m["t"] = pd.to_datetime(m["create_time"], utc=True)
    m = m.drop_duplicates("t").set_index("t").sort_index()
    for c in ("sum_open_interest_value", "count_toptrader_long_short_ratio"):
        m[c] = pd.to_numeric(m[c], errors="coerce")
    m["liq"] = m["sum_open_interest_value"].rolling("30D").median()          # 직전 30일(T 포함) 5분값 중앙값 — 과거만
    j = pd.merge_asof(pd.DataFrame({"t": f.index}), m[["count_toptrader_long_short_ratio", "liq"]].reset_index(),
                      on="t", direction="backward", tolerance=pd.Timedelta("1h")).set_index("t")
    return f, j


def main():
    u = json.loads((K1 / "_universe.json").read_text(encoding="utf-8"))
    have = [s for s in u["kept"] if (K1 / "metrics" / f"{s}.parquet").exists() and (K1 / "mark1h" / f"{s}.parquet").exists()]
    events, tagged, used = [], [], []
    for sym in have:
        f, j = coin_frame(sym)
        g4 = f.index.hour % 4 == 0
        grid = f.index[g4]
        ls_p = pct_prev(j.loc[grid, "count_toptrader_long_short_ratio"]).reindex(f.index).to_numpy()
        liq = j["liq"].to_numpy()
        cond = g4 & (liq >= LIQ_USD) & ((ls_p > 0.9) | (ls_p < 0.1))
        if not cond.any():
            continue
        used.append(sym)
        ev = seq(f, cond, np.where(ls_p > 0.9, -1.0, 1.0), HOLD)
        events += ev
        liq_s = pd.Series(liq, index=f.index)
        delisted = f["p"].last_valid_index() < pd.Timestamp("2026-09-01", tz="UTC")
        tagged += [(t, v, sym, float(liq_s.get(t, np.nan)), delisted) for t, v in ev]
    s = aggregate(events)
    parts = {k: v.to_numpy() for k, v in s.groupby(s.index.map(split))}
    x = s.to_numpy()
    rng = np.random.default_rng(SEED)
    ci = [float(np.percentile([rng.choice(x, len(x)).mean() for _ in range(2000)], q)) for q in (2.5, 97.5)]
    pos_parts = sum(1 for k in ("TRAIN", "VALID", "TEST") if k in parts and parts[k].mean() > 0)
    rep = len(x) >= 200 and x.mean() > 0 and tstat(x) >= 2.0 and pos_parts >= 2
    eco = rep and (x - COST_N).mean() > 0 and (x - 2 * COST_N).mean() > 0
    rob = eco and tstat(x - COST_N) >= 2.0
    verdict = "판정불가" if len(x) < 200 else ("ROBUST" if rob else "ECONOMIC" if eco else "REPLICATED" if rep else "NOT REPLICATED")
    tg = pd.DataFrame(tagged, columns=["t", "v", "sym", "liq", "delisted"])
    tg["tert"] = tg.groupby("t")["liq"].rank(pct=True).pipe(lambda r: np.where(r <= 1 / 3, "하", np.where(r <= 2 / 3, "중", "상")))
    out = {"verdict": verdict, "coins_downloaded": len(have), "coins_with_signal": len(used), "universe_candidates": len(u["kept"]),
           "n_obs": len(x), "gross_bp": round(float(x.mean()), 2), "gross_ci95": [round(c, 2) for c in ci], "t": round(tstat(x), 2),
           "net10_bp": round(float((x - COST_N).mean()), 2), "net20_bp": round(float((x - 2 * COST_N).mean()), 2),
           "t_net10": round(tstat(x - COST_N), 2), "breakeven_bp": round(float(x.mean()), 2),
           "parts": {k: {"n": len(v), "bp": round(float(v.mean()), 2), "t": round(tstat(v), 2)} for k, v in parts.items()},
           "yearly_bp": {int(y): round(float(v), 1) for y, v in s.groupby(s.index.year).mean().items()},
           "record": {"by_liquidity_tertile_eventlevel": tg.groupby("tert")["v"].agg(["count", "mean"]).round(2).to_dict(),
                      "delisted_eventlevel": tg.groupby("delisted")["v"].agg(["count", "mean"]).round(2).to_dict()}}
    (HERE / "crypto-k1-replication.json").write_text(json.dumps(out, ensure_ascii=False, indent=1, default=str), encoding="utf-8")
    print(json.dumps({k: v for k, v in out.items() if k != "record"}, ensure_ascii=False))
    print(json.dumps(out["record"], ensure_ascii=False))


if __name__ == "__main__":
    main()
