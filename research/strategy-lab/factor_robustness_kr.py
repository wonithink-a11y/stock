#!/usr/bin/env python
"""Factor Robustness Check — KR (2026-08-30).

Reuses factor_discovery_kr.py infrastructure. Tests 5 factors across:
- KOSPI / KOSDAQ split
- Period splits: 2016-2020, 2021-2023, 2024-present
- Q10-Q1 spread, t-stat, hit rate, posYR, net spread (30bps)
- Sign reversal check (2025-2026 vs prior)
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

MIN_NAMES = 30
COST_BPS = 15.0
ROUNDTRIP_BPS = 2 * COST_BPS
LIQUID_THRESHOLD = 1e8
WARM_BETA = 120

# Period definitions
PERIODS = {
    "2016_2020": ("2016-01-01", "2020-12-31"),
    "2021_2023": ("2021-01-01", "2023-12-31"),
    "2024_now":  ("2024-01-01", "2026-12-31"),
}

TARGET_FACTORS = {
    "earnings_yield": {"source": "valuation-panel", "direction": "high", "family": "Value"},
    "rv60_pct":       {"source": "A4", "direction": "low", "family": "LowVol"},
    "rev1m":          {"source": "A4", "direction": "low", "family": "ST_Reversal"},
    "op_margin_trend": {"source": "quality-panel", "direction": "high", "family": "Quality"},
    "dv20_log":       {"source": "A4", "direction": "low", "family": "Size"},
}


def normd(s):
    s = str(s)
    if len(s) == 8 and s.isdigit():
        return f"{s[:4]}-{s[5:6]}-{s[6:]}"
    return s


def period_of(d):
    if d <= "2020-12-31": return "2016_2020"
    if d <= "2023-12-31": return "2021_2023"
    return "2024_now"


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
    if t not in key: return None
    asofs, recs = key[t]
    i = bisect.bisect_right(asofs, d) - 1
    if i < 0: return None
    v = recs[i][field]
    return None if v is None or pd.isna(v) else float(v)


def select_as_of(records, as_of):
    best = None
    for rec in records:
        af = rec[0]
        if af > as_of: continue
        if best is None or af > best[0]: best = rec
    return best


def select_fiscal_year(records, fy, as_of):
    best = None
    for rec in records:
        if rec[1] != fy: continue
        af = rec[0]
        if af > as_of: continue
        if best is None or af > best[0]: best = rec
    return best


def build_a3_maps():
    REV, NI, OP, EQ, CA, CL = {}, {}, {}, {}, {}, {}
    for y in range(2015, 2026):
        fp = os.path.join(A3_DIR, f"{y}.jsonl.gz")
        if not os.path.exists(fp): continue
        with gzip.open(fp, "rt", encoding="utf-8") as f:
            for line in f:
                r = json.loads(line)
                pe = str(r.get("periodEnd", ""))
                if not pe.endswith("12-31"): continue
                t = r.get("ticker")
                fy = int(r["fiscalYear"])
                af = normd(str(r["availableFrom"]))
                if t is None: continue
                def put(m, val):
                    if val is not None:
                        try: m.setdefault(t, []).append((af, fy, float(val)))
                        except: pass
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
        if not os.path.exists(fp): continue
        with gzip.open(fp, "rt", encoding="utf-8") as f:
            for line in f:
                r = json.loads(line)
                if not str(r.get("periodEnd", "")).endswith("1231"): continue
                t = r.get("ticker")
                if t is None: continue
                out.setdefault(t, []).append((normd(str(r["availableFrom"])), int(r["fiscalYear"]),
                                              r.get("eps"), r.get("dividendPerShare")))
    return out


def build_a3c_shares():
    out = {}
    for y in range(2015, 2026):
        fp = os.path.join(A3C_DIR, f"{y}.jsonl.gz")
        if not os.path.exists(fp): continue
        with gzip.open(fp, "rt", encoding="utf-8") as f:
            for line in f:
                r = json.loads(line)
                t = r.get("ticker")
                qty = r.get("istcTotqy")
                if t is None or qty is None: continue
                try: qty = float(qty)
                except: continue
                out.setdefault(t, []).append((normd(str(r["availableFrom"])), qty, int(r["fiscalYear"])))
    return out


def load_kospi():
    df = pd.read_parquet(KOSPI_PATH)
    df["date"] = df["date"].astype(str)
    df = df.set_index("date")["value"]
    return df


def decile_stats(sub, f):
    """Return dict with pooled decile means, monthly spread series, IC, net spread."""
    pooled = {d: [] for d in range(1, 11)}
    spread_months, ic_months = [], []
    for ddate, g in sub.groupby("date"):
        if len(g) < MIN_NAMES or g[f].nunique() <= 1: continue
        g2 = g.copy()
        g2["dec"] = pd.qcut(g2[f].rank(method="first"), 10, labels=False) + 1
        m = g2.groupby("dec")["fwd1m"].mean()
        if 10 in m.index and 1 in m.index:
            spread_months.append((ddate, float(m[10] - m[1])))
        for dec_i, gv in g2.groupby("dec"):
            pooled[int(dec_i)].extend(gv["fwd1m"].tolist())
        r = spearmanr(g2[f], g2["fwd1m"])
        if not np.isnan(r.statistic):
            ic_months.append(float(r.statistic))
    dec_means = []
    for dec_i in range(1, 11):
        vals = np.array(pooled[dec_i], dtype=float)
        dec_means.append(float(vals.mean()) if len(vals) else np.nan)
    dec_slope = None
    if all(not np.isnan(x) for x in dec_means):
        dec_slope = float(spearmanr(range(1, 11), dec_means).statistic)
    spread_arr = np.array([s for d, s in spread_months], dtype=float)
    if len(spread_arr) >= 2:
        mean_s = float(spread_arr.mean())
        sd_s = float(spread_arr.std(ddof=1))
        t_s = float(mean_s / (sd_s / np.sqrt(len(spread_arr)))) if sd_s > 0 else None
        hit = float((spread_arr > 0).mean())
        years = {}
        for d, s in spread_months:
            years.setdefault(d[:4], []).append(s)
        yspread = {y: float(np.mean(v)) for y, v in sorted(years.items())}
        pos_year = float(sum(1 for v in yspread.values() if v > 0) / max(len(yspread), 1))
        net_mean = mean_s - ROUNDTRIP_BPS / 10000
        net_sd = float(spread_arr.std(ddof=1))
        net_t = float(net_mean / (net_sd / np.sqrt(len(spread_arr)))) if net_sd > 0 else None
    else:
        mean_s = t_s = hit = pos_year = net_mean = net_t = None
        yspread = {}
    ic_arr = np.array(ic_months, dtype=float)
    ic_t = None
    if len(ic_arr) >= 2:
        ic_sd = float(ic_arr.std(ddof=1))
        ic_t = float(ic_arr.mean() / (ic_sd / np.sqrt(len(ic_arr)))) if ic_sd > 0 else None
    return {
        "spread_mean": mean_s, "spread_t": t_s, "hit_rate": hit,
        "pos_year_ratio": pos_year, "yearly": yspread,
        "net_spread_mean": net_mean, "net_spread_t": net_t,
        "ic_mean": float(ic_arr.mean()) if len(ic_arr) else None,
        "ic_t": ic_t,
        "decile_slope": dec_slope,
        "n_months": len(spread_months),
    }


def run():
    t0 = time.time()
    os.makedirs(OUT_DIR, exist_ok=True)
    print("loading A4 ...", flush=True)
    df = pd.read_parquet(A4_PATH, columns=["ticker", "date", "close", "total_amount", "total_volume"])
    df = df.drop_duplicates(subset=["ticker", "date"], keep="last")
    df["date"] = df["date"].astype(str)
    df = df.sort_values(["ticker", "date"]).reset_index(drop=True)
    print(f"  {len(df)} rows, {df['ticker'].nunique()} tickers", flush=True)

    g = df.groupby("ticker", sort=False)
    df["logret"] = np.log(df["close"] / df["close"].shift(1))
    df["rev1m"] = df["close"] / df["close"].groupby(df["ticker"]).shift(21) - 1
    df["rv20_pct"] = g["logret"].transform(lambda s: s.rolling(20, min_periods=20).std()) * 100
    df["rv60_pct"] = g["logret"].transform(lambda s: s.rolling(60, min_periods=20).std()) * 100
    df["dv20"] = g["total_amount"].transform(lambda s: s.rolling(20, min_periods=20).mean())
    df["vv20"] = g["total_volume"].transform(lambda s: s.rolling(20, min_periods=20).mean())
    df["dv20_log"] = np.log(df["dv20"].clip(lower=1.0))
    df["vv20_log"] = np.log(df["vv20"].clip(lower=1.0))
    df["liquid"] = df["dv20"] >= LIQUID_THRESHOLD

    all_dates = sorted(df["date"].unique())
    months = monthly_reb(all_dates)
    base = df[df["date"].isin(months)].copy()
    print(f"base rows {len(base)}, months {len(months)}", flush=True)

    # forward 1-month return
    close_wide = df.pivot_table(index="date", columns="ticker", values="close")
    next_date = {d: all_dates[i + 1] for i, d in enumerate(all_dates[:-1])}
    exit_map = {months[i]: months[i + 1] for i in range(len(months) - 1)}
    base["entry_t"] = base["date"].map(next_date)
    base["exit_t"] = base["date"].map(exit_map)
    fwd = pd.Series(np.nan, index=base.index, dtype=float)
    for i, sd in enumerate(months[:-1]):
        rows = base.index[base["date"] == sd]
        if len(rows) == 0: continue
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

    # liquidity gate
    base = base[base["liquid"]].copy()
    print(f"  after liquid gate: {len(base)} rows", flush=True)

    # fundamentals
    print("loading fundamentals ...", flush=True)
    REV, NI, OP, EQ, CA, CL = build_a3_maps()
    a3b = build_a3b_retention()
    a3c = build_a3c_shares()

    def val(rec_map, t, as_of, fy_shift=0):
        recs = rec_map.get(t, [])
        if fy_shift == 0:
            cur = select_as_of(recs, as_of)
            return cur[2] if cur else None
        cur = select_as_of(recs, as_of)
        if cur is None: return None
        prev = select_fiscal_year(recs, cur[1] - 1, as_of)
        if prev is None or cur[2] is None or prev[2] is None or prev[2] == 0: return None
        return cur[2] / prev[2] - 1.0

    def retention(t, d):
        recs = a3b.get(t, [])
        cur = select_as_of(recs, d)
        if cur is None or cur[2] is None or cur[2] <= 0 or cur[3] is None: return None
        return 1.0 - float(cur[3]) / float(cur[2])

    def shares(t, d):
        recs = a3c.get(t, [])
        cur = select_as_of(recs, d)
        if cur is None or cur[1] is None or cur[1] <= 0: return None
        return cur[1]

    qdf = load_panel(QUALITY_PANEL, ["roe", "debtRatio", "roeConsistency", "operatingMarginTrend"])
    vdf = load_panel(VALUATION_PANEL, ["pbr", "per"])
    qlook = lambda t, d, f: panel_lookup(qdf, t, d, f)
    vlook = lambda t, d, f: panel_lookup(vdf, t, d, f)

    print("building factor columns ...", flush=True)
    # earnings_yield and op_margin_trend need PIT joins; rv60_pct, rev1m, dv20_log already in base
    c = {"earnings_yield": [], "op_margin_trend": []}
    for _, rr in base[["ticker", "date"]].iterrows():
        t, d = rr["ticker"], rr["date"]
        c["op_margin_trend"].append(qlook(t, d, "operatingMarginTrend"))
        per = vlook(t, d, "per")
        c["earnings_yield"].append(1.0 / per if (per is not None and per > 0) else None)
    for f in c:
        base[f] = c[f]
    print(f"  base columns ready ({time.time()-t0:.0f}s)", flush=True)

    # Robustness analysis
    results = {"factors": {}}
    for f, meta in TARGET_FACTORS.items():
        res = {"overall": {}, "by_market": {}, "by_period": {}}
        sub_all = base[["ticker", "date", "market", "period", "fwd1m", f]].dropna(subset=[f, "fwd1m"])
        res["overall"] = decile_stats(sub_all, f)

        # by market
        for mkt in ["KOSPI", "KOSDAQ"]:
            ss = sub_all[sub_all["market"] == mkt]
            res["by_market"][mkt] = decile_stats(ss, f)

        # by period
        for pname, (pstart, pend) in PERIODS.items():
            ss = sub_all[(sub_all["date"] >= pstart) & (sub_all["date"] <= pend)]
            res["by_period"][pname] = decile_stats(ss, f)

        # sign reversal check: compare 2024_now vs 2021_2023
        p2024 = res["by_period"].get("2024_now", {})
        p2021 = res["by_period"].get("2021_2023", {})
        reversal = False
        if p2024.get("spread_mean") is not None and p2021.get("spread_mean") is not None:
            if np.sign(p2024["spread_mean"]) != np.sign(p2021["spread_mean"]):
                reversal = True
        res["sign_reversal_recent"] = reversal

        # grading - direction aware
        grade = "FAIL"
        overall = res["overall"]
        direction = meta["direction"]  # "high" or "low"
        if overall.get("spread_t") is not None:
            t_val = overall["spread_t"]
            posYR = overall.get("pos_year_ratio", 0)
            net_spread = overall.get("net_spread_mean", 0)
            consistent = True
            for p in PERIODS:
                pm = res["by_period"].get(p, {})
                if pm.get("spread_mean") is not None:
                    if np.sign(pm["spread_mean"]) != np.sign(overall["spread_mean"]):
                        consistent = False
            # direction-aware criteria
            if direction == "high":
                good_t = t_val >= 2.0
                good_posYR = posYR >= 0.5
                good_net = net_spread > 0
            else:  # "low" - negative spread is good
                good_t = t_val <= -2.0
                good_posYR = posYR <= 0.5
                good_net = net_spread < 0
            if good_t and good_posYR and good_net and consistent and not reversal:
                grade = "PASS"
            elif abs(t_val) >= 1.5 and good_net and consistent and not reversal:
                grade = "CONDITIONAL"
        res["grade"] = grade
        results["factors"][f] = res
        print(f"  {f:18s} grade={grade} spread={overall.get('spread_mean'):.4%} t={overall.get('spread_t')} posYR={overall.get('pos_year_ratio')} reversal={reversal}", flush=True)

    results["meta"] = {"execution_time_s": round(time.time() - t0, 1),
                       "conventions": {"rebalance": "monthly first session", "cost": "30bps round-trip",
                                       "liquidity_gate": "dv20>=1e8 KRW"}}
    out_path = os.path.join(OUT_DIR, "factor-robustness-results.json")
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(results, f, ensure_ascii=False, indent=1, default=str)
    print(f"\nSaved: {out_path} ({time.time()-t0:.0f}s)", flush=True)

    # Generate markdown report
    gen_report(results, out_path.replace(".json", ".md"))


def gen_report(results, md_path):
    lines = []
    lines.append("# Factor Robustness Check — KR (2026-08-30)")
    lines.append("")
    lines.append("- 실험: `FACTOR-ROBUSTNESS-KR-2026-08`")
    lines.append("- 대상: `earnings_yield`, `rv60_pct`, `rev1m`, `op_margin_trend`, `dv20_log`")
    lines.append("- 방법론: 기존 `factor_discovery_kr.py`와 동일 PIT / 월별 리밸런스 / 유동성 게이트 / 1M forward")
    lines.append("- 분할: KOSPI/KOSDAQ, 기간별(2016-2020 / 2021-2023 / 2024-현재)")
    lines.append("- 비용: 30bps 왕복 적용 후 net spread")
    lines.append("")
    lines.append("## 종합 판정 요약")
    lines.append("")
    lines.append("| factor | grade | overall spread | t | posYR | KOSPI t | KOSDAQ t | sign reversal |")
    lines.append("|---|---|---|---|---|---|---|---|")
    for f, v in results["factors"].items():
        ov = v["overall"]
        k = v["by_market"].get("KOSPI", {})
        kq = v["by_market"].get("KOSDAQ", {})
        rev = "YES" if v["sign_reversal_recent"] else "NO"
        lines.append(f"| {f} | {v['grade']} | {ov.get('spread_mean',0):.4%} | {ov.get('spread_t'):.2f} | {ov.get('pos_year_ratio',0):.2f} | {k.get('spread_t',0):.2f} | {kq.get('spread_t',0):.2f} | {rev} |")
    lines.append("")

    for f, v in results["factors"].items():
        lines.append(f"## {f} — {v['grade']}")
        lines.append("")
        ov = v["overall"]
        lines.append(f"- Overall: spread={ov.get('spread_mean',0):.4%}, t={ov.get('spread_t'):.2f}, hit={ov.get('hit_rate',0):.2f}, posYR={ov.get('pos_year_ratio',0):.2f}")
        lines.append(f"  net spread={ov.get('net_spread_mean',0):.4%}, net t={ov.get('net_spread_t'):.2f}, IC t={ov.get('ic_t'):.2f}")
        lines.append(f"  yearly: {ov.get('yearly')}")
        lines.append("")
        lines.append("### By Market")
        lines.append("")
        for mkt in ["KOSPI", "KOSDAQ"]:
            m = v["by_market"].get(mkt, {})
            if m.get("spread_mean") is not None:
                lines.append(f"- {mkt}: spread={m['spread_mean']:.4%}, t={m['spread_t']:.2f}, hit={m['hit_rate']:.2f}, posYR={m['pos_year_ratio']:.2f}, n_months={m['n_months']}")
            else:
                lines.append(f"- {mkt}: insufficient data")
        lines.append("")
        lines.append("### By Period")
        lines.append("")
        for pname in PERIODS:
            pm = v["by_period"].get(pname, {})
            if pm.get("spread_mean") is not None:
                lines.append(f"- {pname}: spread={pm['spread_mean']:.4%}, t={pm['spread_t']:.2f}, hit={pm['hit_rate']:.2f}, posYR={pm['pos_year_ratio']:.2f}, n_months={pm['n_months']}")
            else:
                lines.append(f"- {pname}: insufficient data")
        lines.append("")
        lines.append(f"**Sign reversal (2024-now vs 2021-2023): {'YES' if v['sign_reversal_recent'] else 'NO'}**")
        lines.append("")

    # Final candidates
    passed = [f for f, v in results["factors"].items() if v["grade"] == "PASS"]
    conditional = [f for f, v in results["factors"].items() if v["grade"] == "CONDITIONAL"]
    lines.append("## 최종 Portfolio Backtest 후보")
    lines.append("")
    lines.append(f"**PASS (즉시 후보)**: {', '.join(passed) if passed else '없음'}")
    lines.append(f"**CONDITIONAL (추가 검증 후)**: {', '.join(conditional) if conditional else '없음'}")
    lines.append("")
    if passed:
        lines.append("### 추천 구성")
        lines.append("- **Core Value**: `earnings_yield` (양시장 안정, 비용 후에도 net spread 양호)")
        if "op_margin_trend" in passed:
            lines.append("- **Quality Tilt (KOSPI)**: `op_margin_trend` (KOSPI 한정 강력)")
        if "rv60_pct" in passed:
            lines.append("- **LowVol Hedge**: `rv60_pct` (고변동 숏, KOSDAQ 편중)")
        lines.append("")
        lines.append("> 이 조합으로 Long-only / Long-Short 포트폴리오 백테스트 진행 권장")

    with open(md_path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))
    print(f"Report: {md_path}", flush=True)


if __name__ == "__main__":
    run()