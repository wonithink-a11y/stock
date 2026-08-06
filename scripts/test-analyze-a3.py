#!/usr/bin/env python3
"""A3 품질 분석기 회귀 — 합성 픽스처로 누락 패턴 분류를 못 박는다.
  python scripts/test-analyze-a3.py

네트워크도 수집 산출물도 필요 없다. 지키려는 것 셋이다.

  1. 세 유형(중간 구멍 · 뒤 잘림 · 앞 늦음)이 각각 옳게 분류되는가
  2. 사유를 아는 구멍과 모르는 구멍이 갈리는가 — recordGaps의 존재 이유다
  3. 파생값이 원시 사실과 어긋나지 않는가

분석기는 판단의 입력이 된다. 여기가 틀리면 그 위에서 내린 임계·승격이 전부 틀린다.
"""
import importlib.util
import json
import os
import sys

for _s in (sys.stdout, sys.stderr):
    if hasattr(_s, "reconfigure"):
        _s.reconfigure(errors="replace")

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
spec = importlib.util.spec_from_file_location(
    "az", os.path.join(ROOT, "scripts", "analyze-fundamentals-a3.py"))
az = importlib.util.module_from_spec(spec)
spec.loader.exec_module(az)

POL = json.load(open(os.path.join(ROOT, "config/policies/fundamentals.v1.json"),
                     encoding="utf-8"))
# 픽스처는 좁은 구간으로 본다. 정책 구간을 쓰면 픽스처가 11년치가 돼 읽기 어렵다.
P = {**POL, "fiscalYearFrom": 2020, "fiscalYearTo": 2024}

passed = failed = 0


def ok(name, cond, detail=""):
    global passed, failed
    if cond:
        passed += 1
        print(f"  OK    {name}")
    else:
        failed += 1
        print(f"  FAIL  {name}{('  — ' + detail) if detail else ''}")


def R(corp, year, fs="CFS", **kw):
    r = {"corp": corp, "ticker": "000001", "fiscalYear": year, "availableFrom":
         f"{year + 1}-03-31", "fsDiv": fs, "periodEnd": f"{year}-12-31",
         "accountSource": {a: "nameExact" for a in az.ACCOUNTS}}
    for a in az.ACCOUNTS:
        r[a] = 100
    r.update(kw)
    return r


print("[누락 패턴 세 유형]")
# A: 전 연도 · B: 중간 구멍(2022) · C: 뒤 잘림(2022까지) · D: 앞 늦음(2022부터)
rows = ([R("A", y) for y in range(2020, 2025)]
        + [R("B", y) for y in (2020, 2021, 2023, 2024)]
        + [R("C", y) for y in (2020, 2021, 2022)]
        + [R("D", y) for y in (2022, 2023, 2024)])
done = {"A", "B", "C", "D", "E"}          # E는 레코드 0건으로 완료
o = az.analyze(rows, done, {}, None, P)

ok("전 연도 보유를 센다", o["fullRange"] == 1, str(o["fullRange"]))
ok("중간 구멍만 내부 구멍으로 센다 (뒤 잘림·앞 늦음은 구멍이 아니다)",
   o["internalHoles"] == 1 and o["internalHolesDetail"][0]["corp"] == "B",
   str([h["corp"] for h in o["internalHolesDetail"]]))
ok("구멍의 빠진 해를 지목한다", o["internalHolesDetail"][0]["missing"] == [2022],
   str(o["internalHolesDetail"][0]))
ok("뒤가 잘린 법인을 센다 (C만)", o["tailCut"] == 1, str(o["tailCut"]))
ok("마지막 해 분포를 남긴다", o["tailCutByLastYear"] == {2022: 1},
   str(o["tailCutByLastYear"]))
ok("앞이 늦게 시작한 법인을 센다 (D만)", o["headLate"] == 1, str(o["headLate"]))
ok("레코드 0건으로 완료된 법인을 센다 (E)", o["corpsDoneWithNoRecords"] == 1,
   str(o["corpsDoneWithNoRecords"]))

