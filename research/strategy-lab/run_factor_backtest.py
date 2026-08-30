#!/usr/bin/env python
"""Run single-factor backtests for Step 3 factors - optimized version."""
import json
import os
import sys
import time

import numpy as np

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(REPO_ROOT, "research", "strategy-lab"))

from engine.runner import run_smoke


def compute_metrics_fast(portfolio, calendar, diag, initial_capital=100_000_000):
    """Compute metrics from closed positions only - much faster."""
    closed = portfolio.closed_positions
    if not closed:
        return None
    
    # Total P&L
    total_pnl = sum(pos["pnl"] for pos in closed)
    total_return = total_pnl / initial_capital
    
    # Number of trades
    n_trades = len(closed)
    
    # Win rate
    win_trades = sum(1 for pos in closed if pos["pnl"] > 0)
    win_rate = win_trades / n_trades if n_trades > 0 else 0
    
    # Avg trade return
    avg_trade_ret = total_pnl / n_trades / initial_capital if n_trades > 0 else 0
    
    # CAGR approximation
    entry_dates = [pos["entry_date"] for pos in closed]
    exit_dates = [pos["exit_date"] for pos in closed]
    first_entry = min(entry_dates)
    last_exit = max(exit_dates)
    first_year = int(first_entry[:4])
    last_year = int(last_exit[:4])
    n_years = last_year - first_year + 1
    
    # Annualized return (CAGR)
    if n_years > 0 and initial_capital > 0:
        total_growth = 1 + total_return
        cagr = total_growth ** (1.0 / n_years) - 1
    else:
        cagr = 0
    
    # Monthly returns for Sharpe
    monthly_pnl = {}
    for pos in closed:
        yr_mo = pos["exit_date"][:7]
        monthly_pnl.setdefault(yr_mo, 0)
        monthly_pnl[yr_mo] += pos["pnl"]
    
    monthly_rets = [v / initial_capital for v in monthly_pnl.values()]
    if len(monthly_rets) >= 2:
        mret_mean = np.mean(monthly_rets)
        mret_std = np.std(monthly_rets, ddof=1)
        if mret_std > 0:
            sharpe = mret_mean / mret_std * np.sqrt(12)
        else:
            sharpe = None
    else:
        sharpe = None
    
    # MDD from monthly equity curve
    equity = initial_capital
    peak = equity
    mdd = 0
    for mo in sorted(monthly_pnl.keys()):
        equity += monthly_pnl[mo]
        peak = max(peak, equity)
        dd = (equity / peak) - 1
        mdd = min(mdd, dd)
    
    # Exposure: average fraction of max_positions actually used
    # Use maxSimultaneousPositionsObserved / max_positions (30)
    max_simul = diag.get("maxSimultaneousPositionsObserved", 0)
    max_pos = 30
    avg_exposure = max_simul / max_pos if max_pos > 0 else 0
    
    # Total costs
    total_cost = 0
    for pos in closed:
        entry = pos.get("entry")
        exit_ = pos.get("exit")
        if isinstance(entry, dict):
            total_cost += entry.get("cost_bps", 0) * entry.get("fill_price", 0) * entry.get("shares", 0) / 10000
        if isinstance(exit_, dict):
            total_cost += exit_.get("cost_bps", 0) * exit_.get("fill_price", 0) * exit_.get("shares", 0) / 10000
    
    total_cost_bps = total_cost / initial_capital * 10000 if initial_capital > 0 else 0
    
    # Yearly returns
    yearly_pnl = {}
    for pos in closed:
        yr = pos["exit_date"][:4]
        yearly_pnl.setdefault(yr, 0)
        yearly_pnl[yr] += pos["pnl"]
    yearly_returns = {yr: v / initial_capital for yr, v in yearly_pnl.items()}
    
    return {
        "total_return": total_return,
        "cagr": cagr,
        "sharpe": sharpe,
        "mdd": mdd,
        "exposure": avg_exposure,
        "n_trades": n_trades,
        "win_rate": win_rate,
        "avg_trade_return": avg_trade_ret,
        "total_cost_bps": total_cost_bps,
        "yearly_returns": yearly_returns,
    }


def run_backtest(strategy_id, start, end, repo_root):
    print(f"  Running {strategy_id}...", flush=True)
    result = run_smoke(strategy_id, start, end, repo_root, trace_limit=0)
    diag = result["diag"]
    portfolio = result["portfolio"]
    calendar = result["calendar"]
    
    print(f"    signals: {diag['signalCount']}, trades: {diag['executableTradeCount']}, closed: {diag['closedPositionCount']}", flush=True)
    
    metrics = compute_metrics_fast(portfolio, calendar, diag)
    return {"diag": diag, "metrics": metrics, "strategy_id": strategy_id}


