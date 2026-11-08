#!/usr/bin/env python3
"""한국 대형주 급락 사건 연구 — 사전등록 findings/kr-largecap-crash-events-preregistration-2026-11.md"""
import json
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
import tech_timing_3x as B  # noqa: E402

STOCKS = {"삼성전자": "005930.KS", "현대차": "005380.KS", "NAVER": "035420.KS", "LG화학": "051910.KS", "삼성SDI": "006400.KS", "POSCO홀딩스": "005490.KS", "카카오": "035720.KS", "기아": "000270.KS", "KB금융": "105560.KS"}
HS = (21, 63, 126)
NPERM = 2000


def fw(p, i, h):
    return (p[i + h] / p[i] - 1) * 100 if i + h < len(p) else np.nan


def st(a):
    a = np.array([x for x in a if not np.isnan(x)])
    return None if len(a) == 0 else dict(n=len(a), mean=round(float(a.mean()), 1), med=round(float(np.median(a)), 1), win=round(float((a > 0).mean() * 100)), worst=round(float(a.min())))


def main() -> int:
    rng = np.random.default_rng(B.SEED)
    out, ok = {}, 0
    for nm, tk in STOCKS.items():
        df = B.load(tk)
        df = df[df.index <= B.END]
        p = df["Close"].values
        n = len(p)
        r20 = np.full(n, np.nan)
        r20[20:] = p[20:] / p[:-20] - 1
        hi = np.array([p[max(0, i - 251):i + 1].max() for i in range(n)])
        dd = p / hi - 1
        cond = (r20 <= -0.25) & (dd <= -0.40)
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
                m = p[i + 1:i + 64].min() / p[i] - 1
                add.append(m * 100)
                re += int(m <= -0.10)
        if add:
            a = np.sort(add)
            row["추가낙폭63"] = dict(n=len(a), 중앙=round(float(np.median(a))), 최악=round(float(a[0])), 재하락10pct=f"{re}/{len(a)}")
        okh = False
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
            if h == 63 and m_ev > m_all and pv <= 0.01:
                okh = True
        row["ok"] = okh
        ok += int(okh)
        out[nm] = row
        print(f"{nm:8s} 사건{len(ev):2d} | 21일 {row['21일']} | 63일 {row['63일']} p{row.get('p63')} 초과{row.get('초과63')} | 추가낙폭63 {row.get('추가낙폭63')} | 현재 {row['현재']} {'★현재조건' if row['현재조건'] else ''}")
    v = "약한 신호 후보(상한)" if ok >= 5 else ("약함" if ok >= 2 else "신호 없음")
    print("\n충족", ok, "/ 9 →", v)
    out["_ok"], out["_verdict"] = ok, v
    (B.ROOT / "findings" / "kr-largecap-crash-events-results.json").write_text(json.dumps(out, ensure_ascii=False, indent=1, default=float), encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main())
