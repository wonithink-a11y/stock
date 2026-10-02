#!/usr/bin/env python3
"""업종 부상 탐지 부록(설명용) - 사전등록 findings/sector-rise-detector-preregistration-2026-10.md §7.

  7.1 진입 지연·연속일 민감도   7.2 업종 강세 지속 기간   7.3 거래대금 확인(현재 상태)
정의는 문서에 고정돼 있고 **전부 보고**한다. 채택·판정 근거가 아니다. 과거 분류별 이후 수익률(7.3)은 내지 않는다.

  python run_sector_rise_extras.py --selftest
  python run_sector_rise_extras.py [--only 7.1|7.2|7.3]     # 문서·코드가 커밋된 깨끗한 상태에서만
"""
import argparse
import sys
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import run_sector_rise_study as rs  # noqa: E402

KS = (2, 3, 5)
DELAYS = (0, 1, 2, 3, 5)
HOLD = 20
TOP_THIRD_K = (1, 3, 6)


def build_rel(R, elig, gid, ngroups):
    """(날짜 × 업종) 일 상대수익(업종 적격 중앙값 − 시장 적격 중앙값)."""
    D = R.shape[0]
    mk = np.full(D, np.nan)
    rel = np.full((D, ngroups), np.nan)
    for i in range(10, D):
        e = elig[i]
        if e.sum() < 50:
            continue
        mk[i] = rs.nanmed(R[i, e])
        for g in range(ngroups):
            m = e & (gid == g)
            if m.sum() >= rs.MIN_GROUP:
                rel[i, g] = rs.nanmed(R[i, m]) - mk[i]
    return rel


def starts(S, g_i, dedup=rs.DEDUP_DAYS):
    D = S.shape[0]
    return [i for i in range(D) if S[i, g_i] and not S[max(0, i - dedup):i, g_i].any()]


def fwd_excess(C, O, elig, gid, i, g, d, hold=HOLD):
    """사건일 i, 진입 지연 d. d=0: 사건일 종가 → i+hold 종가. d>=1: i+d 시가 → i+d+hold-1 종가."""
    D = C.shape[0]
    if d == 0:
        if i + hold >= D:
            return np.nan
        r = C[i + hold] / C[i] - 1
    else:
        j = i + d
        if j + hold - 1 >= D:
            return np.nan
        r = np.where(O[j] > 0, C[j + hold - 1] / O[j] - 1, np.nan)
    m = elig[i] & (gid == g)
    return rs.nanmean(r[m]) - rs.nanmean(r[elig[i]])


def sensitivity(C, O, elig, gid, rel, dates, ngroups):
    out = {}   # (k, d) -> {year: [ex...]}
    for k in KS:
        S = rs.s1_state(rel, k)
        for g in range(ngroups):
            for i in starts(S, g):
                if (elig[i] & (gid == g)).sum() < rs.MIN_GROUP:
                    continue
                for d in DELAYS:
                    v = fwd_excess(C, O, elig, gid, i, g, d)
                    if not np.isnan(v):
                        out.setdefault((k, d), {}).setdefault(dates[i][:4], []).append(v)
    return out


def print_sensitivity(out, dates):
    years = sorted({d[:4] for d in dates})
    print("### 7.1 진입 지연·연속일 민감도 — 20세션 보유 평균 초과(bp, 비용 전). 연속일 k × 진입 d(0=사건일 종가, 1=다음 시가=기준, 2·3·5=그 뒤 거래일 시가)\n")
    print("| k | d | " + " | ".join(years) + " | 전체 평균(참고) |")
    print("|---|---|" + "---|" * (len(years) + 1))
    for k in KS:
        for d in DELAYS:
            cell = out.get((k, d), {})
            allv = [x for v in cell.values() for x in v]
            row = " | ".join((f"{np.mean(cell[y]) * 1e4:+.0f}" if y in cell and len(cell[y]) >= 5 else "·") for y in years)
            print(f"| {k} | {d} | {row} | {np.mean(allv) * 1e4:+.0f} (n={len(allv)}) |")
    print("\n(· = 해당 연도 사건 5건 미만)")


def month_ends(dates):
    return [i for i in range(len(dates) - 1) if dates[i][:7] != dates[i + 1][:7]]


