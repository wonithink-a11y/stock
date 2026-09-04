#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""종목별 손절가·목표가·수량 -> docs/data/trade-levels.json

config/policies/portfolio.v1.json(PF-1.2, 미발효)의 규칙을, daily-analysis 가 이미 매일
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


def effective_exit(policy):
    """PF-1.1: 기본은 리밸런싱 청산이라 가격 기반 손절가가 없다. 낙폭축소 변형이
    켜져 있을 때만 그 값을 쓴다 - 정책이 안 정한 값을 지어내지 않는다(절대 규칙 1)."""
    e = policy["exit"]
    v = e.get("drawdownReductionVariant") or {}
    if e.get("stopMultiple") is not None:
        return {"atrPeriod": e.get("atrPeriod", v.get("atrPeriod", 14)),
                "stopMultiple": e["stopMultiple"], "rewardRisk": e.get("rewardRisk"),
                "source": "exit"}
    if v.get("enabled"):
        return {"atrPeriod": v.get("atrPeriod", 14), "stopMultiple": v["stopMultiple"],
                "rewardRisk": v.get("rewardRisk"), "source": "drawdownReductionVariant"}
    return {"atrPeriod": v.get("atrPeriod", 14), "stopMultiple": None, "rewardRisk": None,
            "source": e.get("mode", "rebalance_only")}


def effective_sizing(policy):
    """riskPerTradePct 가 null 이면 균등금액(PF-1.1 확정값)."""
    s = policy["sizing"]
    if s.get("riskPerTradePct") is not None:
        return {"mode": "risk_parity", "riskPerTradePct": s["riskPerTradePct"],
                "maxPositionPct": s["maxPositionPct"], "maxPositions": s["maxPositions"]}
    n = s["maxPositions"]
    return {"mode": "equal_notional", "riskPerTradePct": None,
            "maxPositionPct": 100.0 / n, "maxPositions": n}


def levels_for(price, atr, p):
    """정책 하나를 가격·ATR 에 적용. 가격/ATR 이 못 쓸 값이면 None - 지어내지 않는다.
    손절 규칙 자체가 없으면(stopMultiple=None) stop/target 을 null 로 낸다 -
    가격과 ATR 은 여전히 유효한 사실이므로 종목을 버리지는 않는다."""
    if price is None or atr is None or price <= 0 or atr <= 0:
        return None
    base = {"price": round(price, 2), "atr14": round(atr, 2),
            "atrPct": round(atr / price * 100, 2)}
    if p.get("stopMultiple") is None:
        base.update({"stop": None, "target": None, "stopPct": None,
                     "targetPct": None, "riskPerShare": None})
        return base
    risk_per_share = p["stopMultiple"] * atr
    stop = price - risk_per_share
    if stop <= 0:
        return None            # ATR 이 가격만큼 큰 종목: 규칙이 성립하지 않는다
    target = price + p["rewardRisk"] * risk_per_share
    base.update({
        "stop": round(stop, 2),
        "target": round(target, 2),
        "stopPct": round((stop / price - 1) * 100, 2),
        "targetPct": round((target / price - 1) * 100, 2),
        "riskPerShare": round(risk_per_share, 2),
    })
    return base


def position_pct(risk_per_share, price, sizing):
    """이 종목이 계좌에서 차지할 비중(%)."""
    if sizing["mode"] == "equal_notional":
        return sizing["maxPositionPct"]          # 1/N, 종목 특성과 무관하다
    raw = sizing["riskPerTradePct"] * price / risk_per_share
    return min(raw, sizing["maxPositionPct"])


def shares_per_million(risk_per_share, price, sizing):
    """100만원을 계좌로 봤을 때 살 수량. 계좌 금액은 저장소에 적지 않는다."""
    budget = 1_000_000 * position_pct(risk_per_share, price, sizing) / 100.0
    return int(math.floor(budget / price)) if price > 0 else 0


