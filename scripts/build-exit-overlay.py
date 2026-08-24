#!/usr/bin/env python3
"""exit overlay 승격 — Tier A + Tier B 통합, GATE-EP-1 해소 트랙 3단계.

`build-exit-reason-overlay.py`(Tier A, MERGED — 새 DART 호출 없음)와
`build-exit-reason-overlay-tierb.py`(Tier B, 나머지 5개 사유 — DART
list.json 조회)는 둘 다 로컬 진단 전용으로 이미 검증됐다(2026-08-24,
508종목 중 248종목=48.8% 분류). 이 스크립트는 그 둘을 그대로 재사용해
(새 로직 없음, 로직 중복 없음) `docs/A5-파일럿-exit-overlay-설계안.md` §1이
정의한 overlay 스키마로 합치고, `--promote`일 때만
`data/backfill/exitOverlay/`에 쓴다(규칙 4 — 기본은 dry-run).

우선순위: Tier A(MERGED)가 이미 분류한 corp은 Tier B가 건드리지 않는다
(tierb.py의 load_tier_a_classified()가 이미 이렇게 짜여 있다 — 여기서는
그 산출을 그대로 합치기만 한다).

사용:
    python scripts/build-exit-overlay.py --selftest
    python scripts/build-exit-overlay.py --dry-run       # DART 호출 O, data/backfill/ 쓰기 X
    python scripts/build-exit-overlay.py --promote        # DART 호출 O, data/backfill/exitOverlay/v1.jsonl 기록
"""
import argparse
import datetime
import gzip
import importlib.util
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT_DIR = os.path.join(ROOT, "data/backfill/exitOverlay")
POLICY_PATH = os.path.join(ROOT, "config/policies/exitOverlay.v1.json")
OVERLAY_VERSION = "v1"
STAGE_VERSION = "EO.0"

fails, warns = [], []


def chk(cond, msg):
    print(("  OK  " if cond else "  FAIL") + "  " + msg)
    if not cond:
        fails.append(msg)


def warn(cond, msg):
    print(("  OK  " if cond else "  WARN") + "  " + msg)
    if not cond:
        warns.append(msg)


def load_policy():
    with open(POLICY_PATH, encoding="utf-8") as f:
        return json.load(f)


def _load(name, filename):
    spec = importlib.util.spec_from_file_location(name, os.path.join(ROOT, "scripts", filename))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


tier_a = _load("tier_a", "build-exit-reason-overlay.py")
tier_b = _load("tier_b", "build-exit-reason-overlay-tierb.py")


def build_overlay_records(exit_rows, merger_rows, dart_key, counters):
    """Tier A → Tier B 순서로 분류하고 overlay 스키마로 정규화한다."""
    classified_at = datetime.date.today().isoformat()

    tierA_classified, tierA_buckets = tier_a.classify(exit_rows, merger_rows)
    tierA_corps = {c["corp"] for c in tierA_classified}

    records = []
    for c in tierA_classified:
        records.append({
            "corp": c["corp"], "ticker": c["ticker"], "corpName": c.get("corpName"),
            "exitReason": c["exitReason"], "exitAtConfirmed": c["exitAtConfirmed"],
            "source": "tierA-mergerSpinoff",
            "evidence": {
                "rceptNo": c["evidenceRceptNo"], "disclosureDate": c["evidenceDisclosureDate"],
                "reportNm": c["evidenceReportNm"], "diffDays": c["diffDays"],
            },
            "overlayVersion": OVERLAY_VERSION, "classifiedAt": classified_at,
        })

    pool = [r for r in exit_rows if r["corp"] not in tierA_corps]
    tierB_classified, tierB_unclassified, tierB_buckets = [], [], {"ambiguousAuditCapital": 0, "noSignal": 0}
    for row in pool:
        corp = row["corp"]
        exit_at = tier_b.to_date(row["exitAtConfirmed"])
        bgn_de = (exit_at - datetime.timedelta(days=tier_b.WINDOW_DAYS)).strftime("%Y%m%d")
        end_de = exit_at.strftime("%Y%m%d")
        rows = tier_b.list_disclosures_i(dart_key, corp, bgn_de, end_de, counters)
        report_nms = [str(r.get("report_nm") or "") for r in rows]
        reason, evidence = tier_b.classify_report_nms(report_nms)
        if reason:
            tierB_classified.append({
                "corp": corp, "ticker": row.get("ticker"), "corpName": row.get("corpName"),
                "exitReason": reason, "exitAtConfirmed": row["exitAtConfirmed"],
                "source": "tierB-dart-list-i",
                "evidence": {"matchedReportNms": {k: v for k, v in evidence.items() if v}},
                "overlayVersion": OVERLAY_VERSION, "classifiedAt": classified_at,
            })
        else:
            if evidence["auditOpinion"] and evidence["capitalImpairment"]:
                tierB_buckets["ambiguousAuditCapital"] += 1
            elif not any(evidence.values()):
                tierB_buckets["noSignal"] += 1
            tierB_unclassified.append(corp)

    records.extend(tierB_classified)
    records.sort(key=lambda r: r["corp"])  # 결정론 — manifest 해시가 순서에 민감하다

    diag = {
        "overlayVersion": OVERLAY_VERSION,
        "generatedAt": datetime.datetime.now().isoformat(timespec="seconds"),
        "exitAtConfirmedTotal": len(exit_rows),
        "tierA": {"classified": len(tierA_classified), "buckets": tierA_buckets},
        "tierB": {
            "pool": len(pool), "classified": len(tierB_classified),
            "callsTotal": counters["calls"], "listErrors": counters["listErrors"],
            "unclassifiedBuckets": tierB_buckets,
        },
        "totalClassified": len(records),
        "totalUnknown": len(exit_rows) - len(records),
        "classifiedRate": round(len(records) / len(exit_rows), 4) if exit_rows else None,
        "distribution": {},
    }
    for r in records:
        diag["distribution"][r["exitReason"]] = diag["distribution"].get(r["exitReason"], 0) + 1
    return records, diag


