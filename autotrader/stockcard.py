"""종목 분석 카드 — 계획 입력 전에 보는 참고 자료와 **규칙으로 계산한** 진입·손절·목표. 새 수집 없음, 저장소 데이터만.

★ 투자 자문이 아니다. 가격은 아래 규칙의 계산값이고, 그 규칙의 검증 결과를 화면에 같이 적는다.
   손절 = 진입 상단 − 3×ATR14, 목표 = 진입 상단 + 1.5×손절폭 — PBR 포트폴리오 청산규칙 연구의 변형 C 그대로
   (research/strategy-lab/findings/tier2-exit-policy-oos-2026-09.md: 낙폭은 줄었고 TEST 수익은 무손절보다 낮았다).
   진입 구간(현재가 −1% ~ 현재가)은 규칙이 아니라 체결 여유다 — 연구 근거 없음.
★ 모르는 값은 None(0 이 아니다). 데이터 날짜를 같이 돌려준다 — 일봉은 Actions 지연으로 전일까지다.

출처(docs/data, ui/data): prices.json(일봉 250) · trade-levels.json(ATR14) · stock-context.json(증권사 목표가) ·
latest.json(점수·PBR) · sector-strength.json(업종 대분류) · positions.json(모의 PBR 슬리브 보유). 장중 현재가는 호출자가 넘긴다.
"""
from __future__ import annotations

import json
import statistics
from pathlib import Path
from typing import Dict, List, Optional

from .config import REPO_ROOT

STOP_ATR = 3.0            # 연구 변형 C
REWARD_RISK = 1.5         # 연구 변형 C
ZONE_PCT = 1.0            # 체결 여유(규칙 아님)
PBR_SLEEVE = "pbr_value_v1_combined"
RULE_NOTE = ("손절 = 진입 상단 − 3×ATR, 목표 = 진입 상단 + 1.5×손절폭. PBR 포트폴리오 연구에서 시험한 값이다 — 최대 낙폭은 줄었고, "
             "마지막 25% 구간 연수익은 손절 없이 들고 간 쪽보다 낮았다(4.75% 대 5.50%). 한 종목을 골라 매매할 때의 성과는 검증되지 않았다. "
             "진입 구간(현재가 −1%~현재가)은 체결 여유일 뿐 규칙이 아니다. 투자 자문이 아니라 규칙 계산값이다.")

_cache: Dict[Path, tuple] = {}


def _load(rel: str, root: Path = REPO_ROOT):
    """파일이 바뀔 때만 다시 읽는다(prices.json 16MB)."""
    p = root / rel
    try:
        m = p.stat().st_mtime
    except OSError:
        return None
    hit = _cache.get(p)
    if hit and hit[0] == m:
        return hit[1]
    try:
        d = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    _cache[p] = (m, d)
    return d


def _kr_prices(root: Path) -> Dict[str, dict]:
    d = _load("docs/data/prices.json", root) or {}
    return {k: v for k, v in (d.get("byTicker") or {}).items() if v.get("market") == "KR" and v.get("c")}


def search(q: str, root: Path = REPO_ROOT, limit: int = 10) -> List[tuple]:
    """종목코드(정확히) 또는 이름 일부 → [(코드, 이름)]. 관심종목 국내만(가격 데이터가 있는 종목)."""
    q = (q or "").strip()
    if not q:
        return []
    px = _kr_prices(root)
    if q.upper() in px:
        return [(q.upper(), px[q.upper()].get("name", ""))]
    ql = q.lower()
    hits = [(k, v.get("name", "")) for k, v in px.items() if ql in str(v.get("name", "")).lower()]
    hits.sort(key=lambda x: (not x[1].lower().startswith(ql), len(x[1]), x[0]))    # 앞글자 일치·짧은 이름 먼저
    return hits[:limit]


def levels(price: float, atr: Optional[float]) -> Optional[dict]:
    """규칙 계산값. ATR 을 모르면 None — 손절 폭을 지어내지 않는다."""
    if not price or not atr or atr <= 0:
        return None
    hi = round(price)
    lo = round(price * (1 - ZONE_PCT / 100))
    stop = round(hi - STOP_ATR * atr)
    target = round(hi + REWARD_RISK * (hi - stop))
    if stop <= 0:
        return None
    return {"entryLow": lo, "entryHigh": hi, "stop": stop, "target": target,
            "stopPct": (stop / hi - 1) * 100, "targetPct": (target / hi - 1) * 100}


