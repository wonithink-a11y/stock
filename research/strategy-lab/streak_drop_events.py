#!/usr/bin/env python3
"""연속 하락 사건 — 사전등록 findings/streak-drop-events-preregistration-2026-11.md"""
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
import tech_timing_3x as B  # noqa: E402

MARKETS = {"SPY": "SPY", "QQQ": "QQQ", "반도체SOX": "^SOX", "닛케이": "^N225", "DAX": "^GDAXI", "항셍": "^HSI", "코스피": "^KS11", "코스닥": "^KQ11", "대만가권": "^TWII", "상해종합": "000001.SS", "FTSE": "^FTSE", "CAC40": "^FCHI"}
CELLS = {"A (≥3일·−5%)": (3, 0.05), "B (≥4일·−7%)": (4, 0.07), "C (≥5일·−10%)": (5, 0.10)}
HS = (1, 5, 21, 63)
NPERM = 2000


def fwd(a, i, h):
    return (a[i + h] / a[i] - 1) * 100 if i + h < len(a) else np.nan


def stat(a):
    a = np.array([x for x in a if not np.isnan(x)])
    if len(a) == 0:
        return None
    return dict(n=len(a), 평균=round(float(a.mean()), 2), 중앙=round(float(np.median(a)), 2), 이익=round(float((a > 0).mean() * 100)), 최악=round(float(a.min()), 1))


def streaks(p):
    n = len(p)
    L = np.zeros(n, dtype=int)
    for i in range(1, n):
        L[i] = L[i - 1] + 1 if p[i] < p[i - 1] else 0
    return L


def main() -> int:
    rng = np.random.default_rng(B.SEED)
    out = {}
    tally = {c: {"양": 0, "음": 0} for c in CELLS}
    current = {}
    for mk, tk in MARKETS.items():
        s = B.load(tk)["Close"]
        s = s[s.index <= B.END]
        p = s.values
        n = len(p)
        L = streaks(p)
        down = np.array([False] + [p[i] < p[i - 1] for i in range(1, n)])
        base_down = float(down[1:].mean())
        cur_L = int(L[-1])
        cur_D = (p[-1] / p[-1 - cur_L] - 1) * 100 if cur_L > 0 else 0.0
        current[mk] = dict(연속하락일=cur_L, 누적=round(float(cur_D), 1), 기준일=str(s.index[-1].date()))
        out[mk] = {}
        for cname, (lmin, dmin) in CELLS.items():
            ev, last, in_streak_hit = [], -999, False
            for i in range(1, n):
                if L[i] == 0:
                    in_streak_hit = False
                if L[i] >= lmin and not in_streak_hit:
                    D = p[i] / p[i - L[i]] - 1
                    if D <= -dmin and i - last > 10:
                        ev.append(i)
                        last = i
                        in_streak_hit = True
            row = dict(사건=len(ev), 날짜=[str(s.index[i].date()) for i in ev][-8:])
            sig21 = None
            for h in HS:
                allr = np.array([fwd(p, i, h) for i in range(n)])
                evr = np.array([allr[i] for i in ev if not np.isnan(allr[i])])
                if len(evr) < 4:
                    row[f"{h}일"] = None
                    continue
                m_all = np.nanmean(allr)
                diff = evr.mean() - m_all
                cnt = 0
                for _ in range(NPERM):
                    k = int(rng.integers(252, n - 252))
                    sh = np.array([allr[(i + k) % n] for i in ev if not np.isnan(allr[i])])
                    sh = sh[~np.isnan(sh)]
                    if len(sh) and abs(sh.mean() - m_all) >= abs(diff):
                        cnt += 1
                pv = (1 + cnt) / (1 + NPERM)
                st = stat(evr)
                st.update(무조건=round(float(m_all), 2), 차이=round(float(diff), 2), 양측p=round(pv, 4))
                row[f"{h}일"] = st
                if h == 21:
                    sig21 = (pv, diff)
            if sig21 and sig21[0] <= 0.01:
                tally[cname]["양" if sig21[1] > 0 else "음"] += 1
            # hazard: 사건 다음 날 또 하락 비율, 이어진 추가 연속
            nd = [int(down[i + 1]) for i in ev if i + 1 < n]
            extra = []
            for i in ev:
                j = i + 1
                while j < n and down[j]:
                    j += 1
                if j < n:
                    extra.append((p[j - 1] / p[i] - 1) * 100 if j - 1 > i else 0.0)
            row["hazard"] = dict(다음날하락=f"{sum(nd)}/{len(nd)}", 비율=round(sum(nd) / len(nd) * 100) if nd else None, 평소하락일비율=round(base_down * 100), 이어진추가하락평균=round(float(np.mean(extra)), 2) if extra else None)
            per = {}
            for pn, (a, b) in {"~2009": ("1900", "2009-12-31"), "2010~19": ("2010-01-01", "2019-12-31"), "2020~": ("2020-01-01", "2026-12-31")}.items():
                v = [fwd(p, i, 21) for i in ev if a <= str(s.index[i].date()) <= b]
                v = [x for x in v if not np.isnan(x)]
                per[pn] = None if len(v) < 3 else dict(n=len(v), 평균=round(float(np.mean(v)), 2))
            row["구간21일"] = per
            out[mk][cname] = row
    for cname in CELLS:
        t = tally[cname]
        print(f"\n===== 셀 {cname}: 21일 p≤0.01 지수 양 {t['양']} · 음 {t['음']} (총 12)")
        for mk in MARKETS:
            r = out[mk][cname]
            parts = []
            for h in HS:
                x = r.get(f"{h}일")
                parts.append(f"+{h}d {x['평균']:+.2f}({x['무조건']:+.2f}) p{x['양측p']:.3f}" if x else f"+{h}d -")
            hz = r["hazard"]
            print(f"  {mk:8s} 사건{r['사건']:3d} | " + " | ".join(parts) + f" | 다음날 또 하락 {hz['비율']}%(평소 {hz['평소하락일비율']}%) 추가하락 {hz['이어진추가하락평균']}")
    print("\n현재(2026-11-06) 연속 하락 상태:", current)
    verdict = {}
    for cname in CELLS:
        m = max(tally[cname]["양"], tally[cname]["음"])
        verdict[cname] = "방향 신호 있음" if m >= 6 else ("INCONCLUSIVE" if m >= 2 else "신호 없음")
    print("판정:", verdict)
    out["_tally"], out["_verdict"], out["_current"] = tally, verdict, current
    (B.ROOT / "findings" / "streak-drop-events-results.json").write_text(json.dumps(out, ensure_ascii=False, indent=1, default=float), encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main())
