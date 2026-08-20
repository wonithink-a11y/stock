#!/usr/bin/env python3
"""A3d 회귀 — 순수 함수(classify·서브분류·A3c 브래킷)를 실사례+합성 픽스처로 검증.
  python scripts/test-fundamentals-a3d.py

네트워크를 안 쓴다. 정답은 이번 세션에 DART API로 실제 확인한 값이다(브리프
§3.6·§16.3·§19) — A3d 산출물 자체로 정답표를 만들지 않는다(교훈72).
"""
import importlib.util
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
os.chdir(ROOT)
spec = importlib.util.spec_from_file_location(
    "a3d", os.path.join(ROOT, "scripts", "build-fundamentals-a3d.py"))
m = importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)

POL = json.load(open("config/policies/fundamentals.v1.json", encoding="utf-8"))
A3D = POL["a3d"]

passed = failed = 0


def ok(label, cond, detail=""):
    global passed, failed
    print(("  OK    " if cond else "  FAIL  ") + label
          + (f"  — {detail}" if not cond and detail else ""))
    if cond:
        passed += 1
    else:
        failed += 1


print("[classify — 실제 report_nm 문자열, §15·§3.6·goldenset 실사례]")
cats = A3D["categories"]
ok("005930류 독립형 '주식분할결정' → split (§3.6 인용, OR의 한쪽)",
   m.classify("주식분할결정", cats) == ["split"])
ok("079650 '주권매매거래정지해제(액면분할 주권 변경상장)' → split (goldenset 실측 다수형)",
   m.classify("주권매매거래정지해제(액면분할 주권 변경상장)", cats) == ["split"])
ok("goldenset 실측 '주권매매거래정지해제(액면병합 주권 변경상장)' → reverseOrConsolidation",
   m.classify("주권매매거래정지해제(액면병합 주권 변경상장)", cats) == ["reverseOrConsolidation"])
ok("goldenset 실측 '주권매매거래정지해제(주식병합(무액면주식) 주권 변경상장)' → reverseOrConsolidation",
   m.classify("주권매매거래정지해제(주식병합(무액면주식) 주권 변경상장)", cats) == ["reverseOrConsolidation"])
ok("★ 애매한 정지 통보(해제 아님) '주권매매거래정지(주식의 병합, 분할 등 전자등록 변경, 말소)'는 "
   "의도적으로 매칭 안 됨(분할·병합 구분 불가, goldenset 66건 실측)",
   m.classify("주권매매거래정지(주식의 병합, 분할 등 전자등록 변경, 말소)", cats) == [])
ok("goldenset 실측 '주권매매거래정지해제(감자 주권 및 액면분할 변경상장)' → split "
   "(감자는 이제 list.json이 아니라 crDecsn에서 별도로 나온다 — 같은 corp에서 "
   "가까운 시점에 잡히면 resolver.js의 COMPOUND_EVENT가 처리)",
   m.classify("주권매매거래정지해제(감자 주권 및 액면분할 변경상장)", cats) == ["split"])
ok("'주요사항보고서(회사합병결정)' → mergerSpinoff",
   m.classify("주요사항보고서(회사합병결정)", cats) == ["mergerSpinoff"])
ok("'주요사항보고서(주식교환·이전결정)' → mergerSpinoff",
   m.classify("주요사항보고서(주식교환·이전결정)", cats) == ["mergerSpinoff"])
ok("무관한 공시('영업정지')는 빈 리스트",
   m.classify("영업정지", cats) == [])
ok("★ 2026-08-20 구조 변경 확인 — '감자결정'·'유상증자결정'·'무상증자결정'은 "
   "이제 categories 표에 없다(상세 API로 직접 수집, 아래 sub_classify 테스트 참고) "
   "— classify()로는 안 잡혀야 한다",
   m.classify("주요사항보고서(감자결정)", cats) == []
   and m.classify("주요사항보고서(유상증자결정)", cats) == []
   and m.classify("주요사항보고서(무상증자결정)", cats) == [])

print("\n[sub_classify_rights — 034020 + 스모크 테스트(gh run 32362600405) 실사례 40건]")
cls = A3D["classification"]
ok("034020 ic_mthn='주주배정후 실권주 일반공모' → rightsOfferingShareholders",
   m.sub_classify_rights("주주배정후 실권주 일반공모", cls) == "rightsOfferingShareholders")
ok("020560/079160류 ic_mthn='제3자배정증자' → rightsOfferingThirdParty",
   m.sub_classify_rights("제3자배정증자", cls) == "rightsOfferingThirdParty")
ok("★ 스모크 실측 '일반공모증자'(불특정다수 대상, 권리락 없음) → rightsOfferingThirdParty",
   m.sub_classify_rights("일반공모증자", cls) == "rightsOfferingThirdParty")
ok("★ 스모크 실측 '주주우선공모증자'(기존 주주 우선, 권리락 대상) → rightsOfferingShareholders",
   m.sub_classify_rights("주주우선공모증자", cls) == "rightsOfferingShareholders")
