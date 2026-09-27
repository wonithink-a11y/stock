"""직접매매 계획 카드 — 계획 검증·수량·상태 전이·결과(R 배수). 순수 함수만(브로커·네트워크 없음).

설계: docs/control/직접매매-계획카드-설계-2026-09-27.md

파일이 둘이고 쓰는 쪽이 하나씩이다(덮어쓰기 경합 없음):
    <프로필 상태>/plans.json               웹만 쓴다 — 계획 정의 + 사용자 요청(취소·지금 청산)
    <프로필 상태>/strategy_plan_trader.json 전략만 쓴다 — 계획별 진행 상태(ctx.state["plans"])
웹이 뚫려도 계획으로 낼 수 있는 주문은 프로필 파일(SSH 전용)의 허용 종목·한도 안이다 — 엔진이 매 주문 검사한다.
"""
from __future__ import annotations

import json
import math
import os
import re
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, List, Optional, Tuple

TICKER = re.compile(r"^[0-9A-Z]{6}$")
MAX_ACTIVE = 20               # 동시에 살아 있는 계획 수 상한(실수로 대량 입력 방지)
MAX_RISK_PCT = 5.0            # 한 계획이 잃어도 되는 자본 비율의 상한
MAX_EXIT_TRIES = 3            # 청산 주문은 계획당 하루 3번까지(휴장일에 5분마다 실패 알림이 쌓이지 않게)
MIN_SAMPLE = 30               # 종료 30건 전에는 기대값을 판정에 쓰지 않는다(설계 §5 — 결과 보기 전에 고정)
MIN_TAG_SAMPLE = 20           # 태그별 비교는 태그마다 20건 이상일 때만

STATUS_KO = {"wait": "대기", "entering": "진입 주문", "held": "보유", "exiting": "청산 주문",
             "done": "종료", "expired": "만료", "cancelled": "취소"}
CLOSED = ("done", "expired", "cancelled")


# ------------------------------------------------------------------ 파일(웹 소유)
def plans_path(sdir) -> Path:
    return Path(sdir) / "plans.json"


