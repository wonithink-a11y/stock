#!/usr/bin/env python3
"""미국 애널리스트 목표가 신뢰도 Q1~Q4 — 사전등록 findings/us-price-target-reliability-preregistration-2026-10.md(d4a61764) 그대로.

입력(gitignore): data/us-price-targets/{targets.parquet, prices.parquet, splits.json} — collect_us_price_targets.py
          industry.json(반도체 제외 기록용, 없으면 yfinance 로 한 번 받는다)
출력: findings/us-price-target-reliability-results-2026-10.json (숫자만, 문서는 손으로 쓴다)
    python research/strategy-lab/run_us_price_target_reliability.py
    python research/strategy-lab/run_us_price_target_reliability.py --selftest
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
D = HERE / "data" / "us-price-targets"
OUT = HERE / "findings" / "us-price-target-reliability-results-2026-10.json"
H12 = 252
SEED = 20261018
COST, STRESS = 10.0, 20.0                 # 왕복 bp
TRAIN, VALID, TEST = ("2013-01-01", "2019-12-31"), ("2020-01-01", "2023-12-31"), ("2024-01-01", "2100-01-01")
PERIODS = {"2012~15": ("2012-01-01", "2015-12-31"), "2016~23": ("2016-01-01", "2023-12-31"),
           "2024": ("2024-01-01", "2024-12-31"), "2025~": ("2025-01-01", "2100-01-01")}
BUY = {"buy", "strong buy", "outperform", "overweight", "positive", "sector outperform", "market outperform",
       "accumulate", "add", "top pick", "conviction buy", "long-term buy", "speculative buy"}
SELL = {"sell", "underperform", "underweight", "reduce", "negative", "strong sell", "sector underperform",
        "market underperform", "moderate sell"}


# ── 공용 ──────────────────────────────────────────────────────────────
def nw_t(x, lag):
    """평균의 Newey-West t. 관측 < 3 이면 nan."""
    x = np.asarray(x, float)
    x = x[~np.isnan(x)]
    n = len(x)
    if n < 3:
        return float("nan")
    e = x - x.mean()
    v = e @ e / n
    for k in range(1, min(lag, n - 1) + 1):
        v += 2 * (1 - k / (lag + 1)) * (e[k:] @ e[:-k]) / n
    return float(x.mean() / np.sqrt(v / n)) if v > 0 else float("nan")


def scale(target, prior, s, close):
    """사전등록 §1.3 척도 규칙 → (target, prior) 또는 None(제외)."""
    if s == 1:
        t, p = target, prior
    else:
        a, b = abs(np.log(target / close)), abs(np.log(target / s / close))
        if np.log(s) >= 0.2 and abs(a - b) < 0.1:
            return None
        t, p = (target / s, prior / s) if b < a else (target, prior)
    if not (0.2 <= t / close <= 5):
        return None
    return t, p


def grade_family(g):
    g = (g or "").strip().lower()
    return "buy" if g in BUY else "sell" if g in SELL else "hold"


def in_(s, rng):
    return (s >= pd.Timestamp(rng[0])) & (s <= pd.Timestamp(rng[1]))


def period_means(df, col, datecol):
    return {k: (round(float(df.loc[in_(df[datecol], r), col].mean()), 2) if in_(df[datecol], r).any() else None,
                int(in_(df[datecol], r).sum())) for k, r in PERIODS.items()}


# ── 자료 ──────────────────────────────────────────────────────────────
def load():
    t = pd.read_parquet(D / "targets.parquet")
    p = pd.read_parquet(D / "prices.parquet")
    sp = json.loads((D / "splits.json").read_text(encoding="utf-8"))
    p["date"] = pd.to_datetime(p["date"]).dt.tz_localize(None)
    p = p[p.ticker != "SPY"]
    W = {c: p.pivot(index="date", columns="ticker", values=c).sort_index() for c in ("close", "high", "low", "adj_close")}
    cal = W["close"].index
    t = t[t.target > 0].copy()
    t["ts_"] = pd.to_datetime(t.ts)
    t["d"] = pd.to_datetime(t.ts.str[:10])
    t = t.sort_values("ts_").drop_duplicates(["ticker", "firm", "d"], keep="last")
    t = t[t.ticker.isin(W["close"].columns)]
    col = {c: i for i, c in enumerate(W["close"].columns)}
    t["j"] = t.ticker.map(col)
    t["i0"] = np.searchsorted(cal.values, t.d.values, side="right") - 1      # D 이하 마지막 거래일
    t = t[t.i0 >= 0]
    C = W["close"].values
    t["c0"] = C[t.i0.values, t.j.values]
    t = t[~np.isnan(t.c0)]
    sdates = {k: [(pd.Timestamp(d), v) for d, v in L] for k, L in sp.items()}
    t["S"] = [float(np.prod([v for d, v in sdates.get(k, []) if d > x])) for k, x in zip(t.ticker, t.d)]
    sc = [scale(a, b, s, c) for a, b, s, c in zip(t.target, t.prior, t.S, t.c0)]
    keep = np.array([x is not None for x in sc])
    excluded = int((~keep).sum())
    t = t[keep].copy()
    sc = [x for x in sc if x is not None]
    t["T"], t["P"] = [x[0] for x in sc], [x[1] for x in sc]
    return t, W, cal, excluded


# ── Q1 ───────────────────────────────────────────────────────────────
def q1(t, W):
    C, Hi, Lo = W["close"].values, W["high"], W["low"]
    n = len(C)
    m = t[t.i0 + H12 < n].copy()
    m = m[m.d >= "2012-01-01"]
    m["c1"] = C[m.i0.values + H12, m.j.values]
    fmax = Hi.rolling(H12, min_periods=1).max().shift(-H12).values     # (i, i+252]
    fmin = Lo.rolling(H12, min_periods=1).min().shift(-H12).values
    m["hmax"], m["lmin"] = fmax[m.i0.values, m.j.values], fmin[m.i0.values, m.j.values]
    m = m.dropna(subset=["c1", "hmax", "lmin"])
    m["u"] = m["T"] / m.c0 - 1
    m["r"] = m.c1 / m.c0 - 1
    m["b"] = m.u - m.r
    up = m.u > 0
    m["hit_end"] = np.where(up, m.c1 >= m["T"], m.c1 <= m["T"])
    m["hit_any"] = np.where(up, m.hmax >= m["T"], m.lmin <= m["T"])
    mon = m.groupby(m.d.dt.to_period("M"))["b"].mean()
    per = {k: round(float(m.loc[in_(m.d, r), "b"].mean() * 100), 2) for k, r in PERIODS.items()}
    t1 = nw_t(mon.values, 12)
    supported = t1 >= 2 and all(v > 0 for v in per.values())
    m["uq"] = pd.qcut(m.u.rank(method="first"), 5, labels=False) + 1
    slope = float(np.polyfit(m.u, m.r, 1)[0])
    m["fam"] = m.to_grade.map(grade_family)
    pct = lambda s: round(float(s.mean() * 100), 2)
    return m, {
        "n": len(m), "months": len(mon), "mean_u_pct": pct(m.u), "median_u_pct": round(float(m.u.median() * 100), 2),
        "mean_r_pct": pct(m.r), "median_r_pct": round(float(m.r.median() * 100), 2),
        "mean_bias_pct": pct(m.b), "median_bias_pct": round(float(m.b.median() * 100), 2),
        "bias_nw_t": round(t1, 2), "bias_by_period_pct": per, "H1": "SUPPORTED" if supported else "NOT SUPPORTED",
        "hit_end_pct": pct(m.hit_end), "hit_any_pct": pct(m.hit_any),
        "hit_end_up_pct": pct(m.loc[up, "hit_end"]), "hit_any_up_pct": pct(m.loc[up, "hit_any"]),
        "share_u_positive_pct": pct(up),
        "by_u_quintile": {int(q): {"mean_u": pct(g.u), "mean_r": pct(g.r), "median_r": round(float(g.r.median() * 100), 2),
                                   "hit_end": pct(g.hit_end), "n": len(g)} for q, g in m.groupby("uq")},
        "calib_slope_r_on_u": round(slope, 3),
        "by_year": {int(y): {"n": len(g), "u": pct(g.u), "r": pct(g.r), "bias": pct(g.b), "hit_end": pct(g.hit_end)}
                    for y, g in m.groupby(m.d.dt.year)},
        "by_grade": {f: {"n": len(g), "u": pct(g.u), "r": pct(g.r), "bias": pct(g.b), "hit_end": pct(g.hit_end)}
                     for f, g in m.groupby("fam")},
    }


# ── Q2 ───────────────────────────────────────────────────────────────
def q2(t, W, cal, semis):
    close, adj = W["close"], W["adj_close"]
    me = pd.Series(cal, index=cal).groupby(cal.to_period("M")).max()
    me = me[me >= "2012-01-01"]
    rows, prev = [], {5: set(), 1: set()}
    tk = t[["ticker", "firm", "d", "T"]].sort_values("d")
    for k in range(len(me) - 1):
        M, M1 = me.iloc[k], me.iloc[k + 1]
        w = tk[(tk.d < M) & (tk.d > M - pd.Timedelta(days=365))]
        last = w.groupby(["ticker", "firm"])["T"].last()
        g = last.groupby(level=0).agg(["median", "count"])
        g = g[g["count"] >= 3]
        px = close.loc[M].reindex(g.index)
        r = (adj.loc[M1] / adj.loc[M] - 1).reindex(g.index)
        df = pd.DataFrame({"up": g["median"] / px - 1, "r": r}).dropna()
        if len(df) < 50:
            continue
        df["q"] = pd.qcut(df.up.rank(method="first"), 5, labels=False) + 1
        q5, q1_ = set(df.index[df.q == 5]), set(df.index[df.q == 1])
        to = lambda new, old: 1.0 if not old else 2 * (1 - len(new & old) / max(len(new), 1))
        ew = df.r.mean()
        nos = df[~df.index.isin(semis)]
        nos_q = pd.qcut(nos.up.rank(method="first"), 5, labels=False) + 1 if len(nos) >= 50 else None
        rows.append({"M": M, "n": len(df), "spread": (df.r[df.q == 5].mean() - df.r[df.q == 1].mean()) * 1e4,
                     "q5_ew": (df.r[df.q == 5].mean() - ew) * 1e4, "q1_ew": (df.r[df.q == 1].mean() - ew) * 1e4,
                     "to_sum": to(q5, prev[5]) + to(q1_, prev[1]),
                     "spread_ex_semis": None if nos_q is None else (nos.r[nos_q == 5].mean() - nos.r[nos_q == 1].mean()) * 1e4,
                     "q5": sorted(q5), "q1": sorted(q1_)})
        prev = {5: q5, 1: q1_}
    df = pd.DataFrame(rows)
    # 기록: 3·12개월 보유(겹침) 스프레드
    hold = {}
    for h in (3, 12):
        v = []
        for k, row in df.iterrows():
            i = me.searchsorted(row.M)
            if i + h < len(me):
                a0, a1 = adj.loc[me.iloc[i]], adj.loc[me.iloc[i + h]]
                rr = a1 / a0 - 1
                v.append((rr.reindex(row.q5).mean() - rr.reindex(row.q1).mean()) * 1e4)
        hold[h] = {"mean_bp": round(float(np.nanmean(v)), 1), "nw_t": round(nw_t(v, h), 2), "n": len(v)}
    return df, hold


# ── Q3 ───────────────────────────────────────────────────────────────
def q3(t, W, cal):
    adj = W["adj_close"]
    A = adj.values
    n = len(cal)
    e = t[(t.P > 0) & (t["T"] != t.P)].copy()
    e["dir"] = np.sign(e["T"] - e.P)
    e["mag"] = (e["T"] / e.P - 1).abs()
    e["rating_change"] = (e.from_grade.fillna("").str.strip() != "") & (e.from_grade.fillna("") != e.to_grade.fillna(""))
    g = e.groupby(["ticker", "d"]).agg(dirs=("dir", "nunique"), dir=("dir", "first"), j=("j", "first"),
                                        mag=("mag", "mean"), rc=("rating_change", "max")).reset_index()
    g = g[g.dirs == 1]
    g["i1"] = np.searchsorted(cal.values, g.d.values, side="right")         # D 다음 거래일
    out = {}
    mkt_cache = {}
    for h in (1, 5, 20):
        ok = g.i1 + h < n
        x = g[ok].copy()
        a0, a1 = A[x.i1.values, x.j.values], A[x.i1.values + h, x.j.values]
        x["ret"] = a1 / a0 - 1
        if h not in mkt_cache:
            mk = np.full(n, np.nan)
            mk[: n - h] = np.nanmean(A[h:] / A[:-h] - 1, axis=1)
            mkt_cache[h] = mk
        x["ex"] = (x.ret - mkt_cache[h][x.i1.values]) * 1e4
        out[h] = x.dropna(subset=["ex"])
    return out


def cell_series(x, direction, date="d"):
    s = x[x.dir == direction].groupby(date).ex.mean()
    return s


# ── Q4 ───────────────────────────────────────────────────────────────
def q4(m):
    m = m.copy()
    m["e"] = np.abs(np.log(m.c1 / m["T"]))
    m["sgn"] = np.log(m["T"] / m.c1)
    adj_e, adj_s = np.full(len(m), np.nan), np.full(len(m), np.nan)
    m = m.reset_index(drop=True)
    for _, g in m.groupby("ticker"):
        idx = g.index.values
        dd = g.d.values.astype("datetime64[D]").astype(np.int64)
        ff, ee, ss = g.firm.values, g.e.values, g.sgn.values
        for k in range(len(idx)):
            w = (np.abs(dd - dd[k]) <= 30) & (ff != ff[k])
            if w.any():
                adj_e[idx[k]] = ee[k] - ee[w].mean()
                adj_s[idx[k]] = ss[k] - ss[w].mean()
    m["ae"], m["as_"] = adj_e, adj_s
    m = m.dropna(subset=["ae"])
    A = m[m.d <= "2019-12-31"]
    B = m[m.d >= "2020-01-01"]
    ca, cb = A.groupby("firm").size(), B.groupby("firm").size()
    firms = sorted(set(ca[ca >= 30].index) & set(cb[cb >= 30].index))
    res = {"firms": len(firms), "rows_A": len(A), "rows_B": len(B)}
    if len(firms) < 15:
        res["H4"] = "판정불가"
        return res
    rng = np.random.default_rng(SEED)

    def persist(col):
        sa = A[A.firm.isin(firms)].groupby("firm")[col].median().reindex(firms)
        sb = B[B.firm.isin(firms)].groupby("firm")[col].median().reindex(firms)
        rho = float(sa.rank().corr(sb.rank()))
        perm = np.array([sa.rank().corr(pd.Series(rng.permutation(sb.rank().values), index=firms)) for _ in range(1000)])
        return rho, float((perm >= rho).mean()), sa, sb

    rho, p, sa, sb = persist("ae")
    rho_s, p_s, _, sbs = persist("as_")
    res.update({"rho": round(rho, 3), "p_one_sided": round(p, 4),
                "H4": "SUPPORTED" if rho > 0 and p < 0.05 else "NOT SUPPORTED",
                "bias_rho": round(rho_s, 3), "bias_p": round(p_s, 4),
                "B_best10": [[f, round(float(v), 3), int(cb[f])] for f, v in sb.sort_values().head(10).items()],
                "B_worst10": [[f, round(float(v), 3), int(cb[f])] for f, v in sb.sort_values().tail(10).items()],
                "B_most_optimistic5": [[f, round(float(v), 3)] for f, v in sbs.sort_values().tail(5).items()]})
    return res


# ── 판정 ──────────────────────────────────────────────────────────────
def judge(cells):
    """cells: name → dict(series=pd.Series(index=날짜, gross bp), lag, cost_per_obs=pd.Series bp(왕복 10bp 기준))."""
    rng = np.random.default_rng(SEED)
    trains = {k: c["series"][in_(c["series"].index.to_series(), TRAIN)].values for k, c in cells.items()}
    floor = []
    for _ in range(500):
        floor.append(max(abs(nw_t(v * rng.choice([-1, 1], len(v)), cells[k]["lag"])) for k, v in trains.items()))
    floor = float(np.percentile(floor, 95))
    out = {"floor": round(floor, 3)}
    for k, c in cells.items():
        s, lag = c["series"], c["lag"]
        idx = s.index.to_series()
        tr, va, te = s[in_(idx, TRAIN)], s[in_(idx, VALID)], s[in_(idx, TEST)]
        oos = s[in_(idx, VALID) | in_(idx, TEST)]
        t_tr = nw_t(tr.values, lag)
        d = 1.0 if t_tr >= 0 else -1.0
        cost = c["cost"].reindex(oos.index)
        net = d * oos - cost
        net_s = d * oos - cost * STRESS / COST
        bs = np.random.default_rng(SEED).choice(oos.values * d, (2000, len(oos))).mean(axis=1)
        info = abs(t_tr) >= floor and np.sign(va.mean()) == d and np.sign(te.mean()) == d
        econ = info and net.mean() > 0 and net_s.mean() > 0
        robust = econ and nw_t(net.values, lag) >= 2
        n_te = len(te)
        verdict = ("판정불가" if n_te < c["min_test"] else "ROBUST" if robust else "ECONOMIC" if econ
                   else "INFORMATION" if info else "REJECT")
        per = {}
        for pk, r in PERIODS.items():
            v = s[in_(idx, r)]
            per[pk] = {"gross_dir_bp": round(float(d * v.mean()), 1) if len(v) else None, "n": len(v)}
        out[k] = {"dir": int(d), "train_t": round(t_tr, 2), "train_bp": round(float(tr.mean()), 1), "n_train": len(tr),
                  "valid_bp": round(float(va.mean()), 1), "valid_t": round(nw_t(va.values, lag), 2), "n_valid": len(va),
                  "test_bp": round(float(te.mean()), 1), "test_t": round(nw_t(te.values, lag), 2), "n_test": n_te,
                  "oos_gross_dir_bp": round(float(d * oos.mean()), 1),
                  "oos_ci95": [round(float(np.percentile(bs, 2.5)), 1), round(float(np.percentile(bs, 97.5)), 1)],
                  "oos_net_bp": round(float(net.mean()), 1), "oos_net_stress_bp": round(float(net_s.mean()), 1),
                  "oos_net_t": round(nw_t(net.values, lag), 2),
                  "breakeven_rt_bp": round(float(d * oos.mean() / (cost.mean() / COST)), 1) if cost.mean() > 0 else None,
                  "periods": per, "verdict": verdict}
    return out


def industry(tickers):
    p = D / "industry.json"
    if p.exists():
        return json.loads(p.read_text(encoding="utf-8"))
    import yfinance as yf
    from concurrent.futures import ThreadPoolExecutor

    def one(t):
        try:
            return t, (yf.Ticker(t.replace(".", "-")).info or {}).get("industry")
        except Exception:
            return t, None
    with ThreadPoolExecutor(4) as ex:
        d = dict(ex.map(one, tickers))
    p.write_text(json.dumps(d, ensure_ascii=False), encoding="utf-8")
    return d


def selftest():
    assert scale(400, 380, 4.0, 110) == (100, 95)            # 분할 전 척도 → ÷S
    assert scale(112.5, 100, 4.0, 110) == (112.5, 100)       # 이미 반영
    assert scale(300, 0, 1.0, 100) == (300, 0)
    assert scale(600, 0, 1.0, 100) is None                    # 5배 밖
    assert scale(141, 0, 2.0, 100) is None                    # √2 근처 = 애매(log2 ≥ 0.2, 차이 < 0.1)
    assert grade_family("Overweight") == "buy" and grade_family("Underweight") == "sell" and grade_family("Neutral") == "hold"
    x = np.array([1.0, -1.0] * 50)
    assert abs(nw_t(x + 0.0, 5)) < 1e-9
    print("selftest OK")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--selftest", action="store_true")
    if ap.parse_args().selftest:
        return selftest()
    t, W, cal, excluded = load()
    print(f"목표가 행 {len(t):,} (척도 규칙 제외 {excluded})")
    semis = {k for k, v in industry(list(W["close"].columns)).items() if v and "semiconductor" in v.lower()}

    m, r1 = q1(t, W)
    print("Q1", {k: r1[k] for k in ("n", "mean_u_pct", "mean_r_pct", "mean_bias_pct", "bias_nw_t", "H1", "hit_end_up_pct", "hit_any_up_pct")})

    q2df, q2hold = q2(t, W, cal, semis)
    q2s = pd.Series(q2df.spread.values, index=pd.DatetimeIndex(q2df.M))
    q2cost = pd.Series(q2df.to_sum.values * COST / 2, index=q2s.index)      # 편도 5bp × Σ|Δw|
    ev = q3(t, W, cal)
    cells = {"Q2": {"series": q2s, "lag": 1, "cost": q2cost, "min_test": 24}}
    for name, dirn, h in (("R5", 1, 5), ("R20", 1, 20), ("L5", -1, 5), ("L20", -1, 20)):
        s = cell_series(ev[h], dirn)
        cells[name] = {"series": s, "lag": h, "cost": pd.Series(COST, index=s.index), "min_test": 100}
    jd = judge(cells)
    for k in cells:
        print(k, {x: jd[k][x] for x in ("dir", "train_t", "test_bp", "oos_gross_dir_bp", "oos_net_bp", "verdict")})
    print("floor", jd["floor"])

    rec2 = {"q5_ew_bp": round(float(q2df.q5_ew.mean()), 1), "q5_ew_t": round(nw_t(q2df.q5_ew.values, 1), 2),
            "q1_ew_bp": round(float(q2df.q1_ew.mean()), 1), "q1_ew_t": round(nw_t(q2df.q1_ew.values, 1), 2),
            "spread_ex_semis_bp": round(float(q2df.spread_ex_semis.astype(float).mean()), 1),
            "spread_ex_semis_by_period": period_means(q2df.assign(x=q2df.spread_ex_semis.astype(float)), "x", "M"),
            "months": len(q2df), "median_names": int(q2df.n.median()), "mean_turnover_sum": round(float(q2df.to_sum.mean()), 3),
            "hold": q2hold, "semis_tickers": len(semis)}
    rec3 = {}
    for h, x in ev.items():
        for dirn, nm in ((1, "up"), (-1, "down")):
            y = x[x.dir == dirn]
            rec3[f"{nm}_h{h}"] = {"events": len(y), "dates": int(y.d.nunique()), "mean_bp": round(float(y.ex.mean()), 1),
                                  "rating_change_bp": round(float(y[y.rc].ex.mean()), 1), "n_rc": int(y.rc.sum())}
            if h == 20:
                y = y.assign(mt=pd.qcut(y.mag.rank(method="first"), 3, labels=["small", "mid", "large"]))
                rec3[f"{nm}_h20_by_mag"] = {str(k): round(float(v), 1) for k, v in y.groupby("mt", observed=True).ex.mean().items()}
    r4 = q4(m)
    print("Q4", {k: r4.get(k) for k in ("firms", "rho", "p_one_sided", "H4", "bias_rho", "bias_p")})

    yr = t.groupby(t.d.dt.year).agg(rows=("firm", "size"), tickers=("ticker", "nunique"), firms=("firm", "nunique"))
    doc = {"prereg": "d4a61764", "rows_after_scale": len(t), "scale_excluded": excluded,
           "rows_by_year": {int(k): v for k, v in yr.to_dict("index").items()},
           "Q1": r1, "judge": jd, "Q2_record": rec2, "Q3_record": rec3, "Q4": r4}
    OUT.write_text(json.dumps(doc, ensure_ascii=False, indent=1, default=str), encoding="utf-8")
    print("→", OUT.relative_to(HERE))


if __name__ == "__main__":
    sys.exit(main())
