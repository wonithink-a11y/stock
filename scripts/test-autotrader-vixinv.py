#!/usr/bin/env python3
"""autotrader VIX 인버스 플러그인 회귀 — 키·네트워크 없이 돈다. 주문은 내지 않는다(FakeBroker·계획 확인만).

    python scripts/test-autotrader-vixinv.py
"""
import datetime as dt
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from autotrader.broker import FakeBroker                    # noqa: E402
from autotrader.engine import KST                           # noqa: E402
from autotrader.models import Position                      # noqa: E402
from autotrader.strategies import vix_inverse as VI         # noqa: E402
from autotrader.strategy import Context                     # noqa: E402

FAILS, COUNT = [], [0]


def ck(name, cond):
    COUNT[0] += 1
    if not cond:
        FAILS.append(name)
    print(("ok   " if cond else "FAIL ") + name)


def closes(vals, end="2026-11-02"):
    """마지막 값이 end 일. 앞은 평일 역순."""
    d, out = dt.date.fromisoformat(end), []
    for v in reversed(vals):
        while d.weekday() >= 5:
            d -= dt.timedelta(days=1)
        out.append((d, v))
        d -= dt.timedelta(days=1)
    return out[::-1]


NOW = datetime(2026, 11, 3, 23, 35, tzinfo=KST)             # 미국 동부 09:35(겨울)
P = {"symbol": "SVIX", "capital_usd": 1000, "split": True, "join_current_cycle": True}


def run(vals, params=None, pos=None, st=None, now=NOW, qn=dt.date(2026, 10, 28), quote=25.0):
    VI._vix_closes = lambda: closes(vals)
    VI._qn_posted = lambda: qn
    fb = FakeBroker(cash={"US": 5000}, quotes={"SVIX": quote, "SVXY": quote}, positions={"US": pos or []})
    ctx = Context(fb, now, {**P, **(params or {})}, st if st is not None else {})
    return VI.STRATEGY().decide(ctx), ctx


def pos(q, avg):
    return [Position("SVIX", "US", q, avg)]


# 규칙: 14 -> 15(대기) -> 21 진입(1칸)
out, c = run([14, 15, 21])
ck("진입 신호: 1칸 지정가 매수(시세 +0.5%)", len(out) == 1 and out[0].side == "BUY" and out[0].limit_price == 25.12 and out[0].qty == 9)
ck("한 칸 = capital/4 를 넘지 않는다", out[0].qty * out[0].limit_price <= 250)
ck("상태 기록", c.state["lastBar"] == "2026-11-02" and c.state["targetTranche"] == 1)

out, _ = run([14, 15, 31])
ck("갭 급등 31: 한 번에 3칸(750달러)", out[0].qty * out[0].limit_price <= 750 and out[0].qty >= 29)

out, _ = run([14, 15, 21], pos=pos(9, 25.0))
ck("이미 1칸 보유 + 목표 1칸이면 주문 없음(멱등)", out == [])
out, _ = run([14, 15, 21], pos=pos(9, 25.0), quote=40.0)
ck("원가 기준 — 가격이 올라도 추가 매수 안 함", out == [])
out, _ = run([14, 15, 21, 26], pos=pos(9, 25.0))
ck("26 처음 넘으면 2칸 목표 -> 1칸 추가", len(out) == 1 and out[0].side == "BUY" and 8 <= out[0].qty <= 10)
out, _ = run([14, 15, 21, 26, 22], pos=pos(18, 25.0))
ck("VIX 가 내려도 단계는 줄이지 않는다", out == [])
out, _ = run([14, 15, 21, 26, 15.5], pos=pos(18, 25.0))
ck("≤16 청산: 전량 지정가 매도(시세 -0.5%)", len(out) == 1 and out[0].side == "SELL" and out[0].qty == 18 and out[0].limit_price == 24.88)
out, _ = run([14, 15, 18, 19], pos=[])
ck("대기·무보유면 주문 없음", out == [])
out, _ = run([14, 21], pos=pos(8, 25.0), params={"split": False})
ck("한번에: 보유 1칸 이면 3칸 더(100%까지)", len(out) == 1 and out[0].qty >= 26)

# 진행 중 사이클 건너뛰기
out, c = run([14, 21], params={"join_current_cycle": False})
ck("join=false 면 진행 중 사이클 건너뜀 + 노트", out == [] and c.state["skip_cycle"] and any("건너뛴다" in n for n in c.notes))
st = {"skip_entry": "2026-10-29"}                           # 옛 사이클(10-29 진입)을 건너뛰기로 했다
out, c2 = run([14, 21, 15, 22], params={"join_current_cycle": False}, st=st)
ck("청산 뒤 새 진입은 매수", len(out) == 1 and not c2.state["skip_cycle"])

# 데이터·시간 방어
out, c = run([14, 21], now=datetime(2026, 11, 3, 17, 0, tzinfo=KST))
ck("정규장 밖이면 주문 없이 노트", out == [] and any("정규장 밖" in n for n in c.notes))
out, c = run([14, 21], now=datetime(2026, 11, 9, 23, 35, tzinfo=KST))
ck("VIX 일봉이 낡으면 주문 없음", out == [] and any("낡았다" in n for n in c.notes))
VI._vix_closes = lambda: closes([14, 21]) + [(dt.date(2026, 11, 3), 12.0)]
fb = FakeBroker(cash={"US": 5000}, quotes={"SVIX": 25.0})
VI._qn_posted = lambda: dt.date(2026, 10, 28)
c = Context(fb, NOW, dict(P), {})
out = VI.STRATEGY().decide(c)
ck("오늘(미완성) 일봉은 버린다 — 12.0 이 청산 신호로 안 읽힌다", len(out) == 1 and out[0].side == "BUY")
VI._vix_closes = lambda: closes([20, 21, 22])
try:
    VI.STRATEGY().decide(Context(fb, NOW, dict(P), {}))
    ck("VIX ≤16 없는 창은 ValueError(SystemExit 새지 않음)", False)
except ValueError:
    ck("VIX ≤16 없는 창은 ValueError(SystemExit 새지 않음)", True)

# QN 알림 — 매도를 막지 않는다
out, c = run([14, 21, 15], pos=pos(9, 25.0), qn=dt.date(2026, 8, 20))
ck("QN 만료 임박이어도 매도 intent 는 나간다", len(out) == 1 and out[0].side == "SELL")
ck("QN 임박 노트", any("만료" in n for n in c.notes))
out, c = run([14, 21], qn=dt.date(2026, 10, 28))
ck("QN 여유면 노트 없음", not any("면제" in n for n in c.notes))
out, c = run([14, 21], params={"symbol": "SVXY"}, quote=60.0)
ck("SVXY 는 '확인 못 함' 노트", any("SVXY" in n and "확인 못" in n for n in c.notes))

print(f"\n{COUNT[0] - len(FAILS)}/{COUNT[0]} ok")
sys.exit(1 if FAILS else 0)
