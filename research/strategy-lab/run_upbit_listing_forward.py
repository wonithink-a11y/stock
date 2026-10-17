#!/usr/bin/env python3
"""업비트 원화 신규 상장 뒤 7일 숏 — forward 기록(사전등록 findings/upbit-krw-listing-forward-preregistration-2026-10.md).

기록 전용 — 매매·점수 불사용. 공개 API 만(업비트·바이낸스 현물·USDⓈ-M, 키 없음).
    python research/strategy-lab/run_upbit_listing_forward.py            # 증분 기록, 건수만
    python research/strategy-lab/run_upbit_listing_forward.py --selftest # 네트워크 없음
    python research/strategy-lab/run_upbit_listing_forward.py --judge    # 사전등록 §4 시점 전엔 거부
"""
from __future__ import annotations

import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE / "futures"))
from upbit_krw_listing import event, ret  # noqa: E402  U1 정의 그대로
from short_horizon_study import tstat  # noqa: E402

REPORT = HERE / "reports" / "2026-10-upbit-listing-forward"
EV, BASE = REPORT / "events.jsonl", REPORT / "baseline_markets.json"
FIRST_D0 = pd.Timestamp("2026-10-19")
BAR, COST, STRESS, SEED = 2.0, 10.0, 20.0, 20261018
MIN_F1, MIN_F2 = 30, 20
GATES = {1: (60, pd.Timestamp("2027-10-19")), 2: (120, pd.Timestamp("2028-10-19"))}
UP, BN, FA = "https://api.upbit.com/v1", "https://api.binance.com/api/v3", "https://fapi.binance.com/fapi/v1"
DAY = pd.Timedelta(days=1)
KST = timezone(timedelta(hours=9))


# ---------- 계산(순수) ----------

def measure(d0, up, upbtc, cs, bs, perp=None, fund=None, onboard=None) -> dict:
    """한 사건 기록. up·upbtc 업비트 원화 종가, cs·bs 바이낸스 현물 코인·BTC 종가, perp 무기한 종가,
    fund = [(시각, 비율)], onboard = 무기한 onboardDate(Timestamp). 전부 UTC·날짜 인덱스."""
    r = {"d0": d0.date().isoformat()}
    if d0 < FIRST_D0:
        return {**r, "status": "before_freeze"}
    if cs is None or not len(cs):
        return {**r, "status": "no_spot"}
    e = event(d0, cs, bs, up, upbtc)
    if isinstance(e, str):
        return {**r, "status": e}
    if e["U1"] is None:
        return {**r, "status": "missing_price"}
    r.update(status="used", U1_raw=round(e["U1"][0], 1), U1_ex=round(e["U1"][1], 1),
             pump_d0=e["pump_d0"] and round(e["pump_d0"], 1), pre_7_1=e["pre_7_1"] and round(e["pre_7_1"], 1),
             perp_onboard=onboard.isoformat() if onboard is not None else None,
             perp_at_d0=bool(onboard is not None and onboard < d0 + DAY))
    if r["perp_at_d0"] and perp is not None:
        c, b = ret(perp, d0, d0 + 7 * DAY), ret(bs, d0, d0 + 7 * DAY)
        lo, hi = d0 + DAY + pd.Timedelta(minutes=1), d0 + 8 * DAY + pd.Timedelta(minutes=1)
        f = [x for t, x in (fund or []) if lo <= t < hi]
        if np.isfinite(c) and np.isfinite(b):
            r.update(perp_raw=round(-c * 1e4, 1), perp_ex=round(-(c - b) * 1e4, 1),
                     funding_bp=round(sum(f) * 1e4, 1), funding_n=len(f))
    return r


