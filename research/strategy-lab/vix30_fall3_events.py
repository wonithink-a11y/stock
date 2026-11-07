#!/usr/bin/env python3
"""VIX≥30 · 3일 연속 하락 사건 연구 — 사전등록 findings/vix30-fall3-events-preregistration-2026-11.md

    python research/strategy-lab/vix30_fall3_events.py
"""
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
import tech_timing_3x as B  # noqa: E402

MARKETS = [("^GSPC", 3, True), ("^NDX", 3, True), ("^SOX", 3, True), ("^RUT", 3, True), ("^N225", 2, False), ("^GDAXI", 2, False), ("^KS11", 2, False), ("^KQ11", 2, False), ("^HSI", 2, False)]
HS = (21, 63, 126, 252)
NPERM = 2000


def series(close: pd.Series, lev: int):
    r = close.pct_change().fillna(0.0)
    lv = (1 + lev * r - lev * 0.01 / 252).cumprod()   # 3배 연 3%, 2배 연 2%
    return close.values, lv.values


def fwd(p, i, h):
    return (p[i + h] / p[i] - 1) * 100 if i + h < len(p) else np.nan


def stats(a):
    a = np.array([x for x in a if not np.isnan(x)])
    if len(a) == 0:
        return None
    return dict(n=len(a), mean=round(float(a.mean()), 1), med=round(float(np.median(a)), 1), win=round(float((a > 0).mean() * 100)), worst=round(float(a.min()), 0))


def main() -> int:
    vix = B.load("^VIX")["Close"]
    rng = np.random.default_rng(B.SEED)
    out, ok_count, weak = {}, 0, 0
    for tk, lev, us in MARKETS:
        df = B.load(tk)
        df = df[df.index <= B.END]
        v = (vix if us else vix.shift(1)).reindex(df.index).ffill().values
        px, lv = series(df["Close"], lev)
        n = len(px)
        ev, last = [], -999
        for i in range(3, n):
            if v[i] >= 30 and v[i] < v[i - 1] < v[i - 2] < v[i - 3] and i - last > 30:
                ev.append(i)
                last = i
        row = dict(events=[str(df.index[i].date()) for i in ev])
        # 1. 사건 수익 + 순열
        good = 0
        for nm, p in (("1배", px), (f"{lev}배", lv)):
            row[nm] = {}
            for h in HS:
                r = [fwd(p, i, h) for i in ev]
                row[nm][f"{h}일"] = stats(r)
            if nm != "1배":
                pass
        okh = 0
        for h in (21, 63):
            p = lv
            allr = np.array([fwd(p, i, h) for i in range(n)])
            valid = np.where(~np.isnan(allr))[0]
            evr = np.array([allr[i] for i in ev if not np.isnan(allr[i])])
            if len(evr) == 0:
                continue
            m_ev, m_all = evr.mean(), allr[valid].mean()
            cnt = 0
            for _ in range(NPERM):
                k = int(rng.integers(252, n - 252))
                s = np.array([allr[(i + k) % n] for i in ev if not np.isnan(allr[i])])
                s = s[~np.isnan(s)]
                if len(s) and s.mean() >= m_ev:
                    cnt += 1
            pval = (1 + cnt) / (1 + NPERM)
            row[f"p{h}"] = round(pval, 4)
            row[f"초과{h}"] = round(float(m_ev - m_all), 1)
            if m_ev > m_all and pval <= 0.01:
                okh += 1
        row["ok"] = okh == 2
        ok_count += int(row["ok"])
        # 2. 규칙 거래
        tr = []
        for i in ev:
            j = next((k for k in range(i + 1, min(n, i + 253)) if v[k] < 20), min(n - 1, i + 252))
            seg = lv[i:j + 1] / lv[i]
            tr.append(((lv[j] / lv[i] - 1) * 100, (seg.min() - 1) * 100, j - i))
        if tr:
            row["거래"] = dict(n=len(tr), win=round(float(np.mean([t[0] > 0 for t in tr]) * 100)), mean=round(float(np.mean([t[0] for t in tr])), 1), worst=round(float(min(t[0] for t in tr))), 최악낙폭=round(float(min(t[1] for t in tr))), 평균일수=round(float(np.mean([t[2] for t in tr]))))
        out[tk] = row
        print(f"{tk:8s} {lev}배 사건 {len(ev):2d}건 | 21일 {row[f'{lev}배'].get('21일')} p{row.get('p21')} 초과{row.get('초과21')} | 63일 {row[f'{lev}배'].get('63일')} p{row.get('p63')} 초과{row.get('초과63')} | 거래 {row.get('거래')} | {'충족' if row['ok'] else ''}")
    verdict = "신호 있음" if ok_count >= 5 else ("약한 신호" if ok_count >= 3 else "신호 없음")
    print("\n충족 시장", ok_count, "/ 9 →", verdict)
    out["_ok"], out["_verdict"] = ok_count, verdict
    (B.ROOT / "findings" / "vix30-fall3-events-results.json").write_text(json.dumps(out, ensure_ascii=False, indent=1, default=float), encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main())
