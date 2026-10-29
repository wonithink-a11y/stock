#!/usr/bin/env python3
"""크립토 내재변동성(Deribit DVOL) → BTC. 사전등록 findings/crypto-dvol-preregistration-2026-10.md.

    python research/strategy-lab/futures/crypto_dvol.py --collect   # Deribit DVOL(BTC·ETH) → data/crypto/dvol/
    python research/strategy-lab/futures/crypto_dvol.py             # 판정
    python research/strategy-lab/futures/crypto_dvol.py --selftest
"""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import coinbase_premium as cp  # noqa: E402  split·period·judge 그대로(20401a4)
import coinbase_premium_robustness as rb  # noqa: E402
from short_horizon_study import null_bar, tstat  # noqa: E402

SEED = 20261030
DATA = HERE.parent / "data" / "crypto" / "dvol"
D = pd.Timedelta(days=1)
START, END = pd.Timestamp("2021-03-01", tz="UTC"), pd.Timestamp("2026-10-01", tz="UTC")
PWIN, PMIN, PCUT = 365, 180, 0.8          # V1
ZWIN, ZMIN = 365, 180                     # V2
CWIN, CMIN, ZTH, HOLD3 = 90, 60, 2.0, 3   # V3
RVH, RVMIN = 720, 600
HALF = 5.0                                # 편도 bp (왕복 10)
N_NULL = 500


# ---------- 수집 ----------
def _dvol(cur: str) -> tuple[pd.Series, dict]:
    import requests
    out, diag = {}, {"calls": 0, "out_of_window": 0}
    t = START
    while t < END:
        e = min(t + 500 * D, END)
        url = ("https://www.deribit.com/api/v2/public/get_volatility_index_data"
               f"?currency={cur}&resolution=1D&start_timestamp={int(t.timestamp() * 1000)}&end_timestamp={int(e.timestamp() * 1000) - 1}")
        for k in range(6):
            r = requests.get(url, timeout=60)
            if r.status_code == 200:
                break
            time.sleep(2 ** k)
        r.raise_for_status()
        diag["calls"] += 1
        for ts, _o, _h, _l, c in r.json()["result"]["data"]:
            ts = pd.Timestamp(ts, unit="ms", tz="UTC")
            if not (t <= ts < e):            # 응답이 요청 구간에 답했는지 (교훈81)
                diag["out_of_window"] += 1
                continue
            out[ts] = float(c)
        t = e
        time.sleep(0.2)
    s = pd.Series(out, dtype=float).sort_index()
    diag.update(first=str(s.index[0].date()), last=str(s.index[-1].date()), days=int(len(s)))
    return s, diag


def collect():
    DATA.mkdir(parents=True, exist_ok=True)
    diag = {}
    for cur in ("BTC", "ETH"):
        s, diag[cur] = _dvol(cur)
        s.rename("close").to_frame().to_parquet(DATA / f"dvol_{cur.lower()}.parquet")
    (DATA / "_diagnostics.json").write_text(json.dumps(diag, ensure_ascii=False, indent=1), encoding="utf-8")
    print(diag)


def load_dvol(cur: str) -> pd.Series:
    s = rb._read(DATA / f"dvol_{cur.lower()}.parquet")["close"]
    return s.reindex(pd.date_range(s.index[0], s.index[-1], freq="D"))   # 빠진 날은 결측


# ---------- 계산 ----------
def daily_open(h: pd.DataFrame) -> pd.Series:
    o = h["open"]
    return o[o.index.hour == 0]


def rv30(h: pd.DataFrame) -> pd.Series:
    """day d → [d−29 00:00, d+1 00:00) 시간 봉 종가 로그수익으로 연율 %."""
    c = h["close"].reindex(pd.date_range(h.index[0], h.index[-1], freq="h"))
    r2 = np.log(c / c.shift(1)) ** 2
    roll = r2.rolling(RVH, min_periods=RVMIN)
    rv = np.sqrt(roll.mean() * 24 * 365) * 100
    rv = rv[rv.index.hour == 23]
    rv.index = rv.index.normalize()
    return rv


