"""VIX · 공탐지수 · RSI 극단 매매 규칙 (S&P500) — 사전등록 vix-fng-rsi-timing-preregistration-2026-11.md 를 그대로 실행.

    python research/strategy-lab/vix_fng_rsi_timing.py

문턱·창·비용·체결·판정 기준은 사전등록에서 고정. 이 파일에서 바꾸지 않는다.
필요: data/macro/cnn_fear_greed_raw.csv (커밋 안 함), yfinance.
"""
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import yfinance as yf

ROOT = Path(__file__).resolve().parent
FG_CSV = ROOT / "data/macro/cnn_fear_greed_raw.csv"
OUT_JSON = ROOT / "findings/vix-fng-rsi-timing-results.json"
START, END = "2011-01-03", "2026-03-11"
COST = 0.0005            # 전환 1회(편도)당
BOOT, SEED = 2000, 20261103
ALPHA = 0.05 / 6         # 판정 셀 6개 Bonferroni
RULES = {                # 이름: (열, 팔기, 사기)
    "R1 VIX": ("vix", lambda v: v <= 14, lambda v: v >= 20),
    "R2 공탐": ("fg", lambda v: v >= 80, lambda v: v <= 20),
    "R3 RSI": ("rsi", lambda v: v >= 80, lambda v: v <= 30),
}
FRAMES = {"D": dict(ppy=252, blk=21), "W": dict(ppy=52, blk=4)}
ERAS = [("2011~15", 2011, 2015), ("2016~23", 2016, 2023), ("2024", 2024, 2024), ("2025~", 2025, 2026), ("2020", 2020, 2020)]


def rsi14(c):
    d = c.diff()
    up = d.clip(lower=0).ewm(alpha=1 / 14, adjust=False).mean()
    dn = (-d.clip(upper=0)).ewm(alpha=1 / 14, adjust=False).mean()
    return 100 - 100 / (1 + up / dn)


def dl(sym, **kw):
    x = yf.download(sym, auto_adjust=False, progress=False, **kw)
    x.columns = x.columns.get_level_values(0)
    return x


def build_frames():
    px = dl("^GSPC", start="2010-06-01", end="2026-03-12")
    vx = dl("^VIX", start="2010-06-01", end="2026-03-12")
    fg = pd.read_csv(FG_CSV, parse_dates=["date"]).drop_duplicates("date").set_index("date")["fear_and_greed_index"]
    d = pd.DataFrame({"O": px["Open"], "C": px["Close"], "vix": vx["Close"]}).dropna(subset=["O", "C"])
    d["fg"] = fg.reindex(d.index).ffill()      # 거래일 아닌 행은 reindex 로 사라지고, 빠진 날은 직전 값 유지
    d.loc[:"2010-12-31", "fg"] = np.nan
    d["rsi"] = rsi14(d["C"])
    g = d.groupby(pd.Grouper(freq="W-FRI"))
    w = pd.DataFrame({"O": g["O"].first(), "C": g["C"].last(), "vix": g["vix"].last(), "fg": g["fg"].last()}).dropna(subset=["C"])
    w = w[w.index <= pd.Timestamp(END) + pd.Timedelta(days=7)]
    w = w[w.index.map(lambda t: t <= pd.Timestamp(END))]   # 끝이 안 찬 마지막 주봉 제외
    w["rsi"] = rsi14(w["C"])
    return {"D": d, "W": w}


def window(df):
    i0 = df.index.searchsorted(pd.Timestamp(START))
    return df.iloc[i0 - 1:df.index.searchsorted(pd.Timestamp(END), side="right")]   # 첫 줄 = 창 직전 봉(전일 종가용)


def state(x, sell, buy):
    s = np.ones(len(x))
    cur = 1.0
    for i in range(1, len(x)):                  # 0번 = 창 직전 봉, 매수로 시작
        v = x[i]
        if not np.isnan(v):
            if sell(v):
                cur = 0.0
            elif buy(v):
                cur = 1.0
        s[i] = cur
    return s


