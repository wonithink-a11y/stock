#!/usr/bin/env python3
"""차트 타점 기법 54개 × 3배 레버리지(합성 TQQQ·SOXL형) — 사전등록 findings/tech-timing-3x-preregistration-2026-11.md

    python research/strategy-lab/tech_timing_3x.py --selftest
    python research/strategy-lab/tech_timing_3x.py            # 전체 실행 → findings/tech-timing-3x-results.json + 표 출력
"""
import argparse
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parent
CACHE = ROOT / "data" / "tech-timing"
END = "2026-11-06"
COST = 0.001          # 전환 1회
DRAG = 0.03 / 252     # 3배 연 비용
PERIODS = {"TRAIN": ("1900-01-01", "2009-12-31"), "VALID": ("2010-01-01", "2019-12-31"), "TEST": ("2020-01-01", END)}
SEED = 20261108
NPERM = 2000


def load(tk: str) -> pd.DataFrame:
    CACHE.mkdir(parents=True, exist_ok=True)
    f = CACHE / f"{tk.replace('^', '')}.parquet"
    if f.exists():
        return pd.read_parquet(f)
    import yfinance as yf
    d = yf.download(tk, start="1990-01-01", end="2026-11-07", progress=False, auto_adjust=True)
    d.columns = [c[0] if isinstance(c, tuple) else c for c in d.columns]
    d = d[["Open", "High", "Low", "Close"]].dropna()
    d.index = pd.to_datetime(d.index).tz_localize(None)
    d.to_parquet(f)
    return d


# ---------- 지표 ----------
def sma(s, n): return s.rolling(n).mean()
def ema(s, n): return s.ewm(span=n, adjust=False).mean()


def rsi(s, n):
    d = s.diff()
    up = d.clip(lower=0).ewm(alpha=1 / n, adjust=False).mean()
    dn = (-d.clip(upper=0)).ewm(alpha=1 / n, adjust=False).mean()
    return 100 - 100 / (1 + up / dn)


def state(enter: np.ndarray, exit_: np.ndarray) -> np.ndarray:
    """진입/청산 불리언 열 → 상태(0/1). 시작 0. 같은 날 둘 다면 청산 우선."""
    out = np.zeros(len(enter), dtype=np.int8)
    on = 0
    for i in range(len(enter)):
        if on and exit_[i]:
            on = 0
        elif (not on) and enter[i]:
            on = 1
        out[i] = on
    return out


def atr(df, n):
    pc = df["Close"].shift()
    tr = pd.concat([df["High"] - df["Low"], (df["High"] - pc).abs(), (df["Low"] - pc).abs()], axis=1).max(axis=1)
    return tr.ewm(alpha=1 / n, adjust=False).mean()


def supertrend(df, n, mult):
    a = atr(df, n).values
    hl2 = ((df["High"] + df["Low"]) / 2).values
    c = df["Close"].values
    ub, lb = hl2 + mult * a, hl2 - mult * a
    fub, flb = ub.copy(), lb.copy()
    tr = np.ones(len(c), dtype=np.int8)
    for i in range(1, len(c)):
        fub[i] = ub[i] if (ub[i] < fub[i - 1] or c[i - 1] > fub[i - 1]) else fub[i - 1]
        flb[i] = lb[i] if (lb[i] > flb[i - 1] or c[i - 1] < flb[i - 1]) else flb[i - 1]
        if tr[i - 1] == 1 and c[i] < flb[i]: tr[i] = 0
        elif tr[i - 1] == 0 and c[i] > fub[i]: tr[i] = 1
        else: tr[i] = tr[i - 1]
    return tr


def adx_di(df, n=14):
    up = df["High"].diff()
    dn = -df["Low"].diff()
    pdm = np.where((up > dn) & (up > 0), up, 0.0)
    mdm = np.where((dn > up) & (dn > 0), dn, 0.0)
    a = atr(df, n)
    pdi = 100 * pd.Series(pdm, index=df.index).ewm(alpha=1 / n, adjust=False).mean() / a
    mdi = 100 * pd.Series(mdm, index=df.index).ewm(alpha=1 / n, adjust=False).mean() / a
    dx = 100 * (pdi - mdi).abs() / (pdi + mdi)
    return dx.ewm(alpha=1 / n, adjust=False).mean(), pdi, mdi


