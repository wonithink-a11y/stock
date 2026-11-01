#!/usr/bin/env python3
"""autotrader 크립토 목표 비중(crypto_weights) 회귀 — 키·네트워크 없이 돈다.

핀하는 것: 설정 검사(합>1·종목 형식·자본 없음 거부) · 첫 실행은 슬라이스(max_order_krw)로 나눠 매수 · 체결 확인 뒤에만 보유·현금 변경 ·
dry-run 은 상태를 안 바꾼다 · 밴드 안이면 무주문 · 5,000원 미만 주문 안 만듦 · **자기 체결 수량만 매도**(개인 보유 불가침) ·
대기 주문이 있으면 새 주문 없음 · 킬 스위치.

    python scripts/test-autotrader-cryptoweights.py
"""
import json
import sys
import tempfile
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from autotrader.broker import FakeBroker                                      # noqa: E402
from autotrader.config import GateError, kill_file, normalize_config           # noqa: E402
from autotrader.engine import KST, Ledger, run_once                          # noqa: E402
from autotrader.models import Position                                       # noqa: E402
from autotrader.strategies import crypto_weights as CW                        # noqa: E402

FAILS, COUNT = [], [0]
ENV = {"UPBIT_TRADE_ACCESS_KEY": "a", "UPBIT_TRADE_SECRET_KEY": "s", "AUTOTRADER_ALLOW_LIVE": "I-ACCEPT-REAL-TRADES"}
BTC, ETH = 100_000_000.0, 5_000_000.0


def ck(name, cond):
    COUNT[0] += 1
    if not cond:
        FAILS.append(name)
    print(("ok   " if cond else "FAIL ") + name)


def cfg_for(td, **params):
    p = {"weights": {"KRW-BTC": 0.5, "KRW-ETH": 0.3}, "capital_krw": 1_000_000, "band_pct": 5.0, "max_order_krw": 200_000, **params}
    return normalize_config({"strategy": "crypto_weights", "broker": "upbit", "mode": "live", "key_prefix": "UPBIT_TRADE",
                             "markets": ["UPBIT"], "symbol_allowlist": ["KRW-BTC", "KRW-ETH"], "params": p,
                             "risk": {"UPBIT": {"max_order_value": 3_000_000, "max_daily_value": 9_000_000, "max_orders_per_run": 5,
                                                "max_position_value": 900_000_000}},
                             "live": {"enabled": True, "tr_ids_reviewed": True}, "state_dir": str(td)})


def at(day, hour=9):
    return datetime(2026, 11, day, hour, 5, tzinfo=KST)


def run(cfg, fb, when, execute=True):
    return run_once(cfg, fb, CW.STRATEGY(), execute=execute, env=ENV, now=when, sleep=lambda s: None)


def state(td):
    return json.loads((Path(td) / "strategy_crypto_weights.json").read_text("utf-8"))


def fill_all(td, fb, price):
    """원장의 미확인 주문을 전부 체결로 만든다(가격 = 시세, 수수료 0.05%)."""
    seen = {f["orderNo"] for f in fb.fill_rows}
    for r in Ledger(td).rows():
        if r.get("kind") == "order" and r.get("executed") and r["orderNo"] not in seen:
            px = price[r["symbol"]]
            qty = float(r["qty"]) if r["side"] == "SELL" else float(r["qty"])
            fb.fill_rows.append({"orderNo": r["orderNo"], "symbol": r["symbol"], "side": r["side"], "qty": qty,
                                 "price": px, "fee": qty * px * 0.0005, "state": "done"})


