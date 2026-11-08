#!/usr/bin/env python3
"""VIX 사다리 민감도 격자 — 사전등록 findings/vix-ladder-sensitivity-preregistration-2026-11.md"""
import json
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
import tech_timing_3x as B  # noqa: E402
import vix_ladder_3x as L  # noqa: E402

FEE = 0.0005


def cycle(lv, v, s, N, s0, d, ex, cap=252):
    n = len(lv)
    sell = None
    for i in range(s + 1, min(n, s + cap + 1)):
        if v[i] <= ex:
            sell = i
            break
    if sell is None:
        if s + cap >= n:
            return None
        sell = s + cap
    filled = []
    for i in range(s, sell + 1):
        for k in range(N):
            if v[i] >= s0 + d * k and k not in [f[0] for f in filled]:
                filled.append((k, i))
    worst = 0.0
    for t in range(s, sell + 1):
        qq = sum((1 - FEE) / lv[i] for _, i in filled if i <= t)
        c = sum(1 for _, i in filled if i <= t)
        worst = min(worst, ((qq * lv[t] + (N - c)) / N - 1) * 100)
    q = sum((1 - FEE) / lv[i] for _, i in filled)
    val = q * lv[sell] * (1 - FEE) + (N - len(filled))
    return dict(ret=(val / N - 1) * 100, worst=worst)


def main() -> int:
    vix = B.load("^VIX")["Close"]
    out = {}
    for tk, nm in (("^NDX", "NDX 3x"), ("^SOX", "SOX 3x"), ("^GSPC", "S&P 3x")):
        df = B.load(tk)
        df = df[df.index <= B.END]
        v = vix.reindex(df.index).ffill().values
        r = df["Close"].pct_change().fillna(0.0)
        lv = (1 + 3 * r - 0.03 / 252).cumprod().values
        cells = {}
        for s0 in (18, 20, 22, 25):
            ev, last = [], -999
            for i in range(len(v)):
                if v[i] >= s0:
                    if i - last > 30:
                        ev.append(i)
                    last = i
            for d in (3, 5, 7):
                for ex in (14, 16, 18):
                    rows = []
                    for s in ev:
                        c = cycle(lv, v, s, 8, s0, d, ex)
                        if c:
                            c["date"] = str(df.index[s].date())
                            rows.append(c)
                    ok, info = True, {}
                    for p in ("TRAIN", "VALID", "TEST"):
                        rr = [x for x in rows if L.per(x["date"]) == p]
                        if len(rr) < 4:
                            ok = False
                            info[p] = "판정불가"
                            continue
                        a = np.array([x["ret"] for x in rr])
                        good = a.mean() > 0 and (a > 0).mean() * 100 >= 75 and a.min() >= -45
                        ok = ok and good
                        info[p] = f"평균{a.mean():.1f} 이익{(a > 0).mean()*100:.0f}% 최악{a.min():.0f}" + ("" if good else " ✘")
                    cells[f"시작{s0} 간격{d} 청산{ex}"] = dict(ok=bool(ok), **info)
        npass = sum(1 for c in cells.values() if c["ok"])
        frac = npass / len(cells)
        label = "둔감" if frac >= 0.70 else ("보통" if frac >= 0.30 else "민감")
        out[nm] = dict(합격=npass, 전체=len(cells), 비율=round(frac, 2), 판정=label, cells=cells)
        print(f"\n== {nm}: 합격 {npass}/{len(cells)} ({frac*100:.0f}%) → {label}")
        by = {}
        for k, c in cells.items():
            by.setdefault(k.split()[0], []).append(c["ok"])
        print("  시작별 합격", {k: f"{sum(x)}/{len(x)}" for k, x in by.items()})
        byd = {}
        for k, c in cells.items():
            byd.setdefault(k.split()[1], []).append(c["ok"])
        print("  간격별 합격", {k: f"{sum(x)}/{len(x)}" for k, x in byd.items()})
        bye = {}
        for k, c in cells.items():
            bye.setdefault(k.split()[2], []).append(c["ok"])
        print("  청산별 합격", {k: f"{sum(x)}/{len(x)}" for k, x in bye.items()})
        fails = [k for k, c in cells.items() if not c["ok"]][:6]
        print("  불합격 예", [(k, {p: cells[k][p] for p in ("TRAIN", "VALID", "TEST")}) for k in fails[:2]])
    (B.ROOT / "findings" / "vix-ladder-sensitivity-results.json").write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main())