def psar(df, af0=0.02, afmax=0.2):
    h, l, c = df["High"].values, df["Low"].values, df["Close"].values
    n = len(c)
    sar = np.zeros(n)
    bull = True
    ep = h[0]
    af = af0
    sar[0] = l[0]
    for i in range(1, n):
        s = sar[i - 1] + af * (ep - sar[i - 1])
        if bull:
            s = min(s, l[i - 1], l[i - 2] if i > 1 else l[i - 1])
            if l[i] < s:
                bull, s, ep, af = False, ep, l[i], af0
            elif h[i] > ep:
                ep, af = h[i], min(af + af0, afmax)
        else:
            s = max(s, h[i - 1], h[i - 2] if i > 1 else h[i - 1])
            if h[i] > s:
                bull, s, ep, af = True, ep, h[i], af0
            elif l[i] < ep:
                ep, af = l[i], min(af + af0, afmax)
        sar[i] = s
    return (c > sar).astype(np.int8)


def fib_state(close: pd.Series, k: float, L: int = 126) -> np.ndarray:
    c = close.values
    n = len(c)
    out = np.zeros(n, dtype=np.int8)
    on = 0
    for i in range(n):
        if i < L:
            continue
        w = c[i - L + 1:i + 1]
        ih, il = int(np.argmax(w)), int(np.argmin(w))
        H, Lw = w[ih], w[il]
        R = H - Lw
        if on and (c[i] >= H or c[i] <= Lw):
            on = 0
        elif (not on) and ih > il and R > 0 and c[i] <= H - k * R and c[i] > Lw:
            on = 1
        out[i] = on
    return out


def ichimoku_top(df):
    h, l = df["High"], df["Low"]
    ten = (h.rolling(9).max() + l.rolling(9).min()) / 2
    kij = (h.rolling(26).max() + l.rolling(26).min()) / 2
    sa = ((ten + kij) / 2).shift(26)
    sb = ((h.rolling(52).max() + l.rolling(52).min()) / 2).shift(26)
    return ten, kij, pd.concat([sa, sb], axis=1).max(axis=1)


def stoch(df, n=14, k=3, d=3):
    ll, hh = df["Low"].rolling(n).min(), df["High"].rolling(n).max()
    raw = 100 * (df["Close"] - ll) / (hh - ll)
    kk = raw.rolling(k).mean()
    return kk, kk.rolling(d).mean()


