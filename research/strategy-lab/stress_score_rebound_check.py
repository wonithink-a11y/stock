#!/usr/bin/env python
"""ChatGPT 대화가 제안한 "여러 스트레스 지표 동시 극단값 → 반등매수" 아이디어의
1차 정찰 - "상시 투자 오버레이"가 아니라 "평소 현금 대기, 극단 하락시에만 일시
진입"이라는 별개 가설(사용자 확인, 2026-08-28). production 변경 없음, 새 API
호출 없음 - 기존 market-regime/crypto 패널만 재사용.

절대 threshold(GPT 원문의 "MDD -14%면 매수") 대신 자산별 expanding-window
percentile로 정의 - CLAUDE.md가 반복 강조하는 원칙(PBR/A5-3 등)과 동일.
Look-ahead 방지: 각 날짜의 percentile은 그 날짜까지의 데이터만으로 계산.

4개 스트레스 축(각 1점, 0~4):
  1. drawdown_pct   : 시작 이후 trailing peak 대비 낙폭의 |값|이 지금까지 분포에서 상위 10%
  2. rsi_low_pct    : RSI14가 낮은 정도(=100-RSI)가 지금까지 분포에서 상위 10%
  3. ma200_dev_pct  : price/MA200-1의 음수 크기가 지금까지 분포에서 상위 10%
  4. vol_pct        : KOSPI/Nasdaq100은 VIX percentile, BTC는 자체 20일 실현변동성
                      percentile(GPT 지적 - VIX를 BTC에 그대로 쓰면 안 됨)

trigger episode = score>=3인 날 중 "직전날 score<3"인 첫날만(같은 급락 구간
내 중복 트리거 제거 - 안 그러면 NW보정을 해도 과대평가된다).
"""
import numpy as np
import pandas as pd

DATA_DIR = "data/market-regime"
WARMUP = 500  # 최소 관측치 확보 전엔 percentile 불안정하므로 제외


def rsi14(close):
    delta = close.diff()
    gain = delta.clip(lower=0).rolling(14).mean()
    loss = (-delta.clip(upper=0)).rolling(14).mean()
    rs = gain / loss.replace(0, np.nan)
    return 100 - 100 / (1 + rs)


def expanding_pctrank(s):
    """각 시점까지의 값만으로 그 시점 값의 백분위(0~1)를 계산 - PIT-safe."""
    return s.expanding(min_periods=WARMUP).apply(
        lambda w: (w.iloc[:-1] < w.iloc[-1]).mean() if len(w) > 1 else np.nan, raw=False
    )


def build_features(df, vix=None, use_own_vol=False):
    df = df.sort_values("date").reset_index(drop=True)
    close = df["value"]
    peak = close.cummax()
    drawdown = close / peak - 1.0
    df["drawdown_pct"] = expanding_pctrank(-drawdown)  # 낙폭이 클수록(더 음수) 높은 percentile

    rsi = rsi14(close)
    df["rsi_low_pct"] = expanding_pctrank(100 - rsi)

    ma200 = close.rolling(200).mean()
    dev = close / ma200 - 1.0
    df["ma200_dev_pct"] = expanding_pctrank(-dev)

    if use_own_vol:
        ret = close.pct_change()
        vol20 = ret.rolling(20).std()
        df["vol_pct"] = expanding_pctrank(vol20)
    else:
        v = vix.set_index("date")["value"].reindex(df["date"]).ffill().reset_index(drop=True)
        df["vol_pct"] = expanding_pctrank(v)

    df["score"] = sum((df[c] >= 0.9).astype(int) for c in
                       ["drawdown_pct", "rsi_low_pct", "ma200_dev_pct", "vol_pct"])
    for h in (5, 20, 60, 120):
        df[f"fwd_{h}"] = close.shift(-h) / close - 1.0
    return df


def episodes(df, min_score):
    trig = df["score"] >= min_score
    is_start = trig & ~trig.shift(1, fill_value=False)
    return df[is_start].copy()


def newey_west_t(x, lag):
    x = np.asarray(x, dtype=float)
    x = x[~np.isnan(x)]
    n = len(x)
    if n < 5:
        return None
    e = x - x.mean()
    g0 = float(np.sum(e * e)) / n
    s = g0
    for l in range(1, min(lag, n - 1) + 1):
        w = 1.0 - l / (lag + 1.0)
        s += 2.0 * w * float(np.sum(e[l:] * e[:-l])) / n
    se = np.sqrt(max(s, 0.0) / n)
    return round(float(x.mean() / se), 3) if se > 0 else None


def report(name, df, min_score):
    ep = episodes(df, min_score)
    print(f"\n=== {name} | score>={min_score} | 표본기간 {df['date'].min().date()}~{df['date'].max().date()} ===")
    print(f"  episode 수: {len(ep)}")
    if len(ep) == 0:
        return
    for h in (5, 20, 60, 120):
        base = df[f"fwd_{h}"].dropna()
        trig = ep[f"fwd_{h}"].dropna()
        if len(trig) < 3:
            print(f"  d{h}: 표본 부족(n={len(trig)})")
            continue
        base_mean = base.mean()
        trig_mean = trig.mean()
        winrate = (trig > 0).mean()
        lag = max(1, h // 21)
        t = newey_west_t(trig.values, lag)
        print(f"  d{h:>3}: episode mean={trig_mean:+.2%} (n={len(trig)}, NWt={t}, winrate={winrate:.0%}) "
              f"| baseline mean={base_mean:+.2%} | excess={trig_mean - base_mean:+.2%}")


def main():
    vix = pd.read_parquet(f"{DATA_DIR}/vixcls_raw.parquet")
    vix["date"] = pd.to_datetime(vix["date"])

    assets = [
        ("KOSPI", f"{DATA_DIR}/krkospi_raw.parquet", "date", False),
        ("Nasdaq100", f"{DATA_DIR}/usnasdaq100_raw.parquet", "usableFromDate", False),
        ("S&P500", f"{DATA_DIR}/ussp500_raw.parquet", "usableFromDate", False),
    ]
    for name, path, datecol, use_own_vol in assets:
        df = pd.read_parquet(path).rename(columns={datecol: "date"})
        df["date"] = pd.to_datetime(df["date"])
        df = build_features(df, vix=vix, use_own_vol=use_own_vol)
        for ms in (3, 4):
            report(name, df, ms)

    btc = pd.read_parquet("data/crypto/daily/KRW-BTC.parquet").reset_index()
    print("\nBTC columns:", list(btc.columns))
    datecol = "date" if "date" in btc.columns else btc.columns[0]
    valcol = "close" if "close" in btc.columns else ("value" if "value" in btc.columns else btc.columns[-1])
    btc = btc.rename(columns={datecol: "date", valcol: "value"})[["date", "value"]]
    btc["date"] = pd.to_datetime(btc["date"])
    btc = build_features(btc, use_own_vol=True)
    for ms in (3, 4):
        report("BTC-KRW", btc, ms)


if __name__ == "__main__":
    main()
