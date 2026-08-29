"""Event independence analysis for S1, S3-A, S6 (crypto).
Reuses methodology from crypto-s2-event-independence-2026-08.md.
"""
import json
import os
from collections import defaultdict
from pathlib import Path

import numpy as np
import pandas as pd

REPO = Path(__file__).resolve().parent
RESULTS_JSON = REPO / "findings" / "crypto-community-strategies" / "results.json"
OUT_DIR = REPO / "findings"
CRITERIA_JSON = REPO / "rule_discovery_criteria.json"

UNIVERSE = ["KRW-BTC", "KRW-ETH", "KRW-SOL", "KRW-XRP", "KRW-ADA", "KRW-DOGE", "KRW-DOT"]
TEST_START = "2025-11-02"
TEST_END = "2026-08-27"
INITIAL_CAPITAL = 10_000_000_000.0


def load_criteria():
    with open(CRITERIA_JSON, encoding="utf-8") as f:
        return json.load(f)


def load_strategy_test_data(strategy_uid):
    """Load TEST period trades and metrics for a strategy."""
    with open(RESULTS_JSON) as f:
        data = json.load(f)
    strat = data["strategies"][strategy_uid]
    trades = strat["periods"]["TEST"]["trades"]
    metrics = strat["periods"]["TEST"]["metrics"]
    return trades, metrics


def compute_equity_curve(trades, initial_capital=INITIAL_CAPITAL):
    """Build equity curve from trade list."""
    if not trades:
        return [(pd.Timestamp(TEST_START), initial_capital), (pd.Timestamp(TEST_END), initial_capital)]
    trades_sorted = sorted(trades, key=lambda t: t["exit_date"])
    curve = [(pd.Timestamp(TEST_START), initial_capital)]
    equity = initial_capital
    for t in trades_sorted:
        equity += t["pnl"]
        curve.append((pd.Timestamp(t["exit_date"]), equity))
    return curve


def compute_metrics_from_curve(curve):
    """Compute CAGR, Sharpe, MDD, TotalReturn from equity curve."""
    if len(curve) < 2:
        return {"totalReturn": 0.0, "cagr": 0.0, "sharpe_ann": 0.0, "maxDrawdown": 0.0, "netPnL": 0.0}
    t0, e0 = curve[0]
    t1, e1 = curve[-1]
    years = (t1 - t0).total_seconds() / (365.25 * 86400)
    total_return = e1 / e0 - 1
    cagr = (e1 / e0) ** (1 / years) - 1 if years > 0 and e0 > 0 else 0.0

    eq = np.array([v for _, v in curve])
    rets = eq[1:] / eq[:-1] - 1
    rets = rets[eq[:-1] > 0]
    sharpe = np.mean(rets) / np.std(rets, ddof=1) * np.sqrt(365) if len(rets) > 1 and np.std(rets) > 0 else 0.0

    peak = np.maximum.accumulate(eq)
    mdd = np.min((eq - peak) / peak) if len(eq) > 0 else 0.0

    return {
        "totalReturn": total_return,
        "cagr": cagr,
        "sharpe_ann": sharpe,
        "maxDrawdown": mdd,
        "netPnL": e1 - e0,
    }


def event_decomposition(trades):
    """Group trades by entry date, compute NetPnL per entry day."""
    by_date = defaultdict(list)
    for t in trades:
        entry_date = pd.Timestamp(t["entry_date"]).date()
        by_date[entry_date].append(t)

    total_pnl = sum(t["pnl"] for t in trades)
    rows = []
    for d in sorted(by_date.keys()):
        day_trades = by_date[d]
        symbols = ", ".join(sorted(set(t["symbol"] for t in day_trades)))
        n = len(day_trades)
        day_pnl = sum(t["pnl"] for t in day_trades)
        pct = (day_pnl / total_pnl * 100) if total_pnl != 0 else 0
        rows.append({
            "entry_date": d,
            "symbols": symbols,
            "trade_count": n,
            "net_pnl": day_pnl,
            "pct_of_total": pct,
        })
    return rows, total_pnl


def leave_one_event_out(trades):
    """Remove all trades from one entry date, recompute metrics."""
    by_date = defaultdict(list)
    for t in trades:
        entry_date = pd.Timestamp(t["entry_date"]).date()
        by_date[entry_date].append(t)

    baseline_curve = compute_equity_curve(trades)
    baseline = compute_metrics_from_curve(baseline_curve)

    results = [{"excluded": "baseline", **baseline}]
    for d in sorted(by_date.keys()):
        remaining = [t for t in trades if pd.Timestamp(t["entry_date"]).date() != d]
        curve = compute_equity_curve(remaining)
        m = compute_metrics_from_curve(curve)
        results.append({"excluded": str(d), **m})
    return results