def persistence(C, elig, gid, dates, ngroups):
    me = [i for i in month_ends(dates) if i >= 63 + rs.TV_WIN]
    RS = np.full((len(me), ngroups), np.nan)
    for a, i in enumerate(me):
        e = elig[i]
        r3 = C[i] / C[i - 63] - 1
        mk = rs.nanmed(r3[e])
        for g in range(ngroups):
            m = e & (gid == g)
            if m.sum() >= rs.MIN_GROUP:
                RS[a, g] = rs.nanmed(r3[m]) - mk
    return me, RS


def print_persistence(me, RS, dates, groups):
    spells = []
    for g in range(RS.shape[1]):
        run = 0
        for a in range(RS.shape[0]):
            v = RS[a, g]
            if not np.isnan(v) and v > 0:
                run += 1
            else:
                if run:
                    spells.append(run)
                run = 0
        # 진행 중인 마지막 구간은 제외(미완결)
    sp = np.array(spells)
    print("### 7.2 업종 강세 지속 기간 (월말 기준 3개월 상대강도 > 0 이 연속된 월 수)\n")
    print(f"완결된 구간 {len(sp)}개 · 중앙값 {np.median(sp):.0f}개월 · 평균 {sp.mean():.1f}개월 · 3개월 이상 {100 * (sp >= 3).mean():.0f}% · 6개월 이상 {100 * (sp >= 6).mean():.0f}% · 12개월 이상 {100 * (sp >= 12).mean():.0f}%\n")
    # 상위 3분의 1 유지
    top = np.zeros(RS.shape, bool)
    valid = ~np.isnan(RS)
    for a in range(RS.shape[0]):
        idx = np.where(valid[a])[0]
        if len(idx) < 9:
            continue
        kk = int(np.ceil(len(idx) / 3))
        order = idx[np.argsort(-RS[a, idx], kind="stable")][:kk]
        top[a, order] = True
    yrs = sorted({dates[i][:4] for i in me})
    print("상위 3분의 1 업종이 k개월 뒤에도 상위 3분의 1인 비율 (무작위 기대 약 33~35%) — 연도별(기준월의 연도)\n")
    print("| 연도 | " + " | ".join(f"{k}개월 뒤" for k in TOP_THIRD_K) + " |")
    print("|---|" + "---|" * len(TOP_THIRD_K))
    for y in yrs:
        row = []
        for k in TOP_THIRD_K:
            num = den = 0
            for a, i in enumerate(me):
                if dates[i][:4] != y or a + k >= len(me):
                    continue
                for g in np.where(top[a])[0]:
                    if valid[a + k, g]:
                        den += 1
                        num += top[a + k, g]
            row.append(f"{100 * num / den:.0f}% (n={den})" if den >= 10 else "·")
        print(f"| {y} | " + " | ".join(row) + " |")
    allr = []
    for k in TOP_THIRD_K:
        num = den = 0
        for a in range(len(me)):
            if a + k >= len(me):
                continue
            for g in np.where(top[a])[0]:
                if valid[a + k, g]:
                    den += 1
                    num += top[a + k, g]
        allr.append(f"{100 * num / den:.0f}%")
    print(f"\n전체(참고): " + " · ".join(f"{k}개월 뒤 {r}" for k, r in zip(TOP_THIRD_K, allr)))


