#!/usr/bin/env python3
"""코인베이스 프리미엄 z ≤ −2 → BTC 24시간 forward 기록. 사전등록 findings/coinbase-premium-negz-forward-preregistration-2026-10.md(87505fd).

    python research/strategy-lab/run_coinbase_premium_negz_forward.py            # 월간 점검(더 자주 돌려도 된다) → reports/ 커밋
    python research/strategy-lab/run_coinbase_premium_negz_forward.py --judge    # 성숙 사건 40 ∧ 6개월 전에는 건수만
    python research/strategy-lab/run_coinbase_premium_negz_forward.py --selftest

P·z 는 futures/coinbase_premium.py(20401a4)의 zscore 를 그대로 쓴다. 기록 전용 — 매매·알림 없음.
"""
from __future__ import annotations

import argparse
import io
import json
import sys
import time
import zipfile
from pathlib import Path

import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(HERE / "futures"))
import coinbase_premium as cp  # noqa: E402  동결 z 정의

OUT = ROOT / "reports" / "2026-10-coinbase-premium-negz-forward"
START = pd.Timestamp("2026-10-01", tz="UTC")
FETCH = pd.Timestamp("2026-08-15", tz="UTC")
H = pd.Timedelta(hours=1)
K, HOLD = -2.0, 24
GATE, EXT, MONTHS, T_KEEP, COSTS = 40, 80, 6, -1.65, (10.0, 20.0)


def _get(url: str, **params):
    import requests
    for k in range(6):
        try:
            r = requests.get(url, params=params, timeout=60)
            if r.status_code == 200:
                return r
        except Exception:
            pass
        time.sleep(2 ** k)
    raise RuntimeError(f"응답 없음: {url}")


def cb_closes(t0: pd.Timestamp, t1: pd.Timestamp) -> pd.Series:
    out = {}
    t = t0
    while t < t1:
        e = min(t + 300 * H, t1)
        rows = _get("https://api.exchange.coinbase.com/products/BTC-USD/candles", granularity=3600,
                    start=f"{t:%Y-%m-%dT%H:%M:%SZ}", end=f"{(e - H):%Y-%m-%dT%H:%M:%SZ}").json()
        for ts, _lo, _hi, _op, cl, _v in rows:
            ts = pd.Timestamp(ts, unit="s", tz="UTC")
            if t <= ts < e:                       # 요청 구간 안 봉만(교훈81)
                out[ts] = float(cl)
        t = e
        time.sleep(0.15)
    return pd.Series(out, dtype=float).sort_index()


def bn_bars(t0: pd.Timestamp, t1: pd.Timestamp) -> pd.DataFrame:
    rows = {}
    t = t0
    while t < t1:
        k = _get("https://data-api.binance.vision/api/v3/klines", symbol="BTCUSDT", interval="1h",
                 startTime=int(t.timestamp() * 1000), endTime=int((t1 - H).timestamp() * 1000), limit=1000).json()
        if not k:
            break
        for x in k:
            ts = pd.Timestamp(int(x[0]), unit="ms", tz="UTC")
            if t0 <= ts < t1:
                rows[ts] = (float(x[1]), float(x[4]))
        t = pd.Timestamp(int(k[-1][0]), unit="ms", tz="UTC") + H
    return pd.DataFrame.from_dict(rows, orient="index", columns=["open", "close"]).sort_index()


def zseries(cb: pd.Series, bn: pd.DataFrame, t1: pd.Timestamp) -> pd.Series:
    grid = pd.date_range(FETCH + H, t1, freq="h")
    p = pd.Series(cb.reindex(grid - H).to_numpy() / bn["close"].reindex(grid - H).to_numpy() - 1, index=grid)
    return cp.zscore(p)


def find_events(z: pd.Series, start: pd.Timestamp) -> list[tuple[pd.Timestamp, float]]:
    """z ≤ −2 첫 시각, 사건 뒤 24h 차단(마이너스 쪽만). 차단은 start 이전 사건에서도 이어진다."""
    ev, free = [], None
    for T, v in z[z <= K].items():
        if free is not None and T < free:
            continue
        free = T + HOLD * H
        if T >= start:
            ev.append((T, float(v)))
    return ev


def _read(name: str) -> list[dict]:
    f = OUT / name
    return [json.loads(x) for x in f.read_text(encoding="utf-8").splitlines() if x.strip()] if f.exists() else []


def _append(name: str, rows: list[dict]):
    if rows:
        with (OUT / name).open("a", encoding="utf-8") as f:
            for r in rows:
                f.write(json.dumps(r, ensure_ascii=False, sort_keys=True) + "\n")


