#!/usr/bin/env python3
"""업종 거래대금 확인 - 사전등록 findings/sector-volume-confirmation-preregistration-2026-10.md (문서가 이 코드보다 우선).

A. S1(업종 상대강세 k일 연속) 사건을 사건일 거래대금 비중 추세(증가/감소)로 나눠 진입 후 누적 초과 경로를 비교
B. 월말 2×2(가격 상대강세/약세 × 비중 증가/감소) → 다음 20세션 초과
과거 구간은 설명용(이미 본 표본). 전체 기간 합산 판정 없음 - 연도별, 2026년 4~9월 월별.

  python run_sector_volume_confirm.py --selftest
  python run_sector_volume_confirm.py                  # 연도별·월별 (문서·코드가 커밋된 깨끗한 상태에서만)
  python run_sector_volume_confirm.py --forward-report # 동결일 이후만, 월별
"""
import argparse
import sys
import warnings
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import run_sector_rise_study as rs  # noqa: E402
import run_sector_rise_extras as ex  # noqa: E402

PREREG = HERE / "findings" / "sector-volume-confirmation-preregistration-2026-10.md"
KS = (3, 5)
NS = (1, 2, 3, 5, 10, 15, 20)
INTERVALS = [(0, 1), (1, 3), (3, 5), (5, 10), (10, 15), (15, 20)]
VOL_LONG, VOL_SHORT = 60, 20
MIN_N = 5


def volume_ratio(V, elig, gid, i, g):
    """사건일 i 의 적격 종목 목록 고정. 비중(t) = 그룹 거래대금 ÷ 시장 적격 거래대금, 추세 = 20일 평균 ÷ 60일 평균."""
    if i < VOL_LONG - 1:
        return np.nan
    m = elig[i] & (gid == g)
    w = V[i - VOL_LONG + 1:i + 1]
    tm = np.nansum(w[:, elig[i]], axis=1)
    if np.any(tm <= 0):
        return np.nan
    share = np.nansum(w[:, m], axis=1) / tm
    return share[-VOL_SHORT:].mean() / share.mean()


def path_excess(C, O, elig, gid, i, g, ns=NS):
    """진입 = i+1 시가. 누적 초과(n) = 그룹 EW (C[j+n-1]/O[j]-1) − 시장 EW. 데이터가 모자라면 NaN."""
    D = C.shape[0]
    j = i + 1
    out = []
    m = elig[i] & (gid == g)
    for n in ns:
        if j + n - 1 >= D:
            out.append(np.nan)
            continue
        r = np.where(O[j] > 0, C[j + n - 1] / O[j] - 1, np.nan)
        out.append(rs.nanmean(r[m]) - rs.nanmean(r[elig[i]]))
    return np.array(out)


def increments(mean_path):
    """mean_path: NS 순서의 평균 누적 초과. 구간 증분 {(a,b): 값}. 0 시점은 0."""
    pts = {0: 0.0}
    pts.update(dict(zip(NS, mean_path)))
    return {(a, b): pts[b] - pts[a] for a, b in INTERVALS if not (np.isnan(pts[a]) or np.isnan(pts[b]))}


def most_fading(inc):
    return min(inc, key=inc.get) if inc else None


def collect_A(C, O, V, elig, gid, rel, dates, ngroups, keyfn, min_date=None):
    res = {}
    for k in KS:
        S = rs.s1_state(rel, k)
        for g in range(ngroups):
            for i in ex.starts(S, g):
                if min_date and dates[i] < min_date:
                    continue
                if (elig[i] & (gid == g)).sum() < rs.MIN_GROUP or i + 2 >= len(dates):
                    continue
                r = volume_ratio(V, elig, gid, i, g)
                if np.isnan(r):
                    continue
                p = path_excess(C, O, elig, gid, i, g)
                res.setdefault(k, {}).setdefault(keyfn(dates[i]), {"up": [], "down": []})["up" if r > 1 else "down"].append(p)
    return res


