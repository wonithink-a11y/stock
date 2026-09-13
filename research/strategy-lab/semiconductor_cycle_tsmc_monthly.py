#!/usr/bin/env python3
"""반도체 사이클 연구 Stage 2 — TSMC 월간매출 vs SOXL 선행수익률.

사용자 GO(2026-09-13). Stage 1(DART 분기, 삼성전자·SK하이닉스)이 n=36~18로
통계 결론을 못 낸 것을, 월간 빈도(TSMC)로 표본을 늘려 재검증한다.

★ 수집 방법에 대한 중요한 사실: `investor.tsmc.com`은 Cloudflare 봇 차단이
걸려 있다. `requests`로 첫 호출은 통과했지만 바로 다음 호출부터 "Just a
moment..." JS 챌린지 페이지를 돌려줬다(실측 2026-09-13) — 즉 이 스크립트가
매번 재실행 시 자동으로 데이터를 다시 받아올 수 없다. Cloudflare 우회
시도(TLS 지문 위장, 챌린지 자동풀이 등)는 하지 않는다 — 그건 접근제어를
피해가는 것이지 기술적 불편 해소가 아니다. 대신 Claude Browser 패널(실제
브라우저, 챌린지를 정상적으로 통과)로 2013~2026년 14개 연도 페이지를 한 번
수동 조회해 얻은 값을 아래 TSMC_DATA에 스냅샷으로 고정했다(출처:
investor.tsmc.com/english/monthly-revenue/{year}, 조회일 2026-09-13).
갱신하려면 같은 방식(브라우저로 직접 조회)으로 다시 받아야 한다 — 이건
DART/FRED처럼 매번 재현 가능한 자동 수집기가 아니라 스냅샷이다.

PIT: 발표일 데이터를 스크레이핑하지 못했다(financial-calendar 페이지는
Cloudflare+JS 렌더링이라 별도이고, 이번 스코프 밖). 대신 실측한 공표
관례(2025~2026 캘린더 확인: 정규월 8~13일, 예외 없이 항상 다음달 10일
전후)를 보수적으로 반영해 **월말 + 15일**을 availableFrom으로 가정한다 —
관측된 최대 지연(13일)보다 며칠 더 늦게 잡아 look-ahead를 만들지 않는
쪽으로 치우친 가정이다(기존 macro_common.py의 CPI 등 발표지연 관례와 동일
원칙).

    python research/strategy-lab/semiconductor_cycle_tsmc_monthly.py
"""
from pathlib import Path

import numpy as np
import pandas as pd
from scipy import stats

ROOT = Path(__file__).resolve().parent
OUT_DIR = ROOT / "data" / "semiconductor-cycle"
PIT_LAG_DAYS = 15  # 월말 기준, 실측 최대 공표지연(13일)보다 보수적으로 며칠 더