def update(events: list[dict], obs: list[dict], z: pd.Series, bo: pd.Series, now: pd.Timestamp) -> tuple[list, list, int]:
    seen = {e["T"] for e in events}
    new_ev = [{"T": str(T), "z": round(v, 3), "recordedAt": now.isoformat(timespec="seconds")}
              for T, v in find_events(z, START) if str(T) not in seen]
    cur = {str(T) for T, _ in find_events(z, START)}
    drift = sum(1 for e in events if e["T"] not in cur and pd.Timestamp(e["T"]) + HOLD * H < z.index[-1])
    done = {o["T"] for o in obs}
    new_obs = []
    for e in events + new_ev:
        T = pd.Timestamp(e["T"])
        if e["T"] in done or T + HOLD * H > bo.index[-1]:
            continue
        p0, p1 = bo.get(T, np.nan), bo.get(T + HOLD * H, np.nan)
        ok = bool(np.isfinite(p0) and np.isfinite(p1))
        w = z[T:T + (HOLD - 1) * H]
        new_obs.append({"T": e["T"], "ok": ok, "r24_bp": round((p1 / p0 - 1) * 1e4, 2) if ok else None,
                        "minZ24": round(float(w.min()), 3) if len(w) else None, "recordedAt": now.isoformat(timespec="seconds")})
    return new_ev, new_obs, drift


def funding_bp(T: pd.Timestamp, cache: dict) -> float | None:
    """(T, T+24h] 펀딩률 합 × 1e4 — 양이면 숏이 받는다. 월 파일이 아직 없으면 None."""
    tot = 0.0
    for m in sorted({T.strftime("%Y-%m"), (T + HOLD * H).strftime("%Y-%m")}):
        if m not in cache:
            import requests
            r = requests.get(f"https://data.binance.vision/data/futures/um/monthly/fundingRate/BTCUSDT/BTCUSDT-fundingRate-{m}.zip", timeout=60)
            if r.status_code != 200:
                cache[m] = None
            else:
                with zipfile.ZipFile(io.BytesIO(r.content)) as zf:
                    d = pd.read_csv(zf.open(zf.namelist()[0]))
                cache[m] = pd.Series(d.iloc[:, 2].to_numpy(float), index=pd.to_datetime(d.iloc[:, 0], unit="ms", utc=True).dt.floor("min"))
        if cache[m] is None:
            return None
        s = cache[m]
        tot += float(s[(s.index > T) & (s.index <= T + HOLD * H)].sum())
    return tot * 1e4


def _t(x: np.ndarray) -> float:
    return float(x.mean() / (x.std(ddof=1) / np.sqrt(len(x)))) if len(x) > 2 and x.std(ddof=1) > 0 else float("nan")


