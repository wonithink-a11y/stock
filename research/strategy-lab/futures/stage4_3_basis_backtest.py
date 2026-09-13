# -*- coding: utf-8 -*-
"""Stage 4-3: KOSPI200 선물 basis 단순 신호 백테스트 (Long-only).

- 데이터: Stage 3-2/4-2 동일(연속선물 front 주간, 롤오버봉 제거 후 4,041 bar, 새 수집 금지)
- 신호: bar close에서 basis(=front close - SPOT_PRC)를 과거 정보만으로 계산한
  expanding percentile과 비교. A: <=20%, B: <=30%, C: <=40% 분위수 (사전 지정, 최적화 없음)
- 체결: 신호 bar close -> 다음 bar open (look-ahead 금지)
- 청산: 진입 후 5 or 20 거래일 후 open. stop/target 없음.
- 대기: 포지션 없으면 현금, leverage<=1x
- 비용: 편도 500원 + 1틱(12,500원) = 편도 13,000원, 왕복 26,000원
- 자본: 기간 내 max close x 250,000 (Stage 3-2 관례)
- 기간: 2010-2017 / 2018-2024 / 2025~ / 전체
- 판정: A/C/B 비교 + B&H + event-study(Stage 4-2) 방향 대조
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
WARMUP = 252

THRESHOLDS = {"A": 0.20, "B": 0.30, "C": 0.40}
HOLDS = [5, 20]
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
    for f in ["TDD_OPNPRC", "TDD_CLSPRC", "SPOT_PRC", "ACC_TRDVOL"]:
        df[f] = pd.to_numeric(df[f], errors="coerce")
    df["date"] = pd.to_datetime(df["BAS_DD"], format="%Y%m%d")
    df = df.sort_values("date")
    fr = df.sort_values("ACC_TRDVOL", ascending=False).groupby("date").first().sort_index()
    fr["roll"] = (fr["ISU_CD"] != fr["ISU_CD"].shift(1)).fillna(True)
    fr = fr[~fr["roll"]]
    return fr


def build_signals(basis, p):
    n = len(basis)
    sig = np.zeros(n, dtype=bool)
    hist = []
    for i in range(n):
        if len(hist) >= WARMUP:
            q = np.quantile(hist, p)
            sig[i] = basis[i] <= q
        hist.append(basis[i])
    return sig


def run_strategy(sub, sig_global, hold):
    """sub: 기간 window (전체 series의 위치를 갖는 행), sig_global: 전역 과거분위수 신호."""
    o = sub["TDD_OPNPRC"].to_numpy(dtype=float)
    c = sub["TDD_CLSPRC"].to_numpy(dtype=float)
    # 전역 신호를 window 위치로 매핑 (데이터가 sub일 뿐 인덱스 전역)
    sig = sig_global.loc[sub.index].to_numpy(bool)
    n = len(sub)
    ts = sub.index.to_numpy()

    trades, realized, cost_sum = [], 0.0, 0.0
    pos, entry_px = 0, np.nan
    planned_exit = -1
    eq_net, eq_gross, pos_mask = [], [], []

    for i in range(n):
        # 청산 우선: 진입 bar i에서 open 체결이라 i==planned_exit -> 청산
        if pos == 1 and i == planned_exit:
            gross = pos * (o[i] - entry_px) * MULT
            realized += gross
            cost_sum += cost(o[i])
            t = trades[-1]
            t["exit_px"] = o[i]
            t["exit_ts"] = ts[i]
            t["gross"] = gross
            pos = 0
        if pos == 0:
            # 신호는 전 bar close 기준 -> bar i open 체결
            if i > 0 and sig[i - 1]:
                pos = 1
                entry_px = o[i]
                planned_exit = i + hold
                cost_sum += cost(o[i])
                trades.append(dict(side=1, entry_px=o[i], exit_px=None,
                                   entry_ts=ts[i], exit_ts=None, gross=None))
        opnl = pos * (c[i] - entry_px) * MULT if pos else 0.0
        eq_net.append(realized - cost_sum + opnl)
        eq_gross.append(realized + opnl)
        pos_mask.append(pos == 1)

    if pos == 1:  # 강제 청산 (window 끝)
        gross = pos * (c[-1] - entry_px) * MULT
        realized += gross
        cost_sum += cost(c[-1])
        t = trades[-1]
        t["exit_px"] = c[-1]
        t["exit_ts"] = ts[-1]
        t["gross"] = gross
        eq_net[-1] = realized - cost_sum
        eq_gross[-1] = realized

    exposure = float(np.mean(pos_mask)) if n else 0.0
    return trades, np.asarray(eq_net), np.asarray(eq_gross), ts, exposure


def bench(sub, cap):
    c = sub["TDD_CLSPRC"].to_numpy(dtype=float)
    gross = (c[-1] - c[0]) * MULT
    net = gross - 2.0 * cost(0.0)
    eq = pd.Series((c - c[0]) * MULT, index=sub.index)
    eq.iloc[-1] = net
    return dict(trades=[dict(side=1, entry_px=c[0], exit_px=c[-1],
                             entry_ts=sub.index[0], exit_ts=sub.index[-1], gross=gross)],
                eq_net=eq, exposure=1.0)


def metrics_wrap(trades, eq_net, ts, cap, exposure):
    if len(eq_net) == 0:
        return None
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
    closed = [t for t in trades if t["gross"] is not None]
    tot_cost = sum(cost(t["entry_px"]) for t in closed) + sum(
        cost(t["exit_px"]) for t in closed)
    n_close = len(closed)
    wr = len(wins) / n_close if n_close else np.nan
    expectancy = (sum(t["gross"] for t in closed) - tot_cost) / n_close if n_close else np.nan
    return dict(
        years=round(years, 4), bars=len(daily_n),
        capital_krw=round(float(cap), 0), exposure=round(float(exposure), 4),
        trade_count=n_close, trades_per_year=round(n_close / years, 2),
        cagr_net=round(float(cagr), 4), sharpe_net=round(float(sharpe), 3),
        sortino_net=round(float(sortino), 3), calmar_net=round(float(calmar), 3),
        mdd_net=round(float(mdd), 4), win_rate=round(wr, 4) if wr == wr else None,
        profit_factor=round(float(pf), 3) if pf == pf else None,
        avg_win_krw=round(float(avg_win), 0) if avg_win == avg_win else None,
        avg_loss_krw=round(float(avg_loss), 0) if avg_loss == avg_loss else None,
        expectancy_krw=round(float(expectancy), 0) if expectancy == expectancy else None,
        total_cost_krw=round(float(tot_cost), 0),
        total_cost_pct_cap=round(float(tot_cost / cap), 5),
        final_equity_net_krw=round(float(final), 0),
    )


def main():
    fr = load()
    basis = (fr["TDD_CLSPRC"] - fr["SPOT_PRC"])
    print("bars:", len(fr), fr.index[0].date(), "~", fr.index[-1].date())
    sig = {k: pd.Series(build_signals(basis.to_numpy(), p), index=fr.index)
           for k, p in THRESHOLDS.items()}
    rows = []
    for sname, p in THRESHOLDS.items():
        nsig = int(sig[sname].sum())
        # event-study 대조용: 신호 날짜의 평균 이후 수익률(whole series)
        o = fr["TDD_OPNPRC"].to_numpy(dtype=float)
        c = fr["TDD_CLSPRC"].to_numpy(dtype=float)
        fwd = {}
        for h in HOLDS:
            r = np.full(len(fr), np.nan)
            for i in range(len(fr) - h):
                r[i] = c[i + h] / c[i] - 1.0
            fwd[h] = r
        es = {}
        for h in HOLDS:
            m = np.nanmean(fwd[h][sig[sname].to_numpy()])
            es[h] = float(m) if m == m else None
        print(f"[{sname}] p={p} 신호수={nsig} event-study 평균수익률(close기준) 5d={es[5]} 20d={es[20]}")

    for sname, p in THRESHOLDS.items():
        for hold in HOLDS:
            for pname, ps, pe in PERIODS:
                sub = fr[(fr.index >= ps) & (fr.index <= pe)]
                if len(sub) < hold + 2:
                    continue
                cap = float(sub["TDD_CLSPRC"].max()) * MULT
                trades, eqn, eqg, ts, exposure = run_strategy(sub, sig[sname], hold)
                m = metrics_wrap(trades, eqn, ts, cap, exposure)
                m |= dict(strategy="basis", threshold=sname, hold_days=hold,
                          period=pname, signal_pct=p, status="OK")
                rows.append(m)
            if sname == "A" and hold == 20:
                pass

    for pname, ps, pe in PERIODS:
        sub = fr[(fr.index >= ps) & (fr.index <= pe)]
        if len(sub) < 2:
            continue
        cap = float(sub["TDD_CLSPRC"].max()) * MULT
        b = bench(sub, cap)
        m = metrics_wrap(b["trades"], b["eq_net"].to_numpy(), sub.index, cap, 1.0)
        m |= dict(strategy="buyhold", threshold="-", hold_days="full", period=pname,
                  signal_pct=None, status="OK")
        rows.append(m)

    out = pd.DataFrame(rows)
    cols = ["strategy", "threshold", "hold_days", "signal_pct", "period", "years", "bars",
            "capital_krw", "exposure", "trade_count", "trades_per_year", "cagr_net",
            "sharpe_net", "sortino_net", "calmar_net", "mdd_net", "win_rate",
            "profit_factor", "avg_win_krw", "avg_loss_krw", "expectancy_krw",
            "total_cost_krw", "total_cost_pct_cap", "final_equity_net_krw"]
    out = out[[c for c in cols if c in out.columns]].sort_values(
        ["strategy", "threshold", "hold_days", "period"])
    out.to_csv(OUTDIR / "futures-stage4-3-basis-backtest.csv", index=False,
               encoding="utf-8-sig")
    import json
    detail = out.to_dict(orient="records")
    (OUTDIR / "futures-stage4-3-basis-backtest.json").write_text(
        json.dumps(detail, ensure_ascii=False, indent=2), encoding="utf-8")

    pd.set_option("display.width", 250)
    for _, r in out.sort_values("period").iterrows():
        print(f"{r['strategy']:8s} {str(r['threshold']):2s} h={str(r['hold_days']):4s} "
              f"{r['period']:9s} exp={r['exposure']:.2f} n={r['trade_count']:3d} "
              f"CAGR={r['cagr_net']:7.4f} Sh={r['sharpe_net']:5.3f} MDD={r['mdd_net']:7.4f} "
              f"WR={r['win_rate']} PF={r['profit_factor']} Exp={r['expectancy_krw']} "
              f"cost={r['total_cost_krw']}")


if __name__ == "__main__":
    main()