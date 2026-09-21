#!/usr/bin/env python3
"""autotrader 무한매수 플러그인 회귀 — 옛 러너(run_infinite_buying_daily vts)와 같은 계획을 내는가. 키·네트워크 없이 돈다.

규칙 값은 가짜다(진짜는 로컬 전용). 보는 것은 수치가 아니라 배선: 엔진 계획과 1:1 · 모의=지정가/실전=LOC ·
MOC 건너뜀 · T 잇기(매수·매도) · 옛 상태 이어받기 · 분할수 변경 차단 · 같은 종목 여러 호가가 엔진 중복검사에 안 걸림.

    python scripts/test-autotrader-infbuy.py
"""
import json
import sys
import tempfile
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "research" / "strategy-lab"))

import infinite_buying_engine as E                                            # noqa: E402
from autotrader.broker import FakeBroker                                      # noqa: E402
from autotrader.config import normalize_config                                # noqa: E402
from autotrader.engine import KST, run_once                                   # noqa: E402
from autotrader.models import Position                                        # noqa: E402
from autotrader.strategies import infinite_buying as IB                       # noqa: E402
from autotrader.strategy import Context                                       # noqa: E402

FAILS, COUNT = [], [0]


def ck(name, cond):
    COUNT[0] += 1
    if not cond:
        FAILS.append(name)
    print(("ok   " if cond else "FAIL ") + name)


FAKE_RULES = {"basePct": {"TQQQ": 10.0, "SOXL": 12.0}, "tick": 0.01, "starSlope": 1.0, "quarterFrac": 0.25,
              "reverseEnterT": 1.0, "reverseSellDiv": 10.0, "reverseBuyFrac": 0.25, "reverseStarWindow": 5}
BARS = [{"date": f"2026-09-{d:02d}", "open": 50.0, "high": 50.0, "low": 50.0, "close": 50.0 + d * 0.1} for d in range(1, 21)]
IB._bars = lambda tk: BARS                                                    # noqa: E731


def ctx_for(broker, params, state):
    return Context(broker, datetime(2026, 9, 22, 21, 30, tzinfo=KST), params, state)


