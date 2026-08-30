#!/usr/bin/env python
"""Factor Discovery — KR Research Lab (2026-08-30).

Cross-sectional decile (Q1~Q10) study over the A4 base panel (2016-01 ~ 2026-08),
monthly rebalance, next-1-month forward return, PIT-only fundamentals.

Reuses the Research Lab's established infrastructure exactly:
  - A4 base panel (monthly first-session rebalance, next-day entry, exit next month)
  - premade PIT panels: valuation-panel.jsonl (pbr/per), quality-panel.jsonl (roe/...)
  - raw A3/A3b/A3c annual fundamentals via select_as_of / select_fiscal_year (PIT)
  - rank-based deciles (pd.qcut on .rank(method='first')) — lab convention,
    no ad-hoc value winsorization (matches every prior lab study)
  - cost convention: 15bps/side round-trip = 30bps per monthly rebalance
  - A1a market field -> KOSPI / KOSDAQ split

Factor families:
  Value:       pbr, per(>0), earnings_yield(=1/per)
  Profitability: roe, op_margin, net_margin   (gross-margin/ROA infeasible: no COGS/no total assets)
  Quality:     retention, debt_ratio, current_ratio, roe_consistency, op_margin_trend
  Size:        dv20_log (log 20d mean trading value; marketCap notComputable in A4)
  LowVol/Beta: rv20_pct, rv60_pct, beta12m (vs KOSPI)
  Investment:  equity_growth
  ST Reversal: rev1m (past 21-session return)
  Momentum:    mom3m, mom6m, mom12m, mom12m_skip1m
  Liquidity/Turnover: dv20_log, vv20_log, turnover_ratio_pct (A3c shares PIT)

Outputs:
  reports/2026-08-30-factor-discovery/factor-discovery-results.json
  findings/factor-discovery-kr-2026-08.md  (written by report step)
"""
import bisect
import gzip
import json
import os
import sys
import time

import numpy as np
import pandas as pd
from scipy.stats import spearmanr

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
OUT_DIR = os.path.join(LAB, "reports", "2026-08-30-factor-discovery")
OUT_SUFFIX = ""

MIN_NAMES = 30
COST_BPS = 15.0
ROUNDTRIP_BPS = 2 * COST_BPS           # 30 bps per monthly rebalance
LIQUID_THRESHOLD = 1e8                 # 1e8 KRW = 1eok (lab absolute liquidity gate)
WARM_BETA = 120
LIQUID_GATE_OFF = False

# factor -> (source tag, expected direction for the "good" leg in prose)
FACTOR_ORDER = [
    ("pbr", "valuation-panel", "low"),
    ("per", "valuation-panel", "low"),
    ("earnings_yield", "valuation-panel (1/per, per>0)", "high"),
    ("roe", "quality-panel", "high"),
    ("op_margin", "A3 opProfit/revenue", "high"),
    ("net_margin", "A3 netIncome/revenue", "high"),
    ("retention", "A3b 1-dps/eps", "low"),
    ("debt_ratio", "quality-panel", "low"),
    ("current_ratio", "A3 curAs/curLiab", "high"),
    ("roe_consistency", "quality-panel", "high"),
    ("op_margin_trend", "quality-panel", "high"),
    ("dv20_log", "A4 log 20d mean trading value", "low"),
    ("vv20_log", "A4 log 20d mean volume", "low"),
    ("turnover_ratio_pct", "A3c shares PIT", "high"),
    ("rv20_pct", "A4 std(log ret,20)*100", "low"),
    ("rv60_pct", "A4 std(log ret,60)*100", "low"),
    ("beta12m", "A4 vs KOSPI 252d", "low"),
    ("equity_growth", "A3 equity YoY", "high"),
    ("rev1m", "A4 past 21-session ret", "low"),
    ("mom3m", "A4 past 63-session ret", "high"),
    ("mom6m", "A4 past 126-session ret", "high"),
    ("mom12m", "A4 past 252-session ret", "high"),
    ("mom12m_skip1m", "A4 21..252 session ret", "high"),
]

