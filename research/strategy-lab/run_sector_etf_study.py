#!/usr/bin/env python3
"""업종 ETF 연계 - 사전등록 findings/sector-etf-link-preregistration-2026-10.md (문서가 이 코드보다 우선).

E1 ETF 묶음의 20일 가격 방향 × 자금 유입 → 다음 20세션 초과 · E2 ETF-종목 선행/후행·유입과 부상 사건(기록 전용) · E3 S1 사건 뒤 ETF vs 종목(비용 후)
과거는 설명용. 전체 기간 합산 판정 없음 - 연도별, 2026년 4~9월 월별.

  python run_sector_etf_study.py --selftest
  python run_sector_etf_study.py                    # 문서·코드가 커밋된 깨끗한 상태에서만
  python run_sector_etf_study.py --forward-report   # 동결일 이후만, 월별
"""
import argparse
import json
import re
import sys
import warnings
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import run_sector_rise_study as rs  # noqa: E402
import run_sector_rise_extras as ex  # noqa: E402

PREREG = HERE / "findings" / "sector-etf-link-preregistration-2026-10.md"
ETF_DIR = HERE / "data" / "etf-ohlc"
MAP = [("반도체", "반도체"), ("2차전지", "2차전지|배터리"), ("바이오·헬스케어", "바이오|헬스케어|제약"), ("자동차·부품", "자동차"),
       ("금융", "은행|증권|보험|금융"), ("조선·해운·운송", "조선|해운|운송"), ("건설·부동산·건자재", "건설"), ("항공·방산", "방산|항공|우주"),
       ("철강·비철금속", "철강"), ("화학·소재", "화학|소재"), ("IT·소프트웨어", "소프트웨어|인터넷|게임|플랫폼"), ("미디어·엔터·광고", "미디어|엔터|콘텐츠|K-?POP"),
       ("전력·전기장비", "전력|전기|원자력|원전|신재생|태양광|풍력"), ("유통·소비재", "소비|유통|화장품"), ("음식료·농수산", "음식료|식품"),
       ("기계·장비", "기계|로봇"), ("통신·네트워크", "통신")]
EXC = re.compile("레버리지|인버스|선물|채권|합성|미국|중국|일본|글로벌|S&P|나스닥|KOFR|국채|CD금리|리츠|배당|인도|베트남|유럽|월간|커버드|단기|머니마켓|금현물|달러|엔|금융채|채")
MIN_ETFS, MIN_NA = 3, 5e10
LAG20, LAG5 = 20, 5
HOLD = 20
COST_ETF_BP, COST_STOCK_BP = 5.0, 33.5
MIN_N = 5
LAGS = (-3, -1, 0, 1, 3)


def group_of(name):
    if EXC.search(name or ""):
        return None
    for g, pat in MAP:
        if re.search(pat, name):
            return g
    return None


# ---------------------------------------------------------------- 순수 계산
def basket(A, i, lag, g_idx):
    """업종 ETF 묶음: (cols, 가격 lag 일, 자금 유입 lag 일 %). 조건 미달이면 None. A: dict(C,O,NAV,SH,NA,eg)."""
    if i - lag < 0:
        return None
    cols = np.where(A["eg"] == g_idx)[0]
    if not len(cols):
        return None
    C, SH, NA, NAV = A["C"], A["SH"], A["NA"], A["NAV"]
    ok = (~np.isnan(C[i, cols]) & ~np.isnan(C[i - lag, cols]) & (C[i - lag, cols] > 0) & ~np.isnan(SH[i, cols]) & ~np.isnan(SH[i - lag, cols])
          & ~np.isnan(NA[i, cols]) & ~np.isnan(NA[i - lag, cols]) & (NA[i - lag, cols] > 0) & ~np.isnan(NAV[i, cols]))
    cols = cols[ok]
    if len(cols) < MIN_ETFS or NA[i - lag, cols].sum() < MIN_NA:
        return None
    w = NA[i, cols]
    ret = (w * (C[i, cols] / C[i - lag, cols] - 1)).sum() / w.sum()
    flow = ((SH[i, cols] - SH[i - lag, cols]) * NAV[i, cols]).sum() / NA[i - lag, cols].sum()
    return cols, ret, flow


def etf_fwd(A, i, cols, hold=HOLD):
    """진입 = i+1 시가, 청산 = i+hold 종가(진입일 포함 hold 세션). 순자산(i) 가중. 데이터가 모자라면 NaN."""
    D = A["C"].shape[0]
    j = i + 1
    if j + hold - 1 >= D:
        return np.nan
    o, c, w = A["O"][j, cols], A["C"][j + hold - 1, cols], A["NA"][i, cols]
    ok = ~np.isnan(o) & ~np.isnan(c) & (o > 0) & ~np.isnan(w)
    if ok.sum() < MIN_ETFS:
        return np.nan
    return (w[ok] * (c[ok] / o[ok] - 1)).sum() / w[ok].sum()


