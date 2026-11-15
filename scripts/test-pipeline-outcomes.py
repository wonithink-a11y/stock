#!/usr/bin/env python3
"""사건 구분 · 무효 조건 점검 · 사후 평가 · 화면 파일 회귀 — 네트워크 없음. 기준: docs/VALIDATION.md §5.

핀하는 것: 같은 종목 연속 후보는 첫 날만 사건(5회 연속 탈락 뒤 재진입은 새 사건) · 무효 조건 종류마다 닿음/안 닿음 경계 ·
자료 부족은 '모름'(닿음도 안 닿음도 아님) · 진입은 기록 다음 거래일 종가 · 정지·시세 없음은 ret null ·
만기 전에는 재지 않고 이미 잰 것은 다시 재지 않는다 · 판정 잠김 · 화면 파일 결정적(갈래별 평균 수익 없음) · 알림 문구.

    python scripts/test-pipeline-outcomes.py
"""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from pipeline import events as E                                               # noqa: E402
from pipeline import monitor as M                                              # noqa: E402
from pipeline import outcomes as O                                             # noqa: E402
from pipeline import view as V                                                 # noqa: E402
from pipeline.__main__ import message                                          # noqa: E402

failed = 0
CODE = {"kind": "code", "name": "pipeline.candidates", "version": "CR-1.0"}
LLM = {"kind": "llm", "name": "pipeline.agents", "version": "1", "model": "m", "promptVersion": "v1"}
DAYS = [f"202611{d:02d}" for d in range(2, 31)] + [f"202612{d:02d}" for d in range(1, 31)] + [f"202701{d:02d}" for d in range(1, 31)]


def ok(cond, label):
    global failed
    if not cond:
        failed += 1
        print(f"  FAIL {label}")


def cand(ticker, as_of, rank=1):
    sid = E.cand_id(as_of, "CR-1.0", ticker)
    return E.make("CANDIDATE_SELECTED", event_id=sid, ticker=ticker, market="KR",
                  occurred_at=f"{as_of[:4]}-{as_of[4:6]}-{as_of[6:]}T20:45:00+09:00", as_of=as_of, producer=CODE, signal_id=sid,
                  evidence_ids=[f"score:{as_of}:{ticker}"],
                  payload={"ruleVersion": "CR-1.0", "rank": rank, "of": 20, "eligible": 300, "finalScore": 80.0, "rawScore": 80.0,
                           "riskPenalty": 0, "coverage": 90.0, "enginePolicies": {}, "inputSha256": "ab" * 32})


