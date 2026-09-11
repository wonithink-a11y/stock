#!/usr/bin/env python
"""ui/data/positions.json 빌더 - 오픈코드가 만들 차트 UI가 읽는 데이터 피드.

KIS 모의투자 계좌를 읽기 전용으로 한 번 조회(inquire_balance - 주문 없음)해서
positionStore(전략별 보유상태, research/strategy-lab/data/paper/*.json)와
합친다. inquire_balance 응답 자체에 현재가·평가손익이 이미 들어있어(KIS가
계좌 보유종목 조회에 시세를 같이 준다) 종목마다 별도 시세조회를 안 한다 -
호출 1번으로 끝나 레이트리미터(계좌당 1건/초)에 걸릴 일이 없다.

오픈코드는 이 파일도, ui/data/ 아래 어떤 파일도 만들거나 고치지 않는다 -
읽기만 한다(AGENTS.md의 ui/ 위임 범위 참고). 이 스크립트는 KIS를 건드리므로
Claude가 직접 짜고 돌린다(직접 작성 예외 4번).

  python build_ui_feed.py
"""
import json
import os
import sys
from datetime import datetime, timedelta, timezone

_THIS_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, _THIS_DIR)
REPO_ROOT = os.path.dirname(os.path.dirname(_THIS_DIR))
OUT_PATH = os.path.join(REPO_ROOT, "ui", "data", "positions.json")
KST = timezone(timedelta(hours=9))
# 명시적 allowlist - data/paper/에는 dummy_sma20·각종 테스트(test_*_synth)의
# 옛 상태 파일도 같이 있다(글롭으로 다 긁으면 그것도 대시보드에 새 나온다,
# 실측으로 발견: dummy_sma20에 005930 1건이 남아있었다). 실제 파일럿
# 전략만 여기 나열한다.
LIVE_STRATEGIES = ["pbr_value_v1", "lowmom60_v1", "pbr_value_v1_combined",
                    "factor_earnings_yield_v1", "foreign_flow5d_v1"]


HISTORY_SESSIONS = 60  # 차트용 최근 일봉 개수
TRADE_LOOKBACK_DAYS = 90  # KIS 일별주문체결 조회 상한이 3개월이다


def _price_history(repo_root, symbols):
    """A2a 최근 일봉(종가만) - 오픈코드 UI가 라인/캔들 차트를 그릴 최소
    재료. ★ A2a는 workflow_dispatch 수동 트리거라 상시 최신이 아니다
    (CLAUDE.md 참고) - 그래서 "실시간 차트"가 아니라 "가장 최근 백필
    시점까지의 일봉"이다. UI는 이 한계를 화면에 표시해야 한다(작업지시서
    명시)."""
    from engine.data.a2aProvider import A2aProvider
    from engine.data.calendar import TradingCalendar
    calendar = TradingCalendar(repo_root=repo_root)
    a2a = A2aProvider(repo_root=repo_root, use_cache=True)
    end = calendar.days[-1]
    start = calendar.sessions_between(calendar.days[0], end)[-HISTORY_SESSIONS]
    bars_by_ticker = a2a.load(set(symbols), start, end, universe_hash="ui-feed-history")
    out = {}
    max_date = None
    for symbol, bars in bars_by_ticker.items():
        if bars.empty:
            continue
        out[symbol] = [{"date": str(idx.date()), "close": float(row["close"])}
                        for idx, row in bars.iterrows()]
        last = out[symbol][-1]["date"]
        if max_date is None or last > max_date:
            max_date = last
    return out, max_date



def _blank_day(date_str):
    return {"date": date_str, "buyKrw": 0, "sellKrw": 0, "buyCount": 0, "sellCount": 0,
            "realizedKrw": 0, "realizedFrom": 0}


def _realized(row, meta):
    """실현손익 = (체결평균가 - 진입가) x 체결수량. None 이면 잴 수 없다는 뜻이고
    0 이 아니다(교훈57) - 진입가는 원장에만 있고, 원장 이전 매도는 영영 모른다.
    수수료·세금은 안 뺀다(KIS 체결금액이 세전이다) - 화면이 그렇게 말한다."""
    if not meta or row["side"] != "SELL":
        return None
    entry = meta.get("entryPrice")
    if not entry or not row.get("avgPrice") or row["filledQty"] <= 0:
        return None
    return round((row["avgPrice"] - entry) * row["filledQty"])


def _add_fill(day, row, realized=None):
    if row["side"] == "SELL":
        day["sellKrw"] += row["amountKrw"]
        day["sellCount"] += 1
    else:
        day["buyKrw"] += row["amountKrw"]
        day["buyCount"] += 1
    if realized is not None:
        day["realizedKrw"] += realized
        day["realizedFrom"] += 1          # 몇 건으로 잰 값인가 - 분모를 숨기지 않는다


def _finish_days(by_date):
    days = sorted(by_date.values(), key=lambda d: d["date"], reverse=True)
    for day in days:
        day["netKrw"] = day["buyKrw"] - day["sellKrw"]
    return days


