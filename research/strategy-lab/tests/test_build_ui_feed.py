"""build_ui_feed.py의 _position_row() self-check. KIS도 A2a도 안 건드린다.

왜 있는가(2026-09-09 실측): 이 함수가 수량을 계좌 보유수량으로 덮어쓰고 있었다.
pbr_value_v1 은 29종목 중 25종목이 pbr_value_v1_combined 와 겹쳐서, 겹치는 종목이
두 전략 모두에 계좌 전량으로 찍혔다 - 전략별 평가금액 합 262.9백만원(실제 주식
평가액 130.5백만원), UI 도넛의 "예수금(미배분)" 233.8백만원(실제 368.2백만원).
"""
import importlib.util
import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(_HERE))
_spec = importlib.util.spec_from_file_location(
    "build_ui_feed", os.path.join(os.path.dirname(_HERE), "build_ui_feed.py"))
feed = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(feed)

passed, failed = 0, 0


def ok(name, cond, detail=""):
    global passed, failed
    if cond:
        passed += 1
    else:
        failed += 1
        print(f"  FAIL  {name}  {detail}")


def _holding(qty, prpr, avg):
    return {"pdno": "021820", "hldg_qty": str(qty), "prpr": str(prpr),
            "pchs_avg_pric": str(avg), "evlu_pfls_amt": "999999", "evlu_pfls_rt": "99.9"}


def test_open_uses_strategy_book_not_account_quantity():
    """계좌는 346주(두 전략 합)를 들고 있어도 이 전략의 몫은 16주다."""
    pos = {"status": "OPEN", "quantity": 16, "entry_price": 10_000.0}
    row = feed._position_row("021820", pos, _holding(346, 11_000, 9_500), [])
    ok("수량은 전략 장부", row["quantity"] == 16, row)
    ok("진입단가도 전략 장부", row["avgEntryPrice"] == 10_000.0, row)
    # (11,000 - 10,000) x 16 = 16,000  (계좌가 준 999,999 가 아니다)
    ok("손익을 전략 몫으로 다시 계산", row["unrealizedPnlKrw"] == 16_000, row)
    ok("손익률도", row["unrealizedPnlPct"] == 10.0, row)


def test_mid_entry_uses_filled_quantity_not_target():
    """탑업 중(PENDING_ENTRY)에는 quantity 가 목표지 보유가 아니다."""
    pos = {"status": "PENDING_ENTRY", "quantity": 330, "target_quantity": 330,
           "filled_quantity": 16, "entry_price": 10_000.0}
    row = feed._position_row("021820", pos, _holding(346, 11_000, 9_500), [])
    ok("목표가 아니라 확인된 보유량", row["quantity"] == 16, row)
    ok("손익도 확인된 보유량 기준", row["unrealizedPnlKrw"] == 16_000, row)


def test_fresh_pending_entry_holds_nothing():
    """아직 한 주도 안 산 의도 - 계좌에 그 종목이 있어도(다른 전략이 샀다)
    이 전략의 보유는 0 이다. 옛 코드가 여기서 남의 보유를 제 것으로 읽었다."""
    pos = {"status": "PENDING_ENTRY", "quantity": 330, "intent_date": "2026-09-01"}
    row = feed._position_row("021820", pos, _holding(330, 11_000, 9_500), [])
    ok("보유 0", row["quantity"] == 0, row)
    ok("손익 0", row["unrealizedPnlKrw"] == 0, row)


def test_not_in_account_is_left_unmarked():
    pos = {"status": "PENDING_ENTRY", "quantity": 5, "intent_date": "2026-09-01"}
    row = feed._position_row("021820", pos, None, [])
    ok("시세·손익 없음", "currentPrice" not in row and "unrealizedPnlKrw" not in row, row)
    ok("상태·의도일은 남는다", row["status"] == "PENDING_ENTRY" and row["intentDate"] == "2026-09-01", row)


def test_falls_back_to_account_avg_when_book_has_no_entry_price():
    """옛 상태(entry_price 없음)도 죽지 않는다 - 계좌 평균단가로 대체한다."""
    pos = {"status": "OPEN", "quantity": 10}
    row = feed._position_row("021820", pos, _holding(10, 11_000, 9_500), [])
    ok("계좌 평균단가로 대체", row["avgEntryPrice"] == 9_500.0, row)
    ok("손익 = (11000-9500)x10", row["unrealizedPnlKrw"] == 15_000, row)


def test_strategy_rows_sum_to_account_when_books_are_consistent():
    """겹치는 종목을 두 전략이 나눠 들고 있을 때, 두 행의 합이 계좌 보유수량과
    같아야 한다 - 이게 도넛의 예수금이 맞아떨어지는 조건이다."""
    h = _holding(346, 11_000, 9_500)
    a = feed._position_row("021820", {"status": "OPEN", "quantity": 16, "entry_price": 10_000.0}, h, [])
    b = feed._position_row("021820", {"status": "OPEN", "quantity": 330, "entry_price": 10_500.0}, h, [])
    ok("두 전략 합 == 계좌", a["quantity"] + b["quantity"] == 346, (a["quantity"], b["quantity"]))


