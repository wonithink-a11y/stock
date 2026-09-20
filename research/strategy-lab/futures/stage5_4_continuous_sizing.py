# -*- coding: utf-8 -*-
"""Stage 5-4: KOSPI200 선물 일봉 연속(continuous) sizing 백테스트 (연구 산출물).

- 목적: Stage 5-3(threshold binary) 대신 percentile에 연속 반응하는 exposure가
  CAGR 희생을 줄이면서 MDD를 줄이는지 검증. '전체 Sharpe 최대'가 아니라
  특정 레짐(코로나) 의존 없는 위험 감소 효과가 핵심.
- 원천: Stage 5-1~5-3과 동일(KRX drv/fut_bydd_trd 일봉 주간, 새 수집 금지).
- 신호: Stage 5-1 확정 rolling252 RV20 percentile(pct_rv20_rol). percentile 0~1.
- 연속 규칙(고정 3종, 함수/배율 최적화 금지):
  A: exposure = 1.0 - 0.5*pct, clip [0.25, 1.0]
  B: exposure = 1.0 - 0.75*pct, clip [0.25, 1.0]
  C: exposure = 1.0 - pct,      clip [0.0, 1.0]
- 비교: B&H 1.0x + Stage 5-3 A/B/C는 기존 산출물(CSV/JSON)을 reference로 읽음(재현 금지).
- 체결: 신호 t close -> t+1 open부터 적용, look-ahead 금지, leverage>1 금지.
- 비용: Stage 3-2 동일(편도 500원+1틱). sizing 변화 시에만, |Δw|에 비례(5-3과 동일 관례).
- 지표: CAGR/Sharpe/Sortino/Calmar/MDD/realized vol/TotalCost/AvgExposure/ExposureTurnover/ResizeCount
- §8 2010-2017·2018-2024에서 B&H 대비 ΔCAGR/Δvol/ΔMDD/ΔSharpe 비교(레짐 의존 판단).
- §9 0x 민감도: continuous가 5-3 B(0x) 대비 CAGR 보존하면서 MDD 줄이는지.
- §10 코로나 제외: 2020-03-19 trough 기준 dd-window와 동일 방식 window 제외 재계산
  (long: trough±[30d,300d] = 2020-02-18~2021-01-13, short: trough±[15d,60d] = 2020-03-04~2020-05-18).
- §11 5일 robustness: pct decile별 fwd +5/+10/+15/+20d 실현변동성·수익률,
  continuous exposure 관계, exposure×fwdvol(위험노출) 평탄성.
- 금지(미실행): target vol 최적화·5/10/15% 탐색·새 함수 형태·threshold 최적화·EMA/OI/basis
  결합·Short·leverage>1·WFA/OOS·타선물·intraday·production·commit.
"""
from pathlib import Path

import numpy as np
import pandas as pd

from stage5_1_volatility_event_study import load, front_series, process, same_contract_ret
from stage5_3_sizing_backtest import run_buyhold, metrics as metrics_53
from stage5_2_volatility_risk_study import bootstrap_ci

REPO = Path(r"C:\Users\User\projects\stock")
OUTDIR = REPO / "research" / "strategy-lab" / "futures"
REF_BT = OUTDIR / "futures-stage5-3-sizing-backtest.csv"
REF_DEC = OUTDIR / "futures-stage5-3-decomposition.csv"

MULT = 250_000.0
TICKVAL = 12_500.0
FEE_PER_SIDE = 500.0
SLIP_TICKS = 1.0
DAYS_PER_YEAR = 365.25
TRADING_DAYS = 252.0
COST_SIDE = FEE_PER_SIDE + TICKVAL * SLIP_TICKS  # 13,000 KRW / 1x 편도
PERIODS = {
    "ALL": (None, None),
    "2010-2017": ("2010-01-01", "2017-12-31"),
    "2018-2024": ("2018-01-01", "2024-12-31"),
    "2025-": ("2025-01-01", None),
}
COVID_LONG = (pd.Timestamp("2020-02-18"), pd.Timestamp("2021-01-13"))
COVID_SHORT = (pd.Timestamp("2020-03-04"), pd.Timestamp("2020-05-18"))
RULES = {"A": (0.5, 0.25, 1.0), "B": (0.75, 0.25, 1.0), "C": (1.0, 0.0, 1.0)}


def cont_weight(p, k, lo, hi):
    if p != p:
        return 1.0
    return float(np.clip(1.0 - k * p, lo, hi))