def selftest():
    checks = []

    def check(name, cond):
        checks.append((name, bool(cond)))

    exit_rows = [
        {"corp": "A", "ticker": "000001", "corpName": "합병180일이내", "exitAtConfirmed": "2020-06-30"},
        {"corp": "B", "ticker": "000002", "corpName": "TierB자진상폐대상", "exitAtConfirmed": "2020-06-30"},
        {"corp": "C", "ticker": "000003", "corpName": "둘다무신호", "exitAtConfirmed": "2020-06-30"},
    ]
    merger_rows = [
        {"corp": "A", "rceptNo": "1", "disclosureDate": "20200401", "reportNm": "주요사항보고서(회사합병결정)"},
    ]

    class FakeCounters(dict):
        pass

    # Tier B 경로를 실제 DART 호출 없이 검증하기 위해 list_disclosures_i를 몽키패치한다.
    orig = tier_b.list_disclosures_i
    fake_reports = {"B": ["주권매매거래정지(자진상장폐지 신청)"], "C": ["주주총회소집결의"]}

    def fake_list(key, corp, bgn_de, end_de, counters):
        counters["calls"] += 1
        return [{"report_nm": nm} for nm in fake_reports.get(corp, [])]

    tier_b.list_disclosures_i = fake_list
    try:
        counters = {"calls": 0, "listErrors": {}}
        records, diag = build_overlay_records(exit_rows, merger_rows, "fake-key", counters)
    finally:
        tier_b.list_disclosures_i = orig

    by_corp = {r["corp"]: r for r in records}
    check("A는 Tier A(MERGED)로 분류됨", by_corp.get("A", {}).get("exitReason") == "MERGED")
    check("A의 source가 tierA-mergerSpinoff", by_corp.get("A", {}).get("source") == "tierA-mergerSpinoff")
    check("B는 Tier A를 건너뛰고 Tier B(VOLUNTARY)로 분류됨", by_corp.get("B", {}).get("exitReason") == "VOLUNTARY")
    check("B의 source가 tierB-dart-list-i", by_corp.get("B", {}).get("source") == "tierB-dart-list-i")
    check("C는 어느 tier도 못 잡아 overlay에 없음(UNKNOWN 유지, 지어내지 않음)", "C" not in by_corp)
    check("레코드가 corp로 정렬됨(결정론)", [r["corp"] for r in records] == sorted(by_corp.keys()))
    check("Tier B는 A가 이미 분류한 corp을 재조회하지 않음", counters["calls"] == 2)
    check("diag.totalClassified == 2", diag["totalClassified"] == 2)
    check("diag.totalUnknown == 1 (C)", diag["totalUnknown"] == 1)
    check("모든 레코드에 overlayVersion이 박힘", all(r["overlayVersion"] == OVERLAY_VERSION for r in records))

    ok = all(c for _, c in checks)
    for name, c in checks:
        print(("  PASS  " if c else "  FAIL  ") + name)
    print()
    print("통과 %d · 실패 %d" % (sum(c for _, c in checks), sum(not c for _, c in checks)))
    return 0 if ok else 1


