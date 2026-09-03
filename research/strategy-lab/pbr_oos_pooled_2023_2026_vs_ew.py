#!/usr/bin/env python
"""PBR 검증 마무리 진단 - 2023-01~2026-08.14 전체를 하나의 OOS 구간으로 묶어
C방식(top-30·월별·turnover20>=1억원·30bps) 실제 엔진 성과를, 같은 기간 같은
고유동성 유니버스의 EW 벤치마크·PBR long-short spread와 나란히 비교한다 -
최근 성과가 시장 베타인지 PBR 선별력인지 가른다. 파라미터 고정, 재튜닝 없음.
C방식(연속보유 유지, 청산-재진입 없음)은 resolved 리스트를 스케줄링 직전에
후처리할 뿐이라 engine/runner.py·portfolio.py 원본 그대로 메인 트리에서 실행
(수정 불필요) - production/정책 미변경, 커밋 없음.

  python pbr_oos_pooled_2023_2026_vs_ew.py
"""
import json
import os
import sys
import time
from datetime import date as _date

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402

from engine.runner import run_smoke, _schedule_portfolio, _drop_suspension_rows  # noqa: E402
from engine.portfolio.portfolio import Portfolio, PortfolioConfig  # noqa: E402
from engine.metrics.metrics import total_return, cagr, max_drawdown, sharpe, trade_stats  # noqa: E402
from pbr_vs_ew_monthly_mtm import schedule_with_monthly_mtm, curve_metrics  # noqa: E402
from engine.data.a2aProvider import A2aProvider  # noqa: E402
from engine.data.calendar import TradingCalendar  # noqa: E402

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
PANEL_PATH = os.path.join(REPO_ROOT, "research", "strategy-lab", "reports",
                           "2026-08-21-a5-valuation-precheck", "valuation-panel.jsonl")
START, END = "2023-01-01", "2026-08-14"
MIN_TURNOVER = 100_000_000.0
COST_RT_BPS = 30.0
TOP_N = 30


def _to_ordinal(d):
    y, m, dd = map(int, d.split("-"))
    return _date(y, m, dd).toordinal()


def merge_continuous_holds(resolved):
    """C: collapse a same-symbol renewal chain (exit day == next entry day) into
    one trade spanning the whole chain - no interim cash event, no interim cost."""
    ordered = sorted(resolved, key=lambda item: item[1].order_date)
    merged, chain_idx = [], {}
    for item in ordered:
        sig, order, entry_fill, exit_fill, risk_spec, atr = item
        idx = chain_idx.get(order.symbol)
        if idx is not None:
            p_sig, p_order, p_entry, p_exit, p_risk, p_atr = merged[idx]
            if p_exit.fill_date == order.order_date:
                merged[idx] = (p_sig, p_order, p_entry, exit_fill, p_risk, p_atr)
                continue
        merged.append(item)
        chain_idx[order.symbol] = len(merged) - 1
    return merged


def trades_from_portfolio(portfolio):
    trades = []
    for p in portfolio.closed_positions:
        entry, exit_ = p["entry"], p["exit"]
        trades.append({"pnl": p["pnl"], "holding_sessions": _to_ordinal(exit_.fill_date) - _to_ordinal(p["entry_date"]),
                        "symbol": p["symbol"], "entry_date": p["entry_date"], "exit_date": exit_.fill_date,
                        "exit_type": exit_.fill_type, "entry_price": entry.fill_price,
                        "exit_price": exit_.fill_price, "shares": p["shares"]})
    return trades


def realized_metrics(portfolio):
    """폐기된 회계 방식 - 대조용으로만 남긴다(결과표에 쓰지 않는다).

    청산일에만 손익을 적립하므로 연속보유 포지션의 미실현 낙폭이 곡선에 안
    나타나 MDD를 얕게, Sharpe를 부풀려 낸다(2026-08-22 발견).
    """
    events = sorted((p["exit_date"], p["pnl"]) for p in portfolio.closed_positions)
    curve, eq = [], portfolio.config.initial_capital
    for d, pnl in events:
        eq += pnl
        curve.append((d, eq))
    if not curve:
        return {}
    return {"cagr": cagr(curve), "mdd": max_drawdown(curve), "sharpe": sharpe(curve)}


