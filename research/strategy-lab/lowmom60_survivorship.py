#!/usr/bin/env python
"""LOWMOM60 survivorship 재검증 — A1A_A1B_MERGED 유니버스 (생존 + 상장폐지).

기존 LOWMOM60(60D 저모멘텀 top-30 월 리밸런스)은 A1A_ONLY(현재 상장 종목)로 계산되어
survivorship bias가 알파를 부풀리는 방향이었다. 상장폐지 종목(A1B)을 A2b 가격과 병합한
유니버스로 같은 백테스트를 재실행해 그 차이를 정량화한다.

메커니즘 (PIT 준수):
  리밸런스일 t: t 종가까지 데이터로 mom60 계산 → 저모멘텀 상위 top-30 선정
  진입: t 다음 거래일 시가(t+1 open). 청산: 다음 리밸런스 t+1 open 전체 교체.
  상장폐지 종목은 데이터가 끝나면(exitAt 이후) 더 이상 진입 불가 — 이전 보유분은
  마지막 가격으로 청산 (자연 종료). 거래비용 roundTrip 30bps.

결과 비교:
  A1A_ONLY (기존) vs A1A_A1B_MERGED (survivorship 제거) — CAGR/MDD/승률/PF/연도별.
"""
import gzip
import json
import os
import sys

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from engine.data.a2aProvider import A2aProvider  # noqa: E402
from engine.data.calendar import TradingCalendar  # noqa: E402
from engine.data.universeProvider import UniverseProvider  # noqa: E402
from engine.runner import _drop_suspension_rows  # noqa: E402

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
START = "2016-01-01"
END = "2026-08-14"
TOP_N = 30
COST_RT_BPS = 30.0
INITIAL_CAPITAL = 100_000_000.0
A2B_DIR = os.path.join(REPO_ROOT, "data", "backfill", "price", "a2b")
A2B_SCHEMA = ("ticker", "date", "open", "high", "low", "close", "volume")
A2B_QUALITY_EXCLUDED = "price-quality-excluded.jsonl.gz"
A2B_SKIP_FILES = {"price-quality-excluded.jsonl.gz", "delisted-exit.jsonl.gz"}


def load_a2b(a1b_tickers):
    """A2b 연도별 jsonl.gz에서 A1B 종목만 읽는다. quality-excluded 파일은 제외."""
    a1b_tickers = set(a1b_tickers)
    buffers = {t: [] for t in a1b_tickers}
    files = [f for f in os.listdir(A2B_DIR) if f.endswith(".jsonl.gz") and f not in A2B_SKIP_FILES]
    for fn in sorted(files):
        with gzip.open(os.path.join(A2B_DIR, fn), "rt", encoding="utf-8") as f:
            for line in f:
                row = json.loads(line)
                t = row["ticker"]
                if t not in buffers:
                    continue
                missing = [k for k in A2B_SCHEMA if k not in row]
                if missing:
                    raise ValueError(f"A2b schema violation: missing {missing} ({t} {row.get('date')})")
                buffers[t].append(row)
    result = {}
    for t, rows in buffers.items():
        if not rows:
            continue
        df = pd.DataFrame(rows)
        df["date"] = pd.to_datetime(df["date"])
        df = df.sort_values("date").set_index("date")
        for col in ("open", "high", "low", "close"):
            df[col] = df[col].astype("float64")
        df["volume"] = df["volume"].astype("int64")
        result[t] = df[["open", "high", "low", "close", "volume"]]
    return result


def monthly_rebalance_dates(calendar, start, end):
    days = calendar.sessions_between(start, end)
    out, seen = [], set()
    for d in days:
        ym = d[:7]
        if ym not in seen:
            seen.add(ym)
            out.append(d)
    return out


