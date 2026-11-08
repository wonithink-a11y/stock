#!/usr/bin/env python3
"""하루 급락의 원인별 반응 — 사전등록 findings/drop-cause-events-preregistration-2026-11.md"""
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
import tech_timing_3x as B  # noqa: E402
import post_drop_asset_selection as P  # noqa: E402
import one_day_drop_5pct as D  # noqa: E402

LABEL = {
    "2000-01-04": "미상", "2000-04-03": "정책·정치", "2000-04-12": "거시", "2000-04-14": "거시", "2000-07-05": "미상", "2000-07-28": "미상",
    "2000-09-21": "기업·기술", "2000-10-10": "기업·기술", "2000-11-28": "미상", "2001-05-29": "미상", "2001-07-06": "미상", "2001-09-17": "외생",
    "2001-10-17": "미상", "2002-06-19": "미상", "2002-07-25": "금융·신용", "2002-10-16": "미상", "2008-09-17": "금융·신용", "2008-09-29": "정책·정치",
    "2008-10-15": "금융·신용", "2009-01-20": "정책·정치", "2011-08-08": "정책·정치", "2020-02-27": "외생", "2020-03-09": "외생", "2020-06-11": "외생",
    "2020-09-03": "기업·기술", "2022-05-05": "거시", "2022-09-13": "거시", "2025-01-27": "기업·기술", "2025-04-03": "정책·정치", "2025-04-04": "정책·정치",
    "2026-06-05": "거시", "2026-11-05": "정책·정치",
}
NPERM = 5000


def stat(a):
    a = np.array([x for x in a if not np.isnan(x)])
    if len(a) == 0:
        return None
    return dict(n=len(a), 평균=round(float(a.mean()), 2), 중앙=round(float(np.median(a)), 2), 이익=round(float((a > 0).mean() * 100)), 최악=round(float(a.min()), 1))


def main() -> int:
    df = P.closes()
    n = len(df)
    ks = B.load("^KS11")["Close"]
    sox = B.load("^SOX")["Close"].reindex(df.index)
    vix = B.load("^VIX")["Close"].reindex(df.index).ffill().values
    dates = set()
    for px, thr in ((df["QQQ"], -0.05), (df["SPY"], -0.05), (sox, -0.08)):
        for i in D.daily_events(px, thr, 20):
            if df.index[i] >= pd.Timestamp(P.START):
                dates.add(df.index[i])
    dates = sorted(dates)
    clusters = []
    for d in dates:
        if clusters and (d - clusters[-1][0]).days <= 7:
            clusters[-1].append(d)
        else:
            clusters.append([d])
    ev = []
    for c in clusters:
        lab = LABEL.get(str(c[0].date())) or next((LABEL.get(str(x.date())) for x in c if LABEL.get(str(x.date()))), "미상")
        ev.append((df.index.get_loc(c[0]), lab, [str(x.date()) for x in c]))
    q = df["QQQ"].values
    out = {"클러스터": [(df.index[i].strftime("%Y-%m-%d"), lab, ds) for i, lab, ds in ev]}
    cats = sorted({lab for _, lab, _ in ev})
    res = {}
    for cat in cats:
        ids = [i for i, lab, _ in ev if lab == cat]
        row = dict(사건=len(ids), 날짜=[str(df.index[i].date()) for i in ids])
        for h in (1, 5, 21, 63):
            row[f"QQQ{h}일"] = stat([P.fwd(q, i, h) for i in ids])
        dn = rb = tot = 0
        for i in ids:
            if i + 21 < n:
                seg = q[i + 1:i + 22] / q[i] - 1
                tot += 1
                dn += int(seg.min() <= -0.05)
                rb += int(seg.max() >= 0.05)
        row["21일내"] = f"추가하락5% {dn}/{tot} · 반등5% {rb}/{tot}"
        kr = []
        for i in ids:
            pos = ks.index.searchsorted(df.index[i], side="right")
            if 1 <= pos and pos + 21 < len(ks):
                kr.append(((ks.iloc[pos] / ks.iloc[pos - 1] - 1) * 100, (ks.iloc[pos + 20] / ks.iloc[pos - 1] - 1) * 100))
        row["코스피반응일"] = stat([x[0] for x in kr])
        row["코스피21일"] = stat([x[1] for x in kr])
        row["VIX사건일"] = round(float(np.mean([vix[i] for i in ids])), 1)
        res[cat] = row
    out["분류"] = res
    # 정책·정치 vs 나머지(미상 제외) 21일 QQQ
    lab_ids = [(i, lab) for i, lab, _ in ev if lab != "미상" and not np.isnan(P.fwd(q, i, 21))]
    x = np.array([P.fwd(q, i, 21) for i, _ in lab_ids])
    pol = np.array([lab == "정책·정치" for _, lab in lab_ids])
    obs = x[pol].mean() - x[~pol].mean() if pol.sum() and (~pol).sum() else np.nan
    rng = np.random.default_rng(B.SEED)
    cnt = 0
    for _ in range(NPERM):
        sh = rng.permutation(pol)
        if abs(x[sh].mean() - x[~sh].mean()) >= abs(obs):
            cnt += 1
    p = (1 + cnt) / (1 + NPERM)
    out["정책vs나머지21일"] = dict(정책n=int(pol.sum()), 나머지n=int((~pol).sum()), 정책평균=round(float(x[pol].mean()), 2), 나머지평균=round(float(x[~pol].mean()), 2), 차이=round(float(obs), 2), 양측p=round(p, 4))
    verdict = "원인 구분 신호 있음" if p <= 0.01 else ("INCONCLUSIVE" if p <= 0.2 else "신호 없음")
    out["판정"] = verdict
    print("군집", len(ev), "건 | 분류별:")
    for cat, r in res.items():
        print(f"\n[{cat}] 사건 {r['사건']}건 {r['날짜']}")
        for h in (1, 5, 21, 63):
            print(f"   QQQ +{h}일", r[f'QQQ{h}일'])
        print("   ", r["21일내"], "| 코스피 반응일", r["코스피반응일"], "| 코스피 21일", r["코스피21일"], "| VIX", r["VIX사건일"])
    print("\n정책·정치 vs 나머지(미상 제외) QQQ 21일:", out["정책vs나머지21일"], "→", verdict)
    (B.ROOT / "findings" / "drop-cause-events-results.json").write_text(json.dumps(out, ensure_ascii=False, indent=1, default=float), encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main())
