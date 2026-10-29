#!/usr/bin/env python3
"""해시 리본(채굴자 항복 국면) → BTC. 사전등록 findings/hash-ribbons-preregistration-2026-10.md.

    python research/strategy-lab/futures/hash_ribbons.py --collect   # blockchain.info hash-rate → data/crypto/onchain/
    python research/strategy-lab/futures/hash_ribbons.py             # 판정
    python research/strategy-lab/futures/hash_ribbons.py --selftest
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import coinbase_premium as cp  # noqa: E402
import coinbase_premium_robustness as rb  # noqa: E402
from crypto_dvol import HALF, dsharpe, perf, shift_null, sized, welch  # noqa: E402  (d4b5851 동결본)

SEED = 20261101
DATA = HERE.parent / "data" / "crypto" / "onchain"
D = pd.Timedelta(days=1)
START, END = pd.Timestamp("2018-01-01", tz="UTC"), pd.Timestamp("2026-10-01", tz="UTC")
LAG = 2


def collect():
    import requests
    DATA.mkdir(parents=True, exist_ok=True)
    r = requests.get("https://api.blockchain.info/charts/hash-rate?timespan=all&format=json&sampled=false", timeout=120)
    r.raise_for_status()
    (DATA / "hashrate.json").write_text(r.text, encoding="utf-8")
    print(len(load_hr()), load_hr().index[-1])


def load_hr() -> pd.Series:
    v = json.loads((DATA / "hashrate.json").read_text(encoding="utf-8"))["values"]
    s = pd.Series({pd.Timestamp(x["x"], unit="s", tz="UTC").normalize(): float(x["y"]) for x in v}, dtype=float).sort_index()
    s = s[~s.index.duplicated(keep="last")]
    return s.reindex(pd.date_range(s.index[0], s.index[-1], freq="D"))


def capitulation(hr: pd.Series) -> pd.Series:
    s30 = hr.rolling(30, min_periods=25).mean()
    s60 = hr.rolling(60, min_periods=50).mean()
    c = (s30 < s60).astype(float)
    return c.where(s30.notna() & s60.notna())


def frame(c: pd.Series, od: pd.Series, lag: int = LAG) -> pd.DataFrame:
    """국면일 d → 관측일 d+lag, r = O(d+lag+1)/O(d+lag) − 1."""
    c = c.dropna()
    t = c.index + lag * D
    r = od.reindex(t + D).to_numpy() / od.reindex(t).to_numpy() - 1
    f = pd.DataFrame({"r": r, "C": c.to_numpy().astype(bool)}, index=t)
    return f[np.isfinite(f["r"]) & (f.index >= START) & (f.index < END)]


def judge(f: pd.DataFrame, rng) -> dict:
    sp = f.index.map(cp.split)
    parts = {k: f[sp == k] for k in ("TRAIN", "VALID", "TEST")}
    tr = parts["TRAIN"]
    d_tr, t_tr = welch(tr["r"].to_numpy(), tr["C"].to_numpy())
    bar = float(np.quantile(np.abs(shift_null(tr["r"].to_numpy(), tr["C"].to_numpy(), lambda r, h: welch(r, h)[1], rng)), 0.95))
    s = np.sign(d_tr)
    diffs = {k: welch(x["r"].to_numpy(), x["C"].to_numpy()) for k, x in parts.items()}
    info = bool(abs(t_tr) >= bar and all(np.sign(diffs[k][0]) == s for k in ("VALID", "TEST")))
    oos = f[sp != "TRAIN"]
    r = oos["r"].to_numpy()
    off = oos["C"].to_numpy() if s < 0 else ~oos["C"].to_numpy()        # 나쁜 국면 = 0x
    ds10, ds20 = dsharpe(r, off, HALF), dsharpe(r, off, 2 * HALF)
    eco = bool(info and ds10 > 0 and ds20 > 0)
    null = shift_null(r, off, dsharpe, rng)
    rob = bool(eco and ds10 > np.quantile(null, 0.95))
    v = "ROBUST" if rob else "ECONOMIC" if eco else "INFORMATION" if info else "REJECT"

    def ds(x):
        o = x["C"].to_numpy() if s < 0 else ~x["C"].to_numpy()
        return round(dsharpe(x["r"].to_numpy(), o), 3)
    return {"verdict": v, "bar_shift95": round(bar, 2), "t_train": round(t_tr, 2), "rule": "항복 날 0x" if s < 0 else "항복 아닌 날 0x",
            "diff_bp(C−nonC)": {k: {"n_C": int(x["C"].sum()), "n": int(len(x)), "bp": round(diffs[k][0], 1), "t": round(diffs[k][1], 2)} for k, x in parts.items()},
            "oos": {"rule": perf(sized(r, off, HALF)), "always_long": perf(sized(r, np.zeros_like(off), HALF)),
                    "dSharpe_net10": round(ds10, 3), "dSharpe_net20": round(ds20, 3), "shift_null_p": round(float((null >= ds10).mean()), 3),
                    "exposure%": round(float((~off).mean() * 100), 1)},
            "periods_dSharpe": {g: ds(x) for g, x in f.groupby(f.index.map(cp.period))},
            "yearly": {int(y): {"C%": round(float(x["C"].mean() * 100), 1), "diff_bp": round(welch(x["r"].to_numpy(), x["C"].to_numpy())[0], 1), "dSharpe": ds(x)}
                       for y, x in f.groupby(f.index.year)}}


def buy_signals(c: pd.Series, od: pd.Series) -> list:
    """항복 뒤 S30 > S60 로 돌아선 다음, 처음으로 가격 10일 평균 > 20일 평균인 날(다음 항복 전 1회)."""
    m10, m20 = od.rolling(10).mean(), od.rolling(20).mean()
    out, armed, was_cap = [], False, False
    for d, v in c.dropna().items():
        if v == 1:
            was_cap, armed = True, False
            continue
        if was_cap:
            armed, was_cap = True, False
        if armed and m10.get(d + D, np.nan) > m20.get(d + D, np.nan):
            out.append(d)
            armed = False
    return out


def main():
    rng = np.random.default_rng(SEED)
    od = rb._read(cp.DATA / "bn_btc.parquet")["open"]
    od = od[od.index.hour == 0]
    hr = load_hr()
    c = capitulation(hr)
    f = frame(c, od)
    out = {"hr_last": str(hr.last_valid_index().date()), "days": int(len(f)), "H1": judge(f, rng)}
    rec = {}
    f0 = frame(c, od, 1)
    rec["lag1"] = {k: dict(zip(("bp", "t"), (round(v, 2) for v in welch(x["r"].to_numpy(), x["C"].to_numpy())))) for k, x in f0.groupby(f0.index.map(cp.split))}
    sig = [d for d in buy_signals(c, od) if START <= d < END]
    base = {h: float(np.nanmean(od.shift(-h).reindex(od.index) / od - 1) * 100) for h in (30, 60, 90)}
    rows = []
    for d in sig:
        t0 = d + LAG * D
        rows.append({"d": str(d.date()), **{f"{h}d%": round(float((od.get(t0 + h * D, np.nan) / od.get(t0, np.nan) - 1) * 100), 1) for h in (30, 60, 90)}})
    rec["H2_buy_signals"] = rows
    rec["H2_mean%"] = {f"{h}d": round(float(np.nanmean([x[f"{h}d%"] for x in rows])), 1) for h in (30, 60, 90)} if rows else {}
    rec["unconditional_mean%(2018~)"] = {f"{h}d": round(v, 1) for h, v in base.items()}
    cc = c.dropna()
    runs = (cc != cc.shift()).cumsum()
    lens = cc.groupby(runs).agg(["first", "size"])
    rec["capitulation_run_days"] = {"n": int((lens["first"] == 1).sum()), "median": float(lens[lens["first"] == 1]["size"].median()),
                                    "max": int(lens[lens["first"] == 1]["size"].max())}
    out["record"] = rec
    (HERE / "hash-ribbons.json").write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
    print(json.dumps(out, ensure_ascii=False, indent=1))


def selftest():
    ok = 0
    days = pd.date_range("2018-01-01", periods=300, freq="D", tz="UTC")
    hr = pd.Series(100.0, index=days)
    hr.iloc[150:180] = 50.0                                        # 30일 급감 → 항복
    c = capitulation(hr)
    assert c.iloc[100] == 0 and c.iloc[175] == 1 and np.isnan(c.iloc[30]); ok += 1
    hr2 = hr.copy(); hr2.iloc[200:] = 1.0
    assert c.iloc[:200].equals(capitulation(hr2).iloc[:200]); ok += 1    # 미래 불변
    od = pd.Series(np.arange(1, 400, dtype=float), index=pd.date_range("2017-12-01", periods=399, freq="D", tz="UTC"))
    f = frame(c, od)
    d = days[175]
    assert f.loc[d + 2 * D, "C"] and abs(f.loc[d + 2 * D, "r"] - (od[d + 3 * D] / od[d + 2 * D] - 1)) < 1e-12; ok += 1
    sig = buy_signals(c, od)
    assert len(sig) == 1 and sig[0] > days[175]; ok += 1             # 항복 뒤 1회, 상승 가격이라 바로 확인
    print(f"selftest {ok}/4 OK")


if __name__ == "__main__":
    if "--selftest" in sys.argv:
        selftest()
    elif "--collect" in sys.argv:
        collect()
    else:
        main()