def day_obs(rows: list[dict], cell: str) -> pd.DataFrame:
    """셀 관측: 같은 D0 평균(ex·raw), 인덱스 = D0."""
    d = pd.DataFrame([x for x in rows if x.get("status") == "used"])
    if d.empty:
        return pd.DataFrame(columns=["ex", "raw"])
    if cell == "F1":
        d = d.assign(ex=d["U1_ex"], raw=d["U1_raw"])
    else:
        if "perp_ex" not in d:
            return pd.DataFrame(columns=["ex", "raw"])
        d = d[d["perp_at_d0"].fillna(False).astype(bool) & d["perp_ex"].notna()]
        d = d.assign(ex=d["perp_ex"] + d["funding_bp"], raw=d["perp_raw"] + d["funding_bp"])
    d["d0"] = pd.to_datetime(d["d0"])
    return d.groupby("d0")[["ex", "raw"]].mean()


def verdict(day: pd.DataFrame, min_n: int) -> dict:
    n = len(day)
    if n < min_n:
        return {"verdict": "판정불가", "n_days": n}
    wk = day.groupby(day.index.to_period("W-SUN")).mean()
    ex, raw = wk["ex"].to_numpy(), wk["raw"].to_numpy()
    t = tstat(ex)
    net = lambda c: (float(raw.mean() - c), float(ex.mean() - c))
    info = ex.mean() > 0 and t >= BAR
    eco = info and min(net(COST)) > 0 and min(net(STRESS)) > 0
    rob = eco and tstat(ex - COST) >= BAR
    v = "REJECT" if ex.mean() <= 0 else "ROBUST" if rob else "ECONOMIC" if eco else "INFORMATION" if info else "INCONCLUSIVE"
    rng = np.random.default_rng(SEED)
    ci = [round(float(np.percentile([rng.choice(ex, len(ex)).mean() for _ in range(2000)], q)), 1) for q in (2.5, 97.5)]
    return {"verdict": v, "n_days": n, "n_weeks": len(wk), "t_week": round(t, 2), "ex_bp": round(float(ex.mean()), 1),
            "raw_bp": round(float(raw.mean()), 1), "ex_ci95": ci, "net_raw_ex": [round(x, 1) for x in net(COST)],
            "net_raw_ex_stress": [round(x, 1) for x in net(STRESS)], "t_net_ex": round(tstat(ex - COST), 2),
            "breakeven_bp": round(float(min(raw.mean(), ex.mean())), 1),
            "yearly_ex": {int(y): round(float(x), 1) for y, x in day["ex"].groupby(day.index.year).mean().items()}}


def gate_open(stage: int, n_days: int, today: pd.Timestamp) -> bool:
    n, when = GATES[stage]
    return n_days >= n or (today >= when and n_days >= MIN_F1)


# ---------- 수집 ----------

def series(rows, tcol, vcol, unit=None) -> pd.Series:
    d = pd.DataFrame(rows)
    idx = (pd.to_datetime(d[tcol], unit=unit) if unit else pd.to_datetime(d[tcol])).dt.normalize()
    return pd.Series(d[vcol].astype(float).to_numpy(), index=idx).sort_index()


def klines(base: str, sym: str, start: pd.Timestamp) -> pd.Series | None:
    from collect_upbit_listings import get
    js = get(f"{base}/klines", {"symbol": sym, "interval": "1d", "startTime": int(start.timestamp() * 1000), "limit": 20})
    return series([{"t": k[0], "c": k[4]} for k in js], "t", "c", unit="ms") if js else None


def fetch(market: str, perps: dict) -> dict:
    from collect_upbit_listings import get
    js = get(f"{UP}/candles/days", {"market": market, "count": 200})
    if len(js) >= 200:
        return {"d0": None, "status": "before_freeze"}       # 200일 넘게 거래 중 = 동결 전 시장
    up = series(js, "candle_date_time_utc", "trade_price")
    d0 = up.index.min()
    if d0 >= FIRST_D0 and datetime.now(timezone.utc).date() < (d0 + 8 * DAY).date():
        return {"d0": d0.date().isoformat(), "status": "pending"}
    to = (d0 + 10 * DAY).strftime("%Y-%m-%dT00:00:00Z")
    upbtc = series(get(f"{UP}/candles/days", {"market": "KRW-BTC", "to": to, "count": 20}), "candle_date_time_utc", "trade_price")
    coin, start = market.split("-", 1)[1], d0 - 10 * DAY
    cs, bs = klines(f"{BN}", f"{coin}USDT", start), klines(f"{BN}", "BTCUSDT", start)
    psym = next((s for s in (f"{coin}USDT", f"1000{coin}USDT", f"1000000{coin}USDT") if s in perps), None)
    perp = fund = onboard = None
    if psym:
        onboard = perps[psym]
        perp = klines(FA, psym, start)
        fr = get(f"{FA}/fundingRate", {"symbol": psym, "startTime": int((d0 + DAY).timestamp() * 1000),
                                       "endTime": int((d0 + 9 * DAY).timestamp() * 1000), "limit": 1000}) or []
        fund = [(pd.to_datetime(x["fundingTime"], unit="ms"), float(x["fundingRate"])) for x in fr]
    return {**measure(d0, up, upbtc, cs, bs, perp, fund, onboard), "perp_symbol": psym}


