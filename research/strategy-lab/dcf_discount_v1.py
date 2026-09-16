#!/usr/bin/env python
"""DCF 내재가치 할인율 팩터 v1(연구용) — FCFE 간이 DCF + 규칙1(정직한 점수) 준수/위반 비교.

왜 있나
-------
사용자 요청 둘을 한 스크립트로 합친다.
  (1) PBR·earnings_yield 같은 비율이 아니라 미래현금흐름을 할인한 "DCF식 저평가"가
      한국 주식에서 독립적인 알파를 가지는가 — 안 해본 축.
  (2) 절대 규칙 1("결측치는 null/유보, 채워 넣지 않는다")을 어기면 실제로 뭐가
      달라지는가 — 규칙 자체를 검증하는 실험. "채우는 쪽"이 이기는지 지는지는
      추측하지 말고 재서 확인한다.

DCF 산식 — v1은 의도적으로 단순하다(그래서 정직하게 표시한다)
-------------------------------------------------------------
  FCFE(자기자본 잉여현금) 방식 — WACC/부채가중 대신 자기자본비용 하나로 할인한다.
    FCF 대리지표 = A3 netIncome (capex·운전자본 분해 데이터가 없어 세후이익을 그대로 씀)
    자기자본비용 = rf(그 시점 국고채3년, market-regime/krtreasury3y_raw) + ERP(5.5%, [ASSUMPTION])
      ★ 베타를 종목별로 안 잰다(v1 단순화) — 전 종목 beta=1 가정. 종목별 리스크
      차별화가 없다는 뜻 — 다음 버전 후보.
    성장률 = 최근 회계연도 매출 CAGR(가용 연도 전체) → 5년에 걸쳐 terminal growth로
      선형 수렴(fade). terminal growth = min(rf, 2%) — 챗지피티가 지적한 "과거
      성장률을 그대로 미래로 쓰면 관성모델이 된다"는 문제를 이렇게 처리한다.
    이익 성장률 = 매출 성장률과 같다고 가정(마진 불변, 단순화).
    Terminal Value = FCFE_5년째 * (1+terminal_g) / (costOfEquity - terminal_g)
    fairValuePerShare = (5년 PV 합 + terminal PV) / A3c 발행주식수(그 시점 PIT)

  이건 "정확한 기업가치"가 아니라 PBR·earnings_yield와 같은 위상의 밸류에이션
  팩터 하나다 — 해석 시 그렇게만 쓴다.

규칙1 실험 — 두 변형
--------------------
  honest(현재 방식)  회계연도 2개 미만(성장률 계산 불가)이면 그 달 그 종목은 제외
  filled(규칙1 위반) 회계연도 2개 미만이면, 그 달 다른 종목들의 성장률 중앙값으로
                     채워서 그대로 점수를 매긴다(제외하지 않는다)
  ★ 둘 다 순이익<=0(적자)인 종목은 제외한다 — 이건 "결측"이 아니라 "DCF 모델
  자체가 정의 안 되는 영역"이라 이번 실험(결측 처리 방식 비교)의 대상이 아니다.
  ★ 발행주식수(A3c)가 아예 없으면 두 변형 다 제외한다 — 주당가치 자체를 못
  낸다(추정으로 메울 수 있는 성격이 아니다).

방법론은 sweep_momentum_window.py와 동일 재사용 — 유동성 통과 EW 대비 초과수익,
회전율×30bp 비용, 난수 귀무분포 |t| 95pct, TRAIN/VALID/TEST.

사용법
------
  python dcf_discount_v1.py --selftest
  python dcf_discount_v1.py --null-draws 200
"""
import argparse
import glob
import gzip
import json
import os
import time

import numpy as np
import pandas as pd

_THIS = os.path.dirname(os.path.abspath(__file__))
REPO_ROOT = os.path.dirname(os.path.dirname(_THIS))
PANEL = os.path.join(_THIS, "data", "factor-panel", "kr-monthly-v1.parquet")
OHLC = os.path.join(_THIS, "data", "factor-panel", "a2a-ohlc.parquet")
A3_DIR = os.path.join(REPO_ROOT, "data", "backfill", "fundamentals", "a3")
A3C_DIR = os.path.join(REPO_ROOT, "data", "backfill", "fundamentals", "a3c")
RF_PATH = os.path.join(_THIS, "data", "market-regime", "krtreasury3y_raw.parquet")
OUT_DIR = os.path.join(_THIS, "reports", "dcf-discount-v1")

