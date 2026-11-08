#!/usr/bin/env python3
"""지수 사건 연구 4건(vix30-fall3·streak-drop·foreign-drop·crash-rebound)의 군집 인지 재분류. 사전등록 findings/drop-events-v2-preregistration-2026-11.md.
사건 정의·시장·지평은 원 스크립트 그대로 재현한다(새 가설 없음).   python research/strategy-lab/run_dropevents_v2.py"""
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
import tech_timing_3x as B  # noqa: E402

F = Path(__file__).resolve().parent / "findings"
BOOT, SEED, MIN_MKT_EV = 2000, 20261108, 5
REGION = {"SPY": "미국", "QQQ": "미국", "반도체SOX": "미국", "^GSPC": "미국", "^NDX": "미국", "^SOX": "미국", "^RUT": "미국", "닛케이": "아시아", "^N225": "아시아", "항셍": "아시아", "^HSI": "아시아",
          "코스피": "아시아", "^KS11": "아시아", "코스닥": "아시아", "^KQ11": "아시아", "대만가권": "아시아", "상해종합": "아시아", "DAX": "유럽", "^GDAXI": "유럽", "FTSE": "유럽", "CAC40": "유럽"}


def fw(p, h):
    a = np.full(len(p), np.nan)
    a[:-h] = (p[h:] / p[:-h] - 1) * 100
    return a


def load(tk):
    s = B.load(tk)["Close"]
    return s[s.index <= B.END]


def ev_vix30(s, vix, us):
    p = s.values
    v = (vix if us else vix.shift(1)).reindex(s.index).ffill().values
    ev, last = [], -999
    for i in range(3, len(p)):
        if v[i] >= 30 and v[i] < v[i - 1] < v[i - 2] < v[i - 3] and i - last > 30:
            ev.append(i)
            last = i
    return ev


def streak_len(p):
    L = np.zeros(len(p), dtype=int)
    for i in range(1, len(p)):
        L[i] = L[i - 1] + 1 if p[i] < p[i - 1] else 0
    return L


def ev_streak(p, lmin, dmin):
    L = streak_len(p)
    ev, last, hit = [], -999, False
    for i in range(1, len(p)):
        if L[i] == 0:
            hit = False
        if L[i] >= lmin and not hit:
            if p[i] / p[i - L[i]] - 1 <= -dmin and i - last > 10:
                ev.append(i)
                last = i
                hit = True
    return ev


def ev_foreign(s):
    r = s.pct_change().values
    ev, last = [], -999
    for i in range(1, len(r)):
        if r[i] <= -0.05:
            if i - last > 20:
                ev.append(i)
            last = i
    return ev


def ev_crash(p):
    n = len(p)
    r20 = np.full(n, np.nan)
    r20[20:] = p[20:] / p[:-20] - 1
    dd = np.array([p[i] / p[max(0, i - 251):i + 1].max() - 1 for i in range(n)])
    cond = (r20 <= -0.20) & (dd <= -0.30)
    ev, last = [], -999
    for i in range(n):
        if cond[i] and i - last > 40:
            ev.append(i)
        if cond[i]:
            last = i
    return ev


def boot(events, days, rng):
    ev = sorted(events, key=lambda x: x[1])
    cl, last = [], None
    for _, d, x in ev:
        t = pd.Timestamp(d)
        if last is None or (t - last).days > days:
            cl.append([])
        cl[-1].append(x)
        last = t
    sums = np.array([sum(c) for c in cl])
    ns = np.array([len(c) for c in cl])
    idx = rng.integers(0, len(cl), size=(BOOT, len(cl)))
    stat = sums[idx].sum(axis=1) / ns[idx].sum(axis=1)
    return float(sums.sum() / ns.sum()), [round(float(x), 2) for x in np.percentile(stat, [2.5, 97.5])], len(cl)