def read_jsonl(p: Path) -> list[dict]:
    return [json.loads(x) for x in p.read_text(encoding="utf-8").splitlines() if x.strip()] if p.exists() else []


def cmd_update():
    from collect_upbit_listings import get
    REPORT.mkdir(parents=True, exist_ok=True)
    krw = sorted(m["market"] for m in get(f"{UP}/market/all", {}) if m["market"].startswith("KRW-"))
    if not BASE.exists():
        BASE.write_text(json.dumps({"frozen": "2026-10-18", "markets": krw}, ensure_ascii=False, indent=1), encoding="utf-8")
        print(f"동결 목록 저장 {len(krw)}개")
    base = set(json.loads(BASE.read_text(encoding="utf-8"))["markets"])
    done = {x["market"] for x in read_jsonl(EV)}
    new = [m for m in krw if m not in base and m not in done]
    perps = {}
    if new:
        info = get(f"{FA}/exchangeInfo", {})
        perps = {s["symbol"]: pd.to_datetime(s["onboardDate"], unit="ms") for s in info["symbols"]
                 if s.get("contractType") == "PERPETUAL" and s.get("quoteAsset") == "USDT"}
    add, pending = [], 0
    for m in new:
        r = fetch(m, perps)
        if r["status"] == "pending":
            pending += 1
            continue
        add.append({"market": m, **r, "recorded_at": datetime.now(KST).isoformat(timespec="seconds")})
    if add:
        with EV.open("a", encoding="utf-8") as f:
            f.writelines(json.dumps(x, ensure_ascii=False) + "\n" for x in add)
    rows = read_jsonl(EV)
    used = [x for x in rows if x["status"] == "used"]
    print(json.dumps({"원화 시장": len(krw), "동결 목록": len(base), "새 시장": len(new), "이번 기록": len(add), "대기(D0+8 전)": pending,
                      "누적 기록": len(rows), "used": len(used), "상장일(F1)": len({x["d0"] for x in used}),
                      "무기한 있음(F2)": sum(bool(x.get("perp_at_d0")) for x in used)}, ensure_ascii=False))


def cmd_judge():
    rows = read_jsonl(EV)
    today = pd.Timestamp(datetime.now(timezone.utc).date())
    j1, j2 = REPORT / "judge-1.json", REPORT / "judge-2.json"
    if j2.exists():
        raise SystemExit("최종 판정이 이미 있다 - 거부")
    if j1.exists():
        prev = json.loads(j1.read_text(encoding="utf-8"))["cells"]
        if not any(c["verdict"] in ("INCONCLUSIVE", "판정불가") for c in prev.values()):
            raise SystemExit("1차 판정이 결론을 냈다 - 최종 없음, 거부")
        stage = 2
    else:
        stage = 1
    obs = {c: day_obs(rows, c) for c in ("F1", "F2")}
    n = len(obs["F1"])
    if not gate_open(stage, n, today):
        k, when = GATES[stage]
        raise SystemExit(f"{stage}차 판정 시점 전 - 거부 (F1 상장일 {n} < {k}, 또는 {when.date()} 이후 {MIN_F1}개)")
    used = [x for x in rows if x["status"] == "used"]
    out = {"stage": stage, "date": today.date().isoformat(),
           "cells": {"F1": verdict(obs["F1"], MIN_F1), "F2": verdict(obs["F2"], MIN_F2)},
           "record": {"status": pd.Series([x["status"] for x in rows]).value_counts().to_dict(),
                      "perp_coverage": round(sum(bool(x.get("perp_at_d0")) for x in used) / max(len(used), 1), 3),
                      "funding_bp_mean": round(float(np.nanmean([x.get("funding_bp", np.nan) for x in used] or [np.nan])), 1),
                      "pump_d0_mean": round(float(np.nanmean([x.get("pump_d0") or np.nan for x in used] or [np.nan])), 1)}}
    (j1 if stage == 1 else j2).write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
    print(json.dumps(out, ensure_ascii=False, indent=1))


