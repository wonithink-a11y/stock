"""Portfolio.process_day 의 부분 청산 self-check.

process_day 는 원래부터 exits_today 로 (symbol, exit_fill, shares) 를 받았지만
shares 와 무관하게 포지션을 통째로 pop 했다. 부분 익절(분할매도)을 재려면
'일부만 팔고 나머지를 남기는' 경로가 필요하다 - 2026-09-04 추가.

가장 중요한 단정은 **전량 청산 경로가 안 바뀌었다**는 것이다(shares == 보유수량
이면 예전과 수치가 완전히 같아야 한다). 나머지 회귀 194건이 그걸 이미 보고 있고
여기서는 부분 경로 자체를 본다.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from engine.execution.contracts import Fill, Order
from engine.portfolio.portfolio import Portfolio, PortfolioConfig
from engine.signals.schema import RiskSpec


def _order_fill(symbol, price, cost_bps=15.0):
    order = Order(symbol, "2024-01-01", "2024-01-02", "LONG", RiskSpec(10.0, 3.0, 60))
    return order, Fill(order, "2024-01-02", price, "OPEN", cost_bps, 0.0)


def _open_one(price=10_000, capital=10_000_000, max_positions=1):
    cfg = PortfolioConfig(initial_capital=capital, max_positions=max_positions)
    pf = Portfolio(cfg)
    order, fill = _order_fill("000001", price)
    pf.process_day("2024-01-02", [], [(order, fill)])
    return pf, order


def test_partial_exit_keeps_remainder_open():
    pf, order = _open_one()
    held = pf.open_positions["000001"]["shares"]
    basis = pf.open_positions["000001"]["cost_basis"]
    sell = held // 2
    xf = Fill(order, "2024-02-01", 12_000, "TARGET", 15.0, 0.0)
    pf.process_day("2024-02-01", [("000001", xf, sell)], [])

    pos = pf.open_positions["000001"]
    assert pos["shares"] == held - sell, pos
    # 원가는 수량 비례로 안분된다
    assert abs(pos["cost_basis"] - basis * (held - sell) / held) < 1e-6, pos
    assert len(pf.closed_positions) == 1
    c = pf.closed_positions[0]
    assert c["partial"] is True and c["shares"] == sell, c
    assert c["pnl"] > 0, c                      # 10,000 -> 12,000 이면 이익이어야 한다


def test_partial_then_full_exit_sums_to_whole():
    """부분청산 후 나머지를 마저 팔면 수량·손익이 전량 한 번에 판 것과 맞아야 한다."""
    pf_a, order_a = _open_one()
    held = pf_a.open_positions["000001"]["shares"]
    xf1 = Fill(order_a, "2024-02-01", 12_000, "TARGET", 15.0, 0.0)
    pf_a.process_day("2024-02-01", [("000001", xf1, held // 2)], [])
    rest = pf_a.open_positions["000001"]["shares"]
    xf2 = Fill(order_a, "2024-03-01", 12_000, "TIME_EXIT", 15.0, 0.0)
    pf_a.process_day("2024-03-01", [("000001", xf2, rest)], [])
    assert "000001" not in pf_a.open_positions
    assert sum(c["shares"] for c in pf_a.closed_positions) == held
    split_pnl = sum(c["pnl"] for c in pf_a.closed_positions)

    # 같은 가격에 한 번에 판 경우
    pf_b, order_b = _open_one()
    xf = Fill(order_b, "2024-03-01", 12_000, "TIME_EXIT", 15.0, 0.0)
    pf_b.process_day("2024-03-01", [("000001", xf, held)], [])
    whole_pnl = pf_b.closed_positions[0]["pnl"]

    assert abs(split_pnl - whole_pnl) < 1e-6, (split_pnl, whole_pnl)
    assert abs(pf_a.cash - pf_b.cash) < 1e-6, (pf_a.cash, pf_b.cash)


def test_full_exit_path_marked_not_partial():
    pf, order = _open_one()
    held = pf.open_positions["000001"]["shares"]
    xf = Fill(order, "2024-02-01", 9_000, "STOP", 15.0, 0.0)
    pf.process_day("2024-02-01", [("000001", xf, held)], [])
    assert "000001" not in pf.open_positions
    c = pf.closed_positions[0]
    assert c["partial"] is False and c["shares"] == held, c
    assert c["pnl"] < 0, c                      # 10,000 -> 9,000 이면 손실


def test_partial_exit_frees_no_slot():
    """부분청산은 슬롯을 비우지 않는다 - 종목이 아직 열려 있기 때문이다."""
    cfg = PortfolioConfig(initial_capital=10_000_000, max_positions=1)
    pf = Portfolio(cfg)
    o1, f1 = _order_fill("000001", 10_000)
    pf.process_day("2024-01-02", [], [(o1, f1)])
    held = pf.open_positions["000001"]["shares"]
    xf = Fill(o1, "2024-02-01", 12_000, "TARGET", 15.0, 0.0)
    o2, f2 = _order_fill("000002", 10_000)
    pf.process_day("2024-02-01", [("000001", xf, held // 2)], [(o2, f2)])
    assert "000001" in pf.open_positions
    assert "000002" not in pf.open_positions, "슬롯이 1개인데 부분청산으로 새 종목이 들어왔다"


def main():
    for fn in (test_partial_exit_keeps_remainder_open,
               test_partial_then_full_exit_sums_to_whole,
               test_full_exit_path_marked_not_partial,
               test_partial_exit_frees_no_slot):
        fn()
        print("  ok  " + fn.__name__)
    print("portfolio partial exit self-check ok (4건)")


if __name__ == "__main__":
    main()
