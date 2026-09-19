#!/usr/bin/env python3
"""BTC 펀딩 캐리 — Portfolio Margin / Multi-Assets 설계 문서용 수치 재계산 (읽기 전용, 주문 없음).

    python research/strategy-lab/crypto_funding_carry_pm_analysis.py

설계 문서 `docs/control/펀딩캐리-PortfolioMargin-설계-2026-09-19.md` 의 §2·§5 숫자가 여기서 나온다.
입력은 로컬 `data/crypto/funding/BTCUSDT.parquet`·`data/crypto/basis/1h/BTCUSDT_1h.parquet`(gitignore, 로컬 전용).
모델은 단순화다: 현물 1 BTC(담보율 c 적용) + USDT-M 1 BTC 숏, 수량 고정(재조정 없음), 펀딩은 USDT 로 누적.
"""
import numpy as np
import pandas as pd
from pathlib import Path

D = Path(__file__).resolve().parent / "data" / "crypto"


def load():
    b = pd.read_parquet(D / "basis" / "1h" / "BTCUSDT_1h.parquet")
    b["time"] = pd.to_datetime(b["time"], utc=True)
    price = b.set_index("time")["mark_close"].astype(float)
    f = pd.read_parquet(D / "funding" / "BTCUSDT.parquet")["fundingRate"].astype(float)
    return price, f


def funding_stats(f: pd.Series) -> None:
    print("== 연도별 펀딩 수취(명목 대비 %, 단순합) / 음수 결제 비율")
    y = f.groupby(f.index.year).agg(["sum", lambda s: (s < 0).mean()])
    for yr, (s, n) in y.iterrows():
        print(f"  {yr}: {s * 100:6.2f}%   음수 {n * 100:4.1f}%")
    end = f.index[-1]
    print("== 최근 구간 연환산")
    for d in (30, 90, 180, 365, 730):
        w = f[f.index > end - pd.Timedelta(days=d)]
        print(f"  최근 {d:>3}일: {w.sum() * 365 / d * 100:6.2f}%   음수 {(w < 0).mean() * 100:5.1f}%")
    r = (f.rolling(270).sum() * 365 / 90 * 100).dropna()
    print(f"== 롤링 90일 연환산: 최소 {r.min():.2f} / 5% {r.quantile(.05):.2f} / 중앙 {r.median():.2f} / "
          f"95% {r.quantile(.95):.2f}   <0 비율 {(r < 0).mean() * 100:.1f}%  <3% 비율 {(r < 3).mean() * 100:.1f}%")
    cum = f.cumsum()
    print(f"== funding-only 누적 최대낙폭 {(cum - cum.cummax()).min() * 100:.2f}%p, 최악 30일 {f.rolling(90).sum().min() * 100:.2f}%")


def unimmr_stress(price: pd.Series, f: pd.Series) -> None:
    fh = f.copy()
    fh.index = fh.index.floor("h")
    fund = fh.groupby(level=0).sum().reindex(price.index).fillna(0.0)
    i0 = int(np.argmax(price.index >= pd.Timestamp("2019-12-23 11:00", tz="UTC")))
    p, fu = price.iloc[i0:], fund.iloc[i0:]
    p0 = p.iloc[0]
    cumf = (fu * p).cumsum()
    print(f"== uniMMR 스트레스 (2019-12 진입, BTC {p0:,.0f} → 최고 {p.max():,.0f}) — 재조정 없음")
    print("  담보율   MMR   추가버퍼  최저uniMMR")
    for c in (0.95, 0.90, 0.80, 0.70):
        for mmr in (0.005, 0.01, 0.025):
            for buf in (0.0, 0.10):
                eq = np.minimum(p * c, p) + (buf * p0 - (p - p0) + cumf)
                print(f"  {c:.2f}  {mmr * 100:4.1f}%  {buf * 100:4.0f}%   {(eq / (mmr * p)).min():8.2f}")


def negative_balance_drag(price: pd.Series, f: pd.Series) -> None:
    fh = f.copy()
    fh.index = fh.index.floor("h")
    fund = fh.groupby(level=0).sum().reindex(price.index).fillna(0.0)
    print("== 1년 정적 보유 시 USDT 음수잔고와 이자 부담(연 r 가정, 명목 대비 %p)")
    print("  진입     BTC변화%  funding%  최대음수잔고%  이자10%APR  이자20%APR")
    for start in pd.date_range("2020-01-01", "2025-08-01", freq="6MS", tz="UTC"):
        i0 = int(np.argmax(price.index >= start))
        i1 = min(i0 + 8760, len(price) - 1)
        p, fu = price.iloc[i0:i1 + 1], fund.iloc[i0:i1 + 1]
        p0 = p.iloc[0]
        cumf = (fu * p).cumsum()
        neg = (-(-(p - p0) + cumf)).clip(lower=0)
        i10 = neg.sum() * 0.10 / 8760 / p0 * 100
        print(f"  {start:%Y-%m}  {(p.iloc[-1] / p0 - 1) * 100:8.1f}  {cumf.iloc[-1] / p0 * 100:8.1f}  "
              f"{neg.max() / p0 * 100:12.1f}  {i10:9.2f}  {i10 * 2:9.2f}")


if __name__ == "__main__":
    px, fr = load()
    funding_stats(fr)
    unimmr_stress(px, fr)
    negative_balance_drag(px, fr)
