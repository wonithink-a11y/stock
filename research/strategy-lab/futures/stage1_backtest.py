# -*- coding: utf-8 -*-
"""Futures 개인운용 Stage 1 백테스트.

원천 데이터: research/strategy-lab/.cache/leadlag/futures_1m.parquet
(KRX 선물 5종 × 주간/야간 1분봉, 2025-08-26 ~ 2026-09-03, 250거래일)

테스트 대상 (지시서 F1/F2, REJECT된 futures lead-lag 가설은 재실험하지 않음):
  F1  Donchian/Turtle : Entry 20/55 bar breakout, Exit 10/20 bar, ATR(14) Stop 2/3
  F2  MA Trend        : SMA 50/200 · EMA 50/200

실행 규칙:
  - Signal 는 bar close 에서 계산, 다음 bar open 에 체결 (look-ahead 금지)
  - Intrabar ATR stop 은 STOP_FIRST (stop 이 당일 시가 이상일 때 시가 체결 = 갭 리스크)
  - 롤오버(contract_changed) 봉은 시계열에서 제거
  - 두 방향(롱/숏) 모두 허용, 1계약 고정 · 자본 = 기간 내 최대 계약 명목 (leverage <= 1x)

계약 사양 (KRX 공식, 2026 기준):
  kospi200    승수 250,000 원/pt   틱 0.05 pt = 12,500 원
  kosdaq150   승수  10,000 원/pt   틱 0.10 pt =  1,000 원
  usd         승수  10,000 원/pt   틱 0.10 pt =  1,000 원 (거래단위 US $10,000)
  ktb3        승수 1,000,000 원/pt 틱 0.01 pt = 10,000 원 (액면 1억원 / 100)
  ktb10       승수 1,000,000 원/pt 틱 0.01 pt = 10,000 원

비용 모델 (편도): 명목 x 5bps (수수료율 상단, 위탁+거래소+청산 포함, 보수적) + 1틱 슬리피지
  총 왕복 ≈ 10bps + 2틱. 실사용 수수료(정액 계약당 ~수백원~수천원)보다 보수적.

산출물:
  research/strategy-lab/futures/futures-backtest-results.csv
  research/strategy-lab/futures/futures-stage1-results.json (보고서 작성용 상세)
"""
import json
import math
import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd

REPO = Path(__file__).resolve().parents[3]
DATA = REPO / "research" / "strategy-lab" / ".cache" / "leadlag" / "futures_1m.parquet"
OUTDIR = Path(__file__).resolve().parent
CSV_OUT = OUTDIR / "futures-backtest-results.csv"
JSON_OUT = OUTDIR / "futures-stage1-results.json"

# 멀티플라이어: 가격 1pt 변동 시 1계약 PnL(원). ktb 는 (액면1억/100).
MULT = {
    "kospi200": 250_000.0,
    "kosdaq150": 10_000.0,
    "usd": 10_000.0,
    "ktb3": 1_000_000.0,
    "ktb10": 1_000_000.0,
}
TICK = {
    "kospi200": (0.05, 12_500.0),
    "kosdaq150": (0.10, 1_000.0),
    "usd": (0.10, 1_000.0),
    "ktb3": (0.01, 10_000.0),
    "ktb10": (0.01, 10_000.0),
}

# 비용 모델 (편도): 증권사 수수료 500원/계약/편도 + 1틱 슬리피지
#   증권사 수수료: 키움/한국투자 등 개인 대상 정액 ~500원(위탁+KRX+청산 포함 상한)
#   슬리피지: 유동성 있는 선물 1틱 기준 (보수적)
#   실거래 시 정액 수수료(100~1000원)이므로 이 모델은 약간 보수적.
FEE_PER_SIDE_KRW = 500.0
SLIP_TICKS = 1.0

TIMEFRAMES = ["5m", "15m", "1h", "day"]
F1_COMBOS = [(en, ex, ak) for en in (20, 55) for ex in (10, 20) for ak in (2, 3)]
F2_MA = [("SMA", 50, 200), ("EMA", 50, 200)]
F2_MIN_SIGNAL_BARS = 100

