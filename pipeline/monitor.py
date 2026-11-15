"""S5 무효 조건 점검 — 반증이 쓴 조건을 코드가 매일 본다. 순수 함수. 계약: docs/AGENT_SPEC.md §3.5.

닿으면 기록과 알림 1회. 주문은 내지 않는다. manual 은 점검하지 않는다(닿았다고도 안 닿았다고도 적지 않는다).
잴 자료가 모자라면 UNKNOWN 이다 — 모르는 것을 '안 닿음'으로도 '닿음'으로도 치지 않는다(호출한 쪽이 계산 불가로 센다).
"""
from __future__ import annotations

from typing import List, Optional, Tuple

WINDOW = 60          # 후보일 뒤 60거래일까지만 본다
UNKNOWN = "unknown"  # 자료 부족


def check(c: dict, *, closes: List[Tuple[str, float]], signal_day: str, risk_states: List[str],
          final_score: Optional[float], runs_missed: int):
    """→ 닿았으면 observed(dict), 안 닿았으면 None, 잴 수 없으면 UNKNOWN.

    closes: 그 종목의 (일자, 종가) 오름차순, 오늘까지. runs_missed: 최근 연속으로 후보에서 빠진 실행 수.
    """
    k = c["kind"]
    if k == "risk-state-added":
        return {"riskStates": sorted(risk_states)} if risk_states else None
    if k == "score-below":
        if final_score is None:
            return UNKNOWN
        return {"finalScore": final_score} if final_score < c["value"] else None
    if k == "candidate-dropped":
        return {"runsMissed": runs_missed} if runs_missed >= c["days"] else None
    px = [x for _, x in closes]
    if k == "drawdown-from-signal":
        base = next((x for d, x in closes if d == signal_day), None)
        if not base or not px:
            return UNKNOWN
        dd = round((px[-1] / base - 1) * 100, 6)                  # 144/160 이 −9.9999…% 로 나와 정확히 −10% 를 놓치지 않게
        return {"signalClose": base, "close": px[-1], "pct": round(dd, 2)} if dd <= -c["pct"] else None
    if k == "close-below-ma":
        ma, days = c["ma"], c["days"]
        if len(px) < ma + days - 1:
            return UNKNOWN
        if sum(1 for d, _ in closes if d > signal_day) < days:    # 후보일 뒤의 마감만 센다
            return None
        mas = [sum(px[i - ma + 1:i + 1]) / ma for i in range(len(px) - days, len(px))]
        if all(x < m for x, m in zip(px[-days:], mas)):
            return {"closes": px[-days:], f"ma{ma}": round(mas[-1], 2)}
        return None
    return None                                                   # manual