def leave_one_asset_out(trades):
    """Remove all trades from one symbol, recompute metrics."""
    baseline_curve = compute_equity_curve(trades)
    baseline = compute_metrics_from_curve(baseline_curve)

    results = [{"excluded": "baseline", **baseline, "trade_count": len(trades)}]
    for sym in UNIVERSE:
        remaining = [t for t in trades if t["symbol"] != sym]
        curve = compute_equity_curve(remaining)
        m = compute_metrics_from_curve(curve)
        m["trade_count"] = len(remaining)
        results.append({"excluded": sym, **m})
    return results


def cluster_decomposition(trades):
    """Separate cluster days (>=2 symbols same entry date) vs solo days."""
    by_date = defaultdict(list)
    for t in trades:
        entry_date = pd.Timestamp(t["entry_date"]).date()
        by_date[entry_date].append(t)

    clusters = []
    solo = []
    total_pnl = sum(t["pnl"] for t in trades)

    for d in sorted(by_date.keys()):
        day_trades = by_date[d]
        symbols = set(t["symbol"] for t in day_trades)
        day_pnl = sum(t["pnl"] for t in day_trades)
        pct = (day_pnl / total_pnl * 100) if total_pnl != 0 else 0
        row = {
            "entry_date": d,
            "symbols": ", ".join(sorted(symbols)),
            "trade_count": len(day_trades),
            "net_pnl": day_pnl,
            "pct_of_total": pct,
        }
        if len(symbols) >= 2:
            clusters.append(row)
        else:
            solo.append(row)

    cluster_pnl = sum(r["net_pnl"] for r in clusters)
    solo_pnl = sum(r["net_pnl"] for r in solo)
    return clusters, solo, cluster_pnl, solo_pnl, total_pnl


def check_sign_flip(loo_results, baseline_cagr):
    """Check if removing any single event flips the sign of CAGR."""
    for r in loo_results:
        if r["excluded"] != "baseline":
            if (baseline_cagr > 0 and r["cagr"] < 0) or (baseline_cagr < 0 and r["cagr"] > 0):
                return True, r["excluded"], r["cagr"]
    return False, None, None


def check_asset_sign_flip(loo_results, baseline_cagr):
    """Check if removing any single asset flips the sign of CAGR."""
    for r in loo_results:
        if r["excluded"] != "baseline":
            if (baseline_cagr > 0 and r["cagr"] < 0) or (baseline_cagr < 0 and r["cagr"] > 0):
                return True, r["excluded"], r["cagr"]
    return False, None, None


def apply_verdict(criteria, strategy_id, trades, baseline_metrics, event_flip, asset_flip, max_event_pct):
    """Apply rule_discovery_criteria.json to determine KEEP/HOLD/REJECT."""
    n = len(trades)
    min_test = criteria["thresholds"]["min_sample_size"]["test"]
    max_single_pct_reject = criteria["thresholds"]["concentration"]["max_single_year_pct_for_auto_reject"]
    max_single_pct_keep = criteria["thresholds"]["concentration"]["max_single_year_pct_for_auto_keep"]

    # Check min sample size
    if n < min_test:
        return "HOLD", f"Sample size N={n} < min_test={min_test}"

    # Check concentration gate (event flip or asset flip or max single event pct)
    if event_flip:
        return "REJECT", "Single event removal flips CAGR sign"
    if asset_flip:
        return "REJECT", "Single asset removal flips CAGR sign"
    if max_event_pct >= max_single_pct_reject:
        return "REJECT", f"Max single event contribution {max_event_pct:.1f}% >= {max_single_pct_reject}%"
    if max_event_pct >= max_single_pct_keep:
        return "HOLD", f"Max single event contribution {max_event_pct:.1f}% in [{max_single_pct_keep}-{max_single_pct_reject})% range"

    return "KEEP", "Passes concentration and sample size gates"


def format_markdown_table(headers, rows):
    """Format a list of dicts as markdown table."""
    if not rows:
        return ""
    # Ensure all rows have all headers
    for r in rows:
        for h in headers:
            if h not in r:
                r[h] = ""
    # Header
    out = "| " + " | ".join(headers) + " |\n"
    out += "| " + " | ".join(["---"] * len(headers)) + " |\n"
    for r in rows:
        out += "| " + " | ".join(str(r.get(h, "")) for h in headers) + " |\n"
    return out


