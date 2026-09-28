#!/usr/bin/env python3
"""크립토 포지션 쏠림(롱숏·테이커·OI) — 1차 판정 (사전등록 findings/crypto-positioning-preregistration-2026-09.md).

가격·특징·집계·판정은 crypto_short_horizon 을 import 해 그대로 쓴다(재구현 금지). 새로 만드는 것은 metrics 특징과 K1~K3 뿐.
  python research/strategy-lab/futures/crypto_positioning_study.py
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from crypto_short_horizon import COST_N, DATA, aggregate, features, load, seq, split  # noqa: E402
from short_horizon_study import null_bar, tstat  # noqa: E402

SEED = 20260928
HOLD = 12
MET = DATA / "metrics"


def pct_prev(s: pd.Series, n=180, minp=90) -> pd.Series:
    """직전 n 관측(현재 제외) 중 현재보다 작은 비율 — crypto_short_horizon 의 fpct 와 같은 모양."""
    return s.rolling(n + 1, min_periods=minp + 1).apply(lambda x: (x[:-1] < x[-1]).mean(), raw=True)


def metrics_at(sym: str, idx: pd.DatetimeIndex) -> pd.DataFrame | None:
    f = MET / f"{sym}.parquet"
    if not f.exists():
        return None
    m = pd.read_parquet(f)
    m["t"] = pd.to_datetime(m["create_time"], utc=True)
    m = m.drop_duplicates("t").set_index("t").sort_index()
    for c in ("sum_open_interest", "count_toptrader_long_short_ratio", "sum_taker_long_short_vol_ratio"):
        m[c] = pd.to_numeric(m[c], errors="coerce")
    m["taker4h"] = m["sum_taker_long_short_vol_ratio"].rolling("4h").mean()     # (T−4h, T] 5분 비율 평균
    left = pd.DataFrame({"t": idx})
    right = m[["sum_open_interest", "count_toptrader_long_short_ratio", "taker4h"]].reset_index()
    j = pd.merge_asof(left, right, on="t", direction="backward", tolerance=pd.Timedelta("1h"))   # T 이하 마지막, 1시간 안
    return j.set_index("t")


def judge(s: pd.Series, bar: float, cost_mult=1.0) -> dict:
    parts = {k: v.to_numpy() for k, v in s.groupby(s.index.map(split))}
    for k in ("TRAIN", "VALID", "TEST"):
        parts.setdefault(k, np.array([]))
    tr = parts["TRAIN"]
    sg = np.sign(tr.mean()) if len(tr) else 0
    info = bool(abs(tstat(tr)) >= bar and len(parts["VALID"]) and len(parts["TEST"])
                and np.sign(parts["VALID"].mean()) == sg and np.sign(parts["TEST"].mean()) == sg)
    oos = sg * np.r_[parts["VALID"], parts["TEST"]]
    c = COST_N * cost_mult
    net = lambda k: float((oos - k).mean()) if len(oos) else np.nan
    eco = info and net(c) > 0 and net(2 * c) > 0
    rob = eco and tstat(oos - c) >= 2
    rng = np.random.default_rng(SEED)
    ci = [float(np.percentile([rng.choice(oos, len(oos)).mean() for _ in range(2000)], q)) for q in (2.5, 97.5)] if len(oos) > 2 else None
    v = ("판정불가" if len(parts["TEST"]) < 20 else "ROBUST" if rob else "ECONOMIC" if eco
         else "INFORMATION" if info else "REJECT")
    return {"verdict": v, "sign": int(sg), "t_train": round(tstat(tr), 2),
            **{k: {"n": len(parts[k]), "bp": round(float(parts[k].mean()), 2) if len(parts[k]) else None,
                   "t": round(tstat(parts[k]), 2)} for k in ("TRAIN", "VALID", "TEST")},
            "oos_gross_bp": round(float(oos.mean()), 2) if len(oos) else None, "oos_gross_ci95": ci,
            "net_oos": round(net(c), 2), "net_oos_stress": round(net(2 * c), 2), "cost_bp": c,
            "breakeven_bp": round(float(oos.mean()), 2) if len(oos) else None,
            "t_net_oos": round(tstat(oos - c), 2) if len(oos) > 2 else None}


def main():
    coins = load()
    feats = {k: features(d, fu) for k, (d, fu) in coins.items()}
    ev = {"K1": [], "K2": []}
    k3_long, k3_short, k3m_long, k3m_short = {}, {}, {}, {}
    rec_corr, rec_start = [], {}
    for sym, f in feats.items():
        m = metrics_at(sym, f.index)
        if m is None:
            continue
        rec_start[sym] = str(m["sum_open_interest"].first_valid_index())
        g4 = (f.index.hour % 4 == 0)
        grid = f.index[g4]
        ls_p = pct_prev(m.loc[grid, "count_toptrader_long_short_ratio"]).reindex(f.index).to_numpy()
        tk_p = pct_prev(m.loc[grid, "taker4h"]).reindex(f.index).to_numpy()
        oi = m.loc[grid, "sum_open_interest"]
        oi_p = pct_prev(oi / oi.shift(1) - 1).reindex(f.index).to_numpy()
        ext1 = g4 & ((ls_p > 0.9) | (ls_p < 0.1))
        ev["K1"] += seq(f, ext1, np.where(ls_p > 0.9, -1.0, 1.0), HOLD)
        ext2 = g4 & ((tk_p > 0.9) | (tk_p < 0.1))
        ev["K2"] += seq(f, ext2, np.where(tk_p > 0.9, -1.0, 1.0), HOLD)
        r4, s4, p = f["r4"].to_numpy(), f["s4"].to_numpy(), f["p"].to_numpy()
        fwd = np.full(len(p), np.nan)
        fwd[:-HOLD] = (p[HOLD:] / p[:-HOLD] - 1) * 1e4
        up, dn = g4 & (r4 > 2 * s4), g4 & (r4 < -2 * s4)
        for mask, pct_hi, store in ((up, True, k3_long), (up, False, k3_short), (dn, True, k3m_long), (dn, False, k3m_short)):
            sel = mask & ((oi_p >= 0.8) if pct_hi else (oi_p <= 0.2)) & np.isfinite(fwd)
            for t, v in zip(f.index[sel], fwd[sel]):
                store.setdefault(t, []).append(v)
        fp = f["fpct"].reindex(grid).to_numpy()
        for name, arr in (("K1", ls_p), ("K2", tk_p)):
            a = pd.Series(arr, index=f.index).reindex(grid).to_numpy()
            ok = np.isfinite(a) & np.isfinite(fp)
            if ok.sum() > 50:
                rec_corr.append((name, sym, float(np.corrcoef(a[ok], fp[ok])[0, 1])))

    def spread(lo_d, hi_d, sign=1.0):
        """같은 T 에 둘 다 있을 때 (유입 평균 − 이탈 평균) × sign, 12시간 비중첩."""
        out, last = [], None
        for t in sorted(set(lo_d) & set(hi_d)):
            if last is not None and t < last + pd.Timedelta(hours=HOLD):
                continue
            out.append((t, sign * (np.mean(lo_d[t]) - np.mean(hi_d[t]))))
            last = t
        return out

    series = {k: aggregate(v) for k, v in ev.items()}
    series["K3"] = aggregate(spread(k3_long, k3_short))
    rng = np.random.default_rng(SEED)
    bar = null_bar([s[s.index.map(split) == "TRAIN"].to_numpy() for s in series.values()], rng)
    out = {"bar": round(bar, 2), "coins_with_metrics": len(rec_start),
           "cells": {k: judge(s, bar, cost_mult=2.0 if k == "K3" else 1.0) for k, s in series.items()}}
    for k, s in series.items():
        out["cells"][k]["yearly_bp"] = {int(y): round(float(v), 1) for y, v in (s * out["cells"][k]["sign"]).groupby(s.index.year).mean().items()}
    k3m = aggregate(spread(k3m_long, k3m_short, sign=-1.0))      # 하락 충격: 신규 숏 유입(OI↑) 쪽이 더 내리는가 → 부호 뒤집어 양 = 가설
    out["record"] = {
        "K3_mirror_down": {"n": len(k3m), "bp": round(float(k3m.mean()), 2) if len(k3m) else None, "t": round(tstat(k3m.to_numpy()), 2)},
        "corr_with_funding_pct": {n: round(float(np.mean([c for nn, _, c in rec_corr if nn == n])), 3) for n in ("K1", "K2")},
        "metrics_start": rec_start}
    (HERE / "crypto-positioning.json").write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
    print("bar", out["bar"], "coins", out["coins_with_metrics"])
    for c, r in out["cells"].items():
        print(f"{c} {r['verdict']:10s} s{r['sign']:+d} tTR {r['t_train']:6.2f} n {r['TRAIN']['n']}/{r['VALID']['n']}/{r['TEST']['n']} "
              f"bp {r['TRAIN']['bp']}/{r['VALID']['bp']}/{r['TEST']['bp']} net {r['net_oos']} tnet {r['t_net_oos']}")
    print("record", json.dumps({k: v for k, v in out["record"].items() if k != "metrics_start"}, ensure_ascii=False))


if __name__ == "__main__":
    main()
