#!/usr/bin/env python3
"""A3c 정찰 회귀 — 네트워크 없이 판정 로직만 밟는다.
  python scripts/test-probe-fundamentals-a3c.py

지키는 것은 A3b 회귀와 같다 — **못 잰 것을 통과로 적지 않는다**(교훈50·57).
추가로 이 파일만의 것: 액면분할 관측(split_verdict)이 "50배 근처 비율이
나타났다"를 지어내지 않고 실제 연속값 비율만 계산해 사람이 판단하게 두는가.
"""
import importlib.util
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
os.chdir(ROOT)
spec = importlib.util.spec_from_file_location(
    "a3c_probe", os.path.join(ROOT, "scripts", "probe-fundamentals-a3c.py"))
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
    base = {"corp": "00126380", "fiscalYear": 2024, "reprtCode": "11011",
            "reprtLabel": "사업보고서", "group": "currentWithA3",
            "dartStatus": "000", "rowCount": 1,
            "rceptNoPresent": True, "rceptNoFormatOk": True,
            "availableFrom": "20250311", "availableFromParsable": True,
            "istcTotqy": 5969782550, "istcTotqyRowFound": True}
    base.update(kw)
    return base


print("[1] num() — 숫자로 안 읽히면 None이지 0이 아니다")
ok("콤마 포함 문자열을 정수로", m.num("5,969,782,550") == 5969782550)
ok("빈 문자열은 None", m.num("") is None)
ok("'-'는 None (0이 아니다)", m.num("-") is None)
ok("None 입력도 None", m.num(None) is None)

print("\n[2] 전건 정상 — GO")
v = m.verdict([obs(), obs(reprtCode="11013", reprtLabel="1분기")])
ok("GO 다", v["go"] is True and not v["blockers"], str(v["blockers"]))
ok("canAnchorPit 참", v["canAnchorPit"] is True)
ok("canReadIstcTotqy 참", v["canReadIstcTotqy"] is True)

print("\n[3] istc_totqy를 못 읽으면 NO-GO")
v = m.verdict([obs(istcTotqy=None, istcTotqyRowFound=False)])
ok("NO-GO 다", v["go"] is False)
ok("blocker가 istc_totqy 부재를 지목한다",
   any("istc_totqy" in b for b in v["blockers"]), str(v["blockers"]))

print("\n[4] rcept_no 없으면 NO-GO")
v = m.verdict([obs(rceptNoPresent=False, availableFrom=None, availableFromParsable=False)])
ok("NO-GO 다", v["go"] is False)
ok("canAnchorPit 거짓", v["canAnchorPit"] is False)

print("\n[5] 응답 0건 — 0을 100%로 읽지 않는다")
v = m.verdict([{"corp": "x", "fiscalYear": 2024, "reprtCode": "11011", "dartStatus": "013", "rowCount": 0}])
ok("비율이 None이다", v["rceptNoPresentRate"] is None and v["istcTotqyRowFoundRate"] is None)
ok("GO가 아니다", v["go"] is False)

print("\n[6] split_verdict — 관측이 2건 미만이면 측정 불가로 남긴다(지어내지 않는다)")
sv = m.split_verdict([obs(istcTotqy=5969782550)])
ok("measured False", sv["measured"] is False)
ok("이유를 남긴다", "2건 미만" in sv["reason"])

print("\n[7] split_verdict — 실제 분할 시나리오(50배)를 그대로 계산한다")
pre, post = 119395655, 5969782550  # 실측에 가까운 규모(50배 근사)
split_obs = [
    obs(reprtCode="11013", reprtLabel="1분기", istcTotqy=pre, availableFrom="20180515"),
    obs(reprtCode="11012", reprtLabel="반기", istcTotqy=post, availableFrom="20180814"),
]
sv = m.split_verdict(split_obs)
ok("measured True", sv["measured"] is True)
ok("분기 순서대로 정렬된 시퀀스를 남긴다",
   [s[0] for s in sv["sequence"]] == ["1분기", "반기"], str(sv["sequence"]))
ok("비율을 계산한다 (50배 근처, 반올림 오차 허용)",
   abs(sv["quarterOverQuarterRatios"][0] - 50) < 1, str(sv["quarterOverQuarterRatios"]))
ok("판단은 여기서 안 내린다 — '이게 분할이다'라고 단정하는 필드가 없다",
   "isSplit" not in sv and "detected" not in sv, str(sv.keys()))

print("\n[8] probe_cell — 응답 파싱과 PIT 필드 추출")
_rows = [{"rcept_no": "20250311000123", "stlm_dt": "2024.12.31", "se": "보통주",
          "istc_totqy": "5,969,782,550", "isu_stock_totqy": "6,000,000,000",
          "distb_stock_co": "5,900,000,000"}]
m.dart_get = lambda e, p: ({"list": _rows}, "000", None)
o = m.probe_cell("00126380", 2024, "11011", "사업보고서")
ok("availableFrom을 rcept_no 앞 8자리에서 만든다", o["availableFrom"] == "20250311")
ok("istc_totqy를 콤마 제거 후 정수로 읽는다", o["istcTotqy"] == 5969782550, str(o.get("istcTotqy")))
ok("보통주 행을 우선한다", o["seSample"] == ["보통주"])
ok("stlm_dt 원문을 남긴다", o["stlmDtRaw"] == ["2024.12.31"])

print("\n[9] 표본 선정이 결정적이다 (A3 산출물이 있을 때만)")
a3_idx = m.load_a3_index()
if not a3_idx:
    ok("A3 산출물이 있어야 이 검사를 할 수 있다", False, "a3/*.jsonl.gz 없음")
else:
    s1, s2 = m.pick_sample(a3_idx), m.pick_sample(a3_idx)
    ok("두 번 골라도 같다", s1 == s2)
    groups = {p["group"] for p in s1}
    ok("두 축이 모두 표본에 있다", groups <= {"currentWithA3", "delistedWithA3"})

print(f"\n{'='*54}")
print(f"통과 {passed} · 실패 {failed}")
sys.exit(0 if failed == 0 else 1)
