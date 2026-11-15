#!/usr/bin/env python3
"""근거 묶음 + 논리·반증 주석 회귀 — 네트워크·키 없음(가짜 LLM). 기준: docs/VALIDATION.md §5 '인용 대조'.

핀하는 것: 묶음 절 종류가 닫힌 목록(뉴스 본문·목표가 없음) · 기준일 뒤 자료 미수록 · 묶음 해시 결정적 ·
묶음에 없는 인용 탈락 · 다른 절의 인용 탈락 · claim 숫자가 인용에 없으면 탈락 · 통과 0건이면 기록 없음 ·
목록 밖 무효 조건은 manual 로 강등 · 근거 없는 깃발은 내린다 · 이미 쓴 후보는 다시 뽑지 않는다 ·
한도(429) 뒤 후보는 건너뛴다 · 지시문 파일 해시 핀 · LLM 출력의 점수·검증 칸은 기록에 못 들어간다.

    python scripts/test-pipeline-agents.py
"""
import hashlib
import io
import sys
import urllib.error
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from pipeline import agents as A                                               # noqa: E402
from pipeline import bundle as B                                               # noqa: E402
from pipeline import events as E                                               # noqa: E402

failed = 0
AT = "2026-11-16T20:50:00+09:00"
MODEL = "gemini-test"
# 지시문을 고치면 버전을 올린다(v2 파일을 새로 만든다) — 같은 버전 파일 수정 금지
PROMPT_SHA = {"thesis": "70a0e2caf48bc793a1d075ea9042c4fe95545f743c4f91bfd7091afc136d73b8", "rebuttal": "a332f666408e98f3140cb08f098ecce33df069ff0ecafd4d2f0c6555eb202709"}


def ok(cond, label):
    global failed
    if not cond:
        failed += 1
        print(f"  FAIL {label}")


def cand(ticker="005930", score=71.4):
    sid = E.cand_id("20261116", "CR-1.0", ticker)
    return E.make("CANDIDATE_SELECTED", event_id=sid, ticker=ticker, market="KR", occurred_at="2026-11-16T20:45:12+09:00",
                  as_of="20261116", producer={"kind": "code", "name": "pipeline.candidates", "version": "CR-1.0"},
                  signal_id=sid, evidence_ids=[f"score:20261116:{ticker}", f"state:{ticker}"],
                  payload={"ruleVersion": "CR-1.0", "rank": 3, "of": 20, "eligible": 341, "finalScore": score,
                           "rawScore": 73.4, "riskPenalty": 2.0, "coverage": 89.5, "enginePolicies": {},
                           "inputSha256": "ab" * 32})


def prices(n=120, last="20261116"):
    days = [f"2026{m:02d}{d:02d}" for m in range(5, 12) for d in range(1, 29)]
    days = [d for d in days if d <= last][-n:] + ["20261117"]            # 기준일 뒤 하루가 섞여 있다
    c = [1000 + i for i in range(len(days))]
    return {"d": days, "h": [x + 10 for x in c], "l": [x - 10 for x in c], "c": c}


QUOTE = "2026년 반기 TV의 평균 판매가격은 전년 연간 평균 대비 약 4% 하락하였으며, 스마트폰은 약 7% 상승하였습니다."
DECODE = {"rceptNo": "20260814003699", "reportNm": "반기보고서 (2026.06)", "items": [{"claim": "x", "quote": QUOTE}]}
HIST = [{"sortKey": "20261110:20261110000123:00", "occurredAt": "2026-11-10T00:00:00+09:00",
         "payload": {"rceptNo": "20261110000123", "reportNm": "단일판매ㆍ공급계약체결  "}},
        {"sortKey": "20260801:20260801000001:00", "occurredAt": "2026-08-01T00:00:00+09:00",
         "payload": {"rceptNo": "20260801000001", "reportNm": "옛 공시"}},
        {"sortKey": "20261117:20261117000009:00", "occurredAt": "2026-11-17T00:00:00+09:00",
         "payload": {"rceptNo": "20261117000009", "reportNm": "내일 공시"}}]
RESULT = {"name": "삼성전자", "components": {"fundamental": 6.8, "valuation": 8.8}, "topFactors": [{"factor": "valuation", "impact": 4.2}]}


def bundle(c=None, **kw):
    args = dict(result=RESULT, decode=DECODE, state={"riskStates": []}, history=HIST, prices=prices(),
                rank_h5={"asOf": "2026-11-14", "byTicker": {"005930": [87, 44]}})
    args.update(kw)
    return B.build(c or cand(), **args)