def returns(O, C, T):
    """T[t] = 봉 t 종가 뒤 목표 포지션. 봉 t 시가에 T[t-1] 로 전환, 시가 이전(밤사이)은 T[t-2]."""
    gon = O[1:] / C[:-1] - 1
    gid = C[1:] / O[1:] - 1
    T1 = T[:-1]                                    # 봉 t(=1..) 의 시가→종가 포지션 = T[t-1]
    T2 = np.r_[1.0, T[:-2]]                        # 밤사이 포지션 = T[t-2]
    r = (1 + T2 * gon) * (1 + T1 * gid) - 1 - COST * np.abs(T1 - T2)
    return r, T1


def metrics(r, idx, ppy):
    eq = np.cumprod(1 + r)
    yrs = (idx[-1] - idx[0]).days / 365.25
    return dict(cagr=eq[-1] ** (1 / yrs) - 1, sharpe=r.mean() / r.std(ddof=1) * np.sqrt(ppy),
                mdd=float((eq / np.maximum.accumulate(eq) - 1).min()), total=eq[-1] - 1)


def boot_dsharpe(rs, rb, blk, ppy, rng):
    n = len(rs)
    nb = int(np.ceil(n / blk))
    out = np.empty(BOOT)
    for b in range(BOOT):
        idx = ((rng.integers(0, n, nb)[:, None] + np.arange(blk)) % n).ravel()[:n]
        a, c = rs[idx], rb[idx]
        out[b] = a.mean() / a.std(ddof=1) - c.mean() / c.std(ddof=1)
    return out * np.sqrt(ppy)


def timing_p(O, C, T, sh_rule, ppy, rng):
    n = len(T) - 1
    hit = 0
    for _ in range(BOOT):
        k = int(rng.integers(21, n - 21))
        Ts = np.r_[1.0, np.roll(T[1:], k)]
        r, _ = returns(O, C, Ts)
        if r.mean() / r.std(ddof=1) * np.sqrt(ppy) >= sh_rule:
            hit += 1
    return (hit + 1) / (BOOT + 1)


def verdict(p, dsh_lo, dsh_pt, cagr_r, cagr_b):
    if p <= ALPHA:
        return "ECONOMIC" if (dsh_lo > 0 and cagr_r >= cagr_b) else "INFORMATION"
    return "REJECT" if dsh_pt <= 0 else "INCONCLUSIVE"


def run_cell(df, col, sell, buy, ppy, blk, rng):
    f = window(df)
    O, C = f["O"].to_numpy(), f["C"].to_numpy()
    T = state(f[col].to_numpy(), sell, buy)
    r, T1 = returns(O, C, T)
    rb = C[1:] / C[:-1] - 1
    idx = f.index[1:]
    mr, mb = metrics(r, idx, ppy), metrics(rb, idx, ppy)
    bt = boot_dsharpe(r, rb, blk, ppy, rng)
    lo99, lo95, hi95 = np.quantile(bt, ALPHA / 2), np.quantile(bt, 0.025), np.quantile(bt, 0.975)
    p = timing_p(O, C, T, mr["sharpe"], ppy, rng)
    dsh = mr["sharpe"] - mb["sharpe"]
    ser = pd.DataFrame({"r": r, "b": rb, "pos": T1}, index=idx)
    yr = ser.groupby(ser.index.year).agg(r=("r", lambda x: (1 + x).prod() - 1), b=("b", lambda x: (1 + x).prod() - 1), pos=("pos", "mean"))
    eras = {}
    for nm, a, z in ERAS:
        s = ser[(ser.index.year >= a) & (ser.index.year <= z)]
        eras[nm] = dict(rule=(1 + s.r).prod() - 1, hold=(1 + s.b).prod() - 1, inmkt=s.pos.mean())
    return dict(rule=mr, hold=mb, dsharpe=dsh, ci95=[lo95, hi95], lo99=lo99, p=p,
                inmkt=float(T1.mean()), trades=int(np.abs(np.diff(T)).sum()), n=len(r),
                verdict=verdict(p, lo99, dsh, mr["cagr"], mb["cagr"]),
                years={int(y): dict(rule=v.r, hold=v.b, inmkt=v.pos) for y, v in yr.iterrows()}, eras=eras)


