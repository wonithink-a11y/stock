#!/usr/bin/env python3
"""L2c: 판정 규칙 v2 + 군집 부트스트랩. 사전등록 findings/condition-grid-l2c-preregistration-2026-11.md.
    python research/strategy-lab/run_condition_grid_l2c.py
"""
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
import condition_grid as G  # noqa: E402
import tech_timing_3x as B  # noqa: E402

F = Path(__file__).resolve().parent / "findings"
REGION = {"SPY": "미국", "QQQ": "미국", "반도체SOX": "미국", "닛케이": "아시아", "항셍": "아시아", "코스피": "아시아", "코스닥": "아시아", "대만가권": "아시아", "상해종합": "아시아",
          "DAX": "유럽", "FTSE": "유럽", "CAC40": "유럽"}
BOOT, SEED = 2000, 20261108


def collect(cfg):
    G.SPY_RET = G.load_cv("SPY")["Close"].pct_change()
    vix = B.load("^VIX")["Close"]
    macro = {"DXY": G._macro("DX-Y.NYB"), "TNX": G._macro("^TNX")}
    fomc, flow_df = G.load_fomc(), G.load_flows()
    mk = {}
    for m in cfg["markets"]:
        d = G.load_cv(m["ticker"])
        d = d[d.index <= B.END]
        S, p = G.build_series(d, vix, m.get("vix_lag", 0), G.SPY_RET)
        G.add_l2(S, d, m["ticker"], m.get("vix_lag", 0), m.get("flows", False), macro, fomc, flow_df)
        mk[m["name"]] = (S, p, d.index, G.fwd_array(p, cfg.get("primary", 21)))
    out = {}
    for e in cfg["events"]:
        for flt in [None] + cfg["filters"]:
            cell = f"{e['name']} | {flt['name'] if flt else '조건 없음'}"
            for nm, (S, p, idx, a) in mk.items():
                ev = [i for i in G.events_for(e, S, p) if G.passes(S, i, flt)]
                ev = [i for i in ev if not np.isnan(a[i])]
                if len(ev) >= cfg.get("min_events", 20):
                    base = np.nanmean(a)
                    out.setdefault(cell, []).extend((nm, str(idx[i].date()), float(a[i] - base)) for i in ev)
    return out


def clusters(events, days=30):
    ev = sorted(events, key=lambda x: x[1])
    cl, last = [], None
    for e in ev:
        t = pd.Timestamp(e[1])
        if last is None or (t - last).days > days:
            cl.append([])
        cl[-1].append(e[2])
        last = t
    return cl


def boot(events, days=30, rng=None):
    cl = clusters(events, days)
    sums = np.array([sum(c) for c in cl])
    ns = np.array([len(c) for c in cl])
    k = len(cl)
    idx = rng.integers(0, k, size=(BOOT, k))
    stat = sums[idx].sum(axis=1) / ns[idx].sum(axis=1)
    return float(sums.sum() / ns.sum()), [float(x) for x in np.percentile(stat, [2.5, 97.5])], k


def classify(s, ev):
    mk = sorted({e[0] for e in ev})
    regions = sorted({REGION[m] for m in mk})
    rng = np.random.default_rng(SEED)
    mean, ci, k = boot(ev, 30, rng)
    sign = 1 if mean >= 0 else -1
    ci_ok = (ci[0] > 0) if sign > 0 else (ci[1] < 0)
    ci14 = boot(ev, 14, np.random.default_rng(SEED))[1]
    ci60 = boot(ev, 60, np.random.default_rng(SEED))[1]
    reasons = []
    if len(mk) < 4:
        reasons.append("시장 부족")
    if len(regions) < 2:
        reasons.append("지역 부족")
    if not ci_ok:
        reasons.append("구간 0 포함")
    if not s["통과2"]:
        reasons.append("통과2 미충족")
    p3 = not reasons
    anysig = s["BH통과_양"] + s["BH통과_음"] > 0 or s["통과"]
    verdict = "INFORMATION" if p3 else ("INCONCLUSIVE" if anysig else "REJECT")
    return dict(cell=s["cell"], 유효시장=len(mk), 시장=mk, 지역=regions, 사건=len(ev), 군집=k, 평균초과=round(mean, 2), ci95=[round(x, 2) for x in ci],
                ci95_14일=[round(x, 2) for x in ci14], ci95_60일=[round(x, 2) for x in ci60], 통과2=s["통과2"], 통과3=p3, 사유=reasons, 판정=verdict)


def main():
    res = {}
    for nm in ("condition-grid-l2", "condition-grid-l2b"):
        cfg = json.loads((F / f"{nm}-config.json").read_text(encoding="utf-8"))
        v1 = json.loads((F / f"{nm}-results.json").read_text(encoding="utf-8"))
        ev = collect(cfg)
        rows = [classify(s, ev[s["cell"]]) for s in v1["요약"] if s["cell"] in ev]
        res[nm] = rows
        c = pd.Series([r["판정"] for r in rows]).value_counts().to_dict()
        print(nm, len(rows), "칸", c, "통과3:", [r["cell"] for r in rows if r["통과3"]])
    (F / "condition-grid-l2c-results.json").write_text(json.dumps(res, ensure_ascii=False, indent=1), encoding="utf-8")


if __name__ == "__main__":
    main()
