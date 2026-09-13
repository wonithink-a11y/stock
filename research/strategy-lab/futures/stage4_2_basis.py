# -*- coding: utf-8 -*-
"""Stage 4-2: KOSPI200 선물 일봉 Basis 특성 분석 (READ-ONLY, 전략/백테스트 없음).

- 원천: research/strategy-lab/.cache/kospi200_daily/ (Stage 3-2 기존 데이터, 새 수집 금지)
- 사용 필드: TDD_CLSPRC(선물), SPOT_PRC(현물), ACC_TRDVOL, ACC_OPNINT_QTY, BAS_DD(날짜)
- front 계약: 날짜별 최대거래량 주간 계약 (Stage 3-2 관례)
- basis = close - SPOT_PRC (절대), basis% = basis/SPOT_PRC, dbasis = 전일대비(동일계약만)
- 계약 교체(롤) 별도 식별: ISU_CD 변경일 flag 셋, dbasis는 동일계약 연속에서만 정의
- 미래수익률 1/5/20일: 동일계약이 t+h 날짜에도 존재할 때만 (롤 급식 배제)
- 분위수: 과거 정보만으로 5분위 경계 생성(누적expanding / 252일 rolling), 주/보조
- 판정: A 명확·일관 / B 약한 / C 없음 / D 데이터·롤 문제로 판단불가
"""
from pathlib import Path

import numpy as np
import pandas as pd

REPO = Path(r"C:\Users\User\projects\stock")
CACHE = REPO / "research" / "strategy-lab" / ".cache" / "kospi200_daily"
OUTDIR = REPO / "research" / "strategy-lab" / "futures"
HORIZONS = [1, 5, 20]


def load():
    df = pd.concat([pd.read_parquet(p) for p in sorted(CACHE.glob("kospi200_*.parquet"))],
                   ignore_index=True)
    df = df[df["ISU_NM"].str.contains("주간", na=False)].copy()
    for f in ["TDD_CLSPRC", "SPOT_PRC", "ACC_TRDVOL", "ACC_OPNINT_QTY"]:
        df[f] = pd.to_numeric(df[f], errors="coerce")
    df["date"] = pd.to_datetime(df["BAS_DD"], format="%Y%m%d")
    return df.sort_values("date")


def front_series(df):
    fr = df.sort_values("ACC_TRDVOL", ascending=False).groupby("date").first().sort_index()
    fr["roll"] = (fr["ISU_CD"] != fr["ISU_CD"].shift(1)).fillna(True)
    return fr


def same_contract_ret(fr, h):
    """동일계약 기준 t->t+h 수익률. t+h에도 같은 ISU_CD가 존재할 때만 정의."""
    idx = fr.index.to_numpy()
    cd = fr["ISU_CD"].to_numpy()
    cl = fr["TDD_CLSPRC"].to_numpy(dtype=float)
    m = {}
    for i, c in enumerate(cd):
        i2 = i + h
        m[int(i)] = (cl[i2] / cl[i] - 1.0) if (i2 < len(cd) and c == cd[i2]
                                              and np.isfinite(cl[i]) and np.isfinite(cl[i2])) else np.nan
    return pd.Series([m[int(i)] for i in range(len(cd))], index=idx)