DAYS_PER_YEAR = 365.25
TRADING_DAYS = 252.0


# ---------------------------------------------------------------- 데이터

def load_raw():
    df = pd.read_parquet(DATA)
    df = df[df["f_close"].notna() & (df["f_volume"] > 0)].copy()
    df["dt"] = pd.to_datetime(df["trade_date"]) + pd.to_timedelta(
        df["minute"].str.slice(0, 2).astype(int), unit="h"
    ) + pd.to_timedelta(df["minute"].str.slice(2, 4).astype(int), unit="m")
    return df


def build_series(sub, timeframe, continuous=False):
    sub = sub.sort_values("dt")
    if timeframe == "day":
        key = pd.to_datetime(sub["trade_date"])
    else:
        floor = {"5m": "5min", "15m": "15min", "1h": "1h"}[timeframe]
        key = sub["dt"].dt.floor(floor)
    g = sub.groupby(key)
    out = pd.DataFrame({
        "open": g["f_open"].first(),
        "high": g["f_high"].max(),
        "low": g["f_low"].min(),
        "close": g["f_close"].last(),
        "volume": g["f_volume"].sum(),
    })
    out["roll"] = g["contract_changed"].any()
    out = out[~out["roll"]].sort_index()
    return out


# ---------------------------------------------------------------- 지표

def indicators(b, entryN, exitM, atrN=14):
    o = b["open"].to_numpy(dtype=float)
    h = b["high"].to_numpy(dtype=float)
    l = b["low"].to_numpy(dtype=float)
    c = b["close"].to_numpy(dtype=float)
    n = len(b)
    # Donchian 채널 (직전 N개 봉의 최고/최저, 현재 봉 제외)
    dc_hi = pd.Series(h).rolling(entryN).max().shift(1).to_numpy()
    dc_lo = pd.Series(l).rolling(entryN).min().shift(1).to_numpy()
    ex_hi = pd.Series(h).rolling(exitM).max().shift(1).to_numpy()
    ex_lo = pd.Series(l).rolling(exitM).min().shift(1).to_numpy()
    lon = (c > dc_hi) & np.isfinite(dc_hi)
    sho = (c < dc_lo) & np.isfinite(dc_lo)
    exit_long = (c < ex_lo) & np.isfinite(ex_lo)
    exit_short = (c > ex_hi) & np.isfinite(ex_hi)
    # ATR(14) Wilder 스타일 (ewm alpha=1/n)
    pc = np.concatenate([[c[0]], c[:-1]])
    tr = np.maximum.reduce([h - l, (h - pc), (l - pc)])
    atr = pd.Series(tr).ewm(alpha=1.0 / atrN, adjust=False).mean().to_numpy()
    return dict(open=o, high=h, low=l, close=c, lon=lon, sho=sho,
                exit_long=exit_long, exit_short=exit_short, atr=atr)


# ---------------------------------------------------------------- 시뮬레이터

class Sim:
    def __init__(self, mult, tickval):
        self.mult = mult
        self.tickval = tickval
        self.trades = []
        self.realized = 0.0
        self.cost = 0.0
        self.pos = 0
        self.entry_px = np.nan
        self.atr_entry = np.nan
        self._cur = None

    def _cost(self, px):
        return FEE_PER_SIDE_KRW + self.tickval * SLIP_TICKS

    def open_trade(self, side, px, ts):
        self.pos = side
        self.entry_px = px
        self.cost += self._cost(px)
        self._cur = dict(side=side, entry_px=px, entry_ts=ts)

    def close_trade(self, px, ts):
        gross = self.pos * (px - self.entry_px) * self.mult
        self.realized += gross
        self.cost += self._cost(px)
        self._cur["exit_px"] = px
        self._cur["exit_ts"] = ts
        self._cur["gross"] = gross
        self._cur["cost"] = self._cost(self.entry_px) + self._cost(px)
        self.trades.append(self._cur)
        self.pos = 0
        self._cur = None


