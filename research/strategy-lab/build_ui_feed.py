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
LIVE_STRATEGIES = ["pbr_value_v1", "lowmom60_v1", "pbr_value_v1_combined", "factor_earnings_yield_v1"]


HISTORY_SESSIONS = 60  # 차트용 최근 일봉 개수


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


def main():
    from engine.live import positionStore
    from engine.live.kisVtsClient import KisVtsClient, KisVtsError

    try:
        holdings, cash, eval_total = KisVtsClient().inquire_balance()
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
            row = {"symbol": symbol, "status": pos["status"], "quantity": pos.get("quantity"),
                   "intentDate": pos.get("intent_date"), "history": history_by_symbol.get(symbol, [])}
            h = holdings_by_symbol.get(symbol)
            if h:  # KIS가 실제로 보유 중으로 잡은 종목 - PENDING/SUBMITTED는 아직 없음
                row.update({
                    "quantity": int(h["hldg_qty"]),
                    "avgEntryPrice": float(h["pchs_avg_pric"]),
                    "currentPrice": float(h["prpr"]),
                    "unrealizedPnlKrw": float(h["evlu_pfls_amt"]),
                    "unrealizedPnlPct": float(h["evlu_pfls_rt"]),
                })
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
    }
    os.makedirs(os.path.dirname(OUT_PATH), exist_ok=True)
    with open(OUT_PATH, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=2)
    print(f"저장: {OUT_PATH} ({sum(len(s['positions']) for s in strategies.values())}건)")


if __name__ == "__main__":
    main()