def run_continuous(cts, pct, k, lo, hi):
    """Stage 5-3 run_sizing과 동일 체결·비용 모형. w는 percentile 연속 함수."""
    o = cts["TDD_OPNPRC"].to_numpy(dtype=float)
    c = cts["TDD_CLSPRC"].to_numpy(dtype=float)
    idx = cts.index
    pv = pct.reindex(idx).to_numpy(dtype=float)
    n = len(cts)
    if n < 2:
        return None
    w = np.full(n, np.nan)
    w[0] = 1.0
    for t in range(1, n):
        w[t] = cont_weight(pv[t - 1], k, lo, hi)
    cap = float(cts["TDD_CLSPRC"].max()) * MULT
    nav = np.empty(n)
    nav[0] = cap
    cost = COST_SIDE
    nav[0] -= cost
    resizes = 0
    turn = 0.0
    for t in range(1, n):
        pnl = w[t - 1] * (o[t] - c[t - 1]) + w[t] * (c[t] - o[t])
        pnl *= MULT
        dc = abs(w[t] - w[t - 1]) * COST_SIDE
        if abs(w[t] - w[t - 1]) > 1e-12:
            resizes += 1
        nav[t] = nav[t - 1] + pnl - dc
        cost += dc
        turn += abs(w[t] - w[t - 1])
    cost += w[-1] * COST_SIDE
    nav[-1] -= w[-1] * COST_SIDE
    return dict(nav=nav, w=w, idx=idx, cap=cap, cost=cost, resizes=resizes, turnover=turn)


def metrics_extended(res):
    m = metrics_53(res)
    if m is None:
        return None
    pos_ts = pd.DatetimeIndex(res["idx"])[:len(res["nav"])]
    daily_n = pd.Series(np.asarray(res["nav"]) + res["cap"], index=pos_ts).resample("D").last().dropna()
    rets = daily_n.pct_change().dropna()
    m["vol_ann"] = round(float(rets.std(ddof=1) * np.sqrt(TRADING_DAYS)), 4) if len(rets) > 1 else np.nan
    m["avg_exposure"] = round(float(np.nanmean(res["w"])), 4)
    turn = res.get("turnover", 0.0)
    m["exp_turnover"] = round(float(turn), 4)
    years = m["years"]
    m["exp_turnover_ann"] = round(float(turn / years), 4) if years else np.nan
    m["resize_count"] = int(res["resizes"])
    return m


def fwd_rv(fr, h):
    """동일계약 이후 h일 실현변동성(연율) — t+1..t+h 로그수익 기준."""
    n = len(fr)
    cd = fr["ISU_CD"].to_numpy()
    cl = fr["TDD_CLSPRC"].to_numpy(dtype=float)
    logr = np.full(n, np.nan)
    for i in range(1, n):
        if cd[i] == cd[i - 1] and np.isfinite(cl[i]) and np.isfinite(cl[i - 1]) and cl[i - 1] > 0:
            logr[i] = np.log(cl[i] / cl[i - 1])
    out = np.full(n, np.nan)
    for t in range(n):
        t2 = t + h
        if t2 >= n or cd[t] != cd[t2]:
            continue
        w = logr[t + 1:t2 + 1]
        if len(w) == h and np.all(np.isfinite(w)):
            out[t] = np.sqrt(np.mean(w * w) * 252.0)
    return pd.Series(out, index=fr.index)