def pct_past(x: pd.Series, win: int, minp: int) -> pd.Series:
    """x(d) 가 직전 win 일(현재 제외, 유효 minp) 값들 중 차지하는 백분위(작은 값 비율)."""
    a = x.to_numpy()
    out = np.full(len(a), np.nan)
    for i in range(len(a)):
        if not np.isfinite(a[i]):
            continue
        p = a[max(0, i - win):i]
        p = p[np.isfinite(p)]
        if len(p) >= minp:
            out[i] = (p < a[i]).mean()
    return pd.Series(out, index=x.index)


def z_past(x: pd.Series, win: int, minp: int) -> pd.Series:
    past = x.shift(1).rolling(win, min_periods=minp)
    return (x - past.mean()) / past.std()


def next_ret(od: pd.Series, d: pd.DatetimeIndex, h: int) -> np.ndarray:
    """신호일 d → O(d+1+h)/O(d+1) − 1."""
    return od.reindex(d + (1 + h) * D).to_numpy() / od.reindex(d + D).to_numpy() - 1


def v1_frame(dv: pd.Series, od: pd.Series, cut: float = PCUT) -> pd.DataFrame:
    """진입일(d+1) 인덱스: r = 그날 일수익, H = 전날 신호."""
    p = pct_past(dv, PWIN, PMIN)
    p = p[p.notna()]
    r = next_ret(od, p.index, 1)
    f = pd.DataFrame({"r": r, "H": (p >= cut).to_numpy()}, index=p.index + D)
    return f[np.isfinite(f["r"]) & (f.index < END)]


def welch(r: np.ndarray, H: np.ndarray) -> tuple[float, float]:
    a, b = r[H], r[~H]
    if len(a) < 3 or len(b) < 3:
        return 0.0, 0.0
    diff = a.mean() - b.mean()
    return float(diff * 1e4), float(diff / np.sqrt(a.var(ddof=1) / len(a) + b.var(ddof=1) / len(b)))


def shift_null(r: np.ndarray, H: np.ndarray, fn, rng, n: int = N_NULL) -> np.ndarray:
    m = len(H)
    return np.array([fn(r, np.roll(H, int(rng.integers(30, m - 30)))) for _ in range(n)])


def sized(r: np.ndarray, H: np.ndarray, half: float, w0: float = 0.0) -> np.ndarray:
    """H 날 w0x, 나머지 1x. 전환(첫날 진입 포함)마다 |Δw| × 편도 비용."""
    w = np.where(H, w0, 1.0)
    dw = np.abs(np.diff(np.r_[0.0, w]))
    return w * r - dw * half / 1e4


def sharpe(x: np.ndarray) -> float:
    return float(x.mean() / x.std(ddof=1) * np.sqrt(365)) if len(x) > 2 and x.std(ddof=1) > 0 else 0.0


def perf(x: np.ndarray) -> dict:
    eq = np.cumprod(1 + x)
    return {"ann_ret%": round(float((eq[-1] ** (365 / len(x)) - 1) * 100), 1), "ann_vol%": round(float(x.std(ddof=1) * np.sqrt(365) * 100), 1),
            "sharpe": round(sharpe(x), 3), "mdd%": round(float((eq / np.maximum.accumulate(eq) - 1).min() * 100), 1)}


def dsharpe(r: np.ndarray, H: np.ndarray, half: float = HALF) -> float:
    return sharpe(sized(r, H, half)) - sharpe(sized(r, np.zeros_like(H), half))


