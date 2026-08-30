#!/usr/bin/env python
"""Step 9 — KR Squeeze + Volume Expansion 검증 (Crypto S2 이식).

목적: Crypto에서 TEST 유일 PROMISING이었던 S2
"Squeeze + Breakout + Volume Expansion" 구조가 한국 주식에서도 작동하는지 검증.

Crypto S2 정확한 조건 (bb_squeeze_vol_v1/rule.py · policy.json, verbatim):
  - BB(period=20, std=2.0, ddof=0 population) on close
  - bbwidth = (upper - lower) / mid
  - squeeze = bbwidth의 trailing 100봉 내 percentile rank <= 0.20
  - breakout = close[t] > upper[t] AND close[t-1] <= upper[t-1]  (fresh cross)
  - vol_ok = volume[t] > SMA(volume, 20)[t] * 1.5
  - entry_cond = squeeze AND breakout AND vol_ok  (동일 봉 t)
  - 진입: 신호 다음 거래일 OPEN

전략랩 매도/포지션 규칙 (사용자 선택: 표준 보유기간 청산):
  - 진입: 신호 다음 거래일 OPEN (A2a adjusted)
  - 청산: 보유 5 trading days 뒤 종가 (Strategy Lab 표준, Step 6/7과 동일)
  - 비용: 프로젝트 기본 30bps RT (COST_RT_BPS=30)
  - Top-10 동일가중 (Step 7과 동일), 겹치는 롤링 코호트

새 feature/파라미터 최적화/새 전략 없음. S2 구조만 이식.
"""
import os
import sys

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from engine.data.a2aProvider import A2aProvider  # noqa: E402

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
DATA = os.path.join(REPO_ROOT, "research", "strategy-lab", "data", "a4", "a4-research-dataset.parquet")
OUT = os.path.join(REPO_ROOT, "research", "strategy-lab", "findings", "kr-squeeze-volume-2026-08.md")

# --- S2 파라미터 (Crypto, verbatim) ---
BB_PERIOD = 20
BB_STD = 2.0
SQUEEZE_LOOKBACK = 100
SQUEEZE_PCT = 0.20
VOL_SMA_PERIOD = 20
VOL_RATIO_MIN = 1.5

# --- Strategy Lab 표준 ---
COST_RT_BPS = 30.0
TOP_N = 10
HOLD = 5
TRADING_DAYS = 252.0

SPLIT = {
    "TRAIN": ("2016-01-01", "2022-07-01"),
    "VALID": ("2022-07-01", "2024-01-01"),
    "TEST":  ("2024-01-01", "2026-12-31"),
}


def series_metrics(daily):
    r = daily.dropna()
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
    return {"total": float(total), "cagr": float(cagr), "mdd": float(mdd),
            "sharpe": sharpe, "calmar": calmar, "n": int(n)}


def compute_s2_signals(bars_by_ticker, vol_by_ticker):
    """Crypto S2 entry_cond(verbatim)를 한국주식 데일리 OHLCV에 적용.
    bars_by_ticker: ticker->DataFrame[index=date, open,close]
    vol_by_ticker:  ticker->DataFrame[date->volume] (A4 raw volume)
    returns: list of (ticker, signal_date)"""
    signals = []
    for tk, df in bars_by_ticker.items():
        if tk not in vol_by_ticker:
            continue
        f = df.copy()
        v = vol_by_ticker[tk]
        f = f.join(v, how="left")
        if f["volume"].isna().all():
            continue
        mid = f["close"].rolling(BB_PERIOD).mean()
        std = f["close"].rolling(BB_PERIOD).std(ddof=0)
        upper = mid + BB_STD * std
        bbwidth = ((upper - (mid - BB_STD * std)) / mid)
        pctile = bbwidth.rolling(SQUEEZE_LOOKBACK).rank(pct=True)
        squeeze = pctile <= SQUEEZE_PCT
        above = f["close"] > upper
        prev_above = above.shift(1, fill_value=False)
        breakout = above & ~prev_above
        vol_sma20 = f["volume"].rolling(VOL_SMA_PERIOD).mean()
        vol_ok = f["volume"] > vol_sma20 * VOL_RATIO_MIN
        warmup = upper.notna() & pctile.notna() & vol_sma20.notna()
        entry_cond = squeeze & breakout & vol_ok & warmup
        for d in f.index[entry_cond]:
            signals.append((tk, d))
    return signals


