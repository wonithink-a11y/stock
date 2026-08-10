#!/usr/bin/env python3
"""A3b 정찰 회귀 — 네트워크 없이 판정 로직만 밟는다.
  python scripts/test-probe-fundamentals-a3b.py

정찰의 산출물은 데이터가 아니라 **판정**이다. 그래서 여기서 지키는 것은 하나다 —
**못 잰 것을 통과로 적지 않는다**(교훈50·57). 정찰이 GO를 잘못 내면 그 뒤 2일치
수집과 A3b 계약 전체가 잘못된 전제 위에 선다. A3가 fnlttSinglAcntAll에서 3일을
잃을 뻔한 자리가 정확히 여기다.

밟는 분기:
  1. 전건 정상이면 GO
  2. rcept_no 가 없으면 NO-GO (availableFrom 경로가 없다)
  3. stlm_dt 가 없으면 NO-GO (계약 1을 잴 수단이 없다)
  4. PIT 방향이 A3 계약(>)과 다르면 NO-GO
  5. 응답이 0건이면 비율이 None 이고 GO 가 아니다 (0건을 100%로 읽지 않는다)
  6. 표본 선정이 결정적이다 (재실행해도 같은 표본이라야 대조가 성립한다)
  7. 금액을 산출물에 남기지 않는다
"""
import importlib.util
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
os.chdir(ROOT)
spec = importlib.util.spec_from_file_location(
    "a3b_probe", os.path.join(ROOT, "scripts", "probe-fundamentals-a3b.py"))
m = importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)

passed = failed = 0


def ok(label, cond, detail=""):
    global passed, failed
    print(("  OK    " if cond else "  FAIL  ") + label + (f"  — {detail}" if not cond and detail else ""))
    if cond:
        passed += 1
    else:
        failed += 1


def obs(**kw):
    """정상 관측 하나. 개별 테스트가 필요한 것만 덮어쓴다."""
    base = {"corp": "00126380", "fiscalYear": 2024, "group": "currentWithA3",
            "dartStatus": "000", "rowCount": 6,
            "rceptNoPresent": True, "rceptNoFormatOk": True, "rceptNoConsistent": True,
            "availableFrom": "20250311", "availableFromParsable": True,
            "stlmDtPresent": True, "periodEnd": "20241231", "periodEndParsable": True,
            "pitDirection": "after", "epsRowFound": True, "dividendRowFound": True}
    base.update(kw)
    return base


print("[1] 전건 정상")
v = m.verdict([obs(), obs(fiscalYear=2023)])
ok("GO 다", v["go"] is True and not v["blockers"], str(v["blockers"]))
ok("PIT 계약 방향이 A3와 같은 > 로 확정된다",
   v["pitContractDirection"] == "availableFrom > periodEnd", v["pitContractDirection"])
ok("valuation 을 연다", v["opensValuation"] is True)

print("\n[2] rcept_no 없음 — A3가 fnlttSinglAcntAll에서 겪은 것과 같은 상태")
v = m.verdict([obs(rceptNoPresent=False, availableFrom=None, availableFromParsable=False,
                   pitDirection=None)])
ok("NO-GO 다", v["go"] is False)
ok("canAnchorPit 이 거짓이다", v["canAnchorPit"] is False)
ok("blocker 가 PIT 앵커 부재를 지목한다",
   any("PIT 앵커" in b for b in v["blockers"]), str(v["blockers"]))

print("\n[3] stlm_dt 없음 — 계약 1을 잴 수단이 없다")
v = m.verdict([obs(stlmDtPresent=False, periodEnd=None, periodEndParsable=False,
                   pitDirection=None)])
ok("NO-GO 다", v["go"] is False)
ok("canMeasurePeriodEnd 가 거짓이다", v["canMeasurePeriodEnd"] is False)
ok("A3 의 periodEnd 를 빌려 쓰지 말라는 근거가 blocker 에 있다",
   any("빌려" in b for b in v["blockers"]), str(v["blockers"]))

print("\n[4] PIT 방향이 A3 계약과 다르다")
v = m.verdict([obs(), obs(pitDirection="before", availableFrom="20241130")])
ok("NO-GO 다", v["go"] is False)
ok("MIXED_OR_UNEXPECTED 로 표시된다",
   v["pitContractDirection"] == "MIXED_OR_UNEXPECTED", v["pitContractDirection"])
