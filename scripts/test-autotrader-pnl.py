#!/usr/bin/env python3
"""autotrader 실현손익 회귀 — 체결 원장·평균단가. 키·네트워크 없이 돈다.

핀하는 것: 우리 주문번호의 체결만 센다(공유 계좌의 남의 체결 제외) · 시작 보유를 원가로 · 누적 체결은 덮어쓴다(부분체결 중복 없음) ·
원가를 모르는 매도는 지어내지 않고 incomplete · 원장을 만들기 전에 이미 있던 우리 주문은 시작 보유에 들어 있으니 다시 안 센다.

    python scripts/test-autotrader-pnl.py
"""
import json
import sys
import tempfile
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from autotrader import web                                                    # noqa: E402
from autotrader.broker import FakeBroker                                      # noqa: E402
from autotrader.config import normalize_config                                # noqa: E402
from autotrader.engine import KST, Ledger                                     # noqa: E402
from autotrader.pnl import new_fills, realized, sync_fills                    # noqa: E402
from autotrader import notify                                                 # noqa: E402

FAILS, COUNT = [], [0]


def ck(name, cond):
    COUNT[0] += 1
    if not cond:
        FAILS.append(name)
    print(("ok   " if cond else "FAIL ") + name)


def order(no, sym, side, day="2026-09-22"):
    return {"ts": day, "day": day, "kind": "order", "market": "US", "symbol": sym, "side": side, "qty": 1, "orderNo": no,
            "executed": True}


