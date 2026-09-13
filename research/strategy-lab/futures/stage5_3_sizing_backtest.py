# -*- coding: utf-8 -*-
"""Stage 5-3: KOSPI200 선물 일봉 0~1x sizing 백테스트 (READ-ONLY 이지만 연구 산출물).

- 목적: Stage 5-1/5-2 "RV20 고변동성 → 미래 위험 증가" 관계를 실제 0~1x 포지션
  sizing으로 전환할 가치가 있는지 1차 검증.
- 원천: Stage 5-1/5-2와 동일(KRX drv/fut_bydd_trd 일봉 주간, 새 수집 금지).
- 신호: Stage 5-1 확정 rolling252 RV20 percentile(pct_rv20_rol) 그대로. threshold 최적화 없음.
- 기준: B&H(Long-only 1.0x 항상, 방향필터 없음, 신호 당일 close 계산, 다음거래일 open부터 적용, look-ahead 금지).
- 사전 지정 sizing만:
  A Binary      : Q5(>=0.8) → 0.5x, 그 외 1.0x
  B Binary def. : Q5(>=0.8) → 0.0x, 그 외 1.0x
  C 3단계       : Q1~Q3(<0.6) → 1.0x, Q4(0.6~0.8) → 0.75x, Q5(>=0.8) → 0.5x
- 비용: Stage 3-2 동일 (편도 500원 + 1 tick slippage). sizing 변경 시에만 발생.
  (크기 변경 |Δw|에 비례한 편도 비용: |Δw| * (500 + 12,500). 진입·청산도 1x당 1편도.)
- 메트릭: CAGR/Sharpe/MDD/Sortino/Calmar/WinRate/ProfitFactor/ResizeCount/TradesPerYear/
  TotalCost/AverageExposure/TimeInMarket. B&H와 반드시 비교. 기간 4분리.
- §8 robustness: RV20 Q1/Q5 event 기준 이후수익(동일계약) +5/+10/+15/+20d 방향 유지 확인
  + 이후 5일 실현변동성(Q1/Q5) 유지 확인.
- §10 분해: B&H 對 sizing의 수익/변동성/MDD/비용/exposure 차이 분리.
- 금지(미실행): 배율 최적화·Q2~Q4 threshold 탐색·EMA/basis/OI 결합·Short·leverage 확대·
  WFA/OOS·타선물·새 데이터·production·commit.
"""
from pathlib import Path

import numpy as np
import pandas as pd
from scipy import stats as st

from stage5_1_volatility_event_study import load, front_series, process, same_contract_ret, PERIODS
from stage5_2_volatility_risk_study import bootstrap_ci

REPO = Path(r"C:\Users\User\projects\stock")
OUTDIR = REPO / "research" / "strategy-lab" / "futures"

MULT = 250_000.0
TICKVAL = 12_500.0
FEE_PER_SIDE = 500.0
SLIP_TICKS = 1.0
DAYS_PER_YEAR = 365.25
TRADING_DAYS = 252.0
COST_SIDE = FEE_PER_SIDE + TICKVAL * SLIP_TICKS  # 13,000 KRW per 1x side

Q1_CUT, Q5_CUT = 0.2, 0.8
RULES = {"A": "binary", "B": "defensive", "C": "3step"}
HORIZONS_ROBUST = [5, 10, 15, 20]


def target_weight(p, rule):
    """p: rolling252 RV20 percentile (NaN=warmup → 1.0x, sizing 없음)."""
    if p != p:                       # 홍평기 NaN
        return 1.0
    if rule == "binary":
        return 0.5 if p >= Q5_CUT else 1.0
    if rule == "defensive":
        return 0.0 if p >= Q5_CUT else 1.0
    if rule == "3step":
        if p < 0.6:
            return 1.0
        return 0.75 if p < Q5_CUT else 0.5
    raise ValueError(rule)


