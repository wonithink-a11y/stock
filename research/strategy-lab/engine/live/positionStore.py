"""Restart-safe paper-trading position state - one JSON file per strategy under
research/strategy-lab/data/paper/. This is live mutable state, not a research
finding or a backfill artifact - data/backfill/ rule 4 does not apply here, but
by the same logic this directory is not meant to be committed either (added to
.gitignore alongside it). A crash or restart between runs must not lose a
PENDING_ENTRY or OPEN position - that is the entire point of writing it to disk
after every run_once() call instead of keeping it only in memory.
"""
import json
from datetime import date, timedelta
from pathlib import Path

STATE_DIR = "research/strategy-lab/data/paper"


def _path(repo_root, strategy_id):
    return Path(repo_root) / STATE_DIR / f"{strategy_id}_positions.json"


def load(repo_root, strategy_id):
    p = _path(repo_root, strategy_id)
    if not p.exists():
        return {}
    with open(p, encoding="utf-8") as f:
        return json.load(f)


def save(repo_root, strategy_id, positions):
    p = _path(repo_root, strategy_id)
    p.parent.mkdir(parents=True, exist_ok=True)
    with open(p, "w", encoding="utf-8") as f:
        json.dump(positions, f, ensure_ascii=False, indent=2)


# --- 주문 원장 (2026-09-11 신설) ---------------------------------------------
# 왜 있는가: 전략 귀속은 **주문을 내는 순간에만** 존재했다. order_no 는 체결
# 확인과 동시에 state 에서 지워지고(paperEngine 507), 매도가 체결되면 포지션
# 자체가 삭제된다(580) - 그래서 "어느 전략이 언제 얼마 사고 팔았나"와 전략별
# 실현손익을 나중에 물으면 답할 데가 없었다. 수명이 폴링 한 사이클(10분)이라
# UI(하루 3회)는 대부분 이미 지워진 뒤에 본다. 교훈75 - 원시 사실은 그 자리에서
# 남긴다. 없는 행은 이유를 말하지 않는다.
#
# 금액·체결가·체결수량은 **여기 안 적는다.** KIS 체결내역이 그 정본이고
# (odno 로 조인된다), 두 곳에 적으면 언젠가 갈린다. 이 파일은 매핑만 갖는다.
ORDERS_PRUNE_DAYS = 120   # KIS 일별주문체결 조회가 3개월까지다 - 그보다 조금만 더 든다


def _orders_path(repo_root, strategy_id):
    return Path(repo_root) / STATE_DIR / f"{strategy_id}_orders.json"


def load_orders(repo_root, strategy_id):
    p = _orders_path(repo_root, strategy_id)
    if not p.exists():
        return {}
    try:
        with open(p, encoding="utf-8") as f:
            return json.load(f)
    except ValueError:
        # 깨진 원장이 매매를 막지 않는다 - 귀속을 잃을 뿐이다(fail-soft).
        return {}


def record_order(repo_root, strategy_id, order_no, entry, today=None):
    """주문번호 -> {date, symbol, side, quantity, reason} 한 줄을 남긴다.

    ★ 이 함수는 예외를 던지지 않는다. 원장 쓰기 실패가 주문 루프를 멈추면
    기록하려던 편의가 매매를 깨는 사고가 된다 - 실패하면 그 주문의 귀속만
    비고 거래는 그대로 간다. 실패를 조용히 넘기지는 않는다(반환값 False).

    prune: entry["date"](YYYY-MM-DD)가 today 기준 ORDERS_PRUNE_DAYS 보다
    오래된 항목을 떨군다. 체결내역 조회 창을 넘어서면 조인할 상대가 없다.
    """
    if not order_no:
        return False
    try:
        orders = load_orders(repo_root, strategy_id)
        orders[str(order_no)] = entry
        today = today or entry.get("date")
        if today:
            cutoff = (date.fromisoformat(today) - timedelta(days=ORDERS_PRUNE_DAYS)).isoformat()
            orders = {k: v for k, v in orders.items() if (v.get("date") or "") >= cutoff}
        p = _orders_path(repo_root, strategy_id)
        p.parent.mkdir(parents=True, exist_ok=True)
        with open(p, "w", encoding="utf-8") as f:
            json.dump(orders, f, ensure_ascii=False, indent=2)
        return True
    except Exception:
        return False