def run_pbr_engine_methodC():
    t0 = time.time()
    base = run_smoke("pbr_value_v1", START, END, REPO_ROOT)
    resolved, params = base["resolved"], base["params"]
    merged = merge_continuous_holds(resolved)
    portfolio_cfg = PortfolioConfig(
        initial_capital=params["portfolio"]["initialCapital"], max_positions=params["portfolio"]["maxPositions"],
        equal_weight=params["portfolio"]["equalWeight"], fractional_shares=params["portfolio"]["fractionalShares"],
        tie_break=params["portfolio"]["tieBreak"])
    # 월말 시가평가로 스케줄한다(_schedule_portfolio() 무수정 복제본 + 월말 스냅샷).
    portfolio, snapshots = schedule_with_monthly_mtm(
        merged, portfolio_cfg, base["bars_by_ticker"], base["calendar"], START, END)
    r = curve_metrics(snapshots)
    deprecated = realized_metrics(portfolio)
    t_stats = trade_stats(trades_from_portfolio(portfolio))
    print(f"  engine methodC resolved: {len(base['resolved'])} -> merged {len(merged)} trades ({time.time()-t0:.0f}s)")
    return {
        "cagr": round(r.get("cagr"), 4) if r.get("cagr") is not None else None,
        "mdd": round(r.get("mdd"), 4) if r.get("mdd") is not None else None,
        "sharpe": round(r.get("sharpe"), 4) if r.get("sharpe") is not None else None,
        "tradeCount": t_stats.get("tradeCount"),
        "winRate": round(t_stats.get("winRate", 0), 4) if t_stats.get("winRate") is not None else None,
        "accountingMethod": "monthly mark-to-market (schedule_with_monthly_mtm)",
        "monthlySnapshotCount": len(snapshots),
        "deprecatedRealizedPnL": {
            "note": "폐기된 실현손익 누적 회계. 인용 금지 - 위 cagr/mdd/sharpe를 쓴다.",
            **{k: (round(v, 4) if isinstance(v, float) else v) for k, v in deprecated.items()},
        },
    }, portfolio


# ---------- panel side: EW benchmark, low/high PBR, IC (same high-liquidity universe) ----------

def monthly_rebalance_dates(calendar, start, end):
    days = calendar.sessions_between(start, end)
    out, seen = [], set()
    for d in days:
        ym = d[:7]
        if ym not in seen:
            seen.add(ym)
            out.append(d)
    return out


def load_valuation_panel():
    rows = [json.loads(line) for line in open(PANEL_PATH, encoding="utf-8")]
    df = pd.DataFrame(rows)
    df = df.dropna(subset=["pbr"])
    df = df[df["pbr"] > 0]
    return df.set_index(["ticker", "asOf"])["pbr"].to_dict()


def build_panel(bars_by_ticker, rebalance_dates, pbr_lookup):
    rows = []
    for ticker, bars in bars_by_ticker.items():
        if bars.empty or len(bars) < 260:
            continue
        close, open_, vol = bars["close"], bars["open"], bars["volume"]
        idx = close.index.astype(str)
        pos = {d: i for i, d in enumerate(idx)}
        turnover20 = (close * vol).rolling(20).mean()
        for k, t in enumerate(rebalance_dates[:-1]):
            pbr = pbr_lookup.get((ticker, t))
            if pbr is None:
                continue
            i = pos.get(t)
            if i is None or i + 1 >= len(idx):
                continue
            entry_date = idx[i + 1]
            exit_date = rebalance_dates[k + 1]
            j = pos.get(exit_date)
            if j is None or j + 1 >= len(idx):
                continue
            entry_price, exit_price = float(open_.iloc[i + 1]), float(open_.iloc[j + 1])
            if entry_price <= 0 or exit_price <= 0:
                continue
            tv = turnover20.iloc[i]
            rows.append({"ticker": ticker, "entry_date": t, "pbr": float(pbr),
                         "ret": exit_price / entry_price - 1,
                         "turnover20": float(tv) if not pd.isna(tv) else 0.0})
    return pd.DataFrame(rows)