def main():
    df = load()
    fr = front_series(df)
    d, fwd, mae = process(fr)
    pct = d["pct_rv20_rol"]
    cts_all = fr[~fr["roll"]].copy()

    # -------- reference: Stage 5-3 (재현 금지) --------
    ref_bt = pd.read_csv(REF_BT, encoding="utf-8-sig")
    ref_dec = pd.read_csv(REF_DEC, encoding="utf-8-sig")

    print("== Stage 5-4: continuous sizing 100% (A/B/C) vs B&H · 5-3 binary (reference) ==")

    # -------- 1) 기본 백테스트 (기간별) --------
    rows = []
    for pname, (ps, pe) in PERIODS.items():
        sub = cts_all[cts_all.index >= pd.Timestamp(ps)] if ps else cts_all
        if pe:
            sub = sub[sub.index <= pd.Timestamp(pe)]
        if len(sub) < 3:
            continue
        for key, (k, lo, hi) in RULES.items():
            bt = run_continuous(sub, pct, k, lo, hi)
            m = metrics_extended(bt)
            m |= dict(source=f"5-4_{key}", period=pname, window="none", status="OK")
            rows.append(m)
    out = pd.DataFrame(rows)
    print("\n--- 5-4 continuous (기본, window=none) ---")
    print(out[["source", "period", "cagr_net", "vol_ann", "sharpe_net", "sortino_net",
               "mdd_net", "calmar_net", "avg_exposure", "exp_turnover_ann",
               "resize_count", "total_cost_krw"]].to_string(index=False))

    # -------- 2) Stage 5-3 reference 병합 (비교표용) --------
    ref_rows = []
    for _, r in ref_bt.iterrows():
        ref_rows.append(dict(
            source=("B&H" if r["strategy"] == "buyhold" else "5-3_" + r["strategy"].split("_")[1]),
            period=r["period"], window="none",
            cagr_net=r["cagr_net"], sharpe_net=r["sharpe_net"], sortino_net=r["sortino_net"],
            calmar_net=r["calmar_net"], mdd_net=r["mdd_net"],
            total_cost_krw=r["total_cost_krw"], avg_exposure=r["avg_exposure"],
            resize_count=r["resize_count"], vol_ann=np.nan, exp_turnover=np.nan,
            exp_turnover_ann=np.nan, status="ref", years=r["years"], bars=r["bars"],
        ))
    combined = pd.concat([out.drop(columns=["years", "bars"]), pd.DataFrame(ref_rows)], ignore_index=True)
    # out 컬럼 재정렬 + reference 컬럼 매핑
    cols = ["source", "period", "window", "years", "bars", "capital_krw", "cagr_net",
            "vol_ann", "sharpe_net", "sortino_net", "calmar_net", "mdd_net",
            "total_cost_krw", "avg_exposure", "exp_turnover", "exp_turnover_ann",
            "resize_count", "status"]
    full = pd.concat([
        out,
        pd.DataFrame(ref_rows),
    ], ignore_index=True)
    for col in [c for c in cols if c not in full.columns]:
        full[col] = np.nan
    full = full[cols].sort_values(["period", "source"])

    # -------- 3) §10 코로나 제외 (5-4 + 신규 B&H) --------
    covid_rows = []
    for pname, (ps, pe) in PERIODS.items():
        sub_full = cts_all[cts_all.index >= pd.Timestamp(ps)] if ps else cts_all
        if pe:
            sub_full = sub_full[sub_full.index <= pd.Timestamp(pe)]
        if len(sub_full) < 3:
            continue
        for wname, (lo, hi) in [("none", (None, None)),
                                ("covid_long", COVID_LONG), ("covid_short", COVID_SHORT)]:
            if lo is None:
                sub = sub_full
            else:
                sub = sub_full[~((sub_full.index >= lo) & (sub_full.index <= hi))]
            if len(sub) < 3:
                continue
            bh = run_buyhold(sub)
            mb = metrics_extended(bh)
            mb |= dict(source="B&H", period=pname, window=wname, status="OK")
            covid_rows.append(mb)
            for key, (k, a, b) in RULES.items():
                bt = run_continuous(sub, pct, k, a, b)
                m = metrics_extended(bt)
                m |= dict(source=f"5-4_{key}", period=pname, window=wname, status="OK")
                covid_rows.append(m)
    covid = pd.DataFrame(covid_rows)
    print("\n--- §10 코로나 제외 (B&H baseline + 5-4) ---")
    print(covid[["source", "period", "window", "bars", "cagr_net", "vol_ann", "sharpe_net",
                 "mdd_net", "calmar_net", "avg_exposure"]].to_string(index=False))

    # -------- §8 B&H 대비 분해 (5-3 reference vs 5-4 신규) --------
    dec_rows = []
    for _, r in ref_dec.iterrows():
        dec_rows.append(dict(
            source="5-3_" + r["strategy"].split("_")[1], period=r["period"],
            d_cagr=r["d_cagr"], d_vol_ann=r["d_vol_ann"], d_mdd=r["d_mdd"],
            d_cost=r["d_cost"], d_exposure=r["d_exposure"], d_sharpe=r["d_sharpe"],
            d_sortino=r["d_sortino"], status="ref"))
    for pname, (ps, pe) in PERIODS.items():
        sub = cts_all[cts_all.index >= pd.Timestamp(ps)] if ps else cts_all
        if pe:
            sub = sub[sub.index <= pd.Timestamp(pe)]
        if len(sub) < 3:
            continue
        bh = run_buyhold(sub)
        for key, (k, lo, hi) in RULES.items():
            bt = run_continuous(sub, pct, k, lo, hi)
            mb = metrics_extended(bt)
            mbh = metrics_extended(bh)
            dec_rows.append(dict(
                source=f"5-4_{key}", period=pname,
                d_cagr=round(float(mb["cagr_net"] - mbh["cagr_net"]), 4),
                d_vol_ann=round(float(mb["vol_ann"] - mbh["vol_ann"]), 4),
                d_mdd=round(float(mb["mdd_net"] - mbh["mdd_net"]), 4),
                d_cost=round(bt["cost"] - bh["cost"], 0),
                d_exposure=round(float(np.nanmean(bt["w"]) - 1.0), 4),
                d_sharpe=round(float(mb["sharpe_net"] - mbh["sharpe_net"]), 3),
                d_sortino=round(float(mb["sortino_net"] - mbh["sortino_net"]), 3),
                status="new"))
    dec = pd.DataFrame(dec_rows).sort_values(["period", "source"])
    print("\n--- §8 B&H 대비 분해 (5-3 reference vs 5-4) ---")
    print(dec[["source", "period", "d_cagr", "d_vol_ann", "d_mdd", "d_sharpe",
               "d_sortino", "d_exposure"]].to_string(index=False))

    # -------- §11 5일 robustness: pct decile x fwd vol/ret + exposure --------
    base = pd.DataFrame(index=fr.index)
    base["p"] = pct
    for h in (5, 10, 15, 20):
        base[f"rv{h}"] = fwd_rv(fr, h)
        base[f"ret{h}"] = same_contract_ret(fr, h)
    robust_rows = []
    for pname, (ps, pe) in PERIODS.items():
        b = base
        if ps:
            b = b[b.index >= pd.Timestamp(ps)]
        if pe:
            b = b[b.index <= pd.Timestamp(pe)]
        b = b.dropna(subset=["p", "rv5", "rv20"])
        if len(b) < 50:
            robust_rows.append(dict(period=pname, note="유보(표본부족)"))
            continue
        b = b.copy()
        b["dec"] = pd.qcut(b["p"], 10, labels=False, duplicates="drop")
        for dk in range(int(b["dec"].nunique())):
            g = b[b["dec"] == dk]
            mp = float(g["p"].mean())
            row = dict(period=pname, decile=int(dk), n=len(g), mean_pct=round(mp, 4))
            row["exp_A"] = round(cont_weight(mp, *RULES["A"]), 4)
            row["exp_B"] = round(cont_weight(mp, *RULES["B"]), 4)
            row["exp_C"] = round(cont_weight(mp, *RULES["C"]), 4)
            for h in (5, 10, 15, 20):
                row[f"fwd_rv{h}d"] = round(float(g[f"rv{h}"].mean()), 4)
                row[f"fwd_ret{h}d"] = round(float(g[f"ret{h}"].mean()), 5)
            row["ewvol_A"] = round(row["exp_A"] * row["fwd_rv5d"], 5)
            row["ewvol_B"] = round(row["exp_B"] * row["fwd_rv5d"], 5)
            row["ewvol_C"] = round(row["exp_C"] * row["fwd_rv5d"], 5)
            robust_rows.append(row)
    robust = pd.DataFrame(robust_rows)
    print("\n--- §11 pct decile x 이후 변동성/수익 (전체) ---")
    print(robust[robust["period"] == "ALL"].to_string(index=False))

    # -------- 저장 --------
    full.to_csv(OUTDIR / "futures-stage5-4-continuous-sizing.csv", index=False, encoding="utf-8-sig")
    covid.to_csv(OUTDIR / "futures-stage5-4-covid-excl.csv", index=False, encoding="utf-8-sig")
    dec.to_csv(OUTDIR / "futures-stage5-4-decomposition.csv", index=False, encoding="utf-8-sig")
    robust.to_csv(OUTDIR / "futures-stage5-4-robustness.csv", index=False, encoding="utf-8-sig")

    import json
    detail = {
        "backtest": full.to_dict(orient="records"),
        "covid_excl": covid.to_dict(orient="records"),
        "decomposition": dec.to_dict(orient="records"),
        "robustness": robust.to_dict(orient="records"),
        "config": {"cost_side_krw": COST_SIDE, "rules": RULES,
                   "covid_long": [str(x.date()) for x in COVID_LONG],
                   "covid_short": [str(x.date()) for x in COVID_SHORT],
                   "ref_stage5_3": "futures-stage5-3-sizing-backtest.csv(decomp)"},
    }
    (OUTDIR / "futures-stage5-4-continuous-sizing.json").write_text(
        json.dumps(detail, ensure_ascii=False, indent=2), encoding="utf-8")
    print("\n저장: futures-stage5-4-{continuous-sizing,covid-excl,decomposition,robustness}.csv + json (md 별도)")


if __name__ == "__main__":
    main()