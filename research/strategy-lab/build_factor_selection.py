#!/usr/bin/env python
"""Build selection.json for factor single-factor backtest (Step 3).

Reads the factor_discovery_kr.py outputs and builds pre-computed selections
for earnings_yield (top decile), rv60_pct (bottom decile), rev1m (bottom decile).
Uses the same PIT / universe / liquidity gate / monthly rebalance conventions.
"""
import json
import os
import sys

import pandas as pd

# Paths
REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
LAB = os.path.join(REPO_ROOT, "research", "strategy-lab")
A4_PATH = os.path.join(LAB, "data", "a4", "a4-research-dataset.parquet")
QUALITY_PANEL = os.path.join(LAB, "reports", "2026-08-21-buffett-quality-precheck", "quality-panel.jsonl")
VALUATION_PANEL = os.path.join(LAB, "reports", "2026-08-21-a5-valuation-precheck", "valuation-panel.jsonl")
A1A_PATH = os.path.join(REPO_ROOT, "data", "backfill", "universe", "a1a", "current.jsonl")
A3_DIR = os.path.join(REPO_ROOT, "data", "backfill", "fundamentals", "a3")
A3B_DIR = os.path.join(REPO_ROOT, "data", "backfill", "fundamentals", "a3b")
A3C_DIR = os.path.join(REPO_ROOT, "data", "backfill", "fundamentals", "a3c")
KOSPI_PATH = os.path.join(LAB, "data", "market-regime", "krkospi_raw.parquet")

# Factor configs
FACTOR_CONFIGS = {
    "earnings_yield": {
        "direction": "high",  # top decile
        "strategy_id": "factor_earnings_yield_v1",
        "output_dir": os.path.join(LAB, "strategies", "factor_earnings_yield_v1"),
    },
    "rv60_pct": {
        "direction": "low",  # bottom decile (low vol)
        "strategy_id": "factor_rv60_v1",
        "output_dir": os.path.join(LAB, "strategies", "factor_rv60_v1"),
    },
    "rev1m": {
        "direction": "low",  # bottom decile (reversal)
        "strategy_id": "factor_rev1m_v1",
        "output_dir": os.path.join(LAB, "strategies", "factor_rev1m_v1"),
    },
}

# Common params
START = "2016-01-01"
END = "2026-09-03"
MIN_TURNOVER = 100_000_000.0
WARM_BETA = 120

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from engine.data.a2aProvider import A2aProvider
from engine.data.calendar import TradingCalendar
from engine.runner import _drop_suspension_rows

import bisect
import gzip
import numpy as np
from scipy.stats import spearmanr


def normd(s):
    s = str(s)
    if len(s) == 8 and s.isdigit():
        return f"{s[:4]}-{s[5:6]}-{s[6:]}"
    return s


def monthly_reb(dates):
    out, seen = [], set()
    for d in sorted(dates):
        if d[:7] not in seen:
            seen.add(d[:7])
            out.append(d)
    return out


def load_market_map():
    m = {}
    with open(A1A_PATH, encoding="utf-8") as f:
        for line in f:
            r = json.loads(line)
            if r.get("ticker") and r.get("market"):
                m[r["ticker"]] = r["market"]
    return m


def load_panel(path, keep_fields):
    df = pd.read_json(path, lines=True)
    df = df[["ticker", "asOf"] + keep_fields]
    df["asOf"] = df["asOf"].astype(str)
    df = df.dropna(subset=["ticker", "asOf"])
    key = {}
    for t, g in df.groupby("ticker"):
        g = g.sort_values("asOf")
        key[t] = (g["asOf"].tolist(), g[keep_fields].to_dict("records"))
    return key


def panel_lookup(key, t, d, field):
    if t not in key:
        return None
    asofs, recs = key[t]
    i = bisect.bisect_right(asofs, d) - 1
    if i < 0:
        return None
    v = recs[i][field]
    return None if v is None or pd.isna(v) else float(v)


