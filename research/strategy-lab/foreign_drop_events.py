#!/usr/bin/env python3
"""해외 지수 하루 급락 사건 — 사전등록 findings/foreign-drop-events-preregistration-2026-11.md"""
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
import tech_timing_3x as B  # noqa: E402

MARKETS = {"닛케이": "^N225", "DAX": "^GDAXI", "항셍": "^HSI", "코스피": "^KS11", "코스닥": "^KQ11", "대만가권": "^TWII", "상해종합": "000001.SS", "FTSE": "^FTSE", "CAC40": "^FCHI"}
HS = (1, 5, 21, 63)
NPERM = 2000


def fwd(a, i, h):
    return (a[i + h] / a[i] - 1) * 100 if i + h < len(a) else np.nan


def stat(a):
    a = np.array([x for x in a if not np.isnan(x)])
    if len(a) == 0:
        return None
    return dict(n=len(a), 평균=round(float(a.mean()), 2), 중앙=round(float(np.median(a)), 2), 이익=round(float((a > 0).mean() * 100)), 최악=round(float(a.min()), 1))


def main() -> int:
    spy = B.load("SPY")["Close"]
    sret = spy.pct_change()
    rng = np.random.default_rng(B.SEED)
    out, pooled = {}, []
    ok_neg = ok_pos = 0
    for nm, tk in MARKETS.items():
        s = B.load(tk)["Close"]
        s = s[s.index <= B.END]
        p = s.values
        n = len(p)
        r = s.pct_change().values
        ev, last = [], -999
        for i in range(1, n):
            if r[i] <= -0.05:
                if i - last > 20:
                    ev.append(i)
                last = i
        glob = []
        for i in ev:
            d = s.index[i]
            prev = sret[sret.index < d].dropna()
            same = sret[sret.index == d].dropna()
            vals = []
            if len(prev):
                vals.append(prev.iloc[-1])
            if len(same):
                vals.append(same.iloc[0])
            glob.append(bool(vals) and min(vals) <= -0.03)
        row = dict(사건=len(ev), 글로벌=int(sum(glob)), 자국고유=len(ev) - int(sum(glob)), events=[(str(s.index[i].date()), "글로벌" if g else "자국") for i, g in zip(ev, glob)])
        sig = []
        for h in HS:
            allr = np.array([fwd(p, i, h) for i in range(n)])
            evr = np.array([allr[i] for i in ev if not np.isnan(allr[i])])
            if len(evr) == 0:
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
                sig.append((pv, diff))
        if sig and sig[0][0] <= 0.01:
            if sig[0][1] > 0:
                ok_pos += 1
            else:
                ok_neg += 1
        # 정규화 21일 수집(원인 구분)
        allr21 = np.array([fwd(p, i, 21) for i in range(n)])
        m21 = np.nanmean(allr21)
        for i, g in zip(ev, glob):
            if not np.isnan(allr21[i]):
                pooled.append((nm, g, allr21[i] - m21, allr21[i]))
        out[nm] = row
        print(f"\n[{nm}] 사건 {len(ev)}건 (글로벌 {row['글로벌']}·자국고유 {row['자국고유']})")
        for h in HS:
            x = row[f"{h}일"]
            if x:
                print(f"   +{h:2d}일 평균{x['평균']:+6.2f}(무조건{x['무조건']:+.2f}) 중앙{x['중앙']:+.2f} 이익{x['이익']}% 최악{x['최악']} 차이{x['차이']:+.2f} 양측p{x['양측p']:.4f}")
    g = np.array([x[2] for x in pooled if x[1]])
    l = np.array([x[2] for x in pooled if not x[1]])
    lab = np.array([x[1] for x in pooled])
    val = np.array([x[2] for x in pooled])
    obs = g.mean() - l.mean()
    cnt = 0
    for _ in range(5000):
        sh = rng.permutation(lab)
        if abs(val[sh].mean() - val[~sh].mean()) >= abs(obs):
            cnt += 1
    pg = (1 + cnt) / 5001
    raw_g = np.array([x[3] for x in pooled if x[1]])
    raw_l = np.array([x[3] for x in pooled if not x[1]])
    out["원인구분"] = dict(글로벌n=len(g), 자국고유n=len(l), 정규화평균_글로벌=round(float(g.mean()), 2), 정규화평균_자국=round(float(l.mean()), 2), 차이=round(float(obs), 2), 양측p=round(pg, 4),
                       원수익_글로벌=stat(raw_g), 원수익_자국=stat(raw_l))
    out["방향신호"] = dict(양_시장수=ok_pos, 음_시장수=ok_neg)
    v1 = "방향 신호 있음" if max(ok_pos, ok_neg) >= 5 else ("INCONCLUSIVE" if max(ok_pos, ok_neg) >= 2 else "신호 없음")
    v2 = "원인 구분 신호 있음" if pg <= 0.01 else ("INCONCLUSIVE" if pg <= 0.2 else "신호 없음")
    out["판정"] = dict(방향=v1, 원인구분=v2)
    print("\n원인 구분(글로벌 vs 자국 고유, 21일 정규화):", out["원인구분"], "→", v2)
    print("방향(21일 p ≤ 0.01):", out["방향신호"], "→", v1)
    ks = out["코스피"]["events"][-12:]
    kq = out["코스닥"]["events"][-12:]
    print("코스피 최근 사건:", ks)
    print("코스닥 최근 사건:", kq)
    (B.ROOT / "findings" / "foreign-drop-events-results.json").write_text(json.dumps(out, ensure_ascii=False, indent=1, default=float), encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main())
