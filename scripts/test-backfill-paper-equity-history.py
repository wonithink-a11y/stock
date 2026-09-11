"""backfill-paper-equity-history.py 의 reconstruct() self-check. 네트워크 없음.

왜 있는가: 이 함수가 틀리면 벤치마크 비교 차트가 **그럴듯한 거짓 곡선**을 그린다.
계좌 곡선은 대조할 데가 화면밖에 없어서(원본이 이미 사라진 과거다) 눈으로는 못 잡는다.

깨지는 방식: K 를 오늘로 역산하지 않고 추정하면 곡선 전체가 평행이동하고,
매도 부호를 뒤집으면 판 날 이후가 통째로 어긋난다.
"""
import importlib.util
import os
import sys

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_spec = importlib.util.spec_from_file_location(
    "bf", os.path.join(REPO, "scripts", "backfill-paper-equity-history.py"))
bf = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(bf)

passed = failed = 0


def ok(name, cond, detail=""):
    global passed, failed
    if cond:
        passed += 1
    else:
        failed += 1
        print(f"  FAIL  {name}  {detail}")


def _fill(date, symbol, side, qty, amount):
    return {"date": date, "symbol": symbol, "side": side,
            "filledQty": qty, "amountKrw": amount}


def test_buy_only_curve_is_cash_plus_marked_stock():
    """전액 현금에서 시작해 이틀에 걸쳐 산다. 산 날 총평가는 현금이 주식으로
    바뀐 것뿐이라 **가격이 안 변하면 총평가도 안 변해야** 한다 - 매수 자체가
    수익을 만들면 안 된다(가장 흔한 부호 실수)."""
    fills = [_fill("2026-09-04", "A", "BUY", 100, 1_000_000),
             _fill("2026-09-07", "B", "BUY", 50, 500_000)]
    closes = {"A": {"2026-09-04": 10_000.0, "2026-09-07": 10_000.0, "2026-09-08": 10_000.0},
              "B": {"2026-09-04": 10_000.0, "2026-09-07": 10_000.0, "2026-09-08": 10_000.0}}
    rows, k = bf.reconstruct(fills, closes, anchor_total=5_000_000)
    ok("날짜 3개", [r["date"] for r in rows] == ["2026-09-04", "2026-09-07", "2026-09-08"], rows)
    ok("가격 불변이면 총평가 불변",
       {r["totalKrw"] for r in rows} == {5_000_000}, rows)
    ok("K = 초기 예수금", k == 5_000_000, k)
    ok("주식평가가 매수와 함께 는다",
       [r["stockKrw"] for r in rows] == [1_000_000, 1_500_000, 1_500_000], rows)
    ok("현금은 그만큼 준다",
       [r["cashKrw"] for r in rows] == [4_000_000, 3_500_000, 3_500_000], rows)


def test_price_move_shows_up_as_pnl():
    fills = [_fill("2026-09-04", "A", "BUY", 100, 1_000_000)]
    closes = {"A": {"2026-09-04": 10_000.0, "2026-09-07": 11_000.0}}
    rows, _ = bf.reconstruct(fills, closes, anchor_total=5_100_000)
    ok("오늘 총평가가 앵커와 같다", rows[-1]["totalKrw"] == 5_100_000, rows)
    ok("전날은 10% 오르기 전 값", rows[0]["totalKrw"] == 5_000_000, rows)


def test_sell_reduces_holdings_and_returns_cash():
    fills = [_fill("2026-09-04", "A", "BUY", 100, 1_000_000),
             _fill("2026-09-07", "A", "SELL", 100, 1_200_000)]
    closes = {"A": {"2026-09-04": 10_000.0, "2026-09-07": 12_000.0, "2026-09-08": 9_000.0}}
    rows, _ = bf.reconstruct(fills, closes, anchor_total=5_200_000)
    ok("판 뒤 주식평가 0", rows[-1]["stockKrw"] == 0, rows)
    ok("판 뒤 가격이 떨어져도 총평가 불변",
       rows[1]["totalKrw"] == rows[2]["totalKrw"] == 5_200_000, rows)


def test_missing_close_is_skipped_not_zeroed():
    """그날 종가가 없는 종목(거래정지 등)을 0 으로 세면 계좌가 폭락한 것처럼
    보인다(교훈57). 빼고 세고, 몇 개를 못 봤는지 남긴다."""
    fills = [_fill("2026-09-04", "A", "BUY", 100, 1_000_000),
             _fill("2026-09-04", "B", "BUY", 100, 1_000_000)]
    closes = {"A": {"2026-09-04": 10_000.0, "2026-09-07": 10_000.0},
              "B": {"2026-09-04": 10_000.0}}          # 09-07 종가 없음
    rows, _ = bf.reconstruct(fills, closes, anchor_total=5_000_000)
    ok("빠진 종목은 0 으로 안 센다", rows[-1]["stockKrw"] == 1_000_000, rows)


def test_merge_keeps_measured_rows_over_reconstructed():
    existing = [{"date": "2026-09-11", "totalKrw": 999}]
    rows = [{"date": "2026-09-10", "totalKrw": 1}, {"date": "2026-09-11", "totalKrw": 2}]
    merged = bf._merge(existing, rows)
    ok("이미 적힌 날은 안 덮는다", [r["totalKrw"] for r in merged] == [1, 999], merged)


def test_empty_is_empty():
    rows, k = bf.reconstruct([], {}, anchor_total=1)
    ok("체결이 없으면 빈 결과", rows == [] and k is None, (rows, k))


def run_all():
    for fn in (test_buy_only_curve_is_cash_plus_marked_stock,
               test_price_move_shows_up_as_pnl,
               test_sell_reduces_holdings_and_returns_cash,
               test_missing_close_is_skipped_not_zeroed,
               test_merge_keeps_measured_rows_over_reconstructed,
               test_empty_is_empty):
        fn()
    print(f"test-backfill-paper-equity-history: {passed} passed, {failed} failed")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(run_all())
