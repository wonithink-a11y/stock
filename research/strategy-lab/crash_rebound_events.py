#!/usr/bin/env python3
"""급락 후 반등·데드캣 사건 연구 — 사전등록 findings/crash-rebound-events-preregistration-2026-11.md"""
import json
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
import tech_timing_3x as B  # noqa: E402

MARKETS = ["^KS11", "^KQ11", "^SOX", "^NDX", "^N225", "^HSI", "^GDAXI", "^GSPC"]
HS = (21, 63, 126, 252)
NPERM = 2000


def fw(p, i, h):
    return (p[i + h] / p[i] - 1) * 100 if i + h < len(p) else np.nan


def st(a):
    a = np.array([x for x in a if not np.isnan(x)])
    return None if len(a) == 0 else dict(n=len(a), mean=round(float(a.mean()), 1), med=round(float(np.median(a)), 1), win=round(float((a > 0).mean() * 100)), worst=round(float(a.min())))


def main() -> int:
    rng = np.random.default_rng(B.SEED)
    out, ok = {}, 0
    for tk in MARKETS:
        df = B.load(tk)
        df = df[df.index <= B.END]
        p = df["Close"].values
        n = len(p)
        r20 = np.full(n, np.nan)
        r20[20:] = p[20:] / p[:-20] - 1
        dd = p / np.maximum.accumulate(np.array([p[max(0, i - 251):i + 1].max() for i in range(n)])) - 1
        cond = (r20 <= -0.20) & (dd <= -0.30)
        ev, last = [], -999
        for i in range(n):
            if cond[i] and i - last > 40:
                ev.append(i)
            if cond[i]:
                last = i
        row = dict(events=[str(df.index[i].date()) for i in ev], 현재조건=bool(cond[-1]), 현재=f"20일 {r20[-1]*100:.1f}% 낙폭 {dd[-1]*100:.1f}%")
        for h in HS:
            row[f"{h}일"] = st([fw(p, i, h) for i in ev])
        add, re = [], 0
        for i in ev:
            if i + 63 < n:
                add.append((p[i + 1:i + 64].min() / p[i] - 1) * 100)
                re += int(p[i + 1:i + 64].min() / p[i] - 1 <= -0.10)
        if add:
            a = np.sort(add)
            row["추가낙폭63"] = dict(n=len(a), 중앙=round(float(np.median(a))), 하위10=round(float(a[int(len(a) * .1)])), 최악=round(float(a[0])), 재하락10pct=f"{re}/{len(a)}")
        okh = []
        for h in (21, 63):
            allr = np.array([fw(p, i, h) for i in range(n)])
            evr = np.array([allr[i] for i in ev if not np.isnan(allr[i])])
            if len(evr) == 0:
                continue
            m_ev, m_all = evr.mean(), np.nanmean(allr)
            cnt = 0
            for _ in range(NPERM):
                k = int(rng.integers(252, n - 252))
                s = np.array([allr[(i + k) % n] for i in ev if not np.isnan(allr[i])])
                s = s[~np.isnan(s)]
                if len(s) and s.mean() >= m_ev:
                    cnt += 1
            pv = (1 + cnt) / (1 + NPERM)
            row[f"p{h}"], row[f"초과{h}"] = round(pv, 4), round(float(m_ev - m_all), 1)
            okh.append(h == 63 and m_ev > m_all and pv <= 0.01)
        row["ok"] = any(okh)
        ok += int(row["ok"])
        out[tk] = row
        print(f"{tk:8s} 사건{len(ev):2d} | 21일 {row['21일']} p{row.get('p21')} | 63일 {row['63일']} p{row.get('p63')} 초과{row.get('초과63')} | 추가낙폭63 {row.get('추가낙폭63')} | 현재 {row['현재']} {'★현재조건' if row['현재조건'] else ''}")
    v = "신호 있음" if ok >= 4 else ("약한 신호" if ok >= 2 else "신호 없음")
    print("\n충족", ok, "/ 8 →", v)
    out["_ok"], out["_verdict"] = ok, v
    (B.ROOT / "findings" / "crash-rebound-events-results.json").write_text(json.dumps(out, ensure_ascii=False, indent=1, default=float), encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main())