def run_f1(b, en, exn, atrk, mult, tickval):
    iv = indicators(b, en, exn)
    o, h, l, c = iv["open"], iv["high"], iv["low"], iv["close"]
    lon, sho = iv["lon"], iv["sho"]
    xl, xs = iv["exit_long"], iv["exit_short"]
    atr = iv["atr"]
    n = len(b)
    ts = b.index.to_numpy()
    sim = Sim(mult, tickval)
    pending_exit = False
    eq_net, eq_gross = [], []
    for i in range(1, n):
        if not np.isfinite(atr[i - 1]):
            eq_net.append(-sim.cost)
            eq_gross.append(sim.realized + 0.0)
            continue
        # --- open 체결: exit(channel pending / 반대 breakout) -> flip/신규
        if sim.pos == 1 and (pending_exit or sho[i - 1]):
            sim.close_trade(o[i], ts[i])
        elif sim.pos == -1 and (pending_exit or lon[i - 1]):
            sim.close_trade(o[i], ts[i])
        pending_exit = False
        if sim.pos == 0:
            if lon[i - 1]:
                sim.open_trade(1, o[i], ts[i])
                sim.atr_entry = atr[i - 1]
            elif sho[i - 1]:
                sim.open_trade(-1, o[i], ts[i])
                sim.atr_entry = atr[i - 1]
        # --- intrabar ATR stop (STOP_FIRST, 갭 시 시가 체결)
        if sim.pos == 1:
            stop = sim.entry_px - atrk * sim.atr_entry
            if l[i] <= stop:
                sim.close_trade(stop if o[i] > stop else o[i], ts[i])
        elif sim.pos == -1:
            stop = sim.entry_px + atrk * sim.atr_entry
            if h[i] >= stop:
                sim.close_trade(stop if o[i] < stop else o[i], ts[i])
        # --- mark
        opnl = sim.pos * (c[i] - sim.entry_px) * mult if sim.pos != 0 else 0.0
        eq_net.append(sim.realized - sim.cost + opnl)
        eq_gross.append(sim.realized + opnl)
        # --- close 시 채널 exit 예약
        if sim.pos == 1 and xl[i]:
            pending_exit = True
        elif sim.pos == -1 and xs[i]:
            pending_exit = True
    if sim.pos != 0:
        sim.close_trade(c[-1], ts[-1])
        eq_net[-1] = sim.realized - sim.cost
        eq_gross[-1] = sim.realized
    return sim, np.asarray(eq_net), np.asarray(eq_gross), ts


def run_f2(b, ma_type, fast, slow, mult, tickval):
    c = b["close"]
    if ma_type == "SMA":
        f = c.rolling(fast).mean()
        s = c.rolling(slow).mean()
    else:
        f = c.ewm(span=fast, adjust=False).mean()
        s = c.ewm(span=slow, adjust=False).mean()
    tgt = np.where((f > s).to_numpy(bool), 1.0,
                   np.where((f < s).to_numpy(bool), -1.0, 0.0))
    tgt[np.isnan(tgt)] = 0.0
    o = b["open"].to_numpy(dtype=float)
    c = c.to_numpy(dtype=float)
    n = len(b)
    ts = b.index.to_numpy()
    sim = Sim(mult, tickval)
    eq_net, eq_gross = [], []
    for i in range(1, n):
        want = tgt[i - 1]
        if want != sim.pos:
            if sim.pos != 0:
                sim.close_trade(o[i], ts[i])
            if want != 0:
                sim.open_trade(want, o[i], ts[i])
        opnl = sim.pos * (c[i] - sim.entry_px) * mult if sim.pos != 0 else 0.0
        eq_net.append(sim.realized - sim.cost + opnl)
        eq_gross.append(sim.realized + opnl)
    if sim.pos != 0:
        sim.close_trade(c[-1], ts[-1])
        eq_net[-1] = sim.realized - sim.cost
        eq_gross[-1] = sim.realized
    return sim, np.asarray(eq_net), np.asarray(eq_gross), ts


