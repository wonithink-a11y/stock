#!/usr/bin/env python3
"""조건 격자 엔진 — 스킬 .claude/skills/condition-grid. 설정 JSON(사전등록에 포함) → 사건 정의 × 조건 칸별 통계 + BH 보정.

    python research/strategy-lab/condition_grid.py --selftest
    python research/strategy-lab/condition_grid.py --config research/strategy-lab/findings/<이름>-config.json
"""
import argparse
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
import tech_timing_3x as B  # noqa: E402

ENGINE_VERSION = "L2-1"
GRID_DIR = Path(__file__).resolve().parent / "data" / "condition-grid"
CRISES = {"닷컴붕괴": ("2000-03-10", "2002-10-09"), "금융위기": ("2008-09-01", "2009-06-30"), "코로나": ("2020-02-19", "2020-04-30")}

OPS = {">=": lambda a, b: a >= b, "<=": lambda a, b: a <= b, ">": lambda a, b: a > b, "<": lambda a, b: a < b}


def load_cv(tk):
    f = B.CACHE / f"{tk.replace('^', '')}_cv.parquet"
    if f.exists():
        return pd.read_parquet(f)
    import yfinance as yf
    d = yf.download(tk, start="1990-01-01", end="2026-11-07", progress=False, auto_adjust=True)
    d.columns = [c[0] if isinstance(c, tuple) else c for c in d.columns]
    d = d[["Close", "Volume"]].dropna(subset=["Close"])
    d.index = pd.to_datetime(d.index).tz_localize(None)
    f.parent.mkdir(parents=True, exist_ok=True)
    d.to_parquet(f)
    return d


def load_fomc():
    """연준 공식 페이지에서 받은 결정일(회의 마지막 날). 일정은 사전 공개라 미리 알 수 있다."""
    return pd.to_datetime(json.loads((GRID_DIR / "fomc_dates.json").read_text(encoding="utf-8")))


def _macro(tk):
    d = B.load(tk)
    return d["Close"]


def add_l2(S, d, tk, lag, flows, macro, fomc, flow_df):
    """L2 신규 시리즈. 모두 사건일 종가 시점 정보만 쓴다(미국 자료는 lag 만큼 늦춰 PIT)."""
    idx = d.index
    c = d["Close"]
    S["ret20"] = (c / c.shift(20) - 1).values
    try:
        o = B.load(tk)["Open"].reindex(idx)
        pc = c.shift(1)
        gap = (o / pc - 1)
        if (o == pc).mean() > 0.3 or o.isna().mean() > 0.3:   # 시가 자료가 종가 복사본인 시장은 갭 칸 제외
            gap[:] = np.nan
        S["gap"] = gap.values
    except Exception:
        S["gap"] = np.full(len(idx), np.nan)
    for nm, ser, fn in (("usd5", macro["DXY"], lambda x: x / x.shift(5) - 1), ("usd20", macro["DXY"], lambda x: x / x.shift(20) - 1),
                        ("tnx5", macro["TNX"], lambda x: x - x.shift(5)), ("tnx20", macro["TNX"], lambda x: x - x.shift(20))):
        v = fn(ser)
        v = v.shift(lag) if lag else v
        S[nm] = v.reindex(idx.union(v.index)).sort_index().ffill().reindex(idx).values
    # FOMC 거리(달력일). 다음 결정일은 사전 공개 일정, 직후 거리는 결정이 장 마감 뒤(lag=1 시장)면 하루 늦게 안다.
    dates = fomc.values
    nxt = np.full(len(idx), np.nan)
    lst = np.full(len(idx), np.nan)
    for i, t in enumerate(idx.values):
        j = np.searchsorted(dates, t, side="left")
        if j < len(dates):
            nxt[i] = (dates[j] - t) / np.timedelta64(1, "D")
        cut = t - np.timedelta64(lag, "D")
        k = np.searchsorted(dates, cut, side="right") - 1
        if k >= 0:
            lst[i] = (t - dates[k]) / np.timedelta64(1, "D")
    S["fomc_next"], S["fomc_last"] = nxt, lst
    # 수급(국내만): 직전 거래일까지의 외국인·기관 5일 순매수 / 거래대금, 252일 z (당일 값은 쓰지 않는다)
    for nm in ("frgn_z", "inst_z"):
        S[nm] = np.full(len(idx), np.nan)
    if flows and flow_df is not None:
        for nm, col in (("frgn_z", "f"), ("inst_z", "i")):
            r5 = flow_df[col].rolling(5).sum() / flow_df["a"].rolling(5).sum()
            z = (r5 - r5.rolling(252, min_periods=120).mean()) / r5.rolling(252, min_periods=120).std()
            z = z.shift(1)
            S[nm] = z.reindex(idx.union(z.index)).sort_index().ffill().reindex(idx).values
            S[nm][idx < flow_df.index.min()] = np.nan