def main():
    with tempfile.TemporaryDirectory() as td:
        rules = Path(td) / "rules.json"
        rules.write_text(json.dumps(FAKE_RULES), encoding="utf-8")
        params = {"rules_file": str(rules), "tickers": ["TQQQ"], "seed_usd": 10000, "splits": 40}
        r = E.Rules.load(rules, "TQQQ", 40, seed=10000.0)

        # ---- 빈 계좌 첫날: 엔진 계획과 1:1
        fb = FakeBroker(cash={"US": 20000}, quotes={"TQQQ": 52.0})
        st = {}
        got = IB.InfiniteBuying().decide(ctx_for(fb, params, st))
        want = E.plan_orders(E.State(cash=10000.0), r, [b["close"] for b in BARS])
        agg = {}
        for sd, _, lim, q in want:
            if lim is not None:
                agg[(sd.upper(), lim)] = agg.get((sd.upper(), lim), 0) + q
        ck("엔진 계획이 비어 있지 않다", len(got) > 0)
        ck("가격·수량·방향이 엔진 그대로(같은 가격은 합산)", {(i.side, i.limit_price): i.qty for i in got} == agg)
        ck("모의투자는 LOC 를 지정가로", all(i.order_type == "limit" for i in got))
        ck("잔금 = min(배정액-원가, 주문가능)", abs(st["tickers"]["TQQQ"]["state"]["cash"] - 10000.0) < 1e-9)
        unit = st["tickers"]["TQQQ"]["lastUnit"]
        ck("lastUnit 을 남긴다(다음 실행의 T 잇기)", unit and abs(unit - 10000.0 / 40) < 1e-9)

        fb.mode = "live"
        got_live = IB.InfiniteBuying().decide(ctx_for(fb, params, {}))
        ck("실전은 LOC 그대로", any(i.order_type == "loc" for i in got_live))
        fb.mode = "paper"

        # ---- 다음 날: 매수 체결분만큼 T 가 오른다(러너와 같은 식)
        fb2 = FakeBroker(positions={"US": [Position("TQQQ", "US", 5, 50.0)]}, cash={"US": 20000}, quotes={"TQQQ": 52.0})
        IB.InfiniteBuying().decide(ctx_for(fb2, params, st))
        ck("매수 체결 → T += 체결금액/1회매수금", abs(st["tickers"]["TQQQ"]["state"]["t"] - 250.0 / unit) < 1e-9)
        t1 = st["tickers"]["TQQQ"]["state"]["t"]
        ck("잔금에서 투입 원가를 뺀다", abs(st["tickers"]["TQQQ"]["state"]["cash"] - (10000 - 250)) < 1e-9)
        fb3 = FakeBroker(positions={"US": [Position("TQQQ", "US", 2, 50.0)]}, cash={"US": 20000}, quotes={"TQQQ": 52.0})
        IB.InfiniteBuying().decide(ctx_for(fb3, params, st))
        ck("매도 → T 는 남은 수량 비율", abs(st["tickers"]["TQQQ"]["state"]["t"] - t1 * 2 / 5) < 1e-9)

        # ---- 분할수 변경 차단
        try:
            IB.InfiniteBuying().decide(ctx_for(fb3, {**params, "splits": 20}, st))
            ck("보유가 있는데 분할수를 바꾸면 막는다", False)
        except ValueError:
            ck("보유가 있는데 분할수를 바꾸면 막는다", True)

        # ---- 옛 러너 상태 이어받기
        old = Path(td) / "old"
        old.mkdir()
        (old / "TQQQ_vts.json").write_text(json.dumps({"state": {"t": 0.86, "qty": 3, "cost": 150.0, "cash": 1.0},
                                                       "lastUnit": 250.0, "splits": 40, "lastDate": "2026-09-11"}),
                                           encoding="utf-8")
        st2 = {}
        fb4 = FakeBroker(positions={"US": [Position("TQQQ", "US", 3, 50.0)]}, cash={"US": 20000}, quotes={"TQQQ": 52.0})
        IB.InfiniteBuying().decide(ctx_for(fb4, {**params, "import_state_dir": str(old)}, st2))
        ck("옛 러너의 T 를 이어받는다", abs(st2["tickers"]["TQQQ"]["state"]["t"] - 0.86) < 1e-9
           and st2["tickers"]["TQQQ"]["importedLastDate"] == "2026-09-11")
        (old / "TQQQ_vts.json").write_text(json.dumps({"state": {"t": 9.0}}), encoding="utf-8")
        IB.InfiniteBuying().decide(ctx_for(fb4, {**params, "import_state_dir": str(old)}, st2))
        ck("이어받기는 한 번뿐(이후 옛 파일을 안 본다)", abs(st2["tickers"]["TQQQ"]["state"]["t"] - 0.86) < 1e-9)

        # ---- 엔진 전체 경로: 같은 종목 여러 호가가 중복으로 거부되지 않는다
        cfg = normalize_config({"strategy": "infinite_buying", "mode": "paper", "markets": ["US"], "symbol_allowlist": ["TQQQ"],
                                "params": params, "state_dir": str(Path(td) / "state"),
                                "risk": {"US": {"max_order_value": 5000, "max_daily_value": 20000, "max_orders_per_run": 20,
                                                "price_band_pct": 30, "max_position_value": 20000}}})
        fb5 = FakeBroker(positions={"US": [Position("TQQQ", "US", 5, 50.0)]}, cash={"US": 20000}, quotes={"TQQQ": 52.0})
        rep = run_once(cfg, fb5, IB.InfiniteBuying(), execute=True,
                       env={"KIS_VTS_APP_KEY": "k", "KIS_VTS_APP_SECRET": "s", "KIS_VTS_ACCOUNT_NO": "1-01"},
                       repo_root=Path(td), now=datetime(2026, 9, 22, 21, 30, tzinfo=KST))
        buys = [p for p in fb5.placed if p["side"] == "BUY"]
        sells = [p for p in fb5.placed if p["side"] == "SELL"]
        ck("같은 종목 여러 호가가 모두 접수(중복 오탐 없음)", len(buys) >= 2 and rep["rejected"] == [])
        ck("같은 가격 매도(LOC 쿼터+지정가 나머지)는 한 주문으로 합쳐 보유 전량", sum(p["qty"] for p in sells) == 5)
        ck("전략 상태가 프로필 상태 폴더에 저장", (Path(td) / "state" / "strategy_infinite_buying.json").exists())

    print(f"\ntest-autotrader-infbuy {COUNT[0] - len(FAILS)}/{COUNT[0]}")
    return 1 if FAILS else 0


if __name__ == "__main__":
    sys.exit(main())
