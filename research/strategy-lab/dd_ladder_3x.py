#!/usr/bin/env python3
"""낙폭 사다리 × 합성 3배 — 사전등록 findings/dd-ladder-3x-preregistration-2026-11.md"""
import json
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
import tech_timing_3x as B  # noqa: E402
import vix_ladder_3x as L  # noqa: E402

FEE = 0.0005


def run_cycle(lv, dd, s, N, exit_dd, cap=504):
    n = len(lv)
    sell = None
    for i in range(s + 1, min(n, s + cap + 1)):
        if dd[i] >= exit_dd:
            sell = i
            break
    if sell is None:
        if s + cap >= n:
            return None
        sell = s + cap
    filled = []
    for i in range(s, sell + 1):
        for k in range(N):
            if dd[i] <= -0.10 - 0.05 * k and k not in [f[0] for f in filled]:
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
    for tk, nm in (("^NDX", "NDX 3x"), ("^SOX", "SOX 3x"), ("^GSPC", "S&P 3x")):
        df = B.load(tk)
        df = df[df.index <= B.END]
        p = df["Close"].values
        r = df["Close"].pct_change().fillna(0.0)
        lv = (1 + 3 * r - 0.03 / 252).cumprod().values
        hi = np.array([p[max(0, i - 251):i + 1].max() for i in range(len(p))])
        dd = p / hi - 1
        ev, last_ok = [], -999
        i = 252
        busy_until = -1
        while i < len(p):
            if dd[i] <= -0.10 and i > busy_until and i - last_ok > 0 and (i - 60 < 0 or dd[max(0, i - 60):i].max() >= -0.05):
                c = run_cycle(lv, dd, i, 8, -0.05)
                if c is None:
                    break
                ev.append((i, c))
                busy_until = i + c["days"]
                i = busy_until + 1
                continue
            if dd[i] >= -0.05:
                last_ok = i
            i += 1
        out[nm] = {}
        for N, ex in ((4, -0.05), (8, -0.05), (12, -0.05), (8, -0.10)):
            rows = []
            for s, _ in ev:
                c = run_cycle(lv, dd, s, N, ex)
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
            out[nm][f"N{N} 청산{int(ex*100)}"] = cell
        m = out[nm]["N8 청산-5"]
        ok = {p: (None if not m.get(p) or m[p]["n"] < 4 else (m[p]["mean"] > 0 and m[p]["win"] >= 75 and m[p]["worst"] >= -45)) for p in ("TRAIN", "VALID", "TEST")}
        out[nm]["충족"] = ok
        print(f"\n== {nm} 사건 {len(ev)}건 | 주 셀 N8 청산 −5%")
        for per in ("TRAIN", "VALID", "TEST", "ALL"):
            print("  ", per, m.get(per))
        print("   충족", ok, "| 손실 사건", m.get("손실사건"))
        for k in ("N4 청산-5", "N12 청산-5", "N8 청산-10"):
            print("  [기록]", k, out[nm][k].get("ALL"))
    verdict = {nm: ("ROBUST" if all(out[nm]["충족"].get(p) for p in ("TRAIN", "VALID", "TEST")) else ("INFORMATION" if out[nm]["충족"].get("VALID") and out[nm]["충족"].get("TEST") else "REJECT")) for nm in out}
    print("\n판정", verdict)
    out["_verdict"] = verdict
    (B.ROOT / "findings" / "dd-ladder-3x-results.json").write_text(json.dumps(out, ensure_ascii=False, indent=1, default=float), encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main())
