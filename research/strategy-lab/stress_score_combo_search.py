#!/usr/bin/env python
"""stress_score_rebound_check.py 후속 - 사용자 지시(2026-08-28) 두 가지:
(1) GPT 제안대로 "RSI<30이면 매수"가 아니라 "RSI가 30 아래로 갔다가 다시
    위로 돌파할 때" 진입(떨어지는 칼날 완화 시도).
(2) 4개 스트레스 축의 어느 조합(2개·3개 동시)이 가장 잘 맞는지 탐색.

★ 경고를 결과보다 먼저 적는다: episode 표본이 자산당 3~28개뿐이다(주식
피킹 백테스트의 월별 리밸런싱 수백 건과 차원이 다르다). 15개 조합 x 4
자산 x 2개 horizon을 전부 비교하면 다중검정 문제가 커서, 표본이 가장 긴
Nasdaq100(1986~2026, n=28)만 전반부/후반부로 나눠 "전반부에서 고른 조합이
후반부에서도 버티는가"를 확인한다 - 이 프로젝트의 표준 절차(CAND1·PBR
combined 등, TRAIN에서 고르고 TEST는 보기만 함)와 동일. 다른 자산은 표본이
쪼갤 수 없을 만큼 적어 탐색적 참고치로만 본다.

production 변경 없음, 새 API 호출 없음.
"""
import itertools

import numpy as np
import pandas as pd

from stress_score_rebound_check import (
    DATA_DIR, WARMUP, rsi14, expanding_pctrank, newey_west_t,
)

AXES = ["drawdown", "rsi", "ma200", "vol"]


def build(df, vix=None, use_own_vol=False, rsi_mode="threshold"):
    df = df.sort_values("date").reset_index(drop=True)
    close = df["value"]
    peak = close.cummax()
    drawdown = close / peak - 1.0
    df["drawdown"] = expanding_pctrank(-drawdown) >= 0.9

    rsi = rsi14(close)
    if rsi_mode == "threshold":
        df["rsi"] = (expanding_pctrank(100 - rsi) >= 0.9)
    else:  # recover: RSI가 30 밑으로 갔다가 다시 30 위로 올라오는 날만 True
        below = rsi < 30
        df["rsi"] = (~below) & below.shift(1, fill_value=False)

    ma200 = close.rolling(200).mean()
    dev = close / ma200 - 1.0
    df["ma200"] = expanding_pctrank(-dev) >= 0.9

    if use_own_vol:
        ret = close.pct_change()
        vol20 = ret.rolling(20).std()
        df["vol"] = expanding_pctrank(vol20) >= 0.9
    else:
        v = vix.set_index("date")["value"].reindex(df["date"]).ffill().reset_index(drop=True)
        df["vol"] = expanding_pctrank(v) >= 0.9

    for h in (20, 60, 120):
        df[f"fwd_{h}"] = close.shift(-h) / close - 1.0
    return df


def episodes_for_combo(df, combo):
    trig = df[list(combo)].all(axis=1)
    is_start = trig & ~trig.shift(1, fill_value=False)
    return df[is_start].copy()


