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
    ck("한 글자 코인(KRW-G)·숫자 포함(KRW-1INCH)도 허용", CW.parse_params({"weights": {"KRW-G": 0.3, "KRW-1INCH": 0.2}, "capital_krw": 1e6})["weights"]["KRW-G"] == 0.3)
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

    # ---- 전부 0%(weights 비어 있음): 새로 사지 않고 자기 보유만 정리
    with tempfile.TemporaryDirectory() as td:
        c = cfg_for(td, weights={})
        fb = FakeBroker(positions={"UPBIT": [Position("KRW-BTC", "UPBIT", 0.5, 90e6, BTC)]}, cash={"UPBIT": 5_000_000}, quotes=price)
        (Path(td) / "strategy_crypto_weights.json").write_text(json.dumps(
            {"cash": 100_000.0, "capital": 1_000_000.0, "holdings": {"KRW-BTC": 0.006}, "pending": {}}), encoding="utf-8")
        r = run(c, fb, at(2))
        ck("비율 전부 0%: 매수 없음, 자기 BTC(0.006)만 정리 매도(개인 0.5 불변)",
           [x["side"] for x in r["placed"]] == ["SELL"] and r["placed"][0]["qty"] <= 0.006)

    # ---- '기타' 묶음: 후보 중 거래대금 상위 N · 투자유의 제외 · 월 1회 고정 · 균등
    XRP, SOL, ADA, DOGE, JUNK = "KRW-XRP", "KRW-SOL", "KRW-ADA", "KRW-DOGE", "KRW-JUNK"
    px2 = {**price, XRP: 1_000.0, SOL: 200_000.0, ADA: 800.0, DOGE: 300.0, JUNK: 10.0}
    info = {XRP: {"value24h": 900e9, "warning": False}, SOL: {"value24h": 500e9, "warning": False},
            ADA: {"value24h": 100e9, "warning": False}, DOGE: {"value24h": 300e9, "warning": False},
            JUNK: {"value24h": 999e9, "warning": True}}
    cands = [XRP, SOL, ADA, DOGE, JUNK, "KRW-NOPE"]

    def cfg_o(td, **kw):
        c = cfg_for(td, weights={"KRW-BTC": 0.5, "KRW-ETH": 0.2}, other_weight=0.3, other_candidates=cands, other_top_n=2, **kw)
        c["symbol_allowlist"] = ["KRW-BTC", "KRW-ETH"] + cands
        return c
    with tempfile.TemporaryDirectory() as td:
        c = cfg_o(td)
        fb = FakeBroker(positions={"UPBIT": []}, cash={"UPBIT": 5_000_000}, quotes=px2, info=info)
        r = run(c, fb, at(2), execute=False)
        st = state(td)
        ck("기타 = 후보 중 거래대금 상위 2(XRP 9천억·SOL 5천억), 투자유의(JUNK 9천9백억)·마켓 없음(NOPE) 제외", st["other"]["symbols"] == [XRP, SOL])
        ck("기타 30% 를 균등(코인당 15%) — 계획 매수에 XRP·SOL", {x["symbol"] for x in r["planned"]} >= {XRP, SOL})
        info[ADA]["value24h"] = 9_999e9
        run(c, fb, at(20), execute=False)
        ck("같은 달에는 목록이 안 바뀐다(거래대금이 바뀌어도)", state(td)["other"]["symbols"] == [XRP, SOL])
        run(c, fb, datetime(2026, 12, 1, 9, 5, tzinfo=KST), execute=False)
        ck("달이 바뀌면 다시 고른다(ADA 상위로)", state(td)["other"]["symbols"][0] == ADA and state(td)["other"]["month"] == "2026-12")
    with tempfile.TemporaryDirectory() as td:
        c = cfg_o(td)
        fb = FakeBroker(positions={"UPBIT": []}, cash={"UPBIT": 5_000_000}, quotes=px2, info=info)
        (Path(td) / "strategy_crypto_weights.json").write_text(json.dumps(
            {"cash": 500_000.0, "capital": 1_000_000.0, "holdings": {"KRW-SOL": 0.5}, "pending": {},
             "other": {"month": "2026-11", "symbols": [XRP, DOGE], "cands": [x for x in cands]}}), encoding="utf-8")
        fb._pos["UPBIT"] = [Position("KRW-SOL", "UPBIT", 0.5, 150_000.0, 200_000.0)]
        r = run(c, fb, at(2))
        ck("기타에서 빠진 코인(SOL)의 자기 보유는 목표 0 으로 정리 매도", any(x["symbol"] == "KRW-SOL" and x["side"] == "SELL" for x in r["placed"]))
    with tempfile.TemporaryDirectory() as td:
        c = cfg_o(td)

        class Boom(FakeBroker):
            def market_info(self, market, symbols):
                raise RuntimeError("API 다운")
        fb = Boom(positions={"UPBIT": []}, cash={"UPBIT": 5_000_000}, quotes=px2)
        r = run(c, fb, at(2), execute=False)
        ck("시세 조회 실패 → 알림, 고정 코인만 계획(기타는 원화로)", any("조회 실패" in n for n in r.get("notes", []))
           and {x["symbol"] for x in r["planned"]} == {"KRW-BTC", "KRW-ETH"})
    for bad in ({"weights": {"KRW-BTC": 0.8}, "capital_krw": 1e6, "other_weight": 0.3, "other_candidates": ["KRW-XRP"]},
                {"weights": {"KRW-BTC": 0.5}, "capital_krw": 1e6, "other_weight": 0.3},
                {"weights": {"KRW-BTC": 0.5}, "capital_krw": 1e6, "other_weight": 0.3, "other_candidates": ["XRP"]},
                {"weights": {"KRW-BTC": 0.5}, "capital_krw": 1e6, "other_weight": 0.3, "other_candidates": ["KRW-XRP"], "other_top_n": 0}):
        try:
            CW.parse_params(bad)
            ck("기타 설정 오류 거부", False)
        except ValueError:
            ck("기타 설정 오류 거부(합>1·후보 없음·형식·N<1)", True)

    # ---- 한 바구니: weights {} · other_weight 1.0 · other_mode volume — 거래대금 비례, 그 달 고정
    info[ADA]["value24h"] = 100e9                      # 앞 테스트가 바꾼 값을 되돌린다
    with tempfile.TemporaryDirectory() as td:
        c = cfg_for(td, weights={}, other_weight=1.0, other_candidates=cands, other_top_n=2, other_mode="volume")
        c["symbol_allowlist"] = cands
        fb = FakeBroker(positions={"UPBIT": []}, cash={"UPBIT": 5_000_000}, quotes=px2, info=info)
        r = run(c, fb, at(2), execute=False)
        sh = state(td)["other"]["shares"]
        ck("거래대금 비례 비중: XRP 9천억·SOL 5천억 → 64%·36%(합 1)", abs(sh[XRP] - 900 / 1400) < 1e-9 and abs(sh[SOL] - 500 / 1400) < 1e-9
           and abs(sum(sh.values()) - 1) < 1e-9)
        info[SOL]["value24h"] = 9_999e9
        run(c, fb, at(20), execute=False)
        ck("같은 달에는 비중도 고정(거래대금이 바뀌어도)", state(td)["other"]["shares"] == sh)
        ck("한 바구니: 고정 코인 없이 기타만으로 계획 매수(XRP·SOL)", {x["symbol"] for x in r["planned"]} == {XRP, SOL})
    try:
        CW.parse_params({"weights": {}, "capital_krw": 1e6, "other_weight": 1, "other_candidates": ["KRW-XRP"], "other_mode": "cap"})
        ck("other_mode 오류 거부", False)
    except ValueError:
        ck("other_mode 는 equal|volume 만", True)

    # ---- 30개 바구니(목표가 작다) + 값이 딱 떨어지지 않는 시세 — 실데이터 점검에서 찾은 두 버그
    syms30 = [f"KRW-C{i:02d}" for i in range(30)]
    q30 = {s_: 1234.5678 + i * 37.31 for i, s_ in enumerate(syms30)}
    info30 = {s_: {"value24h": 1e9, "value_avg": 1e9, "warning": False} for s_ in syms30}
    with tempfile.TemporaryDirectory() as td:
        c = cfg_for(td, weights={}, other_weight=1.0, other_candidates=syms30, other_top_n=30, other_mode="equal", max_order_krw=200_000)
        c["symbol_allowlist"] = syms30
        c["risk"]["UPBIT"]["max_orders_per_run"] = 30
        fb = FakeBroker(positions={"UPBIT": []}, cash={"UPBIT": 5_000_000}, quotes=q30, info=info30)
        r = run(c, fb, at(2), execute=False)
        ck("30개 균등(코인당 3.3% < 밴드 5%): 첫날 30개 모두 매수 계획(목표가 작아도 처음엔 산다)", len(r["planned"]) == 30 and not r["rejected"])
        r = run(c, fb, at(3))
        ok_dec = all(abs(round(x["qty"], 8) - x["qty"]) < 1e-12 for x in r["placed"])
        ck("시세가 딱 떨어지지 않아도 매수 수량은 소수 8자리(거부 없음)", len(r["placed"]) == 30 and ok_dec and not r["rejected"])
        row = {}
        fill_all(td, fb, q30)
        run(c, fb, at(4))
        st = state(td)
        base = st["cash"] + sum(st["holdings"].get(s_, 0) * q30[s_] for s_ in syms30)
        ck("한 번 체결되면 코인마다 보유가 생긴다(밴드 안은 더 안 산다)", len([s_ for s_ in syms30 if st["holdings"].get(s_, 0) > 0]) == 30 and base > 0)

    # ---- 선정 보정: 스테이블 제외 · N일 평균 순위(그날 급등 코인 완화) · 코인별 비중 상한
    USDT = "KRW-USDT"
    info3 = {XRP: {"value24h": 900e9, "value_avg": 300e9, "warning": False}, SOL: {"value24h": 500e9, "value_avg": 280e9, "warning": False},
             ADA: {"value24h": 100e9, "value_avg": 50e9, "warning": False}, DOGE: {"value24h": 9_000e9, "value_avg": 20e9, "warning": False},
             USDT: {"value24h": 9_999e9, "value_avg": 999e9, "warning": False}}
    c3 = [XRP, SOL, ADA, DOGE, USDT]
    with tempfile.TemporaryDirectory() as td:
        c = cfg_for(td, weights={}, other_weight=1.0, other_candidates=c3, other_top_n=3, other_mode="volume",
                    other_exclude=[USDT], other_rank_days=7)
        c["symbol_allowlist"] = c3
        fb = FakeBroker(positions={"UPBIT": []}, cash={"UPBIT": 5_000_000}, quotes={**px2, USDT: 1_400.0}, info=info3)
        run(c, fb, at(2), execute=False)
        o = state(td)["other"]
        ck("스테이블(USDT)은 거래대금 1위여도 제외, 7일 평균 순위(DOGE 24시간 폭증은 뒤로)", o["symbols"] == [XRP, SOL, ADA]
           and USDT not in o["symbols"] and o["days"] == 7)
    with tempfile.TemporaryDirectory() as td:
        c = cfg_for(td, weights={}, other_weight=1.0, other_candidates=c3, other_top_n=3, other_mode="volume",
                    other_exclude=[USDT], other_rank_days=7, other_max_share=0.4)
        c["symbol_allowlist"] = c3
        fb = FakeBroker(positions={"UPBIT": []}, cash={"UPBIT": 5_000_000}, quotes={**px2, USDT: 1_400.0}, info=info3)
        run(c, fb, at(2), execute=False)
        sh = state(td)["other"]["shares"]
        ck("코인별 비중 상한 40%: 합 1 유지·상한 초과 없음(XRP 원래 48%)", abs(sum(sh.values()) - 1) < 1e-9 and max(sh.values()) <= 0.4 + 1e-9
           and sh[XRP] == 0.4)
    for bad in ({"other_rank_days": 0}, {"other_rank_days": 31}, {"other_max_share": 0.2}, {"other_max_share": 0}, {"other_exclude": ["USDT"]}):
        try:
            CW.parse_params({"weights": {}, "capital_krw": 1e6, "other_weight": 1, "other_candidates": ["KRW-XRP"], "other_top_n": 3, **bad})
            ck("선정 보정 설정 오류 거부", False)
        except ValueError:
            ck("선정 보정 설정 오류 거부(기간 범위·상한×N<1·형식)", True)
    ck("_cap_shares: 상한 넘는 몫을 나머지에 비례 분배(합 1)", abs(sum(CW._cap_shares({"a": 0.7, "b": 0.2, "c": 0.1}, 0.5).values()) - 1) < 1e-9
       and CW._cap_shares({"a": 0.7, "b": 0.2, "c": 0.1}, 0.5)["a"] == 0.5)

    # ---- 업비트 어댑터: market_info 는 공개 API 2개(마켓 목록·시세)로 거래대금·유의를 만든다
    from autotrader import upbit as UB
    mod = UB._client_module()

    class Resp:
        def __init__(self, data):
            self.data = data

        def raise_for_status(self):
            pass

        def json(self):
            return self.data
    calls = []

    def fake_request(method, url, **kw):
        calls.append((method, url.rsplit("/", 1)[-1], kw.get("params")))
        if url.endswith("/market/all"):
            return Resp([{"market": "KRW-XRP", "market_warning": "NONE"}, {"market": "KRW-JUNK", "market_warning": "CAUTION"},
                         {"market": "KRW-EVT", "market_warning": "NONE", "market_event": {"warning": True}}])
        return Resp([{"market": "KRW-XRP", "acc_trade_price_24h": 9e11}, {"market": "KRW-JUNK", "acc_trade_price_24h": 1e12},
                     {"market": "KRW-EVT", "acc_trade_price_24h": 5e11}, {"market": "KRW-GONE", "acc_trade_price_24h": 1e9}])
    orig = mod._request
    mod._request = fake_request
    try:
        mi = UB.UpbitBroker(object()).market_info("UPBIT", ["KRW-XRP", "KRW-JUNK", "KRW-EVT", "KRW-GONE"])
    finally:
        mod._request = orig
    ck("어댑터 market_info: 거래대금·유의(CAUTION·market_event 경고), 목록에 없는 코인(GONE)은 빠진다",
       mi == {"KRW-XRP": {"value24h": 9e11, "warning": False}, "KRW-JUNK": {"value24h": 1e12, "warning": True},
              "KRW-EVT": {"value24h": 5e11, "warning": True}} and [c[1] for c in calls] == ["all", "ticker"]
       and calls[1][2] == {"markets": "KRW-XRP,KRW-JUNK,KRW-EVT,KRW-GONE"})

    # ---- days>1: 일봉 평균(오늘 진행 중인 봉 제외)
    from autotrader import bithumb as BTH
    mod_b = BTH._client_module()
    seen2 = []

    class R2:
        def __init__(self, d):
            self.d = d

        def raise_for_status(self):
            pass

        def json(self):
            return self.d

    def fake2(method, url, **kw):
        seen2.append((url.rsplit("/", 1)[-1], (kw.get("params") or {}).get("count")))
        if url.endswith("/market/all"):
            return R2([{"market": "KRW-XRP", "market_warning": "NONE"}])
        if url.endswith("virtual_asset_warning"):
            return R2([])
        if url.endswith("/ticker"):
            return R2([{"market": "KRW-XRP", "acc_trade_price_24h": 9e11}])
        return R2([{"candle_acc_trade_price": 9e12}, {"candle_acc_trade_price": 100.0}, {"candle_acc_trade_price": 300.0}])
    orig2 = mod_b._request
    mod_b._request = fake2
    try:
        import time as _t
        _sl = _t.sleep
        _t.sleep = lambda x: None
        mi2 = BTH.BithumbBroker(object()).market_info("BITHUMB", ["KRW-XRP"], days=2)
    finally:
        mod_b._request = orig2
        _t.sleep = _sl
    ck("market_info(days=2): 오늘 봉(첫 번째) 제외 일평균 = (100+300)/2, 일봉 count = days+1",
       mi2["KRW-XRP"]["value_avg"] == 200.0 and ("days", 3) in seen2)

    print(f"\ntest-autotrader-cryptoweights {COUNT[0] - len(FAILS)}/{COUNT[0]}")
    return 1 if FAILS else 0


if __name__ == "__main__":
    sys.exit(main())
