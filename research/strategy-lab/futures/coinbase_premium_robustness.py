#!/usr/bin/env python3
"""코인베이스 프리미엄 C24 — 강건성(K1~K4)·알트 재현(R1). 사전등록 findings/coinbase-premium-robustness-preregistration-2026-10.md.

    python research/strategy-lab/futures/coinbase_premium_robustness.py --collect   # 알트 24종 + 업비트 KRW-BTC
    python research/strategy-lab/futures/coinbase_premium_robustness.py             # 판정
    python research/strategy-lab/futures/coinbase_premium_robustness.py --selftest
"""
from __future__ import annotations

import json
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import coinbase_premium as cp  # noqa: E402  원 규칙 — 고치지 않고 불러 쓴다
from crypto_rv_jump import _ms, _read_zip  # noqa: E402
from short_horizon_study import tstat  # noqa: E402

SEED = 20261030
ALTS = cp.DATA / "alts"
H, HOLD, COST = cp.H, 24, cp.COST
OOS_FROM = pd.Timestamp("2023-01-01", tz="UTC")
ADJ_FROM = pd.Timestamp("2021-05-19", tz="UTC")
COINS = {c: (c, c) for c in ["AAVE", "ADA", "APT", "ARB", "ATOM", "AVAX", "BCH", "BNB", "DOGE", "DOT", "ETH", "FIL", "INJ",
                             "LINK", "LTC", "NEAR", "OP", "SOL", "SUI", "UNI", "WLD", "ZEC"]}
COINS.update({"1000PEPE": ("PEPE", "PEPE"), "1000SHIB": ("SHIB", "SHIB")})   # (코인베이스 base, 바이낸스 base)
N_BOOT = 2000


# ---------- 수집 ----------
def _bn_spot(base: str) -> pd.DataFrame:
    import requests
    frames = []
    for m in pd.period_range(cp.START.strftime("%Y-%m"), (cp.END - H).strftime("%Y-%m"), freq="M"):
        raw = ALTS / "raw" / f"{base}USDT-1h-{m}.zip"
        if not raw.exists():
            r = requests.get(f"https://data.binance.vision/data/spot/monthly/klines/{base}USDT/1h/{base}USDT-1h-{m}.zip", timeout=60)
            if r.status_code == 404:
                continue                                   # 상장 전 달
            r.raise_for_status()
            raw.parent.mkdir(parents=True, exist_ok=True)
            raw.write_bytes(r.content)
        d = _read_zip(raw)
        frames.append(pd.DataFrame({"open": d[1].to_numpy(float), "close": d[4].to_numpy(float)}, index=_ms(d[0])))
    df = pd.concat(frames).sort_index()
    return df[~df.index.duplicated(keep="last")]


def parse_upbit(rows: list, to: pd.Timestamp) -> list:
    """업비트 응답 → (UTC 시각, 시가). 요청한 to 보다 앞선 봉만 받는다(교훈81)."""
    out = []
    for x in rows:
        ts = pd.Timestamp(x["candle_date_time_utc"], tz="UTC")
        if ts < to:
            out.append((ts, float(x["opening_price"])))
    return out


def _upbit() -> tuple[pd.DataFrame, dict]:
    import requests
    out, diag, to = [], {"calls": 0, "rejected": 0}, cp.END
    while to > cp.START:
        for k in range(6):
            r = requests.get("https://api.upbit.com/v1/candles/minutes/60",
                             params={"market": "KRW-BTC", "to": to.strftime("%Y-%m-%dT%H:%M:%SZ"), "count": 200}, timeout=60)
            if r.status_code == 200:
                break
            time.sleep(2 ** k)
        r.raise_for_status()
        diag["calls"] += 1
        rows = r.json()
        got = parse_upbit(rows, to)
        diag["rejected"] += len(rows) - len(got)
        if not got:
            break
        out += got
        to = min(t for t, _ in got)
        time.sleep(0.12)
    df = pd.DataFrame(out, columns=["time", "open"]).set_index("time").sort_index()
    df = df[~df.index.duplicated(keep="last")]
    df = df[df.index >= cp.START]
    diag.update(rows=len(df), first=str(df.index[0]))
    return df, diag


def collect():
    ALTS.mkdir(parents=True, exist_ok=True)
    diag = {}

    def one(item):
        coin, (cbb, bnb) = item
        cb, d = cp._cb(f"{cbb}-USD")
        bn = _bn_spot(bnb)
        cb.to_parquet(ALTS / f"{coin}_cb.parquet")
        bn.to_parquet(ALTS / f"{coin}_bn.parquet")
        d.update(bn_rows=len(bn), bn_first=str(bn.index[0]) if len(bn) else None)
        return coin, d

    with ThreadPoolExecutor(4) as ex:
        for coin, d in ex.map(one, COINS.items()):
            diag[coin] = d
            print(coin, d.get("rows"), d.get("first"), d.get("bn_first"), flush=True)
    up, diag["upbit_KRW-BTC"] = _upbit()
    up.to_parquet(ALTS / "upbit_btc.parquet")
    (ALTS / "_diagnostics.json").write_text(json.dumps(diag, ensure_ascii=False, indent=1), encoding="utf-8")
    bad = [c for c in COINS if not diag[c].get("rows") or not diag[c].get("bn_rows")]
    print(json.dumps({"bad": bad, "upbit": diag["upbit_KRW-BTC"]}, ensure_ascii=False))
    if bad:
        sys.exit(1)