ok("알 수 없는 ic_mthn은 None(임의 배정하지 않는다)",
   m.sub_classify_rights("알수없는방식", cls) is None)
ok("ic_mthn 자체가 없으면(None) None", m.sub_classify_rights(None, cls) is None)

print("\n[sub_classify_capital_reduction — 065170·케이에이치건설·루트로닉 실사례]")
ok("065170 cr_mth='...무상병합' → capitalReductionFree",
   m.sub_classify_capital_reduction("기명식 보통주 10주를 동일한 액면주식 1주로 무상병합", cls)
   == "capitalReductionFree")
ok("루트로닉 cr_mth='유상소각(...)' → capitalReductionPaid",
   m.sub_classify_capital_reduction("유상소각(소각대금지급액1주당 37,579.20원 상환)", cls)
   == "capitalReductionPaid")
ok("매칭 안 되면 capitalReductionUnknown(유보 대상, 임의 배정 아님)",
   m.sub_classify_capital_reduction("알수없는방법", cls) == "capitalReductionUnknown")

print("\n[num — crDecsn·fricDecsn 응답 파싱]")
ok("'87.50' → 87.5 (float, cr_rt_ostk는 소수)", m.num("87.50") == 87.5)
ok("'-' → None (0으로 지어내지 않는다)", m.num("-") is None)
ok("None → None", m.num(None) is None)
ok("'2' → 2.0 (fricDecsn.nstk_ascnt_ps_ostk)", m.num("2") == 2.0)

print("\n[배수 계산 — 실사례 재현]")
ok("065170 무상감자: 1 - 90.0/100 = 0.1 (§16.3 실측과 일치)",
   round(1 - 90.0 / 100, 6) == 0.1)
ok("케이에이치건설 무상감자: 1 - 87.50/100 = 0.125",
   round(1 - 87.50 / 100, 6) == 0.125)
ok("065170 무상증자: 1 + 2 = 3 (§3.6 ×3 실측과 정확히 일치)",
   round(1 + 2.0, 6) == 3.0)

print("\n[a3c_bracket_ratio — 000860 실사례(6,500,000→13,000,000, ×2)]")
timeline = {
    "000860": [
        ("20240320", 6500000), ("20240516", 6500000), ("20240814", 6500000),
        ("20241114", 6500000), ("20250318", 6500000), ("20250515", 6500000),
        ("20250814", 13000000), ("20251114", 13000000),
    ]
}
ratio = m.a3c_bracket_ratio("000860", "20250326", timeline)
ok("공시일(2025-03-26)을 감싸는 두 레코드(20250515 이전값·20250814 이후값)의 비율 = 2.0",
   ratio == 2.0, str(ratio))
ok("종목 자체가 timeline에 없으면 None(지어내지 않는다)",
   m.a3c_bracket_ratio("999999", "20250326", timeline) is None)
ok("공시일이 timeline의 마지막 레코드보다 미래면(직후 값이 없으면) None",
   m.a3c_bracket_ratio("000860", "20260101", timeline) is None)
ok("공시일이 timeline의 첫 레코드보다 과거면(직전 값이 없으면) None",
   m.a3c_bracket_ratio("000860", "20200101", timeline) is None)

print("\n[_clean_ratio_distance — 정수/역수 근접도]")
ok("정확히 2.0 → 거리 0", m._clean_ratio_distance(2.0) == 0)
ok("정확히 0.5(2:1 병합) → 거리 0", m._clean_ratio_distance(0.5) == 0)
ok("1.97(2.0에서 1.5% 이탈) → 거리 약 0.015",
   abs(m._clean_ratio_distance(1.97) - 0.015) < 0.001, str(m._clean_ratio_distance(1.97)))
ok("None·0 이하는 None", m._clean_ratio_distance(None) is None and m._clean_ratio_distance(0) is None)

print("\n[validate — 구조 계약]")
rows = [
    {"corp": "00126380", "ticker": "005930", "category": "split",
     "rceptNo": "20180131000001", "disclosureDate": "20180131", "reportNm": "주식분할결정",
     "multiplier": 50.0, "multiplierSource": "a3cBracket", "rawIcMthn": None, "rawCrMth": None},
]
diag = {"corpsIncomplete": 0, "bracketOutOfTolerance": 0, "bracketSamples": 1}
m.validate(rows, POL, diag, from_output_only=True)
ok("정상 레코드는 인수 조건을 통과한다(FAIL 0건)", len(m.fails) == 0, str(m.fails))
m.fails.clear(); m.warns.clear()

bad_rows = rows + [{**rows[0], "corp": "0012638", "category": "split"}]  # corp 7자리(위반)
diag2 = {"corpsIncomplete": 0, "bracketOutOfTolerance": 0, "bracketSamples": 1}
m.validate(bad_rows, POL, diag2, from_output_only=True)
ok("corp 계약 위반(7자리)은 FAIL로 잡힌다", len(m.fails) > 0, str(m.fails))
m.fails.clear(); m.warns.clear()

print(f"\n{'='*54}")
print(f"통과 {passed} · 실패 {failed}")
sys.exit(0 if failed == 0 else 1)