def run(promote):
    pol = load_policy()
    dpath = os.path.join(OUT_DIR, "_diagnostics.json")

    key = os.environ.get("DART_API_KEY", "")
    if not key:
        diag = {"stage": "EO", "stageVersion": STAGE_VERSION}
        if promote:
            diag.update({"aborted": True, "abortReason": "DART_API_KEY 없음"})
            os.makedirs(OUT_DIR, exist_ok=True)
            with open(dpath, "w", encoding="utf-8") as f:
                json.dump(diag, f, ensure_ascii=False, indent=2)
        print("DART_API_KEY 없음 — .env를 셸에 로드했는지 확인")
        return 1

    exit_rows = tier_a.read_jsonl_gz(tier_a.EXIT_PATH)
    merger_rows = tier_a.read_jsonl_gz(tier_a.MERGER_PATH)
    print(f"exitAtConfirmed 종목: {len(exit_rows)}, mergerSpinoff 공시: {len(merger_rows)}")

    counters = {"calls": 0, "listErrors": {}}
    records, diag = build_overlay_records(exit_rows, merger_rows, key, counters)
    diag["stage"] = "EO"
    diag["stageVersion"] = STAGE_VERSION
    diag["exitOverlayPolicy"] = pol["version"]

    print(f"\ntotal classified: {diag['totalClassified']} / {diag['exitAtConfirmedTotal']} "
          f"({100*diag['classifiedRate']:.1f}%)" if diag["classifiedRate"] is not None else "")
    print("distribution:", json.dumps(diag["distribution"], ensure_ascii=False))
    print("DART calls:", counters["calls"], "listErrors:", counters["listErrors"])

    inject = os.environ.get("EO_FAIL_INJECTION", "").strip()
    if inject:
        diag["failInjection"] = inject
        chk(False, f"[FAIL INJECTION] {inject} — 게이트 검증용 강제 실패")

    a = pol["acceptance"]
    total_list_calls = counters["calls"]
    error_calls = sum(n for st, n in counters["listErrors"].items())
    list_error_rate = round(error_calls / total_list_calls, 4) if total_list_calls else 0.0
    diag["tierBListErrorRate"] = list_error_rate
    warn(list_error_rate <= a["tierBListErrorRateWarn"],
         f"Tier B list.json 오류율 {list_error_rate*100:.2f}% <= {a['tierBListErrorRateWarn']*100:.0f}%")
    warn((diag["classifiedRate"] or 0) >= a["minClassifiedRateWarn"],
         f"전체 분류율 {100*(diag['classifiedRate'] or 0):.1f}% >= {a['minClassifiedRateWarn']*100:.0f}%")

    diag["acceptanceFails"] = list(fails)
    diag["acceptanceWarns"] = list(warns)
    diag["acceptancePassed"] = not fails

    if fails:
        print(f"\n인수 조건 {len(fails)}건 실패 — 산출물을 쓰지 않는다")
        for x in fails:
            print(f"  - {x}")
        if promote:
            os.makedirs(OUT_DIR, exist_ok=True)
            with open(dpath, "w", encoding="utf-8") as f:
                json.dump(diag, f, ensure_ascii=False, indent=2)
        return 1

    if not promote:
        print("\n--dry-run — data/backfill/에 쓰지 않았다(규칙 4). 실제 승격은 --promote(GH Actions 전용).")
        return 0

    os.makedirs(OUT_DIR, exist_ok=True)
    out_path = os.path.join(OUT_DIR, f"{OVERLAY_VERSION}.jsonl")
    with open(out_path, "w", encoding="utf-8") as f:
        for r in records:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    with open(dpath, "w", encoding="utf-8") as f:
        json.dump(diag, f, ensure_ascii=False, indent=2)
    print(f"\nwrote {out_path} ({len(records)} records)")
    print(f"wrote {dpath}")
    return 0


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--selftest", action="store_true")
    ap.add_argument("--dry-run", action="store_true", help="DART 호출은 하되 data/backfill/에 쓰지 않는다(기본값과 동일, 명시용)")
    ap.add_argument("--promote", action="store_true", help="data/backfill/exitOverlay/에 쓴다 (GH Actions 전용)")
    args = ap.parse_args()
    if args.selftest:
        return selftest()
    return run(promote=args.promote)


if __name__ == "__main__":
    sys.exit(main())