# ---------- 계산 ----------
def _read(path: Path) -> pd.DataFrame:
    d = pd.read_parquet(path)
    d.index = pd.to_datetime(d.index, utc=True)
    return d


def fwd_ret(open_: pd.Series, grid: pd.DatetimeIndex, h: int = HOLD) -> pd.Series:
    o = open_.reindex(grid).to_numpy()
    return (open_.reindex(grid + h * H).to_numpy() / o - 1) * 1e4


def month(idx: pd.DatetimeIndex) -> pd.PeriodIndex:
    return idx.tz_convert(None).to_period("M")   # UTC 월


def month_boot(values: pd.Series, rng, n: int = N_BOOT) -> list:
    """월 단위 블록 부트스트랩 평균의 95% 구간."""
    blocks = [g.to_numpy() for _, g in values.groupby(month(values.index))]
    means = []
    for _ in range(n):
        pick = rng.integers(0, len(blocks), len(blocks))
        means.append(np.concatenate([blocks[i] for i in pick]).mean())
    return [round(float(np.percentile(means, q)), 1) for q in (2.5, 97.5)]


def k1_random_entry(e: pd.Series, z: pd.Series, ret: pd.Series, rng, n: int = N_BOOT) -> dict:
    d = np.sign(z.reindex(e.index).to_numpy())
    pool = ret.index[ret.notna() & z.notna() & (ret.index >= OOS_FROM)]
    r = ret.reindex(pool).to_numpy()
    null = []
    for _ in range(n):
        idx = rng.choice(len(pool), len(e), replace=False)
        null.append((rng.permutation(d) * r[idx]).mean())
    p95 = float(np.percentile(null, 95))
    return {"actual_bp": round(float(e.mean()), 1), "null_p95_bp": round(p95, 1), "null_mean_bp": round(float(np.mean(null)), 1),
            "p_value": round(float((np.array(null) >= e.mean()).mean()), 4), "pass": bool(e.mean() > p95), "n": int(len(e))}


def daily(series: list[pd.Series]) -> pd.Series:
    s = pd.concat(series)
    return s.groupby(s.index.floor("D")).mean().sort_index()


def r1_summary(dly: pd.Series, rng) -> dict:
    lo, hi = month_boot(dly, rng)
    late = dly[dly.index >= pd.Timestamp("2024-01-01", tz="UTC")]
    rep = bool(dly.mean() > 0 and lo > 0 and dly.mean() - COST > 0 and late.mean() > 0)
    return {"verdict": "REPLICATED" if rep else "NOT REPLICATED", "days": int(len(dly)),
            "gross_bp": round(float(dly.mean()), 1), "t_daily": round(tstat(dly.to_numpy()), 2), "month_block_ci95": [lo, hi],
            "net10_bp": round(float(dly.mean() - COST), 1), "gross_2024on_bp": round(float(late.mean()), 1),
            "periods_bp": {g: {"days": int(len(x)), "bp": round(float(x.mean()), 1), "t": round(tstat(x.to_numpy()), 2)}
                           for g, x in dly.groupby(dly.index.map(cp.period))},
            "yearly_bp": {int(y): round(float(x.mean()), 1) for y, x in dly.groupby(dly.index.year)}}


