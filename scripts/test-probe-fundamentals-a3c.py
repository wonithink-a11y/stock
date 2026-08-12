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
ok("selectedFrom이 보통주다", o["istcTotqySelectedFrom"] == "보통주")
ok("stlm_dt 원문을 남긴다", o["stlmDtRaw"] == ["2024.12.31"])

print("\n[8b] probe_cell — 보통주 행이 없으면 합계로 폴백한다 (2026-08-12 재검증)")
_rows_no_common = [
    {"rcept_no": "20250515000456", "stlm_dt": "2025.03.31", "se": "비고", "istc_totqy": None},
    {"rcept_no": "20250515000456", "stlm_dt": "2025.03.31", "se": "합계",
     "istc_totqy": "68,469,040", "isu_stock_totqy": "1,000,000,000", "distb_stock_co": "68,469,040"},
]
m.dart_get = lambda e, p: ({"list": _rows_no_common}, "000", None)
o = m.probe_cell("00101220", 2025, "11013", "1분기")
ok("보통주가 없으면 합계 행을 쓴다", o["istcTotqySelectedFrom"] == "합계")
ok("합계 행의 istc_totqy를 정수로 읽는다", o["istcTotqy"] == 68469040, str(o.get("istcTotqy")))
ok("istcTotqyRowFound가 참이다", o["istcTotqyRowFound"] is True)

print("\n[8c] probe_cell — 보통주도 합계도 없으면 rows[0]으로 임의 폴백하지 않는다")
_rows_neither = [{"rcept_no": "20250515000456", "stlm_dt": "2025.03.31", "se": "비고", "istc_totqy": "999"}]
m.dart_get = lambda e, p: ({"list": _rows_neither}, "000", None)
o = m.probe_cell("00999999", 2025, "11013", "1분기")
ok("istc_totqy가 None이다 (비고 행의 999를 임의로 안 쓴다)", o["istcTotqy"] is None)
ok("istcTotqyRowFound가 거짓이다", o["istcTotqyRowFound"] is False)
ok("selectedFrom도 None이다", o["istcTotqySelectedFrom"] is None)

print("\n[8d] parse_only / RETEST_DEFAULT — 재검증 대상 4건이 정확하다")
parsed = m.parse_only("00101220:2025:11013,00101433:2025:11013")
ok("문자열을 (corp, year, code) 튜플로 파싱한다",
   parsed == [("00101220", 2025, "11013"), ("00101433", 2025, "11013")], str(parsed))
ok("RETEST_DEFAULT가 4건이다", len(m.RETEST_DEFAULT) == 4)
ok("RETEST_DEFAULT가 실제 실패 4건과 일치한다",
   set(m.RETEST_DEFAULT) == {("00101220", 2025, "11013"), ("00101433", 2025, "11013"),
                              ("00101433", 2025, "11014"), ("00100717", 2016, "11013")},
   str(m.RETEST_DEFAULT))

print("\n[8e] retest_only — 원본 산출물(OUT)이 아니라 OUT_RETEST에 쓴다")
ok("출력 경로가 서로 다르다", m.OUT != m.OUT_RETEST, f"{m.OUT} vs {m.OUT_RETEST}")

print("\n[8f] raw_dump — 가공 없이 원본 행을 그대로 저장한다 (판정·파생값 없음)")
m.KEY = "test-key-not-real"  # KEY 없음 가드를 통과시키려는 테스트 전용 값. 실제 호출 없음(dart_get 모킹됨)
_raw_written = {}
m._write = lambda out, path=m.OUT: _raw_written.update({"out": out, "path": path})
_weird_rows = [{"rcept_no": "20250515000456", "stlm_dt": "2025.03.31", "se": "합계",
                "isu_stock_totqy": "1,000,000,000"}]  # istc_totqy 키가 아예 없는 시나리오
m.dart_get = lambda e, p: ({"list": _weird_rows}, "000", None)
m.raw_dump([("00101220", 2025, "11013")])
ok("출력 경로가 OUT_RAWDUMP다", _raw_written["path"] == m.OUT_RAWDUMP)
ok("원본 행을 가공 없이 그대로 담는다",
   _raw_written["out"]["cells"][0]["rawRows"] == _weird_rows, str(_raw_written["out"]["cells"]))
ok("판정 필드(go/blockers/verdict)가 없다 — 이 모드는 판정하지 않는다",
   "verdict" not in _raw_written["out"] and "go" not in _raw_written["out"],
   str(_raw_written["out"].keys()))
ok("OUT_RAWDUMP도 다른 두 경로와 겹치지 않는다",
   len({m.OUT, m.OUT_RETEST, m.OUT_RAWDUMP}) == 3)

