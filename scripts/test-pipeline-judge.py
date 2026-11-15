#!/usr/bin/env python3
"""반증 깃발 forward 판정 회귀 — 네트워크 없음. 사전등록 pipeline-rebuttal-forward-preregistration-2026-11.md 의 숫자를 핀한다.

핀하는 것: 기준선 사실(60일선 아래·20일 수익률 하위 30% · 일봉 부족은 모름) · G0(20일 창·문턱 경계·건너뛴 날 제외·
실패한 갈래는 영영 제외·표본 시작 = 창 다음 날) · 조건 미달이면 잠김(평균을 계산하지 않는다) · 심은 효과 → 통과,
효과 없음 → REJECT · 코드 깃발과 같은 말이면 INFORMATION · 마감 지나면 INCONCLUSIVE · 표본 시작 전 사건 제외.

    python scripts/test-pipeline-judge.py
"""
import sys
from datetime import date, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from pipeline import events as E                                               # noqa: E402
from pipeline import judge as J                                                # noqa: E402

failed = 0
CODE = {"kind": "code", "name": "x", "version": "1"}
ARM = ["v1", "m"]


def ok(cond, label):
    global failed
    if not cond:
        failed += 1
        print(f"  FAIL {label}")


def diag(kept=9, total=10, cands=2, th=2, rb=2, inv=8, manual=2, pv="v1", stale=False, skipped=False):
    a = {"candidates": 0, "skipped": True} if skipped else {
        "promptVersion": pv, "model": "m", "candidates": cands, "thesis": {"written": th, "claimsKept": kept, "claimsTotal": total},
        "rebuttal": {"written": rb, "invalidations": inv, "manual": manual}}
    return {"agents": a, "candidates": {"staleScoreSkip": stale}}


def days(n, start=date(2026, 11, 16)):
    return [(start + timedelta(days=i)).strftime("%Y%m%d") for i in range(n)]


def event(i, day: date, flag, excess, status="ok", pv="v1"):
    """사건 하나(후보·반증·h20). 종목이 전부 달라 모두 사건의 첫 날이다."""
    t, d = f"{i:06d}", day.strftime("%Y%m%d")
    at = lambda hh: f"{day.isoformat()}T{hh}:00:00+09:00"                                  # noqa: E731
    sid = E.cand_id(d, "CR-1.0", t)
    c = E.make("CANDIDATE_SELECTED", event_id=sid, ticker=t, market="KR", occurred_at=at(20), as_of=d, producer=CODE, signal_id=sid,
               evidence_ids=[f"score:{d}:{t}"], payload={"ruleVersion": "CR-1.0", "rank": 1, "of": 20, "eligible": 300, "finalScore": 80.0,
                                                         "rawScore": 80.0, "riskPenalty": 0, "coverage": 90.0, "enginePolicies": {}, "inputSha256": "a"})
    out = [c]
    if flag:
        out.append(E.make("REBUTTAL_WRITTEN", event_id=E.rebut_id(sid, pv, "m"), ticker=t, market="KR", occurred_at=at(21), as_of=d,
                          producer={"kind": "llm", "name": "x", "version": "1", "model": "m", "promptVersion": pv}, signal_id=sid,
                          evidence_ids=["thesis:x"], payload={"bundleSha256": "b", "thesisEventId": "thesis:x", "counters": [], "flag": flag,
                                                              "invalidations": [{"id": "I1", "text": "t", "check": {"kind": "manual"}}],
                                                              "verification": {"countersTotal": 0, "countersKept": 0, "dropped": []}}))
    if status != "pending":
        entry, m = (day + timedelta(days=1)).strftime("%Y%m%d"), day + timedelta(days=30)
        good = status == "ok"
        out.append(E.make("OUTCOME_MEASURED", event_id=E.out_id(sid, 20), ticker=t, market="KR", occurred_at=f"{m.isoformat()}T20:00:00+09:00",
                          as_of=m.strftime("%Y%m%d"), producer=CODE, signal_id=sid, evidence_ids=[f"px:{d}:{t}"],
                          payload={"horizon": 20, "entryDate": entry, "exitDate": m.strftime("%Y%m%d"), "entryPx": 100.0, "exitPx": 101.0,
                                   "ret": 0.01 if good else None, "benchmark": "KR_WATCHLIST_EW", "benchRet": 0.0, "excess": excess if good else None,
                                   "costBp": 33.5, "netExcess": excess - 0.00335 if good else None, "status": status}))
    return out, (d, t)