def main():
    start = "2016-01-01"
    end = "2026-08-14"
    repo_root = REPO_ROOT
    
    factors = [
        "factor_earnings_yield_v1",
        "factor_rv60_v1",
        "factor_rev1m_v1",
        "composite_ey_rv60_equal_weight",
        "composite_ey_rv60_rank_composite",
    ]
    
    results = {}
    for sid in factors:
        t0 = time.time()
        res = run_backtest(sid, start, end, repo_root)
        results[sid] = res
        print(f"    done in {time.time()-t0:.1f}s", flush=True)
    
    # Print summary
    print("\n=== BACKTEST RESULTS ===")
    for sid, res in results.items():
        m = res["metrics"]
        d = res["diag"]
        if m:
            print(f"\n{sid}:")
            print(f"  Total Return: {m['total_return']:.2%}")
            print(f"  CAGR: {m['cagr']:.2%}")
            print(f"  Sharpe: {m['sharpe']:.2f}" if m['sharpe'] else "  Sharpe: N/A")
            print(f"  MDD: {m['mdd']:.2%}")
            print(f"  Exposure: {m['exposure']:.2%}")
            print(f"  Trades: {m['n_trades']}, Win Rate: {m['win_rate']:.2%}")
            print(f"  Cost (bps): {m['total_cost_bps']:.1f}")
            print(f"  Yearly: {m['yearly_returns']}")
    
    # Save results
    out_path = os.path.join(REPO_ROOT, "research", "strategy-lab", "reports", "2026-08-30-factor-discovery", "factor-single-backtest-results.json")
    with open(out_path, "w", encoding="utf-8") as f:
        save_results = {}
        for k, v in results.items():
            save_results[k] = {
                "diag": v["diag"],
                "metrics": v["metrics"]
            }
        json.dump(save_results, f, ensure_ascii=False, indent=2, default=str)
    print(f"\nSaved: {out_path}")
    
    # Generate markdown report
    gen_report(results)


def gen_report(results):
    lines = []
    lines.append("# Factor Single-Factor Backtest — KR (2026-08-30)")
    lines.append("")
    lines.append("- 실험: `FACTOR-SINGLE-BACKTEST-KR-2026-08`")
    lines.append("- 대상: `earnings_yield` (Q10), `rv60_pct` (Q1), `rev1m` (Q1)")
    lines.append("- 조건: A1A_ONLY, 월별 리밸런스, 30bps 왕복비용, Equal-Weight, Time-exit only")
    lines.append("- 벤치마크: `ew_benchmark_liquid_v1` (동일 유니버스/비용/캘린더)")
    lines.append("")
    lines.append("## 결과 요약")
    lines.append("")
    lines.append("| factor | grade | Total Return | CAGR | Sharpe | MDD | Exposure | Win Rate | Trades |")
    lines.append("|---|---|---|---|---|---|---|---|---|")
    
    for sid, res in results.items():
        m = res["metrics"]
        d = res["diag"]
        if m:
            grade = "PASS" if (m['cagr'] > 0 and (m['sharpe'] or 0) > 0.3 and m['mdd'] > -0.3) else "FAIL"
            factor_name = sid.replace("factor_", "").replace("_v1", "")
            lines.append(f"| {factor_name} | {grade} | {m['total_return']:.2%} | {m['cagr']:.2%} | {m['sharpe']:.2f} | {m['mdd']:.2%} | {m['exposure']:.2%} | {m['win_rate']:.2%} | {m['n_trades']} |")
    
    lines.append("")
    
    for sid, res in results.items():
        m = res["metrics"]
        d = res["diag"]
        if not m:
            continue
        factor_name = sid.replace("factor_", "").replace("_v1", "")
        grade = "PASS" if (m['cagr'] > 0 and (m['sharpe'] or 0) > 0.3 and m['mdd'] > -0.3) else "FAIL"
        lines.append(f"## {factor_name} — {grade}")
        lines.append("")
        lines.append(f"- Total Return: {m['total_return']:.2%}")
        lines.append(f"- CAGR: {m['cagr']:.2%}")
        lines.append(f"- Sharpe: {m['sharpe']:.2f}" if m['sharpe'] is not None else "- Sharpe: N/A")
        lines.append(f"- MDD: {m['mdd']:.2%}")
        lines.append(f"- Exposure: {m['exposure']:.2%}")
        lines.append(f"- Win Rate: {m['win_rate']:.2%}")
        lines.append(f"- Trades: {m['n_trades']}")
        lines.append(f"- Total Cost (bps): {m['total_cost_bps']:.1f}")
        lines.append(f"- Yearly Returns: {m['yearly_returns']}")
        lines.append("")
        lines.append("### Diagnostics")
        lines.append(f"- Signals: {d['signalCount']}, Executable: {d['executableTradeCount']}, Closed: {d['closedPositionCount']}")
        lines.append(f"- Exit Types: {d['exitTypeCounts']}")
        lines.append(f"- Max Simultaneous Positions: {d['maxSimultaneousPositionsObserved']}")
        lines.append("")
    
    out_path = os.path.join(REPO_ROOT, "research", "strategy-lab", "findings", "factor-single-backtest-kr-2026-08.md")
    with open(out_path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))
    print(f"Report: {out_path}")


if __name__ == "__main__":
    main()