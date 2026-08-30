#!/usr/bin/env python
"""Flow × Price Confirmation — Portfolio 검증 (Step 7).

Step 6에서 발견된 "외국인 강매수(Foreign Top 20%) + 당일 가격 약세(Price Bottom 50%)"
5D 효과를 실제 portfolio 형태로 최소 검증한다.

Signal 정의 (Step 6과 정확히 동일):
  A = foreign_flow_ratio 상위 20%  (매일, PIT)
  A 내부에서 B = 당일 가격수익률 하위 50%
  → signal universe = A ∩ B
  → 그 중 foreign_flow_ratio 상위 Top 10 선택 (종목 부족 시 전체), 동일가중

Portfolio:
  - 보유기간 5 trading days (유일)
  - entry: signal일 t 다음 거래일 OPEN (A2a adjusted)  (PIT, 미래데이터 없음)
  - exit : entry 후 5 거래일 뒤 종가
  - Top 10 고정, 그 외 Top-N 테스트 안 함

비용: 프로젝트 기본 비용 모델 30bps RT (COST_RT_BPS=30) — 포지션당 왕복 1회.

Benchmark: 동일 universe(A4 전체 2558종목)의 EW B&H + (가능 시) 지수
OOS: TRAIN/VALID/TEST (Step 2 동일).
"""
import os
import sys

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__))))
from engine.data.a2aProvider import A2aProvider  # noqa: E402

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
DATA = os.path.join(REPO_ROOT, "research", "strategy-lab", "data", "a4", "a4-research-dataset.parquet")
OUT = os.path.join(REPO_ROOT, "research", "strategy-lab", "findings", "flow-price-confirmation-portfolio-2026-08.md")

COST_RT_BPS = 30.0
COST_RT = COST_RT_BPS / 1e4            # 30bp 왕복
TOP_N = 10
HOLD_DAYS = 5
TRADING_DAYS = 252.0

SPLIT = {
    "TRAIN": ("2016-01-01", "2022-07-01"),
    "VALID": ("2022-07-01", "2024-01-01"),
    "TEST":  ("2024-01-01", "2026-12-31"),
}


def metrics_from_daily(daily_ret, n_days_tr=None):
    """daily_ret: 시계열 일별 수익률(index=date). CAGR/MDD/Sharpe/Calmar/Total."""
    r = daily_ret.dropna()
    if len(r) == 0:
        return {}
    eq = np.cumprod(1 + r.values)
    total = eq[-1] - 1
    n = len(r)
    cagr = eq[-1] ** (TRADING_DAYS / n) - 1 if eq[-1] > 0 else -1.0
    peak = np.maximum.accumulate(eq)
    dd = eq / peak - 1
    mdd = float(dd.min())
    sharpe = float(r.mean() / r.std(ddof=1) * np.sqrt(TRADING_DAYS)) if r.std(ddof=1) > 0 else np.nan
    calmar = cagr / abs(mdd) if mdd < 0 else np.nan
    # 기간별 통계
    return {
        "total_return": float(total),
        "cagr": float(cagr),
        "mdd": float(mdd),
        "sharpe": sharpe,
        "calmar": calmar,
        "n_days": int(n),
    }


