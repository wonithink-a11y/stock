# -*- coding: utf-8 -*-
"""Stage 5-1: KOSPI200 선물 일봉 실현변동성 event-study (READ-ONLY, 전략/백테스트 없음).

- 원천: research/strategy-lab/.cache/kospi200_daily/ (Stage 3-2 기존 데이터, 새 수집 금지)
- 사용 필드: TDD_CLSPRC/TDD_OPNPRC/TDD_HGPRC/TDD_LWPRC(선물), SPOT_PRC, ACC_TRDVOL, ACC_OPNINT_QTY, BAS_DD
- front 계약: 날짜별 최대거래량 주간 계약 (Stage 3-2 관례)
- RV5/RV20/RV60: 일간 close-to-close 로그수익률 기반 rolling √(252·mean(r²)), 연율화
- 롤 처리: roll 봉(ISU_CD 변경일)의 일중 로그수익률은 NaN 처리, 미래수익률은 동일계약 t+h 기준
- 분위수: 과거 정보만. primary = expanding(min 252, Stage 4-2 동일), 보조 = rolling252
- 지표: n / mean / median / win rate / MAE(low기준) / Q1-Q5 spread / Welch t / bootstrap CI(2000x)
- 판정: A 일관·경제적 유의 / B 일부 유의 / C 약함·레짐 / D 데이터
"""
from pathlib import Path

import numpy as np
import pandas as pd

REPO = Path(r"C:\Users\User\projects\stock")
CACHE = REPO / "research" / "strategy-lab" / ".cache" / "kospi200_daily"
OUTDIR = REPO / "research" / "strategy-lab" / "futures"
HORIZONS = [1, 5, 20]

PERIODS = {
    "ALL": (None, None),
    "2010-2017": ("2010-01-01", "2017-12-31"),
    "2018-2024": ("2018-01-01", "2024-12-31"),
    "2025-": ("2025-01-01", None),
}
SEED = 12345


def load():
    df = pd.concat([pd.read_parquet(p) for p in sorted(CACHE.glob("kospi200_*.parquet"))],
                   ignore_index=True)
    df = df[df["ISU_NM"].str.contains("주간", na=False)].copy()
    for f in ["TDD_CLSPRC", "TDD_OPNPRC", "TDD_HGPRC", "TDD_LWPRC",
              "SPOT_PRC", "ACC_TRDVOL", "ACC_OPNINT_QTY"]:
        df[f] = pd.to_numeric(df[f], errors="coerce")
    df["date"] = pd.to_datetime(df["BAS_DD"], format="%Y%m%d")
    return df.sort_values("date")


def front_series(df):
    fr = df.sort_values("ACC_TRDVOL", ascending=False).groupby("date").first().sort_index()
    fr["roll"] = (fr["ISU_CD"] != fr["ISU_CD"].shift(1)).fillna(True)
    return fr


def same_contract_ret(fr, h, field="TDD_CLSPRC"):
    idx = fr.index.to_numpy()
    cd = fr["ISU_CD"].to_numpy()
    v = fr[field].to_numpy(dtype=float)
    out = np.full(len(idx), np.nan)
    for i in range(len(idx)):
        i2 = i + h
        if i2 < len(idx) and cd[i] == cd[i2] and np.isfinite(v[i]) and np.isfinite(v[i2]):
            out[i] = v[i2] / v[i] - 1.0
    return pd.Series(out, index=idx)


