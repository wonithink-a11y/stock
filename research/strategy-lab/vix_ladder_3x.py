#!/usr/bin/env python3
"""VIX 사다리 3배 매수 — 사전등록 findings/vix-ladder-3x-preregistration-2026-11.md"""
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
import tech_timing_3x as B  # noqa: E402

MARKETS = [("^NDX", "NDX 3x"), ("^SOX", "SOX 3x"), ("^GSPC", "S&P 3x")]
FEE = 0.0005


def cycle(lv, v, s, N, exit_v):
    n = len(lv)
    end = min(n - 1, s + 252)
    sell = None
    for i in range(s + 1, end + 1):
        if v[i] <= exit_v:
            sell = i
            break
    if sell is None:
        if s + 252 >= n:
            return None      # 진행 중
        sell = s + 252
    filled = []
    for i in range(s, sell + 1):
        for k in range(N):
            if v[i] >= 20 + 5 * k and k not in [f[0] for f in filled]:
                filled.append((k, i))
    q = sum((1 - FEE) / lv[i] for _, i in filled)
    val = q * lv[sell] * (1 - FEE) + (N - len(filled))
    worst = 0.0
    for t in range(s, sell + 1):
        qq = sum((1 - FEE) / lv[i] for _, i in filled if i <= t)
        c = sum(1 for _, i in filled if i <= t)
        worst = min(worst, ((qq * lv[t] + (N - c)) / N - 1) * 100)
    return dict(ret=(val / N - 1) * 100, worst=worst, days=sell - s, n=len(filled), exit_day=str(sell))


def per(date):
    return "TRAIN" if date <= "2009-12-31" else ("VALID" if date <= "2019-12-31" else "TEST")


def main() -> int:
    vix = B.load("^VIX")["Close"]
    out = {}
    for tk, nm in MARKETS:
        df = B.load(tk)
        df = df[df.index <= B.END]
        v = vix.reindex(df.index).ffill().values
        r = df["Close"].pct_change().fillna(0.0)
        lv = (1 + 3 * r - 0.03 / 252).cumprod().values
        ev, last = [], -999
        for i in range(len(v)):
            if v[i] >= 20:
                if i - last > 30:
                    ev.append(i)
                last = i
        out[nm] = {}
        for N in (4, 8, 12):
            for exit_v in (16, 20):
                rows = []
                for s in ev:
                    c = cycle(lv, v, s, N, exit_v)
                    if c:
                        c["date"] = str(df.index[s].date())
                        rows.append(c)
                cell = {}
                for p in ("TRAIN", "VALID", "TEST", "ALL"):
                    rr = [x for x in rows if p == "ALL" or per(x["date"]) == p]
                    if not rr:
                        continue
                    a = np.array([x["ret"] for x in rr])
                    cell[p] = dict(n=len(a), mean=round(float(a.mean()), 1), med=round(float(np.median(a)), 1), win=round(float((a > 0).mean() * 100)), worst=round(float(a.min()), 0), 보유중최악=round(float(min(x["worst"] for x in rr)), 0), 평균일수=round(float(np.mean([x["days"] for x in rr]))))
                    if p == "ALL":
                        cell["손실사건"] = [(x["date"], round(x["ret"])) for x in rr if x["ret"] < 0]
                out[nm][f"N{N} 청산≤{exit_v}"] = cell
        main_cell = out[nm]["N8 청산≤16"]
        ok = {}
        for p in ("TRAIN", "VALID", "TEST"):
            c = main_cell.get(p)
            ok[p] = None if (not c or c["n"] < 4) else (c["mean"] > 0 and c["win"] >= 75 and c["worst"] >= -45)
        out[nm]["주셀충족"] = ok
        print(f"\n== {nm} 사건 {len(ev)}건 | 주 셀 N8 청산≤16:")
        for p in ("TRAIN", "VALID", "TEST", "ALL"):
            print("  ", p, main_cell.get(p))
        print("   충족", ok, "| 손실 사건", main_cell.get("손실사건"))
        for key in ("N4 청산≤16", "N12 청산≤16", "N8 청산≤20"):
            print("  [기록]", key, {p: out[nm][key].get(p) for p in ("ALL",)})
    verdicts = {}
    for _, nm in MARKETS[:2]:
        ok = out[nm]["주셀충족"]
        if all(ok.get(p) for p in ("TRAIN", "VALID", "TEST")):
            verdicts[nm] = "ROBUST"
        elif ok.get("VALID") and ok.get("TEST"):
            verdicts[nm] = "INFORMATION"
        else:
            verdicts[nm] = "REJECT"
    print("\n판정", verdicts)
    out["_verdicts"] = verdicts
    (B.ROOT / "findings" / "vix-ladder-3x-results.json").write_text(json.dumps(out, ensure_ascii=False, indent=1, default=float), encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main())