ROUND_TRIP_BPS = 30.0
TOP_N = 30
PROJ_YEARS = 5
ERP = 0.055                    # [ASSUMPTION] 자기자본 리스크프리미엄, 고정
TERMINAL_GROWTH_CAP = 0.02
GROWTH_CLAMP = (-0.30, 0.50)   # 극단적 외삽 방지
WARMUP_YEARS_MIN = 2           # 성장률 계산에 필요한 최소 회계연도 수
PERIODS = {"TRAIN": ("2018-01-01", "2022-06-30"),
           "VALID": ("2022-07-01", "2023-12-31"),
           "TEST": ("2024-01-01", "2026-07-31")}
SESSIONS_PER_YEAR = 12         # 월간 스텝이므로 "세션"이 아니라 "개월"


def _norm_date(s):
    """A3 20260320 / 2026-03-20 두 표기를 다 YYYY-MM-DD로."""
    s = str(s)
    if "-" in s:
        return s
    return f"{s[:4]}-{s[4:6]}-{s[6:8]}"


def tstat(x):
    x = np.asarray(x, dtype=float)
    x = x[np.isfinite(x)]
    if len(x) < 3 or x.std(ddof=1) == 0:
        return float("nan")
    return float(x.mean() / (x.std(ddof=1) / np.sqrt(len(x))))


def turnover(prev_idx, new_idx, n):
    if prev_idx is None:
        return 1.0
    keep = len(np.intersect1d(prev_idx, new_idx, assume_unique=True))
    return (n - keep) / float(n)


def revenue_cagr(records):
    """records: [(fiscalYear, revenue), ...] 오름차순, 최소 2개. 가장 이른/늦은
    연도로 CAGR. 매출<=0인 연도가 끼면 계산 불가(None)."""
    first_y, first_r = records[0]
    last_y, last_r = records[-1]
    years = last_y - first_y
    if years <= 0 or first_r is None or last_r is None or first_r <= 0 or last_r <= 0:
        return None
    g = (last_r / first_r) ** (1.0 / years) - 1.0
    return max(GROWTH_CLAMP[0], min(GROWTH_CLAMP[1], g))


def fair_value_per_share(net_income0, growth0, terminal_g, cost_of_equity, shares):
    if net_income0 is None or net_income0 <= 0 or shares is None or shares <= 0:
        return None
    if cost_of_equity <= terminal_g:
        return None
    pv = 0.0
    fcf = net_income0
    g = growth0
    step = (growth0 - terminal_g) / PROJ_YEARS  # 선형 수렴(fade)
    for y in range(1, PROJ_YEARS + 1):
        g_y = growth0 - step * y
        fcf = fcf * (1 + g_y)
        pv += fcf / (1 + cost_of_equity) ** y
    tv = fcf * (1 + terminal_g) / (cost_of_equity - terminal_g)
    pv += tv / (1 + cost_of_equity) ** PROJ_YEARS
    return pv / shares


def _selftest():
    assert revenue_cagr([(2020, 100), (2023, 133.1)]) is not None
    g = revenue_cagr([(2020, 100), (2023, 133.1)])
    assert abs(g - 0.10) < 1e-3, g          # 10%/yr 복리
    assert revenue_cagr([(2020, 100), (2023, -5)]) is None   # 적자연도 계산 불가
    assert revenue_cagr([(2020, 100), (2020, 100)]) is None  # 연도 간격 0
    v = fair_value_per_share(1000.0, 0.10, 0.02, 0.02, 100.0)
    assert v is None                        # costOfEquity <= terminal_g면 발산 방지
    v = fair_value_per_share(1000.0, 0.10, 0.02, 0.12, 100.0)
    assert v is not None and v > 0
    assert fair_value_per_share(-1000.0, 0.10, 0.02, 0.12, 100.0) is None  # 적자 제외
    assert fair_value_per_share(1000.0, 0.10, 0.02, 0.12, None) is None   # 주식수 없음
    assert turnover(None, np.array([1, 2, 3]), 3) == 1.0
    assert np.isnan(tstat([1.0, 1.0, 1.0]))
    print("selftest OK — revenue_cagr · fair_value_per_share · turnover · tstat")