def load_flows():
    f = GRID_DIR / "krx_flow_daily.parquet"
    if f.exists():
        return pd.read_parquet(f)
    x = pd.read_parquet(Path(__file__).resolve().parent / "data" / "a4" / "a4-research-dataset.parquet", columns=["date", "foreign_net", "inst_net", "total_amount"])
    x["date"] = pd.to_datetime(x["date"])
    g = x.groupby("date").agg(f=("foreign_net", "sum"), i=("inst_net", "sum"), a=("total_amount", "sum"))
    g.to_parquet(f)
    return g


def provenance(cfg_path):
    import hashlib
    import subprocess
    def sh(p):
        return hashlib.sha256(Path(p).read_bytes()).hexdigest()[:16] if Path(p).exists() else None
    try:
        commit = subprocess.check_output(["git", "rev-parse", "--short", "HEAD"], cwd=Path(__file__).parent, text=True).strip()
    except Exception:
        commit = None
    data = {}
    for f in sorted(B.CACHE.glob("*.parquet")):
        data[f.name] = sh(f)
    for f in sorted(GRID_DIR.glob("*")):
        data["condition-grid/" + f.name] = sh(f)
    return dict(engine_version=ENGINE_VERSION, git_commit=commit, engine_sha=sh(__file__), config_sha=sh(cfg_path) if cfg_path else None,
                data_sha=hashlib.sha256(json.dumps(data, sort_keys=True).encode()).hexdigest()[:16], data_files=len(data),
                generated=pd.Timestamp.now().isoformat(timespec="seconds"))


def bh_adjust(p):
    p = np.asarray(p, dtype=float)
    n = len(p)
    order = np.argsort(p)
    adj = np.empty(n)
    prev = 1.0
    for rank, idx in zip(range(n, 0, -1), order[::-1]):
        prev = min(prev, p[idx] * n / rank)
        adj[idx] = prev
    return adj


def build_series(d: pd.DataFrame, vix: pd.Series, vix_lag: int, spy_ret: pd.Series = None):
    c = d["Close"]
    p = c.values
    n = len(p)
    r = c.pct_change().values
    L = np.zeros(n, dtype=int)
    for i in range(1, n):
        L[i] = L[i - 1] + 1 if p[i] < p[i - 1] else 0
    D = np.zeros(n)
    maxday = np.zeros(n)
    for i in range(1, n):
        if L[i] > 0:
            D[i] = p[i] / p[i - L[i]] - 1
            maxday[i] = np.nanmin(r[i - L[i] + 1:i + 1])
    v = (vix.shift(vix_lag) if vix_lag else vix).reindex(c.index).ffill()
    vol = d["Volume"].replace(0, np.nan)
    volratio = (vol / vol.rolling(20).mean().shift(1)).values
    s200 = c.rolling(200).mean()
    dd252 = (c / c.rolling(252, min_periods=1).max() - 1).values
    dd10 = (c / c.rolling(10).max() - 1).values
    delta = c.diff()
    up = delta.clip(lower=0).ewm(alpha=1 / 14, adjust=False).mean()
    dn = (-delta.clip(upper=0)).ewm(alpha=1 / 14, adjust=False).mean()
    rsi14 = (100 - 100 / (1 + up / dn)).values
    sma50 = c.rolling(50).mean()
    run60 = (c / c.shift(60) - 1).values
    rv20 = c.pct_change().rolling(20).std()
    atrratio = (rv20 / rv20.rolling(252, min_periods=60).median()).values
    vixpct = v.rolling(252, min_periods=60).apply(lambda x: (x[:-1] < x[-1]).mean(), raw=True).values
    ma20 = c.rolling(20).mean()
    sd20 = c.rolling(20).std()
    pctb = ((c - (ma20 - 2 * sd20)) / (4 * sd20)).values
    if spy_ret is not None:
        sr = spy_ret.reindex(c.index.union(spy_ret.index)).sort_index()
        prev = spy_ret.shift(1)
        both = pd.concat([spy_ret.rename("a"), prev.rename("b")], axis=1).min(axis=1)
        usd = (both <= -0.03).astype(float).reindex(c.index, method=None).fillna(0.0).values
        prev_only = (spy_ret.shift(1) <= -0.03).astype(float)
        usd = np.maximum(usd, prev_only.reindex(c.index, method="ffill").fillna(0.0).values)
    else:
        usd = np.zeros(len(c))
    return dict(sma50gap=(c / sma50 - 1).values, run60=run60, atrratio=atrratio, vixpct=vixpct, pctb=pctb, usdown=usd, weekday=c.index.weekday.values.astype(float), streakL=L.astype(float), r=r, L=L, D=D, maxday=maxday, vix=v.values, vixchg5=(v / v.shift(5) - 1).values, vol=volratio, sma200gap=(c / s200 - 1).values, rsi14=rsi14, dd252=dd252, dd10=dd10, month=c.index.month.values.astype(float)), p