# 유형이 겹칠 수 있다. 합계를 내면 이중계상이므로 내지 않는다는 것을 못 박는다.
rows2 = [R("F", y) for y in (2021, 2023)]          # 앞 늦음 + 구멍 + 뒤 잘림
o2 = az.analyze(rows2, {"F"}, {}, None, P)
ok("한 법인이 세 유형에 동시에 잡힐 수 있다 (배타적이지 않다)",
   o2["internalHoles"] == 1 and o2["tailCut"] == 1 and o2["headLate"] == 1,
   f"hole={o2['internalHoles']} tail={o2['tailCut']} head={o2['headLate']}")
ok("합계 필드를 만들지 않는다 (만들면 이중계상이다)",
   not any(k.lower().startswith("totalmissing") or k == "missingCorps" for k in o2))


print("\n[공백 사유 — 아는 구멍과 모르는 구멍]")
# recordGaps의 존재 이유가 여기다. 사유가 없으면 구멍이 정상 사실인지 손실인지
# 구분되지 않고, 그 구분이 파서를 고칠지 말지를 가른다.
gaps = {"B": {"2022": "REJECT:PERIOD_END_UNPARSED"}}
o3 = az.analyze(rows, done, gaps, None, P)
ok("사유를 아는 구멍을 센다", o3["holeYearsWithReason"] == 1, str(o3))
ok("사유를 모르는 구멍을 센다", o3["holeYearsWithoutReason"] == 0, str(o3))
ok("빈 해 총계가 앎+모름과 맞는다 (분해가 남김없다)",
   o3["holeYears"] == o3["holeYearsWithReason"] + o3["holeYearsWithoutReason"])
ok("사유가 구멍 상세에 붙는다",
   o3["internalHolesDetail"][0]["reasons"]["2022"] == "REJECT:PERIOD_END_UNPARSED",
   str(o3["internalHolesDetail"][0]["reasons"]))
ok("사유가 없으면 None으로 남는다 (0이나 '없음'으로 채우지 않는다)",
   o["internalHolesDetail"][0]["reasons"]["2022"] is None,
   str(o["internalHolesDetail"][0]["reasons"]))
ok("사유 분포는 계층 앞머리로 센다",
   az.analyze(rows, done, {"B": {"2022": "HARD:transport:X"}}, None, P)
   ["recordGapReasons"] == {"HARD": 1})

# 레코드 0건 법인의 사유도 본다 — 그 법인이 아예 보고서를 안 낸 것인지
# 조회가 다 실패한 것인지는 대응이 정반대다.
o4 = az.analyze(rows, done, {"E": {"2020": "013"}}, None, P)
ok("레코드 0건 법인 중 사유를 아는 것을 센다",
   o4["corpsDoneWithNoRecordsWithReason"] == 1,
   str(o4["corpsDoneWithNoRecordsWithReason"]))


print("\n[연결/별도]")
rows5 = ([R("G", 2020, "CFS"), R("G", 2021, "OFS")]
         + [R("H", 2020, "OFS")] + [R("I", 2020, "CFS")])
o5 = az.analyze(rows5, {"G", "H", "I"}, {}, None, P)
ok("레코드 단위 분포를 낸다", o5["fsDivRecords"] == {"CFS": 2, "OFS": 2},
   str(o5["fsDivRecords"]))
ok("법인 단위 패턴을 낸다 (연결만·별도만·둘 다가 갈린다)",
   o5["fsDivByCorp"] == {"CFS+OFS": 1, "OFS": 1, "CFS": 1}, str(o5["fsDivByCorp"]))


print("\n[계정 매칭]")
# 커버리지 분자에 유동자산·유동부채를 넣지 않는다 — 금융업에는 그 계정이 없어
# 업종 구성이 데이터 품질로 둔갑한다(교훈48).
ok("핵심 계정 목록에 유동자산·유동부채가 없다",
   "currentAssets" not in az.CORE and "currentLiab" not in az.CORE, str(az.CORE))
