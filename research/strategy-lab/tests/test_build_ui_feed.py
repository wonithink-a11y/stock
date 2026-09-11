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

def _exec(date, symbol, side, filled, amount, pending=0, ordered=None, canceled=False, order_no="", avg=100.0):
    return {"orderNo": order_no, "date": date, "symbol": symbol, "name": symbol, "side": side,
            "orderedQty": ordered if ordered is not None else filled + pending,
            "filledQty": filled, "avgPrice": avg, "amountKrw": amount,
            "pendingQty": pending, "rejectedQty": 0, "canceled": canceled}


def test_account_block_keeps_both_cash_figures():
    """예수금이 둘이다 - D+0(dnca)와 D+2(가용). 하나만 내면 화면의 다른 숫자와
    어긋나 보인다. 실측 2026-09-11 값 그대로."""
    summary = {"prvs_rcdl_excc_amt": "100596273", "bfdy_buy_amt": "49675474",
               "bfdy_tlex_amt": "6890", "scts_evlu_amt": "400812136",
               "pchs_amt_smtl_amt": "399348207"}
    a = feed._account_block("150278637", "501408409", summary)
    ok("D+0 예수금", a["cashKrw"] == 150278637, a)
    ok("D+2 가용", a["cashAvailableKrw"] == 100596273, a)
    ok("차이 = 결제대기 + 제비용",
       round(a["cashKrw"] - a["cashAvailableKrw"]) == round(a["settlingKrw"] + a["settlingFeeKrw"]), a)
    ok("총평가 = 유가증권 + D+2 예수금",
       round(a["stockValueKrw"] + a["cashAvailableKrw"]) == round(a["totalValueKrw"]), a)
    ok("주식평가액은 빼서 구하지 않는다(scts 그대로)", a["stockValueKrw"] == 400812136, a)


def test_account_block_survives_missing_summary():
    a = feed._account_block(None, None, {})
    ok("조회 실패면 전부 None - 0으로 메우지 않는다",
       all(a[k] is None for k in a), a)


def test_equity_history_appends_one_row_per_day():
    import tempfile
    from pathlib import Path
    with tempfile.TemporaryDirectory() as tmp:
        p = str(Path(tmp) / "equity-history.json")
        acct = {"totalValueKrw": 501408409.0, "stockValueKrw": 400812136.0, "cashKrw": 150278637.0}
        feed._append_equity(acct, today="2026-09-11", path=p)
        rows = feed._append_equity({**acct, "totalValueKrw": 502000000.0},
                                    today="2026-09-11", path=p)
        ok("같은 날은 덮어쓴다(하루 여러 번 돈다)", len(rows) == 1, rows)
        ok("마지막 회차 값이 남는다", rows[0]["totalKrw"] == 502000000, rows)
        rows = feed._append_equity(acct, today="2026-09-14", path=p)
        ok("다음 날은 새 줄", [r["date"] for r in rows] == ["2026-09-11", "2026-09-14"], rows)


def test_equity_history_skips_when_value_unknown():
    """조회 실패를 0이나 직전 값으로 메우면 차트가 '그날 계좌가 0이었다' 또는
    '안 움직였다'고 거짓말한다(교훈57). 줄을 안 쓴다."""
    import tempfile
    from pathlib import Path
    with tempfile.TemporaryDirectory() as tmp:
        p = str(Path(tmp) / "equity-history.json")
        ok("총평가액 없으면 안 쓴다",
           feed._append_equity({"totalValueKrw": None}, today="2026-09-11", path=p) is None)
        ok("파일도 안 만든다", not Path(p).exists())


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
    ok("빈 입력", out["days"] == [] and out["pending"] == [], out)
    ok("빈 입력 - 전략도 빔", out["byStrategy"] == {}, out)
    ok("빈 입력 - 미귀속 0", out["unattributed"]["count"] == 0, out)


def test_aggregate_trades_splits_by_strategy_via_order_ledger():
    """같은 종목을 두 전략이 같은 날 사도 주문번호가 다르므로 갈린다 -
    이게 원장을 넣은 이유다. 수량·종목으로 되짚는 짐작과 다르다."""
    rows = [
        _exec("2026-09-04", "021820", "BUY", 330, 3_400_000, order_no="A1"),
        _exec("2026-09-04", "021820", "BUY", 16, 165_000, order_no="A2"),
        _exec("2026-09-04", "058450", "SELL", 100, 140_000, order_no="A3"),
    ]
    owner = {k: {"strategy": v} for k, v in
             {"A1": "pbr_value_v1", "A2": "pbr_value_v1_combined", "A3": "pbr_value_v1"}.items()}
    out = feed._aggregate_trades(rows, order_meta=owner)
    a = out["byStrategy"]["pbr_value_v1"][0]
    b = out["byStrategy"]["pbr_value_v1_combined"][0]
    ok("전략A 매수", a["buyKrw"] == 3_400_000, a)
    ok("전략A 매도", a["sellKrw"] == 140_000, a)
    ok("전략B 매수", b["buyKrw"] == 165_000, b)
    ok("계좌 합계는 그대로", out["days"][0]["buyKrw"] == 3_565_000, out["days"])
    ok("전부 귀속되면 미귀속 0", out["unattributed"]["count"] == 0, out["unattributed"])