def eval_combo(df, combo, horizon=60):
    ep = episodes_for_combo(df, combo)
    trig = ep[f"fwd_{horizon}"].dropna()
    base = df[f"fwd_{horizon}"].dropna()
    if len(trig) < 5:
        return {"n": len(trig), "mean": None, "nwt": None, "excess": None}
    lag = max(1, horizon // 21)
    return {
        "n": len(trig),
        "mean": float(trig.mean()),
        "nwt": newey_west_t(trig.values, lag),
        "excess": float(trig.mean() - base.mean()),
        "winrate": float((trig > 0).mean()),
        "dates": ep["date"].tolist(),
    }


def all_combos():
    for size in (2, 3, 4):
        for c in itertools.combinations(AXES, size):
            yield c


def search(df, name, horizon=60, date_lo=None, date_hi=None, verbose=True):
    d = df
    if date_lo is not None:
        d = d[d["date"] >= date_lo]
    if date_hi is not None:
        d = d[d["date"] < date_hi]
    rows = []
    for combo in all_combos():
        r = eval_combo(d, combo, horizon)
        r["combo"] = "+".join(combo)
        rows.append(r)
    rows = [r for r in rows if r["mean"] is not None]
    rows.sort(key=lambda r: (r["nwt"] if r["nwt"] is not None else -99), reverse=True)
    if verbose:
        print(f"\n--- {name} d{horizon} 조합 순위 (기간 {d['date'].min().date() if len(d) else 'NA'}"
              f"~{d['date'].max().date() if len(d) else 'NA'}) ---")
        for r in rows[:8]:
            print(f"  {r['combo']:25s} n={r['n']:>3} mean={r['mean']:+.2%} "
                  f"NWt={r['nwt']} excess={r['excess']:+.2%} winrate={r.get('winrate', 0):.0%}")
    return rows


def main():
    vix = pd.read_parquet(f"{DATA_DIR}/vixcls_raw.parquet")
    vix["date"] = pd.to_datetime(vix["date"])

    print("=" * 90)
    print("1) RSI 방식 비교: threshold(<30) vs recover(<30 이후 재돌파)")
    print("=" * 90)
    for rsi_mode in ("threshold", "recover"):
        for name, path, datecol, use_own_vol in [
            ("KOSPI", f"{DATA_DIR}/krkospi_raw.parquet", "date", False),
            ("Nasdaq100", f"{DATA_DIR}/usnasdaq100_raw.parquet", "usableFromDate", False),
            ("S&P500", f"{DATA_DIR}/ussp500_raw.parquet", "usableFromDate", False),
        ]:
            df = pd.read_parquet(path).rename(columns={datecol: "date"})
            df["date"] = pd.to_datetime(df["date"])
            df = build(df, vix=vix, use_own_vol=use_own_vol, rsi_mode=rsi_mode)
            # score>=3 of 4 (원래 정의와 동일한 심각도, RSI 정의만 교체)
            score = df[AXES].sum(axis=1)
            trig = score >= 3
            is_start = trig & ~trig.shift(1, fill_value=False)
            ep = df[is_start]
            for h in (60, 120):
                trigv = ep[f"fwd_{h}"].dropna()
                basev = df[f"fwd_{h}"].dropna()
                if len(trigv) < 5:
                    print(f"  [{rsi_mode:9s}] {name:10s} d{h}: n={len(trigv)} (표본부족)")
                    continue
                lag = max(1, h // 21)
                t = newey_west_t(trigv.values, lag)
                print(f"  [{rsi_mode:9s}] {name:10s} d{h}: n={len(trigv):>2} mean={trigv.mean():+.2%} "
                      f"NWt={t} excess={trigv.mean()-basev.mean():+.2%}")

    print("\n" + "=" * 90)
    print("2) 4축 조합 탐색 (threshold RSI 기준, 2개/3개/4개 동시조건 전부)")
    print("=" * 90)

    dfs = {}
    for name, path, datecol, use_own_vol in [
        ("KOSPI", f"{DATA_DIR}/krkospi_raw.parquet", "date", False),
        ("Nasdaq100", f"{DATA_DIR}/usnasdaq100_raw.parquet", "usableFromDate", False),
        ("S&P500", f"{DATA_DIR}/ussp500_raw.parquet", "usableFromDate", False),
    ]:
        df = pd.read_parquet(path).rename(columns={datecol: "date"})
        df["date"] = pd.to_datetime(df["date"])
        dfs[name] = build(df, vix=vix, use_own_vol=use_own_vol, rsi_mode="threshold")

    for name, df in dfs.items():
        for h in (60, 120):
            search(df, name, horizon=h)

    print("\n" + "=" * 90)
    print("3) Nasdaq100 전반부(TRAIN)에서 고른 최선 조합을 후반부(TEST)에서 확인")
    print("   (표본이 쪼갤 수 있을 만큼 긴 유일한 자산 - 나머지는 탐색적 참고치일 뿐)")
    print("=" * 90)
    nq = dfs["Nasdaq100"]
    mid = nq["date"].min() + (nq["date"].max() - nq["date"].min()) / 2
    print(f"  분할점: {mid.date()} (TRAIN {nq['date'].min().date()}~{mid.date()}, "
          f"TEST {mid.date()}~{nq['date'].max().date()})")
    for h in (60, 120):
        train_rows = search(nq, "Nasdaq100-TRAIN", horizon=h, date_hi=mid, verbose=True)
        if not train_rows:
            continue
        best = train_rows[0]["combo"]
        print(f"  TRAIN 최선 조합: {best} (NWt={train_rows[0]['nwt']})")
        test_rows = search(nq, "Nasdaq100-TEST(all combos, for reference)", horizon=h, date_lo=mid, verbose=False)
        match = [r for r in test_rows if r["combo"] == best]
        if match:
            r = match[0]
            print(f"  -> 같은 조합의 TEST 성과: n={r['n']} mean={r['mean']:+.2%} "
                  f"NWt={r['nwt']} excess={r['excess']:+.2%}")
        else:
            print(f"  -> TEST 구간엔 이 조합의 episode가 5개 미만이라 판단 불가")


if __name__ == "__main__":
    main()