# (year: [(revenue_ntd_million, reported_yoy_pct), ...])  월 순서 = 1월부터
# 출처: investor.tsmc.com/english/monthly-revenue/{year}, 조회 2026-09-13 (Claude Browser 패널)
# reported_yoy_pct는 TSMC가 표에 직접 게시한 값 — 검산용(§ verify_reported_yoy).
TSMC_DATA = {
    2013: [(47439, 37.1), (41182, 21.5), (44134, 18.9), (50071, 23.5), (51788, 17.2), (54028, 24.3),
           (52103, 7.3), (55091, 11.2), (55382, 27.6), (51795, 3.6), (44330, 0.1), (49681, 33.7)],
    2014: [(51430, 8.4), (46829, 13.7), (49956, 13.2), (61887, 23.6), (60789, 17.4), (60344, 11.7),
           (64925, 24.6), (69279, 25.8), (74846, 35.1), (80736, 55.9), (72275, 63.0), (69510, 39.9)],
    2015: [(87120, 69.4), (62645, 33.8), (72269, 44.7), (75330, 21.7), (70155, 15.4), (59955, -0.6),
           (80953, 24.7), (67038, -3.2), (64514, -13.8), (81743, 1.2), (63428, -12.2), (58347, -16.1)],
    2016: [(70855, -18.7), (59551, -4.9), (73089, 1.1), (66843, -11.3), (73576, 4.9), (81391, 35.8),
           (76392, -5.6), (94311, 40.7), (89703, 39.0), (91085, 11.4), (93030, 46.7), (78112, 33.9)],
    2017: [(76616, 8.1), (71423, 19.9), (85875, 17.5), (56872, -14.9), (72796, -1.1), (84187, 3.4),
           (71611, -6.3), (91917, -2.5), (88579, -1.3), (94520, 3.8), (93153, 0.1), (89897, 15.1)],
    2018: [(79741, 4.1), (64641, -9.5), (103697, 20.8), (81870, 44.0), (80969, 11.2), (70438, -16.3),
           (74371, 3.9), (91055, -0.9), (94922, 7.2), (101550, 7.4), (98389, 5.6), (89831, -0.1)],
    2019: [(78094, -2.1), (60889, -5.8), (79722, -23.1), (74694, -8.8), (80437, -0.7), (85868, 21.9),
           (84758, 14.0), (106118, 16.5), (102170, 7.6), (106040, 4.4), (107884, 9.7), (103313, 15.0)],
    2020: [(103683, 32.8), (93394, 53.4), (113520, 42.4), (96002, 28.5), (93819, 16.6), (120878, 40.8),
           (105963, 25.0), (122878, 15.8), (127585, 24.9), (119303, 12.5), (124865, 15.7), (117365, 13.6)],
    2021: [(126749, 22.2), (106534, 14.1), (129127, 13.7), (111315, 16.0), (112360, 19.8), (148471, 22.8),
           (124558, 17.5), (137427, 11.8), (152685, 19.7), (134539, 12.8), (148268, 18.7), (155382, 32.4)],
    2022: [(172176, 35.8), (146933, 37.9), (171967, 33.2), (172561, 55.0), (185705, 65.3), (175874, 18.5),
           (186763, 49.9), (218132, 58.7), (208248, 36.4), (210266, 56.3), (222706, 50.2), (192560, 23.9)],
    2023: [(200051, 16.2), (163174, 11.1), (145408, -15.4), (147900, -14.3), (176537, -4.9), (156404, -11.1),
           (177616, -4.9), (188686, -13.5), (180430, -13.4), (243203, 15.7), (206026, -7.5), (176300, -8.4)],
    2024: [(215785, 7.9), (181648, 11.3), (195211, 34.3), (236021, 59.6), (229620, 30.1), (207869, 32.9),
           (256953, 44.7), (250866, 33.0), (251873, 39.6), (314240, 29.2), (276058, 34.0), (278163, 57.8)],
    2025: [(293288, 35.9), (260009, 43.1), (285957, 46.5), (349567, 48.1), (320516, 39.6), (263709, 26.9),
           (323166, 25.8), (335772, 33.8), (330980, 31.4), (367473, 16.9), (343614, 24.5), (335003, 20.4)],
    2026: [(401255, 36.8), (317657, 22.2), (415191, 45.2), (410726, 17.5), (416975, 30.1), (442680, 67.9),
           (467580, 44.7), (514806, 53.3)],  # Jan~Aug만 공시됨(조회일 기준)
}


def build_monthly() -> pd.DataFrame:
    rows = []
    for year, entries in TSMC_DATA.items():
        for i, (rev, yoy_reported) in enumerate(entries):
            month = i + 1
            period_end = pd.Timestamp(year=year, month=month, day=1) + pd.offsets.MonthEnd(0)
            rows.append({"year": year, "month": month, "periodEnd": period_end,
                         "revenueNtdMn": rev, "yoyReported": yoy_reported,
                         "availableFrom": period_end + pd.Timedelta(days=PIT_LAG_DAYS)})
    df = pd.DataFrame(rows).sort_values("periodEnd").reset_index(drop=True)
    df["rev_yoy"] = df["revenueNtdMn"].pct_change(12) * 100
    df["rev_qoq3m"] = df["revenueNtdMn"].pct_change(3) * 100
    df["rev_chg6m"] = df["revenueNtdMn"].pct_change(6) * 100
    df["rev_yoy_accel"] = df["rev_yoy"].diff(1)  # YoY 성장률 자체의 전월대비 가속/감속
    df["rev_yoy_roll3m"] = df["rev_yoy"].rolling(3).mean()
    return df


