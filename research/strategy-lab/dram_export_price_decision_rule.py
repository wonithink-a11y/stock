#!/usr/bin/env python3
"""DRAM 수출단가(관세청) → 005930·000660 의사결정 룰 백테스트 (2026-09-13).

`dram-export-price-samsung-hynix-pilot-2026-09-13.md`(HOLD)가 "실제 룰이
없다·비용검증이 없다"를 KEEP 전 남은 조각으로 못박아 사용자 GO로 착수.
사전 지정(round number) 원칙을 먼저 적는다 - 백테스트 결과를 본 뒤 문턱값을
고르면 파라미터 튜닝이 되므로, 아래 설계는 전부 실행 전에 정했다.

## 사전 등록(pre-registration)

- 신호: `ppi_yoy`(DRAM 수출단가 YoY)의 **expanding percentile**(과거 정보만,
  최소 24개월 - Stage5-1 `pctrank_exp`와 동일한 "현재값 제외 과거표본" 규칙).
  raw YoY 값을 그대로 쓰면 2026년처럼 300~500%대 극값이 나올 수 있어(finding
  §2c) 스케일이 안정적인 percentile로 정규화한다.
- 문턱값: **finding 원문 §2 "분위수(5분위)" 분석에서 이미 쓴 Q1/Q5(0.2/0.8
  quintile)를 그대로 재사용** - 이번에 새로 탐색한 값이 아니다.
- 방향(콘트래리안, finding 결론 그대로): DRAM YoY가 **높을수록**(Q5, 가격
  과열) 6개월 선행 수익률이 낮다 → 비중을 줄인다. 낮을수록(Q1) 수익률이
  높지만 **레버리지 확대는 안 한다**(이 랩의 futures Stage 5-3/6과 동일
  원칙 - 최대 1.0x, Q1도 1.0x 유지).
- 사전 지정 규칙 2종만(Stage 5-3 A/B와 같은 구조, 새 규칙 발명 없음):
    A(축소)   Q5(pct>=0.8) → 0.5x, 그 외 1.0x
    B(회피)   Q5(pct>=0.8) → 0.0x, 그 외 1.0x
- 리밸런스: 월 1회, `availableFrom`(월말+20일, PIT) 시점부터 다음 신호까지
  가중치 유지. look-ahead 없음(신호는 이전 달 종가 기준, 적용은 익월 20일부터).
- 비용: 이 랩의 KR 표준 관행(`price_structure_sweep_v2.py`·`donchian_*`)
  **10bp round-trip 수수료 + 5bp/side 슬리피지 = 편도 10bp** 그대로 재사용
  - 새로 정하지 않음. 리밸런스일에 `|Δw| * 10bp`로 부과.
- 기준: B&H(항상 1.0x, 리밸런스 없음).
- 평가: 종목별(005930·000660) + 전체/전반/후반(finding과 동일 반분점
  2020-06-30) - 000660의 국면의존성(§2c로 "진짜"라고 확인됨)이 실제 룰
  성과에도 나타나는지가 핵심 질문.
- 금지: 문턱값 재탐색, 레버리지 확대, Short, 3단계 이상 세분화, WFA/OOS,
  타종목 확장, production, commit(finding에만 기록).

    python research/strategy-lab/dram_export_price_decision_rule.py
"""
from pathlib import Path

import numpy as np
import pandas as pd

from semiconductor_cycle_kcs_export_price import OUT_DIR, load_stock_close

ROOT = Path(__file__).resolve().parent
Q1_CUT, Q5_CUT = 0.2, 0.8
RULES = {"A_reduce": 0.5, "B_avoid": 0.0}
COST_PER_SIDE = 0.0010  # 10bp round-trip/2 + 5bp slippage = 편도 10bp (이 랩 표준)
HALF_SPLIT = pd.Timestamp("2020-06-30")
TICKERS = ["005930", "000660"]


