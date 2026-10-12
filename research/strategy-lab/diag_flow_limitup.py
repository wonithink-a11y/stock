"""수급처별(외국인·기관·개인) 순매수 강도 5분위 → 5일 안 +15% 도달·5일 초과, 그리고 상한가 마감 다음 날 — 사후 기술(EXPLORATORY).

    python research/strategy-lab/diag_flow_limitup.py   # 표준 출력. 결과 정리: findings/flow-limitup-2026-10.md
"""
import sys, json, gzip, glob
import numpy as np, pandas as pd
sys.path.insert(0, r"C:\Users\User\projects\stock\research\strategy-lab")
import combined_rank_model as crm
P = pd.read_parquet(crm.CACHE / "panel.parquet", columns=["t", "tj", "ret5", "exc5", "trd5", "r1", "r5"])
S = pd.read_parquet(crm.CACHE / "supply.parquet")
meta = json.load(open(crm.CACHE / "meta.json"))
years = np.array(meta["years"])
dates, tickers, C, O, Hh, L, V, common, isdel = crm.load_dense()
# 5일 안 고가 +15% 도달(진입 = t+1 시가)
D, T = C.shape
entry = np.full((D, T), np.nan); entry[:-1] = O[1:]
mx = np.full((D, T), np.nan)
for k in range(1, 6):
    Hk = np.full((D, T), np.nan); Hk[:-k] = Hh[k:]
    mx = np.fmax(mx, Hk)
y = (mx / entry - 1) >= 0.15
t, tj = P.t.to_numpy(), P.tj.to_numpy()
P["y"] = y[t, tj]
for c in ["fnet5", "inet5", "pnet1", "fnet1", "inet1", "fnet20"]:
    P[c] = S[c].to_numpy()
P["pnet5"] = np.nan
X = P[P.trd5 & (years[t] >= 2016) & S["has"].to_numpy()].copy()
X["yr"] = years[X.t.to_numpy()]
print("행", len(X), "기본 5일 내 +15% 확률", f"{X.y.mean():.2%}", "평균 5일 초과", f"{X.exc5.mean()*1e4:+.1f}bp")
out = {}
for c, nm in [("fnet5", "외국인 5일"), ("inet5", "기관 5일"), ("fnet20", "외국인 20일"), ("pnet1", "개인 1일"), ("fnet1", "외국인 1일"), ("inet1", "기관 1일")]:
    X["q"] = X.groupby("t")[c].transform(lambda s: pd.qcut(s.rank(method="first"), 5, labels=False) if s.notna().sum() >= 50 else np.nan)
    g = X.groupby("q").agg(P15=("y", "mean"), exc5=("exc5", "mean"), n=("y", "size"))
    per = X.groupby(["q", pd.cut(X.yr, [2015, 2023, 2024, 2026], labels=["16~23", "24", "25~"])], observed=True).exc5.mean().unstack()
    print(f"\n[{nm} 순매수/20일 평균 거래대금, 하위→상위 5분위]")
    print(pd.concat([g.assign(P15=(g.P15 * 100).round(2), exc5=(g.exc5 * 1e4).round(1)), (per * 1e4).round(1)], axis=1).to_string())
# 개인 순매수 vs 외국인+기관 조합: 외국인·기관 동반 순매수 & 개인 순매도
X["combo"] = np.select([(X.fnet5 > 0) & (X.inet5 > 0), (X.fnet5 < 0) & (X.inet5 < 0)], ["외·기 동반 매수", "외·기 동반 매도"], "엇갈림")
print("\n[외국인·기관 5일 동반]"); print(X.groupby("combo").agg(P15=("y", "mean"), exc5=("exc5", "mean"), n=("y", "size")).assign(P15=lambda d: (d.P15 * 100).round(2), exc5=lambda d: (d.exc5 * 1e4).round(1)).to_string())

# 상한가 따라잡기: 일별 krx-daily-ext(폐지 포함) — 종가 ≥ +29.5%
fs = sorted(glob.glob(str(crm.HERE / "data" / "krx-daily-ext" / "20*.parquet")))
e = pd.concat([pd.read_parquet(f, columns=["BAS_DD", "ISU_CD", "FLUC_RT", "MKTCAP"]) for f in fs], ignore_index=True)
e = e[e.ISU_CD.str.endswith("0")]
e["r"] = pd.to_numeric(e.FLUC_RT, errors="coerce") / 100
e = e.sort_values(["ISU_CD", "BAS_DD"]); g = e.groupby("ISU_CD")
e["n1"] = g.r.shift(-1); e["n5"] = np.expm1(g.r.transform(lambda s: np.log1p(s.clip(-0.31, 0.31)).shift(-1).rolling(5).sum().shift(-4)))
e["prev_r"] = g.r.shift(1)
lu = e[(e.r >= 0.295) & (e.BAS_DD >= "20160101")].copy()
lu["yr"] = lu.BAS_DD.str[:4].astype(int)
lu["streak"] = np.where(lu.prev_r >= 0.295, "연속 상한가(2일째↑)", "첫 상한가")
lu["cap"] = pd.cut(lu.MKTCAP, [0, 1e11, 3e11, 1e12, 1e15], labels=["1000억↓", "1000~3000억", "3000억~1조", "1조↑"])
print(f"\n[상한가 마감 {len(lu):,}건 → 다음 날 종가 수익(종가 매수)·5일]")
for k in ["streak", "cap"]:
    print(lu.groupby(k, observed=True).agg(n=("n1", "size"), next_mean=("n1", "mean"), next_med=("n1", "median"), win=("n1", lambda s: (s > 0).mean()), d5_mean=("n5", "mean"), d5_med=("n5", "median")).assign(
        next_mean=lambda d: (d.next_mean * 100).round(2), next_med=lambda d: (d.next_med * 100).round(2), win=lambda d: (d.win * 100).round(0), d5_mean=lambda d: (d.d5_mean * 100).round(2), d5_med=lambda d: (d.d5_med * 100).round(2)).to_string())
print(lu.groupby(pd.cut(lu.yr, [2015, 2019, 2023, 2024, 2026], labels=["16~19", "20~23", "24", "25~"]), observed=True).n1.agg(["size", "mean", "median"]).mul([1, 100, 100]).round(2).to_string())