def build_card(code: str, intraday: Optional[dict] = None, root: Path = REPO_ROOT) -> Optional[dict]:
    """intraday = /kr-intraday 응답(오늘 날짜인 것만 넘긴다). 가격 데이터가 없는 종목이면 None."""
    px = _kr_prices(root).get(code)
    if not px:
        return None
    closes, highs, lows, days = px["c"], px["h"], px["l"], px["d"]
    q = ((intraday or {}).get("quotes") or {}).get(code)
    if q and q[0]:
        price, src = float(q[0]), f"장중 {str((intraday or {}).get('atKst', ''))[11:16]}"
    else:
        price, src = float(closes[-1]), f"종가 {days[-1][:4]}-{days[-1][4:6]}-{days[-1][6:]}"

    def chg(n):
        return (price / closes[-1 - n] - 1) * 100 if len(closes) > n and closes[-1 - n] else None

    def ma(n):
        return sum(closes[-n:]) / n if len(closes) >= n else None

    hi52, lo52 = max(highs), min(lows)
    tl = ((_load("docs/data/trade-levels.json", root) or {}).get("byTicker") or {}).get(code) or {}
    atr = tl.get("atr14")
    tg = (((_load("docs/data/stock-context.json", root) or {}).get("targets") or {}).get("byTicker") or {}).get(code) or {}
    res = [r for r in ((_load("docs/data/latest.json", root) or {}).get("results") or []) if r.get("market", "KR") == "KR"]

    def pbr_of(r):
        v = (((r.get("breakdown") or {}).get("valuation") or {}).get("detail") or {}).get("pbr") or {}
        return v.get("raw") if isinstance(v.get("raw"), (int, float)) and v.get("raw") > 0 else None

    me = next((r for r in res if r.get("ticker") == code), None)
    pbr = pbr_of(me) if me else None
    allp = sorted(x for x in (pbr_of(r) for r in res) if x is not None)
    pbr_pct = (sum(1 for x in allp if x < pbr) / len(allp) * 100) if pbr and allp else None     # 0 = 가장 쌈
    groups = {s["t"]: s.get("g") for s in ((_load("docs/data/sector-strength.json", root) or {}).get("stocks") or [])}
    grp = groups.get(code)
    peers = [pbr_of(r) for r in res if grp and groups.get(r.get("ticker")) == grp]
    peers = [x for x in peers if x is not None]
    sec_med = statistics.median(peers) if len(peers) >= 5 else None                             # 5종목 미만 업종은 중앙값을 안 낸다
    sleeve = (((_load("ui/data/positions.json", root) or {}).get("strategies") or {}).get(PBR_SLEEVE) or {}).get("positions") or []
    held = any(p.get("symbol") == code and p.get("status") == "OPEN" for p in sleeve)
    return {
        "code": code, "name": px.get("name", ""), "price": price, "priceSrc": src, "dailyAsOf": days[-1],
        "chg1d": chg(1) if not q else ((price / q[1] - 1) * 100 if q[1] else None), "chg1w": chg(5), "chg1m": chg(21),
        "ma20": ma(20), "ma60": ma(60), "hi52": hi52, "lo52": lo52,
        "pos52": (price - lo52) / (hi52 - lo52) * 100 if hi52 > lo52 else None,
        "atr": atr, "atrPct": (atr / price * 100) if atr else None, "atrAsOf": tl.get("asOf"),
        "target": tg if tg.get("status") == "ok" else None,
        "score": {"total": me.get("totalScore"), "grade": me.get("grade"),
                  "coverage": (me.get("dataCoverage") or {}).get("overall")} if me else None,
        "pbr": pbr, "pbrPct": pbr_pct, "sector": grp, "sectorPeers": len(peers), "sectorMedianPbr": sec_med,
        "sectorFairPrice": price * sec_med / pbr if pbr and sec_med else None,
        "pbrSleeve": held, "levels": levels(price, atr),
    }


def checks(card: Optional[dict], lo: float, hi: float, stop: float, target: float) -> List[tuple]:
    """입력값 점검 — (등급, 문구). 등급: warn | info. 숫자를 대신 정하지 않고, 적은 숫자가 평소 흔들림·기준선에 비해 어떤지만."""
    out: List[tuple] = []
    if not card:
        return [("warn", "이 종목은 가격 데이터가 없어 점검할 수 없다(관심종목 국내만)")]
    price, atr = card["price"], card.get("atr")
    if lo <= price <= hi:
        out.append(("warn", f"지금 가격 {price:,.0f} 이 진입 구간 안 — 저장하면 다음 점검(5분, 장중)에 바로 살 수 있다"))
    elif price > hi:
        out.append(("info", f"지금 가격이 진입 상단보다 {(price / hi - 1) * 100:.1f}% 위 — 내려와야 산다"))
    if atr:
        k = (hi - stop) / atr
        if k < 1:
            out.append(("warn", f"손절 폭이 하루 평균 변동폭의 {k:.1f}배 — 평소 흔들림만으로 걸릴 수 있다"))
        else:
            out.append(("info", f"손절 폭 = 하루 평균 변동폭(ATR {atr:,.0f})의 {k:.1f}배 (연구 변형 C 는 3배)"))
    else:
        out.append(("warn", "ATR 을 모른다 — 손절 폭이 평소 흔들림 대비 어떤지 점검 못 함"))
    if card.get("hi52") and target > card["hi52"]:
        out.append(("info", f"목표가가 52주 고점 {card['hi52']:,.0f} 보다 위"))
    t = card.get("target")
    if t and target > t["median"]:
        out.append(("info", f"목표가가 증권사 목표가 중앙값 {t['median']:,.0f}({t['brokers']}개사) 보다 위"))
    if card.get("score") and (card["score"].get("coverage") or 0) < 0.6:
        out.append(("info", "점수 데이터 커버리지 60% 미만 — 등급 '유보' 수준"))
    return out


def context_for_plan(card: Optional[dict]) -> dict:
    """계획 저장 때 같이 남기는 당시 상태 — 30건 뒤 '손절을 몇 ATR 로 둔 계획이 나았나'를 내 데이터로 보려고."""
    if not card:
        return {}
    return {k: card.get(k) for k in ("price", "priceSrc", "atr", "atrPct", "pos52", "pbr", "pbrPct", "sector", "pbrSleeve")}
