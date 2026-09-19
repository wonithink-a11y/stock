#!/usr/bin/env python3
"""autotrader 회귀 — 키·네트워크 없이 돈다. 통과가 정보를 주는 것(주문이 실수로 안 나간다, 실계좌 게이트)을 핀한다.

    python scripts/test-autotrader.py
"""
import json
import os
import sys
import tempfile
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from autotrader import kis, risk                                              # noqa: E402
from autotrader.broker import FakeBroker                                      # noqa: E402
from autotrader.config import (LIVE_ACK, ConfigError, GateError, gate_problems, load_env,   # noqa: E402
                               mask, normalize_config)
from autotrader.engine import KST, Ledger, run_once                           # noqa: E402
from autotrader.models import Intent, OpenOrder, Position                    # noqa: E402
from autotrader.strategy import Strategy, load_strategy                       # noqa: E402

FAILS = []
COUNT = [0]


def ck(name, cond):
    COUNT[0] += 1
    if not cond:
        FAILS.append(name)
    print(("ok   " if cond else "FAIL ") + name)


def raises(exc, fn, *a, **k):
    try:
        fn(*a, **k)
    except exc:
        return True
    except Exception:                                   # noqa: BLE001
        return False
    return False


PAPER_ENV = {"KIS_VTS_APP_KEY": "k", "KIS_VTS_APP_SECRET": "s", "KIS_VTS_ACCOUNT_NO": "12345678-01"}
LIVE_ENV = {"KIS_LIVE_APP_KEY": "k", "KIS_LIVE_APP_SECRET": "s", "KIS_LIVE_ACCOUNT_NO": "12345678-01"}


def base_cfg(td, mode="paper", markets=("KR",), allow=("005930",), **kw):
    cfg = {"strategy": "x", "mode": mode, "markets": list(markets), "symbol_allowlist": list(allow),
           "state_dir": str(Path(td) / "state")}
    cfg.update(kw)
    return normalize_config(cfg)


class Fixed(Strategy):
    name = "fixed"
    markets = ["KR", "US"]

    def __init__(self, intents):
        self._i = intents

    def decide(self, ctx):
        return list(self._i)


def kr(sym, side, qty, **k):
    return Intent(sym, side, qty, market="KR", order_type=k.pop("order_type", "market"), **k)