def process(fr):
    n = len(fr)
    cl = fr["TDD_CLSPRC"].to_numpy(dtype=float)
    lo = fr["TDD_LWPRC"].to_numpy(dtype=float)

    # 1) 동일계약 일간 로그수익률 (roll 봉은 NaN)
    logr = np.full(n, np.nan)
    cd = fr["ISU_CD"].to_numpy()
    for i in range(1, n):
        if cd[i] == cd[i - 1] and np.isfinite(cl[i]) and np.isfinite(cl[i - 1]) and cl[i - 1] > 0:
            logr[i] = np.log(cl[i] / cl[i - 1])
    sq = pd.Series(np.nan_to_num(logr * logr), index=fr.index)
    NaN_BYTE = np.isnan(logr)

    def rv(w):
        s = sq.rolling(w, min_periods=w).mean() * 252.0
        s[NaN_BYTE] = np.nan  # roll 봉의 일 그 자체는 NaN 유지
        return np.sqrt(s.clip(lower=0))

    rv5 = rv(5)
    rv20 = rv(20)
    rv60 = rv(60)

    # 2) 변동성 상태 (과거 정보만)
    d = pd.DataFrame({
        "rv5": rv5, "rv20": rv20, "rv60": rv60,
        "ratio_5_20": rv5 / rv20,
        "ratio_20_60": rv20 / rv60,
    }, index=fr.index)
    d["chg_rv20"] = rv20.pct_change(1)             # 1일 변화율
    d["chg5_rv20"] = rv20.pct_change(5)            # 최근 5일 변화율

    def pctrank_exp(x):
        """과거 정보만의 expanding percentile (현재값을 제외한 t<t의 표본 기준)."""
        arr = x.to_numpy(dtype=float)
        out = np.full(len(arr), np.nan)
        n = len(arr)
        for i in range(n):
            v = arr[i]
            if not np.isfinite(v):
                continue
            past = arr[:i]
            past = past[np.isfinite(past)]
            if len(past) >= 252:
                out[i] = float(np.mean(past <= v))
        return pd.Series(out, index=x.index)

    def pctrank_rol(x, w=252):
        """과거 w 유효관측의 rolling percentile (NaN 롤봉 제거된 클린 배열 기준).

        - NaN(롤)을 제거한 clean 시퀀스 위에서, 현재 유효 obs 기준으로
          바로 앞 w개(정확히 252개)의 cum 분포에서 현재값의 백분위를 계산.
          미래 데이터 미사용, len>=w 보장.
        """
        arr = x.to_numpy(dtype=float)
        idx = x.index
        clean = pd.Series(arr, index=idx).dropna()
        cv = clean.to_numpy()
        pr = np.full(len(cv), np.nan)
        for i in range(len(cv)):
            if i < w:
                continue
            win = cv[i - w:i]
            pr[i] = float(np.mean(win <= cv[i]))
        out = pd.Series(np.nan, index=idx)
        out.loc[clean.index] = pr
        return out

    d["pct_rv20_exp"] = pctrank_exp(rv20)
    d["pct_rv20_rol"] = pctrank_rol(rv20)
    d["pct_chg_exp"] = pctrank_exp(rv20.pct_change(1))
    d["pct_ratio520_exp"] = pctrank_exp(rv5 / rv20)
    d["pct_ratio2060_exp"] = pctrank_exp(rv20 / rv60)

    # 3) 이후 수익률 (동일계약, 종가 close) + MAE(low 기준)
    fwd = {h: same_contract_ret(fr, h) for h in HORIZONS}
    mae = {}
    for h in HORIZONS:
        val = np.full(n, np.nan)
        for i in range(n):
            i2 = i + h
            if i2 < n and cd[i] == cd[i2] and np.isfinite(cl[i]) and cl[i] > 0:
                lows = lo[i + 1:i2 + 1]
                if len(lows) == h and np.all(np.isfinite(lows)):
                    val[i] = float(lows.min() / cl[i] - 1.0)
        mae[h] = pd.Series(val, index=fr.index)
    return d, fwd, mae


def bootstrap_ci(a, b, n_iter=2000, seed=SEED):
    rng = np.random.default_rng(seed)
    a = np.asarray(a, dtype=float)
    b = np.asarray(b, dtype=float)
    if len(a) == 0 or len(b) == 0:
        return np.nan, np.nan
    spread = a.mean() - b.mean()
    diffs = np.empty(n_iter)
    na, nb = len(a), len(b)
    for k in range(n_iter):
        sa = a[rng.integers(0, na, size=na)]
        sb = b[rng.integers(0, nb, size=nb)]
        diffs[k] = sa.mean() - sb.mean()
    return float(np.percentile(diffs, 2.5) - (diffs.mean() - spread)), \
        float(np.percentile(diffs, 97.5) - (diffs.mean() - spread))


def event_table(d, fwd, mae):
    from scipy import stats as st
    states = [
        ("pct_rv20_exp", "rv20_expanding_pct"),
        ("pct_rv20_rol", "rv20_rolling252_pct"),
        ("pct_chg_exp", "rv20_1d_change_pct"),
        ("pct_ratio520_exp", "ratio_rv5_rv20_pct"),
        ("pct_ratio2060_exp", "ratio_rv20_rv60_pct"),
    ]
    rows = []
    for col, sname in states:
        p = d[col]
        for pname, (p0, p1) in PERIODS.items():
            mask = pd.Series(True, index=d.index)
            if p0:
                mask &= d.index >= p0
            if p1:
                mask &= d.index <= p1
            psub = p[mask]
            for h in HORIZONS:
                fv = fwd[h][mask]
                mv = mae[h][mask]
                q1m = (psub < 0.2) & fv.notna() & np.isfinite(p)
                q5m = (psub >= 0.8) & fv.notna() & np.isfinite(p)
                q1 = fv[q1m].to_numpy()
                q5 = fv[q5m].to_numpy()
                m1 = mv[q1m].to_numpy()
                m5 = mv[q5m].to_numpy()
                if len(q1) < 5 or len(q5) < 5:
                    rows.append(dict(state=sname, period=pname, horizon=h,
                                     n_q1=int(len(q1)), n_q5=int(len(q5)),
                                     mean_q1=np.nan, mean_q5=np.nan, med_q1=np.nan,
                                     med_q5=np.nan, win_q1=np.nan, win_q5=np.nan,
                                     mae_q1=np.nan, mae_q5=np.nan, spread=np.nan,
                                     tstat=np.nan, pval=np.nan, ci_lo=np.nan, ci_hi=np.nan))
                    continue
                tstat, pval = st.ttest_ind(q1, q5, equal_var=False)
                ci_lo, ci_hi = bootstrap_ci(q1, q5)
                rows.append(dict(
                    state=sname, period=pname, horizon=h,
                    n_q1=int(len(q1)), n_q5=int(len(q5)),
                    mean_q1=float(np.mean(q1)), mean_q5=float(np.mean(q5)),
                    med_q1=float(np.median(q1)), med_q5=float(np.median(q5)),
                    win_q1=float(np.mean(q1 > 0)), win_q5=float(np.mean(q5 > 0)),
                    mae_q1=float(np.nanmedian(m1)) if len(m1) else np.nan,
                    mae_q5=float(np.nanmedian(m5)) if len(m5) else np.nan,
                    spread=float(np.mean(q1) - np.mean(q5)),
                    tstat=float(tstat), pval=float(pval), ci_lo=float(ci_lo), ci_hi=float(ci_hi)))
    return pd.DataFrame(rows)