def collect_B(C, O, V, elig, gid, R, dates, ngroups, keyfn, min_date=None):
    res = {}
    D = len(dates)
    for i in ex.month_ends(dates):
        if i < VOL_LONG or i + 21 >= D or (min_date and dates[i] < min_date):
            continue
        r20 = C[i] / C[i - 20] - 1
        mk = rs.nanmed(r20[elig[i]])
        for g in range(ngroups):
            m = elig[i] & (gid == g)
            if m.sum() < rs.MIN_GROUP:
                continue
            ratio = volume_ratio(V, elig, gid, i, g)
            if np.isnan(ratio):
                continue
            price = rs.nanmed(r20[m]) - mk
            v = ex.fwd_excess(C, O, elig, gid, i, g, 1)
            if np.isnan(v):
                continue
            cls = ("강세" if price > 0 else "약세") + ("+증가" if ratio > 1 else "+감소")
            res.setdefault(keyfn(dates[i]), {}).setdefault(cls, []).append(v)
    return res


def bp(x):
    return "·" if x is None or np.isnan(x) else f"{x * 1e4:+.0f}"


def mean_path(paths):
    if not len(paths):
        return np.full(len(NS), np.nan)
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        return np.nanmean(np.array(paths), axis=0)


def print_A(res, keys, label):
    for k in KS:
        d = res.get(k, {})
        print(f"\n#### A. S1 k={k}{' (기준)' if k == 3 else ' (민감도)'} — {label}: 사건 수 · 누적 초과(bp) n=5/10/20 · 차이(증가−감소) · 가장 줄어드는 구간(증분 최소)\n")
        print("| 키 | 증가군 n | 감소군 n | 증가 5/10/20 | 감소 5/10/20 | A1 차이 n5 | A2 차이 n20 | 증가군 최대 하락 구간 | 감소군 최대 하락 구간 |")
        print("|---|---|---|---|---|---|---|---|---|")
        cnt = {"up": {}, "down": {}}
        for key in keys:
            b = d.get(key)
            if not b:
                print(f"| {key} | - | - | - | - | - | - | - | - |")
                continue
            pu, pd_ = mean_path(b["up"]), mean_path(b["down"])
            ix = {n: NS.index(n) for n in NS}
            nu, nd = len(b["up"]), len(b["down"])
            fu = most_fading(increments(pu)) if nu >= MIN_N else None
            fd = most_fading(increments(pd_)) if nd >= MIN_N else None
            for nm, f in (("up", fu), ("down", fd)):
                if f:
                    cnt[nm][f] = cnt[nm].get(f, 0) + 1
            f5 = lambda p: "/".join(bp(p[ix[n]]) for n in (5, 10, 20))
            fl = lambda f: "·" if f is None else f"{f[0]}→{f[1]}일"
            flag = lambda n: "†" if n < MIN_N else ""
            diff = lambda n: bp(pu[ix[n]] - pd_[ix[n]]) if nu and nd else "·"
            print(f"| {key} | {nu}{flag(nu)} | {nd}{flag(nd)} | {f5(pu)} | {f5(pd_)} | {diff(5)} | {diff(20)} | {fl(fu)} | {fl(fd)} |")
        print("\n연도(월)별 '가장 줄어드는 구간' 횟수 — " + " · ".join(f"{nm}: " + ", ".join(f"{a}→{b}일 {c}" for (a, b), c in sorted(cnt[nm].items())) for nm in ("up", "down")))


def print_B(res, keys, label):
    print(f"\n#### B. 월말 2×2 → 다음 20세션 초과(bp, n) — {label}\n")
    classes = ["강세+증가", "강세+감소", "약세+증가", "약세+감소"]
    print("| 키 | " + " | ".join(classes) + " | B1 (강세+증가)−(강세+감소) |")
    print("|---|---|---|---|---|---|")
    for key in keys:
        b = res.get(key, {})
        cells = []
        for c in classes:
            v = b.get(c, [])
            cells.append(f"{bp(np.mean(v))} (n={len(v)}{'†' if len(v) < MIN_N else ''})" if v else "-")
        a, c2 = b.get("강세+증가", []), b.get("강세+감소", [])
        d = bp(np.mean(a) - np.mean(c2)) if len(a) >= 1 and len(c2) >= 1 else "·"
        print(f"| {key} | " + " | ".join(cells) + f" | {d} |")


