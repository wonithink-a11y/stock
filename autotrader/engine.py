"""엔진 — 게이트 → 정합 → 전략 → 위험 검사 → 주문 → 원장.

한 번의 `run_once` 가 하는 일(순서가 계약이다):
  1. 실행 게이트(config.gate_problems) — 안 맞으면 GateError. 조용히 강등하지 않는다.
  2. 정합: **우리가 낸 주문(원장에 주문번호가 있는 것)만** 다룬다. 사용자가 수동으로 낸 주문은 건드리지 않고,
     그 종목은 건너뛴다. 해외(US)는 우리 미체결을 취소→재조회로 확인, 국내(KR)는 당일물이라 그 종목만 건너뛴다.
  3. 전략 `decide(ctx)` — 주문 목록(Intent)만 받는다.
  4. 주문마다 위험 검사(risk.check_intent)를 통과해야 한다. 킬 스위치는 **주문 직전마다** 다시 본다.
  5. `--execute` 가 아니면 주문하지 않고 계획만 리포트한다(기본).
  6. 주문 실패는 재시도하지 않고 그 실행을 중단한다(중복 주문보다 하루 건너뛰는 게 낫다).
"""
from __future__ import annotations

import json
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Callable, Dict, List, Optional

from . import risk
from .broker import Broker
from .config import GateError, REPO_ROOT, gate_problems, kill_file, state_dir
from .models import Intent
from .strategy import Context, Strategy

KST = timezone(timedelta(hours=9))


class Ledger:
    """실행된 주문의 추가 전용 기록(jsonl). 일일 한도의 근거이자 '우리가 낸 주문' 판별의 기준이다."""

    def __init__(self, sdir: Path):
        self.path = Path(sdir) / "ledger.jsonl"

    def append(self, rec: dict) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(rec, ensure_ascii=False, default=str) + "\n")

    def rows(self) -> List[dict]:
        if not self.path.exists():
            return []
        out = []
        for line in self.path.read_text(encoding="utf-8").splitlines():
            try:
                out.append(json.loads(line))
            except ValueError:
                continue                     # 깨진 줄 하나가 전체를 막지 않게(읽기 전용 감사 기록)
        return out

    def order_nos(self) -> set:
        return {r["orderNo"] for r in self.rows()
                if r.get("kind") == "order" and r.get("executed") and r.get("orderNo")}

    def spent_today(self, market: str, day: str) -> float:
        return sum(float(r.get("value") or 0) for r in self.rows()
                   if r.get("kind") == "order" and r.get("executed")
                   and r.get("market") == market and r.get("day") == day)


def _load_state(sdir: Path, name: str) -> dict:
    p = Path(sdir) / f"strategy_{name}.json"
    if p.exists():
        try:
            return json.loads(p.read_text(encoding="utf-8"))
        except ValueError:
            return {}
    return {}


def _save_json(path: Path, obj) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, ensure_ascii=False, indent=1, default=str), encoding="utf-8")


def _reconcile(broker: Broker, market: str, ledger: Ledger, execute: bool, report: dict,
               blocked: set, sleep: Callable[[float], None], tries: int = 3) -> None:
    """미체결 정리. 우리 주문만 취소한다. 취소가 확인되지 않은 종목은 blocked 에 넣어 그날 주문을 막는다."""
    mine_nos = ledger.order_nos()
    open_orders = broker.open_orders(market)
    mine = [o for o in open_orders if o.order_no in mine_nos]
    foreign = [o for o in open_orders if o.order_no not in mine_nos]
    for o in foreign:                                   # 남의(수동) 미체결 — 건드리지 않고 그 종목만 건너뜀
        blocked.add(o.symbol)
        report["skipped"].append({"symbol": o.symbol, "reason": f"사용자 수동 미체결 주문 {o.order_no} 이 있다(건드리지 않음)"})
    if not mine:
        return
    if market == "KR":                                  # 국내 주문은 당일물 — 취소하지 않고 그 종목만 건너뜀
        for o in mine:
            blocked.add(o.symbol)
            report["skipped"].append({"symbol": o.symbol, "reason": f"오늘 낸 미체결 {o.order_no} 이 남아 있다(당일물, 취소 안 함)"})
        return
    report["reconcile"].append({"market": market, "ourOpenOrders": [o.order_no for o in mine], "execute": execute})
    if not execute:
        return                                          # dry-run: 취소하지 않는다, 계획만 남긴다
    for o in mine:
        try:
            broker.cancel(o, dry_run=False)
            report["cancelled"].append({"orderNo": o.order_no, "symbol": o.symbol})
        except Exception as e:                          # noqa: BLE001 — 실패는 아래 재조회가 판정한다
            report["errors"].append(f"취소 실패 {o.order_no}: {e}")
    remaining = []
    for k in range(tries):
        remaining = [o for o in broker.open_orders(market) if o.order_no in {m.order_no for m in mine}]
        if not remaining:
            break
        if k < tries - 1:
            sleep(1.0)
    for o in remaining:
        blocked.add(o.symbol)
        report["skipped"].append({"symbol": o.symbol, "reason": f"취소를 확인하지 못했다({o.order_no}) — 오늘 주문 안 냄"})


