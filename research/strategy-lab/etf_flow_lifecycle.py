#!/usr/bin/env python3
"""국내 섹터 ETF 의 '돈의 생애주기' — 대응 ETF 버전(실행 전 고정 설계, 2026-09-30). 자문 아님.

    python research/strategy-lab/etf_flow_lifecycle.py --selftest
    python research/strategy-lab/etf_flow_lifecycle.py
    -> findings/etf-flow-lifecycle-results-2026-09.json · reports/2026-09-etf-flows/etf-flow-lifecycle.xlsx · chart PNG

앞선 주식 그룹 시험(sector_flow_calendar_excel.py)과 같은 질문을 **실제 매매 가능한 ETF** 로 다시 한다. 그룹 수익이 아니라 ETF 종가 수익이다.
- 자금 흐름 F = 설정·환매 = (상장좌수 변화 20세션) x NAV / 20세션 전 순자산. (ETF 에는 외국인·기관 순매수 자료가 없다 — 이쪽이 실제 자금 유입에 가깝다. LP 헤지 설정이 섞일 수 있다.)
- 테마 9~15개: 국내주식형 ETF 이름 규칙(우선순위 순, 첫 일치): 반도체 · 2차전지 · 바이오·헬스케어(바이오|헬스케어|제약) · 금융(은행|증권|보험|금융) · 자동차 · 철강·화학(철강|소재|화학) ·
  건설 · 조선·운송(조선|해운|운송) · 방산·우주(방산|우주|항공) · 미디어·게임(게임|미디어|콘텐츠|엔터) · IT·소프트웨어(IT|소프트웨어|인터넷|플랫폼) · 전력·인프라(원자력|전력|전기|인프라|신재생|태양광|풍력|친환경) · 소비재(소비|음식료|화장품).
  제외 이름: 레버리지·인버스·2X·커버드콜·혼합·채권·그룹·코스닥·미국·차이나·글로벌·일본·인도·베트남·리츠·배당(지수형 '200' 자체는 테마 규칙에 안 걸려 자연 제외, '200 건설' 같은 섹터 ETF 는 포함). 분류 = 유니버스 csv 의 class 가 '국내주식형' 인 것만.
- 적격(월초 신호일 D): 상장 60세션 이상 · 순자산 >= 100억 · 최근 20세션 평균 거래대금 >= 1억. 테마 F = 적격 ETF 들의 (좌수 변화 x NAV 합) / (20세션 전 순자산 합). 테마 수익 = 그 달 순자산 최대 ETF 의 수익.
  테마가 8개 미만인 달은 관측하지 않는다.
- 수익: 신호일 다음 세션 종가 → 다음 달 신호일 다음 세션 종가(주식 시험과 같은 규약). 초과수익 = 테마 수익 - 그 달 적격 테마 평균.
- 진입 = 월초 신호일에 F 순위가 새로 상위 3 (전월은 상위 3 밖). 퇴출 규칙 8개(주식 시험과 동일): 보유 1·2·3·6·12개월 · F<0 첫 달 · F 순위가 그 달 테마 수의 절반 밖으로 밀리는 첫 달 · 거래대금 비중 3개월 변화<0 첫 달. 최대 12개월.
- 지표: 사건별 월평균 초과수익(총·비용 후: 편도 10bp x2 / 보유월수 차감), 승률, 평균 보유월. 12개월 블록 부트스트랩 2,000회. 난수 진입 플라시보 300회의 p95 를 바닥선으로.
- 판정(결과 전 고정): 관측 60개월 미만 또는 진입 사건 100건 미만이면 **INCONCLUSIVE(표본 부족), 방향만 기록**. 그 이상이면 (a) 보유 3개월 평균이 플라시보 p95 초과이고 부트스트랩 하한 > 0 이면 '진입 우위 있음',
  (b) 수급 기반 퇴출 규칙이 보유 3개월 대비 짝지은 차이 하한 > 0 이면 '수급 퇴출이 낫다'. 결과를 보고 테마·창·규칙을 바꾸지 않는다.
- 한계: ETF 이력이 짧아(테마 8개 이상 월이 많지 않을 수 있음) 표본 부족 가능성이 크다. 순자산 최대 ETF 로 수익을 잰다(해당 ETF 의 보수·괴리 포함, 분배금 제외).
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

import numpy as np
import pandas as pd

LAB = Path(__file__).resolve().parent
sys.path.insert(0, str(LAB))
from sector_step0 import nw_tstat  # noqa: E402

RES = LAB / "findings" / "etf-flow-lifecycle-results-2026-09.json"
OUT = LAB / "reports" / "2026-09-etf-flows"
THEMES = [("반도체", r"반도체"), ("2차전지", r"2차전지|배터리"), ("바이오·헬스케어", r"바이오|헬스케어|제약"), ("금융", r"은행|증권|보험|금융"),
          ("자동차", r"자동차|모빌리티"), ("철강·화학", r"철강|소재|화학"), ("건설", r"건설"), ("조선·운송", r"조선|해운|운송"),
          ("방산·우주", r"방산|우주|항공"), ("미디어·게임", r"게임|미디어|콘텐츠|엔터"), ("IT·소프트웨어", r"IT|소프트웨어|인터넷|플랫폼"),
          ("전력·인프라", r"원자력|전력|전기|인프라|신재생|태양광|풍력|친환경"), ("소비재", r"소비|음식료|화장품")]
EXCL = re.compile(r"레버리지|인버스|2X|커버드콜|혼합|채권|그룹|코스닥|미국|차이나|글로벌|일본|인도|베트남|리츠|배당")
COST_SIDE = 0.001
RULES = ["보유1", "보유2", "보유3", "보유6", "보유12", "F<0", "F순위>절반", "DTV3<0"]
MAXH = 12
MIN_THEMES = 8


def theme_of(name: str):
    if EXCL.search(name or ""):
        return None
    for t, rx in THEMES:
        if re.search(rx, name):
            return t
    return None


def load():
    uni = pd.read_csv(LAB / "findings" / "etf-cross-section-universe-2026-09.csv", dtype=str, encoding="utf-8").set_index("code")
    ok = set(uni.index[uni["class"] == "국내주식형"])
    recs = []
    for f in sorted((LAB / "data" / "etf-ohlc").glob("*.jsonl")):
        with open(f, encoding="utf-8") as fh:
            for line in fh:
                if '"ISU_CD"' not in line:
                    continue
                d = json.loads(line)
                if d["ISU_CD"] not in ok:
                    continue
                try:
                    recs.append((d["BAS_DD"], d["ISU_CD"], d["ISU_NM"], float(d["TDD_CLSPRC"]), float(d["NAV"]), float(d["ACC_TRDVAL"]),
                                 float(d["INVSTASST_NETASST_TOTAMT"]), float(d["LIST_SHRS"])))
                except (ValueError, KeyError):
                    continue
    df = pd.DataFrame(recs, columns=["d", "code", "name", "px", "nav", "tv", "na", "sh"])
    df["d"] = pd.to_datetime(df["d"])
    df = df.drop_duplicates(["d", "code"])
    df["theme"] = df["name"].map(theme_of)
    return df[df["theme"].notna()].copy()


def build(df: pd.DataFrame):
    dates = pd.DatetimeIndex(sorted(df["d"].unique()))
    codes = sorted(df["code"].unique())
    piv = lambda c: df.pivot(index="d", columns="code", values=c).reindex(index=dates, columns=codes)
    PX, NAV, TV, NA, SH = piv("px"), piv("nav"), piv("tv"), piv("na"), piv("sh")
    theme = df.groupby("code")["theme"].agg(lambda s: s.mode().iloc[0])
    name = df.groupby("code")["name"].last()
    # 월초 신호일 = 각 달 첫 거래일, 진입일 = 그 다음 거래일
    first = pd.Series(dates, index=dates).groupby(dates.to_period("M")).first()
    pos = {d: i for i, d in enumerate(dates)}
    return dates, codes, PX, NAV, TV, NA, SH, theme, name, first, pos


def monthly(df: pd.DataFrame):
    dates, codes, PX, NAV, TV, NA, SH, theme, name, first, pos = build(df)
    themes = [t for t, _ in THEMES]
    tv20 = TV.rolling(20, min_periods=15).mean()
    rows = []
    months = list(first.index)
    for mi, m in enumerate(months[:-1]):
        D = first[m]
        i = pos[D]
        if i < 60 or i + 1 >= len(dates):
            continue
        E = dates[i + 1]
        m2 = months[mi + 1]
        E2 = dates[pos[first[m2]] + 1] if pos[first[m2]] + 1 < len(dates) else None
        if E2 is None:
            continue
        elig = (PX.iloc[i].notna() & (NA.iloc[i] >= 1e10) & (tv20.iloc[i] >= 1e8) & (PX.iloc[i - 60].notna()))
        fl = (SH.iloc[i] - SH.iloc[i - 20]) * NAV.iloc[i]
        base = NA.iloc[i - 20]
        for t in themes:
            cs = [c for c in codes if elig[c] and theme[c] == t]
            if not cs:
                continue
            rep = max(cs, key=lambda c: NA.iloc[i][c])
            ok = [c for c in cs if np.isfinite(fl[c]) and np.isfinite(base[c]) and base[c] > 0]
            F = float(fl[ok].sum() / base[ok].sum()) if ok else np.nan
            ret = float(PX.iloc[pos[E2]][rep] / PX.iloc[pos[E]][rep] - 1) if (np.isfinite(PX.iloc[pos[E2]][rep]) and np.isfinite(PX.iloc[pos[E]][rep])) else np.nan
            rows.append(dict(month=str(m), D=D, theme=t, F=F, tv=float(tv20.iloc[i][cs].sum()), ret=ret, rep=name[rep], n_etf=len(cs), na=float(NA.iloc[i][cs].sum())))
    return pd.DataFrame(rows)


def matrices(mdf: pd.DataFrame):
    F = mdf.pivot(index="month", columns="theme", values="F")
    TVm = mdf.pivot(index="month", columns="theme", values="tv")
    X = mdf.pivot(index="month", columns="theme", values="ret")
    valid = F.notna().sum(axis=1) >= MIN_THEMES
    F, TVm, X = F[valid], TVm[valid], X[valid]
    S = TVm.div(TVm.sum(axis=1), axis=0)
    D = S - S.shift(3)
    n = F.notna().sum(axis=1)
    rk = F.rank(axis=1, ascending=False, method="first")
    return F.index.tolist(), list(F.columns), F.values, S.values, D.values, X.values, rk.values, n.values


def hold_months(rule, t, g, F, D, rk, n, T):
    if rule.startswith("보유"):
        return int(rule[2:])
    for h in range(1, MAXH + 1):
        if t + h >= T:
            return h
        if rule == "F<0" and not (F[t + h, g] >= 0):
            return h
        if rule == "F순위>절반" and not (rk[t + h, g] <= n[t + h] / 2):
            return h
        if rule == "DTV3<0" and not (D[t + h, g] >= 0):
            return h
    return MAXH


def episode(X, t, g, h, cost=False):
    seg = X[t:t + h]
    if np.isnan(seg[:, g]).any():
        return np.nan
    bench = np.nanmean(seg, axis=1)
    e = (np.prod(1 + seg[:, g]) - np.prod(1 + bench)) / h
    return e - (2 * COST_SIDE / h if cost else 0.0)


def run_rules(entries, X, F, D, rk, n, T):
    g_, n_, h_ = {r: [] for r in RULES}, {r: [] for r in RULES}, {r: [] for r in RULES}
    for t, g in entries:
        for r in RULES:
            h = hold_months(r, t, g, F, D, rk, n, T)
            g_[r].append(episode(X, t, g, h))
            n_[r].append(episode(X, t, g, h, True))
            h_[r].append(h)
    f = lambda d: {r: np.array(v, float) for r, v in d.items()}
    return f(g_), f(n_), f(h_)


def lifecycle(mdf: pd.DataFrame):
    months, themes, F, S, D, X, rk, n = matrices(mdf)
    T, N = F.shape
    ent = [(t, g) for t in range(1, T - MAXH - 1) for g in range(N) if rk[t, g] <= 3 and not (rk[t - 1, g] <= 3)]
    valid = [(t, g) for t in range(1, T - MAXH - 1) for g in range(N) if not np.isnan(rk[t, g])]
    out = dict(months=T, first=months[0], last=months[-1], n_entries=len(ent), themes=themes)
    if T < 60 or len(ent) < 100:
        out["inconclusive"] = True
    else:
        out["inconclusive"] = False
    xs = X - np.nanmean(X, axis=1, keepdims=True)
    prof = {}
    for k in range(-3, 7):
        f, r, top, cx = [], [], [], []
        for t, g in ent:
            if 0 <= t + k < T:
                f.append(F[t + k, g]); r.append(rk[t + k, g]); top.append(float(rk[t + k, g] <= 3))
            if k >= 0 and t + k < T:
                seg = xs[t:t + k + 1, g]
                cx.append(np.prod(1 + seg) - 1 if not np.isnan(seg).any() else np.nan)
            if k < 0 and t + k >= 0:
                seg = xs[t + k:t, g]
                cx.append(np.prod(1 + seg) - 1 if not np.isnan(seg).any() else np.nan)
        prof[str(k)] = dict(F=float(np.nanmean(f)), rank=float(np.nanmean(r)), still_top3=float(np.nanmean(top)), cum_excess=float(np.nanmean(cx)), n=len(f))
    out["profile"] = prof
    ex, exn, hh = run_rules(ent, X, F, D, rk, n, T)
    rng = np.random.default_rng(31)
    ent_t = np.array([t for t, g in ent])
    base3 = ex["보유3"]
    boots = {r: [] for r in RULES}
    diffs = {r: [] for r in RULES}
    nb = int(np.ceil(T / 12))
    for _ in range(2000):
        st = rng.integers(0, T, nb)
        cnt = np.bincount(np.concatenate([(s0 + np.arange(12)) % T for s0 in st])[:T], minlength=T)
        w = cnt[ent_t].astype(float)
        for r in RULES:
            ok = ~np.isnan(ex[r]) & ~np.isnan(base3)
            ww = w * ok
            if ww.sum() == 0:
                continue
            boots[r].append(np.nansum(ex[r] * ww) / ww.sum())
            diffs[r].append(np.nansum((ex[r] - base3) * ww) / ww.sum())
    plc = {r: [] for r in RULES}
    for _ in range(300):
        idx = rng.choice(len(valid), size=len(ent), replace=False)
        e2, _, _ = run_rules([valid[i] for i in idx], X, F, D, rk, n, T)
        for r in RULES:
            plc[r].append(np.nanmean(e2[r]))
    res = {}
    for r in RULES:
        v = ex[r][~np.isnan(ex[r])]
        vn = exn[r][~np.isnan(exn[r])]
        res[r] = dict(n=int(len(v)), gross_bp=float(v.mean() * 1e4), net_bp=float(vn.mean() * 1e4), ci=[float(np.quantile(boots[r], .025) * 1e4), float(np.quantile(boots[r], .975) * 1e4)],
                      hit=float((v > 0).mean()), avg_hold=float(hh[r].mean()), placebo_p95_bp=float(np.quantile(plc[r], .95) * 1e4),
                      diff_vs_hold3_bp=(None if r == "보유3" else float(np.mean(diffs[r]) * 1e4)),
                      diff_ci=(None if r == "보유3" else [float(np.quantile(diffs[r], .025) * 1e4), float(np.quantile(diffs[r], .975) * 1e4)]))
    out["rules"] = res
    out["entry_edge"] = bool(res["보유3"]["gross_bp"] > res["보유3"]["placebo_p95_bp"] and res["보유3"]["ci"][0] > 0)
    out["better_flow_exits"] = [r for r in RULES if r.startswith(("F", "DTV")) and res[r]["diff_ci"] and res[r]["diff_ci"][0] > 0]
    dur = []
    for t, g in ent:
        h = 0
        while t + h < T and rk[t + h, g] <= 3:
            h += 1
        dur.append(h)
    out["top3_run_mean"], out["top3_run_median"] = float(np.mean(dur)), float(np.median(dur))
    out["chance_top3"] = float(np.mean(3.0 / n))
    # 기록: 월별 IC(F -> 다음 달 수익), 전/후반
    ics = {}
    for t in range(T):
        f, x = F[t], X[t]
        ok = ~np.isnan(f) & ~np.isnan(x)
        if ok.sum() >= MIN_THEMES:
            ics[months[t]] = pd.Series(f[ok]).corr(pd.Series(x[ok]), method="spearman")
    ic = pd.Series(ics)
    half = len(ic) // 2
    out["ic"] = dict(mean=float(ic.mean()), t=float(nw_tstat(ic.values)), n=len(ic), first_half=float(ic.iloc[:half].mean()), second_half=float(ic.iloc[half:].mean()))
    return out, (months, themes, F, S, X)


def current_snapshot(df: pd.DataFrame):
    dates, codes, PX, NAV, TV, NA, SH, theme, name, first, pos = build(df)
    i = len(dates) - 1
    tv20 = TV.rolling(20, min_periods=15).mean()
    elig = (PX.iloc[i].notna() & (NA.iloc[i] >= 1e10) & (tv20.iloc[i] >= 1e8))
    fl = (SH.iloc[i] - SH.iloc[i - 20]) * NAV.iloc[i]
    base = NA.iloc[i - 20]
    tv_tot = float(tv20.iloc[i][elig].sum())
    rows = []
    for t, _ in THEMES:
        cs = [c for c in codes if elig[c] and theme[c] == t]
        if not cs:
            continue
        ok = [c for c in cs if np.isfinite(fl[c]) and np.isfinite(base[c]) and base[c] > 0]
        rep = max(cs, key=lambda c: NA.iloc[i][c])
        r1 = PX.iloc[i][rep] / PX.iloc[i - 20][rep] - 1 if np.isfinite(PX.iloc[i - 20][rep]) else np.nan
        r3 = PX.iloc[i][rep] / PX.iloc[i - 60][rep] - 1 if np.isfinite(PX.iloc[i - 60][rep]) else np.nan
        sh_now = float(tv20.iloc[i][cs].sum()) / tv_tot
        i3 = i - 60
        el3 = (PX.iloc[i3].notna() & (NA.iloc[i3] >= 1e10) & (tv20.iloc[i3] >= 1e8))
        c3 = [c for c in codes if el3[c] and theme[c] == t]
        tv3 = float(tv20.iloc[i3][el3].sum())
        sh_3 = float(tv20.iloc[i3][c3].sum()) / tv3 if tv3 > 0 and c3 else np.nan
        rows.append(dict(테마=t, 대표ETF=name[rep], ETF수=len(cs), 순자산_억=float(NA.iloc[i][cs].sum() / 1e8), 순유입_20일_억=float(fl[ok].sum() / 1e8) if ok else np.nan,
                         순유입률_20일=float(fl[ok].sum() / base[ok].sum()) if ok else np.nan, 거래대금비중=sh_now, 비중_3개월전=sh_3, 수익_1개월=float(r1), 수익_3개월=float(r3)))
    return str(dates[i].date()), pd.DataFrame(rows).sort_values("순유입률_20일", ascending=False)


def write_outputs(res, mats, snap_date, snap, mdf):
    from openpyxl import Workbook
    from openpyxl.chart import LineChart, Reference
    from openpyxl.formatting.rule import ColorScaleRule
    from openpyxl.styles import Font, PatternFill
    from openpyxl.utils import get_column_letter
    OUT.mkdir(parents=True, exist_ok=True)
    months, themes, F, S, X = mats
    wb = Workbook()
    hdr = PatternFill("solid", fgColor="1F3864")

    def head(ws, r, cols):
        for j, h in enumerate(cols, 1):
            c = ws.cell(row=r, column=j, value=h)
            c.fill, c.font = hdr, Font(color="FFFFFF", bold=True)
    ws = wb.active
    ws.title = "요약"
    ws["A1"] = f"ETF 돈의 생애주기 — 관측 {res['months']}개월({res['first']}~{res['last']}), 진입 사건 {res['n_entries']}건, 테마 {len(res['themes'])}개"
    ws["A1"].font = Font(bold=True)
    ws["A2"] = "표본 부족(INCONCLUSIVE)" if res["inconclusive"] else f"판정: 진입 우위 {'있음' if res['entry_edge'] else '없음'} · 수급 기반 퇴출이 보유3보다 나음 {res['better_flow_exits'] or '없음'}"
    head(ws, 4, ["규칙", "사건수", "총 월평균 초과(bp)", "비용후(bp)", "95% 하한", "95% 상한", "승률", "평균 보유", "난수 p95(bp)", "보유3 대비 차이", "하한", "상한"])
    for i, r in enumerate(RULES, 5):
        v = res["rules"][r]
        vals = [r, v["n"], v["gross_bp"], v["net_bp"], v["ci"][0], v["ci"][1], v["hit"], v["avg_hold"], v["placebo_p95_bp"], v["diff_vs_hold3_bp"],
                v["diff_ci"][0] if v["diff_ci"] else None, v["diff_ci"][1] if v["diff_ci"] else None]
        for j, x in enumerate(vals, 1):
            c = ws.cell(row=i, column=j, value=x)
            if j == 7:
                c.number_format = "0%"
            elif j >= 3 and x is not None and j != 8:
                c.number_format = "0.0"
    r0 = 15
    head(ws, r0, ["k(월)", "평균 F(순유입률)", "평균 F순위", "계속 상위3", "누적 초과수익", "사건수"])
    prof = sorted(res["profile"].items(), key=lambda kv: int(kv[0]))
    for i, (k, v) in enumerate(prof, r0 + 1):
        for j, x in enumerate([int(k), v["F"], v["rank"], v["still_top3"], v["cum_excess"], v["n"]], 1):
            c = ws.cell(row=i, column=j, value=x)
            if j in (2, 5):
                c.number_format = "0.0%"
    ln = LineChart()
    ln.title = "진입 전후 평균 순유입률 (설정·환매)"
    ln.add_data(Reference(ws, min_col=2, min_row=r0, max_row=r0 + len(prof)), titles_from_data=True)
    ln.set_categories(Reference(ws, min_col=1, min_row=r0 + 1, max_row=r0 + len(prof)))
    ln.height, ln.width = 8, 16
    ws.add_chart(ln, "N4")
    ln2 = LineChart()
    ln2.title = "진입 전후 평균 누적 초과수익"
    ln2.add_data(Reference(ws, min_col=5, min_row=r0, max_row=r0 + len(prof)), titles_from_data=True)
    ln2.set_categories(Reference(ws, min_col=1, min_row=r0 + 1, max_row=r0 + len(prof)))
    ln2.height, ln2.width = 8, 16
    ws.add_chart(ln2, "N22")
    for j in range(1, 13):
        ws.column_dimensions[get_column_letter(j)].width = 15
    # 월별 순유입률
    ws2 = wb.create_sheet("월별_순유입률")
    head(ws2, 1, ["월"] + themes)
    for i, m in enumerate(months, 2):
        ws2.cell(row=i, column=1, value=m)
        for j, v in enumerate(F[i - 2], 2):
            if np.isfinite(v):
                ws2.cell(row=i, column=j, value=float(v)).number_format = "0.0%"
    ws2.conditional_formatting.add(f"B2:{get_column_letter(1 + len(themes))}{1 + len(months)}",
                                   ColorScaleRule(start_type="num", start_value=-0.1, start_color="F8696B", mid_type="num", mid_value=0, mid_color="FFFFFF", end_type="num", end_value=0.1, end_color="63BE7B"))
    ws2.freeze_panes = "B2"
    ws3 = wb.create_sheet("월별_테마수익")
    head(ws3, 1, ["월"] + themes)
    for i, m in enumerate(months, 2):
        ws3.cell(row=i, column=1, value=m)
        for j, v in enumerate(X[i - 2], 2):
            if np.isfinite(v):
                ws3.cell(row=i, column=j, value=float(v)).number_format = "0.0%"
    ws3.conditional_formatting.add(f"B2:{get_column_letter(1 + len(themes))}{1 + len(months)}",
                                   ColorScaleRule(start_type="num", start_value=-0.15, start_color="F8696B", mid_type="num", mid_value=0, mid_color="FFFFFF", end_type="num", end_value=0.15, end_color="63BE7B"))
    ws3.freeze_panes = "B2"
    ws4 = wb.create_sheet(f"현재({snap_date})")
    ws4["A1"] = f"기준일 {snap_date} — 최근 20세션 설정·환매 순유입(억원)과 거래대금 비중. 대표ETF = 테마 내 순자산 최대."
    ws4["A1"].font = Font(bold=True)
    head(ws4, 3, list(snap.columns))
    for i, row in enumerate(snap.itertuples(index=False), 4):
        for j, v in enumerate(row, 1):
            c = ws4.cell(row=i, column=j, value=v if not (isinstance(v, float) and np.isnan(v)) else None)
            if j in (6, 7, 8, 9, 10):
                c.number_format = "0.0%"
            elif j in (4, 5):
                c.number_format = "#,##0"
    for j in range(1, 11):
        ws4.column_dimensions[get_column_letter(j)].width = 16
    ws5 = wb.create_sheet("테마별_ETF목록")
    head(ws5, 1, ["테마", "대표ETF(가장 최근 월)", "월수(대표로 선택)"])
    rep = mdf.groupby(["theme", "rep"]).size().reset_index(name="n").sort_values(["theme", "n"], ascending=[True, False])
    for i, row in enumerate(rep.itertuples(index=False), 2):
        for j, v in enumerate(row, 1):
            ws5.cell(row=i, column=j, value=v)
    ws5.column_dimensions["A"].width = 16
    ws5.column_dimensions["B"].width = 40
    wb.save(OUT / "etf-flow-lifecycle.xlsx")


def main():
    df = load()
    mdf = monthly(df)
    res, mats = lifecycle(mdf)
    sd, snap = current_snapshot(df)
    res["current"] = dict(date=sd, table=snap.replace({np.nan: None}).to_dict("records"))
    RES.write_text(json.dumps(res, ensure_ascii=False, indent=1, default=float), encoding="utf-8")
    write_outputs(res, mats, sd, snap, mdf)
    print("months", res["months"], res["first"], res["last"], "entries", res["n_entries"], "inconclusive", res["inconclusive"], "themes", len(res["themes"]))


def selftest():
    assert theme_of("KODEX 반도체") == "반도체" and theme_of("TIGER 2차전지테마") == "2차전지" and theme_of("KODEX 200") is None
    assert theme_of("KODEX 반도체레버리지") is None and theme_of("TIGER 미국필라델피아반도체나스닥") is None and theme_of("TIGER 200 IT") == "IT·소프트웨어"
    T, N = 40, 10
    rng = np.random.default_rng(0)
    F = rng.normal(0, .05, (T, N))
    rk = pd.DataFrame(F).rank(axis=1, ascending=False, method="first").values
    n = np.full(T, N)
    assert hold_months("보유6", 3, 2, F, F, rk, n, T) == 6 and 1 <= hold_months("F<0", 3, 2, F, F, rk, n, T) <= 12
    X = np.zeros((10, 3))
    assert abs(episode(X, 2, 1, 4)) < 1e-12 and abs(episode(X, 2, 1, 4, True) + 2 * COST_SIDE / 4) < 1e-12
    print("selftest ok")


if __name__ == "__main__":
    selftest() if "--selftest" in sys.argv else main()