# ---------------------------------------------------------------- 지표 계산

def metrics(sim, eq_net, eq_gross, ts, cap, label):
    span_days = float((np.datetime64(ts[-1]) - np.datetime64(ts[0])) / np.timedelta64(1, "D"))
    years = max(span_days / DAYS_PER_YEAR, 1e-9)
    stays_dt = pd.DatetimeIndex(ts)
    pos_ts = stays_dt[1:]  # eq arrays 길이 = n-1
    pos_ts = pos_ts[: len(eq_net)]
    cap = float(cap)
    eqn = pd.Series(eq_net + cap, index=pos_ts)
    eqg = pd.Series(eq_gross + cap, index=pos_ts)
    if len(eqn) < 2:
        return None
    daily_n = eqn.resample("D").last().dropna()
    daily_g = eqg.resample("D").last().dropna()
    rets_n = daily_n.pct_change().dropna() if len(daily_n) > 1 else pd.Series(dtype=float)
    rets_g = daily_g.pct_change().dropna() if len(daily_g) > 1 else pd.Series(dtype=float)

    def stats(eq, rets):
        final = eq.iloc[-1]
        cagr = (final / cap) ** (1.0 / years) - 1.0
        if len(rets) > 1:
            sd = rets.std(ddof=1)
        else:
            sd = 0.0
        sharpe = rets.mean() / sd * math.sqrt(TRADING_DAYS) if sd and sd > 0 else np.nan
        downside = rets[rets < 0]
        dsd = downside.std(ddof=1) if len(downside) > 1 else 0.0
        sortino = rets.mean() / dsd * math.sqrt(TRADING_DAYS) if dsd and dsd > 0 else np.nan
        peak = eq.cummax()
        mdd = float(((eq - peak) / peak).min()) if len(eq) > 1 else 0.0
        return cagr, sharpe, sortino, mdd, final

    cagr_n, sharpe_n, sortino_n, mdd_n, _ = stats(eqn, rets_n)
    cagr_g, sharpe_g, sortino_g, mdd_g, final_g = stats(eqg, rets_g)
    mdd_n = float(mdd_n) if mdd_n == mdd_n else np.nan
    calmar_n = cagr_n / abs(mdd_n) if mdd_n and mdd_n < 0 else np.nan

    wins = [t for t in sim.trades if t["gross"] > 0]
    losses = [t for t in sim.trades if t["gross"] <= 0]
    n_trades = len(sim.trades)
    win_rate = len(wins) / n_trades if n_trades else np.nan
    gw = sum(t["gross"] for t in wins)
    gl = sum(t["gross"] for t in losses)
    pf = gw / abs(gl) if abs(gl) > 1e-9 else (np.inf if gw > 0 else np.nan)
    avg_win = gw / len(wins) if wins else np.nan
    avg_loss = gl / len(losses) if losses else np.nan
    expectancy = (gw + gl - sim.cost) / n_trades if n_trades else np.nan
    tot_turn = sum((t["entry_px"] + t["exit_px"]) * sim.mult for t in sim.trades)
    turnover_yr = tot_turn / cap / years if cap > 0 else np.nan

    return {
        "label": label,
        "status": "OK",
        "years": round(years, 4),
        "bars": len(eq_net),
        "capital_krw": round(cap, 0),
        "trade_count": n_trades,
        "trades_per_year": round(n_trades / years, 2),
        "cagr_gross": round(cagr_g, 4),
        "cagr_net": round(cagr_n, 4),
        "sharpe_net": round(sharpe_n, 3),
        "sharpe_gross": round(sharpe_g, 3),
        "sortino_net": round(sortino_n, 3),
        "calmar_net": round(calmar_n, 3),
        "mdd_net": round(mdd_n, 4),
        "mdd_gross": round(mdd_g, 4),
        "win_rate": round(win_rate, 4) if win_rate == win_rate else None,
        "profit_factor": round(pf, 3) if pf == pf else None,
        "avg_win_krw": round(avg_win, 0) if avg_win == avg_win else None,
        "avg_loss_krw": round(avg_loss, 0) if avg_loss == avg_loss else None,
        "expectancy_krw": round(expectancy, 0) if expectancy == expectancy else None,
        "expectancy_pct_cap": round(expectancy / cap, 6) if expectancy == expectancy else None,
        "total_cost_krw": round(sim.cost, 0),
        "total_cost_pct_cap": round(sim.cost / cap, 5),
        "turnover_per_yr": round(turnover_yr, 2) if turnover_yr == turnover_yr else None,
        "final_equity_net_krw": round(eqn.iloc[-1], 0),
        "final_equity_gross_krw": round(eqg.iloc[-1], 0),
    }