def study(name, h, cells, orig):
    """cells: {셀 이름: {시장: [(날짜, 초과)]}}"""
    rows = []
    for cell, per in cells.items():
        valid = {m: e for m, e in per.items() if len(e) >= MIN_MKT_EV}
        allev = [(m, d, x) for m, e in valid.items() for d, x in e]
        if not allev:
            rows.append(dict(연구=name, 셀=cell, 유효시장=0, 판정="판정 불가"))
            continue
        mean, ci, k = boot(allev, 30, np.random.default_rng(SEED))
        ci14 = boot(allev, 14, np.random.default_rng(SEED))[1]
        ci60 = boot(allev, 60, np.random.default_rng(SEED))[1]
        regs = {}
        for m, e in valid.items():
            regs.setdefault(REGION[m], []).extend(x for _, x in e)
        sign = 1 if mean >= 0 else -1
        ci_ok = ci[0] > 0 if sign > 0 else ci[1] < 0
        pos = sum(1 for e in valid.values() if np.mean([x for _, x in e]) * sign > 0)
        rows.append(dict(연구=name, 셀=cell, 지평=h, 유효시장=len(valid), 시장당부호일치=f"{pos}/{len(valid)}", 지역=sorted(regs), 지역평균={r: round(float(np.mean(v)), 2) for r, v in regs.items()},
                         사건=len(allev), 군집=k, 평균초과=round(mean, 2), ci95=ci, ci95_14일=ci14, ci95_60일=ci60, 구간0제외=bool(ci_ok), 원판정=orig))
    return rows


def main():
    vix = B.load("^VIX")["Close"]
    out = []
    # 1) vix30-fall3: 63일
    c = {"VIX≥30·3일 연속 하락": {}}
    for tk, us in [("^GSPC", True), ("^NDX", True), ("^SOX", True), ("^RUT", True), ("^N225", False), ("^GDAXI", False), ("^KS11", False), ("^KQ11", False), ("^HSI", False)]:
        s = load(tk)
        a = fw(s.values, 63)
        base = np.nanmean(a)
        c["VIX≥30·3일 연속 하락"][tk] = [(str(s.index[i].date()), float(a[i] - base)) for i in ev_vix30(s, vix, us) if not np.isnan(a[i])]
    out += study("vix30-fall3-events", 63, c, "INCONCLUSIVE(2/9)")
    # 2) streak-drop: 21일
    MK = {"SPY": "SPY", "QQQ": "QQQ", "반도체SOX": "^SOX", "닛케이": "^N225", "DAX": "^GDAXI", "항셍": "^HSI", "코스피": "^KS11", "코스닥": "^KQ11", "대만가권": "^TWII", "상해종합": "000001.SS", "FTSE": "^FTSE", "CAC40": "^FCHI"}
    REGION["대만가권"] = REGION["상해종합"] = "아시아"
    c = {"A(≥3일·−5%)": {}, "B(≥4일·−7%)": {}, "C(≥5일·−10%)": {}}
    for nm, tk in MK.items():
        s = load(tk)
        a = fw(s.values, 21)
        base = np.nanmean(a)
        for cn, (lm, dm) in zip(c, [(3, 0.05), (4, 0.07), (5, 0.10)]):
            c[cn][nm] = [(str(s.index[i].date()), float(a[i] - base)) for i in ev_streak(s.values, lm, dm) if not np.isnan(a[i])]
    out += study("streak-drop-events", 21, c, "INCONCLUSIVE(A2·B2·C3 <6)")
    # 3) foreign-drop: 21일
    c = {"하루 −5%(전체)": {}}
    for nm in ["닛케이", "DAX", "항셍", "코스피", "코스닥", "대만가권", "상해종합", "FTSE", "CAC40"]:
        s = load(MK[nm])
        a = fw(s.values, 21)
        base = np.nanmean(a)
        c["하루 −5%(전체)"][nm] = [(str(s.index[i].date()), float(a[i] - base)) for i in ev_foreign(s) if not np.isnan(a[i])]
    out += study("foreign-drop-events", 21, c, "INCONCLUSIVE(1/9)")
    # 4) crash-rebound: 63일
    c = {"20일 −20% ∧ 낙폭 −30%": {}}
    for tk in ["^KS11", "^KQ11", "^SOX", "^NDX", "^N225", "^HSI", "^GDAXI", "^GSPC"]:
        s = load(tk)
        a = fw(s.values, 63)
        base = np.nanmean(a)
        c["20일 −20% ∧ 낙폭 −30%"][tk] = [(str(s.index[i].date()), float(a[i] - base)) for i in ev_crash(s.values) if not np.isnan(a[i])]
    out += study("crash-rebound-events", 63, c, "INCONCLUSIVE(3/8)")
    (F / "drop-events-v2-results.json").write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
    for r in out:
        print(r["연구"], r["셀"], r.get("유효시장"), r.get("시장당부호일치"), r.get("지역"), "사건", r.get("사건"), "군집", r.get("군집"), "평균", r.get("평균초과"), r.get("ci95"), r.get("ci95_14일"), r.get("ci95_60일"), r.get("구간0제외"))


if __name__ == "__main__":
    main()