FACTOR_FAMILY = {
    "pbr": "Value", "per": "Value", "earnings_yield": "Value",
    "roe": "Profitability", "op_margin": "Profitability", "net_margin": "Profitability",
    "retention": "Quality", "debt_ratio": "Quality", "current_ratio": "Quality",
    "roe_consistency": "Quality", "op_margin_trend": "Quality",
    "dv20_log": "Size+Liquidity", "vv20_log": "Liquidity", "turnover_ratio_pct": "Liquidity",
    "rv20_pct": "LowVol+Beta", "rv60_pct": "LowVol+Beta", "beta12m": "LowVol+Beta",
    "equity_growth": "Investment", "rev1m": "ST_Reversal",
    "mom3m": "Momentum", "mom6m": "Momentum", "mom12m": "Momentum", "mom12m_skip1m": "Momentum",
}


def period_of(d, train_end="2022-06-30", valid_end="2024-01-01"):
    return "TRAIN" if d <= train_end else ("VALID" if d <= valid_end else "TEST")


def monthly_reb(dates):
    out, seen = [], set()
    for d in sorted(dates):
        if d[:7] not in seen:
            seen.add(d[:7])
            out.append(d)
    return out


def normd(s):
    s = str(s)
    if len(s) == 8 and s.isdigit():
        return f"{s[:4]}-{s[4:6]}-{s[6:]}"
    return s


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


def agg(recs):
    if not recs:
        return {"n": 0}
    v = np.array(recs, dtype=float)
    sd = float(v.std(ddof=1)) if len(v) > 1 else 0.0
    t = float(v.mean() / (sd / np.sqrt(len(v)))) if sd > 0 else None
    return {"n": len(v), "mean": round(float(v.mean()), 6), "sd": round(sd, 6),
            "t": round(t, 3) if t is not None else None}


def port_stats(monthly_nets):
    if not monthly_nets:
        return {}
    m = np.array(monthly_nets, dtype=float)
    n = len(m)
    eq = float(np.prod(1 + m))
    span = n / 12
    cagr = eq ** (1 / max(span, 1e-9)) - 1 if eq > 0 else (1 + np.sum(m)) ** (1 / max(span, 1e-9)) - 1
    sh = float(m.mean() / m.std(ddof=1) * np.sqrt(12)) if m.std(ddof=1) > 0 else None
    peak, mdd, cum = 1e8, 0.0, 1e8
    for r in m:
        cum *= (1 + r)
        peak = max(peak, cum)
        mdd = min(mdd, cum / peak - 1)
    return {"nMonths": n, "cagr": round(cagr, 4), "sharpe": round(sh, 3) if sh is not None else None,
            "mdd": round(mdd, 4), "meanMonthlyNet": round(float(m.mean()), 5)}


def monthly_spread_stats(spread_months):
    if not spread_months:
        return None
    arr = np.array([s for d, s in spread_months], dtype=float)
    n = len(arr)
    sd = float(arr.std(ddof=1)) if n > 1 else 0.0
    t = float(arr.mean() / (sd / np.sqrt(n))) if sd > 0 else None
    hit = float((arr > 0).mean())
    years = {}
    for (d, s) in spread_months:
        years.setdefault(d[:4], []).append(s)
    yspread = {y: float(np.mean(v)) for y, v in sorted(years.items())}
    pos_year = float(sum(1 for v in yspread.values() if v > 0) / max(len(yspread), 1))
    return {"nMonths": n, "mean": round(float(arr.mean()), 6), "sd": round(sd, 6),
            "t": round(t, 3) if t is not None else None, "hitRate": round(hit, 3),
            "posYearRatio": round(pos_year, 3), "yearly": {y: round(v, 6) for y, v in yspread.items()}}