def run_once(cfg: dict, broker: Broker, strategy: Strategy, *, execute: bool, env: Dict[str, str],
             repo_root: Path = REPO_ROOT, now: Optional[datetime] = None,
             sleep: Callable[[float], None] = time.sleep) -> dict:
    problems = gate_problems(cfg, env, execute, repo_root)
    if problems:
        raise GateError(problems)

    now = now or datetime.now(KST)
    sdir = state_dir(cfg, repo_root)
    ledger = Ledger(sdir)
    run_id = now.strftime("%Y%m%d-%H%M%S")
    day = now.strftime("%Y-%m-%d")
    report = {"runId": run_id, "at": now.isoformat(), "mode": cfg["mode"], "execute": execute,
              "strategy": strategy.name, "broker": broker.name, "markets": [],
              "planned": [], "placed": [], "rejected": [], "skipped": [], "reconcile": [],
              "cancelled": [], "errors": [], "status": "ok"}

    state = _load_state(sdir, strategy.name)
    markets = [m for m in cfg["markets"] if m in strategy.markets]
    report["markets"] = markets
    blocked: set = set()
    for m in markets:
        _reconcile(broker, m, ledger, execute, report, blocked, sleep)

    ctx = Context(broker, now, cfg.get("params", {}), state)
    try:
        intents = [i for i in strategy.decide(ctx) if i.market in markets]
    except Exception as e:                              # noqa: BLE001 — 전략 오류는 주문 없이 종료
        report["errors"].append(f"전략 오류: {type(e).__name__}: {e}")
        report["status"] = "strategy-error"
        intents = []

    spent_run: Dict[str, float] = {m: 0.0 for m in markets}
    orders_run: Dict[str, int] = {m: 0 for m in markets}
    sold_run: Dict[tuple, int] = {}
    cash_left: Dict[str, float] = {}
    seen: set = set()
    kill = kill_file(cfg, repo_root)
    aborted = False

    for it in intents:
        rec = {"symbol": it.symbol, "side": it.side, "qty": it.qty, "market": it.market,
               "orderType": it.order_type, "limitPrice": it.limit_price, "reason": it.reason}
        if aborted:
            report["skipped"].append({**rec, "reason": "앞선 주문 실패로 이번 실행 중단"})
            continue
        if it.symbol in blocked:
            report["skipped"].append({**rec, "reason": "미체결/충돌로 이 종목은 오늘 건너뜀"})
            continue
        key = (it.market, it.symbol, it.side)
        if key in seen:
            report["rejected"].append({**rec, "reason": "같은 실행 안에 같은 종목·방향이 중복"})
            continue
        seen.add(key)
        try:
            last = ctx.quote(it.symbol, it.market)
        except Exception as e:                          # noqa: BLE001
            report["rejected"].append({**rec, "reason": f"시세 조회 실패: {e}"})
            continue
        pos = ctx.positions(it.market).get(it.symbol)
        sellable = (pos.qty if pos else 0) - sold_run.get((it.market, it.symbol), 0)
        held_value = (pos.qty if pos else 0) * last
        if it.side == "BUY" and it.market not in cash_left:
            try:
                cash_left[it.market] = ctx.cash(it.market, it.symbol)
            except Exception as e:                      # noqa: BLE001
                report["rejected"].append({**rec, "reason": f"현금 조회 실패: {e}"})
                continue
        why = risk.check_intent(
            it, risk=cfg["risk"][it.market], allowlist=cfg.get("symbol_allowlist", []),
            last_price=last, sellable_qty=sellable, cash=cash_left.get(it.market, 0.0),
            held_value=held_value, spent_today=ledger.spent_today(it.market, day),
            spent_run=spent_run[it.market], orders_run=orders_run[it.market])
        if why:
            report["rejected"].append({**rec, "reason": why})
            continue
        value = risk.order_value(it, last)
        if execute and kill.exists():                   # 주문 직전마다 킬 스위치를 다시 본다
            report["errors"].append("킬 스위치 감지 — 이번 실행 중단")
            report["status"] = "killed"
            aborted = True
            report["skipped"].append({**rec, "reason": "킬 스위치"})
            continue
        spent_run[it.market] += value
        orders_run[it.market] += 1
        if it.side == "SELL":
            sold_run[(it.market, it.symbol)] = sold_run.get((it.market, it.symbol), 0) + it.qty
        else:
            cash_left[it.market] = cash_left.get(it.market, 0.0) - value
        if not execute:
            report["planned"].append({**rec, "value": round(value, 2), "lastPrice": last})
            continue
        try:
            res = broker.place(it, dry_run=False)
        except Exception as e:                          # noqa: BLE001 — 재시도하지 않고 중단
            report["errors"].append(f"주문 실패 {it.symbol}: {e}")
            report["status"] = "order-error"
            aborted = True
            ledger.append({"ts": now.isoformat(), "day": day, "runId": run_id, "mode": cfg["mode"],
                           "strategy": strategy.name, "kind": "error", "market": it.market,
                           "symbol": it.symbol, "side": it.side, "qty": it.qty, "executed": False,
                           "error": str(e)})
            continue
        ledger.append({"ts": now.isoformat(), "day": day, "runId": run_id, "mode": cfg["mode"],
                       "strategy": strategy.name, "kind": "order", "market": it.market,
                       "symbol": it.symbol, "side": it.side, "qty": it.qty,
                       "price": it.limit_price if it.limit_price else last, "value": round(value, 2),
                       "orderNo": res.get("orderNo"), "executed": True})
        report["placed"].append({**rec, "value": round(value, 2), "orderNo": res.get("orderNo")})

    _save_json(Path(sdir) / f"strategy_{strategy.name}.json", ctx.state)
    _save_json(Path(sdir) / "runs" / f"{run_id}.json", report)
    return report
