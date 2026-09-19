#!/usr/bin/env python3
"""단기 3차 — 사전등록 `findings/short-horizon-phase3-preregistration-2026-09.md`.

    python research/strategy-lab/futures/short_horizon_phase3.py            # 실행
    python research/strategy-lab/futures/short_horizon_phase3.py --selftest
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from short_horizon_study import tstat, load_daily  # noqa: E402

CACHE = HERE.parent / ".cache"
ETFS = ["IWM", "DIA", "MDY", "EFA", "EEM", "EWJ", "EWG", "EWU", "EWT", "EWA", "EWZ", "FXI", "EWC", "EWH"]
BLOCKS = [("2001", "2006"), ("2006", "2011"), ("2011", "2016"), ("2016", "2021"), ("2021", "2027")]


# ---------------------------------------------------------------- P3-X
def p3x() -> dict:
    d = pd.concat([pd.read_parquet(p) for p in sorted((CACHE / "a2a_parquet").glob("*.parquet"))])
    d = d[(d["open"] > 0) & (d["close"] > 0)].copy()
    d["date"] = pd.to_datetime(d["date"])
    d = d.sort_values(["ticker", "date"])
    cal = np.sort(d["date"].unique())
    pos = pd.Series(np.arange(len(cal)), index=cal)
    d["k"] = d["date"].map(pos).to_numpy()
    g = d.groupby("ticker")
    d["intraday"] = d["close"] / d["open"] - 1
    nxt_open, nxt_k = g["open"].shift(-1), g["k"].shift(-1)
    d["overnight"] = np.where(nxt_k == d["k"] + 1, nxt_open / d["close"] - 1, np.nan)
    d["amt"] = d["close"] * d["volume"]
    d["liq"] = g["amt"].transform(lambda s: s.shift(1).rolling(20, min_periods=20).mean())
    for c in ("intraday", "overnight"):
        d.loc[d[c].abs() > 0.30, c] = np.nan
    d["tier"] = pd.cut(d["liq"], [-1, 2e9, 2e10, np.inf], labels=["L0", "L1", "L2"])
    out = {}
    for tier, sub in d.dropna(subset=["tier"]).groupby("tier", observed=True):
        daily = sub.groupby("date")[["intraday", "overnight"]].mean() * 1e4
        yr = daily.groupby(daily.index.year).mean().round(1)
        out[str(tier)] = {
            "intraday_bp": round(float(daily["intraday"].mean()), 2), "t_intraday": round(tstat(daily["intraday"].dropna().to_numpy()), 2),
            "overnight_bp": round(float(daily["overnight"].mean()), 2), "t_overnight": round(tstat(daily["overnight"].dropna().to_numpy()), 2),
            "years_intraday_neg": int((yr["intraday"] < 0).sum()), "n_years": int(len(yr)),
            "yearly": {int(y): {"intra": r.intraday, "over": r.overnight} for y, r in yr.iterrows()},
            "stocks_per_day": round(float(sub.groupby("date").size().mean()), 0)}
    v = {}
    for t in ("L1", "L2"):
        r = out[t]
        a = r["t_intraday"] <= -3 and r["intraday_bp"] < 0
        b = r["years_intraday_neg"] >= 8
        v[t] = "SUPPORTED" if a and b else ("PARTIAL" if a or b else "NOT SUPPORTED")
    out["verdict"] = ("SUPPORTED" if all(x == "SUPPORTED" for x in v.values())
                      else "NOT SUPPORTED" if all(x == "NOT SUPPORTED" for x in v.values()) else "PARTIAL")
    out["verdict_by_tier"] = v
    # 보조: 지수 선물
    f = load_daily()
    same = f["code"] == f["code"].shift(-1)
    fi = pd.DataFrame({"intraday": (f["c"] / f["o"] - 1) * 1e4,
                       "overnight": np.where(same, (f["o"].shift(-1) / f["c"] - 1) * 1e4, np.nan)}, index=f.index)
    fi = fi[fi.index >= "2016-01-01"]
    out["futures_index_aux"] = {"intraday_bp": round(float(fi["intraday"].mean()), 2),
                                "overnight_bp": round(float(fi["overnight"].mean()), 2),
                                "yearly": {int(y): [round(float(x), 1) for x in r]
                                           for y, r in fi.groupby(fi.index.year).mean().iterrows()}}
    return out


# ---------------------------------------------------------------- P3-R
def rule_events(f: pd.DataFrame) -> tuple[list, list]:
    """(이벤트 [(날짜, 초과bp, grossbp)], 사용한 기준선)."""
    f = f[f.index >= "2001-01-01"]
    o, c = f["Open"].to_numpy(float), f["Close"].to_numpy(float)
    dates = f.index
    bad = np.r_[False, o[1:] == c[:-1]]                       # 시가 불량일
    n = len(f)
    low10 = (f["Close"] == f["Close"].rolling(10).min()).to_numpy()
    base_ret = np.full(n, np.nan)                              # t+1 시가 → t+5 종가
    for i in range(n - 5):
        if not bad[i + 1]:
            base_ret[i] = (c[i + 5] / o[i + 1] - 1) * 1e4
    blk = np.array([next(k for k, (a, b) in enumerate(BLOCKS) if a <= str(dt.year) < b) for dt in dates])
    base = {k: np.nanmean(base_ret[blk == k]) for k in range(len(BLOCKS)) if np.isfinite(base_ret[blk == k]).any()}
    ev, i = [], 10
    while i < n - 5:
        if low10[i] and np.isfinite(base_ret[i]):
            ev.append((dates[i], base_ret[i] - base[blk[i]], base_ret[i]))
            i += 6
        else:
            i += 1
    return ev, base


def p3r() -> dict:
    per, allev = {}, []
    for tk in ETFS:
        f = pd.read_parquet(CACHE / "market_data" / f"{tk}_ohlc_full.parquet")
        ev, _ = rule_events(f)
        x = np.array([e[1] for e in ev])
        per[tk] = {"n": len(ev), "excess_bp": round(float(x.mean()), 2), "t": round(tstat(x), 2),
                   "gross_net20_bp": round(float(np.mean([e[2] for e in ev]) - 20), 2)}
        allev += ev
    df = pd.DataFrame(allev, columns=["d", "x", "g"]).groupby("d").mean()
    t_all = tstat(df["x"].to_numpy())
    late = df[df.index >= "2014-01-01"]["x"]
    pos = sum(v["excess_bp"] > 0 for v in per.values())
    a, b, c = t_all >= 2.5, pos >= 10, late.mean() > 0
    verdict = "REPLICATED" if a and b and c else ("PARTIAL" if a or b else "NOT REPLICATED")
    return {"verdict": verdict, "pooled_excess_bp": round(float(df["x"].mean()), 2), "t_pooled": round(t_all, 2),
            "n_dates": len(df), "tickers_positive": pos, "late_2014_excess_bp": round(float(late.mean()), 2),
            "late_t": round(tstat(late.to_numpy()), 2),
            "pooled_gross_net20_bp": round(float(df["g"].mean() - 20), 2), "per_ticker": per}


def main():
    out = {"P3X": p3x(), "P3R": p3r()}
    (HERE / "short-horizon-phase3.json").write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
    x = out["P3X"]
    print("P3-X verdict", x["verdict"], x["verdict_by_tier"])
    for t in ("L0", "L1", "L2"):
        r = x[t]
        print(t, f"intra {r['intraday_bp']} (t {r['t_intraday']}) over {r['overnight_bp']} (t {r['t_overnight']}) "
                 f"neg-years {r['years_intraday_neg']}/{r['n_years']} n/day {r['stocks_per_day']}")
        print("   ", {y: v["intra"] for y, v in r["yearly"].items()})
    print("futures aux", x["futures_index_aux"])
    r = out["P3R"]
    print("P3-R", {k: v for k, v in r.items() if k != "per_ticker"})
    for k, v in r["per_ticker"].items():
        print("  ", k, v)


def selftest():
    idx = pd.bdate_range("2001-01-01", periods=3000)
    rng = np.random.default_rng(0)
    c = 100 * np.exp(np.cumsum(rng.normal(0, 0.01, len(idx))))
    f = pd.DataFrame({"Open": c * (1 + rng.normal(0, 0.002, len(idx))), "High": c, "Low": c, "Close": c}, index=idx)
    ev, base = rule_events(f)
    x = np.array([e[1] for e in ev])
    assert abs(tstat(x)) < 3.5, tstat(x)                      # 랜덤워크 → 초과 없음
    f2 = f.copy(); f2["Open"] = f2["Close"].shift(1)          # 전부 불량 시가 → 이벤트 0
    assert len(rule_events(f2.dropna())[0]) == 0
    print("selftest 2/2 OK")


if __name__ == "__main__":
    selftest() if "--selftest" in sys.argv else main()