def select_as_of(records, as_of):
    best = None
    for rec in records:
        af = rec[0]
        if af > as_of:
            continue
        if best is None or af > best[0]:
            best = rec
    return best


def select_fiscal_year(records, fy, as_of):
    best = None
    for rec in records:
        if rec[1] != fy:
            continue
        af = rec[0]
        if af > as_of:
            continue
        if best is None or af > best[0]:
            best = rec
    return best


def build_a3_maps():
    REV, NI, OP, EQ, CA, CL = {}, {}, {}, {}, {}, {}
    for y in range(2015, 2026):
        fp = os.path.join(A3_DIR, f"{y}.jsonl.gz")
        if not os.path.exists(fp):
            continue
        with gzip.open(fp, "rt", encoding="utf-8") as f:
            for line in f:
                r = json.loads(line)
                pe = str(r.get("periodEnd", ""))
                if not pe.endswith("12-31"):
                    continue
                t = r.get("ticker")
                fy = int(r["fiscalYear"])
                af = normd(str(r["availableFrom"]))
                if t is None:
                    continue

                def put(m, val):
                    if val is not None:
                        try:
                            m.setdefault(t, []).append((af, fy, float(val)))
                        except (TypeError, ValueError):
                            pass
                put(REV, r.get("revenue"))
                put(NI, r.get("netIncome"))
                put(OP, r.get("opProfit"))
                put(EQ, r.get("equity"))
                put(CA, r.get("currentAssets"))
                put(CL, r.get("currentLiab"))
    return REV, NI, OP, EQ, CA, CL


def build_a3b_retention():
    out = {}
    for y in range(2015, 2026):
        fp = os.path.join(A3B_DIR, f"{y}.jsonl.gz")
        if not os.path.exists(fp):
            continue
        with gzip.open(fp, "rt", encoding="utf-8") as f:
            for line in f:
                r = json.loads(line)
                if not str(r.get("periodEnd", "")).endswith("1231"):
                    continue
                t = r.get("ticker")
                if t is None:
                    continue
                out.setdefault(t, []).append((normd(str(r["availableFrom"])), int(r["fiscalYear"]),
                                              r.get("eps"), r.get("dividendPerShare")))
    return out


def build_a3c_shares():
    out = {}
    for y in range(2015, 2026):
        fp = os.path.join(A3C_DIR, f"{y}.jsonl.gz")
        if not os.path.exists(fp):
            continue
        with gzip.open(fp, "rt", encoding="utf-8") as f:
            for line in f:
                r = json.loads(line)
                t = r.get("ticker")
                qty = r.get("istcTotqy")
                if t is None or qty is None:
                    continue
                try:
                    qty = float(qty)
                except (TypeError, ValueError):
                    continue
                out.setdefault(t, []).append((normd(str(r["availableFrom"])), qty, int(r["fiscalYear"])))
    return out


def load_kospi():
    df = pd.read_parquet(KOSPI_PATH)
    df["date"] = df["date"].astype(str)
    df = df.set_index("date")["value"]
    return df


def period_of(d):
    if d <= "2022-06-30":
        return "TRAIN"
    elif d <= "2024-01-01":
        return "VALID"
    else:
        return "TEST"