def judge_v1(f: pd.DataFrame, rng) -> dict:
    sp = f.index.map(cp.split)
    parts = {k: f[sp == k] for k in ("TRAIN", "VALID", "TEST")}
    tr = parts["TRAIN"]
    d_tr, t_tr = welch(tr["r"].to_numpy(), tr["H"].to_numpy())
    bar = float(np.quantile(np.abs(shift_null(tr["r"].to_numpy(), tr["H"].to_numpy(), lambda r, h: welch(r, h)[1], rng)), 0.95))
    s = np.sign(d_tr)
    diffs = {k: welch(x["r"].to_numpy(), x["H"].to_numpy()) for k, x in parts.items()}
    info = bool(abs(t_tr) >= bar and all(np.sign(diffs[k][0]) == s for k in ("VALID", "TEST")))
    oos = f[sp != "TRAIN"]
    r, H = oos["r"].to_numpy(), oos["H"].to_numpy()
    ds10, ds20 = dsharpe(r, H, HALF), dsharpe(r, H, 2 * HALF)
    eco = bool(info and s < 0 and ds10 > 0 and ds20 > 0)
    null = shift_null(r, H, dsharpe, rng)
    rob = bool(eco and ds10 > np.quantile(null, 0.95))
    v = "ROBUST" if rob else "ECONOMIC" if eco else "INFORMATION" if info else "REJECT"
    return {"verdict": v, "bar_shift95": round(bar, 2), "t_train": round(t_tr, 2),
            "diff_bp(H−nonH)": {k: {"n_H": int(x["H"].sum()), "n": int(len(x)), "bp": round(diffs[k][0], 1), "t": round(diffs[k][1], 2)} for k, x in parts.items()},
            "oos": {"rule": perf(sized(r, H, HALF)), "always_long": perf(sized(r, np.zeros_like(H), HALF)),
                    "dSharpe_net10": round(ds10, 3), "dSharpe_net20": round(ds20, 3),
                    "shift_null_p": round(float((null >= ds10).mean()), 3), "exposure%": round(float((~H).mean() * 100), 1),
                    "switches": int(np.abs(np.diff(np.r_[0.0, np.where(H, 0.0, 1.0)])).sum())},
            "periods_dSharpe": {g: round(dsharpe(x["r"].to_numpy(), x["H"].to_numpy()), 3) for g, x in f.groupby(f.index.map(cp.period))},
            "yearly": {int(y): {"H%": round(float(x["H"].mean() * 100), 1), "diff_bp": round(welch(x["r"].to_numpy(), x["H"].to_numpy())[0], 1),
                                "dSharpe": round(dsharpe(x["r"].to_numpy(), x["H"].to_numpy()), 3)} for y, x in f.groupby(f.index.year)}}


def v2_series(dv: pd.Series, rv: pd.Series, od: pd.Series) -> tuple[pd.Series, pd.Series]:
    vrp = (dv - rv.reindex(dv.index)).dropna()
    vrp = vrp.reindex(pd.date_range(vrp.index[0], vrp.index[-1], freq="D"))
    z = z_past(vrp, ZWIN, ZMIN)
    z = z[(z.index.dayofweek == 6) & z.notna()]
    r = next_ret(od, z.index, 7)
    s = pd.Series(np.sign(z.to_numpy()) * r * 1e4, index=z.index + D)
    return s[np.isfinite(s) & (s.index < END)], vrp


def v3_series(dv: pd.Series, od: pd.Series, h: int = HOLD3, side: int = 0) -> pd.Series:
    c = np.log(dv / dv.shift(1))
    z = z_past(c, CWIN, CMIN)
    out, free = {}, None
    for d, v in z[z.abs() >= ZTH].items():
        if side and np.sign(v) != side:
            continue
        t0 = d + D
        if free is not None and t0 < free:
            continue
        p0, p1 = od.get(t0, np.nan), od.get(t0 + h * D, np.nan)
        if not (np.isfinite(p0) and np.isfinite(p1)) or t0 + h * D > END:
            continue
        out[t0] = np.sign(v) * (p1 / p0 - 1) * 1e4
        free = t0 + h * D
    return pd.Series(out, dtype=float)


def brief(r: pd.Series) -> dict:
    return {k: {"n": int(len(x)), "bp": round(float(x.mean()), 1), "t": round(tstat(x.to_numpy()), 2)} for k, x in r.groupby(r.index.map(cp.split))}


