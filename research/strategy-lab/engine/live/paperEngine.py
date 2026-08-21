"""Paper Trading Engine skeleton - orchestrates Signal -> OrderIntent ->
PaperBroker -> position state, once per call to run_once(as_of).

Scope (docs/control/리스크계약-스톱타이밍-결정브리프.md 관련 논의, 2026-08-21
사용자 승인 1~2단계): plumbing only. No KIS connection - PaperBroker fills
against A2a historical/EOD bars. Assumes run_once(as_of) is called after the
as_of session has fully closed (no live intraday feed exists yet); a future
step wires this to a same-day intraday source and this assumption is revisited
then, not before.

Lookahead discipline (mirrors engine/execution/executor.py):
  - ENTRY fills at the *next* trading session's open after a signal fires -
    never at the price the signal was computed from. This is why a fresh
    signal goes to PENDING_ENTRY and waits one run_once() cycle, exactly like
    build_order()'s next_session() does in the backtest engine.
  - EXIT (stop/target/time) is decided from as_of's own finalized OHLC - not
    lookahead, because by the time run_once(as_of) is called that session is
    already over.

Duplicate-entry guard: a symbol already PENDING_ENTRY or OPEN is skipped in
the new-signal scan (state dict membership is the only check - no separate
"already holding" flag to keep in sync).
"""
import pandas as pd

from engine.data.a2aProvider import A2aProvider
from engine.data.calendar import TradingCalendar
from engine.live import positionStore
from engine.live.contracts import OrderIntent
from engine.live.paperBroker import PaperBroker


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