def analyze_strategy(strategy_uid, strategy_name, factor_name):
    """Run full event independence analysis for one strategy."""
    print(f"\n=== Analyzing {strategy_name} ({strategy_uid}) ===")

    trades, baseline_metrics = load_strategy_test_data(strategy_uid)
    print(f"  TEST trades: {len(trades)}")
    print(f"  Baseline: CAGR={baseline_metrics['cagr']:.4f} Sharpe={baseline_metrics['sharpe_ann']:.4f} MDD={baseline_metrics['maxDrawdown']:.4f} NetPnL={sum(t['pnl'] for t in trades):.0f}")

    # 1. Event-date decomposition
    event_rows, total_pnl = event_decomposition(trades)
    print(f"  Entry dates: {len(event_rows)}")

    # 2. Leave-one-event-out
    loo_event = leave_one_event_out(trades)
    event_flip, flip_event, flip_cagr = check_sign_flip(loo_event, baseline_metrics["cagr"])
    print(f"  Event sign flip: {event_flip} ({flip_event} -> CAGR={flip_cagr:.4f})" if event_flip else f"  Event sign flip: {event_flip}")

    # 3. Leave-one-asset-out
    loo_asset = leave_one_asset_out(trades)
    asset_flip, flip_asset, flip_cagr_a = check_asset_sign_flip(loo_asset, baseline_metrics["cagr"])
    print(f"  Asset sign flip: {asset_flip} ({flip_asset} -> CAGR={flip_cagr_a:.4f})" if asset_flip else f"  Asset sign flip: {asset_flip}")

    # 4. Cluster decomposition
    clusters, solo, cluster_pnl, solo_pnl, total_pnl = cluster_decomposition(trades)
    print(f"  Clusters: {len(clusters)}, Solo: {len(solo)}")
    print(f"  Cluster PnL: {cluster_pnl:.0f} ({cluster_pnl/total_pnl*100:.1f}%), Solo PnL: {solo_pnl:.0f} ({solo_pnl/total_pnl*100:.1f}%)")

    # Max single event contribution
    max_event_pct = max(abs(r["pct_of_total"]) for r in event_rows) if event_rows else 0

    # Apply verdict
    criteria = load_criteria()
    verdict, reason = apply_verdict(criteria, strategy_uid, trades, baseline_metrics, event_flip, asset_flip, max_event_pct)
    print(f"  Verdict: {verdict} - {reason}")

    # Build markdown output
    md = []

    # Frontmatter
    md.append("---")
    md.append(f"track: crypto")
    md.append(f"factor: {factor_name}")
    md.append(f"date: 2026-08-29")
    md.append(f"verdict: {verdict}")
    md.append(f"criteria_version: v1")
    md.append(f"conditions: [\"{strategy_name} rules (baseline params, no optimization)\"]")
    md.append(f"cagr: {baseline_metrics['cagr']:.4f}")
    md.append(f"sharpe: {baseline_metrics['sharpe_ann']:.4f}")
    md.append(f"mdd: {baseline_metrics['maxDrawdown']:.4f}")
    md.append(f"n: {len(trades)}")
    md.append("---")
    md.append("")

    # 1. Event-date decomposition
    md.append("## 1. TEST event-date decomposition")
    md.append("")
    headers = ["진입일", "종목", "거래수", "합산 NetPnL(M)", "전체 대비 기여(%)"]
    rows = []
    for r in event_rows:
        rows.append({
            "진입일": str(r["entry_date"]),
            "종목": r["symbols"],
            "거래수": r["trade_count"],
            "합산 NetPnL(M)": round(r["net_pnl"] / 1_000_000),
            "전체 대비 기여(%)": round(r["pct_of_total"], 1),
        })
    rows.append({
        "진입일": "**합계**",
        "종목": "",
        "거래수": sum(r["trade_count"] for r in event_rows),
        "합산 NetPnL(M)": round(total_pnl / 1_000_000),
        "전체 대비 기여(%)": 100.0,
    })
    md.append(format_markdown_table(headers, rows))
    md.append("")

    # 2. Leave-one-event-out
    md.append("## 2. Leave-one-event-out (TEST) — 진입일 하나씩 제거")
    md.append("")
    headers = ["제외 진입일", "Total Return", "CAGR", "Sharpe", "MDD", "Net PnL(M)"]
    rows = []
    for r in loo_event:
        rows.append({
            "제외 진입일": r["excluded"],
            "Total Return": f"{r['totalReturn']*100:.2f}%",
            "CAGR": f"{r['cagr']*100:.2f}%",
            "Sharpe": f"{r['sharpe_ann']:.2f}",
            "MDD": f"{r['maxDrawdown']*100:.2f}%",
            "Net PnL(M)": round(r["netPnL"] / 1_000_000),
        })
    md.append(format_markdown_table(headers, rows))
    md.append("")

    # 3. Leave-one-asset-out
    md.append("## 3. Leave-one-asset-out (TEST) — 코인 하나씩 제외")
    md.append("")
    headers = ["제외 코인", "Total Return", "CAGR", "Sharpe", "MDD", "Net PnL(M)", "거래수"]
    rows = []
    for r in loo_asset:
        rows.append({
            "제외 코인": r["excluded"],
            "Total Return": f"{r['totalReturn']*100:.2f}%",
            "CAGR": f"{r['cagr']*100:.2f}%",
            "Sharpe": f"{r['sharpe_ann']:.2f}",
            "MDD": f"{r['maxDrawdown']*100:.2f}%",
            "Net PnL(M)": round(r["netPnL"] / 1_000_000),
            "거래수": r["trade_count"],
        })
    md.append(format_markdown_table(headers, rows))
    md.append("")

    # 4. Cluster decomposition
    md.append("## 4. Cluster decomposition (TEST)")
    md.append("")
    md.append(f"- cluster = 같은 진입일에 2개 이상 코인이 동시 진입")
    md.append(f"- 클러스터 수: {len(clusters)}")
    md.append(f"- 클러스터 합산 NetPnL: {cluster_pnl/1_000_000:.0f}M (전체 {cluster_pnl/total_pnl*100:.0f}%)")
    md.append(f"- 단독 진입 거래일 수: {len(solo)}")
    md.append(f"- 단독 진입 합산 NetPnL: {solo_pnl/1_000_000:.0f}M (전체 {solo_pnl/total_pnl*100:.0f}%)")
    md.append("")
    if clusters:
        md.append("| cluster | 종목 | 거래수 | NetPnL(M) | 기여(%) |")
        md.append("|---------|------|-------|-----------|--------|")
        for c in clusters:
            md.append(f"| {c['entry_date']} | {c['symbols']} | {c['trade_count']} | {c['net_pnl']/1_000_000:.0f} | {c['pct_of_total']:.0f}% |")
        md.append("")
    if solo:
        md.append("- 단독 진입 거래: " + ", ".join(f"{s['entry_date']} {s['symbols']} {s['net_pnl']/1_000_000:.0f}M" for s in solo))
        md.append("")

    # 5. Final verdict
    md.append("## 5. 최종 판정")
    md.append("")
    md.append(f"**전략**: {strategy_name}")
    md.append(f"**TEST 기준선**: TotalReturn {baseline_metrics['totalReturn']*100:.2f}% / CAGR {baseline_metrics['cagr']*100:.2f}% / Sharpe {baseline_metrics['sharpe_ann']:.2f} / MDD {baseline_metrics['maxDrawdown']*100:.2f}% / NetPnL {sum(t['pnl'] for t in trades)/1_000_000:.0f}M / N={len(trades)}")
    md.append("")
    if event_flip:
        md.append(f"(1) **{flip_event} 제거 시**: CAGR {flip_cagr*100:.2f}% — **부호 반전**")
    if asset_flip:
        md.append(f"(2) **{flip_asset} 제거 시**: CAGR {flip_cagr_a*100:.2f}% — **부호 반전**")
    md.append(f"(3) 최대 단일 이벤트 기여: {max_event_pct:.1f}%")
    md.append(f"(4) 표본 크기: N={len(trades)} (min_test={criteria['thresholds']['min_sample_size']['test']})")
    md.append("")
    md.append(f"### 판정: **{verdict}** ({reason})")
    md.append("")

    return "\n".join(md), verdict, event_flip, asset_flip, max_event_pct, flip_event, flip_asset


def main():
    strategies = [
        ("bb_squeeze_v1:D", "S1 bb_squeeze_v1", "s1-event-independence"),
        ("bb_breakout_trend_A:D", "S3-A bb_breakout_trend_A", "s3a-event-independence"),
        ("price_action_v1:D", "S6 price_action_v1", "s6-event-independence"),
    ]

    summaries = []
    for uid, name, factor in strategies:
        md, verdict, event_flip, asset_flip, max_pct, flip_event, flip_asset = analyze_strategy(uid, name, factor)

        # Write finding file
        out_file = OUT_DIR / f"crypto-{factor}-2026-08.md"
        with open(out_file, "w", encoding="utf-8") as f:
            f.write(md)
        print(f"  Written: {out_file}")

        # Summary line
        flip_info = []
        if event_flip:
            flip_info.append(f"이벤트:{flip_event}반전")
        if asset_flip:
            flip_info.append(f"자산:{flip_asset}반전")
        flip_str = ", ".join(flip_info) if flip_info else "반전없음"
        summaries.append(f"{name} -> {verdict}, 최대기여 {max_pct:.1f}%, {flip_str}")

    print("\n=== SUMMARY ===")
    for s in summaries:
        print(s)


if __name__ == "__main__":
    main()