#!/usr/bin/env python3
"""exitReason 복원 — Tier A (2026-08-24, BF-1.1 GATE-EP 해소 트랙 1단계)

배경: `config/policies/exit.v1.json`이 요구하는 exitReason은 A1b(폐지 유니버스)
1,223건 전량이 `UNKNOWN`이다(`build-universe-a1b.py`의 정책 기본값 —
exitReasonPending: true로 명시된 대로 의도된 미완이다). GATE-EP-1(§6.4,
BF-1.1-백필계약.md)이 UNKNOWN>5%면 A6 Primary 결론을 막는데 지금은 100%다.

2026-08-16에 한 번 시도됐던 접근(`dartModifyDate`를 폐지일 근사로 써서 그
주변 DART 공시를 찾는다)은 폐기됐다 — dartModifyDate가 실제 폐지일과
수개월~수년씩 어긋나는 배치값이라는 게 그때 확인됐다(§ BF-1.1-백필계약.md
"dartModifyDate는 exitAt이 아니다"). 그 시도 이후(2026-08-17) A2b가
`delisted-exit.jsonl.gz`에 **가격 데이터로 실측한** `exitAtConfirmed`를
만들어 놨다 — dartModifyDate보다 훨씬 신뢰 가능한 앵커다.

Tier A는 이 앵커로 **새 DART 호출 없이** 이미 커밋된 A3d 산출물
(`mergerSpinoff.jsonl.gz` — A1a·A1b 전체를 대상으로 이미 수집된 회사합병·
분할·주식교환 공시)을 재사용한다. 폐지일(exitAtConfirmed) 이전
`WINDOW_DAYS`일 이내에 mergerSpinoff 공시가 있으면 그 폐지의 원인이라고
보고 exitReason=MERGED로 분류한다. 그 창을 벗어나거나(오래전 공시, 무관할
가능성) 폐지 이후에 뜬 공시(그 법인이 존속법인으로 남아 이후에도 보고를
계속한 경우 등)는 분류하지 않는다 — UNKNOWN으로 남긴다, 지어내지 않는다.

WINDOW_DAYS=365 실측 근거(2026-08-24, 508종목 대조): 180일 이내 94건·
365일 이내 누적 179건·730일 이내 188건·730일 초과(무관 가능성 높음) 22건·
폐지 이후 공시(원인일 수 없음) 37건. 365일에서 끊은 이유: 730일까지 늘려도
겨우 9건 더 느는데(179→188) 인과관계 근거는 오히려 약해진다(공시-폐지
간격이 멀수록 그 사이 다른 사건이 끼어 있을 가능성이 커진다) — 교훈 4번
(a3c_bracket_ratio expected_direction)과 같은 "추측하지 않는다" 원칙.

Tier B(합병 외 사유 — BANKRUPTCY·AUDIT_OPINION·DELISTING_REVIEW_FAILED·
CAPITAL_IMPAIRMENT·VOLUNTARY)는 새 DART list.json 조회가 필요해 범위 밖.

**이 스크립트는 로컬 진단 전용이다(규칙 4)** — data/backfill/에 쓰지
않는다. 산출물은 저장소 루트의 scratch-exit-reason-overlay-tierA.json
(untracked, 기존 scratch-*.json 관례와 동일)뿐이다. A1b delisted.jsonl에
이 결과를 실제로 반영(overlay 승격)하는 것은 별도 실행 단계 — GitHub
Actions manifest 파이프라인으로 가야 한다(Tier B 설계 완료 후 함께 승격
하는 편이 재실행 비용이 적다).

입력(둘 다 이미 로컬에 있는 committed 산출물, 새 수집 없음):
  data/backfill/price/a2b/delisted-exit.jsonl.gz       exitAtConfirmed
  data/backfill/fundamentals/a3d/mergerSpinoff.jsonl.gz  합병·분할·주식교환 공시

사용:
    python scripts/build-exit-reason-overlay.py --selftest
    python scripts/build-exit-reason-overlay.py
"""
import argparse
import datetime
import gzip
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
EXIT_PATH = os.path.join(ROOT, "data/backfill/price/a2b/delisted-exit.jsonl.gz")
MERGER_PATH = os.path.join(ROOT, "data/backfill/fundamentals/a3d/mergerSpinoff.jsonl.gz")
OUT_PATH = os.path.join(ROOT, "scratch-exit-reason-overlay-tierA.json")

WINDOW_DAYS = 365


def read_jsonl_gz(path):
    with gzip.open(path, "rt", encoding="utf-8") as f:
        return [json.loads(line) for line in f if line.strip()]


def to_date(s):
    """YYYYMMDD 또는 YYYY-MM-DD 문자열을 date로."""
    t = s.replace("-", "")
    return datetime.date(int(t[:4]), int(t[4:6]), int(t[6:8]))