def main():
    df = load()
    fr = front_series(df)
    cl = fr["TDD_CLSPRC"].to_numpy(dtype=float)
    sp = fr["SPOT_PRC"].to_numpy(dtype=float)
    basis = pd.Series(cl - sp, index=fr.index, name="basis")
    bpct = pd.Series((cl - sp) / sp, index=fr.index, name="basis_pct")
    same_cd = (fr["ISU_CD"] != fr["ISU_CD"].shift(1)).fillna(True).to_numpy(bool)
    n = len(fr)
    rows = []
    for i in range(n):
        if i == 0:
            rows.append(np.nan)
            continue
        rows.append((basis.iloc[i] - basis.iloc[i - 1]) if (not same_cd[i]) else np.nan)
    db = pd.Series(rows, index=fr.index, name="dbasis")

    # ---- 1. 특성 기초 통계 ----
    stats = {
        "basis_mean": basis.mean(), "basis_median": basis.median(), "basis_std": basis.std(),
        "basis_pct_mean": bpct.mean(), "basis_pct_median": bpct.median(), "basis_pct_std": bpct.std(),
        "dbasis_mean": db.mean(), "dbasis_std": db.std(),
    }

    # ---- 2. 연도별 분포 ----
    yb = pd.DataFrame({"basis": basis, "basis_pct": bpct, "dbasis": db, "ret5": same_contract_ret(fr, 5)})
    yb["year"] = yb.index.year
    yearly = yb.groupby("year").agg(
        n=("basis", "size"),
        basis_mean=("basis", "mean"), basis_med=("basis", "median"), basis_std=("basis", "std"),
        basis_pct_mean=("basis_pct", "mean"), basis_pct_med=("basis_pct", "median"),
        dbasis_mean=("dbasis", "mean")).round(4)

    # ---- 3. 상승장/하락장별 분포 (과거 252일 현물수익률 부호로 레짐 정의) ----
    spot = yb["ret5"].index.to_series(index=yb.index)  # placeholder
    sp_ret = fr["SPOT_PRC"].pct_change(252)
    regime = pd.Series(np.where(sp_ret > 0, "상승장", "하락장"), index=fr.index)
    regime.loc[sp_ret.isna()] = np.nan
    reg = pd.DataFrame({"basis": basis, "basis_pct": bpct, "dbasis": db, "regime": regime}).dropna()
    regsum = reg.groupby("regime").agg(
        n=("basis", "size"), basis_mean=("basis", "mean"), basis_med=("basis", "median"),
        basis_std=("basis", "std"), basis_pct_mean=("basis_pct", "mean"),
        basis_pct_med=("basis_pct", "median")).round(4)

    # ---- 4. 자기상관 (basis 수준, dbasis) ----
    def acf_series(s, maxlag):
        s = s.dropna()
        s = s - s.mean()
        v0 = (s * s).sum()
        out = []
        for l in range(1, maxlag + 1):
            num = (s[s.index >= s.index[l]] * pd.Series(s.to_numpy()[:-l], index=s.index[l:])).sum()
            out.append(num / v0)
        return out

    acf_b = acf_series(basis, 20)
    acf_db = acf_series(db, 20)

    # ---- 5/6/7. 미래수익률 + 분위수(과거 정보만) ----
    # 분위수 경계: (a) 누적확장(최소 252 obs), (b) 252일 rolling
    for name, thr_series in [("expanding", None), ("rolling252", None)]:
        pass
    fwd = {}
    for h in HORIZONS:
        fwd[h] = same_contract_ret(fr, h)

    def expand_qt(s_hist):
        return np.quantile(s_hist, [0.2, 0.4, 0.6, 0.8])

    quintiles = {}
    basis_arr = basis.to_numpy()
    for h in HORIZONS:
        fv = fwd[h].to_numpy()
        q = np.full(n, np.nan)
        hist = []
        for i in range(n):
            if i == 0:
                q[i] = np.nan
                hist.append(basis_arr[i])
                continue
            hist.append(basis_arr[i - 1])  # t-1까지의 과거만
            if len(hist) < 252:
                q[i] = np.nan
                continue
            qs = np.quantile(hist, [0.2, 0.4, 0.6, 0.8])
            q[i] = int(np.digitize(basis_arr[i], qs, right=True)) + 1
        quintiles[h] = pd.DataFrame({"q": q, "fwd": fv}, index=fr.index)

    # 수익률 기반 (과거분위수 조합)
    qsummary = {}
    for h in HORIZONS:
        x = quintiles[h].dropna().copy()
        x["q"] = x["q"].astype(int)
        g = x.groupby("q")["fwd"].agg(["mean", "median", "std", "size"]).reindex([1, 2, 3, 4, 5])
        qsummary[h] = g.round(5)

    # 롤오버 경계 인근 분위수 견고성: 롤 직후 5일 제외 버전도 계산
    roll_mask = pd.Series(False, index=fr.index)
    fr_roll = fr["roll"].astype(bool)
    for k in range(1, 6):
        roll_mask |= fr_roll.shift(k).fillna(False)
    qsummary_drop5 = {}
    for h in HORIZONS:
        x = quintiles[h].loc[~roll_mask].dropna().copy()
        x["q"] = x["q"].astype(int)
        qsummary_drop5[h] = x.groupby("q")["fwd"].agg(["mean", "median", "std", "size"]).reindex([1, 2, 3, 4, 5]).round(5)

    # 전일대비 basis 변화(상승/하락)와 이후 수익률 교차
    db_up = db > 0
    xstat = {}
    for h in HORIZONS:
        m_up = fwd[h][db_up].mean(skipna=True)
        m_dn = fwd[h][db == 0 | (db < 0)].mean(skipna=True)
        xstat[h] = {"fwd_up": m_up, "fwd_down": m_dn, "n_up": int(db_up.sum()),
                    "n_down": int((db < 0).sum())}

    # ---- 출력 ----
    fmt = {"나": None}
    print("== 기본 통계 ==")
    for k, v in stats.items():
        print(f"{k}: {v:.5g}")
    print("\n== 연도별 ==")
    print(yearly.to_string())
    print("\n== 레짐별 ==")
    print(regsum.to_string())
    print("\n== 자기상관 (lag 1/5/10/20) ==")
    print("basis :", [round(acf_b[i - 1], 4) for i in [1, 5, 10, 20]])
    print("dbasis:", [round(acf_db[i - 1], 4) for i in [1, 5, 10, 20]])
    print("\n== 분위수별 이후 선물수익률 (expanding 과거분위수, 평균) ==")
    def fmt_q(s, h):
        return "  ".join([f"Q{k}={s[h].loc[k]['mean']:.5f}" for k in [1, 2, 3, 4, 5]])
    for h in HORIZONS:
        print(f"h={h:2d}  {fmt_q(qsummary, h)}")
    print("\n== 롤 직후 5일 제외 견고성 ==")
    for h in HORIZONS:
        print(f"h={h:2d}  {fmt_q(qsummary_drop5, h)}")
    print("\n== dbasis 상승/하락 후 수익률 ==")
    for h in HORIZONS:
        print(f"h={h:2d}  up={xstat[h]['fwd_up']:.5f} down={xstat[h]['fwd_down']:.5f}")

    # CSV 저장 (long format)
    out_rows = []
    for rec in ["기초"]:
        pass
    for k, v in stats.items():
        out_rows.append({"table": "stat", "key": k, "value": round(float(v), 6)})
    for yr, r in yearly.iterrows():
        for col in ["n", "basis_mean", "basis_std", "basis_pct_mean"]:
            out_rows.append({"table": "yearly", "key": int(yr), "metric": col, "value": r[col]})
    for rg, r in regsum.iterrows():
        for col in ["n", "basis_mean", "basis_std", "basis_pct_mean"]:
            out_rows.append({"table": "regime", "key": str(rg), "metric": col, "value": r[col]})
    for i, l in enumerate([1, 5, 10, 20]):
        out_rows.append({"table": "acf", "key": f"lag{l}", "metric": "basis", "value": acf_b[i]})
        out_rows.append({"table": "acf", "key": f"lag{l}", "metric": "dbasis", "value": acf_db[i]})
    for h in HORIZONS:
        for k in [1, 2, 3, 4, 5]:
            r = qsummary[h].loc[k]
            out_rows.append({"table": f"quintile_h{h}_exp", "key": int(k), "metric": "mean",
                             "value": r["mean"]})
            out_rows.append({"table": f"quintile_h{h}_exp", "key": int(k), "metric": "std",
                             "value": r["std"]})
            out_rows.append({"table": f"quintile_h{h}_exp", "key": int(k), "metric": "n",
                             "value": r["size"]})
        for k in [1, 2, 3, 4, 5]:
            r = qsummary_drop5[h].loc[k]
            out_rows.append({"table": f"quintile_h{h}_drop5", "key": int(k), "metric": "mean",
                             "value": r["mean"]})
    for h in HORIZONS:
        for m, v in xstat[h].items():
            out_rows.append({"table": "dbasis_fwd", "key": int(h), "metric": m, "value": v})
    out = pd.DataFrame(out_rows)
    out.to_csv(OUTDIR / "futures-stage4-2-basis.csv", index=False, encoding="utf-8-sig")

    # JSON 상세 (수작업 판정용)
    import json
    detail = {"stats": {"k": float(v) for k, v in stats.items()},
              "yearly": yearly.astype(str).to_dict(orient="index"),
              "regime": regsum.to_dict(orient="index"),
              "acf": {"basis": acf_b, "dbasis": acf_db},
              "quintile_exp": {str(h): qsummary[h].to_dict(orient="index") for h in HORIZONS},
              "quintile_drop5": {str(h): qsummary_drop5[h].to_dict(orient="index") for h in HORIZONS},
              "dbasis_fwd": xstat}
    (OUTDIR / "futures-stage4-2-basis.json").write_text(
        json.dumps(detail, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    print("\n저장: futures-stage4-2-basis.csv / .json")


if __name__ == "__main__":
    main()