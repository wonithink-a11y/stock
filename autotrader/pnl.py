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

def _n(x):
    """수량 — 주식은 정수 그대로, 코인(업비트)은 소수. 정수로 떨어지면 int 로 둔다(기존 원장·알림 표기 불변)."""
    f = float(x or 0)
    return int(f) if f.is_integer() else f


LOOKBACK_DAYS = 7          # 이 기간 안에 낸 주문만 다시 조회한다(그 뒤엔 체결이 더 생기지 않는다 — 우리 미체결은 다음 실행이 취소)
MAX_LOOKBACK_DAYS = 90     # 수동 되살리기(`fills-sync --days`) 상한 — KIS 체결내역 조회 기간(약 3개월)


def fills_path(cfg: dict) -> Path:
    return state_dir(cfg) / "fills.json"


def load_book(cfg: dict) -> Optional[dict]:
    try:
        return json.loads(fills_path(cfg).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def _key(no) -> str:
    """주문번호 대조용 — 숫자 주문번호는 앞의 0 을 뗀다(주문 응답 ODNO 와 체결내역 odno 의 자릿수가 달라도 같은 주문).
    업비트 UUID 처럼 숫자가 아니면 그대로."""
    s = str(no or "").strip()
    return (s.lstrip("0") or "0") if s.isdigit() else s


def sync_fills(cfg: dict, broker, snap: dict, now: datetime, lookback_days: int = LOOKBACK_DAYS) -> dict:
    """우리 주문의 누적 체결을 브로커에서 받아 체결 원장을 갱신한다. 처음이면 스냅샷의 보유를 시작 원가로 잡는다.

    매 동기화의 사실(조회 기간·받은 행·맞춘 행·오류·주문번호 표본)을 `sync` 에 남긴다 — 체결이 0 건일 때
    '체결이 없었다'와 '조회가 실패했다'와 '번호가 안 맞았다'를 가르려면 그 자리에서 남겨야 한다(교훈 75).
    한 시장의 조회 실패가 다른 시장의 갱신을 막지 않는다. 실패는 `sync.errors` 에 남는다(호출부가 화면에 올린다).
    """
    lookback_days = max(1, min(int(lookback_days), MAX_LOOKBACK_DAYS))
    ours = {r["orderNo"]: r for r in Ledger(state_dir(cfg)).rows()
            if r.get("kind") == "order" and r.get("executed") and r.get("orderNo")}
    book = load_book(cfg)
    if book is None:
        book = {"openedAt": now.isoformat(), "exclude": sorted(ours), "fills": {},
                # 업비트는 시작 보유를 원가에 넣지 않는다 — 계좌의 기존 코인은 사용자 개인 보유이고 전략은 자기 체결분만 판다.
                # 넣으면 개인 평단이 섞여 전략 실현손익이 틀어진다(원가 모르는 매도는 incomplete 로 드러난다).
                "opening": {m: {p["symbol"]: {"qty": p["qty"], "avg": p["avgPrice"]} for p in d.get("positions", [])}
                            for m, d in snap["markets"].items() if "positions" in d and m not in ("UPBIT", "BITHUMB")}}
    excluded = {_key(no) for no in book.get("exclude", [])}
    cutoff = (now - timedelta(days=lookback_days)).strftime("%Y-%m-%d")
    sync = {"at": now.isoformat(), "lookbackDays": lookback_days, "ledgerOrders": len(ours), "markets": {}}
    errors = []
    for m in snap["markets"]:
        pending = {_key(no): no for no, o in ours.items() if o.get("market") == m and _key(no) not in excluded
                   and str(o.get("day", "")) >= cutoff}
        info: dict = {"pending": len(pending)}
        sync["markets"][m] = info
        if not pending:
            continue
        start = (datetime.strptime(min(ours[no]["day"] for no in pending.values()), "%Y-%m-%d") - timedelta(days=1)).strftime("%Y%m%d")
        info["range"] = [start, now.strftime("%Y%m%d")]
        try:
            rows = broker.fills(m, start, now.strftime("%Y%m%d"))
        except Exception as e:                          # noqa: BLE001 — 기록하고 다음 시장으로
            info["error"] = f"{type(e).__name__}: {e}"[:200]
            errors.append(f"{m}: {info['error']}")
            continue
        matched = 0
        for f in rows:
            no = pending.get(_key(f.get("orderNo")))
            if no is not None:
                book["fills"][no] = {**f, "orderNo": no, "market": m}   # 누적값이라 덮어쓴다(부분체결이 늘어나도 한 줄)
                matched += 1
        info.update({"brokerRows": len(rows), "matched": matched,
                     # 번호 형식 대조용 표본(주문번호는 계좌번호가 아니다). 우리 미체결·취소분은 원래 안 맞는다.
                     "oursSample": sorted(pending.values())[-3:],
                     "brokerSample": [f.get("orderNo") for f in rows[:3]]})
    if errors:
        sync["errors"] = errors
    book["sync"] = sync
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
        d = _n(_n(f.get("qty")) - _n((before.get(no) or {}).get("qty")))
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
            pos[(m, s)] = [_n(v["qty"]), _n(v["qty"]) * float(v["avg"])]
    for f in sorted(book.get("fills", {}).values(), key=lambda f: (f.get("day", ""), f["orderNo"])):
        m, key, q, px = f["market"], (f["market"], f["symbol"]), _n(f["qty"]), float(f["price"])
        r = out.setdefault(m, {"realized": 0.0, "incomplete": False, "sells": []})
        qty, cost = pos.get(key, [0, 0.0])
        if f["side"] == "BUY":
            pos[key] = [qty + q, cost + q * px]
            continue
        if qty < q - 1e-9:                                             # 원가를 모르는 매도 — 지어내지 않는다
            r["incomplete"] = True
            pos[key] = [0, 0.0]
            continue
        avg = cost / qty
        pnl = q * (px - avg)
        r["realized"] += pnl
        r["sells"].append({"day": f.get("day"), "symbol": f["symbol"], "qty": q, "price": px, "avg": avg, "pnl": pnl})
        pos[key] = [qty - q, cost - q * avg]
    return out