def classify(exit_rows, merger_rows, window_days=WINDOW_DAYS):
    """corp별 가장 최근 mergerSpinoff 공시를 골라, exitAt 이전
    window_days 이내면 MERGED로 분류. 그 외는 분류하지 않는다(누락, 지어내지
    않음)."""
    latest_by_corp = {}
    for r in merger_rows:
        prev = latest_by_corp.get(r["corp"])
        if prev is None or r["disclosureDate"] > prev["disclosureDate"]:
            latest_by_corp[r["corp"]] = r

    classified, buckets = [], {
        "within180": 0, "within365": 0, "within730": 0,
        "farBefore": 0, "afterExit": 0, "noMergerRecord": 0,
    }
    for exit_row in exit_rows:
        corp = exit_row["corp"]
        m = latest_by_corp.get(corp)
        if m is None:
            buckets["noMergerRecord"] += 1
            continue
        d_exit = to_date(exit_row["exitAtConfirmed"])
        d_disc = to_date(m["disclosureDate"])
        diff_days = (d_exit - d_disc).days
        if diff_days < 0:
            buckets["afterExit"] += 1
            continue
        if diff_days <= 180:
            buckets["within180"] += 1
        elif diff_days <= 365:
            buckets["within365"] += 1
        elif diff_days <= 730:
            buckets["within730"] += 1
        else:
            buckets["farBefore"] += 1
        if diff_days <= window_days:
            classified.append({
                "corp": corp, "ticker": exit_row["ticker"],
                "corpName": exit_row.get("corpName"),
                "exitReason": "MERGED",
                "exitAtConfirmed": exit_row["exitAtConfirmed"],
                "evidenceRceptNo": m["rceptNo"],
                "evidenceDisclosureDate": m["disclosureDate"],
                "evidenceReportNm": m["reportNm"],
                "diffDays": diff_days,
                "source": "a3d-mergerSpinoff-temporal-join",
            })
    return classified, buckets


def selftest():
    checks = []

    def check(name, cond):
        checks.append((name, bool(cond)))

    exit_rows = [
        {"corp": "A", "ticker": "000001", "corpName": "합병케이스180일이내",
         "exitAtConfirmed": "2020-06-30"},
        {"corp": "B", "ticker": "000002", "corpName": "합병케이스730일초과",
         "exitAtConfirmed": "2020-06-30"},
        {"corp": "C", "ticker": "000003", "corpName": "공시가폐지이후",
         "exitAtConfirmed": "2020-06-30"},
        {"corp": "D", "ticker": "000004", "corpName": "합병기록없음",
         "exitAtConfirmed": "2020-06-30"},
    ]
    merger_rows = [
        {"corp": "A", "rceptNo": "1", "disclosureDate": "20200401",
         "reportNm": "주요사항보고서(회사합병결정)"},   # 90일 전
        {"corp": "B", "rceptNo": "2", "disclosureDate": "20170101",
         "reportNm": "주요사항보고서(회사합병결정)"},   # 3년 전, 무관 가능성
        {"corp": "C", "rceptNo": "3", "disclosureDate": "20201001",
         "reportNm": "주요사항보고서(회사합병결정)"},   # 폐지 이후
    ]
    classified, buckets = classify(exit_rows, merger_rows, window_days=365)
    corps = {c["corp"] for c in classified}

    check("180일 이내 공시(A)는 MERGED로 분류됨", "A" in corps)
    check("730일 초과 공시(B)는 창 밖이라 분류 안 됨", "B" not in corps)
    check("폐지 이후 공시(C)는 원인일 수 없어 분류 안 됨", "C" not in corps)
    check("공시 기록 자체가 없는 corp(D)는 UNKNOWN으로 남음", "D" not in corps)
    check("buckets.within180 == 1 (A)", buckets["within180"] == 1)
    check("buckets.farBefore == 1 (B)", buckets["farBefore"] == 1)
    check("buckets.afterExit == 1 (C)", buckets["afterExit"] == 1)
    check("buckets.noMergerRecord == 1 (D)", buckets["noMergerRecord"] == 1)
    check("A의 evidenceRceptNo가 정확히 이식됨",
          next(c for c in classified if c["corp"] == "A")["evidenceRceptNo"] == "1")

    ok = all(c for _, c in checks)
    for name, c in checks:
        print(("  PASS  " if c else "  FAIL  ") + name)
    print()
    print("통과 %d · 실패 %d" % (sum(c for _, c in checks), sum(not c for _, c in checks)))
    return 0 if ok else 1


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--selftest", action="store_true")
    args = ap.parse_args()
    if args.selftest:
        return selftest()

    exit_rows = read_jsonl_gz(EXIT_PATH)
    merger_rows = read_jsonl_gz(MERGER_PATH)
    print("exitAtConfirmed 종목: %d, mergerSpinoff 공시: %d" % (len(exit_rows), len(merger_rows)))

    classified, buckets = classify(exit_rows, merger_rows)
    out = {
        "generatedAt": datetime.datetime.now().isoformat(timespec="seconds"),
        "tier": "A",
        "windowDays": WINDOW_DAYS,
        "note": "로컬 진단 산출물 — data/backfill/에 쓰지 않는다(규칙 4). "
                "실제 반영은 별도 GitHub Actions 승격 단계에서.",
        "inputCounts": {"exitAtConfirmed": len(exit_rows), "mergerSpinoff": len(merger_rows)},
        "buckets": buckets,
        "classifiedCount": len(classified),
        "classifiedRate": round(len(classified) / len(exit_rows), 4) if exit_rows else None,
        "classified": classified,
    }
    with open(OUT_PATH, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=2)
    print("classified: %d / %d (%.1f%%)" % (
        len(classified), len(exit_rows),
        100 * len(classified) / len(exit_rows) if exit_rows else 0))
    print("buckets:", json.dumps(buckets, ensure_ascii=False))
    print("wrote", OUT_PATH)
    return 0


if __name__ == "__main__":
    sys.exit(main())
