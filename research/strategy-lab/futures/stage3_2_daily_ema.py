# -*- coding: utf-8 -*-
"""Stage 3-2: KOSPI200 선물 일봉 EMA 장기 검증 백테스트.

- 원천: research/strategy-lab/.cache/kospi200_daily/ (KRX drv/fut_bydd_trd, 주간만)
- 연속선물: 일별 최대거래량(ACC_TRDVOL) 계약을 front로, 롤(전일 대비 계약 변경) 봉은 제거
  (Stage 1 build_series의 contract_changed 제거 관례 동일)
- 전략: EMA50/200, EMA20/100  LONG-ONLY (지시서: 롱만, 파라미터 최적화 없음)
- 실행: signal은 bar close, 체결은 다음 bar open. 비용 편도 500원 + 1틱(12,500원).
- 자본 = 기간 내 close.max()*멀티플라이어 (leverage <= 1x). 멀티플라이어 250,000원/pt.
- 성과: CAGR/Sharpe/Sortino/Calmar/MDD/WinRate/PF/AvgWin/AvgLoss/TotalCost/Trades/연
- 비교: Buy & Hold (1계약 종일 롤 갭 무시 근사, Stage 1 bench 동일)
- 기간: 2010-2017 / 2018-2024 / 2025~현재 / 전체
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

MA_COMBOS = [("EMA", 20, 100), ("EMA", 50, 200)]
PERIODS = [
    ("2010-2017", "20100101", "20171231"),
    ("2018-2024", "20180101", "20241231"),
    ("2025-", "20250101", "20991231"),
    ("ALL", "19700101", "20991231"),
]


def cost(px):
    return FEE_PER_SIDE + TICKVAL * SLIP_TICKS


def load():
    df = pd.concat([pd.read_parquet(p) for p in sorted(CACHE.glob("kospi200_*.parquet"))],
                   ignore_index=True)
    df = df[df["ISU_NM"].str.contains("주간", na=False)].copy()
    for f in ["TDD_OPNPRC", "TDD_HGPRC", "TDD_LWPRC", "TDD_CLSPRC", "ACC_TRDVOL",
              "ACC_TRDVAL", "ACC_OPNINT_QTY"]:
        df[f] = pd.to_numeric(df[f], errors="coerce")
    df["date"] = pd.to_datetime(df["BAS_DD"], format="%Y%m%d")
    return df.sort_values(["date", "ACC_TRDVOL"], ascending=[True, False])


def front_series(df):
    # front = 날짜별 최대 ACC_TRDVOL 계약
    fr = df.sort_values("ACC_TRDVOL", ascending=False).groupby("date").first()
    fr = fr.sort_index()
    fr["roll"] = (fr["ISU_CD"] != fr["ISU_CD"].shift(1)).fillna(True)
    # Stage 1 관례: 롤 봉 제거
    fr = fr[~fr["roll"]]
    return fr[["TDD_OPNPRC", "TDD_HGPRC", "TDD_LWPRC", "TDD_CLSPRC", "ACC_TRDVOL",
               "ACC_OPNINT_QTY", "ISU_CD", "ISU_NM"]]


def run_ema_long_only(b, fast, slow):
    c = b["TDD_CLSPRC"].ewm(span=fast, adjust=False).mean()
    s = b["TDD_CLSPRC"].ewm(span=slow, adjust=False).mean()
    tgt = np.where((c > s).to_numpy(), 1.0, 0.0)
    final_row = len(b) - 1
    o = b["TDD_OPNPRC"].to_numpy(dtype=float)
    cl = b["TDD_CLSPRC"].to_numpy(dtype=float)
    ts = b.index.to_numpy()
    trades, realized, cost_sum = [], 0.0, 0.0
    pos, entry_px = 0, np.nan
    eq_net, eq_gross = [], []
    for i in range(1, len(b)):
        want = tgt[i - 1]
        if want != pos:
            if pos != 0:
                gross = pos * (o[i] - entry_px) * MULT
                realized += gross
                cost_sum += cost(o[i])
                trades.append(dict(side=pos, entry_px=entry_px, exit_px=o[i],
                                   entry_ts=ts[i - 1], exit_ts=ts[i], gross=gross))
                pos = 0
            if want != 0:
                pos = 1
                entry_px = o[i]
                cost_sum += cost(o[i])
        opnl = pos * (cl[i] - entry_px) * MULT if pos != 0 else 0.0
        eq_net.append(realized - cost_sum + opnl)
        eq_gross.append(realized + opnl)
    if pos != 0:
        gross = pos * (cl[final_row] - entry_px) * MULT
        realized += gross
        cost_sum += cost(cl[final_row])
        trades.append(dict(side=pos, entry_px=entry_px, exit_px=cl[final_row],
                           entry_ts=ts[final_row - 1], exit_ts=ts[final_row], gross=gross))
        eq_net[-1] = realized - cost_sum
        eq_gross[-1] = realized
    return trades, np.asarray(eq_net), np.asarray(eq_gross), ts


def bench(fr, cap):
    c = fr["TDD_CLSPRC"].to_numpy(dtype=float)
    entry_px, exit_px = c[0], c[-1]
    cost_sum = 2.0 * cost(0.0)
    gross = (exit_px - entry_px) * MULT
    net = gross - cost_sum
    # Stage 1 관례: 자본 cap(기간 내 최대 명목) 기준, equity = cap + 1계약 PnL
    # (metrics_wrap에서 cap을 다시 더하므로 여기서는 순PnL만 반환)
    eqn = pd.Series((c - c[0]) * MULT, index=fr.index)
    eqn.iloc[-1] = net
    eqg = pd.Series((c - c[0]) * MULT, index=fr.index)
    return dict(trades=[dict(side=1, entry_px=entry_px, exit_px=exit_px,
                             entry_ts=fr.index[0], exit_ts=fr.index[-1], gross=gross)],
                net=net, gross=gross, cost=cost_sum,
                eq_net=eqn, eq_gross=eqg)


def metrics_wrap(trades, eq_net, eq_gross, ts, cap, period_slice=None, gmean=None):
    if len(ts) == len(eq_net) + 1:
        pos_ts = pd.DatetimeIndex(ts)[1:]
    else:
        pos_ts = pd.DatetimeIndex(ts)[:len(eq_net)]
    eqn = pd.Series(np.asarray(eq_net) + cap, index=pos_ts)
    eqg = pd.Series(np.asarray(eq_gross) + cap, index=pos_ts)
    daily_n = eqn.resample("D").last().dropna()
    daily_g = eqg.resample("D").last().dropna()
    if period_slice is not None:
        start, end = period_slice
        daily_n = daily_n[(daily_n.index >= start) & (daily_n.index <= end)]
        daily_g = daily_g[(daily_g.index >= start) & (daily_g.index <= end)]
        trades = [t for t in trades if start <= t["exit_ts"] <= end]
    eq = daily_n
    if gmean is not None:
        eq = pd.concat([pd.Series([gmean], index=[eq.index[0] - pd.Timedelta(days=1)]), eq]).cumprod() * cap
        eq = eq[eq.index >= eq.index.min() + pd.Timedelta(days=1)]
    rets = daily_n.pct_change().dropna()
    if len(daily_n) < 2:
        return None
    retsg = daily_g.pct_change().dropna()
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
    wins = [t for t in trades if t["gross"] > 0]
    losses = [t for t in trades if t["gross"] <= 0]
    gw = sum(t["gross"] for t in wins)
    gl = sum(t["gross"] for t in losses)
    pf = gw / abs(gl) if abs(gl) > 1e-9 else (np.inf if gw > 0 else np.nan)
    avg_win = gw / len(wins) if wins else np.nan
    avg_loss = gl / len(losses) if losses else np.nan
    tot_cost = sum(cost(t["entry_px"]) for t in trades) + sum(cost(t["exit_px"]) for t in trades)
    expect = (gw + gl - tot_cost) / len(trades) if trades else np.nan
    return dict(
        years=round(years, 4), bars=len(daily_n),
        capital_krw=round(float(cap), 0),
        trade_count=len(trades), trades_per_year=round(len(trades) / years, 2),
        cagr_net=round(float(cagr), 4), sharpe_net=round(float(sharpe), 3),
        sortino_net=round(float(sortino), 3), calmar_net=round(float(calmar), 3),
        mdd_net=round(float(mdd), 4), win_rate=round(len(wins) / len(trades), 4) if trades else None,
        profit_factor=round(float(pf), 3) if pf == pf else None,
        avg_win_krw=round(float(avg_win), 0) if avg_win == avg_win else None,
        avg_loss_krw=round(float(avg_loss), 0) if avg_loss == avg_loss else None,
        total_cost_krw=round(float(tot_cost), 0),
        total_cost_pct_cap=round(float(tot_cost / cap), 5),
        expectancy_krw=round(float(expect), 0) if expect == expect else None,
        final_equity_net_krw=round(float(final), 0),
    )


def main():
    df = load()
    fr = front_series(df)
    print("연속선물 bars:", len(fr), "시작:", fr.index[0], "종료:", fr.index[-1])
    rows = []
    detail = {}

    # 기간별: 자본 = 해당 기간 내 close.max()*멀티 (Stage-1 관례, leverage<=1x)
    periods = [("ALL", "19700101", "20991231")] + [p for p in PERIODS if p[0] != "ALL"]
    for pname, ps, pe in periods:
        sub = fr[(fr.index >= ps) & (fr.index <= pe)]
        if len(sub) < 220:
            continue
        cap = float(sub["TDD_CLSPRC"].max()) * MULT
        for mt, fast, slow in MA_COMBOS:
            trades, eqn, eqg, ts = run_ema_long_only(sub, fast, slow)
            m = metrics_wrap(trades, eqn, eqg, ts, cap)
            m |= dict(strategy="ema_trend", params=f"EMA{fast}_{slow}", period=pname, status="OK")
            rows.append(m)
            detail.setdefault(f"EMA{fast}_{slow}", {})[pname] = m
        b = bench(sub, cap)
        m = metrics_wrap(b["trades"], b["eq_net"].to_numpy(), b["eq_gross"].to_numpy(),
                         b["eq_net"].index.to_numpy(), cap)
        m |= dict(strategy="buyhold", params="long_1contract", period=pname, status="OK")
        rows.append(m)
        detail.setdefault("BUYHOLD", {})[pname] = m
        # 가격기준 B&H (보고서용 참고치)
        cc = sub["TDD_CLSPRC"]
        cum = cc.iloc[-1] / cc.iloc[0] - 1.0
        yrs = (sub.index[-1] - sub.index[0]).days / DAYS_PER_YEAR
        detail["BUYHOLD"][pname]["price_cagr"] = round((1.0 + cum) ** (1.0 / yrs) - 1.0, 4)
        detail["BUYHOLD"][pname]["price_total_ret"] = round(cum, 4)
        detail["BUYHOLD"][pname]["price_mdd"] = round(
            float(((cc - cc.cummax()) / cc.cummax()).min()), 4)

    out = pd.DataFrame(rows)
    cols = ["strategy", "params", "period", "years", "bars", "capital_krw", "trade_count",
            "trades_per_year", "cagr_net", "sharpe_net", "sortino_net", "calmar_net",
            "mdd_net", "win_rate", "profit_factor", "avg_win_krw", "avg_loss_krw",
            "total_cost_krw", "total_cost_pct_cap", "expectancy_krw", "final_equity_net_krw"]
    out = out[[c for c in cols if c in out.columns]]
    out.to_csv(OUTDIR / "futures-stage3-2-daily-ema.csv", index=False, encoding="utf-8-sig")
    (OUTDIR / "futures-stage3-2-daily-ema.json").write_text(
        json_dumps(detail), encoding="utf-8")
    for _, r in out.iterrows():
        print(r["strategy"].ljust(9), str(r["params"]).ljust(10), r["period"].ljust(7),
              "n=%d" % r["trade_count"], "tpy=%s" % r["trades_per_year"],
              "CAGR=%s" % r["cagr_net"], "Sharpe=%s" % r["sharpe_net"],
              "MDD=%s" % r["mdd_net"], "WR=%s" % r["win_rate"], "PF=%s" % r["profit_factor"],
              "cost=%s" % r["total_cost_krw"])


import json


def json_dumps(d):
    return json.dumps(d, ensure_ascii=False, indent=2, default=str)


if __name__ == "__main__":
    main()