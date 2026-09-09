"""engine/live/kisVtsClient.py inquire_balance() 연속조회 self-check.
실제 KIS 네트워크는 호출하지 않는다 - requests.request를 가짜로 바꿔치기한다.

왜 있는가(2026-09-09 실측): KIS 잔고는 output1을 20종목까지만 주고 더 있으면
응답 헤더 tr_cont가 F/M이다. 옛 구현은 첫 페이지만 읽어 실제 101종목 중 20종목만
보고 있었고, 빠진 81종목은 "보유하지 않음"과 구분되지 않았다 - 그래서
ui/data/positions.json의 전략별 평가손익이 계좌의 29.6%만 반영했다.

이 테스트가 깨지는 방식: 연속조회를 빼면 rows=20(첫 페이지)만 나온다.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import engine.live.kisVtsClient as kis_vts  # noqa: E402

passed, failed = 0, 0


def ok(name, cond, detail=""):
    global passed, failed
    if cond:
        passed += 1
    else:
        failed += 1
        print(f"  FAIL  {name}  {detail}")


class _FakeResp:
    def __init__(self, body, headers):
        self.status_code = 200
        self._body = body
        self.headers = headers

    def json(self):
        return self._body


def _client():
    """네트워크·토큰 없이 인스턴스만 만든다(__init__은 env를 읽으므로 우회)."""
    c = kis_vts.KisVtsClient.__new__(kis_vts.KisVtsClient)
    c.cano, c.acnt_prdt_cd = "50000000", "01"
    c._headers = lambda tr_id: {"tr_id": tr_id}
    return c


def _install_pages(pages, bodies=None):
    """pages: [(output1, tr_cont)] 순서대로 돌려준다. 요청 params를 기록한다."""
    seen = []
    orig = kis_vts.requests.request
    orig_wait = kis_vts._RATE_LIMITER.wait
    kis_vts._RATE_LIMITER.wait = lambda: None

    def fake_request(method, url, **kw):
        i = len(seen)
        seen.append({"params": dict(kw.get("params") or {}), "headers": dict(kw.get("headers") or {})})
        if bodies and i < len(bodies):
            return _FakeResp(bodies[i], {"tr_cont": "F"})
        rows, cont = pages[min(i, len(pages) - 1)]
        return _FakeResp(
            {"rt_cd": "0", "output1": rows,
             "ctx_area_fk100": f"FK{i}", "ctx_area_nk100": f"NK{i}",
             "output2": [{"dnca_tot_amt": "1000", "tot_evlu_amt": "2000"}]},
            {"tr_cont": cont})

    kis_vts.requests.request = fake_request
    return seen, (lambda: (setattr(kis_vts.requests, "request", orig),
                           setattr(kis_vts._RATE_LIMITER, "wait", orig_wait)))


def _rows(n, start):
    return [{"pdno": f"{start + i:06d}", "hldg_qty": "10"} for i in range(n)]


def test_follows_tr_cont_until_done():
    pages = [(_rows(20, 100), "F"), (_rows(20, 200), "M"), (_rows(3, 300), "D")]
    seen, restore = _install_pages(pages)
    try:
        holdings, cash, total = _client().inquire_balance()
    finally:
        restore()
    ok("모든 페이지를 합친다 (20+20+3)", len(holdings) == 43, len(holdings))
    ok("첫 페이지에서 안 멈춘다", len(holdings) > 20, len(holdings))
    ok("요청 3번", len(seen) == 3, len(seen))
    ok("2번째 요청부터 tr_cont=N", seen[1]["headers"].get("tr_cont") == "N", seen[1]["headers"])
    ok("커서를 이어받는다", seen[1]["params"]["CTX_AREA_NK100"] == "NK0", seen[1]["params"])
    ok("첫 요청은 커서가 빈 값", seen[0]["params"]["CTX_AREA_NK100"] == "", seen[0]["params"])
    ok("summary는 그대로", (cash, total) == ("1000", "2000"), (cash, total))


def test_zero_quantity_rows_still_filtered():
    rows = _rows(2, 100) + [{"pdno": "999999", "hldg_qty": "0"}]
    _, restore = _install_pages([(rows, "D")])
    try:
        holdings, _, _ = _client().inquire_balance()
    finally:
        restore()
    ok("수량 0은 제외", [h["pdno"] for h in holdings] == ["000100", "000101"], holdings)


def test_single_page_does_not_paginate():
    seen, restore = _install_pages([(_rows(5, 100), "D")])
    try:
        holdings, _, _ = _client().inquire_balance()
    finally:
        restore()
    ok("한 페이지면 한 번만 부른다", len(seen) == 1, len(seen))
    ok("한 페이지 결과 그대로", len(holdings) == 5, len(holdings))


def test_page_cap_raises_instead_of_returning_partial():
    """커서가 안 끝나는데 상한에 걸리면 부분 잔고를 돌려주지 않는다 - 잘린
    잔고를 정상으로 읽으면 하류가 빠진 종목을 '판 종목'으로 해석한다."""
    orig_cap = kis_vts.MAX_BALANCE_PAGES
    kis_vts.MAX_BALANCE_PAGES = 3
    _, restore = _install_pages([(_rows(20, 100), "M")])  # 영원히 M
    try:
        _client().inquire_balance()
        ok("상한 초과는 예외", False, "예외가 안 났다")
    except kis_vts.KisVtsError as e:
        ok("상한 초과는 예외", "3페이지" in str(e), str(e))
    finally:
        restore()
        kis_vts.MAX_BALANCE_PAGES = orig_cap



def test_egw00201_is_retried_not_raised():
    """★ 2026-09-09. 유량 제한은 **계좌 단위**라 이 프로세스의 리미터로는 못
    막는다 - VM 의 10분 폴링과 Actions 의 UI 빌드가 같은 모의계좌를 동시에 친다.
    연속조회로 요청이 1회에서 6회로 늘면서 실제로 걸렸다(Actions 로그:
    "잔고 조회 실패(page 2): EGW00201"). 그 결과 계좌 정보 없이 UI 가 만들어져
    전략별 평가금액이 전부 0 으로 나갔다. EGW00201 은 재시도한다
    (CLAUDE.md 수집 VM 운영 기준 3 의 분류 그대로)."""
    throttled = {"rt_cd": "1", "msg_cd": "EGW00201", "msg1": "초당 거래건수를 초과하였습니다."}
    seen, restore = _install_pages([(_rows(3, 100), "D")], bodies=[throttled, throttled])
    orig_sleep = kis_vts.time.sleep
    kis_vts.time.sleep = lambda s: None          # 테스트를 느리게 만들지 않는다
    try:
        holdings, _, _ = _client().inquire_balance()
    finally:
        kis_vts.time.sleep = orig_sleep
        restore()
    ok("스로틀을 넘기고 결과를 낸다", len(holdings) == 3, len(holdings))
    ok("두 번 재시도했다", len(seen) == 3, len(seen))


def test_non_retryable_error_still_raises():
    """재시도 목록에 없는 오류는 그대로 올린다 - 전부 재시도하면 진짜 실패가
    3배 느리게 같은 실패를 낸다."""
    bad = {"rt_cd": "1", "msg_cd": "40910000", "msg1": "모의투자 주문이 불가한 계좌입니다."}
    seen, restore = _install_pages([(_rows(3, 100), "D")], bodies=[bad])
    try:
        _client().inquire_balance()
        ok("재시도 불가 오류는 예외", False, "예외가 안 났다")
    except kis_vts.KisVtsError as e:
        ok("재시도 불가 오류는 예외", "40910000" in str(e), str(e))
        ok("재시도하지 않았다", len(seen) == 1, len(seen))
    finally:
        restore()


if __name__ == "__main__":
    for fn in (test_follows_tr_cont_until_done, test_zero_quantity_rows_still_filtered,
               test_single_page_does_not_paginate, test_page_cap_raises_instead_of_returning_partial,
               test_egw00201_is_retried_not_raised, test_non_retryable_error_still_raises):
        fn()
    print(f"test_kis_vts_balance_paging: {passed} passed, {failed} failed")
    sys.exit(1 if failed else 0)