def run_backtest(bars_by_ticker, rebalance_dates, factor="mom60", ascending=True,
                 min_price=0, min_turnover=0, cost_bps=COST_RT_BPS):
    """factor 기준 정렬 top-30 월 리밸런스 (기본: mom60 저모멘텀 ascending=True,
    REV20은 factor='rev20', ascending=False). 종목별 월 선택 후 t+1 open 진입/청산.
    진입·청산가 모두 't 이후 첫 거래일 open' — 거래정지 종목은 그 다음
    거래일로 처리. 거래 불가 시 종목 제외."""
    if factor == "rev20":
        ffn = lambda df: -(df["close"] / df["close"].shift(20) - 1)
    else:
        ffn = lambda df: df["close"] / df["close"].shift(60) - 1
    # panel: (ticker, t) -> factor, turnover20, avgclose20, entry_price, exit_price
    rows = []
    for ticker, bars in bars_by_ticker.items():
        if bars.empty or len(bars) < 260:
            continue
        close = bars["close"]
        open_ = bars["open"]
        vol = bars["volume"]
        idx = close.index.astype(str)
        pos = {d: i for i, d in enumerate(idx)}
        fv = ffn(bars)
        turnover20 = (close * vol).rolling(20).mean()
        avgclose20 = close.rolling(20).mean()
        for k, t in enumerate(rebalance_dates[:-1]):
            i = pos.get(t)
            if i is None or i + 1 >= len(idx):
                continue
            m = fv.iloc[i]
            if pd.isna(m):
                continue
            exit_date = rebalance_dates[k + 1]
            j = pos.get(exit_date)
            if j is None or j + 1 >= len(idx):
                continue  # 상장폐지 등으로 다음 리밸런스 이후 거래 없음 → 미진입
            ep = float(open_.iloc[i + 1])
            xp = float(open_.iloc[j + 1])
            if ep <= 0 or xp <= 0:
                continue
            rows.append({
                "ticker": ticker, "entry_date": t, "factor": float(m),
                "ret": xp / ep - 1,
                "turnover20": float(turnover20.iloc[i]) if not pd.isna(turnover20.iloc[i]) else 0.0,
                "avgclose20": float(avgclose20.iloc[i]) if not pd.isna(avgclose20.iloc[i]) else 0.0,
            })
    df = pd.DataFrame(rows)
    if df.empty:
        return None
    sub = df[(df["turnover20"] >= min_turnover) & (df["avgclose20"] >= min_price)]
    months = sorted(sub["entry_date"].unique())
    mrets = []
    for m in months:
        g = sub[sub["entry_date"] == m].sort_values("factor", ascending=ascending).head(TOP_N)
        if g.empty:
            continue
        mrets.append((m, (g["ret"] - cost_bps / 1e4).mean()))
    mdf = pd.DataFrame(mrets, columns=["month", "ret"])
    eq = INITIAL_CAPITAL
    curve = []
    peak = eq
    maxdd = 0.0
    for _, r in mdf.iterrows():
        eq *= (1 + r["ret"])
        peak = max(peak, eq)
        maxdd = min(maxdd, eq / peak - 1)
        curve.append((r["month"], eq))
    eq_df = pd.DataFrame(curve, columns=["month", "equity"])
    years = eq_df["month"].str[:4]
    n_years = len(years.unique())
    total_return = eq_df["equity"].iloc[-1] / INITIAL_CAPITAL - 1
    cagr = (eq_df["equity"].iloc[-1] / INITIAL_CAPITAL) ** (1 / n_years) - 1 if n_years else None
    yearly = {}
    for y, g in eq_df.groupby(years):
        yearly[y] = round(float(g["equity"].iloc[-1] / g["equity"].iloc[0] - 1), 4)
    raw_rets = sub["ret"] - cost_bps / 1e4  # 전체 panel (선택 포함) 대신 실제 선택된 것만
    return {
        "n_months": len(mdf),
        "n_selected_rows": len(sub),
        "totalReturn": round(float(total_return), 4),
        "cagr": round(float(cagr), 4) if cagr else None,
        "maxDrawdown": round(float(maxdd), 4),
        "yearly": yearly,
        "finalEquity": round(float(eq_df["equity"].iloc[-1]), 0),
    }