# ---------------------------------------------------------------- 데이터 적재

def load_a3():
    """ticker -> [(availableFromDate, fiscalYear, revenue, netIncome), ...] 오름차순."""
    by_ticker = {}
    for path in sorted(glob.glob(os.path.join(A3_DIR, "*.jsonl.gz"))):
        with gzip.open(path, "rt", encoding="utf-8") as f:
            for line in f:
                o = json.loads(line)
                if o.get("fsDiv") != "CFS":   # 연결재무제표만 — OFS 섞으면 스케일 불일치
                    continue
                t = o.get("ticker")
                if not t or o.get("revenue") is None:
                    continue
                by_ticker.setdefault(t, []).append((
                    _norm_date(o["availableFrom"]), o["fiscalYear"],
                    o.get("revenue"), o.get("netIncome")))
    for t in by_ticker:
        by_ticker[t].sort(key=lambda r: r[1])  # fiscalYear 오름차순
    return by_ticker


def load_a3c():
    """ticker -> [(availableFromDate, shares), ...] 오름차순."""
    by_ticker = {}
    for path in sorted(glob.glob(os.path.join(A3C_DIR, "*.jsonl.gz"))):
        with gzip.open(path, "rt", encoding="utf-8") as f:
            for line in f:
                o = json.loads(line)
                t = o.get("ticker")
                sh = o.get("isuStockTotqy")
                if not t or not sh:
                    continue
                by_ticker.setdefault(t, []).append((_norm_date(o["availableFrom"]), sh))
    for t in by_ticker:
        by_ticker[t].sort(key=lambda r: r[0])
    return by_ticker


def load_rf():
    df = pd.read_parquet(RF_PATH)
    df["date"] = df["date"].astype(str)
    return dict(zip(df["date"], df["value"]))


def rf_asof(rf_dates_sorted, rf_map, date):
    """date 이전(포함) 가장 최근 국고채3년 금리(%) -> 소수로. 없으면 None."""
    import bisect
    i = bisect.bisect_right(rf_dates_sorted, date) - 1
    if i < 0:
        return None
    return rf_map[rf_dates_sorted[i]] / 100.0


def asof_a3(records, date, min_years=WARMUP_YEARS_MIN):
    """date 시점에 이미 공시된(availableFrom<=date) 레코드만, fiscalYear 오름차순
    유지한 채로 자른다. min_years 미만이면 growth=None."""
    avail = [r for r in records if r[0] <= date]
    if len(avail) < min_years:
        return None, (avail[-1][3] if avail else None)  # (growth, netIncome0)
    rev_pairs = [(r[1], r[2]) for r in avail]
    growth = revenue_cagr(rev_pairs)
    net_income0 = avail[-1][3]
    return growth, net_income0


def asof_a3c(records, date):
    avail = [r for r in records if r[0] <= date]
    return avail[-1][1] if avail else None


# ---------------------------------------------------------------- 팩터 계산