def main():
    c = cand()
    b = bundle(c)
    ids = [s["evidenceId"] for s in b["sections"]]
    ok({s["kind"] for s in b["sections"]} <= set(B.KINDS), "절 종류가 닫힌 목록")
    ok(ids == ["score:20261116:005930", "decode:005930:20260814003699#00", "dart:20261110000123", "state:005930",
               "px:20261116:005930", "ctx:rank-h5:20261114:005930"], f"절 구성: {ids}")
    px = b["sections"][4]["text"]
    ok("종가 1,119" in px or "종가 1119" in px.replace(",", ""), f"가격 사실은 기준일 종가(다음 날 값 아님): {px}")
    ok(bundle(c)["sha256"] == b["sha256"] and bundle(c, state={"riskStates": ["X"]})["sha256"] != b["sha256"], "해시 결정적")
    ok(not any("rank-h5" in s["evidenceId"] for s in bundle(c, rank_h5={"asOf": "2026-11-17", "byTicker": {"005930": [1, 1]}})["sections"]),
       "기준일 뒤 순위 자료 미수록")
    nb = bundle(c, decode=None, prices=prices(n=30))
    ok([s["kind"] for s in nb["sections"]].count("note") == 2, "해독·가격이 없으면 '없음' 절로 명시")
    ok(all(E.validate is not None and s["evidenceId"].split(":")[0] in E.EVIDENCE_PREFIXES for s in b["sections"] + nb["sections"]),
       "절 id 접두사가 계약 안")
    for name in ("thesis", "rebuttal"):
        sha = hashlib.sha256(A.prompt(name).replace("\r\n", "\n").encode("utf-8")).hexdigest()
        ok(sha == PROMPT_SHA[name], f"지시문 {name}.v1 해시 핀: {sha}")

    # 논리 — 인용 대조
    good = {"kind": "business", "claim": "TV 평균 판매가격이 약 4% 하락했다.", "quote": QUOTE[:45], "evidenceId": ids[1]}
    out = {"summary": "TV 가격이 4% 내렸다.", "score": 99, "verification": {"claimsKept": 99}, "claims": [
        good,
        {**good, "quote": "TV 평균 판매가격은 크게 상승하였습니다 전년 대비"},                    # 묶음에 없는 인용
        {**good, "evidenceId": "state:005930"},                                           # 다른 절의 인용
        {**good, "claim": "TV 평균 판매가격이 약 14% 하락했다."},                               # 인용에 없는 숫자
        {**good, "evidenceId": "news:abc"},                                               # 묶음에 없는 근거
        {**good, "kind": "rating"},                                                       # 목록 밖 종류
        {"kind": "quality", "claim": "원점수 73.4 에서 위험 감점 2.0 을 뺐다.", "quote": "최종 점수 71.4 = 원점수 73.4 − 위험 감점 2.0",
         "evidenceId": ids[0]}]}
    th = A.make_thesis(c, b, out, MODEL, AT)
    p = th["payload"]
    ok([x["id"] for x in p["claims"]] == ["T1", "T2"] and p["verification"]["claimsTotal"] == 7 and p["verification"]["claimsKept"] == 2, "통과 2 · 전체 7")
    ok([d["why"] for d in p["verification"]["dropped"]] == ["quote-not-found", "quote-not-found", "number-not-in-quote",
                                                            "evidence-id-unknown", "kind-unknown"], f"탈락 사유: {p['verification']['dropped']}")
    ok(set(p) == {"bundleSha256", "claims", "summary", "verification"} and th["contextOnly"] is True, "LLM 의 score·verification 칸은 못 들어간다")
    ok(p["summary"] == "TV 가격이 4% 내렸다." and th["evidenceIds"] == sorted([ids[0], ids[1]]), "요약·근거 id")
    ok(A.make_thesis(c, b, {**out, "summary": "매출이 305조원이다."}, MODEL, AT)["payload"]["summary"] == "", "인용에 없는 숫자가 든 요약은 비운다")
    ok(A.make_thesis(c, b, {"claims": [out["claims"][1]]}, MODEL, AT) is None and A.make_thesis(c, b, {}, MODEL, AT) is None, "통과 0건 → 기록 없음")

    # 반증
    rout = {"flag": "thesis-weak", "confidence": 0.9, "counters": [
        {"targets": "T1", "claim": "스마트폰은 약 7% 상승해 TV 하락만으로 판단하기 어렵다.", "quote": QUOTE[40:], "evidenceId": ids[1]},
        {"targets": "T9", "claim": "없는 항목 반박", "quote": QUOTE[:45], "evidenceId": ids[1]}],
        "invalidations": [
            {"text": "60일선 아래 5일", "kind": "close-below-ma", "ma": 60.0, "days": 5.0},     # 정수가 실수로 와도 받는다
            {"text": "50일선 아래", "kind": "close-below-ma", "ma": 50, "days": 5},             # 목록 밖 매개변수 → manual
            {"text": "점수 80 아래", "kind": "score-below", "value": 80},                     # 이미 닿아 있음 → manual(2번째라 버림)
            {"text": "점수 60 아래", "kind": "score-below", "value": 60},
            {"text": "위험 상태", "kind": "risk-state-added"}, {"text": "넘침", "kind": "candidate-dropped", "days": 5}]}
    rb = A.make_rebuttal(c, b, th, rout, MODEL, AT)
    rp = rb["payload"]
    ok([x["check"] for x in rp["invalidations"]] == [{"kind": "close-below-ma", "ma": 60, "days": 5}, {"kind": "manual"},
                                                     {"kind": "score-below", "value": 60}, {"kind": "risk-state-added"}],
       f"무효 조건 정규화·상한 4·manual 1: {[x['check'] for x in rp['invalidations']]}")
    ok(len(rp["counters"]) == 1 and rp["verification"] == {"countersTotal": 2, "countersKept": 1, "dropped": [{"id": "#1", "why": "target-unknown"}]}, "반박 대조")
    ok(rp["flag"] == "thesis-weak" and "confidence" not in rp and rb["evidenceIds"][0] == th["eventId"], "깃발·숫자 신뢰도 미수록")
    weak = A.make_rebuttal(c, b, th, {**rout, "counters": [rout["counters"][1]]}, MODEL, AT)
    ok(weak["payload"]["flag"] == "none" and weak["payload"]["counters"] == [], "통과한 반박이 없으면 깃발을 내린다")
    ok(A.make_rebuttal(c, b, th, {"flag": "none", "counters": [], "invalidations": []}, MODEL, AT) is None, "빈 반증 → 기록 없음")

    # 실행 — 이미 쓴 후보 건너뜀 · 한 종목 실패 격리 · 한도
    cs = [cand(t) for t in ("000001", "000002", "000003", "000004")]
    bs = {x["eventId"]: b for x in cs}                                                    # 가짜 응답이 이 묶음의 절 id 를 가리킨다
    seq, calls, slept = iter([out, rout, RuntimeError("깨진 응답"), out, urllib.error.HTTPError("u", 429, "quota", {}, io.BytesIO())]), [], []

    def call(text, schema):
        calls.append(schema is A.THESIS_SCHEMA)
        r = next(seq)
        if isinstance(r, Exception):
            raise r
        return r
    fix = lambda e: e                                                                       # noqa: E731
    evs, d = A.run(cs, bs, set(), call=call, now=lambda: AT, model=MODEL, sleep=slept.append)
    ok([e["type"] for e in evs] == ["THESIS_WRITTEN", "REBUTTAL_WRITTEN", "THESIS_WRITTEN"], f"기록 순서: {[e['type'] for e in evs]}")
    ok(d["thesis"] == {"written": 2, "failed": 1, "claimsTotal": 14, "claimsKept": 4} and d["rebuttal"]["written"] == 1
       and d["rebuttal"]["failed"] == 0 and d["rebuttal"]["flags"]["thesis-weak"] == 1 and d["rebuttal"]["manual"] == 1, f"진단: {d}")
    ok(d["quotaSkipped"] == 2 and len(calls) == 5 and slept == [A.CALL_GAP_SEC] * 4, f"한도 뒤 건너뜀·호출 간격: {d['quotaSkipped']} {slept}")
    for e in evs:
        E.validate(e)
    evs2, d2 = A.run(cs[:1], bs, {evs[0]["eventId"]}, call=call, now=lambda: AT, model=MODEL, sleep=slept.append)
    ok(evs2 == [] and d2["skippedExisting"] == 1 and len(calls) == 5, "이미 논리가 있는 후보는 호출하지 않는다")
    ok("{bundle}" in A.prompt("thesis") and "{claims}" in A.prompt("rebuttal") and fix, "지시문 자리표시자")

    print(f"test-pipeline-agents: {'FAIL ' + str(failed) if failed else 'ok'}")
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
