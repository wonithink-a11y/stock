#!/usr/bin/env python
"""임원·주요주주 소유상황보고서(DART elestock.json) 기반 내부자거래 신호
1차 정찰 — Congressional Trading(가짜 데이터로 판명, 기각)의 실제 한국판
대체재. 이 프로젝트가 아직 한 번도 다루지 않은 완전히 새로운 데이터축
(사용자 지시 2026-08-28, "새로운 신호를 찾아봐").

**중요한 한계(실측 확인, 2026-08-28)**: elestock.json은 bgn_de/end_de
파라미터를 받지만 무시한다 - 실측 결과 모든 기업이 예외 없이 2024년
9월~2025년 1월 사이 어딘가부터만 데이터를 반환한다(삼성전자 2024-09-06
시작, 현대차 2025-01-08, LG전자 2024-10-31 등 - 기업마다 다른 시작일이
공시빈도와 무관해 고정 행수 상한이 아니라 **약 2년 롤링 윈도우**로
추정됨). 이 프로젝트의 다른 factor들이 쓰는 2016~2026 10년 표본과
비교가 안 된다 - 이건 **본격 검증이 아니라 1차 정찰**이다. 신호가
있어 보이면, 전체 역사가 필요한 진짜 검증에는 DART list.json(pblntf_ty
공시 목록)으로 개별 보고서를 찾아 원문을 파싱하는 훨씬 무거운 별도
작업이 필요하다(Tier B exit-reason 분류가 쓴 것과 같은 패턴) - 이번
범위 밖.

신호 정의: 각 리밸런싱일 기준 최근 90일 내 그 종목의 임원·주요주주
지분변동 공시 중 증가(+)건수-감소(-)건수(breadth) - 원주식수 대비
비중(sp_stock_lmp_irds_rate)은 대부분 반올림돼 0.00으로 나와 대형주에서
쓸모없어(실측 확인) 원주수량 대신 건수 기반 breadth를 쓴다(academic
insider-trading literature의 표준 정의와 동일 - 매수/매도 "폭").

data/backfill/fundamentals/a3의 ticker<->corp 매핑을 재사용(새 매핑 없음).
DART_API_KEY는 .env에서 서브프로세스 환경변수로만 로드한다(대화 노출 없음).

  python insider_trading_precheck.py
"""
import gzip
import json
import os
import sys
import time
from datetime import date, timedelta

import requests

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import pandas as pd  # noqa: E402

from engine.data.a2aProvider import A2aProvider  # noqa: E402
from engine.data.calendar import TradingCalendar  # noqa: E402
from engine.runner import _drop_suspension_rows  # noqa: E402

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
A3_DIR = os.path.join(REPO_ROOT, "data", "backfill", "fundamentals", "a3")
OUT_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "insider-trading")
RAW_PATH = os.path.join(OUT_DIR, "elestock-raw.jsonl")
BASE = "https://opendart.fss.or.kr/api"
KEY = os.environ.get("DART_API_KEY", "")
SLEEP = 0.15
LOOKBACK_DAYS = 90
TOP_N = 30
COST_RT_BPS = 30.0
MIN_TURNOVER = 100_000_000.0
END = "2026-08-14"


def load_ticker_corp():
    pairs = {}
    for fname in sorted(os.listdir(A3_DIR)):
        if not fname.endswith(".jsonl.gz"):
            continue
        with gzip.open(os.path.join(A3_DIR, fname), "rt", encoding="utf-8") as f:
            for line in f:
                d = json.loads(line)
                pairs[d["ticker"]] = d["corp"]
    return pairs


def fetch_all():
    """corp별 elestock.json 1콜씩 - bgn_de/end_de 무시되므로 연도 루프 불필요."""
    ticker_corp = load_ticker_corp()
    os.makedirs(OUT_DIR, exist_ok=True)
    n_ok, n_empty, n_fail = 0, 0, 0
    t0 = time.time()
    with open(RAW_PATH, "w", encoding="utf-8") as out_f:
        for i, (ticker, corp) in enumerate(sorted(ticker_corp.items())):
            try:
                r = requests.get(f"{BASE}/elestock.json",
                                  params={"crtfc_key": KEY, "corp_code": corp}, timeout=(10, 30))
                body = r.json()
            except Exception:
                n_fail += 1
                time.sleep(SLEEP)
                continue
            if body.get("status") != "000":
                n_empty += 1
                time.sleep(SLEEP)
                continue
            for rec in body.get("list", []):
                cnt = rec.get("sp_stock_lmp_irds_cnt", "")
                try:
                    delta = int(str(cnt).replace(",", "").strip() or "0")
                except ValueError:
                    continue
                if delta == 0:
                    continue
                out_f.write(json.dumps({"ticker": ticker, "rcept_dt": rec["rcept_dt"],
                                        "delta": delta}, ensure_ascii=False) + "\n")
            n_ok += 1
            if n_ok % 300 == 0:
                out_f.flush()
                print(f"  progress {i+1}/{len(ticker_corp)} ok={n_ok} empty={n_empty} fail={n_fail} "
                      f"({time.time()-t0:.0f}s)")
            time.sleep(SLEEP)
    print(f"fetch done: ok={n_ok} empty={n_empty} fail={n_fail} ({time.time()-t0:.0f}s)")


