#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""미국 S&P500 저PBR 재현 시험 — 사전등록 findings/us-pbr-revalidation-preregistration-2026-09.md(동결 a881dc18) 그대로 1회.

  python research/strategy-lab/run_us_pbr_revalidation.py --selftest   # 합성 데이터로 계산 확인(네트워크·실데이터 없음)
  python research/strategy-lab/run_us_pbr_revalidation.py              # 실행 → reports/2026-09-us-pbr/results.json + 표 출력

구현 결정(사전등록 §1 의 '월 수익률' 정의를 데이터에 맞춘 것 — 신호·문턱·구간과 무관, 실행 전 고정):
  - 야후·Tiingo 가 분사를 **가격 조정 계수(비정수 splits)와 배당을 같은 날 둘 다** 적은 4건(DHR 2016-07-05 · K 2023-10-02 ·
    JEF 2019-09-27 · AIV 2019-02-21)은 그날 배당을 버린다 — 분사 가치는 이미 조정 종가에 들어 있어 이중 계산이 된다
    (DHR 은 하루 +35% 가짜 수익). 판단은 us_account_map.is_clean_split 과 같은 규칙.
"""
import argparse
import hashlib
import json
import math
import sys
from pathlib import Path

import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import us_account_map as M  # noqa: E402

PIT = HERE / "data" / "us-pit"
OUT = HERE / "reports" / "2026-09-us-pbr"
FORM_FIRST, FORM_LAST = "2016-01-01", "2026-07-31"
HALF = "2021-01-01"
CELLS = {"D": 0.10, "Q": 0.20}
COST_RT = 10e-4
N_RAND, SEED = 1000, 20260926
NW_LAG = 3
GATE_UNIV, GATE_D, GATE_BAD_MONTHS = 400, 30, 12


def daily_index(px):
    """(ticker,start) 별 총수익 지수. 분사 이중 계산일의 배당은 버린다."""
    px = px.sort_values(["ticker", "start", "date"]).copy()
    drop = set()
    for (sym, src), g in px[px["dividend"] > 0].groupby(["price_symbol", "source"]):
        ev = {d for d, r in M.split_events(sym, src) if not M.is_clean_split(r)}
        drop |= {(sym, src, d) for d in g["date"] if d in ev}
    if drop:
        m = [(a, b, c) in drop for a, b, c in zip(px["price_symbol"], px["source"], px["date"])]
        px.loc[m, "dividend"] = 0.0
    prev = px.groupby(["ticker", "start"])["close"].shift()
    r = ((px["close"] + px["dividend"].fillna(0)) / prev - 1).fillna(0.0)
    px["idx"] = (1 + r).groupby([px["ticker"], px["start"]]).cumprod()
    return px[["ticker", "start", "date", "idx"]], sorted(drop)


def nw_t(x, lag=NW_LAG):
    x = np.asarray(x, float)
    n = len(x)
    e = x - x.mean()
    s = e @ e / n
    for L in range(1, lag + 1):
        s += 2 * (1 - L / (lag + 1)) * (e[L:] @ e[:-L]) / n
    return x.mean() / math.sqrt(s / n) if s > 0 else float("nan")


def cagr(r):
    r = np.asarray(r, float)
    return float(np.prod(1 + r) ** (12 / len(r)) - 1)


def mdd(r):
    c = np.cumprod(1 + np.asarray(r, float))
    return float((c / np.maximum.accumulate(c) - 1).min())


def sharpe(r):
    r = np.asarray(r, float)
    return float(r.mean() / r.std(ddof=1) * math.sqrt(12)) if r.std(ddof=1) > 0 else float("nan")


def build_months(fund, idxdf):
    """월별 유니버스와 (t, t1] 수익. 반환: 리스트 of dict(date, t1, univ DataFrame[ticker,start,cik,bm,mcap,ret])."""
    me = sorted(fund["date"].unique())
    idx = {k: g.set_index("date")["idx"] for k, g in idxdf.groupby(["ticker", "start"])}
    months, excl = [], []
    for i, t in enumerate(me[:-1]):
        if not (pd.Timestamp(FORM_FIRST) <= t <= pd.Timestamp(FORM_LAST)):
            continue
        t1 = me[i + 1]
        f = fund[(fund["date"] == t) & fund["close"].notna()]
        n_all = len(f)
        neg = int(((f["equity"] <= 0) & f["mcap"].notna()).sum())
        miss = int((f["equity"].isna() | f["mcap"].isna()).sum())
        u = f[(f["equity"] > 0) & f["mcap"].notna() & f["bm"].notna()].sort_values("ticker")
        before = len(u)
        u = u.drop_duplicates("cik", keep="first")
        dup = before - len(u)
        rets = []
        for r in u.itertuples():
            s = idx.get((r.ticker, r.start))
            if s is None or t not in s.index:
                rets.append(np.nan)
                continue
            a = s.loc[t]
            w = s[(s.index > t) & (s.index <= t1)]
            rets.append(float(w.iloc[-1] / a - 1) if len(w) else 0.0)
        u = u.assign(ret=rets)
        nan = int(u["ret"].isna().sum())
        u = u[u["ret"].notna()]
        months.append({"t": t, "t1": t1, "u": u[["ticker", "start", "cik", "bm", "mcap", "ret"]].reset_index(drop=True)})
        excl.append({"t": str(t.date()), "rows": n_all, "neg_equity": neg, "missing": miss, "dup_cik": dup, "no_price_at_t": nan})
    return months, excl


def cell_members(u, frac):
    n = math.ceil(frac * len(u))
    return u.sort_values(["bm", "ticker"], ascending=[False, True]).head(n)


def turnover(prev_w, prev_ret, new_members):
    """편도 교체 비율. prev_w: {key: 가중}, prev_ret: {key: 그 달 수익} → drift 후 가중과 새 EW 비교."""
    if prev_w is None:
        return 1.0
    grown = {k: w * (1 + prev_ret.get(k, 0.0)) for k, w in prev_w.items()}
    tot = sum(grown.values())
    drift = {k: v / tot for k, v in grown.items()} if tot > 0 else {}
    n = len(new_members)
    new = {k: 1 / n for k in new_members}
    keys = set(drift) | set(new)
    return 0.5 * sum(abs(new.get(k, 0) - drift.get(k, 0)) for k in keys)


def run_cells(months):
    res = {}
    ew = np.array([m["u"]["ret"].mean() for m in months])
    for name, frac in CELLS.items():
        ret, to, n = [], [], []
        prev_w = prev_r = None
        for m in months:
            c = cell_members(m["u"], frac)
            keys = list(zip(c["ticker"], c["start"]))
            to.append(turnover(prev_w, prev_r, keys))
            ret.append(c["ret"].mean())
            n.append(len(c))
            prev_w = {k: 1 / len(keys) for k in keys}
            prev_r = dict(zip(keys, c["ret"]))
        res[name] = {"ret": np.array(ret), "turnover": np.array(to), "n": np.array(n)}
    return ew, res


def random_floor(months, ew):
    rng = np.random.default_rng(SEED)
    rets = [m["u"]["ret"].to_numpy() for m in months]
    sizes = {k: [math.ceil(f * len(r)) for r in rets] for k, f in CELLS.items()}
    fam = []
    for _ in range(N_RAND):
        best = -1e9
        for k in CELLS:
            ex = [rng.choice(r, s, replace=False).mean() - e for r, s, e in zip(rets, sizes[k], ew)]
            best = max(best, float(np.mean(ex)))
        fam.append(best)
    return float(np.percentile(fam, 95))


def boot_ci(x, n=2000, seed=SEED):
    rng = np.random.default_rng(seed)
    x = np.asarray(x, float)
    b = [rng.choice(x, len(x), replace=True).mean() for _ in range(n)]
    return float(np.percentile(b, 2.5)), float(np.percentile(b, 97.5))


def summarize(dates, cell, ew, floor):
    ex = cell["ret"] - ew
    net = cell["ret"] - cell["turnover"] * COST_RT
    halves = {}
    for nm, sel in (("2016-2020", dates < pd.Timestamp(HALF)), ("2021-2026", dates >= pd.Timestamp(HALF))):
        halves[nm] = {"months": int(sel.sum()), "excess_bp": float(ex[sel].mean() * 1e4), "nw_t": nw_t(ex[sel])}
    yrs = pd.Series(ex, index=[d.year for d in dates]).groupby(level=0).sum()
    total = float(ex.sum())
    top_share = float(yrs.max() / total) if total > 0 else None
    t = nw_t(ex)
    lo, hi = boot_ci(ex)
    info = bool(ex.mean() >= floor and t >= 2.0)
    econ = bool(info and cagr(net) > cagr(ew))
    robust = bool(econ and all(h["excess_bp"] > 0 for h in halves.values()) and top_share is not None and top_share < 0.5)
    mto = float(cell["turnover"][1:].mean())
    return {
        "months": int(len(ex)), "avg_n": float(cell["n"].mean()), "excess_bp": float(ex.mean() * 1e4), "ci95_bp": [lo * 1e4, hi * 1e4],
        "nw_t": t, "floor_bp": floor * 1e4, "net_excess_bp": float((net - ew).mean() * 1e4),
        "breakeven_rt_bp": float(ex.mean() / mto * 1e4) if mto > 0 else None, "turnover": mto,
        "cagr": cagr(cell["ret"]), "cagr_net": cagr(net), "cagr_ew": cagr(ew), "sharpe": sharpe(cell["ret"]), "sharpe_ew": sharpe(ew),
        "mdd": mdd(cell["ret"]), "mdd_ew": mdd(ew), "halves": halves, "yearly_excess_bp": {int(k): float(v * 1e4) for k, v in yrs.items()},
        "top_year_share": top_share, "INFORMATION": info, "ECONOMIC": econ, "ROBUST": robust,
        "verdict": "KEEP" if robust else ("REJECT" if not info else "HOLD(ECONOMIC)" if econ else "HOLD(INFORMATION)"),
    }


def record_only(months, ew, dates):
    out = {}
    lo = np.array([m["u"].sort_values(["bm", "ticker"], ascending=[True, True]).head(math.ceil(0.1 * len(m["u"])))["ret"].mean() for m in months])
    d = np.array([cell_members(m["u"], 0.10)["ret"].mean() for m in months])
    out["high_pbr_decile_excess_bp"] = float((lo - ew).mean() * 1e4)
    out["D_minus_highpbr_bp"] = float((d - lo).mean() * 1e4)
    out["D_minus_highpbr_nw_t"] = nw_t(d - lo)
    cw = []
    for m in months:
        c = cell_members(m["u"], 0.10)
        cw.append(float((c["ret"] * c["mcap"]).sum() / c["mcap"].sum()))
    out["D_capweighted_excess_bp"] = float((np.array(cw) - ew).mean() * 1e4)
    try:
        mac = pd.read_parquet(HERE / "data" / "market-regime" / "macro_layer_daily_kr.parquet")
        s = mac["usTreasury10y"] if "date" not in mac.columns else mac.set_index("date")["usTreasury10y"]
        s.index = pd.to_datetime(s.index)
        s = s.dropna()
        dy = np.array([float(s[:m["t1"]].iloc[-1] - s[:m["t"]].iloc[-1]) for m in months])
        exd = d - ew
        out["rate"] = {"corr_excess_vs_d10y": float(np.corrcoef(exd, dy)[0, 1]),
                       "excess_up_months_bp": float(exd[dy > 0].mean() * 1e4), "excess_down_months_bp": float(exd[dy <= 0].mean() * 1e4),
                       "up_months": int((dy > 0).sum()), "down_months": int((dy <= 0).sum())}
    except Exception as e:  # 기록 전용 — 실패해도 판정과 무관
        out["rate"] = {"error": str(e)}
    snap = sorted((HERE / "data" / "us-universe" / "membership").glob("*.csv"))
    if snap:
        sec = pd.read_csv(snap[-1]).set_index("symbol")["sector"].to_dict()
        tk = [t for m in months for t in cell_members(m["u"], 0.10)["ticker"]]
        known = [sec[t] for t in tk if t in sec]
        out["D_financials_share_snapshot"] = {"known_rows": len(known), "total_rows": len(tk),
                                              "financials": float(np.mean([s == "Financials" for s in known])) if known else None}
    return out


def main():
    fund_p, px_p = PIT / "panel" / "fundamentals_monthly.parquet", PIT / "panel" / "prices.parquet"
    sha = {p.name: hashlib.sha256(p.read_bytes()).hexdigest()[:12] for p in (fund_p, px_p)}
    fund = pd.read_parquet(fund_p)
    idxdf, dropped = daily_index(pd.read_parquet(px_p))
    months, excl = build_months(fund, idxdf)
    dates = pd.to_datetime([m["t"] for m in months])
    univ = np.array([len(m["u"]) for m in months])
    ew, cells = run_cells(months)
    bad = int(((univ < GATE_UNIV) | (cells["D"]["n"] < GATE_D)).sum())
    floor = random_floor(months, ew)
    summ = {k: summarize(dates, v, ew, floor) for k, v in cells.items()}
    if bad > GATE_BAD_MONTHS:
        for v in summ.values():
            v["verdict"] = "INCONCLUSIVE(게이트)"
    res = {"prereg": "findings/us-pbr-revalidation-preregistration-2026-09.md (동결 a881dc18)", "inputs_sha256_12": sha,
           "months": len(months), "first": str(dates[0].date()), "last": str(dates[-1].date()),
           "universe_mean": float(univ.mean()), "universe_min": int(univ.min()), "gate_bad_months": bad,
           "dividends_dropped_spin_double": [(s, src, str(d.date())) for s, src, d in dropped],
           "ew": {"cagr": cagr(ew), "sharpe": sharpe(ew), "mdd": mdd(ew)}, "floor_bp": floor * 1e4, "cells": summ,
           "record_only": record_only(months, ew, dates), "exclusions_mean": pd.DataFrame(excl).drop(columns="t").mean().round(2).to_dict()}
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "results.json").write_text(json.dumps(res, ensure_ascii=False, indent=1, default=float), encoding="utf-8")
    print(json.dumps(res, ensure_ascii=False, indent=1, default=float))


def selftest():
    # 합성: 60개월 · 500종목, bm 이 높을수록 다음 달 +20bp 더 오르게 만든다 → 셀 D 초과가 양이어야 한다
    rng = np.random.default_rng(1)
    months = []
    for i in range(60):
        bm = rng.uniform(0.05, 2, 500)
        ret = rng.normal(0.01, 0.05, 500) + 0.002 * (bm > np.quantile(bm, 0.9))
        u = pd.DataFrame({"ticker": [f"T{j:03d}" for j in range(500)], "start": "2000", "cik": range(500), "bm": bm,
                          "mcap": rng.uniform(1e9, 1e11, 500), "ret": ret})
        months.append({"t": pd.Timestamp("2016-01-31") + pd.offsets.MonthEnd(i), "t1": None, "u": u})
    ew, cells = run_cells(months)
    assert cells["D"]["n"][0] == 50 and cells["Q"]["n"][0] == 100
    assert (cells["D"]["ret"] - ew).mean() > 0
    assert cells["D"]["turnover"][0] == 1.0 and 0.5 < cells["D"]["turnover"][1:].mean() <= 1.0   # 무작위 bm 이라 거의 전부 교체
    x = np.r_[np.ones(10), -np.ones(10)] * 0.01
    assert abs(nw_t(x)) < 1e-9
    assert abs(cagr([0.01] * 12) - (1.01 ** 12 - 1)) < 1e-12
    assert turnover({("A", "s"): 0.5, ("B", "s"): 0.5}, {("A", "s"): 0.0, ("B", "s"): 0.0}, [("A", "s"), ("C", "s")]) == 0.5
    print("run_us_pbr_revalidation selftest: 통과")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--selftest", action="store_true")
    a = ap.parse_args()
    selftest() if a.selftest else main()