class PriceIndex:
    def __init__(self, prices):
        self.tickers = {}
        for tk, px in prices.items():
            dts = list(px.index)
            self.tickers[tk] = {
                "dates": dts,
                "idx": {d: i for i, d in enumerate(dts)},
                "open": px["open"].to_numpy(dtype=np.float64),
                "close": px["close"].to_numpy(dtype=np.float64),
            }

    def get(self, tk):
        return self.tickers.get(tk)


def portfolio_daily(signal_list, pi, top_n, cost_bp, hold=HOLD):
    """signal_list -> (ticker, signal_date). Top-n per signal_date(티커 asc),
    open entry, hold일 보유, exit-day cost 차감. rolling equal-weight.
    returns: (daily_Series, positions DataFrame)"""
    sig = pd.DataFrame(signal_list, columns=["ticker", "signal_date"])
    sig = sig.sort_values(["signal_date", "ticker"])
    if top_n is not None:
        sig["r"] = sig.groupby("signal_date").cumcount()
        sig = sig[sig["r"] < top_n]
    pos_rows = []
    for tk, g in sig.groupby("ticker"):
        p = pi.get(tk)
        if p is None:
            continue
        idx_map = p["idx"]
        dts = p["dates"]
        o = p["open"]
        cl = p["close"]
        n = len(dts)
        sig_idx = np.array([idx_map[d] for d in g["signal_date"] if d in idx_map], dtype=np.int64)
        if len(sig_idx) == 0:
            continue
        valid = sig_idx + hold < n
        sig_idx = sig_idx[valid]
        if len(sig_idx) == 0:
            continue
        entry = sig_idx + 1
        o1 = o[entry]
        closes = np.stack([cl[entry + k] for k in range(hold)], axis=1)
        ok = np.isfinite(o1) & (o1 > 0) & np.all(np.isfinite(closes), axis=1) & np.all(closes > 0, axis=1)
        sig_idx = sig_idx[ok]
        if len(sig_idx) == 0:
            continue
        entry = sig_idx + 1
        o1 = o[entry]
        closes = np.stack([cl[entry + k] for k in range(hold)], axis=1)
        rets = [closes[:, 0] / o1 - 1.0]
        for k in range(1, hold):
            r = closes[:, k] / closes[:, k - 1] - 1.0
            if k == hold - 1:
                r = r - cost_bp / 1e4
            rets.append(r)
        dates_rows = []
        for k in range(hold):
            dates_rows.append([dts[e + k] for e in entry])
        for k in range(hold):
            for dd, rr in zip(dates_rows[k], rets[k]):
                pos_rows.append({"ticker": tk, "date": dd, "ret": rr})
    posdf = pd.DataFrame(pos_rows)
    if posdf.empty:
        return pd.Series(dtype=float), pd.DataFrame(columns=["ticker", "date", "ret"])
    daily = posdf.groupby("date")["ret"].mean()
    return daily, posdf


