#!/usr/bin/env python
"""V6 selection.json 오프라인 빌더 (strategies/pbr_value_v1/build_selection.py 패턴).

횡단면 스크리닝(외국인+기관 동시 순매수 + 매집가 +5% 이내)은 generate_signals(symbol,
features) 계약 안에서 계산할 수 없다 - nb_5d·매집단가는 그 종목의 OHLCV bars만 보는
compute_features가 만들 수 없는 값이므로. 이 스크립트가 한 번 오프라인으로 계산해
selection.json(ticker -> [{date, holdSessions}])으로 굽고, rule.py는 조회만 한다.
engine 코드는 건드리지 않는다.

조건 = v6_acc_price_signal_study.py와 동일 ([OBSERVED]):
  foreign_nb_5d > 0 AND inst_nb_5d > 0 AND close <= 1.05 * accPrice
  accPrice = 직전 5거래일 외국인+기관 총매수금액 합 / 총매수수량 합

  python build_selection.py            # 소표본 스모크용(30종목, seed=42 - V3 엔진 스모크와 동일 방법)
  python build_selection.py --all      # 유니버스 전체(스모크 아님)
"""
import json
import os
import random
import sys

_THIS_DIR = os.path.dirname(os.path.abspath(__file__))
_STRATEGY_LAB_DIR = os.path.dirname(os.path.dirname(_THIS_DIR))
sys.path.insert(0, _STRATEGY_LAB_DIR)

import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402

REPO_ROOT = os.path.dirname(os.path.dirname(_STRATEGY_LAB_DIR))
A4_PANEL = os.path.join(_STRATEGY_LAB_DIR, "data", "a4", "a4-research-dataset.parquet")
V6_CACHE_DIR = os.path.join(_STRATEGY_LAB_DIR, ".cache", "v6_acc_price")
OUT_PATH = os.path.join(_THIS_DIR, "selection.json")

PRICE_CAP = 1.05      # [OBSERVED] 매집가 대비 +5% 이내 (영상 명시 수치)
HOLD_SESSIONS = 20    # [ASSUMPTION] 영상 미지정 - study T+20 비교 정렬용 고정값
N_TICKERS = 30        # 소표본 스모크 규모
SEED = 42             # V3 엔진 스모크와 같은 표본 추출 방법


def load_screen():
    uni = set(pd.read_parquet(A4_PANEL, columns=["ticker"])["ticker"].unique())
    frames = []
    for year in range(2016, 2027):
        p = os.path.join(V6_CACHE_DIR, f"{year}.parquet")
        if not os.path.exists(p):
            continue
        d = pd.read_parquet(p)
        d["buyAmt"] = d["fBuyAmt"] + d["iBuyAmt"]
        d["buyVol"] = d["fBuyVol"] + d["iBuyVol"]
        frames.append(d.groupby(["ticker", "date"])[["buyAmt", "buyVol"]].sum().reset_index())
    flows = pd.concat(frames, ignore_index=True)

    df = pd.read_parquet(A4_PANEL, columns=["ticker", "date", "close", "foreign_nb_5d", "inst_nb_5d"])
    df = df.merge(flows, on=["ticker", "date"], how="left").sort_values(["ticker", "date"]).reset_index(drop=True)
    g = df.groupby("ticker")
    amt5 = g["buyAmt"].transform(lambda s: s.fillna(0).rolling(5, min_periods=1).sum())
    vol5 = g["buyVol"].transform(lambda s: s.fillna(0).rolling(5, min_periods=1).sum())
    df["accPrice"] = np.where(vol5 > 0, amt5 / vol5, np.nan)

    cond = ((df["foreign_nb_5d"] > 0) & (df["inst_nb_5d"] > 0)
            & df["accPrice"].notna() & (df["close"] <= PRICE_CAP * df["accPrice"]))
    return df[cond][["ticker", "date", "close", "accPrice"]]


def smoke_subset():
    from engine.data.universeProvider import UniverseProvider  # noqa: E402
    uni = UniverseProvider(repo_root=REPO_ROOT, include_delisted=False)
    rng = random.Random(SEED)
    return set(rng.sample(sorted(uni.tickers), N_TICKERS))


def build(tickers):
    scr = load_screen()
    scr = scr[scr["ticker"].isin(set(tickers))]
    selection = {}
    for ticker, g in scr.groupby("ticker"):
        rows = [{"date": d, "holdSessions": HOLD_SESSIONS} for d in sorted(g["date"])]
        if rows:
            selection[ticker] = rows

    with open(OUT_PATH, "w", encoding="utf-8") as f:
        json.dump({
            "generatedFrom": "build_selection.py",
            "period": "2016-01-04 ~ 2026-08-03",
            "screen": "foreign_nb_5d>0 & inst_nb_5d>0 & close<=1.05*accPrice(5d pooled buy VWAP)",
            "priceCap": PRICE_CAP,
            "holdSessions": HOLD_SESSIONS,
            "tickersInSubset": len(selection),
            "signalRows": int(sum(len(v) for v in selection.values())),
            "selection": selection,
        }, f, ensure_ascii=False, indent=2)
    print(f"saved: {OUT_PATH} ({len(selection)} tickers, "
          f"{sum(len(v) for v in selection.values())} signal dates)")


if __name__ == "__main__":
    tickers = smoke_subset() if "--all" not in sys.argv else None
    if tickers is None:
        from engine.data.universeProvider import UniverseProvider  # noqa: E402
        uni = UniverseProvider(repo_root=REPO_ROOT, include_delisted=False)
        tickers = sorted(uni.tickers)
    print(f"building selection for {len(tickers)} tickers")
    build(tickers)