fin = R("J", 2020, currentAssets=None, currentLiab=None)
fin["accountSource"]["currentAssets"] = None
fin["accountSource"]["currentLiab"] = None
o6 = az.analyze([fin], {"J"}, {}, None, P)
ok("금융업 양식(유동 항목 부재)도 핵심 계정은 완전하다",
   o6["coreComplete"] == 1 and o6["coreCompleteRate"] == 1.0, str(o6["coreCompleteRate"]))
ok("MISS는 계정별로 남는다 (평균은 어느 계정이 무너졌는지 가린다)",
   o6["accountSourceByAccount"]["currentAssets"] == {"MISS": 1}
   and o6["accountSourceByAccount"]["equity"] == {"nameExact": 1},
   str(o6["accountSourceByAccount"]["currentAssets"]))


print("\n[그룹별 확보율]")
# 전체 비율만 두면 현재 상장분이 폐지분의 공백을 가린다(A2b 정찰에서 배운 분모 문제).
tgt = {"A": {"group": "current", "market": "KOSPI"},
       "B": {"group": "current", "market": "KOSDAQ"},
       "C": {"group": "delisted", "market": "UNKNOWN"},
       "D": {"group": "delisted", "market": "UNKNOWN"},
       "E": {"group": "delisted", "market": "UNKNOWN"}}
o7 = az.analyze(rows, done, {}, tgt, P)
ok("그룹별 분모를 따로 든다",
   o7["corpsTargetedByGroup"] == {"current": 2, "delisted": 3},
   str(o7["corpsTargetedByGroup"]))
ok("그룹별 확보율이 갈린다",
   o7["corpsWithRecordsRateByGroup"]["current"] == 1.0
   and o7["corpsWithRecordsRateByGroup"]["delisted"] == round(2 / 3, 4),
   str(o7["corpsWithRecordsRateByGroup"]))


print("\n[읽기 전용]")
src = open(os.path.join(ROOT, "scripts/analyze-fundamentals-a3.py"), encoding="utf-8").read()
ok("파일을 쓰지 않는다 (분석기는 파생만 만들고 저장하지 않는다)",
   'open(' in src and not any(f'"w"' in l or "'w'" in l
                              for l in src.splitlines() if "open(" in l), "쓰기 모드 발견")
ok("네트워크를 쓰지 않는다", "requests" not in src and "urllib" not in src)

print("\n[품질 리포트 QR-1.0]")
_qspec = importlib.util.spec_from_file_location(
    "qr", os.path.join(ROOT, "scripts", "generate-quality-report.py"))
qr = importlib.util.module_from_spec(_qspec)
_qspec.loader.exec_module(qr)

o_full = az.analyze(rows, done, gaps, {c: {"group": "current", "market": "KOSPI"}
                                       for c in done}, P)
o_full["source"], o_full["isFinalOutput"] = "t", False
rep = qr.build(o_full, rows)

ok("스키마 검사가 통과한다", qr.check(rep) == [], str(qr.check(rep)))
ok("섹션이 여섯이다 (coverage·missing·pit·schemaQuality·patterns·meta)",
   set(rep) == set(qr.REQUIRED), str(sorted(rep)))

# 칸이 비어 있는 것과 칸이 없는 것은 다르다. 표에 등록된 키를 지우면 걸려야 한다.
import copy as _copy
_broken = _copy.deepcopy(rep)
del _broken["pit"]["futureLeak"]
ok("등록된 칸이 빠지면 스키마 검사가 잡는다",
   any("pit.futureLeak" in b for b in qr.check(_broken)), str(qr.check(_broken)))
_broken2 = _copy.deepcopy(rep)
_broken2["meta"]["schema"] = "QR-0.9"
ok("스키마 버전이 다르면 잡는다", qr.check(_broken2) != [], str(qr.check(_broken2)))

# 계산이 두 벌이 아니라는 것 — 리포트 값은 analyze()에서 그대로 온다.
ok("리포트가 계산을 다시 하지 않는다 (analyze 결과와 같다)",
   rep["patterns"]["internalHoles"] == o_full["internalHoles"]
   and rep["pit"]["futureLeak"] == o_full["pit"]["futureLeak"]
   and rep["schemaQuality"]["coreCompleteRate"] == o_full["coreCompleteRate"])