def judge(obs: list[dict], today: pd.Timestamp, fund=None) -> dict:
    good = [o for o in obs if o["ok"]]
    if not good:
        return {"n": 0, "judge": "거부 — 관측 없음"}
    first = min(pd.Timestamp(o["T"]) for o in obs)
    age = int((today - first).days)
    miss = sum(1 for o in obs if not o["ok"])
    if len(good) < GATE or age < MONTHS * 30:
        return {"n": len(good), "ageDays": age, "missing": miss, "judge": f"거부 — {len(good)}/{GATE} 사건 · {age}/{MONTHS * 30}일(사전등록 §2)"}
    use = sorted(good, key=lambda o: o["T"])[:EXT] if len(good) >= EXT else sorted(good, key=lambda o: o["T"])[:GATE]
    stage = "연장(80)" if len(good) >= EXT else "1차(40)"
    r = np.array([o["r24_bp"] for o in use])
    m, t = float(r.mean()), _t(r)
    v = "CONFIRMED" if m < 0 and t <= T_KEEP else "REJECT" if m >= 0 or stage.startswith("연장") else "INCONCLUSIVE"
    out = {"stage": stage, "n": len(use), "missing": miss, "ageDays": age, "A_mean_bp": round(m, 1), "A_t": round(t, 2), "A_verdict": v}
    if v == "CONFIRMED":
        cache = {}
        f = [(fund or funding_bp)(pd.Timestamp(o["T"]), cache) for o in use]
        if any(x is None for x in f):
            out["B_verdict"] = "보류 — 펀딩 월 파일 없음"
        else:
            nets = {c: -r - c + np.array(f) for c in COSTS}
            out.update({"B_net10_bp": round(float(nets[10.0].mean()), 1), "B_net20_bp": round(float(nets[20.0].mean()), 1),
                        "B_funding_bp": round(float(np.mean(f)), 1),
                        "B_verdict": "EXECUTABLE 후보" if all(x.mean() > 0 for x in nets.values()) else "숏 불가, 보류만"})
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--judge", action="store_true")
    ap.add_argument("--selftest", action="store_true")
    a = ap.parse_args()
    if a.selftest:
        return selftest()
    OUT.mkdir(parents=True, exist_ok=True)
    events, obs = _read("events.jsonl"), _read("observations.jsonl")
    now = pd.Timestamp.now(tz="UTC")
    if a.judge:
        print(json.dumps(judge(obs, now), ensure_ascii=False, indent=1))
        return 0
    t1 = now.floor("h")
    cb, bn = cb_closes(FETCH, t1), bn_bars(FETCH, t1)
    z = zseries(cb, bn, t1).dropna()
    new_ev, new_obs, drift = update(events, obs, z, bn["open"], now)
    _append("events.jsonl", new_ev)
    _append("observations.jsonl", new_obs)
    ok = [o for o in obs + new_obs if o["ok"]]
    base = ((bn["open"].shift(-HOLD) / bn["open"] - 1) * 1e4)[START:].dropna()
    summ = {"asOf": now.isoformat(timespec="seconds"), "zLast": round(float(z.iloc[-1]), 3), "zHours": int(len(z)),
            "cbHours": int(len(cb)), "bnHours": int(len(bn)), "events": len(events) + len(new_ev), "newEvents": len(new_ev),
            "observations": len(ok), "missing": sum(1 for o in obs + new_obs if not o["ok"]), "newObservations": len(new_obs),
            "driftEvents": drift, "anyHour24hMean_bp_record": round(float(base.mean()), 1) if len(base) else None,
            "judge": judge(obs + new_obs, now)}
    (OUT / "_summary.json").write_text(json.dumps(summ, ensure_ascii=False, indent=1), encoding="utf-8")
    print(json.dumps({k: summ[k] for k in ("events", "newEvents", "observations", "newObservations", "missing", "driftEvents", "judge")}, ensure_ascii=False))
    return 0


def selftest():
    ok = 0
    idx = pd.date_range("2026-09-30 20:00", periods=120, freq="h", tz="UTC")
    z = pd.Series(0.0, index=idx)
    z[pd.Timestamp("2026-09-30 22:00", tz="UTC")] = -2.5          # START 이전 사건 — 차단만 넘어온다
    z[pd.Timestamp("2026-10-01 05:00", tz="UTC")] = -3.0          # 차단 중(22:00+24h)
    z[pd.Timestamp("2026-10-01 23:00", tz="UTC")] = -2.1          # 사건
    z[pd.Timestamp("2026-10-02 01:00", tz="UTC")] = 2.5           # 플러스는 무관
    ev = find_events(z, START)
    assert [str(T) for T, _ in ev] == ["2026-10-01 23:00:00+00:00"]; ok += 1
    bo = pd.Series(np.arange(len(idx), dtype=float) + 100, index=idx)
    now = pd.Timestamp("2026-10-06", tz="UTC")
    e1, o1, _ = update([], [], z, bo, now)
    assert len(e1) == 1 and len(o1) == 1 and o1[0]["ok"] and abs(o1[0]["r24_bp"] - ((151 / 127) - 1) * 1e4) < 0.01; ok += 1
    e2, o2, d2 = update(e1, o1, z, bo, now)
    assert e2 == [] and o2 == [] and d2 == 0; ok += 1                # 다시 돌려도 새 기록 없음(고쳐 쓰지 않음)
    assert "거부" in judge(o1, now)["judge"]; ok += 1
    fake = [{"T": str(pd.Timestamp("2026-10-01", tz="UTC") + pd.Timedelta(days=i)), "ok": True, "r24_bp": -60.0 + (i % 5) * 10} for i in range(45)]
    j = judge(fake, pd.Timestamp("2027-06-01", tz="UTC"), fund=lambda T, c: 1.0)
    assert j["A_verdict"] == "CONFIRMED" and j["n"] == 40 and j["B_verdict"] == "EXECUTABLE 후보"; ok += 1
    pos = [dict(o, r24_bp=abs(o["r24_bp"])) for o in fake]
    assert judge(pos, pd.Timestamp("2027-06-01", tz="UTC"))["A_verdict"] == "REJECT"; ok += 1
    print(f"selftest {ok}/6 OK")
    return 0


if __name__ == "__main__":
    sys.exit(main())
