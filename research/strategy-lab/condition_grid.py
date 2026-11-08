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


def build_series(d: pd.DataFrame, vix: pd.Series, vix_lag: int):
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
    return dict(r=r, L=L, D=D, maxday=maxday, vix=v.values, vixchg5=(v / v.shift(5) - 1).values, vol=volratio, sma200gap=(c / s200 - 1).values, rsi14=rsi14, dd252=dd252, dd10=dd10, month=c.index.month.values.astype(float)), p


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
        else:
            raise ValueError(t)
        if ok and i - last > gap:
            out.append(i)
            last = i
    return np.array(out, dtype=int)


def passes(S, i, flt):
    if flt is None:
        return True
    val = S[flt["series"]][i]
    if val != val:
        return False
    return bool(OPS[flt["op"]](val, flt["value"]))


def fwd_array(p, h):
    a = np.full(len(p), np.nan)
    a[:-h] = (p[h:] / p[:-h] - 1) * 100
    return a


def run(cfg):
    rng = np.random.default_rng(cfg.get("seed", B.SEED))
    nperm = cfg.get("nperm", 1000)
    hs = cfg.get("horizons", [5, 21, 63])
    prim = cfg.get("primary", 21)
    min_ev = cfg.get("min_events", 5)
    vix = B.load("^VIX")["Close"]
    mk = {}
    for m in cfg["markets"]:
        d = load_cv(m["ticker"])
        d = d[d.index <= B.END]
        S, p = build_series(d, vix, m.get("vix_lag", 0))
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
                    if h == prim:
                        dts = M["dates"][ev[~np.isnan(a[ev])]]
                        per = {}
                        for pn, (lo, hi) in {"TRAIN": ("1900", "2009-12-31"), "VALID": ("2010-01-01", "2019-12-31"), "TEST": ("2020-01-01", "2026-12-31")}.items():
                            sel = [x for x, dt in zip(evr, dts) if lo <= str(dt.date()) <= hi]
                            per[pn] = (len(sel), round(float(np.mean(sel) - m_all), 2)) if len(sel) >= 3 else None
                        row["per"] = per
                tests.append(row)
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
        summ.append(dict(cell=cell, 시장수=len(valid), 사건합=tot_n, BH통과_양=pos, BH통과_음=neg, 합산초과=None if pooled is None else round(pooled, 2), VALID=pooled_per["VALID"], TEST=pooled_per["TEST"], 통과=ok))
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
    a = ap.parse_args()
    if a.selftest:
        return selftest()
    cfg = json.loads(Path(a.config).read_text(encoding="utf-8"))
    res = run(cfg)
    outp = Path(a.config).with_name(Path(a.config).stem.replace("-config", "") + "-results.json")
    outp.write_text(json.dumps(res, ensure_ascii=False, indent=1, default=float), encoding="utf-8")
    print(f"설정 {res['config']}: 칸 {res['칸']}개, 주 지표 시험 K={res['K']}개(BH 보정). 통과 칸 = BH≤{cfg.get('fdr', 0.05)} 시장 ≥ 절반 ∧ VALID·TEST 같은 부호")
    print(f"{'칸':42s} 시장 사건합 BH양 BH음  합산초과 VALID  TEST 통과")
    for s in sorted(res["요약"], key=lambda x: -(x["BH통과_양"] + x["BH통과_음"])):
        print(f"{s['cell']:42s} {s['시장수']:3d} {s['사건합']:5d} {s['BH통과_양']:3d} {s['BH통과_음']:3d} {str(s['합산초과']):>8s} {str(s['VALID']):>6s} {str(s['TEST']):>6s} {'★' if s['통과'] else ''}")
    print("통과 칸:", [s["cell"] for s in res["요약"] if s["통과"]])
    return 0


if __name__ == "__main__":
    sys.exit(main())
