#!/usr/bin/env python3
"""업비트 원화 상장 7일 숏 — 실행 가능성 점검(기록 전용, 판정 없음).

과거 연구(upbit-krw-listing, d08bf6df)의 사용 사건 121개에 대해, 결과 계산 전에 아래 정의를 고정한다.
  - 무기한 존재: 바이낸스 USDⓈ-M `<코인>USDT`(없으면 `1000<코인>USDT`) 일봉 첫 봉 ≤ D0 → D0 종가에 숏 가능으로 본다.
    (첫 봉 = D0 은 그날 중 상장 — 기록에 따로 센다.)
  - 무기한 7일 숏 원수익 = −(무기한 종가 D0+7 ÷ D0 − 1). 펀딩 = fundingTime ∈ (D0+1 00:00, D0+8 00:00] UTC 의 합(숏은 양이면 받는다).
  - 순 = 원수익 + 펀딩 − 10bp. 초과 = 코인 숏 + BTC 무기한 롱(= −(코인 − BTC), 과거 U1 과 같은 부호) + 펀딩 − 10bp(BTC 다리 비용·펀딩 미반영).
  - 현물 증거금 대출 가능 여부는 공개 이력이 없어 재지 않는다.
판정은 forward(upbit-krw-listing-forward-preregistration-2026-10.md) 에서만 한다 — 이 표본은 이미 본 표본이다.
    python research/strategy-lab/futures/upbit_listing_executability.py
"""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd
import requests

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import upbit_krw_listing as u  # noqa: E402
from short_horizon_study import tstat  # noqa: E402

FAPI = "https://fapi.binance.com/fapi/v1"
CACHE = u.D / "perp"
DAY = pd.Timedelta(days=1)


def get(path, params):
    for k in range(5):
        r = requests.get(f"{FAPI}/{path}", params=params, timeout=20)
        if r.status_code == 429:
            time.sleep(2 + k)
            continue
        if r.status_code == 400:
            return None
        r.raise_for_status()
        time.sleep(0.15)
        return r.json()
    raise SystemExit(f"요청 실패 {path} {params}")


def perp(sym: str, d0: pd.Timestamp):
    """(심볼, 일봉 종가 Series, 펀딩 Series) — 캐시. 없으면 None."""
    f = CACHE / f"{sym}_{d0.date()}.json"
    if f.exists():
        js = json.loads(f.read_text())
    else:
        ms = lambda t: int(t.timestamp() * 1000)
        js = None
        for s in (sym, "1000" + sym):
            k = get("klines", {"symbol": s + "USDT", "interval": "1d", "startTime": ms(d0 - 60 * DAY), "limit": 80})
            if k:
                fr = get("fundingRate", {"symbol": s + "USDT", "startTime": ms(d0), "endTime": ms(d0 + 9 * DAY), "limit": 100}) or []
                js = {"symbol": s + "USDT", "k": [[x[0], x[4]] for x in k], "f": [[x["fundingTime"], x["fundingRate"]] for x in fr]}
                break
        CACHE.mkdir(parents=True, exist_ok=True)
        f.write_text(json.dumps(js))
    if not js:
        return None
    k = pd.Series([float(x[1]) for x in js["k"]], index=pd.to_datetime([x[0] for x in js["k"]], unit="ms"))
    fr = pd.Series([float(x[1]) for x in js["f"]], index=pd.to_datetime([x[0] for x in js["f"]], unit="ms"))
    return js["symbol"], k, fr


def period(y):
    return "~2023" if y <= 2023 else ("2024" if y == 2024 else "2025~")


def main():
    meta = json.loads((u.D / "listings.json").read_text(encoding="utf-8"))
    bb = u.load_close(u.D / "binance_daily" / "BTCUSDT.parquet", "close")
    upbtc = u.load_close(u.D / "upbit_krw_daily" / "KRW-BTC.parquet", "trade_price")
    rows = []
    for m, v in meta.items():
        d0 = pd.Timestamp(v["first"])
        if d0 < pd.Timestamp("2018-01-01") or not v["binance"]:
            continue
        e = u.event(d0, u.load_close(u.D / "binance_daily" / f"{v['binance']}.parquet", "close"), bb,
                    u.load_close(u.D / "upbit_krw_daily" / f"{m}.parquet", "trade_price"), upbtc)
        if isinstance(e, str) or not e["U1"]:
            continue
        row = {"d0": d0, "market": m, "spot_ex": e["U1"][1], "spot_raw": e["U1"][0], "perp": False}
        p = perp(m.split("-", 1)[1], d0)
        if p is not None:
            sym, k, fr = p
            first = k.index.min()
            row["perp_first"] = str(first.date())
            row["perp_same_day"] = bool(first == d0)
            if first <= d0 and d0 in k.index and d0 + 7 * DAY in k.index:
                b = perp("BTC", d0)
                bk = b[1] if b else None
                raw = -(k[d0 + 7 * DAY] / k[d0] - 1) * 1e4
                fund = fr[(fr.index > d0 + DAY) & (fr.index <= d0 + 8 * DAY)].sum() * 1e4
                btc = (bk[d0 + 7 * DAY] / bk[d0] - 1) * 1e4 if bk is not None and d0 in bk.index and d0 + 7 * DAY in bk.index else np.nan
                row.update(perp=True, perp_raw=raw, funding=fund, perp_net=raw + fund - 10, perp_ex_net=raw + btc + fund - 10 if np.isfinite(btc) else np.nan)
        rows.append(row)
    df = pd.DataFrame(rows)
    df["per"] = df["d0"].dt.year.map(period)
    out = {"events": len(df), "by_period": {}}
    for g, x in list(df.groupby("per")) + [("전체", df)]:
        p = x[x["perp"]]
        s = lambda c: {"mean": round(float(p[c].mean()), 1), "median": round(float(p[c].median()), 1), "t": round(tstat(p[c].dropna().to_numpy()), 2)} if len(p) else None
        out["by_period"][g] = {"n": int(len(x)), "perp_at_d0": int(len(p)), "perp_share": round(len(p) / len(x), 2),
                               "perp_same_day": int(x.get("perp_same_day", pd.Series(dtype=bool)).fillna(False).sum()),
                               "spot_ex_all": round(float(x["spot_ex"].mean()), 1), "spot_ex_perp_subset": round(float(p["spot_ex"].mean()), 1) if len(p) else None,
                               "spot_ex_no_perp": round(float(x.loc[~x["perp"], "spot_ex"].mean()), 1) if (~x["perp"]).any() else None,
                               "perp_raw": s("perp_raw"), "funding_7d": s("funding"), "perp_net": s("perp_net"), "perp_ex_net": s("perp_ex_net"),
                               "perp_net_pos_share": round(float((p["perp_net"] > 0).mean()), 2) if len(p) else None}
    df.assign(d0=df["d0"].dt.date.astype(str)).to_csv(HERE / "upbit-listing-executability.csv", index=False)
    (HERE / "upbit-listing-executability.json").write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
    print(json.dumps(out, ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main()
