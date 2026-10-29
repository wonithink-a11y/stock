#!/usr/bin/env python3
"""바이낸스 신규 상장 7일 숏 — 무기한 실행 가능성. 사전등록 findings/binance-listing-perp-preregistration-2026-10.md.

    python research/strategy-lab/futures/binance_listing_perp.py --collect   # 무기한 목록·일봉·펀딩 → data/crypto/listing_perp/
    python research/strategy-lab/futures/binance_listing_perp.py             # 판정
    python research/strategy-lab/futures/binance_listing_perp.py --selftest
"""
from __future__ import annotations

import io
import json
import sys
import zipfile
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import binance_listing as bl  # noqa: E402  사건 정의(7bba3b1 동결본)
import coinbase_premium as cp  # noqa: E402
import coinbase_premium_robustness as rb  # noqa: E402
from short_horizon_study import tstat  # noqa: E402

DATA = HERE.parent / "data" / "crypto" / "listing_perp"
UM = "https://data.binance.vision/data/futures/um/monthly"
D = pd.Timedelta(days=1)
H, COST, STRESS = 7, 10.0, 30.0
END = pd.Timestamp("2026-10-01", tz="UTC")


def _csv(url: str) -> pd.DataFrame:
    r = bl._get(url)
    if r.status_code == 404:
        return pd.DataFrame()
    with zipfile.ZipFile(io.BytesIO(r.content)) as z:
        raw = pd.read_csv(z.open(z.namelist()[0]), header=None)
    return raw[pd.to_numeric(raw[0], errors="coerce").notna()].reset_index(drop=True)


