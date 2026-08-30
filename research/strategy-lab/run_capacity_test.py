#!/usr/bin/env python
"""Run capacity test for earnings_yield with different max_positions."""
import json
import os
import sys
import shutil
import time

import numpy as np

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(REPO_ROOT, "research", "strategy-lab"))

from engine.runner import run_smoke


def compute_metrics(portfolio, diag, initial_capital=100_000_000):
    closed = portfolio.closed_positions
    if not closed:
        return None
    total_pnl = sum(pos["pnl"] for pos in closed)
    total_return = total_pnl / initial_capital
    n_trades = len(closed)
    win_trades = sum(1 for pos in closed if pos["pnl"] > 0)
    win_rate = win_trades / n_trades if n_trades > 0 else 0
    entry_dates = [pos["entry_date"] for pos in closed]
    exit_dates = [pos["exit_date"] for pos in closed]
    first_entry = min(entry_dates)
    last_exit = max(exit_dates)
    first_year = int(first_entry[:4])
    last_year = int(last_exit[:4])
    n_years = last_year - first_year + 1
    cagr = (1 + total_return) ** (1.0 / n_years) - 1 if n_years > 0 else 0
    monthly_pnl = {}
    for pos in closed:
        yr_mo = pos["exit_date"][:7]
        monthly_pnl.setdefault(yr_mo, 0)
        monthly_pnl[yr_mo] += pos["pnl"]
    monthly_rets = [v / initial_capital for v in monthly_pnl.values()]
    if len(monthly_rets) >= 2:
        mret_mean = np.mean(monthly_rets)
        mret_std = np.std(monthly_rets, ddof=1)
        sharpe = mret_mean / mret_std * np.sqrt(12) if mret_std > 0 else None
    else:
        sharpe = None
    equity = initial_capital
    peak = equity
    mdd = 0
    for mo in sorted(monthly_pnl.keys()):
        equity += monthly_pnl[mo]
        peak = max(peak, equity)
        dd = (equity / peak) - 1
        mdd = min(mdd, dd)
    max_simul = diag.get("maxSimultaneousPositionsObserved", 0)
    avg_exposure = max_simul / 30.0 if max_simul else 0  # normalized to 30 for comparison
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
        "exposure": max_simul / 30.0,  # relative to base 30
        "max_simul": max_simul,
        "n_trades": n_trades,
        "win_rate": win_rate,
        "yearly_returns": yearly_returns,
    }


def run_one(max_pos):
    """Run backtest with specific max_positions."""
    # Backup original policy
    policy_path = os.path.join(REPO_ROOT, "research", "strategy-lab", "strategies", "factor_earnings_yield_v1", "policy.json")
    backup_path = policy_path + ".bak"
    shutil.copy2(policy_path, backup_path)
    
    # Write new policy
    policy_new = os.path.join(REPO_ROOT, "research", "strategy-lab", "strategies", "factor_earnings_yield_v1", f"policy_{max_pos}.json")
    shutil.copy2(policy_new, policy_path)
    
    try:
        print(f"  Running max_positions={max_pos}...", flush=True)
        result = run_smoke("factor_earnings_yield_v1", "2016-01-01", "2026-08-14", REPO_ROOT, trace_limit=0)
        diag = result["diag"]
        portfolio = result["portfolio"]
        metrics = compute_metrics(portfolio, diag)
        metrics["max_positions"] = max_pos
        return metrics
    finally:
        # Restore original
        shutil.copy2(backup_path, policy_path)
        os.remove(backup_path)


def main():
    start = time.time()
    max_positions_list = [20, 30, 50, 100]
    results = {}
    
    for mp in max_positions_list:
        t0 = time.time()
        metrics = run_one(mp)
        results[mp] = metrics
        print(f"    done in {time.time()-t0:.1f}s", flush=True)
        print(f"    CAGR: {metrics['cagr']:.2%}, Sharpe: {metrics['sharpe']:.2f}, MDD: {metrics['mdd']:.2%}, max_simul: {metrics['max_simul']}", flush=True)
    
    print("\n=== CAPACITY TEST RESULTS ===")
    print(f"{'max_pos':>8} | {'CAGR':>8} | {'Sharpe':>8} | {'MDD':>8} | {'TotalRet':>8} | {'max_simul':>8} | {'Exposure':>8}")
    for mp in max_positions_list:
        m = results[mp]
        print(f"{mp:>8} | {m['cagr']:>7.2%} | {m['sharpe']:>7.2f} | {m['mdd']:>7.2%} | {m['total_return']:>7.2%} | {m['max_simul']:>8} | {m['exposure']:>7.2%}")
    
    # Save results
    out_path = os.path.join(REPO_ROOT, "research", "strategy-lab", "reports", "2026-08-30-factor-discovery", "capacity-test-results.json")
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(results, f, ensure_ascii=False, indent=2, default=str)
    print(f"\nSaved: {out_path}")
    
    # Generate report
    gen_report(results)