def build_rules(df: pd.DataFrame, vix: pd.Series) -> dict:
    c = df["Close"]
    idx = df.index
    R: dict[str, np.ndarray] = {}
    b = lambda s: s.fillna(False).values.astype(bool)
    for n in (20, 50, 100, 150, 200): R[f"SMA추세{n}"] = (c > sma(c, n)).fillna(False).values.astype(np.int8)
    for f, s in ((10, 50), (20, 60), (20, 120), (50, 150), (50, 200)):
        R[f"SMA교차{f}/{s}"] = (sma(c, f) > sma(c, s)).fillna(False).values.astype(np.int8)
    for n in (20, 50, 100, 200): R[f"EMA추세{n}"] = (c > ema(c, n)).values.astype(np.int8)
    macd = ema(c, 12) - ema(c, 26)
    sig = ema(macd, 9)
    R["MACD>시그널"] = (macd > sig).values.astype(np.int8)
    R["MACD>0"] = (macd > 0).values.astype(np.int8)
    r14, r2 = rsi(c, 14), rsi(c, 2)
    R["RSI14역추세<30/>55"] = state(b(r14 < 30), b(r14 > 55))
    R["RSI14역추세<40/>60"] = state(b(r14 < 40), b(r14 > 60))
    R["RSI2역추세<10/>60"] = state(b(r2 < 10), b(r2 > 60))
    R["RSI14>50"] = (r14 > 50).fillna(False).values.astype(np.int8)
    R["RSI14추세>55/<45"] = state(b(r14 > 55), b(r14 < 45))
    m20, sd = sma(c, 20), c.rolling(20).std()
    up, lo = m20 + 2 * sd, m20 - 2 * sd
    R["볼린저역추세"] = state(b(c < lo), b(c > m20))
    R["볼린저돌파"] = state(b(c > up), b(c < m20))
    for N, M in ((20, 10), (55, 20), (100, 50), (200, 100)):
        hi = c.shift().rolling(N).max()
        lw = c.shift().rolling(M).min()
        R[f"돈치안{N}/{M}"] = state(b(c > hi), b(c < lw))
    for k in (0.382, 0.5, 0.618): R[f"피보나치{k}"] = fib_state(c, k)
    kk, dd = stoch(df)
    cross_up = (kk > dd) & (kk.shift() <= dd.shift())
    R["스토캐스틱교차<20/>80"] = state(b(cross_up & (kk < 20)), b(kk > 80))
    R["스토캐스틱K>D"] = (kk > dd).fillna(False).values.astype(np.int8)
    ten, kij, top = ichimoku_top(df)
    R["일목구름상단"] = (c > top).fillna(False).values.astype(np.int8)
    R["일목전환>기준+구름"] = ((ten > kij) & (c > top)).fillna(False).values.astype(np.int8)
    R["슈퍼트렌드10x3"] = supertrend(df, 10, 3.0)
    R["슈퍼트렌드14x2"] = supertrend(df, 14, 2.0)
    adx, pdi, mdi = adx_di(df)
    R["ADX>25&+DI>-DI"] = ((adx > 25) & (pdi > mdi)).fillna(False).values.astype(np.int8)
    R["+DI>-DI"] = (pdi > mdi).fillna(False).values.astype(np.int8)
    R["파라볼릭SAR"] = psar(df)
    R["모멘텀12-1"] = (c.shift(21) / c.shift(252) - 1 > 0).fillna(False).values.astype(np.int8)
    R["모멘텀126"] = (c / c.shift(126) - 1 > 0).fillna(False).values.astype(np.int8)
    R["모멘텀63"] = (c / c.shift(63) - 1 > 0).fillna(False).values.astype(np.int8)
    rv = c.pct_change().rolling(20).std()
    R["변동성<중앙값"] = (rv < rv.rolling(252).median()).fillna(False).values.astype(np.int8)
    dd252 = c / c.rolling(252).max() - 1
    R["낙폭필터-10/-5"] = state(b(dd252 > -0.05), b(dd252 < -0.10))
    R["낙폭필터-20/-10"] = state(b(dd252 > -0.10), b(dd252 < -0.20))
    R["52주고점0.90"] = (c >= 0.90 * c.rolling(252).max()).values.astype(np.int8)
    R["52주고점0.95"] = (c >= 0.95 * c.rolling(252).max()).values.astype(np.int8)
    R["11~4월보유"] = (~pd.Series(idx.month, index=idx).isin([5, 6, 7, 8, 9, 10])).values.astype(np.int8)
    ym = pd.Series(idx.year * 100 + idx.month, index=idx)
    pos = ym.groupby(ym).cumcount()
    rem = ym.groupby(ym).cumcount(ascending=False)
    R["월말월초5일"] = ((pos < 5) | (rem < 5)).values.astype(np.int8)
    v = vix.reindex(idx).ffill()
    R["VIX<20"] = (v < 20).values.astype(np.int8)
    R["VIX<25"] = (v < 25).values.astype(np.int8)
    R["VIX<VIX50일선"] = (v < sma(v, 50)).fillna(False).values.astype(np.int8)
    s200 = sma(c, 200)
    R["눌림:SMA200위RSI14<40"] = state(b((c > s200) & (r14 < 40)), b((r14 > 60) | (c < s200)))
    s120 = sma(c, 120)
    R["눌림:SMA120위+20일선아래"] = state(b((c > s120) & (c < m20)), b((c > m20 * 1.03) | (c < s120)))
    return R