def sample(weeks, per_week, drop_every, keep_ex, drop_ex, code_same=False, start=date(2027, 1, 4)):
    """주마다 per_week 건. drop_every 번째마다 LLM 깃발. 초과수익은 주마다 ±흔들림을 더한다(결정적)."""
    log, base, i = [], {}, 0
    for w in range(weeks):
        for k in range(per_week):
            i += 1
            drop = i % drop_every == 0
            wob = ((w * 7 + k * 3) % 11 - 5) / 1000.0
            evs, (d, t) = event(i, start + timedelta(weeks=w, days=k), "caution" if drop else "none", (drop_ex if drop else keep_ex) + wob)
            log += evs
            code_drop = drop if code_same else (i % 3 == 0)
            base.setdefault(d, {})[t] = {"known": True, "drop": code_drop}
    return log, base


def main():
    # ---- 기준선 사실
    D = days(70, date(2026, 9, 1))
    px = {f"{i:06d}": {"d": D, "c": [100.0 + i * j * 0.1 for j in range(70)]} for i in range(1, 11)}          # 종목 번호가 클수록 많이 올랐다
    px["000001"]["c"] = [200.0 - j for j in range(70)]                                                       # 내리는 종목: 60일선 아래
    px["000010"]["d"] = D[:40]                                                                               # 일봉 부족
    cs = [{"ticker": f"{i:06d}", "asOf": D[-1]} for i in range(1, 11)]
    bf = J.baseline_facts(cs, px)
    ok(bf["000010"] == {"known": False}, "일봉 부족 → 모름(깃발 없음)")
    ok(bf["000001"]["drop"] and bf["000001"]["ret20Rank"] == 1 and bf["000001"]["close"] < bf["000001"]["ma60"], "내리는 종목은 60일선 아래·수익률 꼴찌")
    ok([t for t in sorted(bf) if bf[t].get("drop")] == ["000001", "000002", "000003"], f"하위 30%(10개 중 순위 ≤ 3): {[t for t in sorted(bf) if bf[t].get('drop')]}")
    ok(bf["000009"]["drop"] is False and bf["000009"]["ret20Rank"] == 9, "오르는 종목은 깃발 없음")

    # ---- G0
    dd = days(25)
    g = J.g0({d: diag() for d in dd[:19]})
    ok(g["arm"] is None and g["arms"]["v1|m"] == {"days": 19, "passed": None}, "19일이면 미정")
    g = J.g0({d: diag() for d in dd[:20]})
    ok(g["arm"] == ARM and g["sampleStart"] == "2026-12-06" and g["arms"]["v1|m"]["window"] == [dd[0], dd[19]], f"20일 통과 → 표본 시작은 창 다음 날: {g['sampleStart']}")
    mixed = {d: diag(skipped=(i % 2 == 1)) for i, d in enumerate(dd)}
    ok(J.g0(mixed)["arm"] is None and J.g0(mixed)["arms"]["v1|m"]["days"] == 13, "주석을 건너뛴 날은 창에 안 센다")
    edge = lambda **kw: J.g0({d: diag(**kw) for d in dd[:20]})["arms"]["v1|m"]["passed"]                    # noqa: E731
    ok(edge(kept=8) is True and edge(kept=79, total=100) is False, "인용 통과율 0.80 경계")
    ok(edge(cands=20, th=17, rb=17, kept=9) is True and edge(cands=20, th=17, rb=16) is False, "기록률 0.85 경계(논리·반증 각각)")
    ok(edge(inv=8, manual=4) is True and edge(inv=8, manual=5) is False, "점검 가능 비율 0.50 경계")
    stale = {d: diag(stale=(i < 3)) for i, d in enumerate(dd[:20])}
    ok(J.g0(stale)["arms"]["v1|m"]["passed"] is False and J.g0({d: diag(stale=(i < 2)) for i, d in enumerate(dd[:20])})["arm"] == ARM, "후보 미생성 2일까지")
    two = {d: diag(kept=5) for d in dd[:20]}
    two.update({d: diag(pv="v2") for d in days(20, date(2026, 12, 10))})
    g2 = J.g0(two)
    ok(g2["arm"] == ["v2", "m"] and g2["arms"]["v1|m"]["passed"] is False and g2["sampleStart"] == "2026-12-30", "실패한 갈래는 제외, 다음 갈래가 통과")

    # ---- 판정: 잠김 · 통과 · 기각
    diags = {d: diag() for d in days(20, date(2026, 12, 1))}                    # 표본 시작 2026-12-21
    semis = set()
    log, base = sample(45, 6, 4, keep_ex=0.010, drop_ex=-0.020)                 # 270건, 깃발 67건
    early, _ = event(900001, date(2026, 12, 10), "caution", -0.5)               # 표본 시작 전 — 들어가면 D 가 크게 흔들린다
    r = J.run(log + early, diags, base, "2027-06-01", semis)
    ok(r["locked"] and "stats" not in r and "verdict" not in r and r["need"]["days"][0] < 365, "365일 전에는 잠김 — 평균 없음")
    ok(r["counts"]["events"] == 270 and r["counts"]["llmDrop"] == 67 and r["counts"]["weeks"] == 45, f"건수(표본 시작 전 사건 제외): {r['counts']}")
    few, fb = sample(45, 6, 9, keep_ex=0.010, drop_ex=-0.020)
    ok(J.run(few, diags, fb, "2028-03-01", semis)["locked"], "깃발 사건 60건 미만이면 잠김")
    ok(J.run(*sample(30, 9, 4, 0.01, -0.02)[:1], diags, {}, "2028-03-01", semis)["locked"], "40주 미만이면 잠김")
    late = J.run(few, diags, fb, "2029-12-25", semis)
    ok(late["locked"] is False and late["verdict"] == "INCONCLUSIVE" and "stats" not in late, "1,095일 마감 → INCONCLUSIVE(평균 없음)")

    r = J.run(log + early, diags, base, "2028-03-01", semis)
    s = r["stats"]
    ok(r["locked"] is False and r["verdict"] == "ROBUST" and r["signal"] == "있음" and r["economic"] == "통과", f"심은 효과(−2% 대 +1%) → 통과: {r.get('verdict')} {s}")
    ok(abs(s["dLlm"] - 0.03) < 0.003 and s["ciLlm"][0] > 0.02 and s["dLlm"] > s["floor"] and abs(s["dCode"]) < 0.01, "D_llm ≈ 3%p · 바닥선 위 · 코드 깃발은 무관")
    ok(r == J.run(log + early, diags, base, "2028-03-01", semis), "난수 씨 고정 — 같은 입력 같은 결과")
    ok(J.run(log, diags, base, "2028-03-01", {f"{i:06d}" for i in range(1, 271, 2)})["stats"]["exSemis"] != s["exSemis"], "반도체 제외 줄은 따로 계산")

    null, nb = sample(45, 6, 4, keep_ex=0.0, drop_ex=0.0)
    rn = J.run(null, diags, nb, "2028-03-01", semis)
    ok(rn["verdict"] == "REJECT" and rn["signal"] == "없음", f"효과 없음 → REJECT: {rn['verdict']} {rn['stats']['dLlm']} floor {rn['stats']['floor']}")
    same, sb = sample(45, 6, 4, keep_ex=0.010, drop_ex=-0.020, code_same=True)
    rs = J.run(same, diags, sb, "2028-03-01", semis)
    ok(rs["verdict"] == "INFORMATION" and rs["economic"] == "미달" and rs["stats"]["ciDiff"][0] <= 0, f"코드 깃발과 같은 말 → INFORMATION: {rs['verdict']}")
    small, smb = sample(45, 6, 4, keep_ex=0.0015, drop_ex=-0.0010)
    rsm = J.run(small, diags, smb, "2028-03-01", semis)
    ok(rsm["verdict"] in ("INFORMATION", "REJECT") and rsm["economic"] == "미달", f"비용(33.5bp)보다 작은 차이는 경제성 미달: {rsm['verdict']}")

    # ---- 상태·미기록
    mixed_log = []
    for i, (flag, st) in enumerate([("none", "ok"), (None, "ok"), ("caution", "halted"), ("none", "pending")], 1):
        mixed_log += event(i, date(2027, 1, 4) + timedelta(days=i), flag, 0.01, st)[0]
    mixed_log += event(9, date(2027, 1, 20), "caution", 0.01, pv="v2")[0]       # 다른 갈래의 반증은 판정 갈래의 기록이 아니다
    c = J.counts(J.rows(mixed_log, {}, ARM, "2026-12-21"))
    ok(c["events"] == 5 and c["status"] == {"halted": 1, "ok": 3, "pending": 1} and c["llmKeep"] == 1 and c["llmUnrecorded"] == 2
       and c["llmDrop"] == 0 and c["codeUnknown"] == 3, f"정지·대기는 평균 밖, 미기록·기준선 모름은 건수만: {c}")
    ok(J.run([], {}, {}, "2027-11-17", semis)["verdict"] == "INCONCLUSIVE" and J.run([], {}, {}, "2027-11-16", semis)["locked"], "G0 마감(2027-11-16) 뒤 INCONCLUSIVE")

    print(f"test-pipeline-judge: {'FAIL ' + str(failed) if failed else 'ok'}")
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