def main():
    # ---- 설정 검사
    bad = [{}, {"weights": {"KRW-BTC": 0.7, "KRW-ETH": 0.4}, "capital_krw": 1e6}, {"weights": {"BTC": 0.5}, "capital_krw": 1e6},
           {"weights": {"KRW-BTC": 0.5}}, {"weights": {"KRW-BTC": 0.5}, "capital_krw": 1000},
           {"weights": {"KRW-BTC": 0}, "capital_krw": 1e6}, {"weights": {"KRW-BTC": True}, "capital_krw": 1e6},
           {"weights": {"KRW-BTC": 0.5}, "capital_krw": 1e6, "band_pct": -1}]
    errs = 0
    for b in bad:
        try:
            CW.parse_params(b)
        except ValueError:
            errs += 1
    ck("잘못된 설정 8가지는 전부 거부", errs == len(bad))
    ok = CW.parse_params({"weights": {"KRW-BTC": 0.5, "KRW-ETH": 0.5}, "capital_krw": 1_000_000})
    ck("합 = 1·기본값(밴드 5·슬라이스 자본의 20%)", ok["band"] == 5.0 and ok["max_order"] == 200_000)

    price = {"KRW-BTC": BTC, "KRW-ETH": ETH}
    with tempfile.TemporaryDirectory() as td:
        c = cfg_for(td)
        fb = FakeBroker(positions={"UPBIT": [Position("KRW-BTC", "UPBIT", 0.5, 90e6, BTC)]}, cash={"UPBIT": 5_000_000}, quotes=price)
        r1 = run(c, fb, at(2))
        by = {x["symbol"]: x for x in r1["placed"]}
        ck("첫 실행: 코인마다 슬라이스(20만원) 매수 — 목표 50만/30만 이어도 한 번에 20만", len(r1["placed"]) == 2
           and all(x["side"] == "BUY" and abs(x["value"] - 200_000) < 1 for x in r1["placed"]))
        ck("주문 식별자에 시각·코인", {r["clientId"] for r in Ledger(td).rows() if r.get("kind") == "order"}
           == {"cw-2026110209-BTC-buy", "cw-2026110209-ETH-buy"})
        r1b = run(c, fb, at(2, 10))
        ck("체결 확인 전(대기)에는 새 주문 없음", not r1b["placed"])
        fill_all(td, fb, price)
        run(c, fb, at(3))
        st = state(td)
        ck("체결 확인 뒤 보유·현금 갱신(수수료 반영)", abs(st["holdings"]["KRW-BTC"] - 0.002) < 1e-9
           and abs(st["holdings"]["KRW-ETH"] - 0.04) < 1e-9 and abs(st["cash"] - (1_000_000 - 400_000 - 400_000 * 0.0005)) < 1e-6
           and len(st["pending"]) == 2)            # 확인한 주문은 정리되고, 같은 실행에서 낸 새 슬라이스 2건만 대기
        # 며칠 더: 슬라이스로 목표에 다가간다
        for d in range(4, 12):
            run(c, fb, at(d))
            fill_all(td, fb, price)
        run(c, fb, at(12))
        st = state(td)
        val = {s: st["holdings"][s] * price[s] for s in price}
        base = st["cash"] + sum(val.values())
        ck("슬라이스로 이어 사서 목표(50%·30%) 밴드 안에 들어온다", abs(val["KRW-BTC"] / base - 0.5) * 100 < 5 and abs(val["KRW-ETH"] / base - 0.3) * 100 < 5)
        n_before = len(Ledger(td).rows())
        r = run(c, fb, at(13))
        ck("밴드 안이면 무주문", not r["placed"] and len(Ledger(td).rows()) == n_before)
        ck("개인 보유 BTC 0.5 는 기준 가치에 안 들어간다(자본 100만원 규모)", base < 1_100_000)

    # ---- 초과분 매도는 자기 수량만
    with tempfile.TemporaryDirectory() as td:
        c = cfg_for(td, weights={"KRW-BTC": 0.2, "KRW-ETH": 0.3})
        fb = FakeBroker(positions={"UPBIT": [Position("KRW-BTC", "UPBIT", 0.5, 90e6, BTC)]}, cash={"UPBIT": 5_000_000}, quotes=price)
        (Path(td)).mkdir(exist_ok=True)
        (Path(td) / "strategy_crypto_weights.json").write_text(json.dumps(
            {"cash": 100_000.0, "capital": 1_000_000.0, "holdings": {"KRW-BTC": 0.006, "KRW-ETH": 0.0}, "pending": {}}), encoding="utf-8")
        r = run(c, fb, at(2))
        sells = [x for x in r["placed"] if x["side"] == "SELL"]
        ck("초과분은 자기 수량 안에서만 매도(계좌의 개인 0.5 BTC 는 그대로)", len(sells) == 1 and 0 < sells[0]["qty"] <= 0.006)

    # ---- dry-run 은 상태를 안 바꾼다
    with tempfile.TemporaryDirectory() as td:
        c = cfg_for(td)
        fb = FakeBroker(positions={"UPBIT": []}, cash={"UPBIT": 5_000_000}, quotes=price)
        rd = run(c, fb, at(2), execute=False)
        run(c, fb, at(3), execute=False)
        st = state(td)
        ck("dry-run: 계획만(주문 2건), 원장·보유·현금 불변", len(rd["planned"]) == 2 and not rd["placed"] and not Ledger(td).rows()
           and st["holdings"] == {} and st["cash"] == 1_000_000)

    # ---- 5,000원 미만·킬 스위치
    with tempfile.TemporaryDirectory() as td:
        c = cfg_for(td, weights={"KRW-BTC": 0.004, "KRW-ETH": 0.3}, capital_krw=1_000_000)
        fb = FakeBroker(positions={"UPBIT": []}, cash={"UPBIT": 5_000_000}, quotes=price)
        r = run(c, fb, at(2))
        ck("5,000원 미만 목표는 주문을 안 만든다(BTC 4,000원)", [x["symbol"] for x in r["placed"]] == ["KRW-ETH"])
    with tempfile.TemporaryDirectory() as td:
        c = cfg_for(td)
        fb = FakeBroker(positions={"UPBIT": []}, cash={"UPBIT": 5_000_000}, quotes=price)
        kill_file(c).parent.mkdir(parents=True, exist_ok=True)
        kill_file(c).write_text("x", encoding="utf-8")
        try:
            run(c, fb, at(2))
            ck("킬 스위치면 실행 거부", False)
        except GateError:
            ck("킬 스위치면 실행 거부", not fb.placed)

    print(f"\ntest-autotrader-cryptoweights {COUNT[0] - len(FAILS)}/{COUNT[0]}")
    return 1 if FAILS else 0


if __name__ == "__main__":
    sys.exit(main())