def main():
    print("Loading A4 + A2a...")
    a4 = pd.read_parquet(DATA, columns=["ticker", "date", "close", "total_volume"])
    a4["date"] = pd.to_datetime(a4["date"])
    a4 = a4[["ticker", "date", "total_volume"]].rename(columns={"total_volume": "volume"})

    tickers = set(a4["ticker"].unique())
    a2a = A2aProvider(repo_root=REPO_ROOT, use_cache=True)
    start = a4["date"].min().strftime("%Y-%m-%d")
    end = a4["date"].max().strftime("%Y-%m-%d")
    bars = a2a.load(tickers, start, end, universe_hash="kr-squeeze-volume")
    bars_by_ticker = {t: df[["open", "close"]].copy() for t, df in bars.items()}
    prices = {t: df[["open", "close"]].copy() for t, df in bars.items()}
    pi = PriceIndex(prices)

    # per-ticker volume series
    vol_by_ticker = {}
    for tk, g in a4.groupby("ticker"):
        vol_by_ticker[tk] = g.set_index("date")["volume"]

    print(f"  A4 tickers={len(tickers)} | A2a tickers={len(bars_by_ticker)}")
    signal_list = compute_s2_signals(bars_by_ticker, vol_by_ticker)
    print(f"  S2 signals (full)= {len(signal_list)}")

    # universe EW daily (benchmark) — A4 close 기반
    a4c = pd.read_parquet(DATA, columns=["ticker", "date", "close"])
    a4c["date"] = pd.to_datetime(a4c["date"])
    bh = []
    for tk, g in a4c.groupby("ticker"):
        g = g.sort_values("date")
        bh.append(pd.DataFrame({"date": g["date"], "ret": (g["close"].shift(-1) / g["close"] - 1).values}))
    bh = pd.concat(bh, ignore_index=True).dropna()
    bh_ret = bh.groupby("date")["ret"].mean()

    lines = []
    lines.append("# KR Squeeze + Volume Expansion — Crypto S2 구조 검증")
    lines.append("")
    lines.append("> 분석 일시: 2026-08-28 | 데이터: A4 + A2a adjusted")
    lines.append(f"> 기간: {a4c['date'].min().date()} ~ {a4c['date'].max().date()} | 종목: {a4c['ticker'].nunique()}")
    lines.append("> S2 신호: BB squeeze + fresh breakout + volume expansion (Crypto bb_squeeze_vol_v1, verbatim)")
    lines.append("> 진입: 신호 다음 거래일 OPEN | 보유: 5 trading days 종가 청산 (전략랩 표준) | 비용: 30bps RT")
    lines.append("")

    lines.append("## 0. Crypto S2 원본 조건 (문서화, verbatim)")
    lines.append("")
    lines.append("| 항목 | 값 (bb_squeeze_vol_v1 policy.json/rule.py) |")
    lines.append("|---|---|")
    lines.append("| BB period / std | 20 / 2.0 (population ddof=0, close) |")
    lines.append("| bandwidth | (upper−lower)/mid |")
    lines.append("| squeeze | BBwidth의 trailing 100봉 percentile rank ≤ 0.20 |")
    lines.append("| breakout | close[t]>upper[t] & close[t−1]≤upper[t−1] (fresh cross) |")
    lines.append("| volume | volume[t] > SMA(volume,20)[t] × 1.5 |")
    lines.append("| entry | squeeze AND breakout AND vol_ok (동일 봉) → 다음 봉 OPEN |")
    lines.append("| 원본 매도 | ATR(14) 2×스톱 / RR 3.0 / 60봉 시간청산 (→ 본 검증은 전략랩 표준 보유기간 청산으로 대체, 사용자 결정) |")
    lines.append("")

    # FULL 성과 (Top10, 30bp)
    daily, _ = portfolio_daily(signal_list, pi, TOP_N, COST_RT_BPS)
    lines.append("## 1. FULL 성과 (Top10, 30bps RT)")
    lines.append("")
    m = series_metrics(daily)
    lines.append(f"- CAGR {m['cagr']:+.4f} | MDD {m['mdd']:.4f} | Sharpe {m['sharpe']:.3f} | Calmar {m['calmar']:.3f} | Total {m['total']:+.4f}")
    lines.append(f"- 일평균 수익 {daily.mean():+.4f}, 활성 일수 {m['n']}")
    ew_full = series_metrics(bh_ret)
    lines.append(f"- Universe EW B&H: CAGR {ew_full['cagr']:+.4f} | Total {ew_full['total']:+.4f} | MDD {ew_full['mdd']:.4f}")
    lines.append("")

    # split
    lines.append("## 2. TRAIN / VALID / TEST")
    lines.append("")
    lines.append("| Period | n_trades | CAGR | MDD | Sharpe | Calmar | Total | EW B&H Total | 승률 | PF | AvgHold |")
    lines.append("|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|")
    # per-period positions for trade-level stats
    split_rows = {}
    for pname, (s, e) in SPLIT.items():
        # filter by signal_date string compare
        sub_sig = [x for x in signal_list if s <= x[1].strftime("%Y-%m-%d") < e]
        d, posdf = portfolio_daily(sub_sig, pi, TOP_N, COST_RT_BPS)
        m = series_metrics(d)
        bhm = series_metrics(bh_ret[(bh_ret.index >= s) & (bh_ret.index < e)])
        trades = len(sub_sig)
        nets = [r[2] for r in position_net_list(sub_sig, pi, TOP_N)]
        wins = sum(1 for x in nets if x > 0)
        win_rate = wins / len(nets) if nets else np.nan
        gross_pnl = sum(max(x, 0.0) for x in nets)
        loss_pnl = sum(max(-x, 0.0) for x in nets)
        pf = gross_pnl / loss_pnl if loss_pnl > 0 else np.nan
        split_rows[pname] = (d, posdf)
        lines.append(f"| {pname} | {trades} | {m['cagr']:+.4f} | {m['mdd']:.4f} | {m['sharpe']:.3f} | {m['calmar']:.3f} | {m['total']:+.4f} | {bhm['total']:+.4f} | {win_rate:.3f} | {pf:.3f} | {HOLD} |")
    lines.append("")

    # cost sensitivity (Top10, FULL; per split TEST 우선)
    lines.append("## 3. 비용 민감도 (Top10, FULL 기준 CAGR / Total)")
    lines.append("")
    lines.append("| Multiplier | cost(bp) | CAGR | Total |")
    lines.append("|---|---:|---:|---:|")
    for mult, name in [(0, "0x"), (1, "1x"), (2, "2x"), (4, "4x")]:
        cb = COST_RT_BPS * mult
        d, _ = portfolio_daily(signal_list, pi, TOP_N, cb)
        m = series_metrics(d)
        lines.append(f"| {name} | {cb:.0f} | {m['cagr']:+.4f} | {m['total']:+.4f} |")
    lines.append("")

    # TEST 연도별
    lines.append("## 4. TEST 연도별 성과")
    lines.append("")
    lines.append("| Year | n_sig | CAGR | Total |")
    lines.append("|---|---:|---:|---:|")
    test_sigs = [x for x in signal_list if SPLIT["TEST"][0] <= x[1].strftime("%Y-%m-%d") < SPLIT["TEST"][1]]
    for yr in sorted({x[1].year for x in test_sigs}):
        sub = [x for x in test_sigs if x[1].year == yr]
        d, _ = portfolio_daily(sub, pi, TOP_N, COST_RT_BPS)
        m = series_metrics(d)
        lines.append(f"| {yr} | {len(sub)} | {m['cagr']:+.4f} | {m['total']:+.4f} |")
    lines.append("")

    # TEST ticker concentration
    lines.append("## 5. 종목별 PnL concentration (TEST)")
    lines.append("")
    test_d, test_pos = portfolio_daily(test_sigs, pi, TOP_N, COST_RT_BPS)
    by_tk = test_pos.groupby("ticker")["ret"].sum()
    total = by_tk.sum()
    lines.append(f"- TEST 일별 누적 net PnL 합 = {total:+.4f} ({test_pos['ticker'].nunique()} 종목)")
    lines.append(f"- 상위 5 종목 적립 net = {by_tk.nlargest(5).sum():+.4f} (기여 {by_tk.nlargest(5).sum()/total if total!=0 else float('nan'):.3f})")
    lines.append(f"- 하위 5 종목 적립 net = {by_tk.nsmallest(5).sum():+.4f}")
    lines.append(f"- 최대 손실 종목 = {by_tk.min():+.4f} ({by_tk.idxmin()}), 최대 이익 종목 = {by_tk.max():+.4f} ({by_tk.idxmax()})")
    lines.append("")

    # TEST event(date) concentration
    lines.append("## 6. 진입 이벤트(signal-date)별 concentration (TEST)")
    lines.append("")
    ev_rows = []
    for sig_ev in sorted(set([x[1].date() for x in test_sigs])):
        ev_sigs = [x for x in test_sigs if x[1].date() == sig_ev]
        if not ev_sigs:
            continue
        tot = sum(sig_event_stats(ev_sigs, pi).values())
        ev_rows.append((sig_ev, len(ev_sigs), tot))
    ev_rows.sort(key=lambda x: x[2], reverse=True)
    ev_total = sum(r[2] for r in ev_rows)
    lines.append(f"- TEST 이벤트(signal-date) 수 = {len(ev_rows)}, net PnL 합 = {ev_total:+.4f}")
    if ev_total != 0:
        lines.append(f"- 최대 단일 이벤트 = {ev_rows[0][2]:+.4f} ({ev_rows[0][0]}, n={ev_rows[0][1]}) 기여 {ev_rows[0][2]/ev_total:.3f}")
        lines.append(f"- 상위 3 이벤트 기여 = {sum(r[2] for r in ev_rows[:3])/ev_total:.3f}")
    lines.append("")
    lines.append("### 상위 5 이벤트(signal-date)")
    lines.append("")
    lines.append("| signal-date | n 종목 | net PnL(코호트 5D) |")
    lines.append("|---|---:|---:|")
    for ev, n, tot in ev_rows[:5]:
        lines.append(f"| {ev} | {n} | {tot:+.4f} |")
    lines.append("")

    with open(OUT, "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")
    print(f"\nSaved: {OUT}")

    print("\n=== FULL ===")
    m = series_metrics(daily)
    print(f"  CAGR={m['cagr']:+.4f} MDD={m['mdd']:.4f} Sharpe={m['sharpe']:.3f} Calmar={m['calmar']:.3f} Total={m['total']:+.4f}")
    print("\n=== Split ===")
    for pname, (s, e) in SPLIT.items():
        sub = [x for x in signal_list if s <= x[1].strftime("%Y-%m-%d") < e]
        d, _ = portfolio_daily(sub, pi, TOP_N, COST_RT_BPS)
        m = series_metrics(d)
        print(f"  {pname:6s} n={len(sub):5d} CAGR={m['cagr']:+.4f} Total={m['total']:+.4f} MDD={m['mdd']:.4f} Sharpe={m['sharpe']:.3f}")
    print("\n=== Cost sensitivity (FULL) ===")
    for mult in [0, 1, 2, 4]:
        d, _ = portfolio_daily(signal_list, pi, TOP_N, COST_RT_BPS * mult)
        m = series_metrics(d)
        print(f"  {mult}x CAGR={m['cagr']:+.4f} Total={m['total']:+.4f}")