def run_sizing(cts, pct, rule):
    """cts: roll 제거 연속계약 window. pct: 같은 window의 pct_rv20_rol.

    신호는 일자 t close 기준 → w_{t+1} open부터. 하루 PnL 분해:
      overnight  = w_{t-1} * (open_t − close_{t-1})   (close t-1에서 결정된 그대로)
      intraday   = w_t      * (close_t − open_t)      (open t에서 w_t 적용)
    크기 변경(Δw≠0) 시 편도 비용 |Δw|*COST_SIDE, 진입 1x(편도) + 청산 w_last(편도).
    """
    o = cts["TDD_OPNPRC"].to_numpy(dtype=float)
    c = cts["TDD_CLSPRC"].to_numpy(dtype=float)
    idx = cts.index
    pv = pct.reindex(idx).to_numpy(dtype=float)
    n = len(cts)
    if n < 2:
        return None

    # w[t]: bar t(open t ~ close t)에 적용할 weight. w[0]=1.0(진입 1x).
    w = np.full(n, np.nan)
    w[0] = 1.0
    for t in range(1, n):
        w[t] = target_weight(pv[t - 1], rule)

    cap = float(cts["TDD_CLSPRC"].max()) * MULT
    nav = np.empty(n)
    nav[0] = cap
    cost = COST_SIDE                     # 진입(1x) 편도
    nav[0] -= cost
    resizes = 0
    for t in range(1, n):
        pnl = w[t - 1] * (o[t] - c[t - 1]) + w[t] * (c[t] - o[t])
        pnl *= MULT
        c_up = abs(w[t] - w[t - 1]) * COST_SIDE
        if w[t] != w[t - 1]:
            resizes += 1
        nav[t] = nav[t - 1] + pnl - c_up
        cost += c_up
    cost += w[-1] * COST_SIDE            # 청산 w_last 편도
    nav[-1] -= w[-1] * COST_SIDE
    return dict(nav=nav, w=w, idx=idx, cap=cap, cost=cost, resizes=resizes)


def run_buyhold(cts):
    """B&H: 항상 1x. 진입 1편도 + 청산 1편도 (Stage 3-2 bench 동일)."""
    o = cts["TDD_OPNPRC"].to_numpy(dtype=float)
    c = cts["TDD_CLSPRC"].to_numpy(dtype=float)
    idx = cts.index
    n = len(cts)
    cap = float(cts["TDD_CLSPRC"].max()) * MULT
    nav = np.empty(n)
    nav[0] = cap - COST_SIDE
    for t in range(1, n):
        pnl = (o[t] - c[t - 1]) + (c[t] - o[t])    # = c[t]-c[t-1]
        nav[t] = nav[t - 1] + pnl * MULT
    nav[-1] -= COST_SIDE
    w = np.ones(n)
    return dict(nav=nav, w=w, idx=idx, cap=cap, cost=2 * COST_SIDE, resizes=0)


def metrics(res):
    nav = pd.Series(res["nav"], index=res["idx"])
    daily_n = nav.resample("D").last().dropna()
    if len(daily_n) < 2:
        return None
    rets = daily_n.pct_change().dropna()
    span = (daily_n.index[-1] - daily_n.index[0]).days
    years = max(span / DAYS_PER_YEAR, 1e-9)
    cagr = (daily_n.iloc[-1] / daily_n.iloc[0]) ** (1.0 / years) - 1.0
    sd = rets.std(ddof=1)
    sharpe = rets.mean() / sd * np.sqrt(TRADING_DAYS) if sd and sd > 0 else np.nan
    downs = rets[rets < 0]
    dsd = downs.std(ddof=1) if len(downs) > 1 else 0.0
    sortino = rets.mean() / dsd * np.sqrt(TRADING_DAYS) if dsd and dsd > 0 else np.nan
    peak = daily_n.cummax()
    mdd = float(((daily_n - peak) / peak).min())
    calmar = cagr / abs(mdd) if mdd and mdd < 0 else np.nan

    # segment(weight 변경 사이 블록) 단위 trade 통계
    w = np.asarray(res["w"])
    idx = res["idx"]
    bounds = [0] + [i for i in range(1, len(w)) if w[i] != w[i - 1]] + [len(w)]
    seg_gross, seg_costs = [], []
    for a, b in zip(bounds[:-1], bounds[1:]):
        gain = res["nav"][b - 1] - (res["nav"][a] if a > 0 else res["nav"][0] + 0)
        # 블록 PnL(비용 제외) = NAVdelta + 그 블록에서 낸 비용
        seg_gross.append(gain)
    gw = sum(g for g in seg_gross if g > 0)
    gl = sum(g for g in seg_gross if g <= 0)
    pf = gw / abs(gl) if abs(gl) > 1e-9 else (np.inf if gw > 0 else np.nan)
    wins = sum(1 for g in seg_gross if g > 0)
    wr = wins / len(seg_gross) if seg_gross else np.nan
    n_seg = len(seg_gross)

    return dict(
        years=round(years, 4), bars=len(daily_n),
        capital_krw=round(res["cap"], 0),
        cagr_net=round(float(cagr), 4), sharpe_net=round(float(sharpe), 3),
        sortino_net=round(float(sortino), 3), calmar_net=round(float(calmar), 3),
        mdd_net=round(float(mdd), 4), win_rate=round(wr, 4),
        profit_factor=round(float(pf), 3),
        resize_count=int(res["resizes"]),
        n_segments=int(n_seg),
        trades_per_year=round((n_seg - 1) / years, 2) if n_seg > 1 else 0.0,
        total_cost_krw=round(res["cost"], 0),
        total_cost_pct_cap=round(res["cost"] / res["cap"], 6),
        avg_exposure=round(float(np.nanmean(w)), 4),
        time_in_market=round(float(np.nanmean(w > 0)), 4),
        final_equity_krw=round(res["nav"][-1], 0),
    )


