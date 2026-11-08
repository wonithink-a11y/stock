#!/usr/bin/env python3
"""VIX 사다리 × SVIX(−1배) 근사 — 사전등록 findings/vix-ladder-svix-preregistration-2026-11.md"""
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
import tech_timing_3x as B  # noqa: E402
import vix_ladder_3x as L  # noqa: E402


def svix_series():
    sx = B.load("SVXY")["Close"]
    sv = B.load("SVIX")["Close"]
    vix = B.load("^VIX")["Close"]
    idx = vix.index[vix.index >= sx.index[0]]
    ret = []
    prev_sx = prev_sv = None
    lvl, out, dates = 100.0, [], []
    for d in idx:
        if d not in sx.index and d not in sv.index:
            continue
        r = 0.0
        if d >= pd.Timestamp("2022-03-30") and d in sv.index:
            if prev_sv is not None:
                r = sv[d] / prev_sv - 1
            prev_sv = sv[d]
            prev_sx = sx[d] if d in sx.index else prev_sx
        elif d in sx.index:
            if prev_sx is not None:
                q = sx[d] / prev_sx - 1
                r = q if d <= pd.Timestamp("2018-02-27") else 2 * q
            prev_sx = sx[d]
        lvl *= 1 + r
        out.append(lvl)
        dates.append(d)
    return pd.Series(out, index=dates)


def main() -> int:
    vix = B.load("^VIX")["Close"]
    s = svix_series()
    s = s[s.index <= B.END]
    v = vix.reindex(s.index).ffill().values
    lv = s.values
    ev, last = [], -999
    for i in range(len(v)):
        if v[i] >= 20:
            if i - last > 30:
                ev.append(i)
            last = i
    out = {}
    for N in (4, 8, 12):
        for ex in (16, 20):
            rows = []
            for i in ev:
                c = L.cycle(lv, v, i, N, ex)
                if c:
                    c["date"] = str(s.index[i].date())
                    rows.append(c)
            cell = {}
            for p in ("TRAIN", "VALID", "TEST", "ALL"):
                rr = [x for x in rows if p == "ALL" or L.per(x["date"]) == p]
                if rr:
                    a = np.array([x["ret"] for x in rr])
                    cell[p] = dict(n=len(a), mean=round(float(a.mean()), 1), med=round(float(np.median(a)), 1), win=round(float((a > 0).mean() * 100)), worst=round(float(a.min())), 보유중최악=round(float(min(x["worst"] for x in rr))), 평균일수=round(float(np.mean([x["days"] for x in rr]))))
                    if p == "ALL":
                        cell["손실사건"] = [(x["date"], round(x["ret"])) for x in rr if x["ret"] < 0]
            out[f"N{N} 청산≤{ex}"] = cell
    m = out["N8 청산≤16"]
    ok = {p: (None if not m.get(p) or m[p]["n"] < 4 else (m[p]["mean"] > 0 and m[p]["win"] >= 75 and m[p]["worst"] >= -45)) for p in ("VALID", "TEST")}
    verdict = "INFORMATION" if ok.get("VALID") and ok.get("TEST") else "REJECT"
    out["_ok"], out["_verdict"] = ok, verdict
    print(f"사건 {len(ev)}건 ({s.index[0].date()}~{s.index[-1].date()})")
    for k, c in out.items():
        if k.startswith("N"):
            print(k, {p: c.get(p) for p in ("VALID", "TEST", "ALL")}, "손실", c.get("손실사건"))
    print("충족", ok, "→", verdict)
    (B.ROOT / "findings" / "vix-ladder-svix-results.json").write_text(json.dumps(out, ensure_ascii=False, indent=1, default=float), encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main())