def sig_event_stats(ev_sigs, pi):
    """이벤트(같은 signal_date) 각 종목의 5D roundtrip net return dict."""
    out = {}
    for tk, sd in ev_sigs:
        p = pi.get(tk)
        if p is None:
            continue
        idx_map = p["idx"]
        if sd not in idx_map:
            continue
        i = idx_map[sd]
        o = p["open"]; cl = p["close"]
        if i + HOLD >= len(cl):
            continue
        o1 = o[i + 1]
        c5 = cl[i + HOLD]
        if np.isfinite(o1) and o1 > 0 and np.isfinite(c5) and c5 > 0:
            out[tk] = c5 / o1 - 1.0 - COST_RT_BPS / 1e4
    return out


def position_net_list(signal_list, pi, top_n):
    """선택(signal_date별 top_n) 후 각 포지션의 5D net roundtrip return list.
    returns: list of (ticker, signal_date, net_ret). win rate/PF/avgHold 계산용."""
    sig = pd.DataFrame(signal_list, columns=["ticker", "signal_date"])
    sig = sig.sort_values(["signal_date", "ticker"])
    if top_n is not None:
        sig["r"] = sig.groupby("signal_date").cumcount()
        sig = sig[sig["r"] < top_n]
    out = []
    for tk, sd in zip(sig["ticker"], sig["signal_date"]):
        p = pi.get(tk)
        if p is None:
            continue
        idx_map = p["idx"]
        if sd not in idx_map:
            continue
        i = idx_map[sd]
        o = p["open"]; cl = p["close"]
        if i + HOLD >= len(cl):
            continue
        o1 = o[i + 1]
        c5 = cl[i + HOLD]
        if np.isfinite(o1) and o1 > 0 and np.isfinite(c5) and c5 > 0:
            out.append((tk, sd, c5 / o1 - 1.0 - COST_RT_BPS / 1e4))
    return out


if __name__ == "__main__":
    main()