print("\n[8g] select_with_carryforward — 확정 규칙(docs/A3c-정책초안.md §2)")
samsung = [
    {"availableFrom": "20180515", "value": 128386494, "tag": "1분기"},
    {"availableFrom": "20180814", "value": 6419324700, "tag": "반기"},
    {"availableFrom": "20181114", "value": 6419324700, "tag": "3분기"},
    {"availableFrom": "20190401", "value": 5969782550, "tag": "사업보고서"},
]
r = m.select_with_carryforward(samsung, "20180601")
ok("분할 후·반기 접수 전엔 분할 전 값을 DIRECT로 유지한다 (미래를 안 당겨쓴다)",
   r == {"value": 128386494, "source": "DIRECT", "from": "20180515", "tag": "1분기"}, str(r))
r = m.select_with_carryforward(samsung, "20180901")
ok("반기 접수 후엔 분할 후 값으로 전환된다",
   r["value"] == 6419324700 and r["source"] == "DIRECT", str(r))

kg = [
    {"availableFrom": "20250814", "value": None, "tag": "1분기"},
    {"availableFrom": "20250814", "value": 68469040, "tag": "반기"},
]
r1 = m.select_with_carryforward(kg, "20250814")
r2 = m.select_with_carryforward(list(reversed(kg)), "20250814")
ok("동일 접수일 — 우선순위(반기>1분기)로 결정되고 입력 순서와 무관하다",
   r1 == r2 == {"value": 68469040, "source": "DIRECT", "from": "20250814", "tag": "반기"}, f"{r1} vs {r2}")

hyp = [
    {"availableFrom": "20250101", "value": 500, "tag": "사업보고서"},
    {"availableFrom": "20250814", "value": 999, "tag": "1분기"},
    {"availableFrom": "20250814", "value": None, "tag": "반기"},
]
r = m.select_with_carryforward(hyp, "20250814")
ok("우선순위 높은 보고서가 결측이어도 같은 날짜의 낮은 우선순위 값으로 안 샌다",
   r["value"] == 500 and r["source"] == "CARRY_FORWARD", str(r))

gn = [
    {"availableFrom": "20250515", "value": None, "tag": "1분기"},
    {"availableFrom": "20250814", "value": 19522575, "tag": "반기"},
    {"availableFrom": "20251114", "value": None, "tag": "3분기"},
    {"availableFrom": "20260318", "value": 19522575, "tag": "사업보고서"},
]
r = m.select_with_carryforward(gn, "20250601")
ok("반기도 안 나온 시점은 정직하게 None이다 (0이나 추정값을 지어내지 않는다)",
   r == {"value": None, "source": None}, str(r))
r = m.select_with_carryforward(gn, "20251201")
ok("3분기 결측을 건너뛰고 반기 값으로 carry-forward한다 (연속 결측 처리)",
   r["value"] == 19522575 and r["source"] == "CARRY_FORWARD"
   and r["selectedButMissing"] == "3분기", str(r))

print("\n[8h] replay_summary — 표본 전체 지표 집계 (판정 없이 숫자만)")


def _obs(corp, fy, code, label, avail, val):
    return {"corp": corp, "fiscalYear": fy, "reprtCode": code, "reprtLabel": label,
            "dartStatus": "000", "availableFrom": avail, "istcTotqy": val}


sample_obs = [
    _obs("A", 2025, "11013", "1분기", "20250515", 100),
    _obs("A", 2025, "11012", "반기", "20250814", 110),
    _obs("A", 2025, "11014", "3분기", "20251114", None),
    _obs("A", 2025, "11011", "사업보고서", "20260318", 120),
    _obs("B", 2025, "11013", "1분기", "20250814", None),
    _obs("B", 2025, "11012", "반기", "20250814", 200),
]
rs = m.replay_summary(sample_obs)
ok("법인×연도 수를 센다", rs["corpYearsObserved"] == 2, str(rs))
ok("동시접수를 1건 잡는다 (B사 1분기·반기가 같은 날)", rs["coFilingCount"] == 1, str(rs))
ok("direct/carry-forward 비율이 숫자로 나온다",
   isinstance(rs["directRatio"], float) and isinstance(rs["carryForwardRatio"], float), str(rs))
ok("neverValidRatio가 0이다 (둘 다 정상값이 최소 한 번은 있다)", rs["neverValidRatio"] == 0.0, str(rs))
ok("연속 결측 최대 길이를 센다 (A사 3분기 1건뿐이라 1)", rs["maxConsecutiveMissing"] == 1, str(rs))

never_obs = [_obs("C", 2025, code, label, "2025" + "0101", None) for code, label in m.REPRT_CODES]
rs2 = m.replay_summary(never_obs)
ok("전 보고서 결측이면 neverValidRatio가 1이다 (지어내지 않는다)", rs2["neverValidRatio"] == 1.0, str(rs2))

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