def pctrank_exp(x: pd.Series, min_periods: int = 24) -> pd.Series:
    """과거 정보만의 expanding percentile(현재값 제외, Stage5-1 pctrank_exp와 동일 규칙)."""
    arr = x.to_numpy(dtype=float)
    out = np.full(len(arr), np.nan)
    for i in range(min_periods, len(arr)):
        hist = arr[:i]
        hist = hist[np.isfinite(hist)]
        if len(hist) < min_periods or not np.isfinite(arr[i]):
            continue
        out[i] = (hist < arr[i]).mean()
    return pd.Series(out, index=x.index)


def target_weight(pct: float, cut_value: float) -> float:
    if pct != pct:  # NaN(warmup) -> B&H와 동일하게 1.0x
        return 1.0
    return cut_value if pct >= Q5_CUT else 1.0


def run_rule(monthly: pd.DataFrame, close: pd.Series, cut_value: float, end_date: pd.Timestamp) -> dict:
    """monthly: [availableFrom, pct] 월별 신호. close: 일별 종가(date-indexed).
    availableFrom부터 다음 availableFrom 전날까지 동일 가중치 유지, 마지막
    구간은 end_date(호출자가 정한 기간 끝)에서 자른다 - 안 자르면 마지막
    세그먼트가 close 전체 이력 끝까지 새 뒤 기간까지 침범한다(실측 버그:
    '전반' 백테스트가 '전체'와 동일한 12.22년으로 나왔던 원인)."""
    end_date = min(end_date, close.index.max())
    dates = monthly["availableFrom"].tolist() + [end_date + pd.Timedelta(days=1)]
    weights = [target_weight(p, cut_value) for p in monthly["pct"]]

    px = close.sort_index()
    nav = 1.0
    nav_series = []
    prev_w = 0.0
    total_cost = 0.0
    n_rebal = 0
    for i, (start, end) in enumerate(zip(dates[:-1], dates[1:])):
        w = weights[i]
        seg = px.loc[start:end]
        seg = seg[seg.index < end]
        if len(seg) < 1:
            continue
        dw = abs(w - prev_w)
        if dw > 0:
            nav *= (1 - dw * COST_PER_SIDE)
            total_cost += dw * COST_PER_SIDE
            n_rebal += 1
        prev_w = w
        rets = seg.pct_change().fillna(0.0)
        for dt, r in rets.items():
            nav *= (1 + w * r)
            nav_series.append((dt, nav))
    if not nav_series:
        return None
    s = pd.Series(dict(nav_series)).sort_index()
    return dict(nav=s, total_cost=total_cost, n_rebal=n_rebal)


def run_buyhold(close: pd.Series, start: pd.Timestamp, end: pd.Timestamp) -> pd.Series:
    px = close.sort_index()
    px = px[(px.index >= start) & (px.index <= end)]
    rets = px.pct_change().fillna(0.0)
    nav = (1 + rets).cumprod()
    nav.iloc[0] = 1.0 - 2 * COST_PER_SIDE  # 진입+청산 1x 편도 2회(왕복)
    return nav


def metrics(nav: pd.Series) -> dict:
    if nav is None or len(nav) < 20:
        return None
    years = (nav.index[-1] - nav.index[0]).days / 365.25
    cagr = (nav.iloc[-1] / nav.iloc[0]) ** (1 / years) - 1 if years > 0 else np.nan
    rets = nav.pct_change().dropna()
    sd = rets.std(ddof=1)
    sharpe = rets.mean() / sd * np.sqrt(252) if sd and sd > 0 else np.nan
    peak = nav.cummax()
    mdd = float(((nav - peak) / peak).min())
    calmar = cagr / abs(mdd) if mdd and mdd < 0 else np.nan
    return dict(years=round(years, 2), cagr=round(float(cagr) * 100, 2),
                sharpe=round(float(sharpe), 3), mdd=round(mdd * 100, 2),
                calmar=round(float(calmar), 3) if calmar == calmar else None,
                n_days=len(nav))