# ---------- 평가 ----------
def lev_ret(close: pd.Series) -> np.ndarray:
    return (3 * close.pct_change() - DRAG).fillna(0.0).values


def strat_ret(pos: np.ndarray, r3: np.ndarray) -> np.ndarray:
    p = np.concatenate([[0], pos[:-1]]).astype(float)   # t 신호 → t+1 수익
    sw = np.abs(np.diff(np.concatenate([[0.0], p])))
    return p * r3 - sw * COST


def metrics(r: np.ndarray, pos_slice: np.ndarray):
    if len(r) < 50:
        return None
    eq = np.cumprod(1 + r)
    yrs = len(r) / 252
    cagr = (eq[-1] ** (1 / yrs) - 1) * 100 if eq[-1] > 0 else -100.0
    sh = r.mean() / r.std() * np.sqrt(252) if r.std() > 0 else 0.0
    mdd = (eq / np.maximum.accumulate(np.concatenate([[1.0], eq]))[1:] - 1).min() * 100
    sw = np.abs(np.diff(pos_slice)).sum()
    return dict(cagr=round(cagr, 1), sharpe=round(sh, 3), mdd=round(mdd, 1), inm=round(pos_slice.mean() * 100), sw=round(sw / yrs, 1))


def perm_p(pos, r3, a, b, rng):
    """구간 [a,b) 포지션 순환이동 순열 p."""
    rs = lambda p: strat_ret(p, r3)[a:b]
    base = rs(pos)
    obs = base.mean() / base.std() if base.std() > 0 else 0.0
    seg = pos[a:b]
    n = len(seg)
    cnt = 0
    for _ in range(NPERM):
        k = int(rng.integers(1, n))
        sh = pos.copy()
        sh[a:b] = np.roll(seg, k)
        x = rs(sh)
        s = x.mean() / x.std() if x.std() > 0 else 0.0
        if s >= obs:
            cnt += 1
    return (1 + cnt) / (1 + NPERM)


def evaluate(df: pd.DataFrame, vix: pd.Series, name: str):
    idx = df.index
    r3 = lev_ret(df["Close"])
    R = build_rules(df, vix)
    start = 252
    bh = np.ones(len(idx), dtype=np.int8)
    rng = np.random.default_rng(SEED)
    bounds = {}
    for k, (s, e) in PERIODS.items():
        m = (idx >= s) & (idx <= e)
        ii = np.where(m)[0]
        ii = ii[ii >= start]
        bounds[k] = (ii[0], ii[-1] + 1) if len(ii) else None
    res = {}
    bh_r = strat_ret(bh, r3)
    bh_m = {k: metrics(bh_r[a:b], bh[a:b]) for k, (a, b) in bounds.items() if bounds[k]}
    for rn, pos in R.items():
        sr = strat_ret(pos, r3)
        row = {}
        for k, bd in bounds.items():
            if not bd:
                continue
            a, b = bd
            m = metrics(sr[a:b], pos[a:b])
            m["dSharpe"] = round(m["sharpe"] - bh_m[k]["sharpe"], 3)
            m["p"] = perm_p(pos, r3, a, b, rng)
            row[k] = m
        res[rn] = row
    return res, bh_m, bounds


def classify(row: dict, bh_m: dict) -> str:
    ks = [k for k in ("TRAIN", "VALID", "TEST") if k in row]
    if len(ks) == 3 and all(row[k]["dSharpe"] >= 0.10 and row[k]["p"] <= 0.01 for k in ks):
        return "ROBUST"
    if all(k in row and row[k]["dSharpe"] >= 0.10 and row[k]["p"] <= 0.01 for k in ("VALID", "TEST")):
        return "INFORMATION"
    return "REJECT"


def tool_flag(row, bh_m):
    ks = [k for k in ("TRAIN", "VALID", "TEST") if k in row]
    return len(ks) == 3 and all(row[k]["mdd"] >= 0.6 * bh_m[k]["mdd"] and row[k]["sharpe"] >= 0.9 * bh_m[k]["sharpe"] for k in ks)


