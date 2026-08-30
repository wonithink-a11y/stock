#!/usr/bin/env python
"""Panic -> Recovery 전략 (사용자 제안, 2026-08-28) - "공포 극단에서 즉시
매수"(stress_score_rebound_check.py, 실패)와 다른 가설: "공포 극단 뒤 가격이
더 이상 쉽게 안 빠진다는 증거가 나올 때"만 매수. 지표를 추가하지 않고 딱
2단계만 쓴다(사용자 지시 - 조건을 늘리면 Donchian+ATR TRAIN 3.67->OOS 붕괴와
같은 과최적화 함정).

  Stage 1 Panic     : drawdown percentile(expanding, PIT-safe) >= 0.80
  Stage 2 Recovery  : 종가 >= 최근 20일 저점 x 1.03
  Entry             : 무포지션 + Panic + Recovery 동시 충족
  Exit              : 종가 < 20일 이동평균(추세 약화) - 지표 추가 없음
  평소              : 현금(수익률 0%)

실제 상태기계로 일별 자본곡선을 구성 - Buy&Hold·현금대기 벤치마크와 CAGR/
MDD/Sharpe/Calmar/Time-in-Market 비교. Nasdaq100(1986~2026)을 TRAIN(전반부)/
TEST(후반부)로 쪼개 과최적화 여부 확인 후 S&P500(탐색적 참고치)도 본다.

production 변경 없음, 새 API 호출 없음.
"""
import numpy as np
import pandas as pd

from stress_score_rebound_check import DATA_DIR, WARMUP, expanding_pctrank

TRADING_DAYS = 252


def build(df):
    df = df.sort_values("date").reset_index(drop=True)
    close = df["value"]
    peak = close.cummax()
    df["peak"] = peak
    drawdown = close / peak - 1.0
    df["drawdown_pct"] = expanding_pctrank(-drawdown)
    df["panic"] = df["drawdown_pct"] >= 0.80
    low20 = close.rolling(20).min()
    df["recovery"] = close >= low20 * 1.03
    df["ma20"] = close.rolling(20).mean()
    df["ma50"] = close.rolling(50).mean()
    df["ret"] = close.pct_change()
    return df


def simulate(df, exit_ma_col="ma20"):
    """상태기계: in_position 동안만 시장 수익률, 아니면 현금(0%). 반환:
    strat_ret(일별), position_flag(일별), entries(진입일 리스트).
    exit_ma_col: 청산 기준 이동평균 컬럼 - 진입 로직(panic/recovery)은 불변,
    청산 민감도만 이 컬럼으로 바꾼다(사용자 지시 - 단일 변수 실험)."""
    close = df["value"].to_numpy()
    ret = df["ret"].to_numpy()
    panic = df["panic"].to_numpy()
    recovery = df["recovery"].to_numpy()
    ma20 = df[exit_ma_col].to_numpy()
    n = len(df)

    strat_ret = np.zeros(n)
    in_pos = np.zeros(n, dtype=bool)
    entries = []
    holding = False
    for i in range(1, n):
        if holding:
            strat_ret[i] = ret[i]
            in_pos[i] = True
            if not np.isnan(ma20[i]) and close[i] < ma20[i]:
                holding = False
        else:
            if panic[i] and recovery[i] and not np.isnan(panic[i]):
                holding = True
                in_pos[i] = True
                entries.append(i)
                # 진입 당일은 이미 회복된 종가 기준 진입이라 당일수익은 0 처리(익일부터 시장수익)
    return strat_ret, in_pos, entries


