#!/usr/bin/env python3
"""파이프라인 기록(AE-1.0) 회귀 — 네트워크·키 없이 돈다. 기준: docs/VALIDATION.md §5.

핀하는 것: 봉투 검증(필수 필드·UTC 시각·미래 asOf·모르는 type·선언 안 된 payload 키·논리/반증의 contextOnly) ·
eventId 멱등(두 번째 쓰기 거부) · **늦게 온 기록도 쓰인다**(커서 멱등이었다면 사라졌을 경우) · sortKey(occurredAt 과 일치,
같은 날 공시 키가 앞) · 무효 조건 닫힌 목록 · 실패 주입(아무것도 안 쓴다) · 접기.

    python scripts/test-pipeline-events.py
"""
import copy
import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from pipeline import events as E                                              # noqa: E402

failed = 0


def ok(cond, label):
    global failed
    if not cond:
        failed += 1
        print(f"  FAIL {label}")


def rejects(e, label):
    try:
        E.validate(e)
    except ValueError:
        return
    ok(False, f"거부해야 한다: {label}")


CODE = {"kind": "code", "name": "pipeline.candidates", "version": "CR-1.0"}
LLM = {"kind": "llm", "name": "pipeline.agents", "version": "1", "model": "gemini-3.5-flash-lite", "promptVersion": "v1"}


def cand(ticker="005930", at="2026-11-16T20:45:12+09:00", as_of="20261116"):
    sid = E.cand_id(as_of, "CR-1.0", ticker)
    return E.make("CANDIDATE_SELECTED", event_id=sid, ticker=ticker, market="KR", occurred_at=at, as_of=as_of,
                  producer=CODE, signal_id=sid, evidence_ids=[f"score:{as_of}:{ticker}", f"state:{ticker}"],
                  payload={"ruleVersion": "CR-1.0", "rank": 3, "of": 20, "eligible": 341, "finalScore": 71.4,
                           "rawScore": 73.4, "riskPenalty": 2.0, "coverage": 89.5,
                           "enginePolicies": {"criteria": "2.4"}, "inputSha256": "ab" * 32})


def thesis(c, at="2026-11-16T20:50:00+09:00"):
    return E.make("THESIS_WRITTEN", event_id=E.thesis_id(c["eventId"], "v1", LLM["model"]), ticker=c["ticker"],
                  market="KR", occurred_at=at, as_of=c["asOf"], producer=LLM, signal_id=c["eventId"],
                  evidence_ids=[f"score:{c['asOf']}:{c['ticker']}"],
                  payload={"bundleSha256": "cd" * 32, "summary": "T1",
                           "claims": [{"id": "T1", "kind": "quality", "claim": "c", "quote": "q",
                                       "evidenceId": f"score:{c['asOf']}:{c['ticker']}"}],
                           "verification": {"claimsTotal": 2, "claimsKept": 1,
                                            "dropped": [{"id": "T2", "why": "quote-not-found"}]}})


def rebuttal(c, th, check, at="2026-11-16T20:51:00+09:00"):
    return E.make("REBUTTAL_WRITTEN", event_id=E.rebut_id(c["eventId"], "v1", LLM["model"]), ticker=c["ticker"],
                  market="KR", occurred_at=at, as_of=c["asOf"], producer=LLM, signal_id=c["eventId"],
                  evidence_ids=[th["eventId"]],
                  payload={"bundleSha256": "cd" * 32, "thesisEventId": th["eventId"], "counters": [],
                           "invalidations": [{"id": "I1", "text": "60일선 이탈", "check": check}], "flag": "caution",
                           "verification": {"countersTotal": 0, "countersKept": 0, "dropped": []}})


def mut(e, **kw):
    x = copy.deepcopy(e)
    for k, v in kw.items():
        if k.startswith("p_"):
            x["payload"][k[2:]] = v
        else:
            x[k] = v
    return x


