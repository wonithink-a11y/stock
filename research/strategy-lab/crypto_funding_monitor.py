#!/usr/bin/env python3
"""BTC 펀딩 캐리 Stage 0 — 읽기 전용 모니터링 (공개 API, 키 없음, 주문 없음).

    python research/strategy-lab/crypto_funding_monitor.py            # 갱신 + 리포트 + 알림 판정
    python research/strategy-lab/crypto_funding_monitor.py --offline  # 캐시만
    python research/strategy-lab/crypto_funding_monitor.py --selftest

설계: docs/control/펀딩캐리-PortfolioMargin-설계-2026-09-19.md §8.
캐시 `.cache/funding_monitor/`(gitignore)를 로컬 펀딩 이력(`data/crypto/funding/BTCUSDT.parquet`)으로 시드하고,
그 이후분만 `GET /fapi/v1/fundingRate` 로 이어 받는다. 실시간 값은 `GET /fapi/v1/premiumIndex`.

★ 알림 임계값은 **제안 기본값**이다(사용자가 정하는 값 — 설계 문서 §8). 여기서 바꾸지 않고 CLI 로만 바꾼다.
★ 알림은 **판정만** 한다 — 어디로도 보내지 않는다(발송 배선은 별도 결정).
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
SEED = HERE / "data" / "crypto" / "funding" / "BTCUSDT.parquet"
CACHE_DIR = HERE / ".cache" / "funding_monitor"
CACHE = CACHE_DIR / "BTCUSDT_funding.parquet"
LATEST = CACHE_DIR / "latest.json"
BASE = "https://fapi.binance.com"
SYMBOL = "BTCUSDT"

# 제안 기본값 — 사용자가 정한다
DEFAULTS = {"ann90_min": 3.0, "ann30_min": 0.0, "neg_run": 3, "basis_abs_max": 0.5, "stale_hours": 24}


def _get(path: str, params: dict) -> object:
    import requests

    r = requests.get(BASE + path, params=params, timeout=20)
    r.raise_for_status()
    return r.json()


def update_cache(offline: bool) -> pd.DataFrame:
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    if CACHE.exists():
        df = pd.read_parquet(CACHE)
    else:
        df = pd.read_parquet(SEED)[["fundingRate"]].astype(float)
    if offline:
        return df
    last = df.index[-1]
    start = int(last.timestamp() * 1000) + 1
    new = []
    for _ in range(50):                       # 상한: 50 페이지 × 1000건
        rows = _get("/fapi/v1/fundingRate", {"symbol": SYMBOL, "startTime": start, "limit": 1000})
        if not rows:
            break
        new += rows
        start = int(rows[-1]["fundingTime"]) + 1
        if len(rows) < 1000:
            break
        time.sleep(0.3)
    if new:
        add = pd.DataFrame(
            {"fundingRate": [float(r["fundingRate"]) for r in new]},
            index=pd.to_datetime([r["fundingTime"] for r in new], unit="ms", utc=True))
        df = pd.concat([df, add])
        df = df[~df.index.duplicated(keep="last")].sort_index()
    df.to_parquet(CACHE)
    return df


def live_snapshot() -> dict:
    d = _get("/fapi/v1/premiumIndex", {"symbol": SYMBOL})
    mark, index = float(d["markPrice"]), float(d["indexPrice"])
    return {"mark": mark, "index": index, "basisPct": (mark / index - 1) * 100,
            "lastFundingRate": float(d["lastFundingRate"]),
            "nextFundingTime": pd.to_datetime(int(d["nextFundingTime"]), unit="ms", utc=True).isoformat()}


def metrics(f: pd.Series, now: pd.Timestamp | None = None) -> dict:
    """f: 결제별 펀딩률(소수), 시간 오름차순. 연환산 = 최근 d일 합 × 365/d (단순합, 복리 아님)."""
    now = now or f.index[-1]
    out = {"lastEvent": f.index[-1].isoformat(), "lastRate": float(f.iloc[-1]),
           "hoursSinceLast": float((now - f.index[-1]).total_seconds() / 3600)}
    for d in (7, 30, 90, 180, 365):
        w = f[f.index > f.index[-1] - pd.Timedelta(days=d)]
        out[f"ann{d}"] = float(w.sum() * 365 / d * 100)
        out[f"neg{d}"] = float((w < 0).mean() * 100)
    tail = f.iloc[-3:]
    out["lastNegRun"] = int((tail < 0).sum()) if (tail < 0).all() else int(_neg_run(f))
    return out


def _neg_run(f: pd.Series) -> int:
    n = 0
    for v in f.iloc[::-1]:
        if v < 0:
            n += 1
        else:
            break
    return n


def alerts(m: dict, live: dict | None, cfg: dict) -> list[str]:
    a = []
    if m["ann90"] < cfg["ann90_min"]:
        a.append(f"90일 연환산 {m['ann90']:.2f}% < {cfg['ann90_min']}% — 신규 진입 중단·청산 검토")
    if m["ann30"] < cfg["ann30_min"]:
        a.append(f"30일 연환산 {m['ann30']:.2f}% < {cfg['ann30_min']}% — 음수 구간")
    if m["lastNegRun"] >= cfg["neg_run"]:
        a.append(f"음수 펀딩 {m['lastNegRun']}회 연속 결제")
    if m["hoursSinceLast"] > cfg["stale_hours"]:
        a.append(f"데이터가 {m['hoursSinceLast']:.0f}시간 묵음(> {cfg['stale_hours']}h) — 수집 실패 의심")
    if live and abs(live["basisPct"]) > cfg["basis_abs_max"]:
        a.append(f"베이시스(mark/index−1) {live['basisPct']:+.3f}% — 절댓값 > {cfg['basis_abs_max']}%")
    if live and live["lastFundingRate"] < 0:
        a.append(f"현재 적용 펀딩률 {live['lastFundingRate'] * 100:+.4f}% (음수)")
    return a


def selftest() -> int:
    fails = []

    def ck(name, cond):
        print(("ok   " if cond else "FAIL ") + name)
        if not cond:
            fails.append(name)

    idx = pd.date_range("2026-01-01", periods=3 * 400, freq="8h", tz="UTC")
    f = pd.Series(0.0001, index=idx)                       # 0.01%/8h = 연 10.95%
    m = metrics(f)
    ck("일정 0.01%/8h 의 연환산은 10.95%", abs(m["ann90"] - 10.95) < 0.05 and abs(m["ann365"] - 10.95) < 0.05)
    ck("정상 데이터는 알림이 없다", alerts(m, {"basisPct": 0.1, "lastFundingRate": 0.0001}, DEFAULTS) == [])
    g = f.copy()
    g.iloc[-3:] = -0.0001
    ck("음수 3연속을 잡는다", metrics(g)["lastNegRun"] == 3
       and any("연속" in x for x in alerts(metrics(g), None, DEFAULTS)))
    h = pd.Series(0.00001, index=idx)                      # 연 1.1% < 3%
    ck("90일 연환산이 임계 아래면 알린다", any("90일" in x for x in alerts(metrics(h), None, DEFAULTS)))
    ck("베이시스 초과를 잡는다", any("베이시스" in x for x in alerts(m, {"basisPct": 0.8, "lastFundingRate": 0.0001}, DEFAULTS)))
    stale = metrics(f, now=f.index[-1] + pd.Timedelta(hours=30))
    ck("30시간 묵으면 알린다", any("묵음" in x for x in alerts(stale, None, DEFAULTS)))
    ck("음수 펀딩률 라이브를 잡는다", any("음수" in x for x in alerts(m, {"basisPct": 0.0, "lastFundingRate": -0.0001}, DEFAULTS)))
    print(f"\nselftest {7 - len(fails)}/7" + ("" if not fails else f"  FAILED: {fails}"))
    return 1 if fails else 0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--offline", action="store_true")
    ap.add_argument("--selftest", action="store_true")
    for k, v in DEFAULTS.items():
        ap.add_argument("--" + k.replace("_", "-"), type=type(v), default=v)
    a = ap.parse_args()
    if a.selftest:
        return selftest()
    cfg = {k: getattr(a, k) for k in DEFAULTS}

    df = update_cache(a.offline)
    f = df["fundingRate"].astype(float)
    m = metrics(f)
    live = None if a.offline else live_snapshot()
    al = alerts(m, live, cfg)

    print(f"BTCUSDT 펀딩 — 마지막 결제 {m['lastEvent']}  ({m['lastRate'] * 100:+.4f}%)  이력 {len(f):,}건")
    print("  연환산(단순합): " + "  ".join(f"{d}일 {m[f'ann{d}']:6.2f}%" for d in (7, 30, 90, 180, 365)))
    print("  음수 비율:      " + "  ".join(f"{d}일 {m[f'neg{d}']:5.1f}%" for d in (30, 90, 365)))
    if live:
        print(f"  실시간: mark {live['mark']:,.1f} / index {live['index']:,.1f}  베이시스 {live['basisPct']:+.3f}%  "
              f"현재 펀딩률 {live['lastFundingRate'] * 100:+.4f}% (연 {live['lastFundingRate'] * 3 * 365 * 100:.1f}%)")
    print(f"  임계(제안 기본값): {cfg}")
    print("  알림: " + ("없음" if not al else ""))
    for x in al:
        print("   - " + x)
    LATEST.write_text(json.dumps({"generatedAt": pd.Timestamp.now(tz="UTC").isoformat(), "metrics": m,
                                  "live": live, "alerts": al, "config": cfg},
                                 ensure_ascii=False, indent=1), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