def selftest():
    idx = pd.date_range("2026-09-01", periods=80)
    bs = pd.Series(np.linspace(100, 110, 80), index=idx)
    cs = pd.Series(10.0, index=idx)
    d0 = pd.Timestamp("2026-10-20")
    cs.loc[d0 + DAY:] = 9.0                                    # 상장 다음 날 10% 하락
    upbtc, up = bs * 1300, cs * 1300
    fund = [(d0 + DAY + pd.Timedelta(milliseconds=1), 0.5), (d0 + 2 * DAY, 0.001), (d0 + 8 * DAY + pd.Timedelta(milliseconds=1), -0.002),
            (d0 + 9 * DAY, 0.7)]                               # 첫 것(진입 순간)·마지막(창 밖)은 빠진다
    r = measure(d0, up, upbtc, cs, bs, cs * 1000, fund, d0 - 30 * DAY)
    assert r["status"] == "used" and r["U1_raw"] == 1000.0 and r["U1_ex"] > 1000 and r["perp_at_d0"]
    assert r["perp_raw"] == r["U1_raw"] and r["funding_n"] == 2 and r["funding_bp"] == -10.0, r
    assert not measure(d0, up, upbtc, cs, bs, cs, fund, d0 + DAY)["perp_at_d0"]           # D0 종가 뒤 상장 무기한
    assert measure(pd.Timestamp("2026-10-18"), up, upbtc, cs, bs)["status"] == "before_freeze"
    assert measure(d0, up, upbtc, None, bs)["status"] == "no_spot"
    assert measure(d0, up * 3, upbtc, cs, bs)["status"] == "price_mismatch"
    # 판정: 상장일 30개 미만 판정불가, 게이트, 셀 관측
    rows = [{"d0": (d0 + 3 * i * DAY).date().isoformat(), "status": "used", "U1_raw": 1500.0 + 50 * (i % 3), "U1_ex": 1400.0 + 100 * (i % 4),
             "perp_at_d0": i % 2 == 0, "perp_raw": 1200.0, "perp_ex": 1100.0 + 10 * i, "funding_bp": -50.0} for i in range(40)]
    assert verdict(day_obs(rows[:29], "F1"), MIN_F1)["verdict"] == "판정불가"
    v1 = verdict(day_obs(rows, "F1"), MIN_F1)
    assert v1["verdict"] == "ROBUST" and v1["n_days"] == 40, v1
    f2 = day_obs(rows, "F2")
    assert len(f2) == 20 and abs(f2["ex"].iloc[0] - 1050.0) < 1e-9
    neg = [{**x, "U1_ex": -x["U1_ex"]} for x in rows]
    assert verdict(day_obs(neg, "F1"), MIN_F1)["verdict"] == "REJECT"
    assert not gate_open(1, 59, pd.Timestamp("2027-10-18")) and gate_open(1, 60, pd.Timestamp("2027-01-01"))
    assert gate_open(1, 30, pd.Timestamp("2027-10-19")) and not gate_open(1, 29, pd.Timestamp("2028-01-01"))
    assert not gate_open(2, 119, pd.Timestamp("2028-10-18")) and gate_open(2, 30, pd.Timestamp("2028-10-19"))
    print("selftest OK")


if __name__ == "__main__":
    selftest() if "--selftest" in sys.argv else cmd_judge() if "--judge" in sys.argv else cmd_update()