def decile_analysis(sub, f):
    if sub.empty:
        return None
    pooled = {d: [] for d in range(1, 11)}
    spread_months, ic_months = [], []
    top_net_months, top_gross_months = [], []
    bot_net_months, bot_gross_months = [], []
    ns, names = [], []
    for ddate, g in sub.groupby("date"):
        if len(g) < MIN_NAMES or g[f].nunique() <= 1:
            continue
        g2 = g.copy()
        g2["dec"] = pd.qcut(g2[f].rank(method="first"), 10, labels=False) + 1
        ns.append(len(g2))
        m = g2.groupby("dec")["fwd1m"].mean()
        if 10 in m.index and 1 in m.index:
            spread_months.append((ddate, float(m[10] - m[1])))
        for dec_i, gv in g2.groupby("dec"):
            pooled[int(dec_i)].extend(gv["fwd1m"].tolist())
        top_g = g2.loc[g2["dec"] == 10, "fwd1m"]
        bot_g = g2.loc[g2["dec"] == 1, "fwd1m"]
        if len(top_g):
            top_gross_months.append(float(top_g.mean()))
            top_net_months.append(float(top_g.mean()) - ROUNDTRIP_BPS / 10000)
        if len(bot_g):
            bot_gross_months.append(float(bot_g.mean()))
            bot_net_months.append(float(bot_g.mean()) - ROUNDTRIP_BPS / 10000)
        r = spearmanr(g2[f], g2["fwd1m"])
        if not np.isnan(r.statistic):
            ic_months.append(float(r.statistic))
    dec_tab = {}
    dec_means = []
    for dec_i in range(1, 11):
        vals = np.array(pooled[dec_i], dtype=float)
        if len(vals) == 0:
            dec_tab[dec_i] = {"n": 0}
            continue
        dec_tab[dec_i] = {"n": int(len(vals)),
                          "mean": round(float(vals.mean()), 6),
                          "median": round(float(np.median(vals)), 6)}
        dec_means.append(float(vals.mean()))
    dec_slope = None
    if len(dec_means) == 10:
        r = spearmanr(range(1, 11), dec_means)
        dec_slope = round(float(r.statistic), 3)
    n_obs = int(sub["ticker"].nunique() if False else len(sub))
    out = {
        "n": n_obs, "nMonths": len(ns), "avgNamesPerMonth": round(float(np.mean(ns)), 1) if ns else None,
        "deciles": dec_tab, "decileSlopeSpearman": dec_slope,
        "spread": monthly_spread_stats(spread_months),
        "netSpread": {
            "nMonths": len(spread_months),
            "mean": round(float(np.mean([s - ROUNDTRIP_BPS / 10000 for d, s in spread_months])), 6)
                    if spread_months else None,
            "t": round(float((np.array([s - ROUNDTRIP_BPS / 10000 for d, s in spread_months]).mean() /
                              (np.array([s - ROUNDTRIP_BPS / 10000 for d, s in spread_months]).std(ddof=1)
                               / np.sqrt(len(spread_months))))), 3)
                 if spread_months and len(spread_months) > 1 else None,
        },
        "ic": agg(ic_months),
        "longTopDecile": {"gross": port_stats(top_gross_months), "net": port_stats(top_net_months)},
        "longBottomDecile": {"gross": port_stats(bot_gross_months), "net": port_stats(bot_net_months)},
    }
    return out


