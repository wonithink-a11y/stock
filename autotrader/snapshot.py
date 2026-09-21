"""상태 스냅샷 — 브로커를 **읽기 전용**으로 조회해 `state/snapshot.json` 에 쓴다. 웹 화면은 이 파일만 읽는다.

이 작업만 KIS 키를 쓴다(웹 서버는 키가 없다). 페이지가 열릴 때마다 KIS 를 부르지 않는 이유: 계좌 단위 초당 건수 제한.
계좌번호는 스냅샷에 넣지 않는다.
"""
from __future__ import annotations

import json
import os
from datetime import datetime
from pathlib import Path
from typing import Dict, Optional

from .broker import Broker
from .config import gate_problems, kill_file, state_dir


def build_snapshot(cfg: dict, broker: Broker, env: Dict[str, str], now: datetime,
                   repo_root: Optional[Path] = None) -> dict:
    kw = {"repo_root": repo_root} if repo_root else {}
    snap = {"at": now.isoformat(), "mode": cfg["mode"], "broker": broker.name,
            "killSwitch": kill_file(cfg, **kw).exists(),
            "gates": {"dry": gate_problems(cfg, env, False, **kw), "execute": gate_problems(cfg, env, True, **kw)},
            "markets": {}}
    for m in cfg["markets"]:
        d: dict = {}
        try:
            pos = broker.positions(m)
            if cfg.get("profile"):                      # 프로필은 자기 종목만(같은 계좌를 여러 전략이 나눠 쓴다)
                allow = set(cfg.get("symbol_allowlist") or [])
                pos = [p for p in pos if p.symbol in allow]
            d["positions"] = [{"symbol": p.symbol, "qty": p.qty, "avgPrice": p.avg_price, "price": p.price} for p in pos]
            d["totals"] = totals(d["positions"])
            d["openOrders"] = [{"orderNo": o.order_no, "symbol": o.symbol, "side": o.side, "qty": o.qty,
                                "remaining": o.remaining, "price": o.price} for o in broker.open_orders(m)]
            ref = cfg.get("params", {}).get("snapshot_ref_symbol_us") if m == "US" else None
            d["cash"] = broker.cash(m, ref) if (m == "KR" or ref) else None
        except Exception as e:                          # noqa: BLE001 — 한 시장의 실패가 다른 시장을 막지 않는다
            d["error"] = f"{type(e).__name__}: {e}"[:200]
        snap["markets"][m] = d
    return snap


def totals(positions) -> dict:
    """투자금(매입원가)·평가금액·평가손익. 현재가를 모르는 종목이 하나라도 있으면 평가·손익은 None(모르는 것은 0 이 아니다)."""
    cost = sum(p["qty"] * p["avgPrice"] for p in positions)
    if any(not p.get("price") for p in positions):
        return {"cost": cost, "value": None, "pnl": None, "pnlPct": None}
    value = sum(p["qty"] * p["price"] for p in positions)
    return {"cost": cost, "value": value, "pnl": value - cost, "pnlPct": (value / cost - 1) * 100 if cost else None}


def write_snapshot(cfg: dict, snap: dict, repo_root: Optional[Path] = None) -> Path:
    sdir = state_dir(cfg, repo_root) if repo_root else state_dir(cfg)
    sdir.mkdir(parents=True, exist_ok=True)
    tmp = sdir / "snapshot.json.tmp"
    tmp.write_text(json.dumps(snap, ensure_ascii=False, indent=1), encoding="utf-8")
    os.replace(tmp, sdir / "snapshot.json")             # 읽는 쪽이 반쯤 쓴 파일을 보지 않게
    return sdir / "snapshot.json"