def events_for(ev_def, S, p):
    n = len(p)
    out, last = [], -10 ** 9
    gap = ev_def.get("gap", 10)
    t = ev_def["type"]
    hit = False
    for i in range(1, n):
        if t == "streak":
            if S["L"][i] == 0:
                hit = False
            ok = S["L"][i] >= ev_def["L"] and S["D"][i] <= -ev_def["D"] and not hit
            if ok:
                hit = True
        elif t == "daily":
            ok = S["r"][i] <= ev_def["thr"]
        elif t == "dd10":
            ok = S["dd10"][i] <= ev_def["thr"]
        elif t == "ret20":
            v = S["ret20"][i]
            ok = v == v and v <= ev_def["thr"]
        elif t == "gap":
            v = S["gap"][i]
            ok = v == v and v <= ev_def["thr"]
        else:
            raise ValueError(t)
        if ok and i - last > gap:
            out.append(i)
            last = i
    return np.array(out, dtype=int)


def passes(S, i, flt):
    if flt is None:
        return True
    clauses = flt["all"] if "all" in flt else [flt]
    for c in clauses:
        val = S[c["series"]][i]
        if val != val or not OPS[c["op"]](val, c["value"]):
            return False
    return True


def fwd_array(p, h):
    a = np.full(len(p), np.nan)
    a[:-h] = (p[h:] / p[:-h] - 1) * 100
    return a


SPY_RET = None


