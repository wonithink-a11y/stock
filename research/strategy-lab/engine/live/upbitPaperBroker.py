"""UpbitPaperBroker - 로컬 시뮬레이션. UpbitClient의 공개 메서드(get_ticker)만
쓴다 - 인증 메서드는 절대 안 부른다(키가 없어도 100% 동작해야 한다는
업비트-연동-2026-08-27 계획 문서의 제약). KIS VTS와 달리 업비트에는
거래소가 제공하는 가짜계좌 서버가 없어서(도메인이 api.upbit.com 하나뿐)
"모의"는 이 클래스가 로컬에서 흉내낼 수밖에 없다.

engine.live.paperBroker.PaperBroker(과거 bar 기반, 체결이 다음 세션)와
다르게 실시간 ticker로 즉시 체결한다 - 크립토는 세션 개념이 없어 "다음 봉의
시가" 같은 지연 규칙이 성립하지 않는다.

상태 없는 설계 - order_no가 심볼을 그대로 담는다(예: "PAPER-KRW-BTC").
submit과 check_fill 사이에 프로세스가 재시작돼도(poll_once()는 이 둘을
서로 다른 호출에서 부른다) order_no만으로 다시 체결을 재현할 수 있다 -
메모리에 주문 장부를 들고 있다가 재시작으로 잃어버리는 실패 모드 자체가
없다. check_fill은 항상 즉시 fullyFilled=True를 반환한다(제출과 체결
사이에 흉내낼 실제 지연이 없다) - poll_once()의 ENTRY_SUBMITTED/
EXIT_SUBMITTED 상태는 한 poll 틱만 거쳐간다.
"""
from .upbitClient import UpbitClient

_PREFIX = "PAPER-"


class UpbitPaperBroker:
    def __init__(self, client=None):
        self.client = client or UpbitClient()

    def submit_buy(self, symbol, quantity):
        return _PREFIX + symbol

    def submit_sell(self, symbol, quantity):
        return _PREFIX + symbol

    def check_fill(self, order_no, order_date_yyyymmdd, requested_qty):
        symbol = order_no[len(_PREFIX):] if order_no.startswith(_PREFIX) else order_no
        price = self.client.get_ticker(symbol)
        return {"fullyFilled": True, "rejected": False,
                "filledQty": requested_qty, "avgPrice": price, "pending": False}

    def current_price(self, symbol):
        return self.client.get_ticker(symbol)
