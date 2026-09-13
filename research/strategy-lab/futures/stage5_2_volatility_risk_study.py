# -*- coding: utf-8 -*-
"""Stage 5-2: KOSPI200 선물 일봉 변동성 event-study의 위험검증 (READ-ONLY).

- 목적: Stage 5-1 "RV20 rolling252 상위 20% → 이후 20일 수익률 우위(+2~3%p)"가
  실제로는 위험 증가를 동반하는지 확인. H1(수익증가) vs H2(위험증가) 분리 평가.
- 원천: Stage 3-2/5-1 동일(KRX drv/fut_bydd_trd 일봉 주간 4,109일, 새 수집 금지).
- 변동성 상태: Stage 5-1 확정 rolling252 RV20 percentile, Q1<20%/Q5≥80%만(최적화 없음).
- 미래 20거래일 관찰:
  A) 위험: 20d realized variance/vol, 20d 최대손실(일최저 로그수익), MAE(진입종가 대비
     이후 20일 최저 low), 95% VaR(일수익률 5% 분위), ES(하위 5% 평균), downside vol(음수수익률 std)
  B) 수익: 1/5/20일 동일계약 수익률(Stage 5-1 동일 정의)
- 4. 지표: n / mean / median / Q5-Q1 spread / Welch t / bootstrap 95% CI(2000x, seed=7)
- 7. 위험조정: fwd20 / fwd20 vol, fwd20 / downside vol (비최적화, 단순 비율)
- 5. 기간: 2010-2017 / 2018-2024 / 2025- / 전체
- 9. 다중검정: 새 지표 발굴 없음. Stage 5-1에서 이미 정한 신호(Q1/Q5)만.
- 금지(미실행): 백테스트·Short·leverage·threshold 최적화·EMA/OI/basis·stop·WFA/OOS·
  타선물·새 데이터·production·commit.
"""
from pathlib import Path

import numpy as np
import pandas as pd

REPO = Path(r"C:\Users\User\projects\stock")
OUTDIR = REPO / "research" / "strategy-lab" / "futures"
SEED = 7
H = 20
TRADING_DAYS = 252.0

PERIODS = {
    "ALL": (None, None),
    "2010-2017": ("2010-01-01", "2017-12-31"),
    "2018-2024": ("2018-01-01", "2024-12-31"),
    "2025-": ("2025-01-01", None),
}
Q1_CUT, Q5_CUT = 0.2, 0.8


def bootstrap_ci(a, b, n_iter=2000, seed=SEED):
    """Q5-Q1 spread(=mean_b - mean_a)의 bootstrap 95% CI."""
    rng = np.random.default_rng(seed)
    a = np.asarray(a, dtype=float)
    b = np.asarray(b, dtype=float)
    if len(a) == 0 or len(b) == 0:
        return np.nan, np.nan
    diffs = np.empty(n_iter)
    na, nb = len(a), len(b)
    for k in range(n_iter):
        sa = a[rng.integers(0, na, size=na)]
        sb = b[rng.integers(0, nb, size=nb)]
        diffs[k] = sb.mean() - sa.mean()
    return float(np.percentile(diffs, 2.5)), float(np.percentile(diffs, 97.5))