def run(cfg, count_only=False):
    global SPY_RET
    SPY_RET = load_cv("SPY")["Close"].pct_change()
    rng = np.random.default_rng(cfg.get("seed", B.SEED))
    rng_m = np.random.default_rng(cfg.get("seed", B.SEED) + 1)   # 매칭 대조 전용(주 지표 난수열을 바꾸지 않는다)
    matched = cfg.get("matched", False)
    nperm = cfg.get("nperm", 1000)
    hs = cfg.get("horizons", [5, 21, 63])
    prim = cfg.get("primary", 21)
    min_ev = cfg.get("min_events", 5)
    vix = B.load("^VIX")["Close"]
    l2 = cfg.get("l2", False)
    if l2:
        macro = {"DXY": _macro("DX-Y.NYB"), "TNX": _macro("^TNX")}
        fomc = load_fomc()
        flow_df = load_flows()
    mk = {}
    for m in cfg["markets"]:
        d = load_cv(m["ticker"])
        d = d[d.index <= B.END]
        S, p = build_series(d, vix, m.get("vix_lag", 0), SPY_RET)
        if l2:
            add_l2(S, d, m["ticker"], m.get("vix_lag", 0), m.get("flows", False), macro, fomc, flow_df)
        mk[m["name"]] = dict(S=S, p=p, dates=d.index, fw={h: fwd_array(p, h) for h in hs})
    flts = [None] + cfg["filters"]
    tests = []   # (cell, market, stats)
    for ev_def in cfg["events"]:
        for flt in flts:
            cell = f"{ev_def['name']} | {flt['name'] if flt else '조건 없음'}"
            for nm, M in mk.items():
                ev_all = events_for(ev_def, M["S"], M["p"])
                ev = np.array([i for i in ev_all if passes(M["S"], i, flt)], dtype=int)
                row = dict(cell=cell, market=nm, n=int(len(ev)))
                n = len(M["p"])
                if count_only:
                    okn = M["fw"][prim][ev] if len(ev) else np.array([])
                    if (~np.isnan(okn)).sum() >= min_ev:
                        tests.append(row)
                    continue
                for h in hs:
                    a = M["fw"][h]
                    evr = a[ev] if len(ev) else np.array([])
                    evr = evr[~np.isnan(evr)]
                    if len(evr) < min_ev:
                        row[h] = None
                        continue
                    m_all = np.nanmean(a)
                    diff = float(evr.mean() - m_all)
                    ks = rng.integers(252, n - 252, size=nperm)
                    idx = (ev[None, :] + ks[:, None]) % n
                    sh = np.nanmean(a[idx], axis=1)
                    p_val = float((1 + np.sum(np.abs(sh - m_all) >= abs(diff))) / (1 + nperm))
                    row[h] = dict(n=int(len(evr)), mean=round(float(evr.mean()), 2), base=round(float(m_all), 2), diff=round(diff, 2), win=round(float((evr > 0).mean() * 100)), p=p_val)
                    if h == prim and matched and flt is not None:
                        # 같은 조건을 만족하는 모든 날을 기준으로 한 대조(조건 자체가 만드는 국면 효과를 분리)
                        reg = np.array([i for i in range(n) if passes(M["S"], i, flt) and not np.isnan(a[i])], dtype=int)
                        if len(reg) >= max(50, 3 * len(evr)):
                            base_m = float(a[reg].mean())
                            sims = np.array([a[rng_m.choice(reg, size=len(evr), replace=False)].mean() for _ in range(nperm)])
                            dm = float(evr.mean() - base_m)
                            row[h]["base_matched"] = round(base_m, 2)
                            row[h]["diff_matched"] = round(dm, 2)
                            row[h]["p_matched"] = float((1 + np.sum(np.abs(sims - base_m) >= abs(dm))) / (1 + nperm))
                    if h == prim:
                        dts = M["dates"][ev[~np.isnan(a[ev])]]
                        row["dates"] = [str(x.date()) for x in dts]
                        keep = [k for k, x in enumerate(dts) if not any(lo <= str(x.date()) <= hi for lo, hi in CRISES.values())]
                        row[h]["n_exc"] = len(keep)
                        row[h]["diff_exc"] = round(float(np.mean(evr[keep]) - m_all), 2) if keep else None
                        per = {}
                        for pn, (lo, hi) in {"TRAIN": ("1900", "2009-12-31"), "VALID": ("2010-01-01", "2019-12-31"), "TEST": ("2020-01-01", "2026-12-31")}.items():
                            sel = [x for x, dt in zip(evr, dts) if lo <= str(dt.date()) <= hi]
                            per[pn] = (len(sel), round(float(np.mean(sel) - m_all), 2)) if len(sel) >= 3 else None
                        row["per"] = per
                tests.append(row)
    if count_only:
        return dict(config=cfg.get("name"), K=len(tests), 칸=len({t["cell"] for t in tests}), tests=tests)
    ps = [t[prim]["p"] for t in tests if t.get(prim)]
    adj = bh_adjust(ps) if ps else []
    k = 0
    for t in tests:
        if t.get(prim):
            t[prim]["p_bh"] = round(float(adj[k]), 4)
            k += 1
    # 칸 요약
    cells = {}
    for t in tests:
        cells.setdefault(t["cell"], []).append(t)
    summ = []
    fdr = cfg.get("fdr", 0.05)
    for cell, rows in cells.items():
        valid = [r for r in rows if r.get(prim)]
        pos = sum(1 for r in valid if r[prim]["p_bh"] <= fdr and r[prim]["diff"] > 0)
        neg = sum(1 for r in valid if r[prim]["p_bh"] <= fdr and r[prim]["diff"] < 0)
        tot_n = sum(r[prim]["n"] for r in valid)
        pooled = float(np.average([r[prim]["diff"] for r in valid], weights=[r[prim]["n"] for r in valid])) if valid else None
        pooled_per = {}
        for pn in ("VALID", "TEST"):
            vals = [(r["per"][pn][1], r["per"][pn][0]) for r in valid if r.get("per") and r["per"].get(pn)]
            pooled_per[pn] = round(float(np.average([v[0] for v in vals], weights=[v[1] for v in vals])), 2) if vals else None
        need = int(np.ceil(0.5 * len(valid))) if valid else 99
        sign = 1 if pos >= neg else -1
        m_pass = max(pos, neg)
        same_sign = all(pooled_per[pn] is not None and np.sign(pooled_per[pn]) == sign for pn in ("VALID", "TEST"))
        ok = bool(valid) and m_pass >= need and same_sign and pooled is not None and np.sign(pooled) == sign
        mt = [r[prim] for r in valid if "diff_matched" in r[prim]]
        m_pool = round(float(np.average([x["diff_matched"] for x in mt], weights=[x["n"] for x in mt])), 2) if mt else None
        m_sig = sum(1 for x in mt if x["p_matched"] <= 0.05 and x["diff_matched"] * (1 if pos >= neg else -1) > 0)
        ex = [r[prim] for r in valid if r[prim].get("diff_exc") is not None and r[prim]["n_exc"] > 0]
        ex_pool = round(float(np.average([x["diff_exc"] for x in ex], weights=[x["n_exc"] for x in ex])), 2) if ex else None
        alld = sorted({d for r in valid for d in r.get("dates", [])})
        clusters = 0
        lastd = None
        for dd in alld:
            t0 = pd.Timestamp(dd)
            if lastd is None or (t0 - lastd).days > 30:
                clusters += 1
            lastd = t0
        sg = 1 if pos >= neg else -1
        ok2 = bool(ok and (m_pool is not None and np.sign(m_pool) == sg) and (ex_pool is not None and np.sign(ex_pool) == sg) and clusters >= cfg.get("min_clusters", 10))
        summ.append(dict(위기제외합산초과=ex_pool, 군집수=clusters, 통과2=ok2, 매칭합산초과=m_pool, 매칭p05시장=m_sig, cell=cell, 시장수=len(valid), 사건합=tot_n, BH통과_양=pos, BH통과_음=neg, 합산초과=None if pooled is None else round(pooled, 2), VALID=pooled_per["VALID"], TEST=pooled_per["TEST"], 통과=ok))
    return dict(config=cfg.get("name"), K=len(ps), 칸=len(cells), 요약=summ, tests=tests)


