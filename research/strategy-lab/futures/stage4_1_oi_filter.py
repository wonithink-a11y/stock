# -*- coding: utf-8 -*-
"""Stage 4-1: KOSPI200 선물 일봉 OI(미결제약정) 추세 확인 필터 검증.

- 원천: research/strategy-lab/.cache/kospi200_daily/ (Stage 3-2에서 이미 수집한 4,109거래일)
- 연속선물: 일별 최대거래량 근월, 롤오버봉 제거 (Stage 3-2 관례 그대로)
- 비교:
    A = EMA50/200 Long-only (기준, Stage 3-2 재현)
    B = A + OI 증가 필터 (진입 추가 조건, 청산은 EMA만)
  진입: EMA50>EMA200 AND OI[전일] > OI[2일전]
  청산: EMA50<EMA200
- signal은 bar close → 다음 bar open 체결, look-ahead 금지
- 비용: 편도 500원 + 1틱(12,500원), 자본=기간 내 최대 명목 (leverage<=1x)
- 기간: 2010~2017 / 2018~2024 / 2025~ / 전체
- 금지(미실행): OI 임계값 최적화·감소조건·ROC/백분위 변형·Short·Donchian·ATR·레짐·sweep·WFA/OOS
"""
import math
from pathlib import Path

import numpy as np
import pandas as pd

REPO = Path(r"C:\Users\User\projects\stock")
CACHE = REPO / "research" / "strategy-lab" / ".cache" / "kospi200_daily"
OUTDIR = REPO / "research" / "strategy-lab" / "futures"

MULT = 250_000.0
TICKVAL = 12_500.0
FEE_PER_SIDE = 500.0
SLIP_TICKS = 1.0
DAYS_PER_YEAR = 365.25
TRADING_DAYS = 252.0

MA_FAST, MA_SLOW = 50, 200
PERIODS = [
    ("ALL", "19700101", "20991231"),
    ("2010-2017", "20100101", "20171231"),
    ("2018-2024", "20180101", "20241231"),
    ("2025-", "20250101", "20991231"),
]


def cost(px):
    return FEE_PER_SIDE + TICKVAL * SLIP_TICKS


def load():
    df = pd.concat([pd.read_parquet(p) for p in sorted(CACHE.glob("kospi200_*.parquet"))],
                   ignore_index=True)
    df = df[df["ISU_NM"].str.contains("주간", na=False)].copy()
    for f in ["TDD_OPNPRC", "TDD_HGPRC", "TDD_LWPRC", "TDD_CLSPRC", "ACC_TRDVOL",
              "ACC_TRDVAL", "ACC_OPNINT_QTY", "SPOT_PRC"]:
        df[f] = pd.to_numeric(df[f], errors="coerce")
    df["date"] = pd.to_datetime(df["BAS_DD"], format="%Y%m%d")
    return df.sort_values("date")


def front_series(df):
    fr = df.sort_values("ACC_TRDVOL", ascending=False).groupby("date").first().sort_index()
    fr["roll"] = (fr["ISU_CD"] != fr["ISU_CD"].shift(1)).fillna(True)
    fr = fr[~fr["roll"]]
    return fr