def volume_state(C, V, elig, gid, dates, groups):
    D = C.shape[0]
    i = D - 1
    e = elig[i]
    Vt = np.where(e[None, :], V, np.nan)
    mk_tv = np.nansum(Vt[i - 59:i + 1], axis=1)
    r20 = C[i] / C[i - 20] - 1
    mk20 = rs.nanmed(r20[e])
    rows = []
    for g, name in enumerate(groups):
        m = e & (gid == g)
        if m.sum() < rs.MIN_GROUP:
            continue
        g_tv = np.nansum(Vt[i - 59:i + 1][:, m], axis=1)
        share = g_tv / mk_tv
        ratio = share[-20:].mean() / share[-60:].mean()
        price = rs.nanmed(r20[m]) - mk20
        rows.append((price, name, int(m.sum()), share[-20:].mean(), ratio))
    rows.sort(reverse=True)
    print(f"### 7.3 거래대금 확인 — 현재({dates[i]}) · 가격 추세 = 업종 20일 수익률 중앙값 − 시장, 비중 = 업종 거래대금 ÷ 시장 적격 거래대금\n")
    print("| 업종 | 종목 | 20일 상대수익 | 거래대금 비중(20일) | 비중 20일/60일 | 분류 |")
    print("|---|---|---|---|---|---|")
    for price, name, n, sh, ratio in rows:
        if price > 0:
            lab = "상대강세 + 비중 증가" if ratio > 1 else "상대강세 + 비중 감소"
        else:
            lab = "상대약세 + 비중 증가" if ratio > 1 else "상대약세 + 비중 감소"
        print(f"| {name} | {n} | {price * 100:+.1f}%p | {sh * 100:.1f}% | {ratio:.2f} | {lab} |")


def selftest():
    def ok(c, m):
        if not c:
            print("selftest 실패:", m); sys.exit(1)
    rng = np.random.default_rng(3)
    D, T = 200, 120
    C = np.cumprod(1 + rng.normal(0, 0.002, (D, T)), axis=0) * 1000
    O = C.copy()
    V = np.full((D, T), 5e9)
    gid = np.array([0] * 60 + [1] * 60)
    common = np.ones(T, bool)
    for d in range(100, 103):
        C[d:, :60] *= 1.03
    O = C.copy()
    C[103:, :60] *= 1.04          # 103일 장중에 상승 - 103일 시가는 상승 전, 104일부터 시가도 반영
    O[104:] = C[104:]
    elig = rs.compute_elig(V, common, gid)
    R = np.full((D, T), np.nan); R[1:] = C[1:] / C[:-1] - 1
    rel = build_rel(R, elig, gid, 2)
    ev_i = [i for i in starts(rs.s1_state(rel, 3), 0) if 100 <= i <= 105]
    ok(ev_i == [102], f"사건일 {ev_i}")
    v0 = fwd_excess(C, O, elig, gid, 102, 0, 0)
    v1 = fwd_excess(C, O, elig, gid, 102, 0, 1)
    v2 = fwd_excess(C, O, elig, gid, 102, 0, 2)
    ok(v1 > 0.015 and v2 < v1 - 0.01, f"하루 늦게 진입하면 상승분을 놓친다 d1={v1} d2={v2}")
    ok(abs(v0 - v1) < 0.01, f"사건일 종가와 다음 시가는 비슷 d0={v0} d1={v1}")
    ok(np.isnan(fwd_excess(C, O, elig, gid, D - 5, 0, 1)), "데이터 끝을 넘으면 NaN")
    me, RS = persistence(C, elig, gid, [f"2026-{1 + d // 21:02d}-{1 + d % 21:02d}" for d in range(D)], 2)
    ok(RS.shape[1] == 2, "지속 기간 행렬")
    print("selftest OK - run_sector_rise_extras")
    return 0


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--selftest", action="store_true")
    ap.add_argument("--only")
    a = ap.parse_args()
    if a.selftest:
        return selftest()
    for p in (rs.PREREG, Path(__file__).resolve(), Path(rs.__file__).resolve()):
        if not rs.committed_clean(p):
            print(f"{p.name} 가 커밋되지 않았거나 수정 중 - 계산하지 않는다")
            return 2
    dates, tickers, groups, C, O, V, common, gid = rs.load_all()
    ng = len(groups)
    elig = rs.compute_elig(V, common, gid)
    R = np.full(C.shape, np.nan)
    R[1:] = C[1:] / C[:-1] - 1
    print(f"A2a {dates[0]} ~ {dates[-1]}\n")
    if a.only in (None, "7.1"):
        rel = build_rel(R, elig, gid, ng)
        print_sensitivity(sensitivity(C, O, elig, gid, rel, dates, ng), dates)
        print()
    if a.only in (None, "7.2"):
        me, RS = persistence(C, elig, gid, dates, ng)
        print_persistence(me, RS, dates, groups)
        print()
    if a.only in (None, "7.3"):
        volume_state(C, V, elig, gid, dates, groups)
    return 0


if __name__ == "__main__":
    sys.exit(main())