def selftest():
    def ok(c, m):
        if not c:
            print("selftest 실패:", m); sys.exit(1)
    rng = np.random.default_rng(5)
    D, T = 160, 100
    C = np.cumprod(1 + rng.normal(0, 0.002, (D, T)), axis=0) * 1000
    V = np.full((D, T), 5e9)
    V[100:, :50] *= np.linspace(1, 3, D - 100)[:, None]       # 업종 0 거래대금이 100일 이후 늘어난다
    V[100:, 50:] *= np.linspace(1, 0.4, D - 100)[:, None]     # 업종 1 은 줄어든다
    gid = np.array([0] * 50 + [1] * 50)
    common = np.ones(T, bool)
    elig = rs.compute_elig(V, common, gid)
    ok(volume_ratio(V, elig, gid, 150, 0) > 1.05, f"증가 업종 비중 추세 {volume_ratio(V, elig, gid, 150, 0)}")
    ok(volume_ratio(V, elig, gid, 150, 1) < 0.95, f"감소 업종 비중 추세 {volume_ratio(V, elig, gid, 150, 1)}")
    ok(np.isnan(volume_ratio(V, elig, gid, 30, 0)), "60일이 모자라면 제외")
    O = C.copy()
    C2 = C.copy()
    O2 = C.copy()
    C2[111:, :50] *= 1.06                                       # 112일부터 상승
    O2[112:] = C2[112:]
    p = path_excess(C2, O2, elig, gid, 110, 0)                  # 진입 O[111](상승 전) → n=1 종가 C[111] 에서 상승
    ok(p[0] > 0.02 and abs(p[-1] - p[1]) < 0.02, f"경로 {p}")
    ok(np.isnan(path_excess(C, O, elig, gid, D - 3, 0)[-1]), "데이터 끝을 넘으면 NaN")
    inc = increments(np.array([0.01, 0.02, 0.03, 0.05, 0.04, 0.03, 0.01]))
    ok(most_fading(inc) == (15, 20), f"가장 줄어드는 구간 {most_fading(inc)}")
    ok(most_fading({}) is None, "빈 입력")
    print("selftest OK - run_sector_volume_confirm")
    return 0


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--selftest", action="store_true")
    ap.add_argument("--forward-report", action="store_true")
    a = ap.parse_args()
    if a.selftest:
        return selftest()
    for p in (PREREG, Path(__file__).resolve(), Path(rs.__file__).resolve(), Path(ex.__file__).resolve()):
        if not rs.committed_clean(p):
            print(f"{p.name} 가 커밋되지 않았거나 수정 중 - 계산하지 않는다")
            return 2
    dates, tickers, groups, C, O, V, common, gid = rs.load_all()
    ng = len(groups)
    elig = rs.compute_elig(V, common, gid)
    R = np.full(C.shape, np.nan)
    R[1:] = C[1:] / C[:-1] - 1
    rel = ex.build_rel(R, elig, gid, ng)
    if a.forward_report:
        keyfn = lambda d: d[:7]
        A = collect_A(C, O, V, elig, gid, rel, dates, ng, keyfn, rs.FREEZE)
        B = collect_B(C, O, V, elig, gid, R, dates, ng, keyfn, rs.FREEZE)
        keys = sorted({k for kk in A.values() for k in kk} | set(B))
        print(f"### forward (동결일 {rs.FREEZE} 이후) 월별")
        print_A(A, keys, "월별"); print_B(B, keys, "월별")
        return 0
    years = sorted({d[:4] for d in dates})
    A = collect_A(C, O, V, elig, gid, rel, dates, ng, lambda d: d[:4])
    B = collect_B(C, O, V, elig, gid, R, dates, ng, lambda d: d[:4])
    A_m = collect_A(C, O, V, elig, gid, rel, dates, ng, lambda d: d[:7], "2026-04-01")
    B_m = collect_B(C, O, V, elig, gid, R, dates, ng, lambda d: d[:7], "2026-04-01")
    months = [f"2026-{m:02d}" for m in range(4, 10)]
    print(f"A2a {dates[0]} ~ {dates[-1]} (사건 5건 미만은 †)")
    print("\n### 연도별"); print_A(A, years, "연도별"); print_B(B, years, "연도별")
    print("\n### 2026년 4~9월 월별"); print_A(A_m, months, "월별"); print_B(B_m, months, "월별")
    return 0


if __name__ == "__main__":
    sys.exit(main())
