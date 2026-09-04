"""Paper Trading Engine - Signal -> OrderIntent -> Broker -> position state.

두 가지 경로가 이 파일에 같이 산다:

  run_once(as_of)          로컬 시뮬레이션(PaperBroker, A2a 과거 EOD 데이터).
                            하루 한 번, 신호 스캔부터 체결까지 한 호출 안에서
                            끝난다(2026-08-21 1~2단계, 사용자 승인). 실전
                            연동과 무관 - run_paper_engine.py·
                            tests/test_paper_engine.py가 이 경로를 쓴다.

  scan_signals(as_of) +     실거래(KisVtsBroker) 경로. 신호 판단(scan_signals,
  poll_once()               하루 1회, EOD 데이터로 충분)과 체결 관리(poll_once,
                            장중 수 분 간격)를 분리한다 - 실제 주문은 "제출"과
                            "체결 확인"이 별개 호출이라 run_once()처럼 한
                            사이클에 못 담는다(2026-08-21 3단계, 사용자 승인
                            "B안으로 진행해줘"). poll_once의 enable_live_orders
                            플래그가 기본 False - 이게 유일한 자동주문
                            활성화 스위치다.

Lookahead discipline (mirrors engine/execution/executor.py):
  - ENTRY fills at the *next* trading session's open after a signal fires -
    never at the price the signal was computed from. run_once()은 이를 위해
    PENDING_ENTRY로 한 사이클 대기한다(build_order()의 next_session()과 동일
    원칙). poll_once()의 실거래 경로는 이 규칙이 자연히 성립한다 - 신호가
    난 날(scan_signals)과 체결이 실제로 나가는 시점(다음 거래일 poll_once)
    사이에 최소 하루 차이가 생긴다(신호는 그날 마감 후에나 계산되므로).
  - EXIT (stop/target/time)은 run_once()에서는 as_of의 확정 OHLC로,
    poll_once()에서는 그 순간의 실시간 시세로 판정한다 - 어느 쪽도
    lookahead가 아니다.

Duplicate-entry guard: run_once()·scan_signals() 둘 다 상태 dict에 이미
있는 심볼은 신호 스캔에서 건너뛴다. poll_once()는 상태값(PENDING_ENTRY/
ENTRY_SUBMITTED/OPEN/EXIT_SUBMITTED)마다 분기가 배타적이라, SUBMITTED
상태인 동안은 같은 심볼에 새 주문을 낼 경로 자체가 없다.
"""
from datetime import datetime, timezone, timedelta

import pandas as pd

from engine.data.a2aProvider import A2aProvider
from engine.data.calendar import TradingCalendar
from engine.live import positionStore
from engine.live.contracts import OrderIntent
from engine.live.paperBroker import PaperBroker

KST = timezone(timedelta(hours=9))