def main():
    c = cand()
    th = thesis(c)
    rb = rebuttal(c, th, {"kind": "close-below-ma", "ma": 60, "days": 5})

    # 봉투
    ok(c["sortKey"] == "20261116T204512:20:005930:00" and c["contextOnly"] is False, "후보 sortKey·contextOnly")
    ok(th["contextOnly"] is True and th["sourceTeam"] == "thesis" and rb["sortKey"].split(":")[1] == "40", "논리·반증 봉투")
    for k in E.ENVELOPE:
        x = copy.deepcopy(c)
        del x[k]
        rejects(x, f"필수 필드 누락 {k}")
    rejects(mut(c, extra=1), "모르는 봉투 키")
    rejects(mut(c, occurredAt="2026-11-16T11:45:12Z"), "UTC 시각")
    rejects(mut(c, occurredAt="2026-11-16T20:45:12"), "오프셋 없는 시각")
    rejects(mut(c, asOf="20261117"), "미래 asOf")
    rejects(mut(c, type="SCORE_ADJUSTED"), "모르는 type")
    rejects(mut(c, sortKey="20261116T204513:20:005930:00"), "sortKey 가 occurredAt 과 불일치")
    rejects(mut(c, sortKey="20261116T204512:30:005930:00"), "sortKey 단계 불일치")
    rejects(mut(c, ticker="02180"), "5자리 ticker")
    ok(cand("0218L0")["ticker"] == "0218L0", "영숫자 ticker 통과")
    rejects(mut(c, evidenceIds=[]), "빈 evidenceIds")
    rejects(mut(c, evidenceIds=["memo:1"]), "모르는 근거 접두사")
    rejects(mut(c, p_finalScore=None), "null 점수 후보")
    rejects(mut(c, p_note="x"), "선언 안 된 payload 키")
    rejects(mut(c, signalId="cand:other"), "후보 signalId 불일치")
    rejects(mut(c, contextOnly=True), "코드 단계의 contextOnly=true")
    rejects(mut(c, producer=LLM), "코드 단계에 llm producer")

    # 점수 불반영(겹 2)
    rejects(mut(th, contextOnly=False), "논리의 contextOnly=false")
    for k in ("score", "weight", "rank", "confidence", "targetPrice", "action"):
        rejects(mut(th, **{f"p_{k}": 1}), f"논리 payload 에 {k}")
        rejects(mut(rb, **{f"p_{k}": 1}), f"반증 payload 에 {k}")
    rejects(mut(rb, p_flag=0.8), "숫자 깃발")
    rejects(mut(th, p_claims=[]), "빈 claims")
    rejects(mut(th, p_verification={"claimsTotal": 1, "claimsKept": 5, "dropped": []}), "검증 건수 불일치")
    rejects(mut(th, producer=CODE), "논리에 code producer")
    rejects(mut(th, producer={k: v for k, v in LLM.items() if k != "promptVersion"}), "promptVersion 없는 llm")

    # 무효 조건 닫힌 목록
    ok(E.check_ok({"kind": "close-below-ma", "ma": 60, "days": 5}) and E.check_ok({"kind": "manual"}), "목록 안 조건")
    for bad in ({"kind": "close-below-ma", "ma": 50, "days": 5}, {"kind": "close-below-ma", "ma": 60, "days": 11},
                {"kind": "rsi-below", "value": 30}, {"kind": "score-below"}, {"kind": "manual", "x": 1}, "manual"):
        ok(not E.check_ok(bad), f"목록 밖 조건 {bad}")
        ok(E.normalize_check(bad) == {"kind": "manual"}, f"manual 로 강등 {bad}")
    rejects(mut(rb, p_invalidations=[{"id": "I1", "text": "t", "check": {"kind": "rsi-below"}}]), "기록 안의 목록 밖 조건")
    rejects(mut(rb, p_invalidations=[]), "counters·invalidations 둘 다 빔")

    # 닿음·사후 평가
    iv = E.make("INVALIDATION_TRIGGERED", event_id=E.inval_id(rb["eventId"], "I1"), ticker="005930", market="KR",
                occurred_at="2026-12-02T20:45:00+09:00", as_of="20261202", producer={**CODE, "name": "pipeline.monitor"},
                signal_id=c["eventId"], evidence_ids=[rb["eventId"], "px:20261202:005930"],
                payload={"rebuttalEventId": rb["eventId"], "invalidationId": "I1",
                         "check": {"kind": "close-below-ma", "ma": 60, "days": 5}, "observed": {}, "daysSinceSignal": 12})
    rejects(mut(iv, p_check={"kind": "manual"}), "manual 닿음")
    base = {"horizon": 20, "entryDate": "20261117", "exitDate": "20261215", "entryPx": 100.0, "exitPx": 104.0,
            "ret": 0.04, "benchmark": "KOSPI", "benchRet": 0.01, "excess": 0.03, "costBp": 33.5, "netExcess": 0.02665,
            "status": "ok"}

    def outcome(**kw):
        return E.make("OUTCOME_MEASURED", event_id=E.out_id(c["eventId"], 20), ticker="005930", market="KR",
                      occurred_at="2027-01-04T20:45:00+09:00", as_of="20270104", producer={**CODE, "name": "pipeline.outcomes"},
                      signal_id=c["eventId"], evidence_ids=["px:20270104:005930"], payload={**base, **kw})
    oc = outcome()
    rejects(mut(oc, p_ret=None), "ok 인데 ret 없음")
    rejects(mut(oc, p_status="halted"), "정지인데 ret 을 숫자로(0 채움 방지)")
    rejects(mut(oc, p_horizon=10), "모르는 만기")
    ok(outcome(status="delisted", ret=None, exitPx=None, excess=None, netExcess=None)["payload"]["ret"] is None,
       "폐지는 ret null")

    # 로그 — 멱등 · 늦게 온 기록 · 해 넘김 · 실패 주입
    with tempfile.TemporaryDirectory() as d:
        root = Path(d) / "events"
        ok(E.read(root) == [], "없는 로그는 빈 목록")
        ok(E.append([c, rb], root) == {"written": 2, "duplicates": 0}, "첫 쓰기")
        ok(E.append([c], root) == {"written": 0, "duplicates": 1}, "같은 eventId 두 번째는 거부")
        ok(th["sortKey"] < rb["sortKey"], "논리는 이미 쓰인 반증보다 앞 시각")
        ok(E.append([th], root) == {"written": 1, "duplicates": 0}, "늦게 온(sortKey 가 더 작은) 기록도 쓰인다")
        ok([e["type"] for e in E.read(root)] == ["CANDIDATE_SELECTED", "THESIS_WRITTEN", "REBUTTAL_WRITTEN"], "읽기는 sortKey 순")
        ok(len((root / "2026" / "005930.jsonl").read_text(encoding="utf-8").splitlines()) == 3, "한 줄에 한 기록")
        ok(E.append([oc, iv], root) == {"written": 2, "duplicates": 0} and (root / "2027" / "005930.jsonl").exists(), "연도 분할")
        later = outcome()
        later["occurredAt"] = "2028-01-03T20:45:00+09:00"
        later["asOf"], later["sortKey"] = "20280103", E.sort_key(later["occurredAt"], "60", "005930")
        ok(E.append([later], root) == {"written": 0, "duplicates": 1} and not (root / "2028").exists(), "해를 넘긴 같은 eventId 도 거부")
        try:
            E.append([cand("000660"), mut(c, asOf="20261117")], root)
            ok(False, "묶음 안 하나가 틀리면 전체 거부")
        except ValueError:
            ok(E.read(root, "000660") == [], "틀린 묶음은 아무것도 안 쓴다")
        os.environ["PIPELINE_FAIL_INJECTION"] = "gate-test"
        try:
            E.append([cand("000660")], root)
            ok(False, "실패 주입이 통과했다")
        except RuntimeError:
            ok(E.read(root, "000660") == [], "실패 주입 — 아무것도 안 쓴다")
        finally:
            del os.environ["PIPELINE_FAIL_INJECTION"]

        f = E.fold(E.read(root))[c["eventId"]]
        ok(f["candidate"]["eventId"] == c["eventId"] and len(f["thesis"]) == 1 and len(f["rebuttal"]) == 1
           and len(f["invalidations"]) == 1 and list(f["outcomes"]) == [20], "접기")

    # 공시 키와 섞어 정렬 — 같은 날 공시가 앞
    dart = "20261116:20261116000123:00"
    ok(sorted([c["sortKey"], dart]) == [dart, c["sortKey"]] and sorted([c["sortKey"], "20261117:2026:00"])[0] == c["sortKey"],
       "같은 날 공시 sortKey 가 앞, 다음 날 공시는 뒤")

    print(f"test-pipeline-events: {'FAIL ' + str(failed) if failed else 'ok'}")
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
