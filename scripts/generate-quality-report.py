#!/usr/bin/env python3
"""A3 재무 품질 리포트 — QR-1.0 스키마로 quality.json을 만든다.

  python scripts/generate-quality-report.py                  # stdout
  python scripts/generate-quality-report.py --out PATH       # 파일로
  python scripts/generate-quality-report.py --check          # 스키마 검사만

**계산은 여기 없다.** 전부 analyze-fundamentals-a3.py의 analyze() 하나에서 나오고,
이 스크립트는 그 결과를 고정된 스키마로 담기만 한다. 계산을 양쪽에 두면 사람이 읽는
수치와 기계가 읽는 수치가 갈리고, 갈린 순간 둘 다 못 믿는다(교훈44).

  analyze-fundamentals-a3.py   계산 + 사람이 읽는 뷰
  generate-quality-report.py   같은 계산 → QR-1.0 스키마 → quality.json

**파생 결과를 저장하는 것이 원칙에 어긋나지 않는가?** 어긋난다 — 그래서 낡음을
탐지할 수 있게 만든다. 리포트는 자기가 무엇으로부터 계산됐는지를 함께 들고 다닌다
(inputDigest · corpsDone · isFinalOutput · generatedAt). 다시 만들어 digest가 다르면
그 리포트는 낡은 것이고, 그 사실이 값으로 증명된다. **저장하되 조용히 낡지 않게 한다.**

기본은 stdout이다. --out을 준 경우에만 파일을 쓴다 — 로컬 실행이 data/를 더럽히지
않는 것이 기본값이어야 한다(절대 규칙 4).
"""
import argparse
import hashlib
import importlib.util
import json
import os
import sys
from datetime import datetime, timedelta, timezone

for _s in (sys.stdout, sys.stderr):
    if hasattr(_s, "reconfigure"):
        _s.reconfigure(errors="replace")

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_spec = importlib.util.spec_from_file_location(
    "az", os.path.join(ROOT, "scripts", "analyze-fundamentals-a3.py"))
az = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(az)

KST = timezone(timedelta(hours=9))

# 스키마 버전. 칸을 늘리거나 뜻을 바꾸면 올린다 — 리포트를 시계열로 비교할 때
# 어느 버전끼리 비교 가능한지가 값으로 남아야 한다.
SCHEMA = "QR-1.0"

# 필수 섹션과 그 안의 필수 키. 이 표 하나가 스키마의 단일 출처다.
# 칸을 늘리려면 여기에 등록해야 하고, 그러면 --check가 강제한다.
REQUIRED = {
    "meta": ["schema", "generatedAt", "source", "isFinalOutput", "inputDigest",
             "corpsDone", "corpsTargeted", "sampleComplete"],
    "coverage": ["overall", "byYear", "byGroup", "byMarket", "byCorp"],
    "missing": ["byReason", "holeYears", "holeYearsWithReason",
                "holeYearsWithoutReason", "reasonCoverage"],
    "pit": ["measured", "futureLeak", "disclosureLagDays", "lagOver180d",
            "lagOver365d", "periodEndMonth"],
    "schemaQuality": ["accountPresence", "accountSourceByAccount", "coreComplete",
                      "coreCompleteRate", "fsDivRecords", "fsDivByCorp", "currency",
                      "nonKrwRecords"],
    "patterns": ["fullRange", "internalHoles", "tailCut", "headLate",
                 "tailCutByLastYear", "notMutuallyExclusive"],
}


def input_digest(rows):
    """이 리포트가 무엇으로부터 나왔는가. 레코드 키만으로 만든다 —
    값이 바뀌어도 같은 키집합이면 같은 수집분이고, 그것이 낡음 판정의 축이다."""
    h = hashlib.sha256()
    for k in sorted(f"{r['corp']}|{r['fiscalYear']}|{r.get('availableFrom')}"
                    for r in rows):
        h.update(k.encode())
    return "sha256:" + h.hexdigest()[:16]