def f1_params_str(en, exn, ak):
    return f"dn_entry{en}_exit{exn}_atr{ak}"


def main():
    t0 = time.time()
    df = load_raw()
    rows = []
    detail = {}

    # 시리즈 정의: day 세션 전 상품, 24h 연속(kospi200·usd) 추기
    series_defs = []
    for p in ["kospi200", "kosdaq150", "usd", "ktb3", "ktb10"]:
        series_defs.append((f"{p}_day", df[(df["product"] == p) & (df["session"] == "day")]))
    for p in ["kospi200", "usd"]:
        series_defs.append((f"{p}_24h", df[df["product"] == p]))

    for name, sub in series_defs:
        p = name.rsplit("_", 1)[0]
        mult = MULT[p]
        _tick, tickval = TICK[p]
        for tf in TIMEFRAMES:
            if name.endswith("_24h") and tf == "day":
                continue
            b = build_series(sub, tf)
            if len(b) < 60:
                continue
            detail.setdefault(name, {})
            cap = float(b["close"].max()) * mult
            for en, exn, ak in F1_COMBOS:
                sim, eqn, eqg, ts = run_f1(b, en, exn, ak, mult, tickval)
                m = metrics(sim, eqn, eqg, ts, cap, f"F1:{f1_params_str(en, exn, ak)}")
                if m is None:
                    continue
                m.update(strategy="F1", product=p, series=name, timeframe=tf,
                         params=f1_params_str(en, exn, ak), entry=en, exit=exn, atr=ak)
                rows.append(m)
                detail[name].setdefault(tf, {})[m["params"]] = m
            for mt, fast, slow in F2_MA:
                lab = f"F2:{mt}{fast}_{slow}"
                if (len(b) - slow) < F2_MIN_SIGNAL_BARS:
                    rec = {"strategy": "F2", "product": p, "series": name, "timeframe": tf,
                           "params": f"{mt}{fast}_{slow}", "entry": None, "exit": None, "atr": None,
                           "status": "INSUFFICIENT_DATA", "bars": len(b), "years": None,
                           "reason": f"slow={slow}, signal bars {len(b)-slow} < {F2_MIN_SIGNAL_BARS}"}
                    rows.append(rec)
                    detail.setdefault(name, {}).setdefault(tf, {})[lab] = {
                        "status": "INSUFFICIENT_DATA",
                        "reason": f"bars={len(b)}, slow={slow} → 신호 가능 봉 {len(b)-slow} < {F2_MIN_SIGNAL_BARS}",
                    }
                    continue
                sim, eqn, eqg, ts = run_f2(b, mt, fast, slow, mult, tickval)
                m = metrics(sim, eqn, eqg, ts, cap, lab)
                if m is None:
                    m = {"status": "INSUFFICIENT_DATA", "reason": "no trades", "label": lab}
                    m.update(strategy="F2", product=p, series=name, timeframe=tf,
                             params=f"{mt}{fast}_{slow}", entry=None, exit=None, atr=None, years=None,
                             bars=len(b))
                    rows.append(m)
                    detail[name].setdefault(tf, {})[lab] = m
                    continue
                m.update(strategy="F2", product=p, series=name, timeframe=tf,
                         params=f"{mt}{fast}_{slow}", entry=None, exit=None, atr=None)
                rows.append(m)
                detail[name].setdefault(tf, {})[lab] = m

    # 벤치마크: day 세션 1계약 롱-바이앤홀드 (롤 갭은 근사로 무시)
    bench_rows = []
    for p in ["kospi200", "kosdaq150", "usd", "ktb3", "ktb10"]:
        b = build_series(df[(df["product"] == p) & (df["session"] == "day")], "day")
        c = b["close"].to_numpy(dtype=float)
        mult = MULT[p]
        tickval = TICK[p][1]
        entry_px = c[0]
        exit_px = c[-1]
        cost = 2.0 * (FEE_PER_SIDE_KRW + tickval * SLIP_TICKS)
        gross = (exit_px - entry_px) * mult
        net = gross - cost
        n = len(c)
        cap = float(b["close"].max()) * mult
        idx = pd.DatetimeIndex(b.index)
        years = (idx[-1] - idx[0]).days / DAYS_PER_YEAR
        rets = pd.Series(c).pct_change().dropna()
        cagr = ((cap + net) / cap) ** (1.0 / years) - 1.0
        sd = rets.std(ddof=1)
        sharpe = rets.mean() / sd * math.sqrt(TRADING_DAYS) if sd and sd > 0 else np.nan
        downs = rets[rets < 0]
        sortino = rets.mean() / (downs.std(ddof=1)) * math.sqrt(TRADING_DAYS) if len(downs) > 1 else np.nan
        eqs = pd.Series(c * mult, index=idx)
        peak = eqs.cummax()
        mdd = float(((eqs - peak) / peak).min())
        bench_rows.append({
            "strategy": "benchmark", "product": p, "series": f"{p}_day", "timeframe": "day",
            "params": "long_1contract_buyhold", "entry": None, "exit": None, "atr": None,
            "status": "OK", "bars": n, "years": round(years, 4), "capital_krw": round(cap, 0),
            "cagr_net": round(cagr, 4), "sharpe_net": round(sharpe, 3), "sortino_net": round(sortino, 3),
            "mdd_net": round(mdd, 4), "trade_count": 1, "trades_per_year": round(1.0 / years, 2),
            "total_cost_krw": round(cost, 0), "final_equity_net_krw": round(cap + net, 0),
            "final_equity_gross_krw": round(cap + gross, 0), "expectancy_krw": round(net, 0),
        })
    rows += bench_rows

    cols = ["strategy", "product", "series", "timeframe", "params", "entry", "exit", "atr",
            "status", "reason", "years", "bars", "capital_krw", "trade_count", "trades_per_year",
            "cagr_gross", "cagr_net", "sharpe_net", "sharpe_gross", "sortino_net", "calmar_net",
            "mdd_net", "mdd_gross", "win_rate", "profit_factor", "avg_win_krw", "avg_loss_krw",
            "expectancy_krw", "expectancy_pct_cap", "total_cost_krw", "total_cost_pct_cap",
            "turnover_per_yr", "final_equity_net_krw", "final_equity_gross_krw"]
    out = pd.DataFrame(rows)
    for c in cols:
        if c not in out.columns:
            out[c] = None
    out = out[cols].sort_values(["strategy", "series", "timeframe", "params"])
    out.to_csv(CSV_OUT, index=False, encoding="utf-8-sig")

    bench = {r["product"]: r for r in bench_rows}
    payload = {"detail": detail, "benchmark": bench}
    JSON_OUT.write_text(json.dumps(payload, ensure_ascii=False, indent=2, default=str), encoding="utf-8")

    print(f"rows={len(out)}  elapsed={time.time()-t0:.1f}s")
    print(f"csv : {CSV_OUT}")
    print(f"json: {JSON_OUT}")
    return out


if __name__ == "__main__":
    main()