def stock_market_fwd(C, O, elig, i, hold=HOLD):
    D = C.shape[0]
    j = i + 1
    if j + hold - 1 >= D:
        return np.nan
    r = np.where(O[j] > 0, C[j + hold - 1] / O[j] - 1, np.nan)
    return rs.nanmean(r[elig[i]])


def state_of(ret, flow):
    return ("상승" if ret > 0 else "하락") + ("·유입" if flow > 0 else "·유출")


def net_diff_bp(etf_ex, stock_ex):
    """E3: (ETF 초과 − 5bp) − (종목 초과 − 33.5bp)."""
    return (etf_ex - COST_ETF_BP / 1e4) - (stock_ex - COST_STOCK_BP / 1e4)


# ---------------------------------------------------------------- 적재
def load_etf(dates, groups):
    di = {d: k for k, d in enumerate(dates)}
    rows, names = {}, {}
    for p in sorted(ETF_DIR.glob("*.jsonl")):
        for line in open(p, encoding="utf-8"):
            r = json.loads(line)
            if "_day" in r:
                continue
            d = f"{r['BAS_DD'][:4]}-{r['BAS_DD'][4:6]}-{r['BAS_DD'][6:]}"
            if d in di:
                rows[(di[d], r["ISU_CD"])] = r
                names[r["ISU_CD"]] = r["ISU_NM"]
    codes = sorted({c for _, c in rows})
    ci = {c: j for j, c in enumerate(codes)}
    D, E = len(dates), len(codes)
    mk = lambda: np.full((D, E), np.nan)
    A = {"C": mk(), "O": mk(), "NAV": mk(), "SH": mk(), "NA": mk()}

    def f(x):
        try:
            return float(str(x).replace(",", ""))
        except (TypeError, ValueError):
            return np.nan
    for (i, c), r in rows.items():
        j = ci[c]
        A["C"][i, j], A["O"][i, j], A["NAV"][i, j] = f(r["TDD_CLSPRC"]), f(r["TDD_OPNPRC"]), f(r["NAV"])
        A["SH"][i, j], A["NA"][i, j] = f(r["LIST_SHRS"]), f(r["INVSTASST_NETASST_TOTAMT"])
    gix = {g: k for k, g in enumerate(groups)}
    eg = np.full(E, -1)
    for c, j in ci.items():
        g = group_of(names[c])
        if g in gix:
            eg[j] = gix[g]
    A["eg"] = eg
    for k in ("C", "O"):
        A[k][A[k] <= 0] = np.nan
    return A, codes, names


# ---------------------------------------------------------------- 분석
def analysis_E1(A, C, O, elig, dates, ng):
    out = []
    for i in ex.month_ends(dates):
        if i < LAG20 or i + HOLD + 1 >= len(dates):
            continue
        mk = stock_market_fwd(C, O, elig, i)
        if np.isnan(mk):
            continue
        for g in range(ng):
            b = basket(A, i, LAG20, g)
            if b is None:
                continue
            cols, ret, flow = b
            f = etf_fwd(A, i, cols)
            if np.isnan(f):
                continue
            out.append({"date": dates[i], "g": g, "up": ret > 0, "in": flow > 0, "ex": f - mk})
    return out


def analysis_E3(A, C, O, elig, gid, rel, dates, ng):
    out = []
    S = rs.s1_state(rel, 3)
    for g in range(ng):
        for i in ex.starts(S, g):
            if i + HOLD + 1 >= len(dates) or (elig[i] & (gid == g)).sum() < rs.MIN_GROUP:
                continue
            b = basket(A, i, LAG20, g)
            if b is None:
                continue
            f = etf_fwd(A, i, b[0])
            mk = stock_market_fwd(C, O, elig, i)
            sx = ex.fwd_excess(C, O, elig, gid, i, g, 1)
            if np.isnan(f) or np.isnan(mk) or np.isnan(sx):
                continue
            out.append({"date": dates[i], "etf": f - mk, "stk": sx})
    return out


def lag_corr(a, b, k):
    """corr(a[t], b[t+k])."""
    if k >= 0:
        x, y = a[:len(a) - k] if k else a, b[k:]
    else:
        x, y = a[-k:], b[:len(b) + k]
    m = ~np.isnan(x) & ~np.isnan(y)
    if m.sum() < 60 or np.std(x[m]) == 0 or np.std(y[m]) == 0:
        return np.nan
    return np.corrcoef(x[m], y[m])[0, 1]