def main():
    rng = np.random.default_rng(SEED)
    cb, bn, us = (_read(cp.DATA / f"{n}.parquet") for n in ("cb_btc", "bn_btc", "cb_usdt"))
    z = cp.zscore(cp.premium(cb, bn))
    e = cp.events(z, bn["open"], HOLD)
    oos = e[e.index >= OOS_FROM]
    ret = pd.Series(fwd_ret(bn["open"], z.index), index=z.index)
    out = {"A": {}, "B": {}}
    out["A"]["K1"] = k1_random_entry(oos, z, ret, rng)
    lo, hi = month_boot(oos, rng)
    out["A"]["K2"] = {"month_block_ci95": [lo, hi], "months": int(month(oos.index).nunique()), "pass": bool(lo > 0)}
    msum = oos.groupby(month(oos.index)).sum()
    top = msum.nlargest(2).index
    rest = oos[~month(oos.index).isin(top)]
    out["A"]["K3"] = {"dropped": [str(m) for m in top], "net10_bp": round(float(rest.mean() - COST), 1), "n": int(len(rest)),
                      "pass": bool(rest.mean() - COST > 0)}
    up = _read(ALTS / "upbit_btc.parquet")["open"]
    longs = oos.index[(np.sign(z.reindex(oos.index)) > 0).to_numpy()]
    ur = pd.Series(fwd_ret(up, longs), index=longs).dropna()
    bnr = pd.Series(fwd_ret(bn["open"], longs), index=longs).dropna()
    out["A"]["K4"] = {"n": int(len(ur)), "missing": int(len(longs) - len(ur)), "upbit_gross_bp": round(float(ur.mean()), 1),
                      "upbit_net10_bp": round(float(ur.mean() - COST), 1), "t_net": round(tstat(ur.to_numpy() - COST), 2),
                      "binance_same_events_gross_bp": round(float(bnr.mean()), 1), "pass": bool(ur.mean() - COST > 0)}
    out["A"]["all_pass"] = all(out["A"][k]["pass"] for k in ("K1", "K2", "K3", "K4"))
    # B — 알트 재현
    per, per_adj, per4 = [], [], []
    coin_tab = {}
    for coin in COINS:
        c, b = _read(ALTS / f"{coin}_cb.parquet"), _read(ALTS / f"{coin}_bn.parquet")
        zc = cp.zscore(cp.premium(c, b))
        ec = cp.events(zc, b["open"], HOLD)
        per.append(ec)
        per4.append(cp.events(zc, b["open"], 4))
        za = cp.zscore(cp.premium(c, b, us))
        ea = cp.events(za, b["open"], HOLD)
        per_adj.append(ea[ea.index >= ADJ_FROM])
        coin_tab[coin] = {"n": int(len(ec)), "bp": round(float(ec.mean()), 1) if len(ec) else None,
                          "t": round(tstat(ec.to_numpy()), 2), "first": str(ec.index.min())[:10] if len(ec) else None}
    out["B"]["R1"] = r1_summary(daily(per), rng)
    out["B"]["record"] = {"coins": coin_tab, "usdt_adjusted_daily": r1_summary(daily(per_adj), rng),
                          "hold4h_daily": {"gross_bp": round(float(daily(per4).mean()), 1), "t": round(tstat(daily(per4).to_numpy()), 2)},
                          "events_total": int(sum(len(x) for x in per))}
    out["recommend_paper_sleeve"] = bool(out["A"]["all_pass"] and out["B"]["R1"]["verdict"] == "REPLICATED")
    (HERE / "coinbase-premium-robustness.json").write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
    print(json.dumps(out, ensure_ascii=False, indent=1))


def selftest():
    rng = np.random.default_rng(1)
    grid = pd.date_range("2023-01-01", periods=24 * 400, freq="h", tz="UTC")
    z = pd.Series(rng.normal(0, 1, len(grid)), index=grid)
    ret = pd.Series(rng.normal(0, 100, len(grid)), index=grid)
    # 방향 정보가 있으면 K1 통과: 사건 시각의 수익을 z 방향으로 +40bp 심는다
    ev = z[z.abs() >= 2].index[::5]
    ret_good = ret.copy()
    ret_good[ev] = np.sign(z[ev]) * 40 + rng.normal(0, 100, len(ev))
    good = pd.Series(np.sign(z[ev]) * ret_good[ev], index=ev)
    assert k1_random_entry(good, z, ret_good, np.random.default_rng(2), 400)["pass"]
    # 월 블록 부트스트랩: 평균이 양으로 크면 하한 > 0
    s = pd.Series(rng.normal(50, 100, 600), index=pd.date_range("2023-01-01", periods=600, freq="D", tz="UTC"))
    assert month_boot(s, np.random.default_rng(4), 400)[0] > 0
    # 일별 묶음: 같은 날 여러 코인 사건 → 한 관측
    a = pd.Series([10.0, 30.0], index=pd.to_datetime(["2024-01-01 01:00", "2024-01-02 05:00"], utc=True))
    b = pd.Series([50.0], index=pd.to_datetime(["2024-01-01 07:00"], utc=True))
    d = daily([a, b])
    assert len(d) == 2 and d.iloc[0] == 30.0
    # 업비트 응답: to 이후 봉은 버린다
    to = pd.Timestamp("2024-01-01 10:00", tz="UTC")
    rows = [{"candle_date_time_utc": "2024-01-01T09:00:00", "opening_price": 1}, {"candle_date_time_utc": "2024-01-01T10:00:00", "opening_price": 2}]
    assert parse_upbit(rows, to) == [(pd.Timestamp("2024-01-01 09:00", tz="UTC"), 1.0)]
    # fwd_ret 는 T 시가 → T+24h 시가
    o = pd.Series(np.arange(1, 101, dtype=float), index=pd.date_range("2024-01-01", periods=100, freq="h", tz="UTC"))
    assert np.isclose(fwd_ret(o, o.index[:1])[0], (25 / 1 - 1) * 1e4)
    print("selftest 5/5 OK")


if __name__ == "__main__":
    if "--selftest" in sys.argv:
        selftest()
    elif "--collect" in sys.argv:
        collect()
    else:
        main()
