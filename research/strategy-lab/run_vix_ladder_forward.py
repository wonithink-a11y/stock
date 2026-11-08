#!/usr/bin/env python3
"""VIX·실현변동성 사다리 forward 기록 — 사전등록 findings/vix-ladder-forward-preregistration-2026-11.md

    python research/strategy-lab/run_vix_ladder_forward.py          # 기록 1줄 추가(수 초)
    python research/strategy-lab/run_vix_ladder_forward.py --judge   # 판정 시점 전에는 거부(건수만 출력)
"""
import argparse
import json
import sys
from datetime import date
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parent
OUT = ROOT.parents[1] / "reports" / "2026-11-vix-ladder-forward" / "observations.jsonl"
START = "2026-11-02"
FEE = 0.0005
CASES = [  # (이름, 지수, 배수, 연비용, 신호 종류, 시작, 간격, 청산, 상한)
    ("NDX3x VIX사다리", "^NDX", 3, 0.03, "vix", 20, 5, 16, 252),
    ("SOX3x VIX사다리", "^SOX", 3, 0.03, "vix", 20, 5, 16, 252),
    ("코스닥2x 실현변동성 사다리", "^KQ11", 2, 0.02, "rv", 25, 5, 18, 252),
]


def fresh(tk):
    import yfinance as yf
    d = yf.download(tk, period="3y", progress=False, auto_adjust=True)
    d.columns = [c[0] if isinstance(c, tuple) else c for c in d.columns]
    d.index = pd.to_datetime(d.index).tz_localize(None)
    return d["Close"].dropna()


def cycle_state(lv, sig, s, N, start, step, exit_v, cap, dates):
    n = len(lv)
    sell = None
    for i in range(s + 1, min(n, s + cap + 1)):
        if sig[i] <= exit_v:
            sell = i
            break
    closed = sell is not None or s + cap < n
    end = sell if sell is not None else min(n - 1, s + cap)
    filled = []
    for i in range(s, end + 1):
        for k in range(N):
            if sig[i] >= start + step * k and k not in [f[0] for f in filled]:
                filled.append((k, i))
    q = sum((1 - FEE) / lv[i] for _, i in filled)
    val = q * lv[end] * (1 - FEE) + (N - len(filled))
    return dict(start=str(dates[s].date()), 체결=len(filled), 체결일=[str(dates[i].date()) for _, i in filled], 기준일=str(dates[end].date()), closed=bool(closed), ret=round((val / N - 1) * 100, 2), 신호=round(float(sig[end]), 1))


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--judge", action="store_true")
    a = ap.parse_args()
    rows = [json.loads(x) for x in OUT.read_text(encoding="utf-8").splitlines()] if OUT.exists() else []
    if a.judge:
        closed = 0
        if rows:
            closed = sum(1 for c in rows[-1]["cases"].values() for e in c["events"] if e["closed"])
        print(f"닫힌 사건 {closed}건. 판정은 닫힌 사건 ≥ 12 ∧ 2027-11-02 이후에만 가능 — 거부.")
        return 2
    vix = fresh("^VIX")
    cases = {}
    for name, tk, lev, drag, kind, start, step, ex, cap in CASES:
        c = fresh(tk)
        idx = c.index
        r = c.pct_change().fillna(0.0)
        lv = (1 + lev * r - drag / 252 * 1.0).cumprod().values
        sig = (vix.reindex(idx).ffill().values if kind == "vix" else (r.rolling(20).std() * np.sqrt(252) * 100).fillna(0.0).values)
        ev, last = [], -999
        for i in range(len(sig)):
            if sig[i] >= start:
                if i - last > 30:
                    ev.append(i)
                last = i
        evs = [cycle_state(lv, sig, s, 8, start, step, ex, cap, idx) for s in ev if str(idx[s].date()) >= START]
        cases[name] = dict(기준일=str(idx[-1].date()), 현재신호=round(float(sig[-1]), 1), events=evs)
    asof = max(v["기준일"] for v in cases.values())
    rec = dict(asof=asof, ran=str(date.today()), cases=cases)
    rows = [x for x in rows if x["asof"] != asof] + [rec]
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text("\n".join(json.dumps(x, ensure_ascii=False) for x in rows) + "\n", encoding="utf-8")
    for n, v in cases.items():
        print(n, "현재신호", v["현재신호"], v["events"])
    return 0


if __name__ == "__main__":
    sys.exit(main())
