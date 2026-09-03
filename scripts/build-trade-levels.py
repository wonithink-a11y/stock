#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""종목별 손절가·목표가·수량 -> docs/data/trade-levels.json

config/policies/portfolio.v1.json(PF-1.0)의 규칙을, daily-analysis 가 이미 매일
쓰는 docs/data/prices.json(872종목 OHLCV 250일)에 적용하기만 한다 - 새 수집 없고
새 규칙도 없다. ATR 정의는 research/strategy-lab/engine/indicators/atr.py 와
같은 Wilder 방식이다(연구 엔진은 production 과 격리돼 있어 import 하지 않고
같은 정의를 여기 다시 쓴다 - 바뀌면 양쪽을 같이 고친다).

★ 이 파일은 '어디서 자르고 얼마나 사는가'만 낸다. '무엇을 사라'가 아니다.
   진입가 기준(entryZone)은 정책에서 null 이다 - 근거가 없어 안 만든다.

  python scripts/build-trade-levels.py
  python scripts/build-trade-levels.py --selftest
"""
import argparse
import json
import math
import os
from datetime import datetime, timezone, timedelta

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PRICES = os.path.join(ROOT, "docs", "data", "prices.json")
POLICY = os.path.join(ROOT, "config", "policies", "portfolio.v1.json")
OUT = os.path.join(ROOT, "docs", "data", "trade-levels.json")

KST = timezone(timedelta(hours=9))


def atr_wilder(high, low, close, period):
    """Wilder's ATR. 마지막 값만 필요하므로 시리즈를 만들지 않는다.
    bar 가 period+1 개 미만이면 None (모르는 것은 0이 아니다 - 교훈57)."""
    n = len(close)
    if n < period + 1:
        return None
    tr = []
    for i in range(1, n):
        pc = close[i - 1]
        tr.append(max(high[i] - low[i], abs(high[i] - pc), abs(low[i] - pc)))
    if len(tr) < period:
        return None
    val = sum(tr[:period]) / period
    for x in tr[period:]:
        val = (val * (period - 1) + x) / period
    return val


def levels_for(price, atr, p):
    """정책 하나를 가격·ATR 에 적용. 실패하면 None - 지어내지 않는다."""
    if price is None or atr is None or price <= 0 or atr <= 0:
        return None
    risk_per_share = p["stopMultiple"] * atr
    stop = price - risk_per_share
    if stop <= 0:
        return None            # ATR 이 가격만큼 큰 종목: 규칙이 성립하지 않는다
    target = price + p["rewardRisk"] * risk_per_share
    return {
        "price": round(price, 2),
        "atr14": round(atr, 2),
        "stop": round(stop, 2),
        "target": round(target, 2),
        "stopPct": round((stop / price - 1) * 100, 2),
        "targetPct": round((target / price - 1) * 100, 2),
        "riskPerShare": round(risk_per_share, 2),
    }


def position_pct(risk_per_share, price, risk_pct, max_pct):
    """이 종목이 계좌에서 차지할 비중(%). 손절폭이 좁을수록 커지므로 상한을 건다."""
    raw = risk_pct * price / risk_per_share
    return min(raw, max_pct)


def shares_per_million(risk_per_share, price, risk_pct, max_pct):
    """100만원을 계좌로 봤을 때 살 수량. 계좌 금액은 저장소에 적지 않는다."""
    budget = 1_000_000 * position_pct(risk_per_share, price, risk_pct, max_pct) / 100.0
    return int(math.floor(budget / price)) if price > 0 else 0


def min_capital(risk_per_share, price, risk_pct, max_pct):
    """1주라도 사려면 필요한 최소 계좌(원). '얼마면 사도 되나'의 실제 답이다."""
    pct = position_pct(risk_per_share, price, risk_pct, max_pct)
    return int(math.ceil(price / (pct / 100.0)))


def build(prices, policy):
    r, s = policy["risk"], policy["sizing"]
    out = {}
    skipped = 0
    for ticker, b in prices["byTicker"].items():
        atr = atr_wilder(b["h"], b["l"], b["c"], r["atrPeriod"])
        lv = levels_for(b["c"][-1] if b["c"] else None, atr, r)
        if lv is None:
            skipped += 1
            continue
        lv["name"] = b.get("name")
        lv["market"] = b.get("market")
        lv["asOf"] = b["d"][-1]
        # 원화 종목만 수량을 낸다. 미국 종목은 환율이 있어야 하는데 여기 없다.
        pct = position_pct(lv["riskPerShare"], lv["price"], s["riskPerTradePct"], s["maxPositionPct"])
        lv["positionPct"] = round(pct, 2)
        lv["capped"] = pct >= s["maxPositionPct"] - 1e-9
        if b.get("market") == "KR":
            lv["sharesPerMillionKRW"] = shares_per_million(
                lv["riskPerShare"], lv["price"], s["riskPerTradePct"], s["maxPositionPct"])
            lv["minCapitalKRW"] = min_capital(
                lv["riskPerShare"], lv["price"], s["riskPerTradePct"], s["maxPositionPct"])
        else:
            lv["sharesPerMillionKRW"] = None
            lv["minCapitalKRW"] = None
        out[ticker] = lv
    return out, skipped


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--selftest", action="store_true")
    args = ap.parse_args()
    if args.selftest:
        return selftest()

    with open(PRICES, encoding="utf-8") as f:
        prices = json.load(f)
    with open(POLICY, encoding="utf-8") as f:
        policy = json.load(f)

    by_ticker, skipped = build(prices, policy)
    r, s = policy["risk"], policy["sizing"]
    out = {
        "updatedAt": datetime.now(KST).isoformat(),
        "policy": policy["version"],
        "params": {
            "atrPeriod": r["atrPeriod"], "stopMultiple": r["stopMultiple"],
            "rewardRisk": r["rewardRisk"], "maxHoldingSessions": r["maxHoldingSessions"],
            "riskPerTradePct": s["riskPerTradePct"], "maxPositionPct": s["maxPositionPct"],
            "maxPositions": s["maxPositions"],
        },
        "entryZone": None,
        "status": policy.get("status", "UNKNOWN"),
        "note": "손절가·목표가·수량 기준일 뿐 매수 추천이 아니다. 진입가 기준은 근거가 없어 만들지 않았다.",
        "provisionalNote": "★ 손절 배수·손익비·보유기간은 검증에서 기각된 값이다"
                           "(findings/portfolio-exit-policy-validation-2026-09.md). "
                           "'지금 규칙대로면 어디서 잘리나'를 보여줄 뿐 이 값이 최선이라는 뜻이 아니다.",
        "tradeStateChecked": False,
        "tradeStateNote": "거래정지·상장폐지 필터(trading.v1.json blockedStates)는 아직 안 걸었다 - "
                          "docs/data/latest.json 에 tradeAllowed 필드가 없다. 화면에서 그 상태를 따로 확인한다.",
        "skippedTickers": skipped,
        "byTicker": by_ticker,
    }
    with open(OUT, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, separators=(",", ":"))
    print(f"wrote {OUT}  ({len(by_ticker)}종목, 제외 {skipped})")


def selftest():
    # TR 이 매일 정확히 10 인 시리즈 -> ATR = 10 (Wilder 든 SMA 든 같은 값)
    close = [1000] * 30
    high = [c + 5 for c in close]
    low = [c - 5 for c in close]
    atr = atr_wilder(high, low, close, 14)
    assert abs(atr - 10.0) < 1e-9, atr

    # 상승 시리즈로 Wilder 가 SMA 와 다른지 확인(정의가 바뀌면 여기서 걸린다)
    c2 = [1000 + i * 10 for i in range(30)]
    a2 = atr_wilder([c + 5 for c in c2], [c - 5 for c in c2], c2, 14)
    assert a2 is not None and 10.0 < a2 < 20.0, a2

    assert atr_wilder([1, 2], [1, 2], [1, 2], 14) is None      # bar 부족 -> None

    p = {"atrPeriod": 14, "stopMultiple": 2.0, "rewardRisk": 3.0}
    lv = levels_for(1000, 10, p)
    assert lv["stop"] == 980 and lv["target"] == 1060, lv      # 손절 -2ATR, 목표 +3R
    assert lv["riskPerShare"] == 20
    assert lv["stopPct"] == -2.0 and lv["targetPct"] == 6.0, lv

    assert levels_for(1000, 600, p) is None                    # stop<=0 이면 규칙 불성립
    assert levels_for(0, 10, p) is None and levels_for(1000, 0, p) is None

    # 가격 1000·손절폭 20 -> 비중 1%*1000/20 = 50% -> 상한 20% 로 잘린다
    assert position_pct(20, 1000, 1.0, 20.0) == 20.0
    assert position_pct(200, 1000, 1.0, 20.0) == 5.0           # 변동성 크면 적게 산다
    assert shares_per_million(200, 1000, 1.0, 20.0) == 50      # 100만*5% / 1000
    assert shares_per_million(60000, 300000, 1.0, 20.0) == 0   # 고가주는 100만원으로 0주
    assert min_capital(60000, 300000, 1.0, 20.0) == 6000000    # 비중 5% -> 30만/5% = 600만원

    prices = {"byTicker": {
        "005930": {"name": "삼성", "market": "KR", "d": ["20260101"] * 30,
                   "h": high, "l": low, "c": close},
        "AAPL": {"name": "Apple", "market": "US", "d": ["20260101"] * 30,
                 "h": high, "l": low, "c": close},
        "000000": {"name": "정지", "market": "KR", "d": ["20260101"] * 30,
                   "h": [0] * 30, "l": [0] * 30, "c": [0] * 30},
    }}
    pol = {"risk": p, "sizing": {"riskPerTradePct": 1.0, "maxPositionPct": 20.0, "maxPositions": 10}}
    bt, skipped = build(prices, pol)
    assert skipped == 1 and "000000" not in bt                 # o=h=l=0 거래정지 아티팩트
    assert bt["005930"]["capped"] is True                      # 1%*1000/20 = 50% -> 20% 로 캡
    assert bt["005930"]["sharesPerMillionKRW"] == 200           # 100만*20% / 1000
    assert bt["005930"]["minCapitalKRW"] == 5000                # 1000 / 20%
    assert bt["AAPL"]["sharesPerMillionKRW"] is None           # 환율 없음 -> null
    print("selftest ok (21건)")


if __name__ == "__main__":
    main()