def run(cur: str, hourly: pd.DataFrame, rng, full: bool) -> dict:
    dv = load_dvol(cur)
    dv = dv[dv.index < END]
    od = daily_open(hourly)
    rv = rv30(hourly)
    f1 = v1_frame(dv, od)
    s2, vrp = v2_series(dv, rv, od)
    s3 = v3_series(dv, od)
    bar = null_bar([x[x.index.map(cp.split) == "TRAIN"].to_numpy() for x in (s2, s3)], rng)
    out = {"dvol_first": str(dv.first_valid_index().date()), "dvol_days": int(dv.notna().sum()), "bar_V2V3": round(bar, 2),
           "V1": judge_v1(f1, rng), "V2": cp.judge(s2, bar), "V3": cp.judge(s3, bar)}
    if not full:
        return out
    sg3 = int(np.sign(s3[s3.index.map(cp.split) == "TRAIN"].mean()) or 1)
    rec = {}
    for cut in (0.9, 0.7):
        g = v1_frame(dv, od, cut)
        o = g[g.index.map(cp.split) != "TRAIN"]
        rec[f"V1_cut{cut}"] = {"t_train": round(welch(*(g[g.index.map(cp.split) == "TRAIN"][c].to_numpy() for c in ("r", "H")))[1], 2),
                               "oos_dSharpe_net10": round(dsharpe(o["r"].to_numpy(), o["H"].to_numpy()), 3)}
    o = f1[f1.index.map(cp.split) != "TRAIN"]
    r, H = o["r"].to_numpy(), o["H"].to_numpy()
    rec["V1_half_size_oos"] = {"rule": perf(sized(r, H, HALF, 0.5)), "dSharpe": round(sharpe(sized(r, H, HALF, 0.5)) - sharpe(sized(r, np.zeros_like(H), HALF)), 3)}
    rec["V3_hold1"] = brief(v3_series(dv, od, 1))
    rec["V3_dvol_up(z≥2)"] = brief(v3_series(dv, od, side=1))
    rec["V3_dvol_down(z≤−2)"] = brief(v3_series(dv, od, side=-1))
    rec["V3_train_sign"] = sg3
    rec["dvol_quantiles"] = {q: round(float(dv.quantile(q)), 1) for q in (0.05, 0.25, 0.5, 0.75, 0.95)}
    rec["vrp_mean_by_year"] = {int(y): round(float(x.mean()), 1) for y, x in vrp.groupby(vrp.index.year)}
    rec["H_share_by_year%"] = {int(y): round(float(x["H"].mean() * 100), 1) for y, x in f1.groupby(f1.index.year)}
    out["record"] = rec
    return out


def legs_v2(s2: pd.Series, dv: pd.Series, rv: pd.Series) -> dict:
    vrp = (dv - rv.reindex(dv.index))
    z = z_past(vrp.reindex(pd.date_range(vrp.index[0], vrp.index[-1], freq="D")), ZWIN, ZMIN)
    sg = np.sign(z.reindex(s2.index - D).to_numpy())
    return {"VRP high(z≥0, 롱)": brief(s2[sg > 0]), "VRP low(z<0, 숏)": brief(s2[sg < 0])}


def main():
    rng = np.random.default_rng(SEED)
    btc = rb._read(cp.DATA / "bn_btc.parquet")
    out = run("BTC", btc, rng, True)
    dv, rv = load_dvol("BTC"), rv30(btc)
    dv = dv[dv.index < END]
    s2, _ = v2_series(dv, rv, daily_open(btc))
    out["record"]["V2_legs"] = legs_v2(s2, dv, rv)
    # 다른 신호인가: 코인베이스 프리미엄 z 일 평균 · 스테이블코인 발행 z
    import stablecoin_supply_btc as sb
    cb = rb._read(cp.DATA / "cb_btc.parquet")
    zc = cp.zscore(cp.premium(cb, btc))
    zc_d = zc.groupby(zc.index.normalize()).mean()
    zs = sb.zscore(sb.load_supply("all"))
    j = pd.concat([dv.rename("dvol"), (dv - rv.reindex(dv.index)).rename("vrp"), zc_d.rename("cbz"), zs.rename("stz")], axis=1).dropna()
    out["record"]["corr"] = {k: round(float(v), 3) for k, v in
                             {"dvol~cbz": j["dvol"].corr(j["cbz"]), "dvol~stablez": j["dvol"].corr(j["stz"]),
                              "vrp~cbz": j["vrp"].corr(j["cbz"]), "dvol~rv30": dv.corr(rv.reindex(dv.index))}.items()}
    eth = rb._read(cp.DATA / "alts" / "ETH_bn.parquet")
    out["record"]["ETH"] = run("ETH", eth, np.random.default_rng(SEED + 1), False)
    (HERE / "crypto-dvol.json").write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
    print(json.dumps(out, ensure_ascii=False, indent=1))