def load_events():
    by_ticker = {}
    with open(RAW_PATH, encoding="utf-8") as f:
        for line in f:
            r = json.loads(line)
            d = date(int(r["rcept_dt"][:4]), int(r["rcept_dt"][5:7]), int(r["rcept_dt"][8:10]))
            by_ticker.setdefault(r["ticker"], []).append((d, r["delta"]))
    for tk in by_ticker:
        by_ticker[tk].sort()
    return by_ticker


def breadth_asof(events, as_of_str):
    """as_of 기준 최근 LOOKBACK_DAYS 내 증가건수-감소건수."""
    d1 = date.fromisoformat(as_of_str)
    d0 = d1 - timedelta(days=LOOKBACK_DAYS)
    window = [delta for d, delta in events if d0 <= d <= d1]
    if not window:
        return None
    return sum(1 for x in window if x > 0) - sum(1 for x in window if x < 0)


def monthly_rebalance_dates(calendar, start, end):
    days = calendar.sessions_between(start, end)
    out, seen = [], set()
    for d in days:
        ym = d[:7]
        if ym not in seen:
            seen.add(ym)
            out.append(d)
    return out


def build_panel(bars_by_ticker, rebalance_dates, events_by_ticker):
    rows = []
    for ticker, bars in bars_by_ticker.items():
        events = events_by_ticker.get(ticker)
        if not events or bars.empty or len(bars) < 30:
            continue
        close, open_, vol = bars["close"], bars["open"], bars["volume"]
        idx = close.index.astype(str)
        pos = {d: i for i, d in enumerate(idx)}
        turnover20 = (close * vol).rolling(20).mean()
        for k, t in enumerate(rebalance_dates[:-1]):
            breadth = breadth_asof(events, t)
            if breadth is None:
                continue
            i = pos.get(t)
            if i is None or i + 1 >= len(idx):
                continue
            entry_date = idx[i + 1]
            exit_date = rebalance_dates[k + 1]
            j = pos.get(exit_date)
            if j is None or j + 1 >= len(idx):
                continue
            entry_price, exit_price = float(open_.iloc[i + 1]), float(open_.iloc[j + 1])
            if entry_price <= 0 or exit_price <= 0:
                continue
            tv = turnover20.iloc[i]
            rows.append({
                "ticker": ticker, "entry_date": t, "breadth": int(breadth),
                "ret": exit_price / entry_price - 1,
                "turnover20": float(tv) if not pd.isna(tv) else 0.0,
            })
    return pd.DataFrame(rows)


def run_backtest(df, top_n=TOP_N, cost_bps=COST_RT_BPS, liquidity_filter=None, direction="high"):
    months = sorted(df["entry_date"].unique())
    month_rets = []
    for m in months:
        g = df[df["entry_date"] == m]
        if liquidity_filter == "high":
            g = g[g["turnover20"] >= MIN_TURNOVER]
        elif liquidity_filter == "low":
            g = g[g["turnover20"] < MIN_TURNOVER]
        g = g.sort_values("breadth", ascending=(direction == "low")).head(top_n)
        if g.empty:
            continue
        month_rets.append((m, (g["ret"] - cost_bps / 1e4).mean(), len(g)))
    mdf = pd.DataFrame(month_rets, columns=["month", "ret", "n"])
    eq, peak, maxdd = 100_000_000.0, 100_000_000.0, 0.0
    for _, row in mdf.iterrows():
        eq *= (1 + row["ret"])
        peak = max(peak, eq)
        maxdd = min(maxdd, eq / peak - 1)
    n_years = max(len(mdf) / 12.0, 1 / 12)
    cagr = (eq / 100_000_000.0) ** (1 / n_years) - 1 if len(mdf) else None
    return {
        "monthsTraded": len(mdf), "avgTickersPerMonth": round(mdf["n"].mean(), 1) if len(mdf) else None,
        "totalReturn": round(eq / 100_000_000.0 - 1, 4),
        "cagr": round(cagr, 4) if cagr is not None else None, "maxDD": round(maxdd, 4),
    }


