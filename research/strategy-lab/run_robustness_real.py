#!/usr/bin/env python
"""HONEST robustness run: real backtest execution + real metric computation.

Reference config: earnings_yield, max_positions=50, equal-weight, cost 30bps
round-trip, A1A_ONLY, monthly rebalance, 2016-01-01 .. 2026-08-14.

Every metric below is computed from the actual backtest result's closed
positions / diag via compute_metrics (identical to run_capacity_test.py).
Nothing is hardcoded.

Runs are saved incrementally to a JSON file so a timeout cannot lose work;
re-running skips keys that already exist.
"""
import importlib.util
import json
import os
import sys
import time

import numpy as np
import pandas as pd

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(REPO_ROOT, "research", "strategy-lab"))

from engine.runner import run_smoke  # noqa: E402

# Reuse the exact, already-accepted metric function from the capacity test.
from run_capacity_test import compute_metrics  # noqa: E402

RULE_PATH = os.path.join(REPO_ROOT, "research/strategy-lab/strategies/factor_earnings_yield_v1/rule.py")
RESULTS_DIR = os.path.join(REPO_ROOT, "research/strategy-lab/reports/2026-08-30-factor-discovery")
OUT_JSON = os.path.join(RESULTS_DIR, "factor-earnings-yield-robustness-real.json")

START = "2016-01-01"
END = "2026-08-14"
STRATEGY_ID = "factor_earnings_yield_v1"


def make_rule_module(max_positions=50, cost_bps=None, round_trip_bps=None, universe_mode=None):
    """cost_bps = per-side cost (legacy, for internal checks).
    round_trip_bps = round-trip cost in bps; entry=exit=round_trip/2.
    The project convention (30bps 왕복) uses round_trip_bps."""
    spec = importlib.util.spec_from_file_location("rule_orig", RULE_PATH)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    mod.PARAMS = json.loads(json.dumps(mod.PARAMS))
    mod.PARAMS["portfolio"]["maxPositions"] = max_positions
    if round_trip_bps is not None:
        per_side = round_trip_bps / 2.0
        mod.PARAMS["cost"]["entryCostBps"] = per_side
        mod.PARAMS["cost"]["exitCostBps"] = per_side
        mod.PARAMS["cost"]["roundTripBps"] = round_trip_bps
    elif cost_bps is not None:
        mod.PARAMS["cost"]["entryCostBps"] = cost_bps
        mod.PARAMS["cost"]["exitCostBps"] = cost_bps
        mod.PARAMS["cost"]["roundTripBps"] = cost_bps * 2
    if universe_mode is not None:
        mod.PARAMS["universe"]["mode"] = universe_mode
    return mod


def _ym_diff(a, b):
    try:
        ya, ma = int(a[:4]), int(a[5:7])
        yb, mb = int(b[:4]), int(b[5:7])
        return (yb - ya) * 12 + (mb - ma)
    except (TypeError, ValueError):
        return None


def mdd_recovery(monthly_pnl, initial_capital=100_000_000):
    """Max drawdown, its trough month, and recovery month (months elapsed)."""
    months = sorted(monthly_pnl.keys())
    eq = initial_capital
    peak = initial_capital
    trough = 0.0
    trough_mo = None
    peak_before_trough = initial_capital
    for mo in months:
        eq += monthly_pnl[mo]
        peak = max(peak, eq)
        dd = eq / peak - 1
        if dd < trough:
            trough = dd
            trough_mo = mo
            peak_before_trough = peak
    recovery_mo = None
    if trough_mo:
        eq2 = initial_capital
        for mo in months:
            eq2 += monthly_pnl[mo]
            if mo > trough_mo and eq2 >= peak_before_trough:
                recovery_mo = mo
                break
    return {
        "max_dd": trough,
        "trough_month": trough_mo,
        "recovery_month": recovery_mo,
        "recovery_months": _ym_diff(trough_mo, recovery_mo) if trough_mo and recovery_mo else None,
        "peak_before_trough": peak_before_trough,
    }


def load_results():
    if os.path.exists(OUT_JSON):
        with open(OUT_JSON, encoding="utf-8") as f:
            return json.load(f)
    return {}


def save_results(results):
    os.makedirs(RESULTS_DIR, exist_ok=True)
    with open(OUT_JSON, "w", encoding="utf-8") as f:
        json.dump(results, f, ensure_ascii=False, indent=2, default=str)


def run_one(label, ticker_subset=None, rule_module=None, start=START, end=END, note=""):
    results = load_results()
    if label in results:
        m = results[label]["metrics"]
        print(f"[skip] {label}: already present (CAGR={m['cagr']:.2%})", flush=True)
        return results[label]

    t0 = time.time()
    res = run_smoke(STRATEGY_ID, start, end, REPO_ROOT,
                    ticker_subset=ticker_subset, trace_limit=0, rule_module=rule_module)
    portfolio = res["portfolio"]
    diag = res["diag"]
    metrics = compute_metrics(portfolio, diag)

    monthly_pnl = {}
    for pos in portfolio.closed_positions:
        ym = pos["exit_date"][:7]
        monthly_pnl.setdefault(ym, 0)
        monthly_pnl[ym] += pos["pnl"]

    rec = {
        "note": note,
        "metrics": metrics,
        "monthly_pnl": monthly_pnl,
        "mdd_recovery": mdd_recovery(monthly_pnl),
        "diag": {
            "signalCount": diag.get("signalCount"),
            "executableTradeCount": diag.get("executableTradeCount"),
            "closedPositionCount": diag.get("closedPositionCount"),
            "maxSimultaneousPositionsObserved": diag.get("maxSimultaneousPositionsObserved"),
            "runClass": diag.get("runClass"),
        },
        "run_seconds": round(time.time() - t0, 1),
        "config": {"max_positions": rule_module.PARAMS["portfolio"]["maxPositions"]
                   if rule_module else "default",
                   "entry_exit_bps": rule_module.PARAMS["cost"]["entryCostBps"]
                   if rule_module else "default"},
    }
    results[label] = rec
    save_results(results)
    m = metrics
    print(f"{label}: CAGR={m['cagr']:.2%}, Sharpe={None if not m['sharpe'] else round(m['sharpe'], 2)}, "
          f"MDD={m['mdd']:.2%}, TotalRet={m['total_return']:.2%}, max_simul={m['max_simul']}, "
          f"trades={m['n_trades']}, wr={m['win_rate']:.2%}  ({rec['run_seconds']}s)", flush=True)
    return rec