def _aggregate_trades(rows, today=None, order_meta=None):
    """체결내역 원시행 -> {"days", "byStrategy", "pending", "unattributed"}.

    days 는 날짜별 매수·매도 합계다 - "며칠에 얼마 팔고 얼마 샀다"가 UI 가
    묻는 전부이고, 종목 단위는 pending(진행 중)에만 필요하다.

    realizedKrw 는 매도 체결에만 붙는다 - 원장이 그 주문의 진입가를 들고 있고
    청산가는 KIS 가 준다. 원장 이전 매도는 진입가를 알 데가 없어 realizedFrom
    (몇 건으로 쟀나)이 그만큼 작게 나온다. 0 으로 메우지 않는다(교훈57).

    ★ 전략 귀속은 order_meta(주문번호 -> 원장 항목)로만 한다. 계좌 응답에는
    전략이 없고, 그 매핑은 주문을 내는 순간에만 존재했다가 체결 확인과 동시에
    사라진다 - 그래서 엔진이 제출 시점에 원장으로 남긴다
    (positionStore.record_order, 교훈75). **추측으로 메우지 않는다**: 원장에
    없는 주문(원장 도입 이전 것)은 전략에 안 넣고 unattributed 로 따로 센다.
    같은 종목을 여러 전략이 겹쳐 들기 때문에(pbr_value_v1 29종목 중 25종목이
    combined 와 겹친다) 종목·수량으로 되짚는 건 짐작이지 기록이 아니다.

    ★ pending 은 **today 인 주문만** 센다. KRX 주문은 당일 유효라 어제의
    미체결은 장 종료로 실효됐는데, 조회 응답의 rmn_qty 는 그대로 남는다 -
    날짜로 안 자르면 "진행 중인 주문"에 죽은 주문이 영원히 쌓인다.
    today 가 None 이면 자르지 않는다(테스트·과거 분석용).

    순수 함수라 네트워크 없이 테스트된다.
    """
    order_meta = order_meta or {}
    by_date = {}
    by_strategy = {}
    pending = []
    unattributed = {"buyKrw": 0, "sellKrw": 0, "count": 0}
    for r in rows:
        meta = order_meta.get(str(r.get("orderNo") or ""))
        owner = meta.get("strategy") if meta else None
        realized = _realized(r, meta)
        if r["pendingQty"] > 0 and not r["canceled"] and (today is None or r["date"] == today):
            entry = {k: r[k] for k in
                     ("date", "symbol", "name", "side", "orderedQty",
                      "filledQty", "pendingQty")}
            entry["strategy"] = owner
            pending.append(entry)
        if r["filledQty"] <= 0:
            continue
        _add_fill(by_date.setdefault(r["date"], _blank_day(r["date"])), r, realized)
        if owner:
            days = by_strategy.setdefault(owner, {})
            _add_fill(days.setdefault(r["date"], _blank_day(r["date"])), r, realized)
        else:
            unattributed["count"] += 1
            if r["side"] == "SELL":
                unattributed["sellKrw"] += r["amountKrw"]
            else:
                unattributed["buyKrw"] += r["amountKrw"]
    pending.sort(key=lambda p: (p["date"], p["symbol"]), reverse=True)
    return {"days": _finish_days(by_date),
            "byStrategy": {k: _finish_days(v) for k, v in by_strategy.items()},
            "pending": pending,
            "unattributed": unattributed}


def _order_ledger_map(repo_root, strategies):
    """주문번호 -> {strategy, side, entryPrice, ...}. 원장은 전략마다 따로 있고
    주문번호는 계좌 전역이라 한 장으로 합친다. 충돌은 구조적으로 없다
    (한 주문은 한 전략이 냈다)."""
    from engine.live import positionStore
    meta = {}
    for strategy_id in strategies:
        for order_no, entry in positionStore.load_orders(repo_root, strategy_id).items():
            meta[str(order_no)] = {**entry, "strategy": strategy_id}
    return meta


def _trades_block(client):
    """조회 실패는 치명적이지 않다 - 포지션 표는 그대로 나와야 한다. 다만
    실패를 빈 내역으로 위장하지 않는다(교훈57): error 를 담아 UI 가 말하게 한다."""
    from engine.live.kisVtsClient import KisVtsError
    today = datetime.now(KST).date()
    start = today - timedelta(days=TRADE_LOOKBACK_DAYS)
    block = {"fromDate": start.isoformat(), "toDate": today.isoformat(),
             "days": [], "byStrategy": {}, "pending": [],
             "unattributed": {"buyKrw": 0, "sellKrw": 0, "count": 0}, "error": None}
    if client is None:
        block["error"] = "KIS 클라이언트를 만들지 못했다(.env 누락)"
        return block
    try:
        rows = client.list_executions(start.strftime("%Y%m%d"), today.strftime("%Y%m%d"))
    except KisVtsError as e:
        print(f"[경고] KIS 체결내역 조회 실패, 매매 내역 없이 계속: {e}")
        block["error"] = str(e)
        return block
    meta = _order_ledger_map(REPO_ROOT, LIVE_STRATEGIES)
    block.update(_aggregate_trades(rows, today=today.isoformat(), order_meta=meta))
    print(f"체결내역: {len(block['days'])}일 · 진행 중 주문 {len(block['pending'])}건 · "
          f"전략귀속 {len(block['byStrategy'])}전략 · 미귀속 {block['unattributed']['count']}건 · "
          f"실현손익 {sum(d['realizedKrw'] for d in block['days']):,}원"
          f"({sum(d['realizedFrom'] for d in block['days'])}건으로 잼)")
    return block