def selftest() -> int:
    fails = []
    def ck(n, c):
        print(("ok   " if c else "FAIL ") + n)
        if not c: fails.append(n)
    e = np.array([0, 1, 0, 0, 0, 0], bool); x = np.array([0, 0, 0, 1, 0, 0], bool)
    ck("상태기계 진입→청산", state(e, x).tolist() == [0, 1, 1, 0, 0, 0])
    both = np.array([1, 1], bool)
    ck("같은 날 진입·청산이면 청산 우선(켜진 상태에서)", state(np.array([1, 1], bool), np.array([0, 1], bool)).tolist() == [1, 0])
    r3 = np.array([0.0, 0.10, -0.10, 0.10])
    pos = np.array([1, 1, 0, 0], dtype=np.int8)
    sr = strat_ret(pos, r3)
    ck("t 신호는 t+1 수익부터, 진입·청산 비용", np.allclose(sr, [0, 0.10 - COST, -0.10, -COST]))
    ck("보유 수익 = 첫 진입 비용 외 레버 수익", np.allclose(strat_ret(np.ones(4, np.int8), r3), [0, 0.10 - COST, -0.10, 0.10]))
    c = pd.Series(np.linspace(100, 200, 400))
    ck("RSI 단조상승 → 100 근처", rsi(c, 14).iloc[-1] > 99)
    ck("3배 일수익 = 3×r − 비용", abs(lev_ret(pd.Series([100.0, 101.0]))[1] - (3 * 0.01 - DRAG)) < 1e-12)
    print("FAIL" if fails else "OK")
    return 1 if fails else 0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--selftest", action="store_true")
    a = ap.parse_args()
    if a.selftest:
        return selftest()
    vix = load("^VIX")["Close"]
    out = {}
    for name, tk, real in (("NDX3x(TQQQ형)", "^NDX", "TQQQ"), ("SOX3x(SOXL형)", "^SOX", "SOXL")):
        df = load(tk)
        df = df[df.index <= END]
        res, bh_m, bounds = evaluate(df, vix, name)
        # 합성 검증
        rp = pd.read_parquet(ROOT / "data" / "leveraged-etf" / f"{real}.parquet").set_index("date")["close"]
        syn = (3 * df["Close"].pct_change() - DRAG).dropna()
        rr = rp.pct_change().dropna()
        j = pd.concat([syn, rr], axis=1, join="inner").dropna()
        j.columns = ["syn", "real"]
        valid = dict(corr=round(float(j.corr().iloc[0, 1]), 4), n=len(j),
                     cum_syn=round(float((1 + j["syn"]).prod()), 2), cum_real=round(float((1 + j["real"]).prod()), 2))
        cls = {k: classify(v, bh_m) for k, v in res.items()}
        tools = [k for k, v in res.items() if tool_flag(v, bh_m)]
        out[name] = dict(bh=bh_m, rules=res, cls=cls, tools=tools, synth_check=valid,
                         bounds={k: [str(df.index[a]), str(df.index[b - 1])] for k, (a, b) in bounds.items() if bounds[k]})
        print(f"\n=== {name} 합성검증 {valid}")
        print("보유", {k: (v['cagr'], v['sharpe'], v['mdd']) for k, v in bh_m.items()})
        from collections import Counter
        print("판정 수", dict(Counter(cls.values())), " 낙폭도구:", tools)
        top = sorted(res.items(), key=lambda kv: -min(kv[1][k]["dSharpe"] for k in kv[1]))[:12]
        print("세 구간 최소 ΔSharpe 상위 12")
        for rn, v in top:
            print(f"  {rn:22s} " + " | ".join(f"{k} Δ{v[k]['dSharpe']:+.2f} p{v[k]['p']:.3f} CAGR{v[k]['cagr']:.0f} MDD{v[k]['mdd']:.0f}" for k in v) + f" → {cls[rn]}")
    (ROOT / "findings" / "tech-timing-3x-results.json").write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main())