def run_ema(b, use_oi_filter):
    """Long-only EMA50/200. use_oi_filter=True면 진입 시 OI 전일대비 증가 필요."""
    ema = b["TDD_CLSPRC"].ewm(span=MA_FAST, adjust=False).mean()
    ema_s = b["TDD_CLSPRC"].ewm(span=MA_SLOW, adjust=False).mean()
    oi = b["ACC_OPNINT_QTY"].to_numpy(dtype=float)
    o = b["TDD_OPNPRC"].to_numpy(dtype=float)
    cl = b["TDD_CLSPRC"].to_numpy(dtype=float)
    ts = b.index.to_numpy()
    n = len(b)

    trades, realized, cost_sum = [], 0.0, 0.0
    pos, entry_px = 0, np.nan
    eq_net, eq_gross = [], []

    # 진입 게이트 시그널 (전일 bar i-1 기준, 직전 OI 대비 증가 · 동일 계약 내에서만)
    ema_up = (ema > ema_s).to_numpy(bool)
    same_cd = np.zeros(n, dtype=bool)
    same_cd[1:] = b["ISU_CD"].to_numpy()[1:] == b["ISU_CD"].to_numpy()[:-1]
    oi_inc = np.zeros(n, dtype=bool)
    oi_inc[2:] = (oi[2:] > oi[1:-1]) & np.isfinite(oi[2:]) & np.isfinite(oi[1:-1]) & same_cd[2:]

    for i in range(1, n):
        # 전일(bar i-1) close에서 판단
        if pos == 0:
            want_long = bool(ema_up[i - 1])
            if use_oi_filter:
                want_long = want_long and bool(oi_inc[i - 1])
            if want_long:
                pos = 1
                entry_px = o[i]
                cost_sum += cost(o[i])
                trades.append(dict(side=1, entry_px=o[i], exit_px=None,
                                   entry_ts=ts[i], exit_ts=None, gross=None))
        else:  # pos == 1
            if not bool(ema_up[i - 1]):
                gross = pos * (o[i] - entry_px) * MULT
                realized += gross
                cost_sum += cost(o[i])
                t = trades[-1]
                t["exit_px"] = o[i]
                t["exit_ts"] = ts[i]
                t["gross"] = gross
                pos = 0
        opnl = pos * (cl[i] - entry_px) * MULT if pos != 0 else 0.0
        eq_net.append(realized - cost_sum + opnl)
        eq_gross.append(realized + opnl)

    # 종료 시 잔포지션 force close (bar close)
    if pos != 0:
        gross = pos * (cl[-1] - entry_px) * MULT
        realized += gross
        cost_sum += cost(cl[-1])
        t = trades[-1]
        t["exit_px"] = cl[-1]
        t["exit_ts"] = ts[-1]
        t["gross"] = gross
        eq_net[-1] = realized - cost_sum
        eq_gross[-1] = realized
    return trades, np.asarray(eq_net), np.asarray(eq_gross), ts


def bench(fr, cap):
    c = fr["TDD_CLSPRC"].to_numpy(dtype=float)
    entry_px, exit_px = c[0], c[-1]
    cost_sum = 2.0 * cost(0.0)
    gross = (exit_px - entry_px) * MULT
    net = gross - cost_sum
    eqn = pd.Series((c - c[0]) * MULT, index=fr.index)
    eqn.iloc[-1] = net
    return dict(trades=[dict(side=1, entry_px=entry_px, exit_px=exit_px,
                             entry_ts=fr.index[0], exit_ts=fr.index[-1], gross=gross)],
                eq_net=eqn, eq_gross=eqn)