def decompose(bt, bh):
    """B&H 對 bt의 분해(§10): 수익/변동성/MDD/비용/exposure 차이."""
    daily_a = pd.Series(bt["nav"], index=bt["idx"]).resample("D").last().dropna().pct_change().dropna()
    daily_b = pd.Series(bh["nav"], index=bh["idx"]).resample("D").last().dropna().pct_change().dropna()
    span = (daily_a.index[-1] - daily_a.index[0]).days
    years = max(span / DAYS_PER_YEAR, 1e-9)
    cagr_a = (np.asarray(bt["nav"])[-1] / np.asarray(bt["nav"])[0]) ** (1.0 / years) - 1.0
    cagr_b = (np.asarray(bh["nav"])[-1] / np.asarray(bh["nav"])[0]) ** (1.0 / years) - 1.0
    vol_a = daily_a.std(ddof=1) * np.sqrt(TRADING_DAYS)
    vol_b = daily_b.std(ddof=1) * np.sqrt(TRADING_DAYS)
    mdd_a = float(((pd.Series(bt["nav"], index=bt["idx"]) / pd.Series(bt["nav"], index=bt["idx"]).cummax()) - 1).min())
    mdd_b = float(((pd.Series(bh["nav"], index=bh["idx"]) / pd.Series(bh["nav"], index=bh["idx"]).cummax()) - 1).min())
    return dict(
        d_cagr=round(float(cagr_a - cagr_b), 4),
        d_vol_ann=round(float(vol_a - vol_b), 4),
        d_mdd=round(float(mdd_a - mdd_b), 4),
        d_cost=round(bt["cost"] - bh["cost"], 0),
        d_exposure=round(float(np.nanmean(bt["w"]) - 1.0), 4),
        d_sharpe=round(float(metrics(bt)["sharpe_net"] - metrics(bh)["sharpe_net"]), 3),
        d_sortino=round(float(metrics(bt)["sortino_net"] - metrics(bh)["sortino_net"]), 3),
    )


def fwd_rv5(fr):
    """동일계약 이후 5일 실현변동성(연율) — Q1/Q5 위험 유지 검증(§9)."""
    n = len(fr)
    cd = fr["ISU_CD"].to_numpy()
    cl = fr["TDD_CLSPRC"].to_numpy(dtype=float)
    logr = np.full(n, np.nan)
    for i in range(1, n):
        if cd[i] == cd[i - 1] and np.isfinite(cl[i]) and np.isfinite(cl[i - 1]) and cl[i - 1] > 0:
            logr[i] = np.log(cl[i] / cl[i - 1])
    out = np.full(n, np.nan)
    for t in range(n):
        t5 = t + 5
        if t5 >= n or cd[t] != cd[t5]:
            continue
        w = logr[t + 1:t5 + 1]
        if np.all(np.isfinite(w)) and len(w) == 5:
            out[t] = np.sqrt(np.mean(w * w) * 252.0)
    return pd.Series(out, index=fr.index)