def build_signal_positions(a4, prices):
    """signal (ticker, signal_date) 리스트 반환. (A2a 티커 고유 calendar 기반)"""
    a4 = a4.sort_values(["ticker", "date"]).reset_index(drop=True)
    a4["f_rank"] = a4.groupby("date")["foreign_flow_ratio"].rank(pct=True)
    a4["p_rank"] = a4.groupby("date")["daily_return"].rank(pct=True)
    # signal universe: foreign top20 AND price bottom50
    sig = a4[(a4["f_rank"] > 0.80) & (a4["p_rank"] < 0.50)].copy()
    # top 10 by foreign_flow_ratio (within date), 동일가중
    sig["picked"] = sig.groupby("date")["foreign_flow_ratio"].rank(method="first", ascending=False)
    sig = sig[sig["picked"] <= TOP_N].copy()
    sig = sig[["ticker", "date", "foreign_flow_ratio", "daily_return"]].rename(columns={"date": "signal_date"})
    # entry day = ticker의 다음 거래일
    pos = []
    for (tk), g in sig.groupby("ticker"):
        px = prices.get(tk)
        if px is None or len(px) < HOLD_DAYS + 1:
            continue
        dts = list(px.index)
        idx_map = {d: i for i, d in enumerate(dts)}
        for _, r in g.iterrows():
            t = r["signal_date"]
            if t not in idx_map:
                continue
            i = idx_map[t]
            if i + HOLD_DAYS >= len(dts):
                continue
            entry_day = dts[i + 1]              # 다음 거래일 open
            exit_day = dts[i + 1 + (HOLD_DAYS - 1)]  # entry 후 5거래일 뒤(마지막 날) 종가
            pos.append({
                "ticker": tk, "signal_date": t,
                "entry_date": entry_day, "exit_date": exit_day,
                "foreign_flow_ratio": r["foreign_flow_ratio"],
                "daily_return": r["daily_return"],
            })
    return pd.DataFrame(pos)


def load_a4():
    df = pd.read_parquet(DATA, columns=["ticker", "date", "foreign_net", "total_amount", "close"])
    df["date"] = pd.to_datetime(df["date"])
    df = df.sort_values(["ticker", "date"]).reset_index(drop=True)
    df["foreign_flow_ratio"] = df["foreign_net"] / df["total_amount"].replace(0, np.nan)
    df["daily_return"] = df.groupby("ticker")["close"].transform(lambda s: s / s.shift(1) - 1)
    return df