def run_once(repo_root, rule, as_of, log=print, bars_by_ticker=None, calendar=None):
    """rule: a strategy module exposing PARAMS, compute_features(bars),
    signal_fires(features, as_of). Returns the list of events this call
    produced (for the caller/tests to assert on - state is the source of
    truth, this return value is a convenience).

    bars_by_ticker: optional pre-loaded {symbol: DataFrame}, each row-indexed
    by date, going up to at least `as_of`. A real daily cron call omits this
    (loads exactly one day's worth of fresh data below); a multi-day smoke
    driver passes the same dict across many run_once() calls to avoid
    re-scanning A2a's gzip files once per simulated day. Passing more history
    than as_of is harmless - every lookup below is keyed to as_of only, so
    this cannot leak lookahead into the fill/exit decisions themselves."""
    params = rule.PARAMS
    strategy_id = params["strategyId"]
    universe = params["testUniverse"]
    risk = params["risk"]
    position_cfg = params["position"]

    if calendar is None:
        calendar = TradingCalendar(repo_root=repo_root)
    broker = PaperBroker()
    if bars_by_ticker is None:
        a2a = A2aProvider(repo_root=repo_root, use_cache=True)
        bars_by_ticker = a2a.load(set(universe), calendar.days[0], as_of, universe_hash="paper-skeleton-v0")

    state = positionStore.load(repo_root, strategy_id)
    events = []
    as_of_ts = pd.Timestamp(as_of)

    def _bar(symbol):
        bars = bars_by_ticker.get(symbol)
        if bars is None or as_of_ts not in bars.index:
            return None
        return bars.loc[as_of_ts]

    # 1) PENDING_ENTRY -> fill at as_of's open, only on the expected next session
    for symbol, pos in list(state.items()):
        if pos["status"] != "PENDING_ENTRY":
            continue
        if calendar.next_session(pos["intent_date"]) != as_of:
            continue  # not yet due (or as_of skipped ahead - stays PENDING, no silent fill)
        row = _bar(symbol)
        if row is None:
            continue
        intent = OrderIntent(symbol=symbol, side="BUY", quantity=pos["quantity"],
                              reason="ENTRY_SIGNAL", intent_date=pos["intent_date"], strategy_id=strategy_id)
        fill = broker.fill_entry(intent, row)
        stop_price = round(fill.fill_price * (1 - risk["stopPct"]), 2)
        target_price = round(fill.fill_price * (1 + risk["targetPct"]), 2)
        state[symbol] = {
            "status": "OPEN", "quantity": pos["quantity"], "entry_price": fill.fill_price,
            "entry_date": as_of, "stop_price": stop_price, "target_price": target_price,
            "max_holding_sessions": risk["maxHoldingSessions"], "sessions_held": 0,
        }
        events.append({"type": "FILL_ENTRY", "symbol": symbol, "price": fill.fill_price, "date": as_of})
        log(f"[{as_of}] ENTRY FILLED  {symbol}  qty={pos['quantity']}  price={fill.fill_price}")

    # 2) OPEN -> check exit against as_of's finalized OHLC
    for symbol, pos in list(state.items()):
        if pos["status"] != "OPEN":
            continue
        row = _bar(symbol)
        if row is None:
            continue
        pos["sessions_held"] += 1
        intent = OrderIntent(symbol=symbol, side="SELL", quantity=pos["quantity"], reason="EXIT_CHECK",
                              intent_date=as_of, strategy_id=strategy_id,
                              stop_price=pos["stop_price"], target_price=pos["target_price"])
        fill = broker.check_exit(intent, row, pos["stop_price"], pos["target_price"])
        if fill is None and pos["sessions_held"] >= pos["max_holding_sessions"]:
            fill = broker.fill_time_exit(intent, row)
        if fill is not None:
            pnl = round((fill.fill_price - pos["entry_price"]) * pos["quantity"], 2)
            events.append({"type": f"FILL_EXIT_{fill.fill_type}", "symbol": symbol,
                            "price": fill.fill_price, "date": as_of, "pnl": pnl})
            log(f"[{as_of}] EXIT FILLED  {symbol}  {fill.fill_type}  price={fill.fill_price}  pnl={pnl}")
            del state[symbol]
        else:
            state[symbol] = pos  # sessions_held 갱신만 반영

    # 3) flat symbols -> scan for a fresh entry signal
    open_or_pending = len(state)
    for symbol in universe:
        if symbol in state:
            continue
        if open_or_pending >= position_cfg["maxPositions"]:
            continue
        bars = bars_by_ticker.get(symbol)
        if bars is None:
            continue
        features = rule.compute_features(bars)
        if not rule.signal_fires(features, as_of):
            continue
        entry_price_hint = float(features.loc[as_of_ts, "close"])
        quantity = max(1, int(position_cfg["notionalPerPosition"] // entry_price_hint))
        state[symbol] = {"status": "PENDING_ENTRY", "quantity": quantity, "intent_date": as_of}
        open_or_pending += 1
        events.append({"type": "INTENT_ENTRY", "symbol": symbol, "date": as_of, "quantity": quantity})
        log(f"[{as_of}] SIGNAL -> INTENT  {symbol}  qty={quantity} (fills next session)")

    positionStore.save(repo_root, strategy_id, state)
    return events


def scan_signals(repo_root, rule, as_of, log=print, bars_by_ticker=None):
    """run_once()의 '3) 신규 진입 신호 스캔' 단계와 판단 로직은 동일하지만
    별개 함수다(호출은 공유하지 않는다) - run_once()는 세 단계가 메모리
    안의 같은 state를 이어 쓰다가 끝에 한 번만 저장하는데, 이 함수가 내부에서
    다시 positionStore.load()를 하면 그 사이 상태(체결·청산)가 아직
    저장 전이라 덮어써질 위험이 있다. 그래서 run_once()의 코드를 그대로
    복제해 뒀다 - 신호 로직을 고치면 두 곳 다 고쳐야 한다(현재는 이
    한계를 감수, 리팩터링은 별도 판단).

    실거래(poll_once) 경로에서는 이 함수가 유일한 진입점이라 이 문제가
    없다 - 하루 1회, 단독으로 load/save한다. PENDING_ENTRY를 만들 뿐
    어떤 주문도 내지 않는다."""
    params = rule.PARAMS
    strategy_id = params["strategyId"]
    universe = params["testUniverse"]
    position_cfg = params["position"]

    calendar = TradingCalendar(repo_root=repo_root)
    if bars_by_ticker is None:
        a2a = A2aProvider(repo_root=repo_root, use_cache=True)
        bars_by_ticker = a2a.load(set(universe), calendar.days[0], as_of, universe_hash="paper-skeleton-v0")

    state = positionStore.load(repo_root, strategy_id)
    events = []
    as_of_ts = pd.Timestamp(as_of)
    open_or_pending = len(state)

    for symbol in universe:
        if symbol in state:
            continue
        if open_or_pending >= position_cfg["maxPositions"]:
            continue
        bars = bars_by_ticker.get(symbol)
        if bars is None:
            continue
        features = rule.compute_features(bars)
        if not rule.signal_fires(features, as_of):
            continue
        entry_price_hint = float(features.loc[as_of_ts, "close"])
        quantity = max(1, int(position_cfg["notionalPerPosition"] // entry_price_hint))
        state[symbol] = {"status": "PENDING_ENTRY", "quantity": quantity, "intent_date": as_of}
        open_or_pending += 1
        events.append({"type": "INTENT_ENTRY", "symbol": symbol, "date": as_of, "quantity": quantity})
        log(f"[{as_of}] SIGNAL -> INTENT  {symbol}  qty={quantity} (실주문은 poll_once가 낸다)")

    positionStore.save(repo_root, strategy_id, state)
    return events


def scan_rebalance_signals(repo_root, rule, as_of, capital_krw, log=print, bars_by_ticker=None,
                            entry_slices=1):
    """scan_signals()의 월별 교체매매(pbr_value_v1·lowmom60_v1) 버전 - 종목별
    predicate(rule.signal_fires) 대신 rule.selected_symbols(as_of)로 이번
    리밸런싱일의 전체 선택 목록을 한 번에 받는다(횡단면 랭킹이 이미
    selection.json에 구워져 있어 종목 단위 루프가 필요 없다).

    이미 보유중(OPEN/PENDING_ENTRY/ENTRY_SUBMITTED)인 종목은 건너뛴다 -
    재선택된 종목을 다시 사지 않는다. poll_once(is_still_selected=...)가
    그 종목을 계속 들고 간다(continuousHoldOnRenewal 효과, 별도 병합
    로직 없음).

    entry_slices: 목표수량을 며칠에 나눠 살지(기본 1 = 하루에 전량, 기존 동작).
    시장충격은 하루 참여율의 함수라 큰 자금에서는 이걸 늘린다 - 실측은
    findings/sizing-position-count-capacity-2026-09.md 정정 절.

    capital_krw: 이 전략에 배정된 가상자금 총액(같은 KIS 모의투자 계좌를
    strategy_id별로 나눠 쓴다, positionStore가 이미 strategy_id별 분리
    파일이라 장부도 자연히 분리됨). 슬롯예산 = capital_krw // maxPositions.
    ponytail: 슬롯예산보다 비싼 종목은 스킵한다(1주 강제매수로 예산을
    넘기지 않음) - 균등가중을 정확히 지키려면 잔여 슬롯 수에 따라 예산을
    동적으로 재분배해야 하지만, 파일럿 규모(가상자금 수백만원, top-30)에서는
    이 단순 버전으로 충분하다."""
    params = rule.PARAMS
    strategy_id = params["strategyId"]
    max_positions = params["portfolio"]["maxPositions"]
    budget_per_slot = capital_krw // max_positions

    calendar = TradingCalendar(repo_root=repo_root)
    target = rule.selected_symbols(as_of)

    if bars_by_ticker is None:
        a2a = A2aProvider(repo_root=repo_root, use_cache=True)
        bars_by_ticker = a2a.load(set(target), calendar.days[0], as_of,
                                   universe_hash=f"{strategy_id}-rebalance-scan")

    state = positionStore.load(repo_root, strategy_id)
    events = []
    as_of_ts = pd.Timestamp(as_of)
    open_or_pending = len(state)

    for symbol in target:
        if symbol in state:
            continue
        if open_or_pending >= max_positions:
            continue
        bars = bars_by_ticker.get(symbol)
        if bars is None or as_of_ts not in bars.index:
            log(f"[{as_of}] SKIP {symbol} - 가격 데이터 없음")
            continue
        price = float(bars.loc[as_of_ts, "close"])
        quantity = int(budget_per_slot // price)
        if quantity < 1:
            log(f"[{as_of}] SKIP {symbol} - 슬롯예산({budget_per_slot:,.0f}) < 가격({price:,.0f})")
            continue
        state[symbol] = {"status": "PENDING_ENTRY", "quantity": quantity,
                          "target_quantity": quantity,
                          "entry_slices": max(int(entry_slices), 1),
                          "intent_date": as_of}
        open_or_pending += 1
        events.append({"type": "INTENT_ENTRY", "symbol": symbol, "date": as_of, "quantity": quantity})
        log(f"[{as_of}] SIGNAL -> INTENT  {symbol}  qty={quantity} (실주문은 poll_once가 낸다)")

    positionStore.save(repo_root, strategy_id, state)
    return events


def _open_from_fills(pos, today, risk):
    """분할 체결 누적(filled_quantity/entry_cost)을 OPEN 포지션으로 확정한다.
    entry_price 는 조각들의 가중평균 단가 - stop/target 은 그 위에서 계산한다."""
    filled = pos.get("filled_quantity", 0)
    entry_price = round(pos.get("entry_cost", 0.0) / filled, 4) if filled else 0.0
    return {"status": "OPEN", "quantity": filled, "entry_price": entry_price,
            "entry_date": pos.get("first_fill_date", today),
            "stop_price": round(entry_price * (1 - risk["stopPct"]), 2),
            "target_price": round(entry_price * (1 + risk["targetPct"]), 2),
            "max_holding_sessions": risk["maxHoldingSessions"], "sessions_held": 0,
            "lastCountedDate": None}


def poll_once(repo_root, rule, broker, log=print, enable_live_orders=False, now=None,
              is_still_selected=None):
    """장중에 여러 번(수 분 간격) 불리는 것을 전제로 한 실거래 폴링.
    broker: KisVtsBroker와 같은 인터페이스(submit_buy/submit_sell/check_fill/
    current_price) - 테스트에서는 합성 FakeBroker를 넣는다.

    enable_live_orders=False(기본값)면 아무 것도 안 하고 즉시 반환한다 -
    이게 유일한 활성화 스위치다. 이 함수를 부르는 스케줄러/크론이 있어도
    이 값이 True로 바뀌기 전까지는 broker를 단 한 번도 호출하지 않는다.

    is_still_selected(symbol) -> bool, optional: pbr_value_v1·lowmom60_v1처럼
    가격 기반 stop/target이 없는(도달 불가능하게 막아둔) 월별 교체매매
    전략용. OPEN 포지션이 "이번 리밸런싱에도 여전히 선택됐는가"를 stop/
    target/time보다 먼저 확인한다 - False면 즉시 REBALANCE_EXIT, True면
    아무 것도 안 하고 계속 보유(continuousHoldOnRenewal과 동일 효과를
    별도 병합 로직 없이 얻는다 - "다시 선택됨"이 곧 "그대로 둠"이므로).
    None(기본값)이면 이 분기를 완전히 건너뛰어 기존 stop/target/time 전략
    (dummy_sma20 등)의 동작은 전혀 안 바뀐다.

    상태기계 (positionStore, 심볼당 하나):
        PENDING_ENTRY    -> submit_buy 시도 -> ENTRY_SUBMITTED
        ENTRY_SUBMITTED  -> check_fill: 체결확인 -> OPEN
                                         거부     -> PENDING_ENTRY(재시도)
                                         대기중   -> 그대로(중복 제출 없음)
        OPEN             -> (is_still_selected가 있으면 그 판정 우선,
                             없거나 True면) stop/target/time 판정
                             -> submit_sell -> EXIT_SUBMITTED
        EXIT_SUBMITTED   -> check_fill: 체결확인 -> 상태 삭제(포지션 종료)
                                         거부     -> OPEN(재시도)
                                         대기중   -> 그대로(중복 제출 없음)

    각 분기는 상태값으로 완전히 배타적이라, 같은 poll_once() 호출 안에서도
    한 심볼에 두 번 주문이 나갈 수 없다 - '이미 SUBMITTED인 걸 다시 사려는'
    경로 자체가 없다.
    """
    if not enable_live_orders:
        log("[비활성] enable_live_orders=False - poll_once가 아무 것도 하지 않음")
        return []

    params = rule.PARAMS
    strategy_id = params["strategyId"]
    risk = params["risk"]
    now = now or datetime.now(KST)
    today = now.strftime("%Y-%m-%d")
    today_compact = now.strftime("%Y%m%d")

    state = positionStore.load(repo_root, strategy_id)
    events = []

    for symbol, pos in list(state.items()):
        status = pos["status"]

        if status == "PENDING_ENTRY":
            # 분할 매수: 목표수량을 entry_slices 일에 나눠 산다(기본 1 = 기존 동작).
            # 시장충격은 '하루' 참여율의 함수라 며칠에 나누면 그만큼 내려간다
            # (findings/sizing-position-count-capacity-2026-09.md 정정 절 참고).
            target = pos.get("target_quantity", pos["quantity"])
            filled = pos.get("filled_quantity", 0)
            remaining = target - filled
            if remaining < 1:                       # 이미 다 샀다(방어적)
                state[symbol] = _open_from_fills(pos, today, risk)
                continue
            if pos.get("last_slice_date") == today:  # 하루 한 조각만 - 폴링은 10분마다다
                continue
            slices = max(int(pos.get("entry_slices", 1)), 1)
            qty = min(remaining, -(-target // slices))   # ceil(target/slices)
            try:
                order_no = broker.submit_buy(symbol, qty)
            except Exception as e:  # KisVtsError 등 - 브로커 예외 타입에 결합하지 않는다
                log(f"[{today}] 매수 제출 실패 {symbol}: {e}")
                continue
            state[symbol] = {**pos, "status": "ENTRY_SUBMITTED", "order_quantity": qty,
                              "order_no": order_no, "order_date": today_compact,
                              "last_slice_date": today}
            events.append({"type": "ENTRY_SUBMITTED", "symbol": symbol,
                            "orderNo": order_no, "quantity": qty})
            log(f"[{today}] 매수 제출  {symbol}  {qty}주"
                + (f" ({filled + qty}/{target})" if slices > 1 else "")
                + f"  주문번호={order_no}")
            continue

        if status == "ENTRY_SUBMITTED":
            order_qty = pos.get("order_quantity", pos["quantity"])
            try:
                r = broker.check_fill(pos["order_no"], pos["order_date"], order_qty)
            except Exception as e:
                log(f"[{today}] 체결조회 실패(매수) {symbol}: {e}")
                continue
            if r["rejected"]:
                # 거부는 체결이 아니다 - last_slice_date 를 지워 같은 날 재시도한다
                state[symbol] = {k: v for k, v in pos.items()
                                  if k not in ("order_no", "order_date", "order_quantity",
                                               "last_slice_date")}
                state[symbol]["status"] = "PENDING_ENTRY"
                events.append({"type": "ENTRY_REJECTED", "symbol": symbol})
                log(f"[{today}] 매수 거부됨  {symbol}  - 다음 poll에서 재시도")
                continue
            if r["fullyFilled"]:
                filled = pos.get("filled_quantity", 0) + r["filledQty"]
                cost = pos.get("entry_cost", 0.0) + r["filledQty"] * r["avgPrice"]
                target = pos.get("target_quantity", pos["quantity"])
                nxt = {**pos, "filled_quantity": filled, "entry_cost": cost}
                # 보유일수는 첫 조각이 체결된 날부터 센다(마지막 조각 날이 아니다)
                nxt.setdefault("first_fill_date", today)
                for k in ("order_no", "order_date", "order_quantity"):
                    nxt.pop(k, None)
                events.append({"type": "FILL_ENTRY", "symbol": symbol,
                                "price": r["avgPrice"], "qty": r["filledQty"]})
                if filled >= target:
                    state[symbol] = _open_from_fills(nxt, today, risk)
                    log(f"[{today}] 매수 체결 완료  {symbol}  qty={filled}  "
                        f"평균단가={state[symbol]['entry_price']}")
                else:
                    nxt["status"] = "PENDING_ENTRY"       # 남은 조각은 다음 거래일에
                    state[symbol] = nxt
                    log(f"[{today}] 매수 체결(부분) {symbol}  {filled}/{target}주 "
                        f"- 남은 조각은 다음 거래일")
            # else: 아직 대기중 - 그대로 둔다(중복 제출 없음)
            continue

        if status == "OPEN":
            if pos.get("lastCountedDate") != today:
                pos["sessions_held"] = pos.get("sessions_held", 0) + 1
                pos["lastCountedDate"] = today
                state[symbol] = pos

            reason = None
            if is_still_selected is not None and not is_still_selected(symbol):
                reason = "REBALANCE_EXIT"

            if reason is None:
                try:
                    price = broker.current_price(symbol)
                except Exception as e:
                    log(f"[{today}] 시세 조회 실패 {symbol}: {e}")
                    continue
                if price <= pos["stop_price"]:
                    reason = "STOP"
                elif price >= pos["target_price"]:
                    reason = "TARGET"
                elif pos["sessions_held"] >= pos["max_holding_sessions"]:
                    reason = "TIME_EXIT"
            if reason is None:
                continue

            try:
                order_no = broker.submit_sell(symbol, pos["quantity"])
            except Exception as e:
                log(f"[{today}] 매도 제출 실패 {symbol}: {e}")
                continue
            state[symbol] = {**pos, "status": "EXIT_SUBMITTED", "order_no": order_no,
                              "order_date": today_compact, "exitReason": reason}
            events.append({"type": "EXIT_SUBMITTED", "symbol": symbol, "reason": reason, "orderNo": order_no})
            log(f"[{today}] 매도 제출  {symbol}  사유={reason}  주문번호={order_no}")
            continue

        if status == "EXIT_SUBMITTED":
            try:
                r = broker.check_fill(pos["order_no"], pos["order_date"], pos["quantity"])
            except Exception as e:
                log(f"[{today}] 체결조회 실패(매도) {symbol}: {e}")
                continue
            if r["rejected"]:
                reverted = {k: v for k, v in pos.items()
                            if k not in ("order_no", "order_date", "exitReason")}
                reverted["status"] = "OPEN"
                state[symbol] = reverted
                events.append({"type": "EXIT_REJECTED", "symbol": symbol})
                log(f"[{today}] 매도 거부됨  {symbol}  - OPEN으로 복귀, 다음 poll에서 재시도")
                continue
            if r["fullyFilled"]:
                exit_price = r["avgPrice"]
                pnl = round((exit_price - pos["entry_price"]) * r["filledQty"], 2)
                events.append({"type": f"FILL_EXIT_{pos['exitReason']}", "symbol": symbol,
                                "price": exit_price, "pnl": pnl})
                log(f"[{today}] 매도 체결 확인  {symbol}  price={exit_price}  pnl={pnl}")
                del state[symbol]
            # else: 아직 대기중 - 그대로 둔다(중복 제출 없음)
            continue

    positionStore.save(repo_root, strategy_id, state)
    return events