def test_aggregate_trades_unknown_order_is_unattributed_not_guessed():
    """원장에 없는 주문(원장 도입 이전 것)을 종목·수량으로 어느 전략에 밀어
    넣으면 지어내는 것이 된다(절대 규칙 1). 따로 세서 화면이 말하게 한다."""
    rows = [
        _exec("2026-08-03", "021820", "BUY", 330, 3_400_000, order_no="OLD"),
        _exec("2026-09-04", "001080", "BUY", 42, 165_000, order_no="NEW"),
    ]
    out = feed._aggregate_trades(rows, order_meta={"NEW": {"strategy": "pbr_value_v1"}})
    ok("모르는 주문은 전략에 안 들어간다",
       list(out["byStrategy"]) == ["pbr_value_v1"], out["byStrategy"])
    ok("귀속된 전략 금액은 그것만",
       out["byStrategy"]["pbr_value_v1"][0]["buyKrw"] == 165_000, out["byStrategy"])
    ok("미귀속으로 센다", out["unattributed"] == {"buyKrw": 3_400_000, "sellKrw": 0, "count": 1},
       out["unattributed"])
    ok("계좌 합계에는 둘 다 들어간다",
       sum(d["buyKrw"] for d in out["days"]) == 3_565_000, out["days"])


def test_realized_pnl_from_ledger_entry_price():
    """실현손익 = (체결평균가 - 진입가) x 체결수량. 진입가는 원장에만 있다 -
    매도가 체결되면 포지션이 삭제돼서 그 뒤로는 알 데가 없다."""
    rows = [_exec("2026-09-04", "021820", "SELL", 100, 1_100_000, order_no="S1", avg=11_000.0)]
    meta = {"S1": {"strategy": "pbr_value_v1", "side": "SELL", "entryPrice": 10_000.0}}
    out = feed._aggregate_trades(rows, order_meta=meta)
    ok("실현손익 = (11000-10000)*100", out["days"][0]["realizedKrw"] == 100_000, out["days"])
    ok("몇 건으로 쟀는지도 남는다", out["days"][0]["realizedFrom"] == 1, out["days"])
    ok("전략별에도 같은 값",
       out["byStrategy"]["pbr_value_v1"][0]["realizedKrw"] == 100_000, out["byStrategy"])


def test_realized_pnl_is_unmeasured_not_zero_without_entry_price():
    """원장 이전 매도는 진입가를 모른다. 0 으로 메우면 '손익 0 으로 팔았다'가
    되고 그건 거짓이다(교훈57) - 안 세고, 몇 건으로 쟀는지를 같이 낸다."""
    rows = [
        _exec("2026-09-04", "021820", "SELL", 100, 1_100_000, order_no="OLD", avg=11_000.0),
        _exec("2026-09-04", "001080", "SELL", 10, 110_000, order_no="S2", avg=11_000.0),
    ]
    meta = {"S2": {"strategy": "pbr_value_v1", "entryPrice": 10_000.0}}
    out = feed._aggregate_trades(rows, order_meta=meta)
    ok("잰 것만 더한다", out["days"][0]["realizedKrw"] == 10_000, out["days"])
    ok("분모를 숨기지 않는다 (2건 중 1건)", out["days"][0]["realizedFrom"] == 1, out["days"])
    ok("매도금액은 둘 다 센다", out["days"][0]["sellKrw"] == 1_210_000, out["days"])


def test_realized_pnl_not_attached_to_buys():
    rows = [_exec("2026-09-04", "021820", "BUY", 100, 1_000_000, order_no="B1", avg=10_000.0)]
    meta = {"B1": {"strategy": "pbr_value_v1", "entryPrice": 9_000.0}}   # 매수엔 의미 없다
    out = feed._aggregate_trades(rows, order_meta=meta)
    ok("매수는 실현손익이 없다", out["days"][0]["realizedFrom"] == 0, out["days"])


def test_aggregate_trades_pending_carries_strategy():
    rows = [_exec("2026-09-11", "021820", "BUY", 0, 0, pending=10, order_no="P1")]
    out = feed._aggregate_trades(rows, today="2026-09-11", order_meta={"P1": {"strategy": "lowmom60_v1"}})
    ok("진행 중 주문도 전략을 단다", out["pending"][0]["strategy"] == "lowmom60_v1", out["pending"])
    out2 = feed._aggregate_trades(rows, today="2026-09-11")
    ok("원장 없으면 None - 지어내지 않는다", out2["pending"][0]["strategy"] is None, out2["pending"])


if __name__ == "__main__":
    for fn in (test_open_uses_strategy_book_not_account_quantity,
               test_mid_entry_uses_filled_quantity_not_target,
               test_fresh_pending_entry_holds_nothing,
               test_not_in_account_is_left_unmarked,
               test_falls_back_to_account_avg_when_book_has_no_entry_price,
               test_strategy_rows_sum_to_account_when_books_are_consistent,
               test_account_block_keeps_both_cash_figures,
               test_account_block_survives_missing_summary,
               test_equity_history_appends_one_row_per_day,
               test_equity_history_skips_when_value_unknown,
               test_aggregate_trades_sums_buy_and_sell_per_day,
               test_aggregate_trades_excludes_unfilled_from_amounts_but_lists_them_pending,
               test_aggregate_trades_pending_is_today_only,
               test_aggregate_trades_empty_is_empty_not_error,
               test_aggregate_trades_splits_by_strategy_via_order_ledger,
               test_aggregate_trades_unknown_order_is_unattributed_not_guessed,
               test_aggregate_trades_pending_carries_strategy,
               test_realized_pnl_from_ledger_entry_price,
               test_realized_pnl_is_unmeasured_not_zero_without_entry_price,
               test_realized_pnl_not_attached_to_buys):
        fn()
    print(f"test_build_ui_feed: {passed} passed, {failed} failed")
    sys.exit(1 if failed else 0)