def analysis_E2a(A, R, elig, gid, dates, ng):
    D = len(dates)
    res = {}
    for g in range(ng):
        etf = np.full(D, np.nan)
        stk = np.full(D, np.nan)
        for t in range(1, D):
            b = basket(A, t, 1, g)
            if b is not None:
                etf[t] = b[1]
            m = elig[t] & (gid == g)
            if m.sum() >= rs.MIN_GROUP:
                stk[t] = rs.nanmean(R[t, m])
        if np.isnan(etf).all():
            continue
        for y in sorted({d[:4] for d in dates}):
            idx = np.array([k for k, d in enumerate(dates) if d[:4] == y])
            for k in LAGS:
                res.setdefault((y, k), []).append(lag_corr(etf[idx], stk[idx], k))
    return res


def analysis_E2b(A, rel, dates, ng):
    S = rs.s1_state(rel, 3)
    by = {}
    for g in range(ng):
        for i in ex.starts(S, g):
            for off, key in ((0, "당일"), (5, "5일 전")):
                t = i - off
                flows = {}
                for gg in range(ng):
                    b = basket(A, t, LAG5, gg)
                    if b is not None:
                        flows[gg] = b[2]
                if g in flows and len(flows) >= 6:
                    order = sorted(flows, key=lambda x: -flows[x])
                    top = set(order[:int(np.ceil(len(flows) / 3))])
                    by.setdefault(dates[i][:4], {}).setdefault(key, []).append(g in top)
    return by


def bp(x):
    return "·" if x is None or np.isnan(x) else f"{x * 1e4:+.0f}"


def print_E1(rows, keys, label):
    print(f"\n#### E1 {label} — 다음 20세션 ETF 묶음 초과(bp, n)\n")
    print("| 키 | 상승·유입 | 상승·유출 | 하락·유입 | 하락·유출 | E1 (상승·유입)−(상승·유출) |")
    print("|---|---|---|---|---|---|")
    for k in keys:
        es = [e for e in rows if e["date"].startswith(k)]
        cells, m = [], {}
        for up in (True, False):
            for inn in (True, False):
                v = [e["ex"] for e in es if e["up"] == up and e["in"] == inn]
                m[(up, inn)] = np.mean(v) if v else np.nan
                cells.append(f"{bp(m[(up, inn)])} (n={len(v)}{'†' if len(v) < MIN_N else ''})" if v else "-")
        d = m[(True, True)] - m[(True, False)] if not (np.isnan(m[(True, True)]) or np.isnan(m[(True, False)])) else np.nan
        print(f"| {k} | " + " | ".join(cells) + f" | {bp(d)} |")


def print_E3(rows, keys, label):
    print(f"\n#### E3 {label} — S1 사건 뒤 20세션 초과(bp). ETF − 종목 (비용 전 / 비용 후: ETF 5bp·종목 33.5bp)\n")
    print("| 키 | n | ETF 초과 | 종목 초과 | 차이(전) | **E3 차이(후)** |")
    print("|---|---|---|---|---|---|")
    for k in keys:
        es = [e for e in rows if e["date"].startswith(k)]
        if not es:
            print(f"| {k} | 0 | - | - | - | - |")
            continue
        a, b = np.mean([e["etf"] for e in es]), np.mean([e["stk"] for e in es])
        print(f"| {k} | {len(es)}{'†' if len(es) < MIN_N else ''} | {bp(a)} | {bp(b)} | {bp(a - b)} | {bp(net_diff_bp(a, b))} |")


def print_E2(res2a, res2b, years):
    print("\n#### E2 (기록 전용) ⓐ ETF 묶음 일 수익 vs 업종 종목 일 수익 상관 — 시차 k (ETF[t] 와 종목[t+k], k>0 이면 ETF 가 앞섬), 업종 평균\n")
    print("| 연도 | " + " | ".join(f"k={k:+d}" for k in LAGS) + " |")
    print("|---|" + "---|" * len(LAGS))
    for y in years:
        cells = []
        for k in LAGS:
            v = [x for x in res2a.get((y, k), []) if not np.isnan(x)]
            cells.append(f"{np.mean(v):.2f} (n={len(v)})" if len(v) >= 3 else "·")
        print(f"| {y} | " + " | ".join(cells) + " |")
    print("\nⓑ S1 사건에서 그 업종 ETF 5일 자금 유입이 업종들 중 상위 3분의 1인 비율(기대 약 33%)\n")
    print("| 연도 | 사건일 당일 | 5일 전 |")
    print("|---|---|---|")
    for y in years:
        d = res2b.get(y, {})
        f = lambda k: f"{100 * np.mean(d[k]):.0f}% (n={len(d[k])})" if d.get(k) else "·"
        print(f"| {y} | {f('당일')} | {f('5일 전')} |")