def hourly():
    try:
        h = dl("^GSPC", period="730d", interval="60m")
        h = h.dropna(subset=["Open", "Close"])
        c = h["Close"]
        f = pd.DataFrame({"O": h["Open"], "C": c, "rsi": rsi14(c)})
        f = f.iloc[1:] if len(f) > 20 else f
        _, sell, buy = RULES["R3 RSI"][0], RULES["R3 RSI"][1], RULES["R3 RSI"][2]
        O, C = f["O"].to_numpy(), f["C"].to_numpy()
        T = state(f["rsi"].to_numpy(), sell, buy)
        r, T1 = returns(O, C, T)
        rb = C[1:] / C[:-1] - 1
        idx = f.index[1:]
        mr, mb = metrics(r, idx, 252 * 7), metrics(rb, idx, 252 * 7)
        return dict(bars=len(r), first=str(idx[0]), last=str(idx[-1]), rule=mr, hold=mb,
                    inmkt=float(T1.mean()), trades=int(np.abs(np.diff(T)).sum()))
    except Exception as e:
        return dict(error=str(e))


def main():
    frames = build_frames()
    rng = np.random.default_rng(SEED)
    res = {}
    for tf, p in FRAMES.items():
        for name, (col, sell, buy) in RULES.items():
            res[f"{name}|{tf}"] = run_cell(frames[tf], col, sell, buy, p["ppy"], p["blk"], rng)
    res["H|R3 RSI"] = hourly()
    OUT_JSON.write_text(json.dumps(res, ensure_ascii=False, indent=1, default=float), encoding="utf-8")
    pct = lambda x: f"{x * 100:+.1f}%"
    print("| 셀 | 판정 | CAGR 규칙/보유 | 샤프 규칙/보유 | ΔSharpe [95% CI] (99.17% 하한) | 타이밍 p | MDD 규칙/보유 | 체류 | 전환 |")
    print("|---|---|---|---|---|---|---|---|---|")
    for k, v in res.items():
        if k.startswith("H|"):
            continue
        print(f"| {k} | **{v['verdict']}** | {pct(v['rule']['cagr'])}/{pct(v['hold']['cagr'])} | {v['rule']['sharpe']:.2f}/{v['hold']['sharpe']:.2f} | "
              f"{v['dsharpe']:+.2f} [{v['ci95'][0]:+.2f}, {v['ci95'][1]:+.2f}] ({v['lo99']:+.2f}) | {v['p']:.4f} | "
              f"{pct(v['rule']['mdd'])}/{pct(v['hold']['mdd'])} | {v['inmkt']*100:.0f}% | {v['trades']} |")
    for k, v in res.items():
        if k.startswith("H|"):
            continue
        print(f"\n### {k} — 연도별 (규칙 / 보유 / 초과 / 체류)")
        print("| " + " | ".join(str(y) for y in v["years"]) + " |")
        print("|" + "---|" * len(v["years"]))
        print("| " + " | ".join(f"{x['rule']*100:+.0f}/{x['hold']*100:+.0f}/{(x['rule']-x['hold'])*100:+.0f}/{x['inmkt']*100:.0f}%" for x in v["years"].values()) + " |")
        print("시기: " + " · ".join(f"{nm} 규칙 {pct(e['rule'])} 보유 {pct(e['hold'])} 체류 {e['inmkt']*100:.0f}%" for nm, e in v["eras"].items()))
        print(f"초과 양(+) 연수: {sum(1 for x in v['years'].values() if x['rule'] > x['hold'])}/{len(v['years'])}")
    print("\n시간봉(기록 전용):", json.dumps(res["H|R3 RSI"], ensure_ascii=False, default=float))


if __name__ == "__main__":
    sys.exit(main())