# --- _aggregate_trades (2026-09-11 신설) -------------------------------------
# UI 의 "리밸런싱 내역"이 읽는 날짜별 매수·매도 합계. 이게 틀리면 화면이
# 조용히 틀린 금액을 말한다 - 원본이 계좌 체결내역이라 대조할 데가 화면뿐이다.

def _exec(date, symbol, side, filled, amount, pending=0, ordered=None, canceled=False):
    return {"date": date, "symbol": symbol, "name": symbol, "side": side,
            "orderedQty": ordered if ordered is not None else filled + pending,
            "filledQty": filled, "avgPrice": 100.0, "amountKrw": amount,
            "pendingQty": pending, "rejectedQty": 0, "canceled": canceled}


def test_aggregate_trades_sums_buy_and_sell_per_day():
    out = feed._aggregate_trades([
        _exec("2026-09-04", "021820", "BUY", 10, 1_000),
        _exec("2026-09-04", "001080", "BUY", 5, 500),
        _exec("2026-09-04", "058430", "SELL", 3, 300),
        _exec("2026-09-07", "013580", "SELL", 7, 700),
    ])
    days = {d["date"]: d for d in out["days"]}
    ok("매수 합", days["2026-09-04"]["buyKrw"] == 1_500, days["2026-09-04"])
    ok("매도 합", days["2026-09-04"]["sellKrw"] == 300, days["2026-09-04"])
    ok("건수", (days["2026-09-04"]["buyCount"], days["2026-09-04"]["sellCount"]) == (2, 1), days["2026-09-04"])
    ok("순매수 = 매수-매도", days["2026-09-04"]["netKrw"] == 1_200, days["2026-09-04"])
    ok("매도만 있는 날", days["2026-09-07"]["netKrw"] == -700, days["2026-09-07"])
    ok("최신 날짜가 먼저", [d["date"] for d in out["days"]] == ["2026-09-07", "2026-09-04"], out["days"])


def test_aggregate_trades_excludes_unfilled_from_amounts_but_lists_them_pending():
    """미체결 주문을 금액에 넣으면 '안 산 걸 샀다'가 된다(절대 규칙 1).
    그렇다고 버리면 '지금 매매가 도는 중'을 못 본다 - 다른 칸으로 보낸다."""
    out = feed._aggregate_trades([
        _exec("2026-09-11", "021820", "BUY", 0, 0, pending=10),
        _exec("2026-09-11", "001080", "BUY", 4, 400, pending=6),
    ])
    ok("체결분만 금액에", out["days"][0]["buyKrw"] == 400, out["days"])
    ok("부분체결도 1건", out["days"][0]["buyCount"] == 1, out["days"])
    ok("미체결 2건이 pending 에", len(out["pending"]) == 2, out["pending"])
    ok("부분체결은 양쪽에 다 뜬다",
       {p["symbol"] for p in out["pending"]} == {"021820", "001080"}, out["pending"])


def test_aggregate_trades_pending_is_today_only():
    """KRX 주문은 당일 유효다. 어제의 미체결은 장 종료로 실효됐는데 응답의
    rmn_qty 는 그대로 남는다 - 날짜로 안 자르면 죽은 주문이 "진행 중"에
    영원히 쌓인다. 취소된 주문도 진행 중이 아니다."""
    rows = [
        _exec("2026-09-11", "021820", "BUY", 0, 0, pending=10),
        _exec("2026-09-04", "001080", "BUY", 0, 0, pending=42),   # 어제 미체결 - 실효
        _exec("2026-09-11", "058430", "SELL", 0, 0, pending=5, canceled=True),
    ]
    out = feed._aggregate_trades(rows, today="2026-09-11")
    ok("오늘 것만 진행 중", [p["symbol"] for p in out["pending"]] == ["021820"], out["pending"])
    ok("today 없으면 안 자른다", len(feed._aggregate_trades(rows)["pending"]) == 2,
       feed._aggregate_trades(rows)["pending"])


def test_aggregate_trades_empty_is_empty_not_error():
    out = feed._aggregate_trades([])
    ok("빈 입력", out == {"days": [], "pending": []}, out)


if __name__ == "__main__":
    for fn in (test_open_uses_strategy_book_not_account_quantity,
               test_mid_entry_uses_filled_quantity_not_target,
               test_fresh_pending_entry_holds_nothing,
               test_not_in_account_is_left_unmarked,
               test_falls_back_to_account_avg_when_book_has_no_entry_price,
               test_strategy_rows_sum_to_account_when_books_are_consistent,
               test_aggregate_trades_sums_buy_and_sell_per_day,
               test_aggregate_trades_excludes_unfilled_from_amounts_but_lists_them_pending,
               test_aggregate_trades_pending_is_today_only,
               test_aggregate_trades_empty_is_empty_not_error):
        fn()
    print(f"test_build_ui_feed: {passed} passed, {failed} failed")
    sys.exit(1 if failed else 0)