def verify_reported_yoy(df: pd.DataFrame) -> None:
    """수집값 검산 — 내가 계산한 YoY가 TSMC 공식 게시 YoY와 맞는지 (사용자 지시 §3)."""
    sub = df.dropna(subset=["rev_yoy", "yoyReported"])
    diff = (sub["rev_yoy"] - sub["yoyReported"]).abs()
    print(f"\n=== 0. YoY 검산 (내 재계산 vs TSMC 공식 게시값) ===")
    print(f"n={len(sub)}  평균 절대오차={diff.mean():.3f}%p  최대오차={diff.max():.3f}%p "
          f"({'통과' if diff.max() < 0.5 else '점검 필요'} — 반올림 오차 범위 0.5%p 이내면 정상)")


def load_soxl_fwd(df: pd.DataFrame) -> pd.DataFrame:
    soxl = pd.read_parquet(ROOT / "data" / "leveraged-etf" / "SOXL.parquet")
    soxl["date"] = pd.to_datetime(soxl["date"])
    soxl = soxl.sort_values("date").set_index("date")["close"]

    def fwd_ret(asof, months):
        end = asof + pd.DateOffset(months=months)
        s = soxl.loc[asof:end]
        if len(s) < 2 or s.index[0] > asof + pd.Timedelta(days=10):
            return np.nan
        return (s.iloc[-1] / s.iloc[0] - 1) * 100

    for m in (1, 3, 6):
        df[f"soxl_fwd_{m}m"] = df["availableFrom"].apply(lambda d: fwd_ret(d, m))
    return df