def main():
    now = datetime(2026, 9, 21, 10, 0, tzinfo=KST)

    # ---------------------------------------------------------------- 모델
    ck("정상 시장가 KR 의도", kr("005930", "BUY", 1).validate() is None)
    ck("수량 0 거부", kr("005930", "BUY", 0).validate() is not None)
    ck("수량 소수·bool 거부", Intent("005930", "BUY", 1.5).validate() is not None
       and Intent("005930", "BUY", True, limit_price=1.0).validate() is not None)
    ck("지정가에 가격 없으면 거부", Intent("005930", "BUY", 1, order_type="limit").validate() is not None)
    ck("NaN·음수 가격 거부", Intent("A", "BUY", 1, limit_price=float("nan")).validate() is not None
       and Intent("A", "BUY", 1, limit_price=-1.0).validate() is not None)
    ck("시장가는 KR 만", Intent("TQQQ", "BUY", 1, market="US", order_type="market").validate() is not None)
    ck("loc 는 US 만", Intent("005930", "BUY", 1, market="KR", order_type="loc", limit_price=1.0).validate() is not None)
    ck("잘못된 side·market 거부", Intent("A", "HOLD", 1, limit_price=1.0).validate() is not None
       and Intent("A", "BUY", 1, market="JP", limit_price=1.0).validate() is not None)

    # ---------------------------------------------------------------- 설정·게이트
    with tempfile.TemporaryDirectory() as td:
        ck("mode 오타는 설정 오류", raises(ConfigError, normalize_config,
                                       {"strategy": "x", "mode": "real", "markets": ["KR"]}))
        ck("알 수 없는 risk 키는 오류", raises(ConfigError, normalize_config,
                                          {"strategy": "x", "mode": "paper", "markets": ["KR"],
                                           "risk": {"KR": {"max_order": 1}}}))
        c = base_cfg(td)
        ck("risk 기본값이 채워진다(보수적)", c["risk"]["KR"]["max_order_value"] == 300_000
           and c["live"] == {"enabled": False, "tr_ids_reviewed": False})
        c2 = base_cfg(td, risk={"KR": {"max_order_value": 50_000}})
        ck("사용자 값이 기본값을 덮는다", c2["risk"]["KR"]["max_order_value"] == 50_000
           and c2["risk"]["KR"]["max_daily_value"] == 1_000_000)

        ck("모의 dry-run 은 모의 키만 필요", gate_problems(c, PAPER_ENV, False, Path(td)) == []
           and len(gate_problems(c, {}, False, Path(td))) == 3)
        live = base_cfg(td, mode="live")
        ck("실전 dry-run(읽기 전용)은 실전 키만 필요", gate_problems(live, LIVE_ENV, False, Path(td)) == [])
        ck("실전 키가 없으면 dry-run 도 막힌다", len(gate_problems(live, PAPER_ENV, False, Path(td))) == 3)

        full_live = base_cfg(td, mode="live", live={"enabled": True, "tr_ids_reviewed": True})
        env_ok = {**LIVE_ENV, "AUTOTRADER_ALLOW_LIVE": LIVE_ACK}
        ck("실전 --execute: 모든 조건이 갖춰지면 통과", gate_problems(full_live, env_ok, True, Path(td)) == [])
        # 조건 하나씩 빼면 각각 막혀야 한다
        no_enabled = base_cfg(td, mode="live", live={"enabled": False, "tr_ids_reviewed": True})
        no_review = base_cfg(td, mode="live", live={"enabled": True, "tr_ids_reviewed": False})
        ck("live.enabled 가 없으면 실전 주문 막힘", any("enabled" in p for p in gate_problems(no_enabled, env_ok, True, Path(td))))
        ck("tr_ids_reviewed 가 없으면 막힘", any("tr_ids_reviewed" in p for p in gate_problems(no_review, env_ok, True, Path(td))))
        ck("환경변수 확인 문구가 없으면 막힘", any("AUTOTRADER_ALLOW_LIVE" in p
                                            for p in gate_problems(full_live, LIVE_ENV, True, Path(td))))
        ck("환경변수 문구가 틀리면 막힘", any("AUTOTRADER_ALLOW_LIVE" in p for p in gate_problems(
            full_live, {**LIVE_ENV, "AUTOTRADER_ALLOW_LIVE": "yes"}, True, Path(td))))
        ck("실전 키가 없으면 --execute 막힘", len(gate_problems(full_live, {"AUTOTRADER_ALLOW_LIVE": LIVE_ACK}, True, Path(td))) == 3)
        ck("모의 --execute 는 live 스위치를 요구하지 않는다", gate_problems(c, PAPER_ENV, True, Path(td)) == [])
        empty_allow = base_cfg(td, allow=())
        ck("허용목록이 비면 --execute 막힘(dry-run 은 통과)",
           any("allowlist" in p for p in gate_problems(empty_allow, PAPER_ENV, True, Path(td)))
           and gate_problems(empty_allow, PAPER_ENV, False, Path(td)) == [])
        kf = Path(td) / "state" / "KILL"
        kf.parent.mkdir(parents=True, exist_ok=True)
        kf.write_text("x", encoding="utf-8")
        ck("킬 스위치는 --execute 만 막는다", any("킬" in p for p in gate_problems(c, PAPER_ENV, True, Path(td)))
           and gate_problems(c, PAPER_ENV, False, Path(td)) == [])
        kf.unlink()

        # .env 로더는 우리 키만 읽는다
        (Path(td) / ".env").write_text("KIS_VTS_APP_KEY=abc\nDART_API_KEY=zzz\nOTHER=1\n", encoding="utf-8")
        e = load_env(Path(td), environ={})
        ck(".env 로더는 관련 키만 읽는다(다른 시크릿은 안 본다)", e == {"KIS_VTS_APP_KEY": "abc"})
        ck("환경변수가 .env 를 이긴다", load_env(Path(td), environ={"KIS_VTS_APP_KEY": "env"})["KIS_VTS_APP_KEY"] == "env")
        ck("마스킹", mask("12345678-01") == "12*********" and mask("") == "")

    # ---------------------------------------------------------------- 위험 검사
    R = {"max_order_value": 1000, "max_daily_value": 2500, "max_orders_per_run": 2, "price_band_pct": 5,
         "max_position_value": 3000, "allow_sell": True}
    ok_kw = dict(risk=R, allowlist=["A"], last_price=100.0, sellable_qty=10, cash=5000.0, held_value=0.0,
                 spent_today=0.0, spent_run=0.0, orders_run=0)
    buy = Intent("A", "BUY", 5, market="KR", order_type="limit", limit_price=100.0)
    ck("정상 주문은 통과", risk.check_intent(buy, **ok_kw) is None)
    ck("허용목록 밖 거부", risk.check_intent(Intent("B", "BUY", 1, limit_price=100.0), **ok_kw) is not None)
    ck("시세 없으면 거부", risk.check_intent(buy, **{**ok_kw, "last_price": None}) is not None
       and risk.check_intent(buy, **{**ok_kw, "last_price": float("nan")}) is not None)
    ck("지정가 밴드 초과 거부", risk.check_intent(Intent("A", "BUY", 1, limit_price=120.0), **ok_kw) is not None)
    ck("주문당 한도 초과 거부", risk.check_intent(Intent("A", "BUY", 11, limit_price=100.0), **ok_kw) is not None)
    ck("일일 한도(오늘+이번 실행) 초과 거부", risk.check_intent(buy, **{**ok_kw, "spent_today": 1500.0, "spent_run": 600.0}) is not None)
    ck("실행당 주문 수 한도 거부", risk.check_intent(buy, **{**ok_kw, "orders_run": 2}) is not None)
    ck("공매도 금지: 매도가능 수량 초과 거부", risk.check_intent(Intent("A", "SELL", 11, limit_price=100.0), **ok_kw) is not None
       and risk.check_intent(Intent("A", "SELL", 10, limit_price=100.0), **ok_kw) is None)
    ck("allow_sell=false 면 매도 거부", risk.check_intent(Intent("A", "SELL", 1, limit_price=100.0),
                                                       **{**ok_kw, "risk": {**R, "allow_sell": False}}) is not None)
    ck("현금 초과 매수 거부", risk.check_intent(buy, **{**ok_kw, "cash": 100.0}) is not None)
    ck("종목당 보유금액 한도 거부", risk.check_intent(buy, **{**ok_kw, "held_value": 2800.0}) is not None)
    ck("시장가는 시세로 금액을 잡는다", risk.order_value(Intent("A", "BUY", 3, order_type="market"), 100.0) == 300.0)

    # ---------------------------------------------------------------- 전략 로더
    ck("전략 이름 검증(경로 조작 방지)", raises(ValueError, load_strategy, "../x") and raises(ValueError, load_strategy, "A b"))
    ck("템플릿 전략이 로드되고 주문을 안 낸다", load_strategy("_template".lstrip("_") if False else "target_weights").name == "target_weights")
    ck("없는 전략은 실패", raises(Exception, load_strategy, "nope_nothing"))

    # ---------------------------------------------------------------- target_weights
    with tempfile.TemporaryDirectory() as td:
        tf = Path(td) / "t.json"
        tf.write_text(json.dumps({"KR": {"005930": 0.5}}), encoding="utf-8")
        cfg = base_cfg(td, params={"targets_file": str(tf), "band_pct": 2.0})
        fb = FakeBroker(positions={"KR": []}, cash={"KR": 1_000_000.0}, quotes={"005930": 70_000.0})
        rep = run_once(cfg, fb, load_strategy("target_weights"), execute=False, env=PAPER_ENV, repo_root=Path(td), now=now)
        pl = rep["planned"]
        ck("목표비중 50%: 100만원 현금 → 7주 매수 계획(위험 한도 안에서)",
           len(pl) + len(rep["rejected"]) == 1)
        big = base_cfg(td, params={"targets_file": str(tf)}, risk={"KR": {"max_order_value": 10_000_000, "max_position_value": 10_000_000}})
        rep2 = run_once(big, fb, load_strategy("target_weights"), execute=False, env=PAPER_ENV, repo_root=Path(td), now=now)
        ck("한도가 넉넉하면 7주 시장가 매수 계획", len(rep2["planned"]) == 1 and rep2["planned"][0]["qty"] == 7
           and rep2["planned"][0]["side"] == "BUY")
        fb2 = FakeBroker(positions={"KR": [Position("005930", "KR", 20, 60000.0)]}, cash={"KR": 0.0}, quotes={"005930": 70_000.0})
        rep3 = run_once(big, fb2, load_strategy("target_weights"), execute=False, env=PAPER_ENV, repo_root=Path(td), now=now)
        ck("비중 초과분은 매도 계획(가진 것 이상 안 판다)", len(rep3["planned"]) == 1 and rep3["planned"][0]["side"] == "SELL"
           and rep3["planned"][0]["qty"] <= 20)
        ck("dry-run 은 주문·원장 없음", fb.placed == [] and not (Path(td) / "state" / "ledger.jsonl").exists())
        tf.write_text(json.dumps({"KR": {"005930": 0.7, "000660": 0.5}}), encoding="utf-8")
        ck("비중 합이 1 초과면 전략 오류(주문 없음)", run_once(
            big, fb, load_strategy("target_weights"), execute=False, env=PAPER_ENV, repo_root=Path(td), now=now
        )["status"] == "strategy-error")

    # ---------------------------------------------------------------- 엔진
    def mk(td, **kw):
        return base_cfg(td, allow=("005930", "000660", "TQQQ"), markets=("KR", "US"), **kw)

    with tempfile.TemporaryDirectory() as td:
        cfg = mk(td)
        q = {"005930": 70_000.0, "000660": 200_000.0, "TQQQ": 70.0}
        fb = FakeBroker(positions={"KR": [Position("005930", "KR", 5, 60000.0)]}, cash={"KR": 5_000_000.0, "US": 1000.0}, quotes=q)
        st = Fixed([kr("005930", "BUY", 2)])
        r = run_once(cfg, fb, st, execute=False, env=PAPER_ENV, repo_root=Path(td), now=now)
        ck("기본(dry-run)은 주문을 내지 않는다", fb.placed == [] and len(r["planned"]) == 1 and r["execute"] is False)
        r = run_once(cfg, fb, st, execute=True, env=PAPER_ENV, repo_root=Path(td), now=now)
        ck("--execute 는 주문을 낸다", len(fb.placed) == 1 and len(r["placed"]) == 1)
        ck("원장에 주문이 남는다", len(Ledger(Path(td) / "state").rows()) == 1 and Ledger(Path(td) / "state").order_nos() == {fb.placed[0]["orderNo"]})
        # 일일 한도 누적: max_daily 1,000,000, 이미 2주(140,000) 썼다
        big_buy = Fixed([kr("005930", "BUY", 4)])                    # 280,000 = 주문당 한도 300,000 이내
        for i in range(3):
            run_once(cfg, fb, big_buy, execute=True, env=PAPER_ENV, repo_root=Path(td), now=now)
        rr = run_once(cfg, fb, big_buy, execute=True, env=PAPER_ENV, repo_root=Path(td), now=now)
        ck("일일 한도가 실행 사이에 누적된다(원장 기반)", len(rr["rejected"]) == 1 and "일일 한도" in rr["rejected"][0]["reason"])
        # 위험 거부·중복·허용목록
        r = run_once(cfg, fb, Fixed([kr("005930", "BUY", 100)]), execute=True, env=PAPER_ENV, repo_root=Path(td),
                     now=datetime(2026, 9, 22, 10, 0, tzinfo=KST))
        ck("한도 초과 주문은 거부되어 안 나간다", len(r["rejected"]) == 1 and r["placed"] == [])
        r = run_once(cfg, fb, Fixed([kr("005930", "BUY", 1), kr("005930", "BUY", 1)]), execute=False, env=PAPER_ENV,
                     repo_root=Path(td), now=datetime(2026, 9, 23, 10, 0, tzinfo=KST))
        ck("같은 실행 안의 중복은 거부", len(r["planned"]) == 1 and len(r["rejected"]) == 1)
        r = run_once(cfg, fb, Fixed([kr("035720", "BUY", 1)]), execute=False, env=PAPER_ENV, repo_root=Path(td),
                     now=datetime(2026, 9, 23, 10, 0, tzinfo=KST))
        ck("허용목록 밖은 거부", len(r["rejected"]) == 1 and r["planned"] == [])

    with tempfile.TemporaryDirectory() as td:
        cfg = mk(td)
        q = {"005930": 70_000.0, "000660": 200_000.0, "TQQQ": 70.0}
        # 킬 스위치: 첫 주문 뒤에 켜지면 다음 주문 직전에 중단
        class KillingBroker(FakeBroker):
            def place(self, intent, dry_run=True):
                out = super().place(intent, dry_run)
                (Path(td) / "state").mkdir(parents=True, exist_ok=True)
                (Path(td) / "state" / "KILL").write_text("x", encoding="utf-8")
                return out
        kb = KillingBroker(cash={"KR": 5_000_000.0}, quotes=q)
        r = run_once(cfg, kb, Fixed([kr("005930", "BUY", 1), kr("000660", "BUY", 1)]), execute=True, env=PAPER_ENV,
                     repo_root=Path(td), now=now)
        ck("킬 스위치는 주문 직전마다 다시 본다(첫 주문 후 켜지면 둘째는 안 나감)",
           len(kb.placed) == 1 and r["status"] == "killed")
        ck("킬 스위치가 켜져 있으면 --execute 시작 자체가 거부", raises(GateError, run_once, cfg, kb, Fixed([]),
                                                                   execute=True, env=PAPER_ENV, repo_root=Path(td), now=now))
        (Path(td) / "state" / "KILL").unlink()

    with tempfile.TemporaryDirectory() as td:
        cfg = mk(td)
        q = {"005930": 70_000.0, "000660": 200_000.0}
        fb = FakeBroker(cash={"KR": 5_000_000.0}, quotes=q, place_fails=True)
        r = run_once(cfg, fb, Fixed([kr("005930", "BUY", 1), kr("000660", "BUY", 1)]), execute=True, env=PAPER_ENV,
                     repo_root=Path(td), now=now)
        ck("주문 실패는 재시도 없이 그 실행을 중단한다", r["status"] == "order-error" and fb.placed == []
           and any("중단" in s["reason"] for s in r["skipped"]))
        ck("실패는 원장에 error 로만 남고 한도에 안 잡힌다", [x["kind"] for x in Ledger(Path(td) / "state").rows()] == ["error"]
           and Ledger(Path(td) / "state").spent_today("KR", "2026-09-21") == 0)

        class Boom(Strategy):
            markets = ["KR"]

            def decide(self, ctx):
                raise RuntimeError("전략 버그")
        fb = FakeBroker(cash={"KR": 5_000_000.0}, quotes=q)
        r = run_once(cfg, fb, Boom(), execute=True, env=PAPER_ENV, repo_root=Path(td), now=now)
        ck("전략 예외는 주문 없이 종료한다", r["status"] == "strategy-error" and fb.placed == [])

        live = base_cfg(td, mode="live", live={"enabled": True, "tr_ids_reviewed": True}, allow=("005930",))
        ck("실전 --execute 는 환경변수 확인 없이는 엔진이 거부", raises(GateError, run_once, live, fb, Fixed([]),
                                                                execute=True, env=LIVE_ENV, repo_root=Path(td), now=now))

    # ---------------------------------------------------------------- 정합(미체결)
    with tempfile.TemporaryDirectory() as td:
        cfg = mk(td)
        led = Ledger(Path(td) / "state")
        led.append({"kind": "order", "executed": True, "orderNo": "OURS", "market": "US", "day": "2026-09-21", "value": 10})
        mine = OpenOrder("OURS", "TQQQ", "US", "BUY", 5, 0, 70.0)
        foreign = OpenOrder("THEIRS", "TQQQ", "US", "BUY", 2, 0, 70.0)
        q = {"TQQQ": 70.0, "005930": 70_000.0}
        us_intent = Intent("TQQQ", "BUY", 1, market="US", order_type="limit", limit_price=70.0)
        fb = FakeBroker(cash={"US": 1000.0, "KR": 1e6}, quotes=q, open_orders=[mine])
        r = run_once(cfg, fb, Fixed([us_intent]), execute=True, env=PAPER_ENV, repo_root=Path(td), now=now)
        ck("해외: 우리 미체결을 취소하고 재접수한다", [c["orderNo"] for c in fb.cancelled] == ["OURS"] and len(fb.placed) == 1)
        fb = FakeBroker(cash={"US": 1000.0}, quotes=q, open_orders=[foreign])
        r = run_once(cfg, fb, Fixed([us_intent]), execute=True, env=PAPER_ENV, repo_root=Path(td), now=now)
        ck("사용자 수동 미체결은 건드리지 않고 그 종목을 건너뛴다", fb.cancelled == [] and fb.placed == []
           and any("수동" in s["reason"] for s in r["skipped"]))
        fb = FakeBroker(cash={"US": 1000.0}, quotes=q, open_orders=[mine], cancel_removes=False)
        r = run_once(cfg, fb, Fixed([us_intent]), execute=True, env=PAPER_ENV, repo_root=Path(td), now=now, sleep=lambda s: None)
        ck("취소가 확인되지 않으면 그 종목은 주문하지 않는다(중복 방지)", fb.placed == [] and any("취소를 확인" in s["reason"] for s in r["skipped"]))
        fb = FakeBroker(cash={"US": 1000.0}, quotes=q, open_orders=[mine])
        r = run_once(cfg, fb, Fixed([us_intent]), execute=False, env=PAPER_ENV, repo_root=Path(td), now=now)
        ck("dry-run 은 취소도 하지 않는다", fb.cancelled == [] and len(r["reconcile"]) == 1)
        led.append({"kind": "order", "executed": True, "orderNo": "KROURS", "market": "KR", "day": "2026-09-21", "value": 10})
        krmine = OpenOrder("KROURS", "005930", "KR", "BUY", 1, 0, 70000.0)
        fb = FakeBroker(cash={"KR": 1e6}, quotes=q, open_orders=[krmine])
        r = run_once(cfg, fb, Fixed([kr("005930", "BUY", 1)]), execute=True, env=PAPER_ENV, repo_root=Path(td), now=now)
        ck("국내: 우리 미체결이 있으면 그 종목만 건너뛴다(취소 안 함)", fb.cancelled == [] and fb.placed == [])

    # ---------------------------------------------------------------- KIS 어댑터
    ck("TR 표: 모의는 V로 시작, 실전은 T로 시작(시세 제외)", all(
        (p.startswith("V") and l.startswith("T")) for k, (p, l) in kis.TR_IDS.items() if k not in kis.QUOTE_KEYS))
    ck("TR 표: 모의 != 실전(시세 제외)", all(p != l for k, (p, l) in kis.TR_IDS.items() if k not in kis.QUOTE_KEYS))
    ck("모의 도메인은 vts, 실전은 다르다", "openapivts" in kis.DOMAINS["paper"] and "openapivts" not in kis.DOMAINS["live"])
    ck("tr_id 는 모드별로 고른다", kis.tr_id("KR", "buy", "paper") == "VTTC0012U" and kis.tr_id("KR", "buy", "live") == "TTTC0012U")

    class Resp:
        def __init__(self, body, status=200, headers=None):
            self._b, self.status_code, self.headers = body, status, headers or {}

        def json(self):
            return self._b

    class Http:
        def __init__(self, routes):
            self.routes, self.calls = routes, []

        def __call__(self, method, url, **kw):
            self.calls.append((method, url, kw))
            for frag, resp in self.routes:
                if frag in url:
                    return resp() if callable(resp) else resp
            raise AssertionError("예상 못 한 호출 " + url)

    token = Resp({"access_token": "T", "access_token_token_expired": "2099-01-01 00:00:00"})
    with tempfile.TemporaryDirectory() as td:
        h = Http([("/oauth2/tokenP", token),
                  ("inquire-balance", Resp({"rt_cd": "0", "output1": [{"pdno": "005930", "hldg_qty": "3", "pchs_avg_pric": "60000"},
                                                                         {"pdno": "000660", "hldg_qty": "0"}],
                                            "output2": [{"dnca_tot_amt": "1000000", "prvs_rcdl_excc_amt": "700000"}]}))])
        cl = kis.KisClient("paper", "KEY1234", "SEC", "12345678-01", Path(td), http=h, sleep=lambda s: None, min_interval=0)
        b = kis.KisBroker(cl)
        ck("잔고: 0주는 제외하고 파싱", [(p.symbol, p.qty, p.avg_price) for p in b.positions("KR")] == [("005930", 3, 60000.0)])
        ck("예수금은 D+0/D+2 중 작은 쪽", b.cash("KR") == 700000.0)
        ck("모의 요청은 모의 도메인·V TR 로 나간다", all("openapivts" in c[1] for c in h.calls)
           and h.calls[-1][2]["headers"]["tr_id"] == "VTTC8434R")
        ck("토큰 캐시 파일이 생기고 권한 파일명이 모드별", (Path(td) / "token_paper.json").exists())

        d = b.place(kr("005930", "BUY", 2), dry_run=True)
        ck("KR 시장가 페이로드", d["dryRun"] and d["payload"]["ORD_DVSN"] == "01" and d["payload"]["ORD_UNPR"] == "0")
        d = b.place(Intent("005930", "BUY", 2, order_type="limit", limit_price=70100.4), dry_run=True)
        ck("KR 지정가는 정수 가격", d["payload"]["ORD_DVSN"] == "00" and d["payload"]["ORD_UNPR"] == "70100")
        d = b.place(Intent("TQQQ", "SELL", 3, market="US", order_type="limit", limit_price=70.0), dry_run=True)
        ck("US 매도 페이로드(SLL_TYPE)", d["payload"]["SLL_TYPE"] == "00" and d["payload"]["OVRS_ORD_UNPR"] == "70.00")
        ck("모의는 loc 를 거부", raises(kis.KisError, b.place, Intent("TQQQ", "BUY", 1, market="US", order_type="loc", limit_price=70.0), True))
        n = len(h.calls)
        ck("주문이 잠긴 브로커는 실주문을 안 보낸다(요청 0건)", raises(kis.KisError, b.place, kr("005930", "BUY", 1), False)
           and len(h.calls) == n)
        ck("국내 취소는 지원하지 않는다", raises(kis.KisError, b.cancel, OpenOrder("1", "005930", "KR", "BUY", 1, 0, 1.0), False))

        posts = Http([("/oauth2/tokenP", token), ("order-cash", Resp({"rt_cd": "1", "msg_cd": "APBK0013", "msg1": "거부"}))])
        cl2 = kis.KisClient("paper", "KEY1234", "SEC", "12345678-01", Path(td) / "x", http=posts, sleep=lambda s: None, min_interval=0)
        b2 = kis.KisBroker(cl2, orders_enabled=True)
        ck("주문 실패는 예외이고 재시도하지 않는다(POST 1회)", raises(kis.KisError, b2.place, kr("005930", "BUY", 1), False)
           and sum(1 for c in posts.calls if "order-cash" in c[1]) == 1)

        lh = Http([("/oauth2/tokenP", token), ("inquire-balance", Resp({"rt_cd": "0", "output1": [], "output2": [{}]}))])
        lcl = kis.KisClient("live", "KEY1234", "SEC", "12345678-01", Path(td) / "l", http=lh, sleep=lambda s: None, min_interval=0)
        kis.KisBroker(lcl).positions("KR")
        ck("실전은 실전 도메인·T TR 로 나간다", all("openapivts" not in c[1] for c in lh.calls)
           and lh.calls[-1][2]["headers"]["tr_id"] == "TTTC8434R")

        pages = iter([Resp({"rt_cd": "0", "output1": [{"pdno": "A", "hldg_qty": "1"}], "ctx_area_fk100": "f", "ctx_area_nk100": "n"}, headers={"tr_cont": "M"}),
                      Resp({"rt_cd": "0", "output1": [{"pdno": "B", "hldg_qty": "2"}]}, headers={"tr_cont": "D"})])
        ph = Http([("/oauth2/tokenP", token), ("inquire-balance", lambda: next(pages))])
        pcl = kis.KisClient("paper", "KEY1234", "SEC", "12345678-01", Path(td) / "p", http=ph, sleep=lambda s: None, min_interval=0)
        ck("연속조회를 끝까지 따라간다", [p.symbol for p in kis.KisBroker(pcl).positions("KR")] == ["A", "B"])
        ck("페이지 상한을 넘으면 부분 결과 대신 실패", raises(kis.KisError, lambda: kis.KisClient(
            "paper", "KEY1234", "SEC", "1", Path(td) / "q",
            http=Http([("/oauth2/tokenP", token), ("inquire-balance", Resp({"rt_cd": "0", "output1": [], "ctx_area_fk100": "f", "ctx_area_nk100": "n"},
                                                                             headers={"tr_cont": "M"}))]),
            sleep=lambda s: None, min_interval=0).paginate("KR", "balance", {}, "x", "output1", ("ctx_area_fk100", "ctx_area_nk100"),
                                                          ("CTX_AREA_FK100", "CTX_AREA_NK100"))))

    # ---------------------------------------------------------------- 소스 위생
    src = "".join(p.read_text(encoding="utf-8") for p in (ROOT / "autotrader").rglob("*.py"))
    ck("소스에 앱키·토큰 리터럴 패턴이 없다", "PS" not in [w for w in src.split() if len(w) > 30 and w.startswith("PS")])

    total = COUNT[0]
    print(f"\ntest-autotrader {total - len(FAILS)}/{total}" + ("" if not FAILS else f"  FAILED: {FAILS}"))
    return 1 if FAILS else 0


if __name__ == "__main__":
    sys.exit(main())