ok("방향 분포를 그대로 남긴다", v["pitDirection"] == {"after": 1, "before": 1},
   str(v["pitDirection"]))

print("\n[5] 응답 0건 — 0을 100%로 읽지 않는다")
v = m.verdict([{"corp": "x", "fiscalYear": 2024, "group": "noA3",
                "dartStatus": "013", "rowCount": 0}])
ok("비율이 None 이다 (분모가 없으면 판정하지 않는다)",
   v["rceptNoPresentRate"] is None and v["periodEndParsableRate"] is None,
   f"{v['rceptNoPresentRate']} / {v['periodEndParsableRate']}")
ok("GO 가 아니다", v["go"] is False)
ok("PIT 방향이 UNMEASURED 다", v["pitContractDirection"] == "UNMEASURED")
ok("그룹별 응답 수를 남긴다", v["byGroup"]["noA3"]["responded"] == 0)

print("\n[6] 표본 선정이 결정적이다")
a3_idx = m.load_a3_index()
if not a3_idx:
    ok("A3 산출물이 있어야 이 검사를 할 수 있다", False, "a3/*.jsonl.gz 없음")
else:
    s1, s2 = m.pick_sample(a3_idx), m.pick_sample(a3_idx)
    ok("두 번 골라도 같다", s1 == s2)
    ok("호출 수가 32건이다", sum(len(p["years"]) for p in s1) == 32,
       str(sum(len(p["years"]) for p in s1)))
    groups = {p["group"] for p in s1}
    ok("세 축이 모두 표본에 있다 (무작위 32건은 갈리는 축을 못 밟는다)",
       groups == {"currentWithA3", "delistedWithA3", "noA3"}, str(groups))
    ok("A3 인덱스에서 고른 법인은 실제로 그 연도를 갖고 있다",
       all((p["corp"], y) in a3_idx
           for p in s1 if p["group"] != "noA3" for y in p["years"]))
    ok("noA3 축은 A3 인덱스에 없다 (599 그룹을 실제로 밟는다)",
       all((p["corp"], y) not in a3_idx
           for p in s1 if p["group"] == "noA3" for y in p["years"]))

print("\n[7] 금액을 남기지 않는다")
_rows = [{"rcept_no": "20250311000123", "stlm_dt": "2024.12.31",
          "se": "(연결)주당순이익", "thstrm": "8,057", "frmtrm": "5,601",
          "stock_knd": "보통주"},
         {"rcept_no": "20250311000123", "stlm_dt": "2024.12.31",
          "se": "주당현금배당금", "thstrm": "1,444", "stock_knd": "보통주"}]
m.dart_get = lambda e, p: ({"list": _rows}, "000", None)
o = m.probe_one("00126380", 2024, {("00126380", 2024): {"rceptNo": "20250311000123",
                                                        "availableFrom": "2025-03-11"}})
blob = json.dumps(o, ensure_ascii=False)
ok("EPS·배당 금액이 산출물에 없다", "8,057" not in blob and "1,444" not in blob
   and "8057" not in blob and "1444" not in blob, blob[:200])
ok("찾았는지·숫자로 읽히는지는 남긴다",
   o["epsRowFound"] and o["epsThstrmNumeric"] and o["dividendRowFound"])
ok("availableFrom 을 rcept_no 앞 8자리에서 만든다", o["availableFrom"] == "20250311")
ok("periodEnd 를 stlm_dt 에서 읽는다", o["periodEnd"] == "20241231", str(o.get("periodEnd")))
ok("방향이 after 다", o["pitDirection"] == "after")
ok("A3 rceptNo 와 대조한다", o.get("rceptNoMatchesA3") is True)
ok("stlm_dt 원문을 남긴다 (형태 자체가 정찰의 산출이다)",
   o["stlmDtRaw"] == ["2024.12.31"], str(o.get("stlmDtRaw")))

print(f"\n{'='*54}")
print(f"통과 {passed} · 실패 {failed}")
sys.exit(0 if failed == 0 else 1)
