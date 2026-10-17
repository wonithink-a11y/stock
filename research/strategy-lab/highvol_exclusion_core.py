"""고변동 배제 코어 — 사전등록 findings/highvol-exclusion-core-preregistration-2026-10.md 그대로.

X1 = 유동 등가중에서 rv60 상위 10% 제외 · X2 = 20% 제외 (비교: 유동 등가중)
X3 = 시총 상위 300 시총가중에서 300 안 rv60 상위 10% 제외 (비교: 300 시총가중)
자료: KRX 일별 전 종목(폐지 포함 PIT) 2010-01~. 네트워크 없음.
실행: python research/strategy-lab/highvol_exclusion_core.py [count]   # count = 표본 크기만(수익률 없음)
산출: findings/highvol-exclusion-core-results-2026-10.{md,json}
"""
import glob
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
D = HERE / "data"
OUT = HERE / "findings" / "highvol-exclusion-core-results-2026-10"
COST = 33.5  # bp, KR 연속 왕복
NAME_EXCL = "스팩|기업인수목적|리츠|부동산투자|인프라|선박"
REGISTERED = "registered" in sys.argv
if REGISTERED:
    OUT = OUT.with_name(OUT.name + "-registered-rule")
CELLS = {"X1": ("ew", 0.10), "X2": ("ew", 0.20), "X3": ("cap300", 0.10)}
ERAS = (("2016~23", "2016-01", "2023-12"), ("2024", "2024-01", "2024-12"), ("2025~", "2025-01", "2099-12"))


def split(m):  # m = 보유 달 'YYYY-MM'
    if m < "2016-01":
        return "PRE"
    return "TRAIN" if m <= "2022-06" else ("VALID" if m <= "2023-12" else "TEST")


def load():
    fs = sorted(glob.glob(str(D / "krx-pbr-history/daily/*.parquet"))) + sorted(glob.glob(str(D / "krx-daily-ext/*.parquet")))
    d = pd.concat(pd.read_parquet(f, columns=["BAS_DD", "ISU_CD", "ISU_NM", "FLUC_RT", "ACC_TRDVAL", "MKTCAP"]) for f in fs)
    d = d[(d.ISU_CD.str[-1] == "0") & ~d.ISU_NM.str.contains(NAME_EXCL, regex=True)]
    d["r"] = pd.to_numeric(d.FLUC_RT, errors="coerce") / 100
    d = d.sort_values(["ISU_CD", "BAS_DD"])
    last_day = d.BAS_DD.max()
    last = d.groupby("ISU_CD").BAS_DD.transform("max")
    tail_rank = d.groupby("ISU_CD").cumcount(ascending=False)  # 0 = 마지막 행
    delisted_tail = (last < last_day) & (tail_rank < 10)
    big = d.r.abs() > 0.30
    n_out = {"kept_delisting_tail": int((big & delisted_tail).sum()), "zeroed_data_error": int((big & ~delisted_tail).sum())}
    if REGISTERED:  # 사전등록 원안 — 감자 자리표시 가격(1원 → 67,000원)이 정리매매 예외로 남는다
        d.loc[big & ~delisted_tail, "r"] = 0.0
    else:  # 보정(결과 뒤, 결과 문서 §자료 보정): 가격제한폭 밖 행은 직전 거래일 시총 대비 시총 비율 — 감자·주식 수 변동을 반영
        mc_prev = d.MKTCAP.astype(float).where(d.ACC_TRDVAL > 0).groupby(d.ISU_CD).transform(lambda s: s.ffill().shift(1))
        mr = d.MKTCAP.astype(float) / mc_prev - 1
        n_out["mcap_ratio_used"] = int((big & mr.notna()).sum())
        n_out["changed_over_1pp"] = int((big & mr.notna() & ((mr - d.r).abs() > 0.01)).sum())
        d.loc[big, "r"] = mr[big].fillna(0.0)
    d["r"] = d.r.clip(lower=-1.0)
    R = d.pivot(index="BAS_DD", columns="ISU_CD", values="r")
    TV = d.pivot(index="BAS_DD", columns="ISU_CD", values="ACC_TRDVAL").astype(float)
    MC = d.pivot(index="BAS_DD", columns="ISU_CD", values="MKTCAP").astype(float)
    lastrow = d.groupby("ISU_CD").BAS_DD.max()
    delist_day = lastrow[lastrow < last_day]
    return R, TV, MC, delist_day, n_out


def features(R, TV):
    traded = TV > 0
    tv20 = TV.rolling(20, min_periods=20).mean()  # 행이 있는 날 기준(없는 날 NaN 이라 창이 끊기면 부적격)
    lr = np.log1p(R.where(traded))
    rv = pd.DataFrame(index=R.index, columns=R.columns, dtype=float)
    for c in R.columns:  # 거래 있는 행 60개
        s = lr[c].dropna()
        if len(s) >= 60:
            rv.loc[s.index, c] = s.rolling(60).std().values
    return traded, tv20, rv