def rank_ic(factor_vals, fwd_rets):
    if len(factor_vals) < 5:
        return None
    return float(np.corrcoef(pd.Series(factor_vals).rank(), pd.Series(fwd_rets).rank())[0, 1])


def period_ic(sub):
    monthly_ics = []
    for m in sorted(sub["entry_date"].unique()):
        g = sub[sub["entry_date"] == m]
        if len(g) < 15:
            continue
        ic = rank_ic((-g["pbr"]).values, g["ret"].values)
        if ic is not None:
            monthly_ics.append(ic)
    if not monthly_ics:
        return {"meanMonthlyIC": None, "icTstat": None}
    ic_mean, ic_std = float(np.mean(monthly_ics)), float(np.std(monthly_ics))
    ic_tstat = (ic_mean / (ic_std / np.sqrt(len(monthly_ics)))) if ic_std > 0 else None
    return {"meanMonthlyIC": round(ic_mean, 4), "icTstat": round(ic_tstat, 2) if ic_tstat is not None else None,
            "icMonthsUsed": len(monthly_ics)}


def monthly_series(sub, selector, cost_bps=COST_RT_BPS):
    out = []
    for m in sorted(sub["entry_date"].unique()):
        g = sub[sub["entry_date"] == m]
        sel = selector(g)
        if sel.empty:
            continue
        out.append((m, float((sel["ret"] - cost_bps / 1e4).mean())))
    return out


def curve_stats(month_rets):
    if not month_rets:
        return None
    mdf = pd.DataFrame(month_rets, columns=["month", "ret"])
    eq, peak, maxdd = 1.0, 1.0, 0.0
    for _, row in mdf.iterrows():
        eq *= (1 + row["ret"])
        peak = max(peak, eq)
        maxdd = min(maxdd, eq / peak - 1)
    n_months = len(mdf)
    n_years = n_months / 12.0
    cagr_ = eq ** (1 / n_years) - 1 if n_years > 0 else None
    std_r = mdf["ret"].std(ddof=1) if len(mdf) > 1 else 0.0
    sharpe_ = (mdf["ret"].mean() / std_r * np.sqrt(12)) if std_r and std_r > 0 else None
    return {"monthsTraded": n_months, "totalReturn": round(eq - 1, 4),
            "cagr": round(cagr_, 4) if cagr_ is not None else None,
            "maxDD": round(maxdd, 4), "sharpe": round(sharpe_, 4) if sharpe_ is not None else None,
            "monthlyRets": {m: round(r, 4) for m, r in month_rets}}


def excess_over_ew(low_rets, ew_rets):
    low_by_m, ew_by_m = dict(low_rets), dict(ew_rets)
    common = sorted(set(low_by_m) & set(ew_by_m))
    if not common:
        return None
    excess = [low_by_m[m] - ew_by_m[m] for m in common]
    edf = pd.Series(excess)
    eq = 1.0
    for r in excess:
        eq *= (1 + r)
    n_years = len(excess) / 12.0
    cagr_ = eq ** (1 / n_years) - 1 if n_years > 0 else None
    std_r = edf.std(ddof=1) if len(edf) > 1 else 0.0
    ir = (edf.mean() / std_r * np.sqrt(12)) if std_r and std_r > 0 else None
    return {"excessCagr": round(cagr_, 4) if cagr_ is not None else None,
            "informationRatio": round(ir, 4) if ir is not None else None,
            "winRateMonths": round(float((edf > 0).mean()), 3)}