def main():
    results = []
    for ticker in TICKERS:
        df = pd.read_parquet(OUT_DIR / f"kcs_export_dram_{ticker}.parquet")
        df = df.dropna(subset=["ppi_yoy"]).sort_values("periodEnd").reset_index(drop=True)
        df["pct"] = pctrank_exp(df["ppi_yoy"])
        close = load_stock_close(ticker)

        periods = {
            "전체": (df["availableFrom"].min(), close.index.max()),
            "전반": (df["availableFrom"].min(), HALF_SPLIT),
            "후반": (HALF_SPLIT, close.index.max()),
        }
        for pname, (pstart, pend) in periods.items():
            sub = df[(df["availableFrom"] >= pstart) & (df["availableFrom"] <= pend)].reset_index(drop=True)
            if len(sub) < 6:
                continue
            bh = run_buyhold(close, sub["availableFrom"].min(), pend)
            m_bh = metrics(bh)
            row = dict(ticker=ticker, period=pname, strategy="buyhold", **m_bh)
            results.append(row)
            for rname, cut in RULES.items():
                out = run_rule(sub[["availableFrom", "pct"]], close, cut, pend)
                m = metrics(out["nav"]) if out else None
                if m:
                    row = dict(ticker=ticker, period=pname, strategy=rname,
                               n_rebal=out["n_rebal"], total_cost_pct=round(out["total_cost"] * 100, 3), **m)
                    results.append(row)

    out_df = pd.DataFrame(results)
    out_path = ROOT / "data" / "semiconductor-cycle" / "dram_decision_rule_backtest.csv"
    out_df.to_csv(out_path, index=False, encoding="utf-8-sig")

    pd.set_option("display.width", 200)
    pd.set_option("display.max_columns", 20)
    print(out_df.to_string(index=False))
    print(f"\n저장: {out_path}")


def selftest() -> int:
    fails = []

    def ck(name, cond):
        print(("ok   " if cond else "FAIL ") + name)
        if not cond:
            fails.append(name)

    x = pd.Series(np.concatenate([np.full(24, 50.0), [10.0, 90.0]]))
    p = pctrank_exp(x, min_periods=24)
    ck("warmup 구간(첫 24개) 전부 NaN", p.iloc[:24].isna().all())
    ck("낮은 값(10) percentile 낮음", p.iloc[24] < 0.5)
    ck("높은 값(90) percentile 높음", p.iloc[25] > 0.5)

    ck("target_weight Q5 이상 cut적용", target_weight(0.85, 0.5) == 0.5)
    ck("target_weight Q5 미만 1.0", target_weight(0.5, 0.5) == 1.0)
    ck("target_weight NaN(warmup) 1.0", target_weight(float("nan"), 0.5) == 1.0)

    idx = pd.date_range("2020-01-01", periods=100, freq="D")
    close = pd.Series(100 + np.arange(100) * 0.1, index=idx)
    monthly = pd.DataFrame({"availableFrom": [idx[0], idx[50]], "pct": [0.9, 0.1]})
    out = run_rule(monthly, close, 0.5, idx[-1])
    ck("run_rule NAV 생성됨", out is not None and len(out["nav"]) > 50)
    ck("run_rule 리밸런스 발생", out["n_rebal"] >= 1)

    out_capped = run_rule(monthly, close, 0.5, idx[60])
    ck("end_date로 마지막 구간이 잘림(과거 버그: 전체 이력까지 침범)",
       out_capped["nav"].index.max() <= idx[60])

    total = 9
    print(f"\nselftest {total - len(fails)}/{total}" + ("" if not fails else f"  FAILED: {fails}"))
    return 1 if fails else 0


if __name__ == "__main__":
    import sys
    if "--selftest" in sys.argv:
        raise SystemExit(selftest())
    main()
