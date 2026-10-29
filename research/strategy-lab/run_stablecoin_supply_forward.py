#!/usr/bin/env python3
"""스테이블코인 발행량 → BTC 1·7일 forward 기록. 사전등록 findings/stablecoin-supply-forward-preregistration-2026-10.md.

    python research/strategy-lab/run_stablecoin_supply_forward.py            # 월간 점검(더 자주 돌려도 된다) → reports/ 커밋
    python research/strategy-lab/run_stablecoin_supply_forward.py --judge    # S1 40건∧6개월 · S7 20건∧12개월 전에는 건수만
    python research/strategy-lab/run_stablecoin_supply_forward.py --selftest

규칙은 futures/stablecoin_supply_btc.py(33bf463)의 zscore·events 를 그대로 부른다. 방향 '늘면 오름' 고정.
유통량은 날짜별 '처음 본 값'을 supply_seen.json 에 고정한다 — DefiLlama 가 나중에 보정해도 과거 사건을 다시 계산하지 않는다.
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
import stablecoin_supply_btc as sb  # noqa: E402  동결 규칙

START = pd.Timestamp("2026-10-31", tz="UTC")
OUT = ROOT / "reports" / "2026-10-stablecoin-supply-forward"
COST = 10.0
CELLS = sb.CELLS                      # S1: 1일 · S7: 7일
GATES = {"S1": (40, 80, 183), "S7": (20, 40, 365)}   # (판정 건수, 연장 건수, 최소 일수)
T_KEEP = 1.65


def fetch_supply() -> pd.Series:
    import requests
    r = requests.get(sb.SRC["all"], timeout=60)
    r.raise_for_status()
    rows = [(int(x["date"]), (x.get("totalCirculatingUSD") or {}).get("peggedUSD")) for x in r.json()]
    return pd.Series({pd.Timestamp(t, unit="s", tz="UTC").normalize(): v for t, v in rows if v}, dtype=float).sort_index()


def fetch_opens(since: pd.Timestamp) -> pd.Series:
    import requests
    r = requests.get("https://data-api.binance.vision/api/v3/klines",
                     params={"symbol": "BTCUSDT", "interval": "1d", "limit": 1000, "startTime": int(since.timestamp() * 1000)}, timeout=60)
    r.raise_for_status()
    return pd.Series({pd.Timestamp(k[0], unit="ms", tz="UTC"): float(k[1]) for k in r.json()}, dtype=float).sort_index()


def merge_seen(seen: dict, fetched: pd.Series) -> dict:
    """처음 본 값을 지킨다 — 이미 있는 날짜는 새 값으로 바꾸지 않는다."""
    out = dict(seen)
    for d, v in fetched.items():
        out.setdefault(d.strftime("%Y-%m-%d"), float(v))
    return out


def seen_series(seen: dict) -> pd.Series:
    s = pd.Series({pd.Timestamp(k, tz="UTC"): v for k, v in seen.items()}, dtype=float).sort_index()
    return s.reindex(pd.date_range(s.index[0], s.index[-1], freq="D"))


def forward_events(seen: dict, opens: pd.Series) -> dict:
    z = sb.zscore(seen_series(seen))
    z = z[z.index >= START]
    return {k: sb.events(z, opens, h) for k, h in CELLS.items()}, z


def load_obs(out: Path) -> list:
    f = out / "observations.jsonl"
    return [json.loads(x) for x in f.read_text(encoding="utf-8").splitlines()] if f.exists() else []


def record(out: Path, ev: dict, z: pd.Series, now: datetime) -> int:
    have = {(o["cell"], o["d"]) for o in load_obs(out)}
    new = 0
    with open(out / "observations.jsonl", "a", encoding="utf-8") as f:
        for cell, s in ev.items():
            for d, r in s.items():
                key = (cell, d.strftime("%Y-%m-%d"))
                if key in have:
                    continue
                f.write(json.dumps({"cell": cell, "d": key[1], "z": round(float(z[d]), 3), "dir": int(np.sign(z[d])),
                                    "grossBp": round(float(r), 2), "netBp": round(float(r) - COST, 2), "recordedAt": now.isoformat()},
                                   ensure_ascii=False) + "\n")
                new += 1
    return new


def judge(out: Path, today: pd.Timestamp | None = None) -> dict:
    obs = load_obs(out)
    today = today or pd.Timestamp.now(tz="UTC")
    res = {}
    for cell, (n1, n2, days) in GATES.items():
        x = [o for o in obs if o["cell"] == cell]
        first = pd.Timestamp(x[0]["d"], tz="UTC") if x else None
        age = (today - first).days if first is not None else 0
        if len(x) < n1 or age < days:
            res[cell] = {"n": len(x), "ageDays": age, "judge": f"거부 — {len(x)}건/{n1} · {age}일/{days}(사전등록 §2)"}
            continue
        use = x[:n2] if len(x) >= n2 else x[:n1]
        net = np.array([o["netBp"] for o in use])
        t = float(net.mean() / (net.std(ddof=1) / np.sqrt(len(net)))) if net.std(ddof=1) > 0 else 0.0
        if net.mean() <= 0:
            v = "REJECT"
        elif t >= T_KEEP:
            v = "KEEP 후보"
        else:
            v = "INCONCLUSIVE — 연장" if len(use) == n1 else "REJECT"
        res[cell] = {"n": len(x), "used": len(use), "net_bp": round(float(net.mean()), 1), "t": round(t, 2), "verdict": v}
    return res


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--judge", action="store_true")
    ap.add_argument("--selftest", action="store_true")
    a = ap.parse_args()
    if a.selftest:
        return selftest()
    OUT.mkdir(parents=True, exist_ok=True)
    if a.judge:
        print(json.dumps(judge(OUT), ensure_ascii=False, indent=1))
        return 0
    sf = OUT / "supply_seen.json"
    seen = json.loads(sf.read_text(encoding="utf-8")) if sf.exists() else {}
    seen = merge_seen(seen, fetch_supply())
    sf.write_text(json.dumps(seen, ensure_ascii=False, sort_keys=True), encoding="utf-8")
    now = datetime.now(timezone.utc)
    ev, z = forward_events(seen, fetch_opens(START - pd.Timedelta(days=1)))
    new = record(OUT, ev, z, now)
    pending = int((z.abs() >= sb.ZTH).sum())
    print(json.dumps({"seenDays": len(seen), "lastSupplyDay": max(seen), "zDaysSinceStart": int(z.notna().sum()),
                      "zAbove2Days": pending, "newObservations": new, "counts": {k: v["n"] for k, v in judge(OUT).items()}}, ensure_ascii=False))
    return 0


def selftest():
    import tempfile
    a = pd.Series({pd.Timestamp("2026-10-01", tz="UTC"): 1.0, pd.Timestamp("2026-10-02", tz="UTC"): 2.0})
    b = pd.Series({pd.Timestamp("2026-10-02", tz="UTC"): 9.0, pd.Timestamp("2026-10-03", tz="UTC"): 3.0})
    s = merge_seen(merge_seen({}, a), b)
    assert s == {"2026-10-01": 1.0, "2026-10-02": 2.0, "2026-10-03": 3.0}            # 처음 본 값 유지
    days = pd.date_range("2025-01-01", "2027-03-01", freq="D", tz="UTC")
    rng = np.random.default_rng(7)
    sup = pd.Series(1e11 * np.exp(np.cumsum(rng.normal(0.001, 0.001, len(days)))), index=days)
    sup[sup.index >= pd.Timestamp("2026-11-20", tz="UTC")] *= 1.05
    seen = merge_seen({}, sup)
    opens = pd.Series(100.0, index=days)
    ev, z = forward_events(seen, opens)
    assert all(d >= START for s_ in ev.values() for d in s_.index)                     # 시작일 이전 사건 없음
    assert pd.Timestamp("2026-11-20", tz="UTC") in ev["S1"].index
    with tempfile.TemporaryDirectory() as d:
        d = Path(d)
        n1 = record(d, ev, z, datetime(2027, 1, 1, tzinfo=timezone.utc))
        n2 = record(d, ev, z, datetime(2027, 1, 2, tzinfo=timezone.utc))
        assert n1 > 0 and n2 == 0                                                      # 다시 돌려도 중복 없음
        assert "거부" in judge(d)["S1"]["judge"]
        obs = [{"cell": "S1", "d": f"2026-11-{i % 28 + 1:02d}", "netBp": 50.0 + (i % 5) * 10} for i in range(40)]
        (d / "observations.jsonl").write_text("\n".join(json.dumps(o) for o in obs) + "\n")
        assert judge(d, pd.Timestamp("2027-06-01", tz="UTC"))["S1"]["verdict"] == "KEEP 후보"
    print("selftest 5/5 OK")
    return 0


if __name__ == "__main__":
    sys.exit(main())
