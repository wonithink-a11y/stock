"""Intraday time-exit — isolated extension for CAND1's validated 익일 09:35 청산.

설계: findings/cand1-engine-integration-design-2026-08.md 옵션 B.
executor.py의 기존 STOP/TARGET/TIME_EXIT 경로(simulate_trade)는 **무변경**이다
— 이 모듈은 그 경로를 호출도, 수정도 하지 않는다. CAND1은 stop/target이
없는 고정시각 청산이라 기존 stop/target 매칭 루프가 애초에 불필요하다
(위 설계문서 §2 "이건 확장 범위를 좁히는 유리한 사실").

기존 Order/Fill 데이터 계약(contracts.py)은 그대로 재사용한다 — 새 필드도,
새 클래스도 추가하지 않았다. 새로 도입하는 건 `fill_type` 값 하나
("INTRADAY_TIME_EXIT")뿐이고, 그건 문자열이라 contracts.py의 dataclass
정의 자체를 건드릴 필요가 없다.

PIT: `resolve_intraday_price()`는 요청한 정확히 그 시각(`exit_hhmm`)의 봉
"하나"만 인덱스로 골라 쓴다 — 그 이후 시각의 봉을 읽거나 필요로 하지
않는다(설계상 보장, 아래 tests/test_intraday_exit.py가 이 성질을 직접
검증한다). 결측(그 시각에 틱이 없음)은 None을 돌려주고 지어내지 않는다
(절대 규칙 1 · 교훈75와 같은 원칙).
"""
from .contracts import Fill, Order

FILL_TYPE_INTRADAY_TIME_EXIT = "INTRADAY_TIME_EXIT"


def resolve_intraday_price(minute_bars, exit_hhmm):
    """minute_bars: 한 종목의 DataFrame[open,high,low,close,volume], tz-aware
    ts 인덱스, 호출자가 이미 특정 날짜 하나로 슬라이스해서 넘긴다(이 함수는
    날짜 슬라이싱을 하지 않는다 — provider I/O와 분리해 순수 함수로 둔다).

    반환: exit_hhmm 정각 봉의 close, 또는 그 시각에 봉이 없으면 None.
    """
    if minute_bars is None or len(minute_bars) == 0:
        return None
    hhmm = minute_bars.index.strftime("%H:%M")
    match = minute_bars[hhmm == exit_hhmm]
    if len(match) == 0:
        return None
    return float(match["close"].iloc[0])


def simulate_intraday_exit_trade(symbol, signal_date, entry_date, entry_price,
                                  minute_bars_on_entry_date, cost_model,
                                  exit_hhmm="09:35"):
    """entry_price는 호출자가 이미 확정해 넘긴다(어떤 일봉 소스를 쓸지는 이
    모듈의 관심사가 아니다 — CAND1 검증에 쓰인 것과 같은 소스를 호출자가
    선택해야 '동일 조건 대조'가 성립한다).

    반환: (entry_fill, exit_fill) — 기존 simulate_trade()와 같은 모양.
    exit_hhmm 봉이 없으면 None(지어내지 않음, 기존 executor의
    "런아웃되면 None" 관례와 동일).
    """
    order = Order(symbol=symbol, signal_date=signal_date, order_date=entry_date,
                  direction="LONG", risk_spec=None)
    entry_fill = Fill(order, entry_date, float(entry_price), "OPEN",
                       cost_model.entry_cost_bps, cost_model.slippage_bps)

    exit_price = resolve_intraday_price(minute_bars_on_entry_date, exit_hhmm)
    if exit_price is None:
        return None

    exit_fill = Fill(order, entry_date, exit_price, FILL_TYPE_INTRADAY_TIME_EXIT,
                      cost_model.exit_cost_bps, cost_model.slippage_bps)
    return entry_fill, exit_fill


def trade_return(entry_fill, exit_fill):
    """왕복 수익률 — CAND1이 검증한 gross=exit/entry-1, net=gross-cost_bps/1e4
    공식과 동일한 값이 나오도록, entry_cost_bps+exit_cost_bps 합을 그 단일
    cost_bps로 맞춰 호출해야 한다(호출자 책임 — 이 함수는 강제하지 않는다,
    CostModel의 두 필드 분리 자체는 기존 계약이라 이 모듈에서 안 바꿈)."""
    gross = exit_fill.fill_price / entry_fill.fill_price - 1.0
    total_cost_bps = entry_fill.cost_bps + exit_fill.cost_bps
    net = gross - total_cost_bps / 1e4
    return gross, net