def main():
    # ---- 사건 구분
    runs = DAYS[:12]
    cs = [cand("000001", d) for d in runs[:3]] + [cand("000001", runs[4])] + [cand("000001", runs[10])] \
        + [cand("000002", d, 2) for d in runs]
    starts = E.episode_starts(cs)
    ok(starts == {E.cand_id(runs[0], "CR-1.0", "000001"), E.cand_id(runs[10], "CR-1.0", "000001"),
                  E.cand_id(runs[0], "CR-1.0", "000002")}, f"첫 날만 사건 · 하루 빠진 건 같은 사건 · 5회 탈락 뒤 새 사건: {sorted(starts)}")

    # ---- 무효 조건
    up = [(d, 100.0 + i) for i, d in enumerate(DAYS[:70])]
    base = dict(closes=up, signal_day=DAYS[60], risk_states=[], final_score=80.0, runs_missed=0)
    chk = lambda c, **kw: M.check(c, **{**base, **kw})                                    # noqa: E731
    ok(chk({"kind": "risk-state-added"}) is None and chk({"kind": "risk-state-added"}, risk_states=["B", "A"]) == {"riskStates": ["A", "B"]}, "위험 상태")
    ok(chk({"kind": "score-below", "value": 80}) is None and chk({"kind": "score-below", "value": 80.1}) == {"finalScore": 80.0}
       and chk({"kind": "score-below", "value": 90}, final_score=None) == M.UNKNOWN, "점수 아래 경계 · 점수 모름")
    ok(chk({"kind": "candidate-dropped", "days": 5}, runs_missed=4) is None and chk({"kind": "candidate-dropped", "days": 5}, runs_missed=5), "후보 탈락 경계")
    dn = up[:61] + [(DAYS[61], 144.1), (DAYS[62], 144.0)]                                # 후보일 종가 160 → −10%
    ok(chk({"kind": "drawdown-from-signal", "pct": 10}, closes=dn[:62]) is None
       and chk({"kind": "drawdown-from-signal", "pct": 10}, closes=dn)["pct"] == -10.0, "낙폭 경계(−10% 이하에서 닿음)")
    ok(chk({"kind": "drawdown-from-signal", "pct": 10}, signal_day="20250101") == M.UNKNOWN, "후보일 종가 모름")
    ma = {"kind": "close-below-ma", "ma": 20, "days": 3}
    fall = up[:61] + [(d, 50.0) for d in DAYS[61:64]]
    ok(chk(ma) is None and chk(ma, closes=fall)["closes"] == [50.0] * 3 and chk(ma, closes=fall[:-1]) is None, "이평 아래 3일 — 2일째는 아직")
    ok(chk(ma, closes=up[:10]) == M.UNKNOWN, "이평 계산에 일봉 부족 → 모름")
    ok(chk(ma, closes=[(d, 200.0 - i) for i, d in enumerate(DAYS[:61])]) is None, "후보일 전의 이탈은 세지 않는다")
    ok(chk({"kind": "manual"}) is None, "manual 은 점검 안 함")

    # ---- 사후 평가: 달력 = 005930. 후보 기록일 20261102(월) → 진입 20261103
    def px(mult, vol=1000, market="KR", days=DAYS):
        return {"market": market, "name": "n", "d": list(days), "c": [100.0 * (mult ** i) for i in range(len(days))], "v": [vol] * len(days)}
    prices = {"005930": px(1.0), "000001": px(1.01), "000003": px(1.0), "AAPL": px(2.0, market="US")}
    c = cand("000001", DAYS[0])
    at = "2027-02-01T20:45:00+09:00"
    outs = O.measure(c, prices, at, set())
    p5 = outs[0]["payload"]
    ok([o["payload"]["horizon"] for o in outs] == [5, 20, 60], "세 만기")
    ok(p5["entryDate"] == DAYS[1] and p5["exitDate"] == DAYS[6], f"진입은 기록 다음 거래일: {p5['entryDate']}")
    exp = 1.01 ** 5 - 1
    ok(abs(p5["ret"] - exp) < 1e-6 and abs(p5["benchRet"] - exp / 3) < 1e-6 and p5["benchmark"] == "KR_WATCHLIST_EW", "수익·기준 수익(KR 만 평균)")
    ok(abs(p5["netExcess"] - (p5["excess"] - 0.00335)) < 1e-6 and p5["costBp"] == 33.5, "비용 33.5bp")
    ok(O.measure(c, prices, at, {outs[0]["eventId"]})[0]["payload"]["horizon"] == 20, "이미 잰 만기는 다시 안 잰다")
    short = {k: {**v, "d": v["d"][:8], "c": v["c"][:8], "v": v["v"][:8]} for k, v in prices.items()}
    ok([o["payload"]["horizon"] for o in O.measure(c, short, at, set())] == [5], "만기 전에는 재지 않는다")
    ok(O.measure(cand("000001", DAYS[-1]), prices, at, set()) == [], "다음 거래일이 없으면 0건")
    halted = dict(prices, **{"000001": px(1.01, vol=0)})
    h = O.measure(c, halted, at, set())[0]["payload"]
    ok(h["status"] == "halted" and h["ret"] is None and h["excess"] is None and h["benchRet"] is not None, "정지 → ret null(0 아님)")
    gone = O.measure(cand("000009", DAYS[0]), prices, at, set())[0]["payload"]
    ok(gone["status"] == "no-price" and gone["ret"] is None and gone["entryPx"] is None, "시세 없음 → ret null")
    try:
        O.judge()
        ok(False, "판정이 열려 있다")
    except SystemExit:
        pass

    # ---- 화면 파일
    th = E.make("THESIS_WRITTEN", event_id=E.thesis_id(c["eventId"], "v1", "m"), ticker="000001", market="KR",
                occurred_at="2026-11-02T20:50:00+09:00", as_of=DAYS[0], producer=LLM, signal_id=c["eventId"],
                evidence_ids=[f"score:{DAYS[0]}:000001"],
                payload={"bundleSha256": "cd" * 32, "summary": "s", "claims": [{"id": "T1", "kind": "quality", "claim": "c", "quote": "q",
                                                                              "evidenceId": f"score:{DAYS[0]}:000001"}],
                         "verification": {"claimsTotal": 1, "claimsKept": 1, "dropped": []}})
    rb = E.make("REBUTTAL_WRITTEN", event_id=E.rebut_id(c["eventId"], "v1", "m"), ticker="000001", market="KR",
                occurred_at="2026-11-02T20:51:00+09:00", as_of=DAYS[0], producer=LLM, signal_id=c["eventId"], evidence_ids=[th["eventId"]],
                payload={"bundleSha256": "cd" * 32, "thesisEventId": th["eventId"], "counters": [], "flag": "none",
                         "invalidations": [{"id": "I1", "text": "10% 하락", "check": {"kind": "drawdown-from-signal", "pct": 10}}],
                         "verification": {"countersTotal": 0, "countersKept": 0, "dropped": []}})
    log = [c, cand("000001", DAYS[1]), cand("000002", DAYS[1], 2), th, rb] + outs
    v = V.build(log, {"000001": "가나", "000002": "다라"})
    ok(v["asOf"] == DAYS[1] and [(x["ticker"], x["isNew"]) for x in v["today"]] == [("000001", False), ("000002", True)], "오늘 후보·새 사건 표시")
    ok(v["today"][0]["episodeSignalId"] == c["eventId"], "이어지는 후보는 사건의 첫 날을 가리킨다")
    ok(v["counts"]["episodes"] == 2 and v["counts"]["flags"] == {"none": 1, "미기록": 1} and v["counts"]["outcomes"]["h20:ok"] == 1, f"건수: {v['counts']}")
    ep = [e for e in v["episodes"] if e["signalId"] == c["eventId"]][0]
    ok(ep["rebuttal"]["invalidations"][0]["triggeredAt"] is None and set(ep["outcomes"]) == {"h5", "h20", "h60"}, "사건 상세")
    dump = json.dumps(v, ensure_ascii=False, sort_keys=True)
    ok(dump == json.dumps(V.build(list(reversed(log)), {"000001": "가나", "000002": "다라"}), ensure_ascii=False, sort_keys=True), "입력 순서와 무관(결정적)")
    ok(not any(k in dump for k in ("meanExcess", "avgExcess", "winRate")), "갈래별 평균 수익은 싣지 않는다")
    ok(V.build([], {})["today"] == [], "빈 로그")

    # ---- 알림
    msg = message(v, {"monitor": {"triggered": [{"ticker": "000001", "name": "가나", "text": "10% 하락"}]}})
    ok("새 사건 1" in msg and "다라(000002)" in msg and "(주석 없음)" in msg and "✖ 가나(000001) — 10% 하락" in msg, f"알림 문구: {msg}")
    quiet = V.build([c, cand("000001", DAYS[1])], {})
    ok(message(quiet, {}) == "", "새 사건·닿음이 없으면 알림 없음")

    print(f"test-pipeline-outcomes: {'FAIL ' + str(failed) if failed else 'ok'}")
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