def main():
    # ---- 평균단가 계산
    book = {"opening": {"US": {"TQQQ": {"qty": 10, "avg": 50.0}}},
            "fills": {"1": {"orderNo": "1", "market": "US", "symbol": "TQQQ", "side": "BUY", "qty": 10, "price": 60.0, "day": "20260922"},
                      "2": {"orderNo": "2", "market": "US", "symbol": "TQQQ", "side": "SELL", "qty": 5, "price": 66.0, "day": "20260923"},
                      "3": {"orderNo": "3", "market": "US", "symbol": "SOXL", "side": "SELL", "qty": 1, "price": 9.0, "day": "20260923"}}}
    r = realized(book)["US"]
    ck("시작 보유+매수의 평균단가(55)로 매도 손익 = 5×(66−55)=55", abs(r["realized"] - 55.0) < 1e-9 and r["sells"][0]["avg"] == 55.0)
    ck("원가를 모르는 매도(SOXL)는 incomplete, 손익에 안 넣는다", r["incomplete"] and len(r["sells"]) == 1)
    ck("원장이 없으면 빈 결과", realized(None) == {})

    with tempfile.TemporaryDirectory() as td:
        cfg = normalize_config({"strategy": "x", "mode": "paper", "markets": ["US"], "symbol_allowlist": ["TQQQ"],
                                "state_dir": str(Path(td) / "s")})
        cfg["profile"] = "p"
        led = Ledger(Path(td) / "s")
        led.append(order("100", "TQQQ", "BUY", "2026-09-21"))                 # 원장 만들기 전의 우리 주문 → 시작 보유에 이미 있다
        snap = {"markets": {"US": {"positions": [{"symbol": "TQQQ", "qty": 15, "avgPrice": 71.42}]}}}
        fb = FakeBroker()
        fb.fill_rows = [{"orderNo": "100", "symbol": "TQQQ", "side": "BUY", "qty": 15, "price": 71.42, "day": "20260921"}]
        now = datetime(2026, 9, 22, 21, 40, tzinfo=KST)
        b = sync_fills(cfg, fb, snap, now)
        ck("처음엔 스냅샷 보유를 시작 원가로", b["opening"]["US"]["TQQQ"] == {"qty": 15, "avg": 71.42})
        ck("시작 전 우리 주문은 다시 안 센다", b["fills"] == {} and "100" in b["exclude"])

        led.append(order("200", "TQQQ", "SELL"))
        fb.fill_rows += [{"orderNo": "200", "symbol": "TQQQ", "side": "SELL", "qty": 3, "price": 81.67, "day": "20260922"},
                         {"orderNo": "999", "symbol": "TQQQ", "side": "SELL", "qty": 7, "price": 1.0, "day": "20260922"}]
        b = sync_fills(cfg, fb, snap, now)
        ck("우리 주문번호 체결만(남의 999 제외)", set(b["fills"]) == {"200"})
        fb.fill_rows[1]["qty"] = 5                                             # 부분체결이 늘었다(누적값)
        b = sync_fills(cfg, fb, snap, now)
        ck("누적 체결은 덮어쓴다(중복 합산 없음)", b["fills"]["200"]["qty"] == 5 and len(b["fills"]) == 1)
        rr = realized(b)["US"]
        ck("실현손익 = 5×(81.67−71.42)", abs(rr["realized"] - 5 * (81.67 - 71.42)) < 1e-9)
        ck("체결 원장이 파일로 남는다", json.loads((Path(td) / "s" / "fills.json").read_text(encoding="utf-8"))["fills"]["200"]["qty"] == 5)

        html = web.render_money_rows({"markets": {"US": {"totals": {"cost": 1, "value": 1, "pnl": 0, "pnlPct": 0}}},
                                      "realized": {"US": rr}})
        ck("화면에 실현손익 줄", "실현손익" in html and "$51.25" in html)
        ck("매도 내역 표", "81.67" in web.render_sells({"realized": {"US": rr}}))
        ck("체결 조회 실패는 표시만", "체결 조회 실패" in web.render_money_rows({"markets": {}, "realizedError": "x"}))

        # ---- 체결 알림: 늘어난 것만, 같은 체결은 두 번 안 알린다
        prev = {"fills": {"200": {"orderNo": "200", "symbol": "SOXL", "side": "BUY", "qty": 2, "price": 40.0, "market": "US"}}}
        cur = {"fills": {"200": {"orderNo": "200", "symbol": "SOXL", "side": "BUY", "qty": 5, "price": 40.1, "market": "US"},
                         "201": {"orderNo": "201", "symbol": "005930", "side": "SELL", "qty": 1, "price": 283000, "market": "KR"}}}
        nf = {f["orderNo"]: f["delta"] for f in new_fills(prev, cur)}
        ck("새 체결은 증가분만(부분체결 2→5 = 3주, 새 주문 1주)", nf == {"200": 3, "201": 1})
        ck("변화 없으면 알림 없음", new_fills(cur, cur) == [])
        ck("원장이 처음 생겨도 이전 없음 = 전부가 아니라 원장 내용만", len(new_fills(None, {"fills": {}})) == 0)
        m = notify.fill_message("infbuy", "paper", new_fills(prev, cur)[0])
        ck("체결 문구: 종목·수량·가격·누적·모의, 계좌번호 없음", "SOXL 매수 3주 @ $40.10" in m and "누적 5주" in m and "모의" in m
           and m.count("\n") == 2 and "12345678" not in m)
        ck("국내 매도 문구", "005930 매도 1주 @ 283,000원" in notify.fill_message("x", "live", new_fills(prev, cur)[1]))
        ck("매매 방이 있으면 그리로, 없으면 콘텐츠 방, 장애 방은 안 씀",
           notify.trade_chat({"TELEGRAM_TRADE_CHAT_ID": "T", "TELEGRAM_CHAT_ID": "C", "TELEGRAM_ALERT_CHAT_ID": "A"}) == "T"
           and notify.trade_chat({"TELEGRAM_CHAT_ID": "C", "TELEGRAM_ALERT_CHAT_ID": "A"}) == "C")

    # ---- 11-06: infbuy fills.json 0건 대응 — 번호 자릿수·동기화 기록·시장별 실패 격리·되살리기 기간
    with tempfile.TemporaryDirectory() as td:
        cfg = normalize_config({"strategy": "x", "mode": "paper", "markets": ["US", "KR"], "symbol_allowlist": ["TQQQ"],
                                "state_dir": str(Path(td) / "s")})
        cfg["profile"] = "p"
        led = Ledger(Path(td) / "s")
        snap = {"markets": {"US": {"positions": []}, "KR": {"positions": []}}}
        now = datetime(2026, 11, 6, 9, 0, tzinfo=KST)
        b = sync_fills(cfg, FakeBroker(), snap, now)                           # 원장 생성(주문 없음 → exclude 빈 목록)
        ck("동기화 기록: 주문 없으면 시장별 pending 0", b["sync"]["markets"]["US"] == {"pending": 0} and b["exclude"] == [])

        led.append(order("0030012345", "TQQQ", "BUY", "2026-11-05"))
        led.append(order("0000777", "TQQQ", "SELL", "2026-10-20"))              # 7일 밖(되살리기 대상)
        fb = FakeBroker()
        fb.fill_rows = [{"orderNo": "30012345", "symbol": "TQQQ", "side": "BUY", "qty": 4, "price": 60.0, "day": "20261105"},
                        {"orderNo": "777", "symbol": "TQQQ", "side": "SELL", "qty": 2, "price": 70.0, "day": "20261020"}]
        b = sync_fills(cfg, fb, snap, now)
        ck("앞의 0 이 다른 번호도 같은 주문(키는 원장 번호)", set(b["fills"]) == {"0030012345"}
           and b["fills"]["0030012345"]["orderNo"] == "0030012345")
        us = b["sync"]["markets"]["US"]
        ck("동기화 기록: 기간·받은 행·맞춘 행·표본", us["pending"] == 1 and us["brokerRows"] == 2 and us["matched"] == 1
           and us["range"] == ["20261104", "20261106"] and us["oursSample"] == ["0030012345"])
        ck("기본 7일 — 10-20 주문은 아직 안 들어온다", "0000777" not in b["fills"])
        b = sync_fills(cfg, fb, snap, now, lookback_days=30)
        ck("되살리기(30일): 7일 밖 체결도 들어온다", set(b["fills"]) == {"0030012345", "0000777"} and b["sync"]["lookbackDays"] == 30)
        ck("되살리기 상한 90일", sync_fills(cfg, fb, snap, now, lookback_days=999)["sync"]["lookbackDays"] == 90)

        class Half(FakeBroker):                                                # US 는 실패, KR 은 정상
            def fills(self, market, start, end):
                if market == "US":
                    raise RuntimeError("EGW00201 초당 거래건수 초과")
                return [{"orderNo": "9", "symbol": "005930", "side": "BUY", "qty": 1, "price": 100.0, "day": "20261105"}]
        led.append({**order("9", "005930", "BUY", "2026-11-05"), "market": "KR"})
        b = sync_fills(cfg, Half(), snap, now)
        ck("한 시장 실패는 기록하고 다른 시장은 갱신", "9" in b["fills"] and "error" in b["sync"]["markets"]["US"]
           and b["sync"]["errors"] and "0030012345" in b["fills"])
        ck("실패해도 파일은 남는다(기록 포함)",
           "errors" in json.loads((Path(td) / "s" / "fills.json").read_text(encoding="utf-8"))["sync"])

    print(f"\ntest-autotrader-pnl {COUNT[0] - len(FAILS)}/{COUNT[0]}")
    return 1 if FAILS else 0


if __name__ == "__main__":
    sys.exit(main())