def ic_by_breadth(df):
    """breadth 값 자체로 스피어만 랭크IC(월별) - decile 나누기엔 breadth가
    정수라 tie가 많아(대부분 -1~+1) qcut이 실패하므로 rank correlation 사용."""
    ics = []
    for m, g in df.groupby("entry_date"):
        if len(g) < 15 or g["breadth"].nunique() < 3:
            continue
        ic = g["breadth"].rank().corr(g["ret"].rank())
        if pd.notna(ic):
            ics.append(float(ic))
    sp = pd.Series(ics)
    t = sp.mean() / (sp.std() / (len(sp) ** 0.5)) if len(sp) > 1 and sp.std() > 0 else None
    return {"nMonths": len(sp), "meanMonthlyIC": round(float(sp.mean()), 4) if len(sp) else None,
            "t": round(float(t), 2) if t is not None else None}


def main():
    if not os.path.exists(RAW_PATH):
        print("raw elestock 데이터 없음 - 먼저 수집한다 (corp별 1콜, DART API)")
        fetch_all()
    else:
        print(f"기존 raw 재사용: {RAW_PATH}")

    events_by_ticker = load_events()
    print(f"insider 이벤트 있는 종목: {len(events_by_ticker)}")
    dates_all = [d for evs in events_by_ticker.values() for d, _ in evs]
    print(f"이벤트 날짜범위: {min(dates_all)} ~ {max(dates_all)} (총 {len(dates_all)}건)")

    tickers = sorted(events_by_ticker.keys())
    calendar = TradingCalendar(repo_root=REPO_ROOT)
    a2a = A2aProvider(repo_root=REPO_ROOT, use_cache=True)
    start = str(min(dates_all) - timedelta(days=120))
    bars_raw = a2a.load(tickers, start, END, universe_hash="insider-trading-precheck")
    bars_by_ticker = {t: _drop_suspension_rows(df) for t, df in bars_raw.items()}
    print(f"bars loaded: {len(bars_by_ticker)} tickers")

    rebalance_dates = monthly_rebalance_dates(calendar, start, END)
    df = build_panel(bars_by_ticker, rebalance_dates, events_by_ticker)
    print(f"panel rows={len(df)}, months={df['entry_date'].nunique() if len(df) else 0}")

    if df.empty:
        print("panel 비어있음 - 신호 정의나 데이터 확인 필요")
        return

    results = {
        "highBreadth_no_filter": run_backtest(df, direction="high", liquidity_filter=None),
        "highBreadth_high_liquidity": run_backtest(df, direction="high", liquidity_filter="high"),
        "lowBreadth_control_no_filter": run_backtest(df, direction="low", liquidity_filter=None),
    }
    for name, r in results.items():
        print(name, "->", json.dumps(r, ensure_ascii=False))
    ic = ic_by_breadth(df)
    print("월별 스피어만 랭크IC(breadth vs ret):", json.dumps(ic, ensure_ascii=False))

    out_dir = os.path.join(REPO_ROOT, "research", "strategy-lab", "reports",
                            "2026-08-28-insider-trading-precheck")
    os.makedirs(out_dir, exist_ok=True)
    out_path = os.path.join(out_dir, "insider-trading-precheck.json")
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump({
            "generatedAt": time.strftime("%Y-%m-%dT%H:%M:%S"),
            "context": "DART elestock.json(임원·주요주주 소유상황보고서) 내부자거래 breadth "
                       "신호 1차 정찰. **한계: elestock.json이 약 2년 롤링 윈도우만 반환**"
                       "(실측 확인, bgn_de/end_de 무시됨) - 이 프로젝트의 다른 10년 표본 "
                       "factor와 직접 비교 불가, 본격 검증 아닌 정찰.",
            "eventDateRange": f"{min(dates_all)} ~ {max(dates_all)}",
            "lookbackDays": LOOKBACK_DAYS, "topN": TOP_N, "costBps": COST_RT_BPS,
            "minTurnover": MIN_TURNOVER, "panelRows": len(df),
            "results": results, "rankIC": ic,
        }, f, ensure_ascii=False, indent=2, default=str)
    print("saved:", out_path)


if __name__ == "__main__":
    main()