# 낡음 탐지 — 파생을 저장하는 대가로 지불하는 것이다.
d1 = qr.input_digest(rows)
ok("같은 레코드는 순서가 달라도 같은 digest",
   d1 == qr.input_digest(list(reversed(rows))), d1)
ok("레코드가 달라지면 digest가 달라진다",
   d1 != qr.input_digest(rows + [R("Z", 2020)]))

# 부분 표본을 전수로 읽지 않게 하는 플래그. FN-1.4 임계는 true인 리포트에서만 정한다.
ok("부분 수집이면 sampleComplete가 false", rep["meta"]["sampleComplete"] is False,
   str(rep["meta"]))
o_fin = dict(o_full, isFinalOutput=True, corpsDone=len(done), corpsTargeted=len(done))
ok("전수 산출물이고 done == targeted일 때만 true",
   qr.build(o_fin, rows)["meta"]["sampleComplete"] is True)
o_fin2 = dict(o_full, isFinalOutput=True, corpsDone=1, corpsTargeted=99)
ok("산출물이어도 done != targeted면 false",
   qr.build(o_fin2, rows)["meta"]["sampleComplete"] is False)

# 사유 없는 구멍이 비율로 남는가 — recordGaps의 적용 범위가 값으로 보여야 한다.
ok("사유를 아는 비율이 남는다 (1.0이 아닐 수 있고 그것이 사실이다)",
   rep["missing"]["reasonCoverage"] == round(
       o_full["holeYearsWithReason"] / o_full["holeYears"], 4)
   if o_full["holeYears"] else rep["missing"]["reasonCoverage"] is None,
   str(rep["missing"]["reasonCoverage"]))
_no_hole = az.analyze([R("A", y) for y in range(2020, 2025)], {"A"}, {}, None, P)
_no_hole["source"], _no_hole["isFinalOutput"] = "t", False
ok("구멍이 없으면 비율을 0이 아니라 None으로 둔다 (잴 수 없는 것과 0은 다르다)",
   qr.build(_no_hole, [R("A", 2020)])["missing"]["reasonCoverage"] is None)

# 시장 축 — UNKNOWN을 버리면 byMarket이 현재 상장분만의 비율인데 전체처럼 읽힌다.
tgt_m = {"A": {"group": "current", "market": "KOSPI"},
         "B": {"group": "current", "market": "KOSDAQ"},
         "C": {"group": "delisted", "market": "UNKNOWN"},
         "D": {"group": "delisted", "market": "UNKNOWN"}}
o_m = az.analyze(rows, done, {}, tgt_m, P)
ok("시장별 분모에 UNKNOWN이 남는다 (폐지분을 버리지 않는다)",
   o_m["corpsTargetedByMarket"] == {"KOSPI": 1, "KOSDAQ": 1, "UNKNOWN": 2},
   str(o_m["corpsTargetedByMarket"]))
ok("UNKNOWN이 폐지분과 같은지 값으로 남긴다 (다르면 byMarket의 뜻이 바뀐다)",
   o_m["marketUnknownIsDelisted"] is True)

# 기본값이 파일을 쓰지 않는 것 — 로컬 실행이 data/를 더럽히지 않아야 한다(절대 규칙 4).
qsrc = open(os.path.join(ROOT, "scripts/generate-quality-report.py"),
            encoding="utf-8").read()
ok("--out을 준 경우에만 파일을 쓴다", 'if a.out:' in qsrc and 'a.out' in qsrc)
ok("PIT 지연 분위수를 남긴다 (평균 하나로는 꼬리가 안 보인다)",
   set(rep["pit"]["disclosureLagDays"]) == {"min", "p25", "median", "p75", "p95", "max"},
   str(sorted(rep["pit"]["disclosureLagDays"])))

print(f"\n{'=' * 54}")
print(f"통과 {passed} · 실패 {failed}")
sys.exit(0 if failed == 0 else 1)