def robust_block(fr, d, metric_series, label):
    """§8/§9: Q1/Q5 event 기준 metric별 (mean/median/n/spread/t/CI)."""
    p = d["pct_rv20_rol"]
    rows = []
    m = pd.Series(metric_series, index=fr.index)
    base = pd.DataFrame({"p": p, "v": m}).dropna()
    for pname, (ps, pe) in PERIODS.items():
        sel = base
        if ps:
            sel = sel[sel.index >= pd.Timestamp(ps)]
        if pe:
            sel = sel[sel.index <= pd.Timestamp(pe)]
        q1 = sel[sel["p"] < Q1_CUT]["v"].to_numpy(dtype=float)
        q5 = sel[sel["p"] >= Q5_CUT]["v"].to_numpy(dtype=float)
        if len(q1) == 0 or len(q5) == 0:
            rows.append(dict(period=pname, metric=label, n_q1=int(len(q1)), n_q5=int(len(q5)),
                             mean_q1=None, mean_q5=None, median_q1=None, median_q5=None,
                             spread_q5q1=None, t=None, pval=None, ci_lo=None, ci_hi=None))
            continue
        t, pv = st.ttest_ind(q5, q1, equal_var=False)
        ci = bootstrap_ci(q1, q5)
        rows.append(dict(period=pname, metric=label, n_q1=int(len(q1)), n_q5=int(len(q5)),
                         mean_q1=float(np.mean(q1)), mean_q5=float(np.mean(q5)),
                         median_q1=float(np.median(q1)), median_q5=float(np.median(q5)),
                         spread_q5q1=float(np.mean(q5) - np.mean(q1)),
                         t=round(float(t), 3), pval=float(pv),
                         ci_lo=float(ci[0]), ci_hi=float(ci[1])))
    return rows