def selftest():
    def ok(c, m):
        if not c:
            print("selftest 실패:", m); sys.exit(1)
    ok(group_of("KODEX 반도체") == "반도체" and group_of("TIGER 2차전지테마") == "2차전지" and group_of("KODEX 반도체레버리지") is None
       and group_of("TIGER 12월자동연장금융채(AA-이상)액티브") is None and group_of("TIGER 미국반도체") is None and group_of("KODEX 200") is None, "이름 매핑")
    D, E = 120, 4
    C = np.full((D, E), 100.0)
    O = C.copy()
    NAV = C.copy()
    SH = np.full((D, E), 1e9)
    NA = C * SH
    SH[60:, 0] = 1.5e9                       # ETF 0 에 유입(좌수 50% 증가)
    NA = C * SH
    C[60:, :] *= 1.10                        # 60일부터 +10%
    O[61:] = C[61:]
    NAV = C.copy()
    NA = C * SH
    A = {"C": C, "O": O, "NAV": NAV, "SH": SH, "NA": NA, "eg": np.array([0, 0, 0, 1])}
    b = basket(A, 62, LAG20, 0)
    ok(b is not None and len(b[0]) == 3, "ETF 3개 묶음")
    _, ret, flow = b
    ok(abs(ret - 0.10) < 1e-9 and flow > 0, f"가격 {ret} 유입 {flow}")
    exp_flow = (0.5e9 * 110.0) / (3 * 100.0 * 1e9)
    ok(abs(flow - exp_flow) < 1e-9, f"유입 계산 {flow} vs {exp_flow}")
    ok(basket(A, 62, LAG20, 1) is None, "ETF 3개 미만 업종은 제외")
    ok(state_of(0.1, 0.2) == "상승·유입" and state_of(-0.1, -0.2) == "하락·유출", "4칸")
    A2 = {k: (v.copy() if hasattr(v, "copy") else v) for k, v in A.items()}
    C2 = A2["C"]; C2[70:, :3] *= 1.05
    f = etf_fwd(A2, 62, np.array([0, 1, 2]))
    ok(not np.isnan(f) and f > 0.04, f"ETF 진입 후 성과 {f}")
    ok(np.isnan(etf_fwd(A, D - 5, np.array([0, 1, 2]))), "데이터 끝을 넘으면 NaN")
    ok(abs(net_diff_bp(0.01, 0.0) - (0.01 - 0.0005 + 0.00335)) < 1e-12 and abs(net_diff_bp(0.0, 0.0) - 0.00285) < 1e-12, "E3 비용 후 차이")
    a = np.arange(50, dtype=float) + np.random.default_rng(1).normal(0, 0.1, 50)
    ok(lag_corr(np.tile(a, 3), np.tile(a, 3), 0) > 0.99, "시차 상관")
    print("selftest OK - run_sector_etf_study")
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
    A, codes, names = load_etf(dates, groups)
    print(f"A2a {dates[0]} ~ {dates[-1]} · ETF {len(codes)}개 중 업종 매핑 {int((A['eg'] >= 0).sum())}개\n")
    E1 = analysis_E1(A, C, O, elig, dates, ng)
    E3 = analysis_E3(A, C, O, elig, gid, rel, dates, ng)
    if a.forward_report:
        months = sorted({e["date"][:7] for e in E1 + E3 if e["date"] >= rs.FREEZE})
        f1 = [e for e in E1 if e["date"] >= rs.FREEZE]
        f3 = [e for e in E3 if e["date"] >= rs.FREEZE]
        print(f"### forward (동결일 {rs.FREEZE} 이후) 월별")
        print_E1(f1, months or ["(아직 없음)"], "월별"); print_E3(f3, months or ["(아직 없음)"], "월별")
        return 0
    years = sorted({d[:4] for d in dates})
    mons = [f"2026-{m:02d}" for m in range(4, 10)]
    print("### 연도별")
    print_E1(E1, years, "연도별"); print_E3(E3, years, "연도별")
    print("\nETF 묶음이 만들어진 업종 수(연도별 E1 관측 기준): " + " · ".join(f"{y} {len({e['g'] for e in E1 if e['date'].startswith(y)})}" for y in years))
    print_E2(analysis_E2a(A, R, elig, gid, dates, ng), analysis_E2b(A, rel, dates, ng), years)
    print("\n### 2026년 4~9월 월별")
    print_E1([e for e in E1 if e["date"] >= "2026-04-01"], mons, "월별")
    print_E3([e for e in E3 if e["date"] >= "2026-04-01"], mons, "월별")
    return 0


if __name__ == "__main__":
    sys.exit(main())
