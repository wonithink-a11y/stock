#!/usr/bin/env python3
"""바이낸스 신규 상장 BL7 forward 기록. 사전등록 findings/binance-listing-forward-preregistration-2026-10.md.

    python research/strategy-lab/run_binance_listing_forward.py            # 월간 점검(더 자주 돌려도 된다) → reports/ 커밋
    python research/strategy-lab/run_binance_listing_forward.py --judge    # 성숙 상장일 40 ∧ 6개월 전에는 건수만
    python research/strategy-lab/run_binance_listing_forward.py --selftest

규칙은 futures/binance_listing.py(7bba3b1)의 eligible·사건 정의를 그대로 쓴다. 기록 전용 — 매매·알림 없음.
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(HERE / "futures"))
import binance_listing as bl  # noqa: E402  동결 규칙

API = "https://data-api.binance.vision/api/v3"
OUT = ROOT / "reports" / "2026-10-binance-listing-forward"
START = pd.Timestamp("2026-10-01", tz="UTC")
D = pd.Timedelta(days=1)
OTHER_Q = ["BTC", "BNB", "BUSD", "FDUSD", "USDC"]
GATE, EXT, MONTHS, T_KEEP = 40, 80, 6, -1.65


def _json(path: str, **params):
    return bl._get(f"{API}/{path}", params=params).json()


def exchange_symbols() -> list[dict]:
    return [{"sym": s["symbol"], "base": s["baseAsset"], "quote": s["quoteAsset"]} for s in _json("exchangeInfo", permissions="SPOT")["symbols"]]


def first_day(sym: str) -> pd.Timestamp | None:
    k = _json("klines", symbol=sym, interval="1d", startTime=0, limit=1)
    return pd.Timestamp(int(k[0][0]), unit="ms", tz="UTC") if isinstance(k, list) and k else None


def open_on(sym: str, t: pd.Timestamp) -> float:
    k = _json("klines", symbol=sym, interval="1d", startTime=int(t.timestamp() * 1000), limit=1)
    if isinstance(k, list) and k and int(k[0][0]) == int(t.timestamp() * 1000):   # 요청한 날 봉인지(교훈81)
        return float(k[0][1])
    return float("nan")


def load(name: str, default):
    f = OUT / name
    return json.loads(f.read_text(encoding="utf-8")) if f.exists() else default


def save(name: str, obj):
    (OUT / name).write_text(json.dumps(obj, ensure_ascii=False, indent=1, sort_keys=True), encoding="utf-8")


def seed_seen(months: dict) -> list[str]:
    """백테스트 목록(월별 일봉이 있는 코인 = 2026-09 까지 나타난 코인)만. 그 뒤 코인은 detect 가 L ≥ START 로 거른다."""
    return sorted({bl.split_symbol(s)[0] for s, ms in months.items() if bl.split_symbol(s) and ms})


def detect(current: list[dict], seen: set, first_fn) -> tuple[list[dict], set]:
    by_base = {}
    for x in current:
        by_base.setdefault(x["base"], []).append(x)
    new, add = [], set()
    for b, xs in sorted(by_base.items()):
        if b in seen:
            continue
        add.add(b)
        if not bl.eligible(b):
            continue
        usdt = next((x["sym"] for x in xs if x["quote"] == "USDT"), None)
        if usdt is None:
            continue
        L = first_fn(usdt)
        others = [first_fn(x["sym"]) for x in xs if x["quote"] in OTHER_Q]
        if L is None or L < START or any(o is not None and o < L for o in others):
            continue
        new.append({"base": b, "sym": usdt, "L": L.strftime("%Y-%m-%d")})
    return new, add


def mature(events: list[dict], done: set, now: pd.Timestamp, open_fn) -> list[dict]:
    rows = []
    for e in events:
        if e["sym"] in done:
            continue
        L = pd.Timestamp(e["L"], tz="UTC")
        t0, t1 = L + D, L + 8 * D
        if now < t1 + pd.Timedelta(hours=1):
            continue
        p0, p1, b0, b1 = open_fn(e["sym"], t0), open_fn(e["sym"], t1), open_fn("BTCUSDT", t0), open_fn("BTCUSDT", t1)
        ok = all(np.isfinite([p0, p1, b0, b1]))
        rows.append({"sym": e["sym"], "L": e["L"], "ok": bool(ok), "relBp": round(((p1 / p0 - 1) - (b1 / b0 - 1)) * 1e4, 2) if ok else None,
                     "stockLike": bool(e["base"].endswith("B") and e["base"][:-1].isalpha() and len(e["base"]) <= 6), "recordedAt": now.isoformat()})
    return rows


def judge(obs: list[dict], today: pd.Timestamp) -> dict:
    ok = [o for o in obs if o["ok"]]
    if not ok:
        return {"n_days": 0, "judge": "거부 — 관측 없음"}
    s = pd.Series([o["relBp"] for o in ok], index=[o["L"] for o in ok]).groupby(level=0).mean().sort_index()
    age = (today - pd.Timestamp(s.index[0], tz="UTC")).days
    if len(s) < GATE or age < MONTHS * 30:
        return {"n_days": int(len(s)), "ageDays": age, "missing": sum(1 for o in obs if not o["ok"]), "judge": f"거부 — {len(s)}/{GATE} 상장일 · {age}/{MONTHS * 30}일(사전등록 §2)"}
    use = s.iloc[:EXT] if len(s) >= EXT else s.iloc[:GATE]
    x = use.to_numpy()
    t = float(x.mean() / (x.std(ddof=1) / np.sqrt(len(x)))) if x.std(ddof=1) > 0 else 0.0
    v = "REJECT" if x.mean() >= 0 else "CONFIRMED" if t <= T_KEEP else ("INCONCLUSIVE — 연장" if len(use) == GATE else "REJECT")
    return {"n_days": int(len(s)), "used": int(len(use)), "mean_bp": round(float(x.mean()), 1), "t": round(t, 2), "verdict": v}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--judge", action="store_true")
    ap.add_argument("--selftest", action="store_true")
    a = ap.parse_args()
    if a.selftest:
        return selftest()
    OUT.mkdir(parents=True, exist_ok=True)
    obs_f = OUT / "observations.jsonl"
    obs = [json.loads(x) for x in obs_f.read_text(encoding="utf-8").splitlines()] if obs_f.exists() else []
    if a.judge:
        print(json.dumps(judge(obs, pd.Timestamp.now(tz="UTC")), ensure_ascii=False, indent=1))
        return 0
    current = exchange_symbols()
    seen = load("seen_bases.json", None)
    first_run = seen is None
    if first_run:
        seen = seed_seen(json.loads((bl.DATA / "months.json").read_text(encoding="utf-8")))
    events = load("events.json", [])
    new, add = detect(current, set(seen), first_day)
    events += new
    save("seen_bases.json", sorted(set(seen) | add))
    save("events.json", events)
    now = pd.Timestamp(datetime.now(timezone.utc))
    rows = mature(events, {o["sym"] for o in obs}, now, open_on)
    with open(obs_f, "a", encoding="utf-8") as f:
        for r in rows:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    print(json.dumps({"firstRun": first_run, "seenBases": len(set(seen) | add), "newEvents": [e["sym"] for e in new], "events": len(events),
                      "newObservations": len(rows), "judge": judge(obs + rows, now)}, ensure_ascii=False))
    return 0


def selftest():
    ok = 0
    cur = [{"sym": "AAAUSDT", "base": "AAA", "quote": "USDT"}, {"sym": "AAABTC", "base": "AAA", "quote": "BTC"},
           {"sym": "BBBUSDT", "base": "BBB", "quote": "USDT"}, {"sym": "OLDUSDT", "base": "OLD", "quote": "USDT"},
           {"sym": "CCCBNB", "base": "CCC", "quote": "BNB"}, {"sym": "BTCUPUSDT", "base": "BTCUP", "quote": "USDT"}]
    fd = {"AAAUSDT": "2026-11-05", "AAABTC": "2026-11-01", "BBBUSDT": "2026-11-10", "OLDUSDT": "2020-01-01", "BTCUPUSDT": "2026-11-10"}
    new, add = detect(cur, {"OLD"}, lambda s: pd.Timestamp(fd[s], tz="UTC") if s in fd else None)
    assert [e["base"] for e in new] == ["BBB"] and {"AAA", "BBB", "CCC", "BTCUP"} <= add; ok += 1     # AAA 는 BTC 먼저 · CCC 는 USDT 없음 · 레버리지 제외
    ev = [{"base": "BBB", "sym": "BBBUSDT", "L": "2026-11-10"}]
    px = {("BBBUSDT", "2026-11-11"): 100.0, ("BBBUSDT", "2026-11-18"): 80.0, ("BTCUSDT", "2026-11-11"): 10.0, ("BTCUSDT", "2026-11-18"): 10.0}
    of = lambda s, t: px.get((s, t.strftime("%Y-%m-%d")), float("nan"))  # noqa: E731
    assert mature(ev, set(), pd.Timestamp("2026-11-17", tz="UTC"), of) == []; ok += 1                # 아직 성숙 전
    r = mature(ev, set(), pd.Timestamp("2026-11-19", tz="UTC"), of)
    assert r[0]["ok"] and abs(r[0]["relBp"] + 2000) < 1e-6; ok += 1
    assert mature(ev, {"BBBUSDT"}, pd.Timestamp("2026-12-01", tz="UTC"), of) == []; ok += 1          # 두 번 안 씀
    assert "거부" in judge(r, pd.Timestamp("2026-12-01", tz="UTC"))["judge"]; ok += 1
    obs = [{"sym": f"S{i}", "L": str((pd.Timestamp("2026-11-01") + pd.Timedelta(days=i)).date()), "ok": True, "relBp": -500.0 + (i % 7) * 50} for i in range(40)]
    assert judge(obs, pd.Timestamp("2027-06-01", tz="UTC"))["verdict"] == "CONFIRMED"; ok += 1
    print(f"selftest {ok}/6 OK")
    return 0


if __name__ == "__main__":
    sys.exit(main())