def build_monthly_selection(panel, px, a3, a3c, rf_map, rf_dates):
    """반환: honest_sel, filled_sel — 각각 {date: [(ticker, discount), ...]} (상위 30, 미리 안 자름 — 원본 랭킹 전체 반환)."""
    col_of = {t: i for i, t in enumerate(px.columns)}

    anchors = sorted(panel["date"].unique())
    eligible_by_date = {d: set(g["ticker"]) for d, g in panel[panel["liquid"]].groupby("date")}

    honest_sel, filled_sel = {}, {}
    for d in anchors:
        elig = eligible_by_date.get(d, set())
        rf = rf_asof(rf_dates, rf_map, d)
        if rf is None or not elig:
            continue
        cost_of_equity = rf + ERP
        terminal_g = min(rf, TERMINAL_GROWTH_CAP)

        rows = []  # (ticker, growth_or_None, net_income0, shares)
        for t in elig:
            growth, ni0 = asof_a3(a3.get(t, []), d)
            sh = asof_a3c(a3c.get(t, []), d)
            rows.append((t, growth, ni0, sh))

        known_growths = [g for _, g, _, _ in rows if g is not None]
        market_median_growth = float(np.median(known_growths)) if known_growths else None

        honest_scores, filled_scores = [], []
        for t, growth, ni0, sh in rows:
            j = col_of.get(t)
            if j is None or ni0 is None or ni0 <= 0 or sh is None or sh <= 0:
                continue  # 두 변형 공통 제외 — 적자/주식수 없음은 결측 실험 대상이 아니다
            if growth is not None:
                fv = fair_value_per_share(ni0, growth, terminal_g, cost_of_equity, sh)
                if fv is not None:
                    honest_scores.append((t, fv))
                    filled_scores.append((t, fv))  # 정보 충분 — 두 변형 동일
            else:
                # honest: 제외(아무것도 안 넣음). filled: 시장 중앙값 성장률로 채운다.
                if market_median_growth is not None:
                    fv = fair_value_per_share(ni0, market_median_growth, terminal_g,
                                               cost_of_equity, sh)
                    if fv is not None:
                        filled_scores.append((t, fv))
        honest_sel[d] = honest_scores
        filled_sel[d] = filled_scores
    return honest_sel, filled_sel


def run_backtest(sel, px, panel):
    """sel: {date: [(ticker, fairValue), ...]}. discount = fv/price - 1, 상위 30 매수,
    유동성 통과 전체 EW 대비 초과수익. 반환: [(date, gross, cost, turnover, holdMonths)]."""
    dates = list(px.index)
    col_of = {t: i for i, t in enumerate(px.columns)}
    mat = px.to_numpy(dtype=float)
    date_idx = {d: i for i, d in enumerate(dates)}
    eligible_by_date = {d: set(g["ticker"]) for d, g in panel[panel["liquid"]].groupby("date")}

    anchors = sorted(sel.keys())
    prev = None
    out = []
    for k in range(len(anchors) - 1):
        d0, d1 = anchors[k], anchors[k + 1]
        i0, i1 = date_idx.get(d0), date_idx.get(d1)
        if i0 is None or i1 is None:
            continue
        cands = []
        for t, fv in sel[d0]:
            j = col_of.get(t)
            if j is None:
                continue
            p0 = mat[i0, j]
            if not np.isfinite(p0) or p0 <= 0:
                continue
            cands.append((t, j, fv / p0 - 1.0))
        if len(cands) < TOP_N:
            continue
        cands.sort(key=lambda x: -x[2])  # 할인율 높은(저평가) 순
        pick = cands[:TOP_N]
        pick_cols = np.array(sorted(j for _, j, _ in pick))

        elig = eligible_by_date.get(d0, set())
        elig_cols = np.array(sorted(col_of[t] for t in elig if t in col_of))
        p0e, p1e = mat[i0, elig_cols], mat[i1, elig_cols]
        ok = np.isfinite(p0e) & (p0e > 0) & np.isfinite(p1e)
        bench = float((p1e[ok] / p0e[ok] - 1.0).mean()) if ok.any() else float("nan")

        p0p = mat[i0, pick_cols]
        p1p = mat[i1, pick_cols]
        okp = np.isfinite(p0p) & (p0p > 0) & np.isfinite(p1p)
        port = float((p1p[okp] / p0p[okp] - 1.0).mean()) if okp.any() else float("nan")

        gross = port - bench
        tn = turnover(prev, pick_cols, TOP_N)
        prev = pick_cols
        out.append((d0, gross, tn * ROUND_TRIP_BPS / 1e4, tn, 1))
    return out