def load_plans(sdir) -> List[dict]:
    try:
        d = json.loads(plans_path(sdir).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    return [p for p in (d.get("plans") or []) if isinstance(p, dict) and p.get("id")]


def save_plans(sdir, plans: List[dict]) -> None:
    p = plans_path(sdir)
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(".tmp")
    tmp.write_text(json.dumps({"plans": plans}, ensure_ascii=False, indent=1), encoding="utf-8")
    os.replace(tmp, p)


# ------------------------------------------------------------------ 입력 검증·수량
def _num(v) -> Optional[float]:
    try:
        x = float(str(v).replace(",", "").strip())
    except (TypeError, ValueError):
        return None
    return x if math.isfinite(x) else None


def reward_risk(entry: float, stop: float, target: float) -> Optional[float]:
    """손익비 = (목표 − 진입) ÷ (진입 − 손절). 진입이 손절 이하면 정의 안 됨."""
    return (target - entry) / (entry - stop) if entry > stop else None


def size_qty(capital: float, risk_pct: float, entry: float, stop: float) -> int:
    """1회 손실을 자본의 risk_pct% 로 묶는 수량. 진입은 구간 **위쪽**(entryHigh)을 넣는다 — 실제 손실이 한도를 넘지 않게."""
    per = entry - stop
    return int(math.floor(capital * risk_pct / 100.0 / per)) if per > 0 else 0


def build_plan(form: Dict[str, str], cfg: dict, now: datetime, active: int) -> Tuple[Optional[dict], str]:
    """웹 입력 → 계획. (계획, "") 또는 (None, 거부 사유). 한도 검사를 입력 시점에 한다 — 들어간 계획은 주문이 나갈 수 있는 계획이다."""
    capital = _num((cfg.get("params") or {}).get("capital"))
    if not capital or capital <= 0:
        return None, "프로필 params.capital(자본)이 없다 — 수량을 계산할 수 없어 계획을 받지 않는다"
    if active >= MAX_ACTIVE:
        return None, f"살아 있는 계획이 {MAX_ACTIVE}개다 — 먼저 정리"
    sym = str(form.get("symbol", "")).strip().upper()
    if not TICKER.match(sym):
        return None, "종목코드는 6자리(숫자·대문자)"
    if sym not in (cfg.get("symbol_allowlist") or []):
        return None, f"{sym} 은 이 프로필의 허용 종목이 아니다(프로필 파일 symbol_allowlist — 서버에서만 바꾼다)"
    lo, hi = _num(form.get("entryLow")), _num(form.get("entryHigh"))
    hi = lo if hi is None else hi
    stop, target, risk = _num(form.get("stop")), _num(form.get("target")), _num(form.get("riskPct"))
    if None in (lo, hi, stop, target, risk) or min(lo, hi, stop, target) <= 0:
        return None, "가격·위험 비율은 양수로"
    if not (stop < lo <= hi < target):
        return None, "순서가 맞아야 한다: 손절 < 진입 하단 ≤ 진입 상단 < 목표"
    if not (0 < risk <= MAX_RISK_PCT):
        return None, f"1회 손실 한도는 0 초과 {MAX_RISK_PCT}% 이하"
    qty = size_qty(capital, risk, hi, stop)
    if qty < 1:
        return None, "계산된 수량이 0 이다(손절 폭이 너무 넓거나 위험 비율이 너무 작다)"
    r = (cfg.get("risk") or {}).get("KR") or {}
    value = qty * hi
    for key, label in (("max_order_value", "주문당 한도"), ("max_position_value", "종목당 보유 한도")):
        if r.get(key) and value > r[key]:
            return None, f"주문 금액 {value:,.0f}원 이 {label} {r[key]:,.0f}원 을 넘는다(수량 {qty}) — 위험 비율을 낮추거나 한도를 서버에서 올린다"
    days = int(_num(form.get("validDays")) or 14)
    days = max(1, min(days, 60))
    pid = now.strftime("%y%m%d-%H%M%S")
    return {"id": pid, "symbol": sym, "market": "KR", "entryLow": lo, "entryHigh": hi, "stop": stop, "target": target,
            "riskPct": risk, "capital": capital, "qty": qty,
            "validUntil": (now + timedelta(days=days)).strftime("%Y-%m-%d"),
            "invalidation": str(form.get("invalidation", ""))[:200], "thesis": str(form.get("thesis", ""))[:200],
            "tag": str(form.get("tag", "")).strip()[:20], "createdAt": now.isoformat()}, ""


# ------------------------------------------------------------------ 상태 전이(전략이 부른다)
def step(p: dict, s: dict, held: int, last: float, today: str) -> Optional[Tuple[str, int, str]]:
    """계획 하나를 한 걸음 진행한다. s(진행 상태)를 고치고, 낼 주문이 있으면 (방향, 수량, 사유).

    held = 지금 계좌의 그 종목 수량(다른 전략 몫이 섞여 있을 수 있다 — 그래서 주문 전 수량과의 차이로만 센다).
    알림·체결은 엔진·스냅샷이 맡는다. 여기서는 주문을 '내겠다'까지만 정한다.
    """
    st = s.get("status", "wait")
    if st in CLOSED:
        return None
    if st == "wait":
        if p.get("cancel"):
            s.update(status="cancelled", closedAt=today)
            return None
        if today > p["validUntil"]:
            s.update(status="expired", closedAt=today)
            return None
        if s.get("entryDay") == today:                      # 진입 시도는 하루 한 번(재시도로 중복 매수하지 않는다)
            return None
        if p["entryLow"] <= last <= p["entryHigh"]:
            s.update(status="entering", entryDay=today, preQty=held, entryRef=last)
            return ("BUY", int(p["qty"]), "진입")
        return None
    if st == "entering":
        got = held - int(s.get("preQty", 0))
        if got > 0:
            s.update(status="held", heldQty=min(got, int(p["qty"])))
        else:
            if today != s.get("entryDay"):                  # 국내 주문은 당일물 — 안 맞았으면 다음 날 다시 대기
                s["status"] = "wait"
            return None
    if s["status"] == "exiting":
        sold = int(s["preExitQty"]) - held
        if sold >= int(s["sellQty"]):
            s.update(status="done", closedAt=today)
            return None
        s.update(status="held", heldQty=max(0, int(s["heldQty"]) - max(0, sold)))     # 덜 팔렸다 — 남은 만큼 다시 판단
    # held
    qty = min(int(s.get("heldQty", 0)), held)
    if qty <= 0:
        s.update(status="done", closedAt=today, exitReason="계좌에서 사라짐(수동 매도 등)")
        return None
    reason = ("손절" if last <= p["stop"] else "목표" if last >= p["target"]
              else "지금 청산 요청" if p.get("closeReq") else None)
    if not reason:
        return None
    tries = (s.get("exitTries") or {}).get(today, 0)
    if tries >= MAX_EXIT_TRIES:
        return None
    s.update(status="exiting", exitTries={today: tries + 1}, exitDay=today, exitReason=reason, exitRef=last,
             preExitQty=held, sellQty=qty)
    return ("SELL", qty, reason)


def reason_tag(pid: str, why: str) -> str:
    return f"plan:{pid} {why}"


# ------------------------------------------------------------------ 결과(웹이 부른다)
def fills_by_plan(ledger_rows: List[dict], book: Optional[dict]) -> Dict[str, Dict[str, dict]]:
    """계획 id → {"BUY": {qty, value}, "SELL": {...}} — 우리 주문번호의 **실제 체결**(스냅샷이 쌓은 fills.json)로만."""
    fills = (book or {}).get("fills") or {}
    out: Dict[str, Dict[str, dict]] = {}
    for r in ledger_rows:
        m = re.match(r"^plan:(\S+) ", str(r.get("reason") or ""))
        if not (m and r.get("kind") == "order" and r.get("executed") and r.get("orderNo") in fills):
            continue
        f = fills[r["orderNo"]]
        q, px = float(f.get("qty") or 0), float(f.get("price") or 0)
        if q <= 0 or px <= 0:
            continue
        a = out.setdefault(m.group(1), {}).setdefault(r.get("side"), {"qty": 0.0, "value": 0.0})
        a["qty"] += q
        a["value"] += q * px
    return out


def outcome(p: dict, f: Dict[str, dict]) -> dict:
    """체결 평균가로 R 배수. 체결을 모르면 None(0 이 아니다)."""
    b, s = f.get("BUY"), f.get("SELL")
    entry = b["value"] / b["qty"] if b and b["qty"] else None
    exit_ = s["value"] / s["qty"] if s and s["qty"] else None
    r = ((exit_ - entry) / (entry - p["stop"]) if entry and exit_ and entry > p["stop"] else None)
    return {"entry": entry, "exit": exit_, "R": r}


def summarize(rs: List[float]) -> dict:
    n = len(rs)
    if not n:
        return {"n": 0}
    wins = [x for x in rs if x > 0]
    losses = [x for x in rs if x <= 0]
    return {"n": n, "winRate": len(wins) / n, "avgWin": sum(wins) / len(wins) if wins else None,
            "avgLoss": sum(losses) / len(losses) if losses else None, "expectancy": sum(rs) / n,
            "worseThan1R": sum(1 for x in rs if x < -1.0), "enough": n >= MIN_SAMPLE}
