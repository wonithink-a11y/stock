"""종목코드 → 이름. 국내는 저장소의 유니버스(A1a 현재·제외, A1b 폐지 — 공개 대시보드 ticker-names 와 같은 출처),
해외·그 밖은 브로커 잔고 응답의 이름(스냅샷에 담긴다). 모르면 빈 문자열 — 코드만 보인다(지어내지 않는다)."""
from __future__ import annotations

import json
import time
from typing import Dict

from .config import REPO_ROOT

_SOURCES = ("data/backfill/universe/a1a/current.jsonl", "data/backfill/universe/a1a/excluded.jsonl",
            "data/backfill/universe/a1b/delisted.jsonl")
_cache: Dict[str, str] = {}
_loaded_at = 0.0


def universe_names(max_age_sec: float = 86400) -> Dict[str, str]:
    """하루 한 번 다시 읽는다(VM 은 매일 pull — 신규 상장 이름이 늦어도 하루)."""
    global _cache, _loaded_at
    if _cache and time.time() - _loaded_at < max_age_sec:
        return _cache
    out: Dict[str, str] = {}
    for rel in _SOURCES:
        p = REPO_ROOT / rel
        if not p.exists():
            continue
        for line in p.read_text(encoding="utf-8").splitlines():
            try:
                row = json.loads(line)
            except ValueError:
                continue
            if row.get("ticker") and row.get("name") and row["ticker"] not in out:     # 활성 이름이 폐지 이름보다 먼저
                out[row["ticker"]] = row["name"]
    _cache, _loaded_at = out, time.time()
    return out


def names_for(snapshots) -> Dict[str, str]:
    """유니버스 + 스냅샷(브로커가 준 이름, 해외 ETF 등). 브로커 이름이 이긴다."""
    out = dict(universe_names())
    for snap in snapshots:
        for d in ((snap or {}).get("markets") or {}).values():
            for p in d.get("positions") or []:
                if p.get("name"):
                    out[p["symbol"]] = p["name"]
    return out