def summarize(series):
    def block(sub):
        if not sub:
            return {"n": 0}
        g = np.array([s[1] for s in sub])
        c = np.array([s[2] for s in sub])
        tn = np.array([s[3] for s in sub])
        per_year = SESSIONS_PER_YEAR
        return {"n": len(sub), "grossAnnPct": float(g.mean() * per_year * 100),
                "costAnnPct": float(c.mean() * per_year * 100),
                "netAnnPct": float((g - c).mean() * per_year * 100),
                "tGross": tstat(g), "tNet": tstat(g - c), "turnover": float(tn.mean())}
    out = {name: block([s for s in series if lo <= s[0] <= hi])
           for name, (lo, hi) in PERIODS.items()}
    out["ALL"] = block(series)
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--selftest", action="store_true")
    ap.add_argument("--null-draws", type=int, default=200)
    args = ap.parse_args()
    if args.selftest:
        _selftest()
        return

    t0 = time.time()
    panel = pd.read_parquet(PANEL, columns=["ticker", "date", "liquid"])
    panel["date"] = panel["date"].astype(str)
    ohlc = pd.read_parquet(OHLC, columns=["ticker", "date", "close"])
    ohlc["date"] = ohlc["date"].astype(str)
    px = ohlc.pivot(index="date", columns="ticker", values="close").sort_index()
    print(f"패널 {len(panel)}행 · 일봉 {px.shape[0]}일x{px.shape[1]}종목 ({time.time()-t0:.0f}s)")

    a3 = load_a3()
    a3c = load_a3c()
    rf_map = load_rf()
    rf_dates = sorted(rf_map)
    print(f"A3 {len(a3)}종목 · A3c {len(a3c)}종목 · rf {len(rf_map)}일 ({time.time()-t0:.0f}s)")

    honest_sel, filled_sel = build_monthly_selection(panel, px, a3, a3c, rf_map, rf_dates)
    hc = sum(len(v) for v in honest_sel.values())
    fc = sum(len(v) for v in filled_sel.values())
    print(f"월별 후보 총합 — honest {hc} · filled {fc} (filled가 더 많아야 정상)")

    honest_series = run_backtest(honest_sel, px, panel)
    filled_series = run_backtest(filled_sel, px, panel)

    rng = np.random.default_rng(20260917)
    dates_common = sorted(set(honest_sel) & set(filled_sel))
    null_t = []
    for _ in range(args.null_draws):
        fake = {}
        for d in dates_common:
            cands = honest_sel[d]
            if len(cands) < TOP_N:
                continue
            tickers = [t for t, _ in cands]
            fake_scores = rng.standard_normal(len(tickers))
            fake[d] = list(zip(tickers, fake_scores))
        s = run_backtest(fake, px, panel)
        null_t.append(abs(tstat([x[1] for x in s])))
    null_t = [t for t in null_t if np.isfinite(t)]
    floor = float(np.percentile(null_t, 95)) if null_t else float("nan")

    for name, series in [("honest(규칙1 준수)", honest_series), ("filled(규칙1 위반)", filled_series)]:
        st = summarize(series)
        a = st["ALL"]
        print(f"\n[{name}] 스텝 {a.get('n', 0)}개")
        print("  총 %+6.2f%% - 비용 %5.2f%% = 순 %+6.2f%%   tGross %+5.2f %s · tNet %+5.2f   "
              "TRAIN/VALID/TEST 순 %+.2f/%+.2f/%+.2f%%"
              % (a.get("grossAnnPct", 0), a.get("costAnnPct", 0), a.get("netAnnPct", 0),
                 a.get("tGross", float("nan")),
                 "통과" if np.isfinite(a.get("tGross", float("nan"))) and abs(a["tGross"]) > floor else "미달",
                 a.get("tNet", float("nan")),
                 st["TRAIN"].get("netAnnPct", 0), st["VALID"].get("netAnnPct", 0),
                 st["TEST"].get("netAnnPct", 0)))

    print(f"\n난수 바닥선(|t| 95pct) {floor:.2f} (draws {len(null_t)})")

    os.makedirs(OUT_DIR, exist_ok=True)
    out = {"generatedAt": time.strftime("%Y-%m-%dT%H:%M:%S"),
           "assumptions": {"ERP": ERP, "terminalGrowthCap": TERMINAL_GROWTH_CAP,
                            "projYears": PROJ_YEARS, "beta": "1.0 (fixed, v1 단순화)",
                            "fcfProxy": "A3 netIncome (FCFE 방식)"},
           "nullFloor95": floor, "periods": PERIODS,
           "honest": summarize(honest_series), "filled": summarize(filled_series)}
    p = os.path.join(OUT_DIR, "backtest.json")
    with open(p, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=1)
    print(f"\n저장 {p} ({time.time()-t0:.0f}s)")


if __name__ == "__main__":
    main()