def _ms(x) -> pd.DatetimeIndex:
    t = x.astype("int64").to_numpy()
    t = np.where(t > 10 ** 14, t // 1000, t)
    return pd.to_datetime(t, unit="ms", utc=True)


def perp_daily(sym: str, months: list[str]) -> pd.Series:
    fr = []
    for m in months:
        d = _csv(f"{UM}/klines/{sym}/1d/{sym}-1d-{m}.zip")
        if len(d):
            s = pd.Series(d[1].astype(float).to_numpy(), index=_ms(d[0]))
            fr.append(s[s.index.tz_convert(None).to_period("M") == pd.Period(m, "M")])
    return pd.concat(fr).sort_index() if fr else pd.Series(dtype=float)


def funding(sym: str, months: list[str]) -> pd.Series:
    fr = []
    for m in months:
        d = _csv(f"{UM}/fundingRate/{sym}/{sym}-fundingRate-{m}.zip")
        if len(d):
            fr.append(pd.DataFrame({"rate": d[2].astype(float).to_numpy(), "ivl": d[1].astype(float).to_numpy()}, index=_ms(d[0])))
    return pd.concat(fr).sort_index() if fr else pd.DataFrame(columns=["rate", "ivl"])


def collect():
    DATA.mkdir(parents=True, exist_ok=True)
    dirs, _ = bl._list("data/futures/um/monthly/klines/")
    perps = sorted(d.rstrip("/").split("/")[-1] for d in dirs)
    (DATA / "perps.json").write_text(json.dumps(perps), encoding="utf-8")
    ev = bl.events_table(json.loads((bl.DATA / "months.json").read_text(encoding="utf-8")))
    ps = set(perps)

    def one(e):
        sym = next((s for s in (f"{e['base']}USDT", f"1000{e['base']}USDT") if s in ps), None)
        if sym is None:
            return e["sym"], None
        p = pd.Period(e["first"], "M")
        months = [str(p + k) for k in range(3)]
        px, fu = perp_daily(sym, months), funding(sym, months)
        px.rename("open").to_frame().to_parquet(DATA / f"{e['sym']}_perp.parquet")
        fu.to_parquet(DATA / f"{e['sym']}_funding.parquet")
        return e["sym"], sym
    with ThreadPoolExecutor(8) as ex:
        m = dict(ex.map(one, ev))
    btc_months = [str(p) for p in pd.period_range("2019-09", "2026-09", freq="M")]
    perp_daily("BTCUSDT", btc_months).rename("open").to_frame().to_parquet(DATA / "BTCUSDT_perp.parquet")
    (DATA / "match.json").write_text(json.dumps(m, ensure_ascii=False), encoding="utf-8")
    print(len(perps), sum(v is not None for v in m.values()), len(m))


def observe(L: pd.Timestamp, px: pd.Series, fu: pd.DataFrame, btc: pd.Series, spot_t0: float) -> dict:
    t0, t1 = L + D, L + D + H * D
    p0, p1, b0, b1 = px.get(t0, np.nan), px.get(t1, np.nan), btc.get(t0, np.nan), btc.get(t1, np.nan)
    if not all(np.isfinite([p0, p1, b0, b1])) or t1 > END:
        return {"ok": False}
    f = fu[(fu.index > t0) & (fu.index <= t1)] if len(fu) else fu
    F = float(f["rate"].sum()) if len(f) else 0.0
    r, b = p1 / p0 - 1, b1 / b0 - 1
    return {"ok": True, "price_only": -(r - b) * 1e4, "funding": F * 1e4, "obs": (-(r - b) + F) * 1e4,
            "fund_against": bool(F < 0), "pre_spot": bool(px.index[0] < L), "basis": (p0 / spot_t0 - 1) * 1e4 if np.isfinite(spot_t0) else np.nan,
            "ivl": float(f["ivl"].median()) if len(f) else np.nan}


def main():
    m = json.loads((DATA / "match.json").read_text(encoding="utf-8"))
    btc = rb._read(DATA / "BTCUSDT_perp.parquet")["open"]
    ev = bl.events_table(json.loads((bl.DATA / "months.json").read_text(encoding="utf-8")))
    rows = []
    for e in ev:
        spot = rb._read(bl.DATA / f"{e['sym']}.parquet")["open"]
        if not len(spot):
            continue
        L = spot.index[0]
        row = {"sym": e["sym"], "L": L, "has_perp": m.get(e["sym"]) is not None}
        if row["has_perp"] and (DATA / f"{e['sym']}_perp.parquet").exists():
            px = rb._read(DATA / f"{e['sym']}_perp.parquet")["open"]
            fu = rb._read(DATA / f"{e['sym']}_funding.parquet") if (DATA / f"{e['sym']}_funding.parquet").exists() else pd.DataFrame(columns=["rate", "ivl"])
            row.update(observe(L, px, fu, btc, spot.get(L + D, np.nan)) if len(px) else {"ok": False})
        else:
            row["ok"] = False
        rows.append(row)
    df = pd.DataFrame(rows)
    df = df[df["L"] + D + H * D <= END]
    df["split"] = df["L"].map(cp.split)
    ok = df[df["ok"] == True].copy()  # noqa: E712
    day = ok.groupby("L")[["obs", "price_only", "funding"]].mean()
    day["split"] = day.index.map(cp.split)
    oos = day[day["split"] != "TRAIN"]
    te = day[day["split"] == "TEST"]
    x = oos["obs"].to_numpy()
    n1, n3 = x - COST, x - STRESS
    if len(oos) < 30 or n1.mean() <= 0:
        v = "NOT EXECUTABLE"
    elif tstat(n1) >= 2 and n3.mean() > 0 and te["obs"].mean() - COST > 0:
        v = "EXECUTABLE"
    else:
        v = "PARTIAL"
    out = {"verdict": v,
           "coverage": {k: {"events": int(len(x_)), "with_perp_obs": int((x_["ok"] == True).sum())} for k, x_ in df.groupby("split")},  # noqa: E712
           "by_split_day_mean_bp": {k: {"days": int(len(x_)), "obs": round(float(x_["obs"].mean()), 1), "t": round(tstat(x_["obs"].to_numpy()), 2),
                                        "price_only": round(float(x_["price_only"].mean()), 1), "funding_7d": round(float(x_["funding"].mean()), 1)}
                                    for k, x_ in day.groupby("split")},
           "oos": {"days": int(len(oos)), "net10": round(float(n1.mean()), 1), "t_net10": round(tstat(n1), 2), "net30": round(float(n3.mean()), 1),
                   "test_net10": round(float(te["obs"].mean() - COST), 1) if len(te) else None},
           "periods": {g: {"days": int(len(x_)), "obs": round(float(x_["obs"].mean()), 1), "t": round(tstat(x_["obs"].to_numpy()), 2)} for g, x_ in day.groupby(day.index.map(cp.period))},
           "record": {"funding_against_short%": {k: round(float(x_["fund_against"].mean() * 100), 1) for k, x_ in ok.groupby("split")},
                      "perp_before_spot%": {k: round(float(x_["pre_spot"].mean() * 100), 1) for k, x_ in ok.groupby("split")},
                      "basis_entry_bp_median": {k: round(float(x_["basis"].median()), 1) for k, x_ in ok.groupby("split")},
                      "funding_interval_h": {str(k): int(v_) for k, v_ in ok["ivl"].value_counts().items()}}}
    (HERE / "binance-listing-perp.json").write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
    print(json.dumps(out, ensure_ascii=False, indent=1))


def selftest():
    L = pd.Timestamp("2024-03-01", tz="UTC")
    idx = pd.date_range(L - 2 * D, periods=20, freq="D")
    px = pd.Series(100.0, index=idx); px[L + 8 * D] = 90.0              # 7일 −10%
    btc = pd.Series(50.0, index=idx); btc[L + 8 * D] = 55.0             # BTC +10%
    fu = pd.DataFrame({"rate": [-0.001] * 3, "ivl": [8.0] * 3}, index=[L + D, L + 2 * D, L + 9 * D])   # 창 안 1건(t0 정산은 제외), 밖 1건
    o = observe(L, px, fu, btc, 100.0)
    assert o["ok"] and abs(o["price_only"] - 2000.0) < 1e-6 and abs(o["funding"] + 10.0) < 1e-9 and abs(o["obs"] - 1990.0) < 1e-6
    assert o["fund_against"] and o["pre_spot"] and abs(o["basis"]) < 1e-9
    print("selftest 2/2 OK")


if __name__ == "__main__":
    if "--selftest" in sys.argv:
        selftest()
    elif "--collect" in sys.argv:
        collect()
    else:
        main()
