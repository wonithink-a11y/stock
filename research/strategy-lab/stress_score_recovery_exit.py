#!/usr/bin/env python
"""stress_score_panic_recovery.py 후속 - 사용자 질문(2026-08-28): "저점매수 후
원상복귀(진입 시점의 직전 고점 재돌파)되면 파는 게 낫지 않나?" 진입 로직은
완전히 동일(panic: drawdown percentile>=0.80, recovery: 20일 저점 대비 +3%),
청산만 "20일선/50일선 이탈" 대신 "진입일의 직전 고점(peak) 재돌파"로 교체 -
단일 변수 실험(MA20->MA50 때와 같은 원칙).

주의: 이 청산 규칙은 상승을 진입 시점 낙폭만큼으로 캡핑한다(고점 재돌파 후
Buy&Hold는 계속 복리로 가지만 이 전략은 그 지점에서 현금화) - 이론적으로
Buy&Hold를 이기기 더 어려운 구조일 수 있다. 회복까지 걸리는 기간이 매우 길 수
있어(닷컴버블 나스닥은 15년) max_hold로 상한을 두고, 상한에 걸려 강제청산된
거래 비율을 별도로 보고한다(원상복귀를 실제로 달성 못한 거래를 감추지 않음).

production 변경 없음, 새 API 호출 없음.
"""
import numpy as np
import pandas as pd

from stress_score_panic_recovery import build, equity_metrics
from stress_score_rebound_check import DATA_DIR

MAX_HOLD = 2500  # 약 10년 상한 - 못 도달하면 강제청산(별도 보고)


def simulate_recovery_exit(df, max_hold=MAX_HOLD):
    close = df["value"].to_numpy()
    ret = df["ret"].to_numpy()
    panic = df["panic"].to_numpy()
    recovery = df["recovery"].to_numpy()
    peak = df["peak"].to_numpy()
    n = len(df)

    strat_ret = np.zeros(n)
    in_pos = np.zeros(n, dtype=bool)
    entries = []
    hold_days_list = []
    capped_list = []
    holding = False
    target = entry_i = None
    for i in range(1, n):
        if holding:
            strat_ret[i] = ret[i]
            in_pos[i] = True
            reached = close[i] >= target
            timed_out = (i - entry_i) >= max_hold
            if reached or timed_out:
                holding = False
                hold_days_list.append(i - entry_i)
                capped_list.append(timed_out and not reached)
        else:
            if panic[i] and recovery[i]:
                holding = True
                in_pos[i] = True
                entries.append(i)
                entry_i = i
                target = peak[i]
    return strat_ret, in_pos, entries, hold_days_list, capped_list


def run_period(df, label):
    df = df.reset_index(drop=True)
    strat_ret, in_pos, entries, hold_days, capped = simulate_recovery_exit(df)
    bh_ret = df["ret"].fillna(0).to_numpy()

    print(f"\n=== {label} [exit=원상복귀] | 기간 {df['date'].iloc[0].date()}~{df['date'].iloc[-1].date()} "
          f"({len(df)}일) ===")
    print(f"  진입 횟수: {len(entries)} | Time in Market: {in_pos.mean():.1%}")
    if len(entries) == 0:
        print("  진입 0건 - 평가 불가")
        return

    m_strat = equity_metrics(strat_ret, "PanicRecovery(원상복귀청산)")
    m_bh = equity_metrics(bh_ret, "Buy&Hold")
    m_cash = {"name": "Cash", "CAGR": 0.0, "MDD": 0.0, "Sharpe": float("nan"),
              "Calmar": float("nan"), "finalEquity": 1.0}
    for m in (m_strat, m_bh, m_cash):
        print(f"  {m['name']:28s} CAGR={m['CAGR']:+.2%} MDD={m['MDD']:.2%} "
              f"Sharpe={m['Sharpe']:.3f} Calmar={m['Calmar']:.3f} finalEquity={m['finalEquity']:.2f}x")

    if hold_days:
        hd = np.array(hold_days)
        cap = np.array(capped)
        print(f"  완결된 트레이드 {len(hd)}건: 평균 보유 {hd.mean():.0f}일(중앙값 {np.median(hd):.0f}일, "
              f"최장 {hd.max()}일) | {MAX_HOLD}일 상한에 걸려 강제청산(원상복귀 실패) {cap.sum()}건 "
              f"({cap.mean():.0%})")
    still_open = len(entries) - len(hold_days)
    if still_open > 0:
        print(f"  기간 끝까지 미청산(아직 보유 중): {still_open}건")


def main():
    for name, path, datecol in [
        ("Nasdaq100", f"{DATA_DIR}/usnasdaq100_raw.parquet", "usableFromDate"),
        ("S&P500", f"{DATA_DIR}/ussp500_raw.parquet", "usableFromDate"),
    ]:
        raw = pd.read_parquet(path).rename(columns={datecol: "date"})
        raw["date"] = pd.to_datetime(raw["date"])
        df = build(raw)
        df_valid = df[df["drawdown_pct"].notna()].reset_index(drop=True)

        run_period(df_valid, f"{name} 전체기간")

        if name == "Nasdaq100":
            mid = df_valid["date"].min() + (df_valid["date"].max() - df_valid["date"].min()) / 2
            train = df_valid[df_valid["date"] < mid]
            test = df_valid[df_valid["date"] >= mid]
            run_period(train, f"{name} TRAIN(전반부)")
            run_period(test, f"{name} TEST(후반부)")


if __name__ == "__main__":
    main()