def main():
    # A1A_ONLY 유니버스
    universe_a1a = UniverseProvider(repo_root=REPO_ROOT, include_delisted=False)
    # A1A_A1B_MERGED 유니버스
    universe_merged = UniverseProvider(repo_root=REPO_ROOT, include_delisted=True)

    calendar = TradingCalendar(repo_root=REPO_ROOT)
    rebalance_dates = monthly_rebalance_dates(calendar, START, END)

    a2a = A2aProvider(repo_root=REPO_ROOT, use_cache=True)

    # --- A1A_ONLY ---
    print("Loading A1A_ONLY bars...")
    a1a_tickers = {e.ticker for e in universe_a1a.entries}
    bars_a1a = a2a.load(a1a_tickers, START, END, universe_hash=universe_a1a.universe_hash)
    bars_a1a = {t: _drop_suspension_rows(df) for t, df in bars_a1a.items()}
    res_a1a = run_backtest(bars_a1a, rebalance_dates, factor="mom60", ascending=True)
    print("=== A1A_ONLY (생존 종목, 기존 결과와 동일 방법) ===")
    print(json.dumps(res_a1a, ensure_ascii=False, indent=2))

    # --- A1A_A1B_MERGED ---
    print("\nLoading A2b (상장폐지) bars...")
    a1b_tickers = {e.ticker for e in universe_merged.entries if e.source == "A1B"}
    bars_a1b = load_a2b(a1b_tickers)
    print(f"A1B tickers={len(a1b_tickers)}, A2b loaded={len(bars_a1b)}")
    merged = dict(bars_a1a)
    merged.update(bars_a1b)
    res_merged = run_backtest(merged, rebalance_dates, factor="mom60", ascending=True)
    print("=== A1A_A1B_MERGED (생존 + 상장폐지, survivorship 제거) ===")
    print(json.dumps(res_merged, ensure_ascii=False, indent=2))

    # 가격 필터 하 survivorship 재확인
    print("\n--- minPrice=5000 필터 재검증 (LOWMOM60) ---")
    res_a1a_p5 = run_backtest(bars_a1a, rebalance_dates, factor="mom60", ascending=True, min_price=5000)
    res_mrg_p5 = run_backtest(merged, rebalance_dates, factor="mom60", ascending=True, min_price=5000)
    print("A1A_ONLY  minPrice>=5000:", json.dumps({k: res_a1a_p5[k] for k in ("totalReturn", "cagr", "maxDrawdown")}))
    print("A1A_A1B_MERGED minPrice>=5000:", json.dumps({k: res_mrg_p5[k] for k in ("totalReturn", "cagr", "maxDrawdown")}))

    # --- REV20 survivorship 재검증 ---
    print("\n=== REV20 survivorship 재검증 ===")
    res_rev_a1a = run_backtest(bars_a1a, rebalance_dates, factor="rev20", ascending=False)
    res_rev_mrg = run_backtest(merged, rebalance_dates, factor="rev20", ascending=False)
    print("REV20 A1A_ONLY:      ", json.dumps({k: res_rev_a1a[k] for k in ("totalReturn", "cagr", "maxDrawdown")}))
    print("REV20 A1A_A1B_MERGED:", json.dumps({k: res_rev_mrg[k] for k in ("totalReturn", "cagr", "maxDrawdown")}))
    res_rev_mrg_p5 = run_backtest(merged, rebalance_dates, factor="rev20", ascending=False, min_price=5000)
    print("REV20 MERGED minPrice>=5000:", json.dumps({k: res_rev_mrg_p5[k] for k in ("totalReturn", "cagr", "maxDrawdown")}))

    out_dir = os.path.join(REPO_ROOT, "research", "strategy-lab", "reports", "2026-08-18-strategy-candidates")
    os.makedirs(out_dir, exist_ok=True)
    out_path = os.path.join(out_dir, "lowmom60_survivorship.json")
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump({
            "LOWMOM60": {"A1A_ONLY": res_a1a, "A1A_A1B_MERGED": res_merged,
                         "minPrice5000": {"A1A_ONLY": res_a1a_p5, "A1A_A1B_MERGED": res_mrg_p5}},
            "REV20": {"A1A_ONLY": res_rev_a1a, "A1A_A1B_MERGED": res_rev_mrg,
                      "minPrice5000_MERGED": res_rev_mrg_p5},
            "config": {"topN": TOP_N, "costBps": COST_RT_BPS, "start": START, "end": END,
                       "a2bNote": f"A1B {len(a1b_tickers)}종목 중 A2b 데이터 로드 {len(bars_a1b)}종목 (나머지는 아직 미수집/quality-excluded)",
                       "method": "월 리밸런스 top-30, t+1 open 진입/청산, 상장폐지 종목은 다음 리밸런스 이후 거래 없으면 미진입"},
        }, f, ensure_ascii=False, indent=2)
    print(f"\nSaved: {out_path}")


if __name__ == "__main__":
    main()