def _load_a1a():
    d = {}
    with open(os.path.join(REPO_ROOT, "data/backfill/universe/a1a/current.jsonl"), encoding="utf-8") as f:
        for line in f:
            r = json.loads(line)
            d[r["ticker"]] = r
    return d


def _load_latest_shares():
    import gzip
    a3c_dir = os.path.join(REPO_ROOT, "data/backfill/fundamentals/a3c")
    files = sorted([f for f in os.listdir(a3c_dir) if f.endswith(".jsonl.gz")])
    if not files:
        return {}
    latest = files[-1]
    shares = {}
    with gzip.open(os.path.join(a3c_dir, latest), "rt", encoding="utf-8") as f:
        for line in f:
            r = json.loads(line)
            if r.get("istcTotqy") and r.get("ticker"):
                shares[r["ticker"]] = r["istcTotqy"]
    return shares


def _classify_mcap():
    a1a = _load_a1a()
    shares = _load_latest_shares()
    from engine.data.a2aProvider import A2aProvider
    p = A2aProvider(repo_root=REPO_ROOT)
    bars = p.load(list(a1a.keys()), "2026-07-01", "2026-08-14", universe_hash="robustness-mcap")
    mcap = {}
    for t in a1a:
        if t in bars and t in shares and len(bars[t]) > 0:
            close = float(bars[t]["close"].iloc[-1])
            mcap[t] = close * shares[t]
    if not mcap:
        return {}, {}, {}, {}
    caps = sorted(mcap.values())
    p33 = np.percentile(caps, 33)
    p67 = np.percentile(caps, 67)
    large = [t for t in mcap if mcap[t] >= p67]
    mid = [t for t in mcap if p33 <= mcap[t] < p67]
    small = [t for t in mcap if mcap[t] < p33]
    print(f"mcap: {len(mcap)} tickers, Large={len(large)}, Mid={len(mid)}, Small={len(small)}, "
          f"tercile p33={p33/1e8:.1f}e8, p67={p67/1e8:.1f}e8", flush=True)
    return {"large": large, "mid": mid, "small": small}, mcap, a1a, shares


def main():
    start_wall = time.time()
    a1a = _load_a1a()
    kospi = [t for t, info in a1a.items() if info.get("market") == "KOSPI"]
    kosdaq = [t for t, info in a1a.items() if info.get("market") == "KOSDAQ"]
    print(f"A1A tickers={len(a1a)} KOSPI={len(kospi)} KOSDAQ={len(kosdaq)}", flush=True)

    # 0. Main reference (max_positions=50, cost 30bps round trip)
    mod_ref = make_rule_module(max_positions=50, cost_bps=30)
    run_one("cost_30bps", rule_module=mod_ref, note="reference: max50, cost30")

    # 1. KOSPI / KOSDAQ
    run_one("market_kospi", ticker_subset=set(kospi), rule_module=mod_ref,
            note="max50 cost30, KOSPI only")
    run_one("market_kosdaq", ticker_subset=set(kosdaq), rule_module=mod_ref,
            note="max50 cost30, KOSDAQ only")

    # 2. Period splits
    for name, s, e in [("2016-2020", "2016-01-01", "2020-12-31"),
                       ("2021-2023", "2021-01-01", "2023-12-31"),
                       ("2024-2026", "2024-01-01", "2026-08-14")]:
        run_one(f"period_{name}", rule_module=mod_ref, start=s, end=e, note=f"period {name}")

    # 3. Cost sensitivity 50 / 65 bps
    mod_50 = make_rule_module(max_positions=50, cost_bps=50)
    run_one("cost_50bps", rule_module=mod_50, note="max50 cost50")
    mod_65 = make_rule_module(max_positions=50, cost_bps=65)
    run_one("cost_65bps", rule_module=mod_65, note="max50 cost65")

    # 4. Market cap segments
    segs, mcap, _, _ = _classify_mcap()
    if segs:
        run_one("mcap_large", ticker_subset=set(segs["large"]), rule_module=mod_ref, note="max50 cost30, large cap")
        run_one("mcap_mid", ticker_subset=set(segs["mid"]), rule_module=mod_ref, note="max50 cost30, mid cap")
        run_one("mcap_small", ticker_subset=set(segs["small"]), rule_module=mod_ref, note="max50 cost30, small cap")

    # 5. Survivorship: merged A1A+A1B universe
    mod_surv = make_rule_module(max_positions=50, cost_bps=30, universe_mode="A1A_A1B_MERGED")
    run_one("survivorship", rule_module=mod_surv, note="max50 cost30, A1A+A1B merged universe")

    print(f"\nAll runs finished in {time.time()-start_wall:.0f}s. Results: {OUT_JSON}", flush=True)


if __name__ == "__main__":
    main()