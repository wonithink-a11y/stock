#!/usr/bin/env python3
"""후보 규칙 CR-1.0 회귀 — 네트워크 없음. 기준: docs/VALIDATION.md §5 '후보 규칙'.

핀하는 것: 고정 입력 → 고정 20종목(동률은 ticker 순) · finalScore null 은 제외(0 취급 아님) · 위험 상태·낮은 신뢰도·
거래 불가 제외 · 낡은 dataCutoff → 후보 0 + 진단 사유 · 같은 날 재실행은 추가 0줄(중복 20).

    python scripts/test-pipeline-candidates.py
"""
import sys
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from pipeline import candidates as C                                           # noqa: E402
from pipeline import events as E                                               # noqa: E402

KST = timezone(timedelta(hours=9))
NOW = datetime(2026, 11, 16, 20, 45, 12, tzinfo=KST)
failed = 0


def ok(cond, label):
    global failed
    if not cond:
        failed += 1
        print(f"  FAIL {label}")


def row(ticker, score, market="KR", cutoff="20261116", **kw):
    res = {"ticker": ticker, "rawScore": score, "riskPenalty": 0, "finalScore": score, "tradeAllowed": True,
           "tradingState": "NORMAL", "flags": [], "confidence": {"coverage": 90.0}}
    res.update(kw)
    return {"market": market, "meta": {"dataCutoff": cutoff, "policies": {"criteria": "2.4"}}, "result": res}


def main():
    # 30종목: 점수 100, 99, … — 그중 일부를 깨뜨린다
    rows = [row(f"{i:06d}", 100 - i) for i in range(1, 31)]
    rows[0]["result"]["finalScore"] = None                      # 000001 null — 1위였을 종목
    rows[1]["result"]["tradeAllowed"] = False                   # 000002
    rows[2]["result"]["flags"] = ["LOW_CONFIDENCE"]             # 000003
    rows[3]["result"]["tradingState"] = "HALTED"                # 000004
    rows[5]["meta"]["dataCutoff"] = "20261113"                  # 000006 혼자 낡음
    rows[6]["result"]["confidence"] = {"coverage": None}        # 000007 커버리지 모름
    rows[8]["result"]["finalScore"] = rows[7]["result"]["finalScore"]      # 000009 = 000008 동률
    rows.append(row("AAPL", 999, market="US"))
    rows.append(row("0218L0", 50.5))                            # 영숫자 코드
    states = {"000005": {"riskStates": ["MEZZANINE_ACTIVE"]}, "000010": {"riskStates": []}}
    data = {"results": rows}

    evs, d = C.select(data, "ab" * 32, states, NOW)
    tick = [e["ticker"] for e in evs]
    ok(len(evs) == 20 and d["candidates"] == 20, "20종목")
    ok(not {"000001", "000002", "000003", "000004", "000005", "000006", "000007", "AAPL"} & set(tick), "부적격 제외")
    ok(tick[:3] == ["000008", "000009", "000010"], f"점수 내림차순·동률은 ticker 순: {tick[:3]}")
    ok(d["excluded"] == {"low-confidence": 2, "null-score": 1, "risk-state": 1, "stale": 1, "trade-not-allowed": 1,
                         "trading-state": 1}, f"제외 사유 집계: {d['excluded']}")
    ok(d["universe"] == 31 and d["eligible"] == 24 and d["asOf"] == "20261116", "유니버스·적격 수")
    e = evs[0]
    ok(e["eventId"] == "cand:20261116:CR-1.0:000008" == e["signalId"] and e["payload"]["rank"] == 1
       and e["payload"]["of"] == 20 and e["payload"]["eligible"] == 24 and e["contextOnly"] is False, "후보 기록 모양")
    ok(e["evidenceIds"] == ["score:20261116:000008", "state:000008"], "근거 id")
    ok([x["payload"]["rank"] for x in evs] == list(range(1, 21)), "순위 1..20")
    evs2, _ = C.select({"results": list(reversed(rows))}, "ab" * 32, states, NOW)
    ok([x["eventId"] for x in evs2] == [x["eventId"] for x in evs], "입력 순서와 무관(결정적)")
    ok("0218L0" in [x["ticker"] for x in C.select(data, "s", states, NOW, n=30)[0]], "영숫자 ticker 가 후보가 된다")

    # 낡은 점수
    evs3, d3 = C.select(data, "s", states, NOW + timedelta(days=5))
    ok(evs3 == [] and d3["staleScoreSkip"] and "낡은" in d3["why"], "5일 낡은 점수 → 후보 0 + 사유")
    ok(len(C.select(data, "s", states, NOW + timedelta(days=3))[0]) == 20, "주말을 낀 3일은 통과")
    evs4, d4 = C.select({"results": []}, "s", {}, NOW)
    ok(evs4 == [] and d4["staleScoreSkip"], "빈 점수 파일 → 후보 0")
    ok(C.select(data, "s", states, NOW - timedelta(days=2))[1]["staleScoreSkip"], "기준일이 실행일보다 미래 → 거부")

    # 재실행 멱등
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        ok(E.append(evs, root) == {"written": 20, "duplicates": 0}, "첫 실행 20줄")
        again, _ = C.select(data, "ab" * 32, states, NOW + timedelta(hours=1))
        ok(E.append(again, root) == {"written": 0, "duplicates": 20}, "같은 날 재실행 → 추가 0, 중복 20")

    print(f"test-pipeline-candidates: {'FAIL ' + str(failed) if failed else 'ok'}")
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
