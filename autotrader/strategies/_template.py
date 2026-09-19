"""새 전략의 출발점 — 이 파일을 복사해 `autotrader/strategies/내전략.py` 로 만든다.

1. 클래스 이름·`name`·`markets` 를 바꾼다.
2. `decide` 에서 지금 낼 주문을 `Intent` 목록으로 돌려준다(없으면 빈 목록).
3. 파일 맨 아래 `STRATEGY = 내전략` 을 유지한다.
4. 설정 파일에 `"strategy": "내전략"`, `"params": {...}` 를 적는다.

`ctx` 로 쓸 수 있는 것:
    ctx.positions("KR")            -> {종목코드: Position(qty, avg_price)}
    ctx.cash("KR")                 -> 주문가능 현금(원). 해외는 ctx.cash("US", "TQQQ") — 기준 종목 필요
    ctx.quote("005930", "KR")      -> 직전 시세
    ctx.now                        -> 지금(KST datetime)
    ctx.params                     -> 설정 파일의 params 딕셔너리
    ctx.state                      -> 실행 사이에 유지되는 딕셔너리(전략이 자유롭게 저장)

주의: 브로커를 직접 부르지 않는다. 위험 한도(risk.py)·허용목록·킬 스위치는 엔진이 강제한다.
이 템플릿은 **아무 주문도 내지 않는다.**
"""
from typing import List

from autotrader.models import Intent
from autotrader.strategy import Context, Strategy


class MyStrategy(Strategy):
    name = "my_strategy"
    markets = ["KR"]

    def decide(self, ctx: Context) -> List[Intent]:
        # 예) 삼성전자가 없으면 1주 시장가 매수:
        # if "005930" not in ctx.positions("KR"):
        #     return [Intent("005930", "BUY", 1, market="KR", order_type="market", reason="예시")]
        return []


STRATEGY = MyStrategy