def selftest():
    fails = []
    def ck(n, c):
        print(("ok   " if c else "FAIL ") + n)
        if not c: fails.append(n)
    adj = bh_adjust([0.001, 0.01, 0.04, 0.5])
    ck("BH 보정 단조", adj[0] <= adj[1] <= adj[2] <= adj[3] and abs(adj[0] - 0.004) < 1e-9)
    p = np.array([100, 99, 98, 97, 96, 95, 100, 101.0])
    idx = pd.bdate_range("2024-01-01", periods=len(p))
    d = pd.DataFrame({"Close": p, "Volume": 1.0}, index=idx)
    S, pp = build_series(d, pd.Series(20.0, index=idx), 0)
    ck("연속 하락 길이", list(S["L"][:7]) == [0, 1, 2, 3, 4, 5, 0])
    ev = events_for(dict(type="streak", L=3, D=0.04), S, pp)
    ck("사건 한 번(연속 안 첫 충족)", list(ev) == [4])
    ck("조건 필터", passes(S, 4, dict(series="vix", op=">=", value=15)) and not passes(S, 4, dict(series="vix", op=">=", value=25)))
    print("FAIL" if fails else "OK")
    return 1 if fails else 0


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--selftest", action="store_true")
    ap.add_argument("--config")
    ap.add_argument("--count", action="store_true", help="결과를 보지 않고 K(시험 수)만 센다")
    a = ap.parse_args()
    if a.selftest:
        return selftest()
    cfg = json.loads(Path(a.config).read_text(encoding="utf-8"))
    if a.count:
        r = run(cfg, count_only=True)
        print(f"{r['config']}: 칸 {r['칸']} · K={r['K']} (사건 {cfg.get('min_events', 5)}건 이상)")
        return 0
    res = run(cfg)
    res["provenance"] = provenance(a.config)
    outp = Path(a.config).with_name(Path(a.config).stem.replace("-config", "") + "-results.json")
    outp.write_text(json.dumps(res, ensure_ascii=False, indent=1, default=float), encoding="utf-8")
    print(f"설정 {res['config']}: 칸 {res['칸']}개, 주 지표 시험 K={res['K']}개(BH 보정). 통과 칸 = BH≤{cfg.get('fdr', 0.05)} 시장 ≥ 절반 ∧ VALID·TEST 같은 부호")
    print(f"{'칸':42s} 시장 사건합 BH양 BH음  합산초과 VALID  TEST 통과 | 매칭초과 매칭p≤.05")
    for s in sorted(res["요약"], key=lambda x: -(x["BH통과_양"] + x["BH통과_음"])):
        print(f"{s['cell']:42s} {s['시장수']:3d} {s['사건합']:5d} {s['BH통과_양']:3d} {s['BH통과_음']:3d} {str(s['합산초과']):>8s} {str(s['VALID']):>6s} {str(s['TEST']):>6s} {'★' if s['통과'] else ''}{'★2' if s.get('통과2') else ''} 군집{s.get('군집수')} 위기제외{s.get('위기제외합산초과')} | {str(s['매칭합산초과']):>6s} {s['매칭p05시장']}")
    print("통과 칸:", [s["cell"] for s in res["요약"] if s["통과"]])
    print("통과2 칸(매칭·위기제외·군집):", [s["cell"] for s in res["요약"] if s.get("통과2")])
    return 0


if __name__ == "__main__":
    sys.exit(main())