def equity_metrics(daily_ret, name):
    daily_ret = np.asarray(daily_ret, dtype=float)
    equity = np.cumprod(1 + daily_ret)
    n_days = len(daily_ret)
    years = n_days / TRADING_DAYS
    cagr = equity[-1] ** (1 / years) - 1 if years > 0 and equity[-1] > 0 else float("nan")
    running_max = np.maximum.accumulate(equity)
    dd = equity / running_max - 1.0
    mdd = dd.min()
    vol = daily_ret.std() * np.sqrt(TRADING_DAYS)
    sharpe = (daily_ret.mean() * TRADING_DAYS) / vol if vol > 0 else float("nan")
    calmar = cagr / abs(mdd) if mdd < 0 else float("nan")
    return {"name": name, "CAGR": cagr, "MDD": mdd, "Sharpe": sharpe, "Calmar": calmar,
            "finalEquity": equity[-1]}


def run_period(df, label, exit_ma_col="ma20"):
    df = df.reset_index(drop=True)
    strat_ret, in_pos, entries = simulate(df, exit_ma_col=exit_ma_col)
    bh_ret = df["ret"].fillna(0).to_numpy()

    print(f"\n=== {label} [exit={exit_ma_col}] | 기간 {df['date'].iloc[0].date()}~{df['date'].iloc[-1].date()} "
          f"({len(df)}일) ===")
    print(f"  진입 횟수: {len(entries)} | Time in Market: {in_pos.mean():.1%}")
    if len(entries) == 0:
        print("  진입 0건 - 평가 불가")
        return

    m_strat = equity_metrics(strat_ret, f"Panic->Recovery({exit_ma_col})")
    m_bh = equity_metrics(bh_ret, "Buy&Hold")
    m_cash = {"name": "Cash", "CAGR": 0.0, "MDD": 0.0, "Sharpe": float("nan"),
              "Calmar": float("nan"), "finalEquity": 1.0}

    for m in (m_strat, m_bh, m_cash):
        print(f"  {m['name']:18s} CAGR={m['CAGR']:+.2%} MDD={m['MDD']:.2%} "
              f"Sharpe={m['Sharpe']:.3f} Calmar={m['Calmar']:.3f} "
              f"finalEquity={m['finalEquity']:.2f}x")

    # 개별 진입 건의 보유기간·수익률 분포
    hold_days, hold_rets = [], []
    i = 0
    n = len(df)
    close = df["value"].to_numpy()
    in_pos_arr = in_pos
    while i < n:
        if in_pos_arr[i]:
            j = i
            while j < n and in_pos_arr[j]:
                j += 1
            hold_days.append(j - i)
            hold_rets.append(close[j - 1] / close[i] - 1.0)
            i = j
        else:
            i += 1
    if hold_days:
        print(f"  개별 트레이드 {len(hold_days)}건: 평균 보유 {np.mean(hold_days):.0f}일, "
              f"평균 수익 {np.mean(hold_rets):+.2%}, 승률 {np.mean([r > 0 for r in hold_rets]):.0%}")


def main():
    for name, path, datecol in [
        ("Nasdaq100", f"{DATA_DIR}/usnasdaq100_raw.parquet", "usableFromDate"),
        ("S&P500", f"{DATA_DIR}/ussp500_raw.parquet", "usableFromDate"),
    ]:
        raw = pd.read_parquet(path).rename(columns={datecol: "date"})
        raw["date"] = pd.to_datetime(raw["date"])
        df = build(raw)
        df_valid = df[df["drawdown_pct"].notna()].reset_index(drop=True)

        for exit_col in ("ma20", "ma50"):
            run_period(df_valid, f"{name} 전체기간", exit_ma_col=exit_col)

        if name == "Nasdaq100":
            mid = df_valid["date"].min() + (df_valid["date"].max() - df_valid["date"].min()) / 2
            train = df_valid[df_valid["date"] < mid]
            test = df_valid[df_valid["date"] >= mid]
            for exit_col in ("ma20", "ma50"):
                run_period(train, f"{name} TRAIN(전반부)", exit_ma_col=exit_col)
                run_period(test, f"{name} TEST(후반부)", exit_ma_col=exit_col)


if __name__ == "__main__":
    main()