def main():
    t_start = time.time()
    print(f"=== pooled OOS {START} ~ {END} ===")

    engine_result, portfolio = run_pbr_engine_methodC()
    print("  engine (C, real portfolio accounting):", json.dumps(engine_result, ensure_ascii=False))

    pbr_lookup = load_valuation_panel()
    tickers = sorted({t for t, _ in pbr_lookup.keys()})
    calendar = TradingCalendar(repo_root=REPO_ROOT)
    a2a = A2aProvider(repo_root=REPO_ROOT, use_cache=True)
    bars_raw = a2a.load(tickers, START, END, universe_hash="pbr-oos-pooled-2023-2026-vs-ew")
    bars_by_ticker = {t: _drop_suspension_rows(df) for t, df in bars_raw.items()}
    rebalance_dates = monthly_rebalance_dates(calendar, START, END)
    panel = build_panel(bars_by_ticker, rebalance_dates, pbr_lookup)
    panel_hi = panel[panel["turnover20"] >= MIN_TURNOVER]
    print(f"  panel high-liquidity rows={len(panel_hi)} ({time.time()-t_start:.0f}s)")

    ic = period_ic(panel_hi)

    low_rets = monthly_series(panel_hi, lambda g: g.sort_values("pbr", ascending=True).head(TOP_N))
    high_rets = monthly_series(panel_hi, lambda g: g.sort_values("pbr", ascending=False).head(TOP_N))
    ew_rets = monthly_series(panel_hi, lambda g: g)  # entire high-liquidity universe, equal-weighted

    low_stats = curve_stats(low_rets)
    high_stats = curve_stats(high_rets)
    ew_stats = curve_stats(ew_rets)

    low_by_m, high_by_m = dict(low_rets), dict(high_rets)
    common = sorted(set(low_by_m) & set(high_by_m))
    spread_series = [(m, low_by_m[m] - high_by_m[m]) for m in common]
    spread_stats = curve_stats(spread_series)

    excess = excess_over_ew(low_rets, ew_rets)

    for d in (low_stats, high_stats, ew_stats, spread_stats):
        if d:
            d.pop("monthlyRets", None)

    result = {
        "period": f"{START} ~ {END}",
        "engine_methodC_realPortfolio_top30_cost30bps": engine_result,
        "panelNaive_lowPBR_top30": low_stats,
        "panelNaive_highPBR_control_top30": high_stats,
        "panelNaive_fullUniverse_EW_highLiquidity": ew_stats,
        "panelNaive_lowMinusHighPBR_spread": spread_stats,
        "ic": ic,
        "excessReturn_lowPBR_over_EW": excess,
        "interpretation": {
            "note": "engine_methodC는 실제 포트폴리오 회계(공유현금·정수주식수) 기준, "
                    "panelNaive_*는 단순 월별 동일가중 평균(공유현금풀 없음) - 서로 다른 "
                    "산출방식이라 절대값이 정확히 일치하진 않지만 방향/부호 비교에는 "
                    "둘 다 유효하다.",
        },
    }
    print("\nresult:", json.dumps(result, ensure_ascii=False, default=str))

    out_dir = os.path.join(REPO_ROOT, "research", "strategy-lab", "reports",
                            "2026-08-21-pbr-oos-pooled-2023-2026-vs-ew")
    os.makedirs(out_dir, exist_ok=True)
    out_path = os.path.join(out_dir, "pbr-oos-pooled-2023-2026-vs-ew.json")
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump({
            "generatedAt": time.strftime("%Y-%m-%dT%H:%M:%S"),
            "context": "PBR 검증 마무리 진단 - 2023-01~2026-08.14를 하나의 OOS로 묶어 C방식 "
                       "실제엔진 vs 전체유니버스EW vs PBR long-short spread 비교. 파라미터 "
                       "고정(top-30·월별·turnover20>=1억원·30bps), 재튜닝 없음, engine/policy "
                       "미변경, 커밋 없음.",
            "result": result,
        }, f, ensure_ascii=False, indent=2, default=str)
    print("\nsaved:", out_path, f"(total {time.time()-t_start:.0f}s)")


if __name__ == "__main__":
    main()