def min_capital(risk_per_share, price, sizing):
    """1주라도 사려면 필요한 최소 계좌(원). '얼마면 사도 되나'의 실제 답이다."""
    pct = position_pct(risk_per_share, price, sizing)
    # round 를 먼저 건다 - 1/N 같은 파생 비율은 부동소수 오차로 30000 이 30000.000000004
    # 가 되고 ceil 이 그걸 30001 로 올린다(실측).
    return int(math.ceil(round(price / (pct / 100.0), 6)))


def build(prices, policy):
    r, s = effective_exit(policy), effective_sizing(policy)
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
        pct = position_pct(lv["riskPerShare"], lv["price"], s)
        lv["positionPct"] = round(pct, 2)
        lv["capped"] = s["mode"] == "risk_parity" and pct >= s["maxPositionPct"] - 1e-9
        # 원화 종목만 수량을 낸다. 미국 종목은 환율이 있어야 하는데 여기 없다.
        if b.get("market") == "KR":
            lv["sharesPerMillionKRW"] = shares_per_million(lv["riskPerShare"], lv["price"], s)
            lv["minCapitalKRW"] = min_capital(lv["riskPerShare"], lv["price"], s)
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
    r, s = effective_exit(policy), effective_sizing(policy)
    out = {
        "updatedAt": datetime.now(KST).isoformat(),
        "policy": policy["version"],
        "params": {
            "atrPeriod": r["atrPeriod"], "stopMultiple": r["stopMultiple"],
            "rewardRisk": r["rewardRisk"], "exitSource": r["source"],
            "maxHoldingSessions": policy["exit"].get("maxHoldingSessions"),
            "sizingMode": s["mode"], "riskPerTradePct": s["riskPerTradePct"],
            "maxPositionPct": s["maxPositionPct"], "maxPositions": s["maxPositions"],
        },
        "entryZone": None,
        "status": policy.get("status", "UNKNOWN"),
        "note": "수량·비중 기준일 뿐 매수 추천이 아니다. 진입가 기준은 근거가 없어 만들지 않았다.",
        "provisionalNote": ("★ " + str(policy.get("version", "이 정책")) + " 은 가격 기반 손절·목표를 두지 않는다(exitSource="
                            + str(r["source"]) + ") - OOS 검증에서 손절 초안값이 기각됐고 "
                            "TEST 최선이 무손절이었다(findings/tier2-exit-policy-oos-2026-09.md). "
                            "stop/target 이 null 인 것은 결측이 아니라 정책이 그렇게 정한 것이다. "
                            "낙폭 축소가 목적이면 drawdownReductionVariant 를 켜면 값이 나온다."
                            if r["stopMultiple"] is None else
                            "★ 이 손절·목표 값은 정책 파일이 명시적으로 켠 것이다 - "
                            "수익이 아니라 낙폭 축소가 근거다."),
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

    # --- 손절 규칙이 켜져 있을 때 (drawdownReductionVariant 또는 명시값)
    p = {"atrPeriod": 14, "stopMultiple": 2.0, "rewardRisk": 3.0}
    lv = levels_for(1000, 10, p)
    assert lv["stop"] == 980 and lv["target"] == 1060, lv      # 손절 -2ATR, 목표 +3R
    assert lv["riskPerShare"] == 20 and lv["atrPct"] == 1.0, lv
    assert lv["stopPct"] == -2.0 and lv["targetPct"] == 6.0, lv
    assert levels_for(1000, 600, p) is None                    # stop<=0 이면 규칙 불성립
    assert levels_for(0, 10, p) is None and levels_for(1000, 0, p) is None

    # --- 손절 규칙이 없을 때(PF-1.1 기본): 종목을 버리지 않고 stop/target 만 null
    p0 = {"atrPeriod": 14, "stopMultiple": None, "rewardRisk": None}
    lv0 = levels_for(1000, 10, p0)
    assert lv0["price"] == 1000 and lv0["atr14"] == 10, lv0
    assert lv0["stop"] is None and lv0["target"] is None, lv0
    assert lv0["riskPerShare"] is None, lv0
    assert levels_for(1000, 600, p0)["stop"] is None            # 손절이 없으니 stop<=0 도 없다

    # --- 정책 해석기
    pol_rebal = {"exit": {"mode": "rebalance_only", "stopMultiple": None,
                          "drawdownReductionVariant": {"enabled": False, "stopMultiple": 3.0,
                                                       "rewardRisk": 1.5, "atrPeriod": 14}},
                 "sizing": {"riskPerTradePct": None, "maxPositions": 30}}
    e = effective_exit(pol_rebal)
    assert e["stopMultiple"] is None and e["source"] == "rebalance_only", e
    pol_dd = json.loads(json.dumps(pol_rebal))
    pol_dd["exit"]["drawdownReductionVariant"]["enabled"] = True
    e2 = effective_exit(pol_dd)
    assert e2["stopMultiple"] == 3.0 and e2["rewardRisk"] == 1.5, e2
    assert e2["source"] == "drawdownReductionVariant", e2

    sz = effective_sizing(pol_rebal)
    assert sz["mode"] == "equal_notional" and abs(sz["maxPositionPct"] - 100 / 30) < 1e-9, sz
    sz2 = effective_sizing({"sizing": {"riskPerTradePct": 1.0, "maxPositionPct": 20.0,
                                        "maxPositions": 10}})
    assert sz2["mode"] == "risk_parity", sz2

    # --- 비중·수량
    assert position_pct(20, 1000, sz2) == 20.0                 # 1%*1000/20=50% -> 상한 20%
    assert position_pct(200, 1000, sz2) == 5.0                 # 변동성 크면 적게 산다
    assert shares_per_million(200, 1000, sz2) == 50            # 100만*5% / 1000
    assert shares_per_million(60000, 300000, sz2) == 0         # 고가주는 100만원으로 0주
    assert min_capital(60000, 300000, sz2) == 6000000          # 비중 5% -> 30만/5% = 600만원
    # 균등금액은 종목 특성과 무관하게 1/N 이다
    assert position_pct(None, 1000, sz) == sz["maxPositionPct"]
    assert min_capital(None, 1000, sz) == 30000                # 가격 x maxPositions

    prices = {"byTicker": {
        "005930": {"name": "삼성", "market": "KR", "d": ["20260101"] * 30,
                   "h": high, "l": low, "c": close},
        "AAPL": {"name": "Apple", "market": "US", "d": ["20260101"] * 30,
                 "h": high, "l": low, "c": close},
        "000000": {"name": "정지", "market": "KR", "d": ["20260101"] * 30,
                   "h": [0] * 30, "l": [0] * 30, "c": [0] * 30},
    }}
    pol = {"exit": {"mode": "manual", "stopMultiple": 2.0, "rewardRisk": 3.0, "atrPeriod": 14},
           "sizing": {"riskPerTradePct": 1.0, "maxPositionPct": 20.0, "maxPositions": 10}}
    bt, skipped = build(prices, pol)
    assert skipped == 1 and "000000" not in bt                 # o=h=l=0 거래정지 아티팩트
    assert bt["005930"]["capped"] is True                      # 1%*1000/20 = 50% -> 20% 로 캡
    assert bt["005930"]["sharesPerMillionKRW"] == 200           # 100만*20% / 1000
    assert bt["005930"]["minCapitalKRW"] == 5000                # 1000 / 20%
    assert bt["AAPL"]["sharesPerMillionKRW"] is None           # 환율 없음 -> null

    # PF-1.1 기본(리밸런싱 청산 + 균등금액)으로 같은 가격표를 돌린다
    bt2, sk2 = build(prices, pol_rebal)
    assert sk2 == 1 and bt2["005930"]["stop"] is None, bt2["005930"]
    assert bt2["005930"]["capped"] is False                    # 균등금액에는 캡 개념이 없다
    assert abs(bt2["005930"]["positionPct"] - 3.33) < 0.01, bt2["005930"]
    assert bt2["005930"]["sharesPerMillionKRW"] == 33           # 100만*3.33% / 1000
    print("selftest ok (30건)")


if __name__ == "__main__":
    main()