def schedule(dates):
    s = pd.Series(dates, index=pd.to_datetime(dates))
    f = s.groupby(s.index.to_period("M")).max().tolist()  # 월 마지막 거래일
    pos = {x: i for i, x in enumerate(dates)}
    out = []
    for k in range(len(f) - 1):
        e0, e1 = pos[f[k]] + 1, pos[f[k + 1]] + 1
        if e1 < len(dates):
            out.append((f[k], dates[e0], dates[e1], f"{f[k + 1][:4]}-{f[k + 1][4:6]}"))  # 보유 구간의 대부분 = 다음 달
    return out


def eligible(fd, traded, tv20, rv, drop=None):
    ok = traded.loc[fd] & (tv20.loc[fd] >= 1e8) & rv.loc[fd].notna()
    if drop is not None:
        ok &= ~ok.index.isin(drop)
    return ok[ok].index


def targets(kind, q, fd, elig, rv, MC):
    if kind == "ew":
        u = elig
        w = pd.Series(1.0, index=u)
    else:
        u = MC.loc[fd, elig].nlargest(300).index
        w = MC.loc[fd, u].astype(float)
    pct = rv.loc[fd, u].rank(pct=True)
    keep = pct[pct <= 1 - q].index
    xw, bw = w[keep], w
    return xw / xw.sum(), bw / bw.sum(), u.difference(keep)


def run(R, TV, MC, traded, tv20, rv, sched, kind, q, drop=None, delist_day=None):
    """반환 DataFrame(month, gx, gb, tx, tb, nx, nb, excl_delist, keep_delist)."""
    Rf = R.fillna(0.0)
    hx, hb = pd.Series(dtype=float), pd.Series(dtype=float)  # 표류 비중(가치, 합 = 직전 체결 뒤 1 기준 성장)
    rows = []
    for fd, e0, e1, m in sched:
        elig = eligible(fd, traded, tv20, rv, drop)
        if len(elig) < 50:
            continue
        tx_, tb_, excl = targets(kind, q, fd, elig, rv, MC)
        rec = {"month": m}
        for name, tgt, h in (("x", tx_, hx), ("b", tb_, hb)):
            v = h / h.sum() if len(h) else h
            has_row = R.loc[e0].reindex(v.index).notna()
            live = v[has_row]  # 행 없음 = 현금(폐지 등)
            stuck = live[~traded.loc[e0].reindex(live.index).fillna(False)]
            free = 1.0 - stuck.sum()
            tgt_e = tgt[traded.loc[e0].reindex(tgt.index).fillna(False)]  # 체결일에 못 사는 목표는 뺀다
            tgt_e = tgt_e / tgt_e.sum() * free
            old = live.drop(stuck.index)
            ix = tgt_e.index.union(old.index)
            turn = float((tgt_e.reindex(ix, fill_value=0) - old.reindex(ix, fill_value=0)).abs().sum())
            new = pd.concat([tgt_e, stuck]).groupby(level=0).sum()
            days = R.index[(R.index > e0) & (R.index <= e1)]
            g = (1 + Rf.loc[days, new.index]).prod()
            end = new * g
            gross = float(end.sum()) - 1
            cost = turn / 2 * COST / 1e4
            rec["g" + name], rec["t" + name], rec["n" + name] = gross, turn, (1 - cost) * (1 + gross) - 1
            if name == "x":
                hx = end
            else:
                hb = end
        if delist_day is not None:
            dd = delist_day[(delist_day > e0) & (delist_day <= e1)].index
            kept = tx_.index
            rec["excl_delist"] = float(np.isin(excl, dd).mean()) if len(excl) else np.nan
            rec["keep_delist"] = float(np.isin(kept, dd).mean())
        rows.append(rec)
    df = pd.DataFrame(rows).set_index("month")
    df["gex"], df["nex"] = df.gx - df.gb, df.nx - df.nb
    return df


def tstat(x):
    x = np.asarray(x, float)
    return float(x.mean() / (x.std(ddof=1) / np.sqrt(len(x)))) if len(x) > 2 and x.std(ddof=1) > 0 else float("nan")


def curve(r):
    c = (1 + r).cumprod()
    yrs = len(r) / 12
    return {"cagr_pct": round(float(c.iloc[-1] ** (1 / yrs) - 1) * 100, 2), "sharpe": round(float(r.mean() / r.std() * np.sqrt(12)), 2),
            "mdd_pct": round(float((c / c.cummax() - 1).min()) * 100, 1)}