def main():
    print("Loading A4 + A2a...")
    a4 = load_a4()
    tickers = set(a4["ticker"].unique())
    a2a = A2aProvider(repo_root=REPO_ROOT, use_cache=True)
    start = a4["date"].min().strftime("%Y-%m-%d")
    end = a4["date"].max().strftime("%Y-%m-%d")
    bars = a2a.load(tickers, start, end, universe_hash="flow-price-confirmation-portfolio")
    # (ticker -> DataFrame[open, close] index=date)
    prices = {t: df[["open", "close"]].copy() for t, df in bars.items()}
    print(f"  A4 rows={len(a4)} tickers={len(tickers)} | A2a tickers={len(prices)}")

    # daily_return 재계산은 A2a close를 써도 되지만 A4와 일치. 그대로 사용.

    pos = build_signal_positions(a4, prices)
    print(f"  signal positions (full)= {len(pos)}")

    # daily portfolio return 시뮬레이션 (overlapping cohorts, equal-weight)
    # 각 position의 일별 return을 구성
    pos_rows = []
    for row in pos.itertuples(index=False):
        px = prices[row.ticker]
        entry_idx = px.index.get_loc(row.entry_date)
        exit_idx = px.index.get_loc(row.exit_date)
        dts = px.index
        o = px["open"].iloc[entry_idx]
        if not np.isfinite(o) or o <= 0:
            continue
        closes = px["close"].iloc[entry_idx:exit_idx + 1]
        if not np.all(np.isfinite(closes)) or (closes <= 0).any():
            continue
        daily = []
        # entry day: open->close
        daily.append((row.entry_date, px["close"].iloc[entry_idx] / o - 1.0))
        # middle days: close->close
        for k in range(entry_idx + 1, exit_idx + 1):
            r_k = px["close"].iloc[k] / px["close"].iloc[k - 1] - 1.0
            if not np.isfinite(r_k):
                r_k = 0.0
            if k == exit_idx:
                r_k -= COST_RT          # exit day에 왕복비용 30bp
            daily.append((dts[k], r_k))
        pos_rows.append({"ticker": row.ticker, "signal_date": row.signal_date,
                         "entry_date": row.entry_date, "exit_date": row.exit_date,
                         "n_days": len(daily)})
        for d, r_k in daily:
            pos_rows.append({"ticker": row.ticker, "signal_date": row.signal_date,
                             "date": d, "kind": "daily", "ret": r_k})
    # 포지션별 총 gross/net return (ticker PnL 분해용)
    trade_df = pos.copy()
    gross = []
    keep_mask = []
    for row in pos.itertuples(index=False):
        px = prices[row.ticker]
        ei = px.index.get_loc(row.entry_date)
        xi = px.index.get_loc(row.exit_date)
        o = px["open"].iloc[ei]
        c = px["close"].iloc[xi]
        ok = np.isfinite(o) and o > 0 and np.isfinite(c) and c > 0
        keep_mask.append(ok)
        gross.append(c / o - 1.0 if ok else np.nan)
    trade_df = trade_df[keep_mask].copy()
    trade_df["ret_gross"] = np.array(gross)[keep_mask]
    trade_df["ret_net"] = trade_df["ret_gross"] - COST_RT

    dret = pd.DataFrame(pos_rows)
    daily_ret = dret[dret["kind"] == "daily"].copy()
    # 일별 active position 수
    active = daily_ret.groupby("date").agg({
        "ret": "mean",
        "ticker": "count",
    }).rename(columns={"ret": "ret", "ticker": "n_pos"})
    active = active.sort_index()

    # EW B&H benchmark (동일 universe = A4 전체, close-to-close)
    bh = []
    for tk, g in a4.groupby("ticker"):
        g = g.sort_values("date")
        r = g["close"].shift(-1) / g["close"] - 1.0
        bh.append(pd.DataFrame({"date": g["date"], "ret": r.values}))
    bh = pd.concat(bh, ignore_index=True).dropna()
    bh_ret = bh.groupby("date")["ret"].mean()

    # weekday annualization helper
    def to_annual_series(daily, n_per_year=TRADING_DAYS):
        return daily

    print("=== Portfolio vs EW B&H (full period) ===")
    pf_full = metrics_from_daily(active["ret"])
    bh_full = metrics_from_daily(bh_ret)
    print(f"  Signal PF: CAGR={pf_full['cagr']:.4f} MDD={pf_full['mdd']:.4f} Sharpe={pf_full['sharpe']:.3f} "
          f"Calmar={pf_full['calmar']:.3f} Total={pf_full['total_return']:.4f} avgPos={active['n_pos'].mean():.1f}")
    print(f"  EW B&H   : CAGR={bh_full['cagr']:.4f} MDD={bh_full['mdd']:.4f} Sharpe={bh_full['sharpe']:.3f} "
          f"Calmar={bh_full['calmar']:.3f} Total={bh_full['total_return']:.4f}")

    # ── split별 ──
    rows = []
    for pname, (s, e) in SPLIT.items():
        d = active[(active.index >= s) & (active.index < e)]
        m = metrics_from_daily(d["ret"])
        bhm = metrics_from_daily(bh_ret[(bh_ret.index >= s) & (bh_ret.index < e)])
        n_pos_total = int(len(trade_df[(trade_df["entry_date"] >= s) & (trade_df["entry_date"] < e)]))
        n_days_hold = int(d["n_pos"].sum()) if "n_pos" in d else 0
        avg_pos = d["n_pos"].mean() if len(d) else np.nan
        # turnover: 일평균 mu of deployed positions (Top10 최대 50개 활성)
        rows.append({
            "period": pname,
            "pf_cagr": m.get("cagr"), "pf_mdd": m.get("mdd"), "pf_sharpe": m.get("sharpe"),
            "pf_calmar": m.get("calmar"), "pf_total": m.get("total_return"),
            "bh_cagr": bhm.get("cagr"), "bh_total": bhm.get("total_return"),
            "n_positions": n_pos_total, "avg_pos": float(avg_pos) if not np.isnan(avg_pos) else None,
            "mean_daily": float(d["ret"].mean()) if len(d) else None,
        })

    # turnover: 일평균 보유종목 수 / 최대(활성 상한) 는 아니고, 거래 측면에서
    # 하루 신규 진입 평균 포지션 수 (총 포지션 / 기간 거래일)
    print("\n=== Split별 ===")
    for r in rows:
        print(f"  {r['period']:6s}: PF CAGR={r['pf_cagr']:.4f} MDD={r['pf_mdd']:.4f} "
              f"Sharpe={np.nan if r['pf_sharpe'] is None else r['pf_sharpe']:.3f} "
              f"Calmar={np.nan if r['pf_calmar'] is None else r['pf_calmar']:.3f} "
              f"Total={r['pf_total']:.4f} | B&H Total={r['bh_total']:.4f} | pos={r['n_positions']} avgPos={r['avg_pos']:.1f}")

    # ── TEST ticker PnL 분해 ──
    test_trades = trade_df[(trade_df["entry_date"] >= SPLIT["TEST"][0]) & (trade_df["entry_date"] < SPLIT["TEST"][1])].copy()
    by_tk = test_trades.groupby("ticker").agg(
        n_trades=("ret_net", "count"), gross_pnl=("ret_gross", "sum"), net_pnl=("ret_net", "sum"),
        mean_net=("ret_net", "mean"),
    ).sort_values("net_pnl", ascending=False)
    top5 = by_tk.head(5)
    total_net = by_tk["net_pnl"].sum()
    # 상위 5개 종목 기여 비중
    top5_share = by_tk.head(5)["net_pnl"].sum() / total_net if total_net != 0 else np.nan
    # 최대 단일 종목 비중
    max_share = by_tk["net_pnl"].max() / total_net if total_net != 0 else np.nan

    print("\n=== TEST ticker PnL 분해 ===")
    print(f"  TEST 기간 net_positions={len(test_trades)} unique_tickers={by_tk.shape[0]} total_net_pnl={total_net:.4f}")
    print(f"  top5 net_pnl 기여 비중 = {top5_share:.3f}, 최대 단일 종목 비중 = {max_share:.3f}")
    print("  top5:")
    for tk, r in by_tk.head(5).iterrows():
        print(f"    {tk}: n={int(r['n_trades'])} gross={r['gross_pnl']:+.4f} net={r['net_pnl']:+.4f}")

    # ── 결과 저장 ──
    lines = []
    lines.append("# Flow × Price Confirmation — Portfolio 검증 (Step 7)")
    lines.append("")
    lines.append("> 분석 일시: 2026-08-28 | 데이터: A4 + A2a adjusted (Step 6과 동일)")
    lines.append(f"> 기간: {a4['date'].min().date()} ~ {a4['date'].max().date()} | 종목: {a4['ticker'].nunique()}")
    lines.append(f"> 비용: {COST_RT_BPS:.0f}bps RT(프로젝트 기본 모델) | 보유기간: {HOLD_DAYS} trading days | Top {TOP_N}")
    lines.append("> 목적: Step 6에서 발견된 '외국인 강매수 + 당일 가격 약세' 5D 효과의 portfolio level 검증")
    lines.append("")
    lines.append("## 0. Signal 정의 (Step 6과 동일)")
    lines.append("")
    lines.append("- A = foreign_flow_ratio 상위 20% (매일 PIT)")
    lines.append("- A 내부에서 B = 당일 가격수익률 하위 50%")
    lines.append("- signal universe = A ∩ B, 그 중 foreign_flow_ratio 상위 Top 10, 동일가중")
    lines.append("- entry: signal일 t 다음 거래일 OPEN (A2a adjusted) | exit: entry 후 5 거래일 종가")
    lines.append("- 비용: 포지션당 왕복 30bps")
    lines.append("")

    lines.append("## 1. 전체 기간 & Split별 성과")
    lines.append("")
    lines.append("| Period | PF CAGR | PF MDD | PF Sharpe | PF Calmar | PF Total | EW B&H Total | n_positions | avg_pos |")
    lines.append("|---|---:|---:|---:|---:|---:|---:|---:|---:|")
    pf_all = pf_full
    bh_all = bh_full
    lines.append(f"| FULL | {pf_all['cagr']:.4f} | {pf_all['mdd']:.4f} | {pf_all['sharpe']:.3f} | {pf_all['calmar']:.3f} | "
                 f"{pf_all['total_return']:.4f} | {bh_all['total_return']:.4f} | {len(trade_df)} | {active['n_pos'].mean():.1f} |")
    for r in rows:
        lines.append(f"| {r['period']} | {r['pf_cagr']:.4f} | {r['pf_mdd']:.4f} | "
                     f"{np.nan if r['pf_sharpe'] is None else r['pf_sharpe']:.3f} | "
                     f"{np.nan if r['pf_calmar'] is None else r['pf_calmar']:.3f} | "
                     f"{r['pf_total']:.4f} | {r['bh_total']:.4f} | {r['n_positions']} | {r['avg_pos']:.1f} |")
    lines.append("")

    lines.append("## 2. 핵심 검증 (TEST)")
    lines.append("")
    test_m = metrics_from_daily(active[(active.index >= SPLIT["TEST"][0]) & (active.index < SPLIT["TEST"][1])]["ret"])
    lines.append(f"- ① TEST portfolio 수익: **{'양수' if test_m['total_return'] > 0 else '음수'}** "
                 f"(Total {test_m['total_return']:+.4f}, CAGR {test_m['cagr']:+.4f})")
    lines.append(f"- ② Step 6 cross-sectional spread → portfolio: TEST Net PnL 합 {total_net:+.4f} over "
                 f"{len(test_trades)} positions")
    lines.append(f"- ③ 종목 집중: TEST 최대 단일 종목 PnL 비중 {max_share:.3f}, 상위 5종목 합 비중 {top5_share:.3f} "
                 f"(unique tickers {by_tk.shape[0]})")
    lines.append("")
    lines.append("### TEST top5 종목 (net PnL)")
    lines.append("")
    lines.append("| ticker | n_trades | gross PnL | net PnL |")
    lines.append("|---|---:|---:|---:|")
    for tk, r in by_tk.head(10).iterrows():
        lines.append(f"| {tk} | {int(r['n_trades'])} | {r['gross_pnl']:+.4f} | {r['net_pnl']:+.4f} |")
    lines.append("")
    lines.append("## 3. 방향 일관성 (CAGR 부호)")
    lines.append("")
    dirs = [("+" if r["pf_cagr"] > 0 else "-") for r in rows]
    consistent = dirs[0] == dirs[1] == dirs[2]
    lines.append(f"| Period | CAGR 부호 |")
    lines.append("|---|---|")
    for r in rows:
        lines.append(f"| {r['period']} | {'+' if r['pf_cagr']>0 else '-'} |")
    lines.append("")
    lines.append(f"TRAIN→VALID→TEST CAGR 부호: {'일관' if consistent else '비일관'}")
    lines.append("")

    lines.append("## 4. 판정")
    lines.append("")
    lines.append("### ROBUST CANDIDATE / PROMISING / WEAK / REJECT 판단")
    lines.append("")
    lines.append("- **ROBUST CANDIDATE**: TEST portfolio 수익 양수 + TRAIN→VALID→TEST 방향 유지 + 특정 종목 미의존")
    lines.append("- **PROMISING**: TEST 수익 양수이나 표본/종목 집중 문제")
    lines.append("- **WEAK**: cross-sectional 효과는 있었으나 portfolio level에서 약함/비용 후 소멸")
    lines.append("- **REJECT**: portfolio level에서 TEST 효과 사라짐")
    lines.append("")

    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    with open(OUT, "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")
    print(f"\nSaved: {OUT}")


if __name__ == "__main__":
    main()
