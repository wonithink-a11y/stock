"""engine/live/kisVtsClient.py의 레이트리미터 self-check. 실제 KIS 네트워크는
호출하지 않는다 - requests.request를 가짜로 바꿔치기한다.

검증 대상(2026-08-21 사용자 확인 - 모의투자 REST 1건/초, 계좌 단위):
  1  실제 모든 REST 호출(토큰·주문·잔고·시세·체결조회 5곳)이 리미터를 거치는가
  2  동시(멀티스레드) 호출도 리미터가 직렬화하는가 - 공유 여부
  3  기존 테스트가 안 깨지는가 (별도로 pytest 전체 재실행)
  4  enable_live_orders=False 상태에서 KIS 호출이 전혀 없는가
     (poll_once의 disabled 분기 자체가 broker를 안 건드리므로 이 파일이
     아니라 tests/test_paper_engine_poll.py::test_disabled_flag_never_touches_broker
     가 이미 담당 - 여기서는 그 사실만 재확인한다)
"""
import os
import sys
import threading
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import engine.live.kisVtsClient as kis_vts  # noqa: E402
from engine.live.kisVtsClient import _RateLimiter  # noqa: E402

passed, failed = 0, 0


def ok(name, cond, detail=""):
    global passed, failed
    if cond:
        passed += 1
    else:
        failed += 1
        print(f"  FAIL  {name}  {detail}")


def test_rate_limiter_serializes_single_thread_calls():
    lim = _RateLimiter(min_interval_sec=0.2)
    t0 = time.monotonic()
    lim.wait()
    lim.wait()
    lim.wait()
    elapsed = time.monotonic() - t0
    # 3번 호출 -> 최소 2번의 간격(0.4초) 이상 걸려야 한다
    ok("3 calls take >= 2 intervals", elapsed >= 0.4 - 0.02, elapsed)


def test_rate_limiter_shared_across_threads():
    """같은 limiter 인스턴스를 여러 스레드가 동시에 두드려도 직렬화된다 -
    '동시에 여러 호출이 들어와도 limiter가 공유되는지'에 대한 답."""
    lim = _RateLimiter(min_interval_sec=0.15)
    n = 5
    call_times = []
    call_lock = threading.Lock()

    def worker():
        lim.wait()
        with call_lock:
            call_times.append(time.monotonic())

    threads = [threading.Thread(target=worker) for _ in range(n)]
    t0 = time.monotonic()
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    total = time.monotonic() - t0

    ok(f"{n} concurrent calls still take >= {n-1} intervals (serialized, not parallel)",
       total >= (n - 1) * 0.15 - 0.03, total)
    call_times.sort()
    gaps = [b - a for a, b in zip(call_times, call_times[1:])]
    ok("every consecutive gap respects min_interval",
       all(g >= 0.15 - 0.03 for g in gaps), gaps)