def summarize(df, rng):
    sp = df.index.map(split)
    by = {}
    for k in ("PRE", "TRAIN", "VALID", "TEST"):
        s = df[sp == k]
        by[k] = {"months": len(s), "gex_bp": round(s.gex.mean() * 1e4, 1), "gex_t": round(tstat(s.gex), 2),
                 "nex_bp": round(s.nex.mean() * 1e4, 1), "nex_t": round(tstat(s.nex), 2)}
    oos = df[sp.isin(["VALID", "TEST"])]
    boot = [rng.choice(oos.gex.values, len(oos)).mean() for _ in range(2000)]
    dturn = (oos.tx - oos.tb).mean()
    eras = {}
    for name, a, b in ERAS:
        s = df[(df.index >= a) & (df.index <= b)]
        eras[name] = {"months": len(s), "nex_bp": round(s.nex.mean() * 1e4, 1), "nex_t": round(tstat(s.nex), 2), "pos_months_pct": round(float((s.nex > 0).mean()) * 100)}
    main = df[sp != "PRE"]
    ex = (1 + main.nex).cumprod()
    yr = lambda c: round(float(main[c].groupby(main.index.str[:4]).sum().mean() / 2) * 100, 1)  # 연 단방향 회전율 %
    return {"by_split": by, "eras": eras,
            "oos": {"months": len(oos), "gex_bp": round(oos.gex.mean() * 1e4, 1),
                    "gex_ci95_bp": [round(float(np.percentile(boot, 2.5)) * 1e4, 1), round(float(np.percentile(boot, 97.5)) * 1e4, 1)],
                    "nex_bp": round(oos.nex.mean() * 1e4, 1), "nex_t": round(tstat(oos.nex), 2),
                    "breakeven_bp": (round(float(oos.gex.mean() / (dturn / 2)) * 1e4, 1) if dturn > 0 else "비용 우위")},
            "turnover_oneway_pct_per_year": {"port": yr("tx"), "bench": yr("tb")},
            "port_net_2016": curve(main.nx), "bench_net_2016": curve(main.nb),
            "excess_cum_mdd_pct": round(float((ex / ex.cummax() - 1).min()) * 100, 1),
            "excess_cum_2016_pct": round(float(ex.iloc[-1] - 1) * 100, 1),
            "delist_rate_next_period": {"excluded_pct": round(float(df.excl_delist.mean()) * 100, 3) if "excl_delist" in df else None,
                                        "kept_pct": round(float(df.keep_delist.mean()) * 100, 3) if "keep_delist" in df else None},
            "year_nex_bp": {y: round(float(v) * 1e4, 1) for y, v in df.nex.groupby(df.index.str[:4]).mean().items()}}


def verdict(s, floor):
    b = s["by_split"]
    if min(b["TRAIN"]["months"], b["VALID"]["months"], b["TEST"]["months"]) < 12:
        return "INCONCLUSIVE"
    t = b["TRAIN"]["gex_t"]
    if t <= -floor:
        return "REJECT(반대 방향)"
    if not (t >= floor and b["VALID"]["gex_bp"] > 0 and b["TEST"]["gex_bp"] > 0):
        return "REJECT"
    if s["oos"]["nex_bp"] <= 0:
        return "INFORMATION"
    return "ROBUST" if s["oos"]["nex_t"] >= 2 else "ECONOMIC"


def main():
    R, TV, MC, delist_day, n_out = load()
    traded, tv20, rv = features(R, TV)
    sched = schedule(list(R.index))
    if len(sys.argv) > 1 and sys.argv[1] == "count":
        ns = [len(eligible(fd, traded, tv20, rv)) for fd, *_ in sched]
        print(json.dumps({"tickers": R.shape[1], "delisted": len(delist_day), "periods": len(sched), "first": sched[0][3], "last": sched[-1][3],
                          "eligible_min_med_max": [min(ns), int(np.median(ns)), max(ns)], "outliers": n_out}, ensure_ascii=False))
        return
    from diag_regime_semis import semi_set
    semi = semi_set(pd.read_parquet(D / "factor-panel/kr-monthly-v1.parquet", columns=["ticker", "sector"]))
    rng = np.random.default_rng(20261017)
    res, dfs = {}, {}
    for c, (kind, q) in CELLS.items():
        dfs[c] = run(R, TV, MC, traded, tv20, rv, sched, kind, q, delist_day=delist_day)
        res[c] = summarize(dfs[c], rng)
        semi_df = run(R, TV, MC, traded, tv20, rv, sched, kind, q, drop=semi)
        res[c]["semis_excluded_eras"] = summarize(semi_df, rng)["eras"]
        print(c, res[c]["by_split"], flush=True)
    # 바닥선: TRAIN gross 초과에 공통 월 부호 반전
    tr = pd.concat({c: dfs[c].gex[dfs[c].index.map(split) == "TRAIN"] for c in CELLS}, axis=1).dropna()
    mx = []
    for _ in range(1000):
        sgn = rng.choice([-1.0, 1.0], len(tr))[:, None]
        mx.append(max(abs(tstat(col)) for col in (tr.values * sgn).T))
    floor = round(float(np.percentile(mx, 95)), 2)
    for c in CELLS:
        res[c]["verdict"] = verdict(res[c], floor)
    out = {"floor": floor, "outliers": n_out, "periods": [sched[0][3], sched[-1][3]], "cells": res}
    OUT.with_suffix(".json").write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
    print(json.dumps({"floor": floor, **{c: res[c]["verdict"] for c in CELLS}}, ensure_ascii=False))


if __name__ == "__main__":
    main()