def main():
    df = load()
    fr = front_series(df)
    print(f"front bars: {len(fr)} ({fr.index[0].date()} ~ {fr.index[-1].date()})  "
          f"roll events: {int(fr['roll'].sum())}  contracts: {fr['ISU_CD'].nunique()}")
    d, fwd, mae = process(fr)
    n = len(fr)

    # 상태 기초
    stat_rows = []
    for col in ["rv5", "rv20", "rv60", "ratio_5_20", "ratio_20_60", "chg_rv20", "chg5_rv20"]:
        s = d[col]
        v = s.dropna()
        stat_rows.append(dict(key=col, n=int(len(v)), mean=float(v.mean()), median=float(v.median()),
                              std=float(v.std()), min=float(v.min()), max=float(v.max()),
                              p20=float(v.quantile(0.2)), p80=float(v.quantile(0.8))))
    stat_df = pd.DataFrame(stat_rows)

    et = event_table(d, fwd, mae)
    et = et.sort_values(["state", "period", "horizon"])

    stat_df = stat_df.rename(columns={"key": "state", "n": "v_n",
                                      "mean": "v_mean", "median": "v_median",
                                      "std": "v_std", "min": "v_min", "max": "v_max",
                                      "p20": "v_p20", "p80": "v_p80"})
    stat_df["table"] = "state_stats"
    stat_df["period"] = "ALL"
    stat_df["horizon"] = 0
    et["table"] = "event"
    full_cols = (["table", "state", "period", "horizon"]
                 + list(et.columns.drop(["table", "state", "period", "horizon"]))
                 + ["v_n", "v_mean", "v_median", "v_std", "v_min", "v_max", "v_p20", "v_p80"])
    for c in full_cols:
        if c not in stat_df.columns:
            stat_df[c] = None
    et_df = et
    for c in full_cols:
        if c not in et_df.columns:
            et_df[c] = None
    merged = pd.concat([stat_df[full_cols], et_df[full_cols]], ignore_index=True)
    merged.to_csv(OUTDIR / "futures-stage5-1-volatility-event-study.csv",
                  index=False, encoding="utf-8-sig")

    print("\n== 변동성 상태 기초 ==")
    print(stat_df.round(4).to_string(index=False))
    print("\n== event-study (Q1=하단20%, Q5=상단20%, spread=Q1-Q5, *: p<0.05) ==")
    pd.set_option("display.width", 240)
    view = et.copy()
    view["star"] = view["pval"].apply(lambda p: "*" if (p == p and p < 0.05) else "")
    for s in et["state"].unique():
        print(f"\n-- {s} --")
        sub = view[view["state"] == s][
            ["period", "horizon", "n_q1", "n_q5", "mean_q1", "mean_q5",
             "win_q1", "win_q5", "mae_q1", "mae_q5", "spread", "tstat", "pval", "ci_lo", "ci_hi", "star"]]
        print(sub.round(4).to_string(index=False))

    import json
    detail = {"n_bars": int(n), "start": str(fr.index[0].date()), "end": str(fr.index[-1].date()),
              "roll_events": int(fr["roll"].sum()), "contracts": int(fr["ISU_CD"].nunique()),
              "state_stats": stat_df.astype(str).to_dict(orient="records"),
              "event": et.astype(str).to_dict(orient="records")}
    (OUTDIR / "futures-stage5-1-volatility-event-study.json").write_text(
        json.dumps(detail, ensure_ascii=False, indent=2), encoding="utf-8")
    print("\n저장: futures-stage5-1-volatility-event-study.csv / .json")


if __name__ == "__main__":
    main()