def analyze(df: pd.DataFrame):
    print(f"전체 관측치: {len(df)}개월 (2013-01 ~ {df['periodEnd'].max().strftime('%Y-%m')})")
    factors = ["rev_yoy", "rev_qoq3m", "rev_chg6m", "rev_yoy_accel", "rev_yoy_roll3m"]

    print("\n=== 1. Spearman (naive, overlap 있음) ===")
    print(f"{'factor':16s} {'horizon':8s} {'n':>4s} {'rho':>8s} {'p':>8s}")
    for factor in factors:
        for m in (1, 3, 6):
            sub = df[[factor, f"soxl_fwd_{m}m"]].dropna()
            if len(sub) < 20:
                continue
            rho, p = stats.spearmanr(sub[factor], sub[f"soxl_fwd_{m}m"])
            flag = " *" if p < 0.05 else ""
            print(f"{factor:16s} {str(m)+'m':8s} {len(sub):4d} {rho:+8.3f} {p:8.3f}{flag}")

    print("\n=== 2. Newey-West(HAC) OLS — 겹치는 윈도우 자기상관 보정 ===")
    import statsmodels.api as sm
    for factor in factors:
        for m in (1, 3, 6):
            sub = df[[factor, f"soxl_fwd_{m}m"]].dropna()
            if len(sub) < 20:
                continue
            X = sm.add_constant(sub[factor])
            y = sub[f"soxl_fwd_{m}m"]
            lag = max(1, m - 1)  # 겹치는 개월수만큼 lag
            model = sm.OLS(y, X).fit(cov_type="HAC", cov_kwds={"maxlags": lag})
            coef, p = model.params[factor], model.pvalues[factor]
            flag = " *" if p < 0.05 else ""
            print(f"{factor:16s} {str(m)+'m':8s} n={len(sub):4d} lag={lag}  "
                  f"coef={coef:+8.3f}  p={p:8.3f}{flag}")

    print("\n=== 3. 완전 비중첩 서브샘플 (매 m개월 간격만 사용) ===")
    for m in (1, 3, 6):
        step = m
        sub_full = df[["rev_yoy", f"soxl_fwd_{m}m"]].dropna()
        sub = sub_full.iloc[::step]
        if len(sub) < 15:
            continue
        rho, p = stats.spearmanr(sub["rev_yoy"], sub[f"soxl_fwd_{m}m"])
        print(f"rev_yoy vs {m}m 비중첩(n={len(sub)}):  rho={rho:+.3f}  p={p:.3f}")

    print("\n=== 4. 분위수별 선행수익률 (rev_yoy 5분위) ===")
    sub = df[["rev_yoy", "soxl_fwd_1m", "soxl_fwd_3m", "soxl_fwd_6m"]].dropna()
    sub = sub.copy()
    sub["q"] = pd.qcut(sub["rev_yoy"], 5, labels=["Q1(최저)", "Q2", "Q3", "Q4", "Q5(최고)"])
    print(sub.groupby("q", observed=True)[["soxl_fwd_1m", "soxl_fwd_3m", "soxl_fwd_6m"]].mean().to_string())
    print("표본수:", sub.groupby("q", observed=True).size().to_dict())

    print("\n=== 5. YoY 상승전환/하락전환 이벤트 (부호 전환 시점) ===")
    sub2 = df[["periodEnd", "rev_yoy", "soxl_fwd_1m", "soxl_fwd_3m", "soxl_fwd_6m"]].dropna().reset_index(drop=True)
    sub2["prev_sign"] = np.sign(sub2["rev_yoy"].shift(1))
    sub2["curr_sign"] = np.sign(sub2["rev_yoy"])
    up_cross = sub2[(sub2["prev_sign"] < 0) & (sub2["curr_sign"] > 0)]
    down_cross = sub2[(sub2["prev_sign"] > 0) & (sub2["curr_sign"] < 0)]
    print(f"상승전환(n={len(up_cross)}): 평균 fwd1m={up_cross['soxl_fwd_1m'].mean():+.1f}%  "
          f"fwd3m={up_cross['soxl_fwd_3m'].mean():+.1f}%  fwd6m={up_cross['soxl_fwd_6m'].mean():+.1f}%")
    print(f"하락전환(n={len(down_cross)}): 평균 fwd1m={down_cross['soxl_fwd_1m'].mean():+.1f}%  "
          f"fwd3m={down_cross['soxl_fwd_3m'].mean():+.1f}%  fwd6m={down_cross['soxl_fwd_6m'].mean():+.1f}%")


def selftest() -> int:
    fails = []

    def ck(name, cond):
        print(("ok   " if cond else "FAIL ") + name)
        if not cond:
            fails.append(name)

    df = build_monthly()
    ck("전 연도 12개월(2026 제외) 존재", (df[df.year < 2026].groupby("year").size() == 12).all())
    ck("2026년은 8개월만(조회일 기준)", (df[df.year == 2026].shape[0]) == 8)
    ck("availableFrom = periodEnd + 15일", (df["availableFrom"] - df["periodEnd"]).dt.days.eq(15).all())
    row = df[(df.year == 2024) & (df.month == 1)].iloc[0]
    ck("2024-01 YoY 재계산이 공식값(7.9%)과 0.5%p 이내로 일치",
       abs(row["rev_yoy"] - row["yoyReported"]) < 0.5)
    ck("매출은 전부 양수", (df["revenueNtdMn"] > 0).all())

    total = 5
    print(f"\nselftest {total - len(fails)}/{total}" + ("" if not fails else f"  FAILED: {fails}"))
    return 1 if fails else 0


def main():
    df = build_monthly()
    verify_reported_yoy(df)
    df = load_soxl_fwd(df)
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    out = OUT_DIR / "tsmc_monthly_revenue.parquet"
    df.to_parquet(out, index=False)
    print(f"저장: {out} ({len(df)}행)\n")
    analyze(df)


if __name__ == "__main__":
    import sys
    if "--selftest" in sys.argv:
        raise SystemExit(selftest())
    main()