def _position_row(symbol, pos, holding, history):
    """UI 한 줄. holding 은 KIS 잔고의 그 종목 행(없으면 None).

    ★ 수량·진입단가는 계좌가 아니라 **전략 장부**의 것을 쓴다. 같은 종목을 두
    전략이 들고 있으면(pbr_value_v1 은 29종목 중 25종목이 pbr_value_v1_combined
    와 겹친다) 계좌 수량은 그 합계다 - 그걸 전략마다 넣으면 전략별 노출이
    전량으로 부풀고, 합산하는 UI 도넛의 "예수금(미배분)"이 그만큼 줄어 보인다
    (실측 2026-09-09: 전략 합 262.9백만원 vs 실제 주식평가액 130.5백만원,
    예수금 233.8백만 표시 vs 실제 368.2백만). 계좌의 pchs_avg_pric 도 전략들이
    섞인 가중평균이라 한 전략의 손익을 못 낸다.

    진입 중(PENDING_ENTRY/ENTRY_SUBMITTED)이면 quantity 는 "사려는 목표"지
    보유량이 아니다 - 실제로 확인된 보유는 filled_quantity 다. 탑업
    (OPEN -> 목표 상향 -> PENDING_ENTRY)이 돌면 이 구간이 며칠 갈 수 있어,
    목표를 보유로 읽으면 그동안 노출이 부풀어 보인다. 부분체결분은 엔진이
    전량 체결 시점에 한 번에 반영하므로(중복 계상 방지) 이 값은 그때까지
    **마지막으로 확인된 보유량**이다 - 계좌보다 적을 수 있고, 그게 지어내지
    않는 쪽이다(교훈57).
    """
    held = (pos.get("quantity") or 0) if pos["status"] == "OPEN"         else (pos.get("filled_quantity") or 0)
    row = {"symbol": symbol, "status": pos["status"], "quantity": held,
           "intentDate": pos.get("intent_date"), "history": history}
    if not holding:
        return row
    current = float(holding["prpr"])
    entry = float(pos.get("entry_price") or holding["pchs_avg_pric"] or 0)
    row.update({
        "avgEntryPrice": entry or None,
        "currentPrice": current,
        "unrealizedPnlKrw": round((current - entry) * held) if entry else None,
        "unrealizedPnlPct": round((current / entry - 1) * 100, 2) if entry else None,
    })
    return row


def main():
    from engine.live import positionStore
    from engine.live.kisVtsClient import KisVtsClient, KisVtsError

    client = None
    try:
        client = KisVtsClient()          # __init__ 이 .env 누락으로 던질 수 있다
        holdings, cash, eval_total = client.inquire_balance()
    except KisVtsError as e:
        print(f"[경고] KIS 잔고 조회 실패, 계좌 정보 없이 계속: {e}")
        holdings, cash, eval_total = [], None, None
    holdings_by_symbol = {h["pdno"]: h for h in holdings}

    all_symbols = set()
    per_strategy_state = {}
    for strategy_id in LIVE_STRATEGIES:
        state = positionStore.load(REPO_ROOT, strategy_id)
        per_strategy_state[strategy_id] = state
        all_symbols.update(state.keys())
    history_by_symbol, history_as_of = (_price_history(REPO_ROOT, all_symbols)
                                         if all_symbols else ({}, None))

    strategies = {}
    for strategy_id, state in per_strategy_state.items():
        positions = []
        for symbol, pos in state.items():
            row = _position_row(symbol, pos, holdings_by_symbol.get(symbol),
                                 history_by_symbol.get(symbol, []))
            positions.append(row)
        strategies[strategy_id] = {"positions": positions}

    out = {
        "updatedAt": datetime.now(KST).isoformat(),
        "historyAsOf": history_as_of,  # 실제로 받은 일봉 중 최신일 - UI가 반드시 표시할 것
        "account": {
            "cashKrw": float(cash) if cash is not None else None,
            "totalValueKrw": float(eval_total) if eval_total is not None else None,
        },
        "strategies": strategies,
        "trades": _trades_block(client),
    }
    os.makedirs(os.path.dirname(OUT_PATH), exist_ok=True)
    with open(OUT_PATH, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=2)
    print(f"저장: {OUT_PATH} ({sum(len(s['positions']) for s in strategies.values())}건)")


if __name__ == "__main__":
    main()
