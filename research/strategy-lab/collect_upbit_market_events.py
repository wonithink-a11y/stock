#!/usr/bin/env python3
"""업비트 투자유의·주의 플래그 forward 기록. 사전등록 findings/upbit-market-events-forward-preregistration-2026-10.md.

    python research/strategy-lab/collect_upbit_market_events.py            # 1회 수집(매시 :07 KST, VM 타이머)
    python research/strategy-lab/collect_upbit_market_events.py --judge    # 12개월 ∧ 갈래 100건 전에는 건수만
    python research/strategy-lab/collect_upbit_market_events.py --selftest # 네트워크 없음

업비트 공식 공개 API(market/all?is_details=true · ticker)만 쓴다 — 키 없음, 주문 없음.
상태(VM): ~/collector-venv/upbit-events/ — state.json(직전 플래그·목록) · events.jsonl(변화) ·
snapshots-YYYY-MM.jsonl(플래그) · prices-YYYY-MM.jsonl(KRW 전 종목 가격, 폐지 종목 포함).
★ state.json 을 지우면 다음 실행이 '첫 실행'이 되어 켜져 있던 플래그를 사건으로 세지 않는다(present_at_start). 원장(jsonl)은 지우지 않는다.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd

KINDS = ["WARNING", "PRICE_FLUCTUATIONS", "TRADING_VOLUME_SOARING", "DEPOSIT_AMOUNT_SOARING",
         "GLOBAL_PRICE_DIFFERENCES", "CONCENTRATION_OF_SMALL_ACCOUNTS"]
MIN_KRW = 100
REARM_H = 168
HORIZONS = (24, 72, 168)
JUDGE_DAYS, JUDGE_MIN_N, T_BONF = 365, 100, -2.64
DEFAULT_DIR = os.path.expanduser("~/collector-venv/upbit-events")
BASE = "https://api.upbit.com/v1"

for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(errors="replace")
    except Exception:
        pass


# ---------- 수집 ----------
def _get(path, params=None):
    import requests
    for k in range(5):
        try:
            r = requests.get(BASE + path, params=params, timeout=30)
            if r.status_code == 200:
                return r.json()
        except requests.RequestException:
            pass
        time.sleep(2 ** k)
    raise RuntimeError(f"업비트 요청 실패: {path}")


def flags_of(markets: list) -> dict:
    """market/all 응답 → {KRW 마켓: [켜진 갈래]} (켜진 것이 없으면 빈 리스트)."""
    out = {}
    for m in markets:
        if not m["market"].startswith("KRW-"):
            continue
        ev = m.get("market_event") or {}
        on = (["WARNING"] if ev.get("warning") else []) + sorted(k for k, v in (ev.get("caution") or {}).items() if v)
        out[m["market"]] = on
    return out


def fetch_prices(krw: list) -> dict:
    px = {}
    for i in range(0, len(krw), 100):
        for row in _get("/ticker", {"markets": ",".join(krw[i:i + 100])}):
            px[row["market"]] = float(row["trade_price"])
        time.sleep(0.15)
    return px


def diff_events(prev: dict | None, cur: dict, px: dict, T: str, gap_h: float) -> list:
    """직전 상태와 비교해 사건을 만든다. 첫 실행(prev None)은 present_at_start 만."""
    ev = []
    if prev is None:
        for m, on in cur.items():
            for k in on:
                ev.append({"t": T, "market": m, "kind": k, "change": "present_at_start", "price": px.get(m)})
        return ev
    for m in sorted(set(cur) | set(prev)):
        if m not in prev:
            ev.append({"t": T, "market": m, "kind": "LISTING", "change": "listed", "price": px.get(m), "maxDelayH": gap_h})
            continue
        if m not in cur:
            ev.append({"t": T, "market": m, "kind": "LISTING", "change": "delisted", "price": None, "maxDelayH": gap_h})
            continue
        a, b = set(prev[m]), set(cur[m])
        for k in sorted(b - a):
            ev.append({"t": T, "market": m, "kind": k, "change": "on", "price": px.get(m), "maxDelayH": gap_h})
        for k in sorted(a - b):
            ev.append({"t": T, "market": m, "kind": k, "change": "off", "price": px.get(m), "maxDelayH": gap_h})
    return ev


def _append(d: Path, name: str, rec: dict):
    with open(d / name, "a", encoding="utf-8") as f:
        f.write(json.dumps(rec, ensure_ascii=False) + "\n")


def collect(d: Path, now: datetime, markets: list, prices_fn=fetch_prices, log=print) -> dict:
    cur = flags_of(markets)
    if len(cur) < MIN_KRW:
        raise RuntimeError(f"KRW 마켓 {len(cur)}개 < {MIN_KRW} — 응답 이상, 기록하지 않는다")
    T = pd.Timestamp(now).floor("h")
    px = prices_fn(sorted(cur))
    sf = d / "state.json"
    st = json.loads(sf.read_text(encoding="utf-8")) if sf.exists() else None
    gap_h = round((T - pd.Timestamp(st["T"])) / pd.Timedelta(hours=1), 1) if st else None
    ev = diff_events(st["flags"] if st else None, cur, px, str(T), gap_h)
    d.mkdir(parents=True, exist_ok=True)
    month = T.strftime("%Y-%m")
    _append(d, f"snapshots-{month}.jsonl", {"t": str(T), "nKRW": len(cur), "flagged": {m: k for m, k in cur.items() if k}})
    _append(d, f"prices-{month}.jsonl", {"t": str(T), "n": len(px), "px": px})
    for e in ev:
        _append(d, "events.jsonl", e)
    sf.write_text(json.dumps({"T": str(T), "flags": cur, "start": st["start"] if st else str(T)}, ensure_ascii=False), encoding="utf-8")
    out = {"T": str(T), "nKRW": len(cur), "flagged": sum(1 for k in cur.values() if k), "events": len(ev),
           "on": sum(e["change"] == "on" for e in ev), "gapH": gap_h}
    log(json.dumps(out, ensure_ascii=False))
    return out


# ---------- 판정 ----------
def load_prices(d: Path) -> pd.DataFrame:
    rows = []
    for f in sorted(d.glob("prices-*.jsonl")):
        for line in f.read_text(encoding="utf-8").splitlines():
            r = json.loads(line)
            rows.append(pd.Series(r["px"], name=pd.Timestamp(r["t"])))
    return pd.DataFrame(rows).sort_index() if rows else pd.DataFrame()


def onsets(events: list) -> pd.DataFrame:
    """off→on 사건, 같은 종목·갈래는 168시간 안 재점화를 새 사건으로 세지 않는다."""
    last, out = {}, []
    for e in events:
        if e["change"] != "on" or e["kind"] not in KINDS:
            continue
        t, key = pd.Timestamp(e["t"]), (e["market"], e["kind"])
        if key in last and t < last[key] + pd.Timedelta(hours=REARM_H):
            continue
        last[key] = t
        out.append({"t": t, "market": e["market"], "kind": e["kind"]})
    return pd.DataFrame(out)


def abnormal(on: pd.DataFrame, px: pd.DataFrame, h: int) -> pd.Series:
    """사건 시각 → h 시간 뒤(그 사이 폐지면 마지막 가격) 종목 수익 − KRW 등가중 수익."""
    vals = []
    for _, r in on.iterrows():
        if r["market"] not in px.columns or r["t"] not in px.index:
            vals.append(np.nan)
            continue
        end = r["t"] + pd.Timedelta(hours=h)
        win = px.loc[r["t"]:end]
        if win.index[-1] < end - pd.Timedelta(hours=2):      # 아직 h 시간이 안 지났거나 수집 공백
            vals.append(np.nan)
            continue
        p = win[r["market"]].dropna()
        coin = p.iloc[-1] / p.iloc[0] - 1 if len(p) else np.nan
        a, b = px.loc[r["t"]], win.iloc[-1]
        both = a.notna() & b.notna()
        mkt = float((b[both] / a[both] - 1).mean())
        vals.append((coin - mkt) * 1e4)
    return pd.Series(vals, index=on.index)


def judge(d: Path, force=False) -> dict:
    sf, ef = d / "state.json", d / "events.jsonl"
    if not sf.exists() or not ef.exists():
        return {"judge": "거부 — 자료 없음"}
    start = pd.Timestamp(json.loads(sf.read_text(encoding="utf-8"))["start"])
    events = [json.loads(x) for x in ef.read_text(encoding="utf-8").splitlines()]
    on = onsets(events)
    counts = {k: int((on["kind"] == k).sum()) if len(on) else 0 for k in KINDS}
    days = (pd.Timestamp.now(tz="UTC") - start).days
    if days < JUDGE_DAYS and not force:
        return {"judge": f"거부 — 수집 {days}일 < {JUDGE_DAYS}일(사전등록 §3)", "onset_counts": counts}
    px = load_prices(d)
    out = {"days": days, "onset_counts": counts, "kinds": {}}
    for k in KINDS:
        sub = on[on["kind"] == k]
        if len(sub) < JUDGE_MIN_N:
            out["kinds"][k] = {"n": len(sub), "verdict": "표본 부족"}
            continue
        res = {}
        for h in HORIZONS:
            a = abnormal(sub, px, h)
            dly = a.groupby(sub["t"].dt.tz_convert("Asia/Seoul").dt.date).mean().dropna()
            t_ = float(dly.mean() / (dly.std(ddof=1) / np.sqrt(len(dly)))) if len(dly) > 2 else np.nan
            res[f"{h}h"] = {"days": int(len(dly)), "bp": round(float(dly.mean()), 1), "t": round(t_, 2)}
        m, t72 = res["72h"]["bp"], res["72h"]["t"]
        res["verdict"] = "회피 근거(INFORMATION)" if m < 0 and t72 <= T_BONF else "근거 없음"
        out["kinds"][k] = res
    return out


# ---------- 시험 ----------
def selftest():
    import tempfile
    failed = 0

    def ok(c, label):
        nonlocal failed
        print(("  ok   " if c else "  FAIL ") + label)
        failed += 0 if c else 1

    def mk(name, warning=False, **caution):
        c = {k: False for k in KINDS[1:]}
        c.update(caution)
        return {"market": name, "market_event": {"warning": warning, "caution": c}}

    base = [mk(f"KRW-C{i:03d}") for i in range(120)] + [mk("BTC-X")]
    fake_px = lambda ms: {m: 100.0 for m in ms}
    with tempfile.TemporaryDirectory() as d:
        d = Path(d)
        t0 = datetime(2026, 11, 1, 0, 7, tzinfo=timezone.utc)
        first = [mk("KRW-C000", warning=True)] + base[1:]
        r = collect(d, t0, first, fake_px, log=lambda *a: None)
        ev = [json.loads(x) for x in (d / "events.jsonl").read_text().splitlines()]
        ok(r["on"] == 0 and ev[0]["change"] == "present_at_start", "첫 실행에 켜진 플래그는 사건이 아니다")
        second = [mk("KRW-C000", warning=True), mk("KRW-C001", TRADING_VOLUME_SOARING=True)] + base[2:] + [mk("KRW-NEW")]
        r = collect(d, datetime(2026, 11, 1, 3, 7, tzinfo=timezone.utc), second, fake_px, log=lambda *a: None)
        ev = [json.loads(x) for x in (d / "events.jsonl").read_text().splitlines()][1:]
        ok(r["on"] == 1 and r["gapH"] == 3.0, "off→on 1건, 빠진 실행은 지연 3시간으로 기록")
        ok(any(e["change"] == "listed" and e["market"] == "KRW-NEW" for e in ev), "상장(목록 추가) 기록")
        ok("BTC-X" not in json.loads((d / "state.json").read_text())["flags"], "KRW 마켓만")
        try:
            collect(d, t0, base[:50], fake_px, log=lambda *a: None)
            ok(False, "KRW < 100 이면 실패")
        except RuntimeError:
            ok(True, "KRW < 100 이면 실패(기록 안 함)")
        ok("거부" in judge(d)["judge"], "12개월 전 --judge 거부")
    # 재점화 168시간 규칙
    t = pd.Timestamp("2026-11-01", tz="UTC")
    evs = [{"t": str(t), "market": "KRW-A", "kind": "WARNING", "change": "on"},
           {"t": str(t + pd.Timedelta(hours=100)), "market": "KRW-A", "kind": "WARNING", "change": "on"},
           {"t": str(t + pd.Timedelta(hours=200)), "market": "KRW-A", "kind": "WARNING", "change": "on"}]
    ok(len(onsets(evs)) == 2, "168시간 안 재점화는 새 사건 아님")
    # 초과수익: 코인 +10%, 시장(두 종목 평균) +5% → +500bp 근처
    idx = pd.date_range(t, periods=80, freq="h")
    a_px = np.full(80, 100.0)
    a_px[72:] = 110.0                                   # 72시간째에 +10%
    px = pd.DataFrame({"KRW-A": a_px, "KRW-B": 100.0}, index=idx)
    on = pd.DataFrame([{"t": t, "market": "KRW-A", "kind": "WARNING"}])
    ok(abs(abnormal(on, px, 72).iloc[0] - 500.0) < 1e-6, "초과수익 = 코인(+10%) − 등가중(+5%) = +500bp")
    ok(np.isnan(abnormal(on, px.iloc[:40], 72).iloc[0]), "72시간이 아직 안 지났으면 결측")
    print(f"\n{'FAILED' if failed else 'PASSED'} - {failed} failure(s)")
    return 1 if failed else 0


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--judge", action="store_true")
    ap.add_argument("--selftest", action="store_true")
    ap.add_argument("--state-dir", default=os.environ.get("UPBIT_EVENTS_DIR", DEFAULT_DIR))
    a = ap.parse_args()
    d = Path(a.state_dir)
    if a.selftest:
        return selftest()
    if a.judge:
        print(json.dumps(judge(d), ensure_ascii=False, indent=1))
        return 0
    collect(d, datetime.now(timezone.utc), _get("/market/all", {"is_details": "true"}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