def gen_report(results):
    # EW Benchmark (from earlier)
    ew = {
        "cagr": 0.0293, "sharpe": 0.24, "mdd": -0.1110, 
        "total_return": 0.3733, "exposure": 0.84
    }
    
    lines = []
    lines.append("# Earnings Yield — Capacity Test (max_positions Scaling)")
    lines.append("")
    lines.append("- 실험: `EARNINGS-YIELD-CAPACITY-TEST-KR-2026-08`")
    lines.append("- 대상: `earnings_yield` 단독, max_positions = 20 / 30 / 50 / 100")
    lines.append("- 조건: 동일 유니버스/PIT/비용/기간/리밸런싱, 초기자본 1억원, Long-only")
    lines.append("")
    lines.append("## 1. 핵심 성과 비교")
    lines.append("")
    lines.append("| max_positions | CAGR | Sharpe | MDD | Total Return | Max Simultaneous | Exposure (rel to 30) |")
    lines.append("|---|---|---|---|---|---|---|")
    for mp in [20, 30, 50, 100]:
        m = results[mp]
        lines.append(f"| {mp} | {m['cagr']:.2%} | {m['sharpe']:.2f} | {m['mdd']:.2%} | {m['total_return']:.2%} | {m['max_simul']} | {m['exposure']:.2%} |")
    lines.append(f"| EW BM | {ew['cagr']:.2%} | {ew['sharpe']:.2f} | {ew['mdd']:.2%} | {ew['total_return']:.2%} | - | {ew['exposure']:.2%} |")
    lines.append("")
    
    lines.append("## 2. 분석")
    lines.append("")
    
    # Find best
    best_sharpe = max(results.items(), key=lambda x: x[1]['sharpe'] or 0)
    best_cagr = max(results.items(), key=lambda x: x[1]['cagr'])
    best_mdd = min(results.items(), key=lambda x: x[1]['mdd'])
    
    lines.append(f"- **Best Sharpe**: max_positions={best_sharpe[0]} (Sharpe={best_sharpe[1]['sharpe']:.2f})")
    lines.append(f"- **Best CAGR**: max_positions={best_cagr[0]} (CAGR={best_cagr[1]['cagr']:.2%})")
    lines.append(f"- **Best MDD**: max_positions={best_mdd[0]} (MDD={best_mdd[1]['mdd']:.2%})")
    lines.append("")
    
    # Capacity analysis
    lines.append("### 용량 효과 분석")
    lines.append(f"- max_positions 20->30: CAGR {results[20]['cagr']:.2%}->{results[30]['cagr']:.2%} ({results[30]['cagr']-results[20]['cagr']:+.2%})")
    lines.append(f"- max_positions 30->50: CAGR {results[30]['cagr']:.2%}->{results[50]['cagr']:.2%} ({results[50]['cagr']-results[30]['cagr']:+.2%})")
    lines.append(f"- max_positions 50->100: CAGR {results[50]['cagr']:.2%}->{results[100]['cagr']:.2%} ({results[100]['cagr']-results[50]['cagr']:+.2%})")
    lines.append("")
    lines.append(f"- max_positions 20->30: Sharpe {results[20]['sharpe']:.2f}->{results[30]['sharpe']:.2f} ({results[30]['sharpe']-results[20]['sharpe']:+.2f})")
    lines.append(f"- max_positions 30->50: Sharpe {results[30]['sharpe']:.2f}->{results[50]['sharpe']:.2f} ({results[50]['sharpe']-results[30]['sharpe']:+.2f})")
    lines.append(f"- max_positions 50->100: Sharpe {results[50]['sharpe']:.2f}->{results[100]['sharpe']:.2f} ({results[100]['sharpe']-results[50]['sharpe']:+.2f})")
    lines.append("")
    
    # Alpha dilution check
    lines.append("### 알파 희석 확인")
    base_cagr = results[30]['cagr']
    for mp in [20, 50, 100]:
        diff = results[mp]['cagr'] - base_cagr
        status = "희석" if diff < -0.001 else ("개선" if diff > 0.001 else "유사")
        lines.append(f"- max_positions={mp}: CAGR 차이 {diff:+.2%} -> {status}")
    lines.append("")
    
    # Final recommendation
    lines.append("## 3. 최종 권장 max_positions")
    lines.append("")
    if results[50]['sharpe'] > results[30]['sharpe'] and results[50]['mdd'] < results[30]['mdd']:
        lines.append("> **PASS: max_positions=50** — 분산효과로 MDD 개선되며 Sharpe 유지/개선")
    elif results[30]['sharpe'] >= results[50]['sharpe'] and results[30]['mdd'] <= results[50]['mdd']:
        lines.append("> **PASS: max_positions=30** (기존 유지) — 50 확대 시 유의미한 개선 없음")
    elif results[20]['sharpe'] > results[30]['sharpe']:
        lines.append("> **CONDITIONAL: max_positions=20** — 소수 정예가 유리하나 용량 제한")
    else:
        lines.append("> **CONDITIONAL** — 추가 검토 필요")
    
    out_path = os.path.join(REPO_ROOT, 'research', 'strategy-lab', 'findings', 'factor-earnings-yield-capacity-test-2026-08.md')
    with open(out_path, 'w', encoding='utf-8') as f:
        f.write('\n'.join(lines))
    print(f"Report: {out_path}")


if __name__ == "__main__":
    REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    main()