def main():
    df = load()
    fr = front_series(df)              # full(front) fr — pct_rv20_rol 등 신호 정의용
    d, fwd, mae = process(fr)          # Stage 5-1 primary: d.pct_rv20_rol
    cts_all = fr[~fr["roll"]].copy()   # roll 제거 연속계약 (백테스트 가격용)

    pct = d["pct_rv20_rol"]
    print("== Stage 5-3: RV20 Q5(Q>=0.8 기존) 0~1x sizing 백테스트 ==")

    # ---------- 백테스트 ----------
    rows, dec_rows = [], []
    strat_keys = [(None, "buyhold")] + [(k, v) for k, v in RULES.items()]
    for pname, (ps, pe) in PERIODS.items():
        sub = cts_all[cts_all.index >= pd.Timestamp(ps)] if ps else cts_all
        if pe:
            sub = sub[sub.index <= pd.Timestamp(pe)]
        if len(sub) < 3:
            continue
        bh = run_buyhold(sub)
        m = metrics(bh)
        m |= dict(strategy="buyhold", period=pname, status="OK")
        rows.append(m)
        for key, rule in RULES.items():
            bt = run_sizing(sub, pct, rule)
            mb = metrics(bt)
            mb |= dict(strategy=f"sizing_{key}", period=pname, status="OK")
            rows.append(mb)
            dc = decompose(bt, bh)
            dc |= dict(strategy=f"sizing_{key}", period=pname)
            dec_rows.append(dc)

    bt_out = pd.DataFrame(rows)
    cols = ["strategy", "period", "years", "bars", "capital_krw",
            "cagr_net", "sharpe_net", "sortino_net", "calmar_net", "mdd_net",
            "win_rate", "profit_factor", "resize_count", "n_segments",
            "trades_per_year", "total_cost_krw", "total_cost_pct_cap",
            "avg_exposure", "time_in_market", "final_equity_krw", "status"]
    bt_out = bt_out[[c for c in cols if c in bt_out.columns]].sort_values(["period", "strategy"])
    bt_out.to_csv(OUTDIR / "futures-stage5-3-sizing-backtest.csv", index=False, encoding="utf-8-sig")

    dec_out = pd.DataFrame(dec_rows).sort_values(["period", "strategy"])
    dec_out.to_csv(OUTDIR / "futures-stage5-3-decomposition.csv", index=False, encoding="utf-8-sig")

    # ---------- §8/§9 robustness ----------
    rob_rows = []
    for h in HORIZONS_ROBUST:
        fwdh = same_contract_ret(fr, h)
        rob_rows += robust_block(fr, d, fwdh, f"fwd{h}d")
    frv5 = fwd_rv5(fr)
    rob_rows += robust_block(fr, d, frv5, "fwd5d_rv_ann")
    rob = pd.DataFrame(rob_rows)
    rob.to_csv(OUTDIR / "futures-stage5-3-robustness.csv", index=False, encoding="utf-8-sig")

    # ---------- §9: B&H 최대 drawdown 구간에서의 exposure ----------
    dd_rows = []
    for pname, (ps, pe) in PERIODS.items():
        sub = cts_all[cts_all.index >= pd.Timestamp(ps)] if ps else cts_all
        if pe:
            sub = sub[sub.index <= pd.Timestamp(pe)]
        if len(sub) < 3:
            continue
        bh = run_buyhold(sub)
        nav = pd.Series(bh["nav"], index=sub.index)
        dd = nav / nav.cummax() - 1.0
        trough = nav.idxmin()
        wnd = (nav.index >= trough - pd.Timedelta(days=30)) & \
              (nav.index <= trough + pd.Timedelta(days=300))
        m_bh = metrics(bh)
        row = dict(period=pname, bh_mdd=round(m_bh["mdd_net"], 4),
                   trough=str(trough)[:10])
        bh_full = pd.Series(bh["nav"], index=sub.index)
        bh_peak = bh_full.cummax()
        # window 내 최소 drawdown(흐름 전체 누적 peak 기준) — 양쪽 동일 기준
        dd_bh_w = (bh_full / bh_peak - 1.0)[wnd].min()
        row["bh_mdd_in_wnd"] = round(float(dd_bh_w), 4)
        for key, rule in RULES.items():
            bt = run_sizing(sub, pct, rule)
            s = pd.Series(bt["nav"], index=sub.index)
            dd_w = (s / s.cummax() - 1.0)[wnd]
            row[f"sizing_{key}_mdd_in_wnd"] = round(float(dd_w.min()), 4) if len(dd_w.dropna()) > 0 else None
        dd_rows.append(row)
    dd_out = pd.DataFrame(dd_rows)
    dd_out.to_csv(OUTDIR / "futures-stage5-3-dd-window.csv", index=False, encoding="utf-8-sig")

    import json
    detail = {
        "backtest": bt_out.to_dict(orient="records"),
        "decomposition": dec_out.to_dict(orient="records"),
        "robustness": rob.to_dict(orient="records"),
        "dd_window": dd_out.to_dict(orient="records"),
        "config": {"cost_side_krw": COST_SIDE, "q1_cut": Q1_CUT, "q5_cut": Q5_CUT,
                   "rules": RULES, "horizons": HORIZONS_ROBUST},
    }
    (OUTDIR / "futures-stage5-3-sizing-backtest.json").write_text(
        json.dumps(detail, ensure_ascii=False, indent=2), encoding="utf-8")

    # ---------- 화면 출력 ----------
    pd.set_option("display.width", 260)
    pd.set_option("display.max_columns", 50)
    print("\n--- 백테스트 (B&H vs sizing) ---")
    show = bt_out[["strategy", "period", "cagr_net", "sharpe_net", "sortino_net",
                   "mdd_net", "calmar_net", "win_rate", "profit_factor", "resize_count",
                   "avg_exposure", "time_in_market", "total_cost_krw"]]
    print(show.to_string(index=False))
    print("\n--- B&H 대비 분해(delta) ---")
    print(dec_out.to_string(index=False))
    print("\n--- §8 robustness: Q1/Q5 이후수익 · 이후 5일 변동성 ---")
    print(rob[(rob["metric"].isin(["fwd5d", "fwd10d", "fwd15d", "fwd20d"]))][
        ["period", "metric", "n_q1", "n_q5", "mean_q1", "mean_q5", "spread_q5q1", "t", "pval"]].to_string(index=False))
    print("\n--- §9 이후 5일 실현변동성(연율) Q1/Q5 ---")
    print(rob[rob["metric"] == "fwd5d_rv_ann"][
        ["period", "n_q1", "n_q5", "mean_q1", "mean_q5", "spread_q5q1", "t", "pval"]].to_string(index=False))
    print(f"\n저장: futures-stage5-3-{{sizing-backtest,decomposition,robustness,dd-window}}.{{csv,json / md 는 별도}}")


if __name__ == "__main__":
    main()