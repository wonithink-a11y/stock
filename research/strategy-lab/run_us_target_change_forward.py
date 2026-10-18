#!/usr/bin/env python3
"""미국 목표가 큰 변경 뒤 20일 — forward 기록 · 판정. 사전등록 findings/us-target-change-forward-preregistration-2026-10.md.

입력: data/us-price-targets/(collect_us_price_targets.py 가 방금 받은 것) · 척도·시점 규칙은 run_us_price_target_reliability.load() 재사용.
출력(커밋): reports/2026-10-us-target-change-forward/events.jsonl — (종목, D) 사건 한 줄. 처음 본 값과 처음 계산한 결과는 다시 쓰지 않는다.
판정 시점 전에는 건수만 출력한다.
    python research/strategy-lab/run_us_target_change_forward.py
    python research/strategy-lab/run_us_target_change_forward.py --judge
    python research/strategy-lab/run_us_target_change_forward.py --selftest
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
OUT = HERE / "reports" / "2026-10-us-target-change-forward" / "events.jsonl"
START = pd.Timestamp("2026-10-19")
CUT_UP, CUT_DN = 0.111, 0.103
H = 20
COST = 10.0
STAGE1, FINAL = 150, 300
KST = timezone(timedelta(hours=9))


def cell(direction, mag):
    if direction > 0:
        return "UP_L" if mag >= CUT_UP else "UP_S"
    return "DN_L" if mag >= CUT_DN else "DN_S"


def detect(t):
    """척도 적용된 목표가 행 → (종목, D) 사건. 방향이 섞인 날은 뺀다."""
    e = t[(t.P > 0) & (t["T"] != t.P) & (t.d >= START)].copy()
    if e.empty:
        return pd.DataFrame(columns=["ticker", "d", "dir", "mag", "rows"])
    e["dir"] = np.sign(e["T"] - e.P)
    e["mag"] = (e["T"] / e.P - 1).abs()
    g = e.groupby(["ticker", "d"]).agg(dirs=("dir", "nunique"), dir=("dir", "first"), mag=("mag", "mean"),
                                        rows=("dir", "size")).reset_index()
    return g[g.dirs == 1].drop(columns="dirs")


def outcome(W, cal, ticker, d):
    """D1 종가 → D1+20 adj 수익 − 등가중 시장(bp). 아직 성숙 전이면 None, 가격이 없으면 'lost'."""
    adj = W["adj_close"]
    i1 = int(np.searchsorted(cal.values, np.datetime64(d), side="right"))
    if i1 + H >= len(cal):
        return None
    if ticker not in adj.columns:
        return "lost"
    a0, a1 = adj.iat[i1, adj.columns.get_loc(ticker)], adj.iat[i1 + H, adj.columns.get_loc(ticker)]
    if not (np.isfinite(a0) and np.isfinite(a1)):
        return "lost"
    r = adj.iloc[i1 + H] / adj.iloc[i1] - 1
    return round(float((a1 / a0 - 1 - r.mean()) * 1e4), 2), str(cal[i1].date()), str(cal[i1 + H].date())


def load_events():
    if not OUT.exists():
        return {}
    return {(r["ticker"], r["d"]): r for r in map(json.loads, OUT.read_text(encoding="utf-8").splitlines()) if r}


def save_events(ev):
    OUT.parent.mkdir(parents=True, exist_ok=True)
    rows = sorted(ev.values(), key=lambda r: (r["d"], r["ticker"]))
    OUT.write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows), encoding="utf-8")


def nw_t(x, lag):
    x = np.asarray(x, float)
    n = len(x)
    if n < 3:
        return float("nan")
    e = x - x.mean()
    v = e @ e / n
    for k in range(1, min(lag, n - 1) + 1):
        v += 2 * (1 - k / (lag + 1)) * (e[k:] @ e[:-k]) / n
    return float(x.mean() / np.sqrt(v / n)) if v > 0 else float("nan")


def date_series(ev, c):
    rows = [r for r in ev.values() if r["cell"] == c and isinstance(r.get("ex_bp"), (int, float))]
    if not rows:
        return pd.Series(dtype=float)
    return pd.DataFrame(rows).groupby("d1").ex_bp.mean().sort_index()


def judge(ev):
    s = {c: date_series(ev, c) for c in ("UP_L", "DN_L", "UP_S", "DN_S")}
    n = {c: len(v) for c, v in s.items()}
    if min(n["UP_L"], n["DN_L"]) < STAGE1:
        print(f"판정 거부 — 성숙 사건일 UP_L {n['UP_L']} · DN_L {n['DN_L']} < {STAGE1}")
        return 1
    final = min(n["UP_L"], n["DN_L"]) >= FINAL
    for c in ("UP_L", "DN_L"):
        m, t = float(s[c].mean()), nw_t(s[c].values, H)
        if final:
            v = "SUPPORTED" if t >= 1.65 and m - COST > 0 else "REJECT"
        else:
            v = "REJECT" if m <= 0 else "SUPPORTED" if t >= 1.65 and m - COST > 0 else "계속(최종은 300)"
        print(f"{c}: 사건일 {n[c]} · 평균 {m:+.1f}bp · NW t {t:.2f} · 순 {m - COST:+.1f}bp → {v}")
    for c in ("UP_S", "DN_S"):
        print(f"{c}(대조): 사건일 {n[c]} · 평균 {float(s[c].mean()) if n[c] else float('nan'):+.1f}bp")
    return 0


def selftest():
    assert cell(1, 0.12) == "UP_L" and cell(1, 0.05) == "UP_S" and cell(-1, 0.103) == "DN_L" and cell(-1, 0.1) == "DN_S"
    t = pd.DataFrame({"ticker": ["A", "A", "B", "B", "C"], "d": pd.to_datetime(["2026-10-20"] * 4 + ["2026-10-10"]),
                      "T": [110.0, 120.0, 90.0, 110.0, 200.0], "P": [100.0, 100.0, 100.0, 100.0, 100.0]})
    g = detect(t)
    assert list(g.ticker) == ["A"] and abs(g.mag.iloc[0] - 0.15) < 1e-9, g   # B 는 방향 섞임, C 는 시작일 전
    print("selftest OK")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--judge", action="store_true")
    ap.add_argument("--selftest", action="store_true")
    a = ap.parse_args()
    if a.selftest:
        return selftest()
    ev = load_events()
    if a.judge:
        return judge(ev)
    import run_us_price_target_reliability as R
    t, W, cal, _ = R.load()
    now = datetime.now(KST).strftime("%Y-%m-%d")
    added = 0
    for r in detect(t).itertuples():
        k = (r.ticker, r.d.strftime("%Y-%m-%d"))
        if k not in ev:
            ev[k] = {"ticker": r.ticker, "d": k[1], "cell": cell(r.dir, r.mag), "mag": round(float(r.mag), 4),
                     "rows": int(r.rows), "firstSeen": now}
            added += 1
    matured = lost = 0
    for k, rec in ev.items():
        if "ex_bp" in rec or rec.get("lost"):
            continue
        o = outcome(W, cal, rec["ticker"], pd.Timestamp(rec["d"]))
        if o == "lost":
            rec["lost"] = True
            lost += 1
        elif o is not None:
            rec["ex_bp"], rec["d1"], rec["exit"] = o
            matured += 1
    save_events(ev)
    cnt = pd.Series([r["cell"] for r in ev.values()]).value_counts().to_dict() if ev else {}
    mat = {c: len(date_series(ev, c)) for c in ("UP_L", "DN_L", "UP_S", "DN_S")}
    print(f"새 사건 {added} · 이번에 성숙 {matured} · 가격 사라짐 {lost} · 누적 사건 {cnt} · 성숙 사건일 {mat} (값은 판정 시점에만)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