def test_all_five_rest_methods_route_through_shared_limiter():
    """토큰·주문·잔고·시세·체결조회 - 5개 REST 메서드 전부 _request()(따라서
    _RATE_LIMITER.wait())를 거치는지 구조적으로 확인한다. requests.request를
    가짜로 바꿔 네트워크는 안 나간다."""
    calls = {"wait": 0, "request": 0}
    orig_wait = kis_vts._RATE_LIMITER.wait
    orig_request_fn = kis_vts.requests.request
    orig_token_cache = kis_vts.TOKEN_CACHE
    # 실제 .token_cache_kis_vts.json(진짜 KIS 토큰이 들어있을 수 있는 파일)을
    # 이 테스트가 절대 안 건드리게 임시 경로로 바꿔치기한다 - 첫 구현이 이걸
    # 안 해서 가짜 토큰("FAKE")을 실제 캐시 파일에 덮어쓴 적이 있다(2026-08-21
    # 실측 - 재실행할 때마다 캐시 히트로 토큰 호출이 스킵돼 4/5만 나왔다).
    import os as _os
    import tempfile
    _fd, _tmp_path = tempfile.mkstemp(suffix=".json")
    _os.close(_fd)  # Windows에서는 fd를 안 닫으면 바로 아래 unlink()가 PermissionError
    fake_cache_path = kis_vts.Path(_tmp_path)
    fake_cache_path.unlink()  # mkstemp가 만든 빈 파일은 지운다 - exists()가 False여야 캐시 미스로 시작
    kis_vts.TOKEN_CACHE = fake_cache_path

    def spy_wait():
        calls["wait"] += 1
        # 테스트를 느리게 만들지 않게 실제 sleep은 건너뛴다 - 호출 여부만 본다
        pass

    class _FakeResp:
        status_code = 200

        def json(self):
            return {
                "access_token": "FAKE", "access_token_token_expired": "2099-01-01 00:00:00",
                "rt_cd": "0", "output": {"ODNO": "FAKEORD", "stck_prpr": "70000"},
                "output1": [{"odno": "FAKEORD", "tot_ccld_qty": "1", "rmn_qty": "0",
                             "rjct_qty": "0", "avg_prvs": "70000"}],
                "output2": [{"dnca_tot_amt": "1000", "tot_evlu_amt": "1000"}],
            }

    def fake_request(method, url, **kwargs):
        calls["request"] += 1
        return _FakeResp()

    kis_vts._RATE_LIMITER.wait = spy_wait
    kis_vts.requests.request = fake_request
    try:
        client = kis_vts.KisVtsClient.__new__(kis_vts.KisVtsClient)
        client.key, client.secret = "FAKEKEY", "FAKESECRET"
        client.cano, client.acnt_prdt_cd = "12345678", "01"
        client._token = None

        client._get_token()
        client.order_cash("BUY", "005930", 1)
        client.inquire_balance()
        client.get_current_price("005930")
        client.get_order_status("FAKEORD", "20260821", 1)
    finally:
        kis_vts._RATE_LIMITER.wait = orig_wait
        kis_vts.requests.request = orig_request_fn
        if fake_cache_path.exists():
            fake_cache_path.unlink()
        kis_vts.TOKEN_CACHE = orig_token_cache

    ok("5 REST calls made", calls["request"] == 5, calls["request"])
    ok("limiter.wait() called exactly once per REST call (1:1, no gaps)",
       calls["wait"] == calls["request"], calls)


def test_disabled_engine_never_reaches_kis_client():
    """poll_once(enable_live_orders=False)가 broker(=KisVtsBroker/KisVtsClient
    경로)를 한 번도 안 건드리는지 - '독약' 브로커로 확인한다. 어떤 메서드든
    호출되면 즉시 예외를 던지므로, 예외가 없으면 진짜 아무 것도 안 건드린 것.
    """
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)) + "/..")
    from engine.live.paperEngine import poll_once

    class PoisonBroker:
        def __getattr__(self, name):
            def _boom(*a, **k):
                raise AssertionError(f"broker.{name}() called while enable_live_orders=False")
            return _boom

    class FakeRule:
        PARAMS = {"strategyId": "test_poison_broker_synth", "testUniverse": ["TEST1"],
                  "risk": {"stopPct": 0.05, "targetPct": 0.10, "maxHoldingSessions": 3},
                  "position": {"notionalPerPosition": 1000000, "maxPositions": 1}}

    from engine.live import positionStore
    repo_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
    positionStore.save(repo_root, "test_poison_broker_synth",
                        {"TEST1": {"status": "PENDING_ENTRY", "quantity": 1, "intent_date": "2026-08-20"}})
    try:
        events = poll_once(repo_root, FakeRule(), PoisonBroker(), log=lambda *a: None,
                            enable_live_orders=False)
        ok("no exception raised (broker untouched)", events == [], events)
    except AssertionError as e:
        ok("no exception raised (broker untouched)", False, str(e))
    finally:
        positionStore.save(repo_root, "test_poison_broker_synth", {})


def main():
    test_rate_limiter_serializes_single_thread_calls()
    test_rate_limiter_shared_across_threads()
    test_all_five_rest_methods_route_through_shared_limiter()
    test_disabled_engine_never_reaches_kis_client()
    print(f"\n{'='*40}\npassed {passed} · failed {failed}")
    if failed:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
