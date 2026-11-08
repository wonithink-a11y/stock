#!/usr/bin/env python3
"""실현변동성 사다리 × 코스피·코스닥 2배 — 사전등록 findings/rv-ladder-kr-2x-preregistration-2026-11.md"""
import json
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
import tech_timing_3x as B  # noqa: E402
import vix_ladder_3x as L  # noqa: E402

FEE = 0.0005


def cycle(lv, rv, s, N, exit_v, start=25.0, step=5.0):
    n = len(lv)
    sell = None
    for i in range(s + 1, min(n, s + 253)):
        if rv[i] <= exit_v:
            sell = i
            break
    if sell is None:
        if s + 252 >= n:
            return None
        sell = s + 252
    filled = []
    for i in range(s, sell + 1):
        for k in range(N):
            if rv[i] >= start + step * k and k not in [f[0] for f in filled]:
                filled.append((k, i))
    worst = 0.0
    for t in range(s, sell + 1):
        qq = sum((1 - FEE) / lv[i] for _, i in filled if i <= t)
        c = sum(1 for _, i in filled if i <= t)
        worst = min(worst, ((qq * lv[t] + (N - c)) / N - 1) * 100)
    q = sum((1 - FEE) / lv[i] for _, i in filled)
    val = q * lv[sell] * (1 - FEE) + (N - len(filled))
    return dict(ret=(val / N - 1) * 100, worst=worst, days=sell - s, n=len(filled))


def main() -> int:
    out = {}
    for tk, nm in (("^KS11", "코스피 2x"), ("^KQ11", "코스닥 2x")):
        df = B.load(tk)
        df = df[df.index <= B.END]
        r = df["Close"].pct_change().fillna(0.0)
        rv = (r.rolling(20).std() * np.sqrt(252) * 100).fillna(0.0).values
        lv = (1 + 2 * r - 0.02 / 252).cumprod().values
        ev, last = [], -999
        for i in range(len(rv)):
            if rv[i] >= 25:
                if i - last > 30:
                    ev.append(i)
                last = i
        out[nm] = {}
        for N, ex in ((4, 18), (8, 18), (12, 18), (8, 22)):
            rows = []
            for s in ev:
                c = cycle(lv, rv, s, N, ex)
                if c:
                    c["date"] = str(df.index[s].date())
                    rows.append(c)
            cell = {}
            for per in ("TRAIN", "VALID", "TEST", "ALL"):
                rr = [x for x in rows if per == "ALL" or L.per(x["date"]) == per]
                if rr:
                    a = np.array([x["ret"] for x in rr])
                    cell[per] = dict(n=len(a), mean=round(float(a.mean()), 1), med=round(float(np.median(a)), 1), win=round(float((a > 0).mean() * 100)), worst=round(float(a.min())), 보유중최악=round(float(min(x["worst"] for x in rr))), 평균일수=round(float(np.mean([x["days"] for x in rr]))))
                    if per == "ALL":
                        cell["손실사건"] = [(x["date"], round(x["ret"])) for x in rr if x["ret"] < 0]
            out[nm][f"N{N} 청산≤{ex}"] = cell
        m = out[nm]["N8 청산≤18"]
        ok = {p: (None if not m.get(p) or m[p]["n"] < 4 else (m[p]["mean"] > 0 and m[p]["win"] >= 75 and m[p]["worst"] >= -45)) for p in ("TRAIN", "VALID", "TEST")}
        out[nm]["충족"] = ok
        print(f"\n== {nm} 사건 {len(ev)}건 | 주 셀 N8 청산 rv≤18 | 현재 rv20 {rv[-1]:.1f}")
        for per in ("TRAIN", "VALID", "TEST", "ALL"):
            print("  ", per, m.get(per))
        print("   충족", ok, "| 손실 사건", m.get("손실사건"))
        for k in ("N4 청산≤18", "N12 청산≤18", "N8 청산≤22"):
            print("  [기록]", k, out[nm][k].get("ALL"))
    verdict = {nm: ("ROBUST" if all(out[nm]["충족"].get(p) for p in ("TRAIN", "VALID", "TEST")) else ("INFORMATION" if out[nm]["충족"].get("VALID") and out[nm]["충족"].get("TEST") else "REJECT")) for nm in out}
    print("\n판정", verdict)
    out["_verdict"] = verdict
    (B.ROOT / "findings" / "rv-ladder-kr-2x-results.json").write_text(json.dumps(out, ensure_ascii=False, indent=1, default=float), encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main())
