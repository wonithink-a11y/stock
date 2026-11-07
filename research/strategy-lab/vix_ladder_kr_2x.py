#!/usr/bin/env python3
"""VIX 사다리 × 코스피·코스닥 2배 — 사전등록 findings/vix-ladder-kr-2x-preregistration-2026-11.md"""
import json
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
import tech_timing_3x as B  # noqa: E402
import vix_ladder_3x as L  # noqa: E402


def main() -> int:
    vix = B.load("^VIX")["Close"].shift(1)
    out = {}
    for tk, nm in (("^KS11", "코스피 2x"), ("^KQ11", "코스닥 2x")):
        df = B.load(tk)
        df = df[df.index <= B.END]
        v = vix.reindex(df.index).ffill().values
        r = df["Close"].pct_change().fillna(0.0)
        lv = (1 + 2 * r - 0.02 / 252).cumprod().values
        ev, last = [], -999
        for i in range(len(v)):
            if v[i] >= 20:
                if i - last > 30:
                    ev.append(i)
                last = i
        out[nm] = {}
        for N in (4, 8, 12):
            for ex in (16, 20):
                rows = []
                for s in ev:
                    c = L.cycle(lv, v, s, N, ex)
                    if c:
                        c["date"] = str(df.index[s].date())
                        rows.append(c)
                cell = {}
                for p in ("TRAIN", "VALID", "TEST", "ALL"):
                    rr = [x for x in rows if p == "ALL" or L.per(x["date"]) == p]
                    if rr:
                        a = np.array([x["ret"] for x in rr])
                        cell[p] = dict(n=len(a), mean=round(float(a.mean()), 1), med=round(float(np.median(a)), 1), win=round(float((a > 0).mean() * 100)), worst=round(float(a.min())), 보유중최악=round(float(min(x["worst"] for x in rr))), 평균일수=round(float(np.mean([x["days"] for x in rr]))))
                        if p == "ALL":
                            cell["손실사건"] = [(x["date"], round(x["ret"])) for x in rr if x["ret"] < 0]
                out[nm][f"N{N} 청산≤{ex}"] = cell
        m = out[nm]["N8 청산≤16"]
        ok = {p: (None if not m.get(p) or m[p]["n"] < 4 else (m[p]["mean"] > 0 and m[p]["win"] >= 75 and m[p]["worst"] >= -45)) for p in ("TRAIN", "VALID", "TEST")}
        out[nm]["주셀충족"] = ok
        print(f"\n== {nm} 사건 {len(ev)}건 | 주 셀 N8 청산≤16")
        for p in ("TRAIN", "VALID", "TEST", "ALL"):
            print("  ", p, m.get(p))
        print("   충족", ok, "| 손실 사건", m.get("손실사건"))
        for k in ("N4 청산≤16", "N12 청산≤16", "N8 청산≤20"):
            print("  [기록]", k, out[nm][k].get("ALL"))
        # 현재 진행 사건
        print("   현재 VIX(직전 미국 종가) ", round(float(v[-1]), 1))
    verdict = {nm: ("ROBUST" if all(out[nm]["주셀충족"].get(p) for p in ("TRAIN", "VALID", "TEST")) else ("INFORMATION" if out[nm]["주셀충족"].get("VALID") and out[nm]["주셀충족"].get("TEST") else "REJECT")) for nm in out}
    print("\n판정", verdict)
    out["_verdict"] = verdict
    (B.ROOT / "findings" / "vix-ladder-kr-2x-results.json").write_text(json.dumps(out, ensure_ascii=False, indent=1, default=float), encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main())