def main():
    print("Loading A4 ...", flush=True)
    df = pd.read_parquet(A4_PATH, columns=["ticker", "date", "close", "total_amount", "total_volume"])
    df = df.drop_duplicates(subset=["ticker", "date"], keep="last")
    df["date"] = df["date"].astype(str)
    df = df.sort_values(["ticker", "date"]).reset_index(drop=True)
    print(f"  {len(df)} rows, {df['ticker'].nunique()} tickers", flush=True)

    g = df.groupby("ticker", sort=False)
    df["logret"] = np.log(df["close"] / df["close"].shift(1))
    df["rev1m"] = df["close"] / df["close"].groupby(df["ticker"]).shift(21) - 1
    df["rv60_pct"] = g["logret"].transform(lambda s: s.rolling(60, min_periods=20).std()) * 100
    df["dv20"] = g["total_amount"].transform(lambda s: s.rolling(20, min_periods=20).mean())
    df["dv20_log"] = np.log(df["dv20"].clip(lower=1.0))
    df["liquid"] = df["dv20"] >= MIN_TURNOVER

    all_dates = sorted(df["date"].unique())
    months = monthly_reb(all_dates)
    base = df[df["date"].isin(months)].copy()

    # forward 1-month return for factor computation
    close_wide = df.pivot_table(index="date", columns="ticker", values="close")
    next_date = {d: all_dates[i + 1] for i, d in enumerate(all_dates[:-1])}
    exit_map = {months[i]: months[i + 1] for i in range(len(months) - 1)}
    base["entry_t"] = base["date"].map(next_date)
    base["exit_t"] = base["date"].map(exit_map)
    fwd = pd.Series(np.nan, index=base.index, dtype=float)
    for i, sd in enumerate(months[:-1]):
        rows = base.index[base["date"] == sd]
        if len(rows) == 0:
            continue
        exit_d = months[i + 1]
        entry_d = next_date[sd]
        try:
            ec = close_wide.loc[entry_d]
            xc = close_wide.loc[exit_d]
        except KeyError:
            continue
        tks = base.loc[rows, "ticker"]
        vals = (xc.reindex(ec.index) / ec - 1.0)
        fwd.loc[rows] = tks.map(vals).to_numpy(dtype=float)
    base["fwd1m"] = fwd
    base = base.dropna(subset=["fwd1m"])
    base = base[base["fwd1m"] > -1].copy()

    market_map = load_market_map()
    base["market"] = base["ticker"].map(market_map)
    base["period"] = base["date"].map(period_of)

    # liquidity gate
    base = base[base["liquid"]].copy()
    print(f"  after liquid gate: {len(base)} rows", flush=True)

    # fundamentals
    print("Loading fundamentals ...", flush=True)
    REV, NI, OP, EQ, CA, CL = build_a3_maps()
    a3b = build_a3b_retention()
    a3c = build_a3c_shares()

    def val(rec_map, t, as_of, fy_shift=0):
        recs = rec_map.get(t, [])
        if fy_shift == 0:
            cur = select_as_of(recs, as_of)
            return cur[2] if cur else None
        cur = select_as_of(recs, as_of)
        if cur is None:
            return None
        prev = select_fiscal_year(recs, cur[1] - 1, as_of)
        if prev is None or cur[2] is None or prev[2] is None or prev[2] == 0:
            return None
        return cur[2] / prev[2] - 1.0

    def shares(t, d):
        recs = a3c.get(t, [])
        cur = select_as_of(recs, d)
        if cur is None or cur[1] is None or cur[1] <= 0:
            return None
        return cur[1]

    qdf = load_panel(QUALITY_PANEL, ["roe", "debtRatio", "roeConsistency", "operatingMarginTrend"])
    vdf = load_panel(VALUATION_PANEL, ["pbr", "per"])
    qlook = lambda t, d, f: panel_lookup(qdf, t, d, f)
    vlook = lambda t, d, f: panel_lookup(vdf, t, d, f)

    print("Building factor columns ...", flush=True)
    c = {"earnings_yield": [], "op_margin_trend": []}
    for _, rr in base[["ticker", "date"]].iterrows():
        t, d = rr["ticker"], rr["date"]
        c["op_margin_trend"].append(qlook(t, d, "operatingMarginTrend"))
        per = vlook(t, d, "per")
        c["earnings_yield"].append(1.0 / per if (per is not None and per > 0) else None)
    for f in c:
        base[f] = c[f]
    # rv60_pct, rev1m, dv20_log already in base from df merge
    print(f"  base columns ready", flush=True)

    # For each factor, compute deciles and build selection
    calendar = TradingCalendar(repo_root=REPO_ROOT)
    a2a = A2aProvider(repo_root=REPO_ROOT, use_cache=True)

    for factor_name, config in FACTOR_CONFIGS.items():
        print(f"\n=== Building selection for {factor_name} ===", flush=True)
        direction = config["direction"]
        strategy_id = config["strategy_id"]
        output_dir = config["output_dir"]

        os.makedirs(output_dir, exist_ok=True)

        # Compute decile assignment for each month
        sub = base[["ticker", "date", "market", "fwd1m", factor_name]].dropna(subset=[factor_name, "fwd1m"])
        selections = {}
        monthly_counts = {}

        for t, g in sub.groupby("date"):
            if len(g) < 30 or g[factor_name].nunique() <= 1:
                continue
            g2 = g.copy()
            g2["dec"] = pd.qcut(g2[factor_name].rank(method="first"), 10, labels=False) + 1
            if direction == "high":
                selected = g2[g2["dec"] == 10]["ticker"].tolist()
            else:
                selected = g2[g2["dec"] == 1]["ticker"].tolist()

            for ticker in selected:
                selections.setdefault(ticker, []).append(t)
            monthly_counts[t] = len(selected)

        # Compute holdSessions for each rebalance date
        hold_sessions_by_date = {}
        for k, t in enumerate(months[:-1]):
            if t not in monthly_counts:
                continue
            entry_date = calendar.next_session(t)
            next_rebal = months[k + 1]
            exit_target = calendar.next_session(next_rebal)
            if entry_date is None or exit_target is None:
                continue
            hold_sessions_by_date[t] = len(calendar.sessions_between(entry_date, exit_target))
        if months:
            hold_sessions_by_date.setdefault(months[-1], 21)

        # Build selection.json format
        selection_out = {}
        for ticker, dates in selections.items():
            selection_out[ticker] = [{"date": d, "holdSessions": hold_sessions_by_date.get(d, 21)}
                                     for d in dates if d in hold_sessions_by_date]
            selection_out[ticker].sort(key=lambda e: e["date"])

        out_path = os.path.join(output_dir, "selection.json")
        with open(out_path, "w", encoding="utf-8") as f:
            json.dump({
                "generatedFrom": "build_factor_selection.py (Step 3)",
                "sourcePanel": "A4 + valuation-panel + quality-panel + A3/A3b/A3c (PIT)",
                "period": f"{START} ~ {END}",
                "minTurnover": MIN_TURNOVER,
                "rebalanceMonths": len(monthly_counts),
                "avgSelectedPerMonth": round(sum(monthly_counts.values()) / len(monthly_counts), 1) if monthly_counts else None,
                "maxSelectedPerMonth": max(monthly_counts.values()) if monthly_counts else None,
                "tickersEverSelected": len(selection_out),
                "selection": selection_out,
            }, f, ensure_ascii=False, indent=2)

        print(f"  saved: {out_path} ({len(selection_out)} tickers, {len(monthly_counts)} months)")
        print(f"  avg/month: {sum(monthly_counts.values()) / len(monthly_counts):.1f}, max/month: {max(monthly_counts.values()) if monthly_counts else None}")

        # Create policy.json
        policy = {
            "strategyId": strategy_id,
            "version": "1.0",
            "note": f"Single-factor backtest for {factor_name} - top decile" if direction == "high" else f"Single-factor backtest for {factor_name} - bottom decile",
            "direction": "LONG_ONLY",
            "factor": {
                "name": factor_name,
                "direction": direction,
                "rebalanceFrequency": "monthly",
                "decile": "Q10" if direction == "high" else "Q1",
                "sourcePanel": "A4 + valuation-panel + quality-panel + A3/A3b/A3c (PIT)",
                "universe": "A1A_ONLY",
                "liquidityGate": "dv20 >= 1e8 KRW (20d mean trading value)",
            },
            "entry": {
                "timing": "next_tradable_session_open",
                "entryDateField": "next_session(t)",
                "entryPriceField": "Open[entry_date]"
            },
            "risk": {
                "note": "No price-based stop/target - pure time exit",
                "stopDistanceFormula": "entry_price * 100",
                "rewardRisk": 1.0,
                "maxHoldingSessions": 21,
                "timeExitRule": "close of the Nth tradable session counting entry_date as session 1, N = holdSessions for that signal"
            },
            "sameBarRule": "STOP_FIRST",
            "gapRule": "fill at session Open if Open already through stop_price",
            "entryDaySameBarCheck": True,
            "cost": {
                "entryCostBps": 15,
                "exitCostBps": 15,
                "roundTripBps": 30,
                "slippageBps": 0
            },
            "portfolio": {
                "initialCapital": 100_000_000,
                "currency": "KRW",
                "maxPositions": 200,
                "equalWeight": True,
                "fractionalShares": False,
                "sameDayCashReuse": False,
                "tieBreak": "ticker_ascending"
            },
            "universe": {
                "mode": "A1A_ONLY",
                "runClassAllowed": ["SMOKE"]
            },
            "scheduling": {
                "continuousHoldOnRenewal": True,
                "note": "Continuous hold on renewal - same thesis continuing"
            },
            "warmup": {
                "note": "Factor values from monthly panel - no technical warmup"
            }
        }

        with open(os.path.join(output_dir, "policy.json"), "w", encoding="utf-8") as f:
            json.dump(policy, f, ensure_ascii=False, indent=2)

        # Create rule.py
        rule_py = f'''"""Single-factor backtest for {factor_name} ({direction} decile).
Monthly rebalance, top/bottom decile, equal-weight, time-exit only.
"""
import json
import os

import pandas as pd

from engine.signals.schema import RiskSpec, Signal

_THIS_DIR = os.path.dirname(os.path.abspath(__file__))

with open(os.path.join(_THIS_DIR, "policy.json"), encoding="utf-8") as _f:
    PARAMS = json.load(_f)

_HOLD_COL = "holdSessions"
_STOP_MULTIPLE = 100.0
_REWARD_RISK = PARAMS["risk"]["rewardRisk"]
_FALLBACK_MAX_HOLDING = PARAMS["risk"]["maxHoldingSessions"]

with open(os.path.join(_THIS_DIR, "selection.json"), encoding="utf-8") as _f:
    _SELECTION_FILE = json.load(_f)
# ticker -> {{date: holdSessions}}
_SELECTION = {{t: {{e["date"]: e["holdSessions"] for e in entries}}
              for t, entries in _SELECTION_FILE["selection"].items()}}


def compute_features(bars: pd.DataFrame) -> pd.DataFrame:
    features = bars.copy()
    features[_HOLD_COL] = float("nan")
    return features


def generate_signals(symbol: str, features: pd.DataFrame) -> list:
    dates = _SELECTION.get(symbol, {{}})
    out = []
    for d, hold_sessions in dates.items():
        ts = pd.Timestamp(d)
        if ts in features.index:
            features.loc[ts, _HOLD_COL] = hold_sessions
            out.append(Signal(symbol=symbol, signal_date=d, direction="LONG"))
    return out


def risk_spec_for(features_row) -> RiskSpec:
    close = float(features_row["close"])
    huge_stop_distance = close * _STOP_MULTIPLE
    hold = features_row.get(_HOLD_COL)
    max_holding = int(hold) if hold is not None and not pd.isna(hold) else _FALLBACK_MAX_HOLDING
    return RiskSpec(stop_distance=huge_stop_distance, reward_risk=_REWARD_RISK,
                     max_holding_sessions=max_holding)


def evaluate_at(pit_features, symbol: str, date: str, prev_date):
    dates = _SELECTION.get(symbol, {{}})
    if date not in dates:
        return None
    row = pit_features.at(date)
    if row is None:
        return None
    return Signal(symbol=symbol, signal_date=date, direction="LONG")
'''

        with open(os.path.join(output_dir, "rule.py"), "w", encoding="utf-8") as f:
            f.write(rule_py)

        print(f"  created: {output_dir}/{{policy.json, rule.py, selection.json}}")

    print("\n=== All factor selections built ===", flush=True)


if __name__ == "__main__":
    main()