def build(o, rows):
    """analyze()의 결과를 QR-1.0으로 담는다. 여기서 새로 계산하지 않는다."""
    targeted = o.get("corpsTargeted")
    return {
        "meta": {
            "schema": SCHEMA,
            "generatedAt": datetime.now(KST).isoformat(timespec="seconds"),
            "source": o["source"],
            "isFinalOutput": o["isFinalOutput"],
            "inputDigest": input_digest(rows),
            "corpsDone": o["corpsDone"],
            "corpsTargeted": targeted,
            # 전수인가. 부분이면 아래 수치는 경향이지 확정값이 아니다 —
            # FN-1.4 임계는 이 값이 true인 리포트에서만 정한다.
            "sampleComplete": bool(o["isFinalOutput"]
                                   and targeted and o["corpsDone"] == targeted),
        },
        "coverage": {
            "overall": {
                "records": o["records"],
                "corpsWithRecords": o["corpsWithRecords"],
                "corpsDone": o["corpsDone"],
                "corpsTargeted": targeted,
                "corpsDoneWithNoRecords": o["corpsDoneWithNoRecords"],
                "rate": (round(o["corpsWithRecords"] / targeted, 4)
                         if targeted else None),
            },
            "byYear": {
                "records": o["recordsByYear"],
                "corps": o["corpsByYear"],
                "corpsMedian": o["corpsByYearMedian"],
                # 특정 연도만 급락하는 것이 계약 2가 잡으려는 실패 모드다.
                "corpsRatioToMedian": o["corpsByYearRatioToMedian"],
            },
            "byGroup": {
                "targeted": o.get("corpsTargetedByGroup"),
                "withRecords": o.get("corpsWithRecordsByGroup"),
                "rate": o.get("corpsWithRecordsRateByGroup"),
            },
            "byMarket": {
                "targeted": o.get("corpsTargetedByMarket"),
                "withRecords": o.get("corpsWithRecordsByMarket"),
                "rate": o.get("corpsWithRecordsRateByMarket"),
                # UNKNOWN은 폐지분이다. A1b의 출처가 DART corpCode 차집합이라 시장
                # 구분을 들고 있지 않다. 버리면 byMarket이 현재 상장분만의 비율인데
                # 전체처럼 읽힌다 — 모르는 것은 0이 아니고 버릴 것도 아니다.
                "unknownIsDelisted": o.get("marketUnknownIsDelisted"),
            },
            "byCorp": {
                "fullRange": o["fullRange"],
                "withInternalHoles": o["internalHoles"],
                "withTailCut": o["tailCut"],
                "withHeadLate": o["headLate"],
            },
        },
        "missing": {
            # 013 / REJECT / HARD / EMPTY / STATUS / EARLY_STOP
            "byReason": o["recordGapReasons"],
            "corpsWithGapRecord": o["recordGapCorps"],
            "holeYears": o["holeYears"],
            "holeYearsWithReason": o["holeYearsWithReason"],
            "holeYearsWithoutReason": o["holeYearsWithoutReason"],
            # 사유를 아는 비율. recordGaps는 그 필드 도입 뒤 스캔한 법인에만 쌓이므로
            # 1.0이 아닐 수 있고, 그 사실이 여기 값으로 남는다.
            "reasonCoverage": (round(o["holeYearsWithReason"] / o["holeYears"], 4)
                               if o["holeYears"] else None),
            "corpsDoneWithNoRecordsWithReason": o["corpsDoneWithNoRecordsWithReason"],
            "internalHolesDetail": o["internalHolesDetail"],
        },
        "pit": {
            "measured": o["pit"]["measured"],
            # 0이어야 한다. 이 축은 조용히 무너진다 — 위반이 있어도 점수·등급은
            # 정상으로 보이고 백테스트만 좋아진다.
            "futureLeak": o["pit"]["futureLeak"],
            "futureLeakSample": o["pit"]["futureLeakSample"],
            "disclosureLagDays": o["pit"]["disclosureLagDays"],
            "lagOver180d": o["pit"]["lagOver180d"],
            "lagOver365d": o["pit"]["lagOver365d"],
            "periodEndMonth": o["periodEndMonth"],
        },
        "schemaQuality": {
            "accountPresence": o["accountPresence"],
            "accountSourceByAccount": o["accountSourceByAccount"],
            "accountSource": o["accountSource"],
            # 분자에 유동자산·유동부채를 넣지 않는다 — 금융업에는 그 계정이 없어
            # 업종 구성이 데이터 품질로 둔갑한다(교훈48).
            "coreAccounts": az.CORE,
            "coreComplete": o["coreComplete"],
            "coreCompleteRate": o["coreCompleteRate"],
            "fsDivRecords": o["fsDivRecords"],
            "fsDivByCorp": o["fsDivByCorp"],
            "currency": o["currency"],
            "nonKrwRecords": o["nonKrwRecords"],
        },
        "patterns": {
            "fullRange": o["fullRange"],
            "internalHoles": o["internalHoles"],
            "tailCut": o["tailCut"],
            "headLate": o["headLate"],
            "tailCutByLastYear": o["tailCutByLastYear"],
            # 세 유형은 배타적이지 않다. 한 법인이 앞 늦음이면서 구멍이면서 뒤 잘림일
            # 수 있어 합계를 내지 않는다 — 합치면 이중계상이다. 이 플래그가 그 사실을
            # 리포트를 읽는 쪽에 전달한다.
            "notMutuallyExclusive": True,
        },
    }


def check(rep):
    """스키마 검사. 칸이 비어 있는 것과 칸이 없는 것은 다르다."""
    bad = []
    for sec, keys in REQUIRED.items():
        if sec not in rep:
            bad.append(f"섹션 없음: {sec}")
            continue
        for k in keys:
            if k not in rep[sec]:
                bad.append(f"{sec}.{k} 없음")
    if rep.get("meta", {}).get("schema") != SCHEMA:
        bad.append(f"schema가 {SCHEMA}가 아니다: {rep.get('meta', {}).get('schema')}")
    return bad


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", help="쓸 경로. 주지 않으면 stdout (data/를 더럽히지 않는다)")
    ap.add_argument("--check", action="store_true", help="스키마 검사만 하고 끝낸다")
    a = ap.parse_args()

    os.chdir(ROOT)
    pol = json.load(open(az.POLICY, encoding="utf-8"))
    rows, source, is_final = az.load_records()
    if not rows:
        print("A3 레코드가 없다 — 수집을 먼저 돌려라", file=sys.stderr)
        return 1
    done, gaps, _ = az.load_state()
    o = az.analyze(rows, done, gaps, az.target_corps(), pol)
    o["source"], o["isFinalOutput"] = source, is_final
    rep = build(o, rows)

    bad = check(rep)
    if bad:
        print("스키마 위반:", file=sys.stderr)
        for b in bad:
            print(f"  - {b}", file=sys.stderr)
        return 1
    if a.check:
        print(f"{SCHEMA} 스키마 통과 — 섹션 {len(REQUIRED)}개")
        return 0

    text = json.dumps(rep, ensure_ascii=False, indent=2)
    if a.out:
        os.makedirs(os.path.dirname(a.out) or ".", exist_ok=True)
        with open(a.out, "w", encoding="utf-8", newline="\n") as f:
            f.write(text + "\n")
        m = rep["meta"]
        print(f"{a.out} — {SCHEMA} · {m['inputDigest']} · "
              f"전수 {m['sampleComplete']} · 법인 {m['corpsDone']}/{m['corpsTargeted']}")
    else:
        print(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
