"""실현손익 — 체결 원장(`state/.../fills.json`)과 평균단가 방식.

주문 원장(ledger.jsonl)은 "주문을 냈다"까지만 안다. 지정가는 안 맞을 수도, 일부만 맞을 수도 있어서 실현손익은
**브로커 체결내역**으로만 셀 수 있다. 스냅샷(5분마다)이 우리 주문번호의 체결을 받아 이 파일에 쌓는다.

★ 우리 주문만 센다. 같은 계좌를 다른 프로그램(PBR 슬리브·옛 무한매수 러너)도 쓰므로 계좌 체결 전체는 이 전략의 것이 아니다.
★ 시작 보유(opening): 이 파일을 처음 만들 때 계좌에 이미 있던 수량·평단을 원가로 삼는다(옛 러너가 산 TQQQ 등).
   그 뒤에 **다른 프로그램이 같은 종목을 사고팔면** 이 계산은 계좌와 어긋난다 — 그 종목은 한 프로그램만 다룬다.
★ 수수료·세금은 빠져 있다(브로커 체결가 기준). 모르는 것은 0 이 아니다 — 원가를 모르는 매도는 incomplete 로 표시한다.
"""
from __future__ import annotations

import json
import os
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, List, Optional

from .config import state_dir
from .engine import Ledger

LOOKBACK_DAYS = 7          # 이 기간 안에 낸 주문만 다시 조회한다(그 뒤엔 체결이 더 생기지 않는다 — 우리 미체결은 다음 실행이 취소)


def fills_path(cfg: dict) -> Path:
    return state_dir(cfg) / "fills.json"


def load_book(cfg: dict) -> Optional[dict]:
    try:
        return json.loads(fills_path(cfg).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def sync_fills(cfg: dict, broker, snap: dict, now: datetime) -> dict:
    """우리 주문의 누적 체결을 브로커에서 받아 체결 원장을 갱신한다. 처음이면 스냅샷의 보유를 시작 원가로 잡는다."""
    ours = {r["orderNo"]: r for r in Ledger(state_dir(cfg)).rows()
            if r.get("kind") == "order" and r.get("executed") and r.get("orderNo")}
    book = load_book(cfg)
    if book is None:
        book = {"openedAt": now.isoformat(), "exclude": sorted(ours), "fills": {},
                "opening": {m: {p["symbol"]: {"qty": p["qty"], "avg": p["avgPrice"]} for p in d.get("positions", [])}
                            for m, d in snap["markets"].items() if "positions" in d}}
    cutoff = (now - timedelta(days=LOOKBACK_DAYS)).strftime("%Y-%m-%d")
    for m in snap["markets"]:
        pending = [o for no, o in ours.items() if o.get("market") == m and no not in book["exclude"]
                   and str(o.get("day", "")) >= cutoff]
        if not pending:
            continue
        start = (datetime.strptime(min(o["day"] for o in pending), "%Y-%m-%d") - timedelta(days=1)).strftime("%Y%m%d")
        for f in broker.fills(m, start, now.strftime("%Y%m%d")):
            if f["orderNo"] in ours and f["orderNo"] not in book["exclude"]:
                book["fills"][f["orderNo"]] = {**f, "market": m}          # 누적값이라 덮어쓴다(부분체결이 늘어나도 한 줄)
    p = fills_path(cfg)
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(".tmp")
    tmp.write_text(json.dumps(book, ensure_ascii=False, indent=1), encoding="utf-8")
    os.replace(tmp, p)
    return book


def new_fills(prev: Optional[dict], book: Optional[dict]) -> List[dict]:
    """이번 동기화에서 **늘어난** 체결만(주문별 누적 수량의 증가분 `delta`). 체결 알림용 — 같은 체결을 두 번 알리지 않는다."""
    before = (prev or {}).get("fills") or {}
    out = []
    for no, f in ((book or {}).get("fills") or {}).items():
        d = int(f.get("qty") or 0) - int((before.get(no) or {}).get("qty") or 0)
        if d > 0:
            out.append({**f, "orderNo": no, "delta": d})
    return out


def realized(book: Optional[dict]) -> Dict[str, dict]:
    """시장별 실현손익(평균단가 방식). {시장: {"realized", "incomplete", "sells": [...]}}"""
    if not book:
        return {}
    out: Dict[str, dict] = {}
    pos: Dict[tuple, list] = {}                                        # (시장, 종목) -> [수량, 원가]
    for m, syms in (book.get("opening") or {}).items():
        for s, v in syms.items():
            pos[(m, s)] = [int(v["qty"]), int(v["qty"]) * float(v["avg"])]
    for f in sorted(book.get("fills", {}).values(), key=lambda f: (f.get("day", ""), f["orderNo"])):
        m, key, q, px = f["market"], (f["market"], f["symbol"]), int(f["qty"]), float(f["price"])
        r = out.setdefault(m, {"realized": 0.0, "incomplete": False, "sells": []})
        qty, cost = pos.get(key, [0, 0.0])
        if f["side"] == "BUY":
            pos[key] = [qty + q, cost + q * px]
            continue
        if qty < q:                                                    # 원가를 모르는 매도 — 지어내지 않는다
            r["incomplete"] = True
            pos[key] = [0, 0.0]
            continue
        avg = cost / qty
        pnl = q * (px - avg)
        r["realized"] += pnl
        r["sells"].append({"day": f.get("day"), "symbol": f["symbol"], "qty": q, "price": px, "avg": avg, "pnl": pnl})
        pos[key] = [qty - q, cost - q * avg]
    return out
