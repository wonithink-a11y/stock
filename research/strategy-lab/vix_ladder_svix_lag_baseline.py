#!/usr/bin/env python3
"""VIX 사다리 SVIX — 집행 지연 · 기준선 · 시기. 사전등록 findings/vix-ladder-svix-lag-baseline-preregistration-2026-11.md
3x 점검(vix_ladder_3x_lag_baseline)의 cycle·stat·era 를 그대로 쓰고, 기준선 제외 폭만 ±63거래일."""
import json
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
import tech_timing_3x as B  # noqa: E402
import vix_ladder_3x_lag_baseline as LB  # noqa: E402
import vix_ladder_svix as SV  # noqa: E402

BAN = 63
SEED = 20261117
FIND = B.ROOT / "findings"


def baseline(lv, ev_idx, rows):
    n = len(lv)
    banned = np.zeros(n, dtype=bool)
    for s in ev_idx:
        banned[max(0, s - BAN):min(n, s + BAN + 1)] = True
    rng = np.random.default_rng(SEED)
    out, ncand = [], []
    for r in rows:
        h = r["days"]
        cand = np.array([j for j in range(0, n - h) if not banned[j]])
        ncand.append(len(cand))
        if len(cand) < 500:
            out.append(np.nan)
            continue
        js = rng.choice(cand, size=2000, replace=True)
        wr = lv[js + h] / lv[js] - 1
        out.append(float((((1 + wr) * (1 - LB.FEE) ** 2 - 1) * 100 * (r["nf"] / LB.N)).mean()))
    return np.array(out), ncand


def main() -> int:
    vix = B.load("^VIX")["Close"]
    s = SV.svix_series()
    s = s[s.index <= B.END]
    v = vix.reindex(s.index).ffill().values
    lv = s.values
    ev, last = [], -999
    for i in range(len(v)):
        if v[i] >= 20:
            if i - last > 30:
                ev.append(i)
            last = i
    orig = json.loads((FIND / "vix-ladder-svix-results.json").read_text(encoding="utf-8"))["N8 청산≤16"]
    res = {"_meta": {"events": len(ev), "ban": BAN, "seed": SEED}}
    for lag in (0, 1):
        rows = []
        for i in ev:
            c = LB.cycle(lv, v, i, lag)
            if c:
                c["date"] = str(s.index[i].date())
                rows.append(c)
        cells = {p: LB.stat([x for x in rows if p == "ALL" or LB.per(x["date"]) == p]) for p in ("VALID", "TEST", "ALL")}
        lab = "지연 견딤" if LB.meets(cells.get("VALID")) and LB.meets(cells.get("TEST")) else "소멸"
        res[f"L{lag}"] = {"cells": cells, "label": lab,
                          "eras": {e: LB.stat([x for x in rows if LB.era(x["date"]) == e]) for e in ("~2015", "2016~23", "2024", "2025~")},
                          "worst_events": sorted([(x["date"], round(x["ret"]), round(x["worst"])) for x in rows], key=lambda z: z[1])[:5]}
        if lag == 0:
            diff = {}
            for p in ("VALID", "TEST", "ALL"):
                a, b = cells.get(p), orig.get(p)
                if a and b:
                    diff[p] = {k: (a[k], b[k]) for k in ("n", "mean", "win", "worst") if a[k] != b[k]}
            res["L0_vs_original_diff"] = diff
        else:
            base, ncand = baseline(lv, ev, rows)
            ret = np.array([x["ret"] for x in rows])
            ok = ~np.isnan(base)
            if ok.sum() >= 4:
                d = ret[ok] - base[ok]
                rng = np.random.default_rng(SEED + 1)
                bs = np.array([rng.choice(d, size=len(d), replace=True).mean() for _ in range(5000)])
                res["baseline"] = {"n": int(ok.sum()), "event_mean": round(float(ret[ok].mean()), 2), "baseline_mean": round(float(base[ok].mean()), 2),
                                   "diff_mean": round(float(d.mean()), 2), "ci95": [round(float(np.percentile(bs, 2.5)), 2), round(float(np.percentile(bs, 97.5)), 2)],
                                   "min_candidates": int(min(ncand)),
                                   "by_era": {e: {"n": int(sum(1 for x, o in zip(rows, ok) if o and LB.era(x["date"]) == e)),
                                                  "diff": (round(float(np.mean([dd for dd, x in zip(d, [r for r, o in zip(rows, ok) if o]) if LB.era(x["date"]) == e])), 2)
                                                           if any(LB.era(x["date"]) == e for x, o in zip(rows, ok) if o) else None)}
                                              for e in ("~2015", "2016~23", "2024", "2025~")}}
            else:
                res["baseline"] = {"산출불가": True, "min_candidates": int(min(ncand)) if ncand else 0}
    print("사건", len(ev), "| L0 vs 원본 차이", res["L0_vs_original_diff"], "| L1 라벨", res["L1"]["label"], "| 기준선", res["baseline"])
    (FIND / "vix-ladder-svix-lag-baseline-results.json").write_text(json.dumps(res, ensure_ascii=False, indent=1, default=float), encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main())