def market_split(sub, f):
    out = {}
    for mkt in ["KOSPI", "KOSDAQ"]:
        ss = sub[sub["market"] == mkt]
        spread_months = []
        for ddate, g in ss.groupby("date"):
            if len(g) < MIN_NAMES or g[f].nunique() <= 1:
                continue
            g2 = g.copy()
            g2["dec"] = pd.qcut(g2[f].rank(method="first"), 10, labels=False) + 1
            mm = g2.groupby("dec")["fwd1m"].mean()
            if 10 in mm.index and 1 in mm.index:
                spread_months.append((ddate, float(mm[10] - mm[1])))
        out[mkt] = monthly_spread_stats(spread_months)
        if out[mkt] is not None:
            out[mkt]["n"] = int(len(ss))
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
    """ticker -> sorted list of (asOf, {field: value}) records (asOf <= as_of space)."""
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
                put(REV, r.get("revenue")); put(NI, r.get("netIncome"))
                put(OP, r.get("opProfit")); put(EQ, r.get("equity"))
                put(CA, r.get("currentAssets")); put(CL, r.get("currentLiab"))
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


def main(max_tickers=None):
    t0 = time.time()
    os.makedirs(OUT_DIR, exist_ok=True)
    print("loading A4 ...", flush=True)
    df = pd.read_parquet(A4_PATH, columns=["ticker", "date", "close", "total_amount", "total_volume"])
    df = df.drop_duplicates(subset=["ticker", "date"], keep="last")
    df["date"] = df["date"].astype(str)
    df = df.sort_values(["ticker", "date"]).reset_index(drop=True)
    if max_tickers is not None:
        keep = df["ticker"].drop_duplicates().head(max_tickers)
        df = df[df["ticker"].isin(keep)]
    print(f"  {len(df)} rows, {df['ticker'].nunique()} tickers", flush=True)

    g = df.groupby("ticker", sort=False)
    df["ret"] = g["close"].pct_change()
    df["logret"] = np.log(df["close"] / df["close"].shift(1))
    df["rev1m"] = df["close"] / df["close"].groupby(df["ticker"]).shift(21) - 1
    df["mom3m"] = df["close"] / df["close"].groupby(df["ticker"]).shift(63) - 1
    df["mom6m"] = df["close"] / df["close"].groupby(df["ticker"]).shift(126) - 1
    df["mom12m"] = df["close"] / df["close"].groupby(df["ticker"]).shift(252) - 1
    df["mom12m_skip1m"] = (df["close"].groupby(df["ticker"]).shift(21)
                            / df["close"].groupby(df["ticker"]).shift(252) - 1)
    df["rv20_pct"] = g["logret"].transform(lambda s: s.rolling(20, min_periods=20).std()) * 100
    df["rv60_pct"] = g["logret"].transform(lambda s: s.rolling(60, min_periods=20).std()) * 100
    df["dv20"] = g["total_amount"].transform(lambda s: s.rolling(20, min_periods=20).mean())
    df["vv20"] = g["total_volume"].transform(lambda s: s.rolling(20, min_periods=20).mean())
    df["dv20_log"] = np.log(df["dv20"].clip(lower=1.0))
    df["vv20_log"] = np.log(df["vv20"].clip(lower=1.0))
    df["liquid"] = df["dv20"] >= LIQUID_THRESHOLD

    print("merging KOSPI for beta ...", flush=True)
    kospi = load_kospi()
    df = df.merge(kospi.rename("mk").to_frame(), on="date", how="left")
    df["mktret"] = df["mk"].pct_change()
    df["rs_rm"] = df["ret"] * df["mktret"]
    df["rm2"] = df["mktret"] ** 2
    ma_rs = df.groupby("ticker", sort=False)["ret"].transform(
        lambda s: s.rolling(252, min_periods=WARM_BETA).mean())
    ma_rm = df.groupby("ticker", sort=False)["mktret"].transform(
        lambda s: s.rolling(252, min_periods=WARM_BETA).mean())
    ma_prod = df.groupby("ticker", sort=False)["rs_rm"].transform(
        lambda s: s.rolling(252, min_periods=WARM_BETA).mean())
    ma_rm2 = df.groupby("ticker", sort=False)["rm2"].transform(
        lambda s: s.rolling(252, min_periods=WARM_BETA).mean())
    var = ma_rm2 - ma_rm ** 2
    cov = ma_prod - ma_rs * ma_rm
    df["beta12m"] = np.where(var > 1e-12, cov / var, np.nan)
    df["beta12m"] = df["beta12m"].astype(float)
    df = df.drop(columns=["mk", "mktret", "rs_rm", "rm2", "ret"])
    print(f"  factors done ({time.time()-t0:.0f}s)", flush=True)

    all_dates = sorted(df["date"].unique())
    months = monthly_reb(all_dates)
    base = df[df["date"].isin(months)].copy()
    print(f"base rows {len(base)}, months {len(months)}", flush=True)

    # forward 1-month return: signal at sd close, entry next trading day close,
    # exit next month first trading day close (lab convention).
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
    print(f"  with fwd1m {len(base)} rows ({time.time()-t0:.0f}s)", flush=True)

    market_map = load_market_map()
    base["market"] = base["ticker"].map(market_map)
    base["period"] = base["date"].map(period_of)
    if not LIQUID_GATE_OFF:
        n_pre = len(base)
        base = base[base["liquid"]].copy()
        print(f"  liquidity gate dv20>=1e8: {n_pre} -> {len(base)} rows", flush=True)

    # ---- fundamentals (PIT) ----
    print("loading A3/A3b/A3c ...", flush=True)
    REV, NI, OP, EQ, CA, CL = build_a3_maps()
    a3b = build_a3b_retention()
    a3c = build_a3c_shares()

    def val(rec_map, t, as_of, fy_shift=0):
        recs = rec_map.get(t, [])
        if fy_shift == 0:
            cur = select_as_of(recs, as_of)
            return cur[2] if cur is not None else None
        cur = select_as_of(recs, as_of)
        if cur is None:
            return None
        prev = select_fiscal_year(recs, cur[1] - 1, as_of)
        if prev is None or cur[2] is None or prev[2] is None or prev[2] == 0:
            return None
        return cur[2] / prev[2] - 1.0

    def retention(t, d):
        recs = a3b.get(t, [])
        cur = select_as_of(recs, d)
        if cur is None or cur[2] is None or cur[2] <= 0 or cur[3] is None:
            return None
        return 1.0 - float(cur[3]) / float(cur[2])

    def shares(t, d):
        recs = a3c.get(t, [])
        cur = select_as_of(recs, d)
        if cur is None or cur[1] is None or cur[1] <= 0:
            return None
        return cur[1]

    print("loading premade panels ...", flush=True)
    qdf = load_panel(QUALITY_PANEL, ["roe", "debtRatio", "roeConsistency", "operatingMarginTrend"])
    vdf = load_panel(VALUATION_PANEL, ["pbr", "per"])
    qlook = lambda t, d, f: panel_lookup(qdf, t, d, f)
    vlook = lambda t, d, f: panel_lookup(vdf, t, d, f)

    print("building factor columns ...", flush=True)
    c = {"net_margin": [], "op_margin": [], "current_ratio": [], "equity_growth": [],
         "retention": [], "roe": [], "debt_ratio": [], "roe_consistency": [],
         "op_margin_trend": [], "pbr": [], "per": [], "shares": []}
    for _, rr in base[["ticker", "date"]].iterrows():
        t, d = rr["ticker"], rr["date"]
        ni = val(NI, t, d); rev = val(REV, t, d); op = val(OP, t, d)
        eq = val(EQ, t, d); ca = val(CA, t, d); cl = val(CL, t, d)
        c["net_margin"].append(ni / rev if (ni is not None and rev) else None)
        c["op_margin"].append(op / rev if (op is not None and rev) else None)
        c["current_ratio"].append(ca / cl if (ca is not None and cl) else None)
        c["equity_growth"].append(val(EQ, t, d, 1))
        c["retention"].append(retention(t, d))
        c["roe"].append(qlook(t, d, "roe"))
        c["debt_ratio"].append(qlook(t, d, "debtRatio"))
        c["roe_consistency"].append(qlook(t, d, "roeConsistency"))
        c["op_margin_trend"].append(qlook(t, d, "operatingMarginTrend"))
        c["pbr"].append(vlook(t, d, "pbr"))
        c["per"].append(vlook(t, d, "per"))
        c["shares"].append(shares(t, d))
    for f in c:
        base[f] = c[f]
    base["turnover_ratio_pct"] = base["vv20"].div(base["shares"])
    base["earnings_yield"] = np.where((base["per"].notna()) & (base["per"] > 0),
                                      1.0 / base["per"], np.nan)
    base["per"] = base["per"].where(base["per"] > 0)
    base = base.drop(columns=["shares"])
    print(f"  base columns ready ({time.time()-t0:.0f}s)", flush=True)

    # ---- per-factor decile analysis ----
    print("=== decile analysis ===", flush=True)
    results = {"experiment": "FACTOR-DISCOVERY-KR-2026-08",
               "conventions": {
                   "rebalance": "monthly first session",
                   "entry": "next trading day close (PIT-safe approximation of next-open)",
                   "exit": "next month first session close",
                   "costBpsPerSide": COST_BPS, "roundTripBps": ROUNDTRIP_BPS,
                   "deciles": "cross-sectional per month, rank-based",
                   "winsorization": "none (rank-based deciles, lab convention)",
                   "minNamesPerMonth": MIN_NAMES,
                   "liquidityGate": "dv20>=1e8 KRW (lab standard)" if not LIQUID_GATE_OFF else "off"},
               "factors": {}}
    for f, src, exp_dir in FACTOR_ORDER:
        sub = base[["ticker", "date", "market", "period", "fwd1m", f]].dropna(subset=[f, "fwd1m"])
        res = decile_analysis(sub, f)
        if res is None:
            continue
        res["source"] = src
        res["family"] = FACTOR_FAMILY[f]
        res["expectedGoodDirection"] = exp_dir
        res["coverage"] = round(float(sub["ticker"].nunique()) / max(base["ticker"].nunique(), 1), 3)
        res["nObs"] = int(len(sub))
        res["coverageOfMonths"] = round(float((sub.groupby("date").size() > 0).mean() if len(sub) else 0), 3)
        res["periods"] = {p: int(len(sub[sub["period"] == p])) for p in ["TRAIN", "VALID", "TEST"]}
        res["marketSplit"] = market_split(sub, f)
        results["factors"][f] = res
        sp = res["spread"]
        print(f"  {f:24s} n={res['nObs']:6d} Q10-Q1={sp['mean'] if sp else None:}"
              f" t={sp['t'] if sp else None} hit={sp['hitRate'] if sp else None}"
              f" posYR={sp['posYearRatio'] if sp else None}"
              f" long10Net={res['longTopDecile']['net'].get('cagr') if res['longTopDecile']['net'] else None}",
              flush=True)

    results["baseRows"] = int(len(base))
    results["baseTickers"] = int(base["ticker"].nunique())
    results["months"] = len(months)
    results["executionTime_s"] = round(time.time() - t0, 1)

    out_path = os.path.join(OUT_DIR, f"factor-discovery-results{OUT_SUFFIX}.json")
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(results, f, ensure_ascii=False, indent=1, default=str)
    print(f"\nSaved: {out_path} ({time.time()-t0:.0f}s)", flush=True)


if __name__ == "__main__":
    mt = None
    SUFFIX = ""
    if "--max-tickers" in sys.argv:
        mt = int(sys.argv[sys.argv.index("--max-tickers") + 1])
    if "--no-liquid-gate" in sys.argv:
        LIQUID_GATE_OFF = True
    if "--suffix" in sys.argv:
        OUT_SUFFIX = sys.argv[sys.argv.index("--suffix") + 1]
    main(max_tickers=mt)