def metrics_wrap(trades, eq_net, eq_gross, ts, cap):
    if len(eq_net) == 0:
        return None
    if len(ts) == len(eq_net) + 1:
        pos_ts = pd.DatetimeIndex(ts)[1:]
    else:
        pos_ts = pd.DatetimeIndex(ts)[:len(eq_net)]
    eqn = pd.Series(np.asarray(eq_net) + cap, index=pos_ts)
    daily_n = eqn.resample("D").last().dropna()
    if len(daily_n) < 2:
        return None
    rets = daily_n.pct_change().dropna()
    span = (daily_n.index[-1] - daily_n.index[0]).days
    years = max(span / DAYS_PER_YEAR, 1e-9)
    final = daily_n.iloc[-1]
    start_eq = daily_n.iloc[0]
    cagr = (final / start_eq) ** (1.0 / years) - 1.0 if start_eq > 0 else np.nan
    sd = rets.std(ddof=1)
    sharpe = rets.mean() / sd * math.sqrt(TRADING_DAYS) if sd and sd > 0 else np.nan
    downs = rets[rets < 0]
    dsd = downs.std(ddof=1) if len(downs) > 1 else 0.0
    sortino = rets.mean() / dsd * math.sqrt(TRADING_DAYS) if dsd and dsd > 0 else np.nan
    peak = daily_n.cummax()
    mdd = float(((daily_n - peak) / peak).min()) if len(daily_n) > 1 else 0.0
    calmar = cagr / abs(mdd) if mdd and mdd < 0 else np.nan
    gw = sum(t["gross"] for t in trades if t["gross"] is not None and t["gross"] > 0)
    gl = sum(t["gross"] for t in trades if t["gross"] is not None and t["gross"] <= 0)
    pf = gw / abs(gl) if abs(gl) > 1e-9 else (np.inf if gw > 0 else np.nan)
    wins = [t for t in trades if t["gross"] is not None and t["gross"] > 0]
    losses = [t for t in trades if t["gross"] is not None and t["gross"] <= 0]
    avg_win = gw / len(wins) if wins else np.nan
    avg_loss = gl / len(losses) if losses else np.nan
    tot_cost = sum(cost(t["entry_px"]) for t in trades) + sum(
        cost(t["exit_px"]) for t in trades if t["exit_px"] is not None)
    n_close = len([t for t in trades if t["gross"] is not None])
    wr = len(wins) / n_close if n_close else np.nan
    return dict(
        years=round(years, 4), bars=len(daily_n),
        capital_krw=round(float(cap), 0),
        trade_count=n_close, trades_per_year=round(n_close / years, 2),
        cagr_net=round(float(cagr), 4), sharpe_net=round(float(sharpe), 3),
        sortino_net=round(float(sortino), 3), calmar_net=round(float(calmar), 3),
        mdd_net=round(float(mdd), 4), win_rate=round(wr, 4) if wr == wr else None,
        profit_factor=round(float(pf), 3) if pf == pf else None,
        avg_win_krw=round(float(avg_win), 0) if avg_win == avg_win else None,
        avg_loss_krw=round(float(avg_loss), 0) if avg_loss == avg_loss else None,
        total_cost_krw=round(float(tot_cost), 0),
        total_cost_pct_cap=round(float(tot_cost / cap), 5),
        final_equity_net_krw=round(float(final), 0),
    )


def main():
    df = load()
    fr = front_series(df)
    print("연속선물 bars:", len(fr), " 시작:", fr.index[0], " 종료:", fr.index[-1])
    rows = []
    detail = {}
    strategies = [("A_ema", False, "A: EMA50/200"), ("B_ema_oi", True, "B: EMA50/200+OI")]

    for pname, ps, pe in PERIODS:
        sub = fr[(fr.index >= ps) & (fr.index <= pe)]
        if len(sub) < 220:
            continue
        cap = float(sub["TDD_CLSPRC"].max()) * MULT
        for key, use_oi, label in strategies:
            trades, eqn, eqg, ts = run_ema(sub, use_oi)
            m = metrics_wrap(trades, eqn, eqg, sub.index, cap)
            m |= dict(strategy=key, params=label, period=pname, status="OK")
            rows.append(m)
            detail.setdefault(key, {})[pname] = m
        b = bench(sub, cap)
        m = metrics_wrap(b["trades"], b["eq_net"].to_numpy(), b["eq_gross"].to_numpy(),
                         sub.index, cap)
        m |= dict(strategy="buyhold", params="long_1contract", period=pname, status="OK")
        rows.append(m)
        detail.setdefault("BUYHOLD", {})[pname] = m

    out = pd.DataFrame(rows)
    cols = ["strategy", "params", "period", "years", "bars", "capital_krw", "trade_count",
            "trades_per_year", "cagr_net", "sharpe_net", "sortino_net", "calmar_net",
            "mdd_net", "win_rate", "profit_factor", "avg_win_krw", "avg_loss_krw",
            "total_cost_krw", "total_cost_pct_cap", "final_equity_net_krw"]
    out = out[[c for c in cols if c in out.columns]]
    out.to_csv(OUTDIR / "futures-stage4-1-oi-filter.csv", index=False, encoding="utf-8-sig")
    import json
    (OUTDIR / "futures-stage4-1-oi-filter.json").write_text(
        json.dumps(detail, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    for _, r in out.iterrows():
        print(f"{r['strategy']:10s} {str(r['params']):22s} {r['period']:9s} "
              f"n={r['trade_count']:3d} tpy={r['trades_per_year']:4.2f} "
              f"CAGR={r['cagr_net']} Sharpe={r['sharpe_net']} MDD={r['mdd_net']} "
              f"WR={r['win_rate']} PF={r['profit_factor']} cost={r['total_cost_krw']}")


if __name__ == "__main__":
    main()