def selftest():
    ok = 0
    x = pd.Series([1.0, 2.0, 3.0, 4.0, 2.5], index=pd.date_range("2022-01-01", periods=5, freq="D", tz="UTC"))
    p = pct_past(x, 3, 2)
    assert np.isnan(p.iloc[1]) and p.iloc[2] == 1.0 and abs(p.iloc[4] - 1 / 3) < 1e-12; ok += 1   # 현재 제외, 작은 값 비율
    hrs = pd.date_range("2021-01-01", periods=24 * 60, freq="h", tz="UTC")
    rng = np.random.default_rng(1)
    c = pd.Series(100 * np.exp(np.cumsum(rng.normal(0, 0.01, len(hrs)))), index=hrs)
    h = pd.DataFrame({"open": c.shift(1).fillna(100.0), "close": c})
    rv = rv30(h)
    assert abs(rv.dropna().iloc[-1] - 0.01 * np.sqrt(24 * 365) * 100) < 15; ok += 1                   # 1%/h → ≈ 94%
    c2 = c.copy(); c2.iloc[-24:] *= 2
    rv2 = rv30(pd.DataFrame({"open": h["open"], "close": c2}))
    assert np.allclose(rv.iloc[:-1].dropna(), rv2.iloc[:-1].dropna()); ok += 1                          # 마지막 날 바꿔도 앞날 RV 불변
    od = pd.Series(100.0, index=pd.date_range("2021-01-01", periods=30, freq="D", tz="UTC"))
    od.iloc[5] = 110.0                                                                                 # O(01-06)
    r = next_ret(od, pd.DatetimeIndex([od.index[3]]), 2)                                               # 신호 01-04 → O(01-07)/O(01-05)
    assert abs(r[0] - 0.0) < 1e-12 and abs(next_ret(od, pd.DatetimeIndex([od.index[3]]), 1)[0] - 0.1) < 1e-12; ok += 1
    rr = np.array([0.01, -0.02, 0.03, 0.0])
    HH = np.array([False, True, True, False])
    got = sized(rr, HH, 5.0)
    assert np.allclose(got, [0.01 - 0.0005, -0.0005, 0.0, -0.0005]); ok += 1                           # 진입·청산·재진입 비용
    dv = pd.Series(50.0, index=pd.date_range("2021-01-01", periods=200, freq="D", tz="UTC")) + rng.normal(0, 1, 200)
    dv.iloc[150] = 90.0
    od2 = pd.Series(100.0, index=pd.date_range("2021-01-01", periods=220, freq="D", tz="UTC"))
    od2.iloc[154] = 103.0                                                                              # 진입 d+1=151, 3일 뒤 154
    s3 = v3_series(dv, od2)
    t0 = dv.index[150] + D
    assert t0 in s3.index and abs(s3[t0] - 300.0) < 1e-6; ok += 1
    assert ((s3.index[1:] - s3.index[:-1]) >= 3 * D).all(); ok += 1
    print(f"selftest {ok}/7 OK")


if __name__ == "__main__":
    if "--selftest" in sys.argv:
        selftest()
    elif "--collect" in sys.argv:
        collect()
    else:
        main()