def main():
    from scipy import stats as st
    from stage5_1_volatility_event_study import load, front_series, process

    df = load()
    fr = front_series(df)
    d, fwd, mae = process(fr)
    n = len(fr)
    idx = fr.index

    cl = fr["TDD_CLSPRC"].to_numpy(dtype=float)
    cd = fr["ISU_CD"].to_numpy()
    # 동일계약 일간 로그수익률 (roll 봉 NaN)
    logr = np.full(n, np.nan)
    for i in range(1, n):
        if cd[i] == cd[i - 1] and np.isfinite(cl[i]) and np.isfinite(cl[i - 1]) and cl[i - 1] > 0:
            logr[i] = np.log(cl[i] / cl[i - 1])

    # ---- 미래 20거래일 위험 지표 (t+1..t+H, 동일계약 연속일 때만) ----
    out = {k: np.full(n, np.nan) for k in
           ["var20", "vol20", "maxloss20", "vaR95", "es95", "dvol20",
            "ret1", "ret5", "ret20", "mae20"]}
    for t in range(n):
        t2 = t + H
        if t2 >= n or cd[t] != cd[t2]:
            continue
        win = logr[t + 1:t2 + 1]
        if len(win) != H or not np.all(np.isfinite(win)):
            continue
        sd = win.std(ddof=1)
        out["var20"][t] = sd * sd * TRADING_DAYS
        out["vol20"][t] = sd * np.sqrt(TRADING_DAYS)
        out["maxloss20"][t] = win.min()
        q05 = np.quantile(win, 0.05)
        out["vaR95"][t] = q05
        tail = win[win <= q05]
        out["es95"][t] = tail.mean() if len(tail) else np.nan
        neg = win[win < 0]
        out["dvol20"][t] = neg.std(ddof=1) * np.sqrt(TRADING_DAYS) if len(neg) >= 2 else np.nan
    for h in [1, 5, 20]:
        out[f"ret{h}"] = fwd[h].to_numpy()
    out["mae20"] = mae[H].to_numpy()

    risk = pd.DataFrame(out, index=idx)
    # 위험조정 (20일 수익률 / 위험)
    risk["ra_vol"] = risk["ret20"] / risk["vol20"]
    risk["ra_dvol"] = risk["ret20"] / risk["dvol20"]

    def stat_of(x):
        x = x[np.isfinite(x)]
        if len(x) == 0:
            return (np.nan,) * 4
        return (float(np.mean(x)), float(np.median(x)), float(len(x)),
                float(np.min(x)))

    rows = []
    met_defs = [
        ("future_risk", "var20", "20d realized variance(연율화)"),
        ("future_risk", "vol20", "20d realized vol(연율화)"),
        ("future_risk", "maxloss20", "20d 내 일최저 로그수익"),
        ("future_risk", "mae20", "MAE(진입종가 대비 20d 최저 low)"),
        ("future_risk", "vaR95", "일수익률 95% VaR(5% 분위)"),
        ("future_risk", "es95", "Expected Shortfall(하위 5% 평균)"),
        ("future_risk", "dvol20", "20d down-side vol(음수수익률 std)"),
        ("future_ret", "ret1", "1일 미래수익률"),
        ("future_ret", "ret5", "5일 미래수익률"),
        ("future_ret", "ret20", "20일 미래수익률"),
        ("riskadj", "ra_vol", "ret20 / vol20"),
        ("riskadj", "ra_dvol", "ret20 / down-side vol"),
    ]
    for itype, col, label in met_defs:
        pctl = d["pct_rv20_rol"]
        for pname, (p0, p1) in PERIODS.items():
            mask = pd.Series(True, index=idx)
            if p0:
                mask &= idx >= p0
            if p1:
                mask &= idx <= p1
            q1m = mask & (pctl < Q1_CUT)
            q5m = mask & (pctl >= Q5_CUT)
            a = risk.loc[q1m, col].to_numpy()
            b = risk.loc[q5m, col].to_numpy()
            a = a[np.isfinite(a)]
            b = b[np.isfinite(b)]
            if len(a) < 5 or len(b) < 5:
                rows.append(dict(type=itype, metric=col, period=pname,
                                 n_q1=int(len(a)), n_q5=int(len(b)),
                                 mean_q1=np.nan, median_q1=np.nan, mean_q5=np.nan,
                                 median_q5=np.nan, spread_q5q1=np.nan,
                                 tstat=np.nan, pval=np.nan,
                                 ci_lo=np.nan, ci_hi=np.nan, label=label))
                continue
            m1, med1, n1, _ = stat_of(a)
            m5, med5, n5, _ = stat_of(b)
            spread = m5 - m1
            t, p = st.ttest_ind(b, a, equal_var=False)
            cilo, cihi = bootstrap_ci(a, b)
            rows.append(dict(type=itype, metric=col, period=pname,
                             n_q1=int(n1), n_q5=int(n5),
                             mean_q1=round(m1, 6), median_q1=round(med1, 6),
                             mean_q5=round(m5, 6), median_q5=round(med5, 6),
                             spread_q5q1=round(spread, 6),
                             tstat=round(float(t), 3), pval=round(float(p), 4),
                             ci_lo=round(cilo, 6), ci_hi=round(cihi, 6),
                             label=label))

    et = pd.DataFrame(rows)
    order = {"2010-2017": 0, "2018-2024": 1, "2025-": 2, "ALL": 3}
    et["_ord"] = et["period"].map(order)
    et = et.sort_values(["type", "metric", "_ord"]).drop(columns="_ord")

    et.to_csv(OUTDIR / "futures-stage5-2-volatility-risk-study.csv",
              index=False, encoding="utf-8-sig")

    print("== Stage 5-2: Q1(저변동성)/Q5(고변동성) 비교, spread=Q5-Q1 ==")
    pd.set_option("display.width", 250)
    for itype in ["future_risk", "future_ret", "riskadj"]:
        print(f"\n--- {itype} ---")
        sub = et[et["type"] == itype]
        print(sub[["metric", "period", "n_q1", "n_q5", "mean_q1", "mean_q5",
                   "spread_q5q1", "tstat", "pval", "ci_lo", "ci_hi"]].to_string(index=False))

    import json
    detail = {
        "note": "H1(고변동성->수익증가) vs H2(고변동성->위험증가) 분리 검증, "
                "rolling252 RV20 percentile Q1/Q5, spread=Q5-Q1, boot 95% CI",
        "n_bars": int(n), "start": str(idx[0].date()), "end": str(idx[-1].date()),
        "row_count": int(len(et)),
        "rows": et.astype(str).to_dict(orient="records"),
    }
    (OUTDIR / "futures-stage5-2-volatility-risk-study.json").write_text(
        json.dumps(detail, ensure_ascii=False, indent=2), encoding="utf-8")
    print("\n저장: futures-stage5-2-volatility-risk-study.csv / .json")


if __name__ == "__main__":
    main()