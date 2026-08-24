#!/usr/bin/env python3
"""exitReason 복원 — Tier B (2026-08-24, BF-1.1 GATE-EP 해소 트랙 2단계)

Tier A(`build-exit-reason-overlay.py`)는 새 DART 호출 없이 A3d
mergerSpinoff를 재사용해 508종목 중 179종목(35.2%)을 MERGED로 분류했다.
Tier B는 나머지 329종목(exitAtConfirmed는 있으나 Tier A가 못 분류한 것)을
대상으로, `docs/BF-1.1-백필계약.md` §5·§6.4가 요구하는 나머지 exitReason
(BANKRUPTCY·AUDIT_OPINION·DELISTING_REVIEW_FAILED·CAPITAL_IMPAIRMENT·
VOLUNTARY, `config/policies/exit.v1.json`의 enum)을 새 DART list.json 조회로
분류한다.

패턴은 지어내지 않았다 — 20개 무작위 표본(corp당 pblntf_ty=I, exitAtConfirmed
이전 730일)의 실제 report_nm을 먼저 읽고 나서 아래 다섯 정규식을 정했다
(scratch-tierb-sample.json, 로컬 진단 산출물, 커밋 안 함). 실측 근거:

  VOLUNTARY               "자진상장폐지" — SBI핀테크솔루션즈·한일네트웍스·
                           대양제지공업·신성통상 등에서 그대로 나타남
  BANKRUPTCY               "회생절차개시결정"·"부도발생"·"파산선고" — 비유
                           테크놀러지(회생절차개시결정)·플랜텍(부도발생).
                           "파산신청"(제출)·"파산신청기각"(기각)은 제외한다
                           — 비엔씨컴퍼니 실사례가 파산신청 후 기각됐는데도
                           결국 다른 사유로 폐지됐다. 결정된 사건만 anchor로
                           쓴다(A3d의 expected_direction과 같은 "추측하지
                           않는다" 원칙)
  AUDIT_OPINION            "의견거절"·"의견부적정"
  CAPITAL_IMPAIRMENT       "자본잠식"
  DELISTING_REVIEW_FAILED  "상장적격성실질심사" — 에프지엔개발전문자기관리
                           부동산투자회사·비유테크놀러지에서 확인

★ AUDIT_OPINION과 CAPITAL_IMPAIRMENT는 KRX의 공식 공시 템플릿 자체가 자주
합쳐서 낸다("반기검토의견부적정,의견거절또는완전자본잠식사실발생" — 성지건설
실사례, 제목만으로는 어느 쪽이 실제 방아쇠였는지 구분 불가). 한 corp의
검색범위 안에 두 키워드가 모두 나타나면(같은 제목이든 다른 공시든) 어느
하나로 단정하지 않고 UNKNOWN으로 남긴다 — 지어내지 않는다(교훈57). 이
ambiguousAuditCapital 건수를 진단에 남겨 다음 세션이 문서(공시 본문) 파싱
으로 더 열지 판단할 수 있게 한다.

우선순위(고정, 결과를 보기 전에 정함): VOLUNTARY > BANKRUPTCY >
(AUDIT_OPINION/CAPITAL_IMPAIRMENT, 모호하면 보류) > DELISTING_REVIEW_FAILED
> UNKNOWN. VOLUNTARY·BANKRUPTCY가 위인 이유는 둘 다 회사의 실제 선택/법적
절차라는 구체적 사실이고, DELISTING_REVIEW_FAILED("상장적격성실질심사")는
보통 audit/capital 등 더 구체적인 사유가 있은 뒤 뒤따르는 심사 절차라서
다른 신호가 전혀 없을 때만 최종 사유로 쓴다.

기업인수목적회사(SPAC) 청산·투자회사(선박투자회사 등) 만기청산처럼 다섯
카테고리 어디에도 안 맞는 실제 케이스도 표본에서 확인했다(교보14호·
케이비제18호·아시아퍼시픽13호선박투자회사) — 이들은 UNKNOWN으로 정직하게
남는다. enum을 늘리는 것은 이 스크립트의 범위 밖(config/policies/exit.v1.json
변경은 별도 🔴 결정).

**이 스크립트는 로컬 진단 전용이다(규칙 4)** — data/backfill/에 쓰지
않는다. 산출물은 저장소 루트의 scratch-exit-reason-overlay-tierB.json
(untracked)뿐이다. A1b delisted.jsonl 반영은 Tier A와 함께 별도 GitHub
Actions 승격 단계에서.

사용:
    python scripts/build-exit-reason-overlay-tierb.py --selftest
    python scripts/build-exit-reason-overlay-tierb.py           # 실제 DART 호출(~329콜)
"""
import argparse
import datetime
import gzip
import importlib.util
import json
import os
import re
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
EXIT_PATH = os.path.join(ROOT, "data/backfill/price/a2b/delisted-exit.jsonl.gz")
MERGER_PATH = os.path.join(ROOT, "data/backfill/fundamentals/a3d/mergerSpinoff.jsonl.gz")
OUT_PATH = os.path.join(ROOT, "scratch-exit-reason-overlay-tierB.json")

WINDOW_DAYS = 365  # Tier A와 같은 근거로 같은 값을 쓴다(간격이 멀수록 다른 사건 혼입 위험)
BASE = "https://opendart.fss.or.kr/api"
REQUEST_SLEEP_SECONDS = 0.12   # config/policies/fundamentals.v1.json과 동일 값
RETRY_ATTEMPTS = 4
RETRY_BACKOFF_BASE = 2
DART_NO_DATA = "013"
QUOTA_EXCEEDED_STATUS = "020"

VOLUNTARY_RE = re.compile(r"자진상장폐지")
BANKRUPTCY_RE = re.compile(r"회생절차개시결정|부도발생|파산선고")
AUDIT_OPINION_RE = re.compile(r"의견\s*거절|의견\s*부적정")
CAPITAL_IMPAIRMENT_RE = re.compile(r"자본잠식")
DELISTING_REVIEW_RE = re.compile(r"상장적격성\s*실질심사")


def read_jsonl_gz(path):
    with gzip.open(path, "rt", encoding="utf-8") as f:
        return [json.loads(line) for line in f if line.strip()]


def to_date(s):
    t = s.replace("-", "")
    return datetime.date(int(t[:4]), int(t[4:6]), int(t[6:8]))


def load_tier_a_classified():
    """Tier A 스크립트를 모듈로 불러와 이미 MERGED로 분류된 corp 집합을 얻는다
    (새 로직 중복 작성 없음)."""
    spec = importlib.util.spec_from_file_location(
        "tier_a", os.path.join(ROOT, "scripts/build-exit-reason-overlay.py"))
    tier_a = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(tier_a)
    exit_rows = read_jsonl_gz(EXIT_PATH)
    merger_rows = read_jsonl_gz(MERGER_PATH)
    classified, _ = tier_a.classify(exit_rows, merger_rows)
    return exit_rows, {c["corp"] for c in classified}


def classify_report_nms(report_nms):
    """corp 하나의 report_nm 목록(윈도 안) → (exitReason|None, evidence dict)."""
    joined_hits = {
        "voluntary": [nm for nm in report_nms if VOLUNTARY_RE.search(nm)],
        "bankruptcy": [nm for nm in report_nms if BANKRUPTCY_RE.search(nm)],
        "auditOpinion": [nm for nm in report_nms if AUDIT_OPINION_RE.search(nm)],
        "capitalImpairment": [nm for nm in report_nms if CAPITAL_IMPAIRMENT_RE.search(nm)],
        "delistingReview": [nm for nm in report_nms if DELISTING_REVIEW_RE.search(nm)],
    }
    if joined_hits["voluntary"]:
        return "VOLUNTARY", joined_hits
    if joined_hits["bankruptcy"]:
        return "BANKRUPTCY", joined_hits
    audit, capital = joined_hits["auditOpinion"], joined_hits["capitalImpairment"]
    if audit and capital:
        return None, joined_hits  # ambiguousAuditCapital — 지어내지 않는다
    if audit:
        return "AUDIT_OPINION", joined_hits
    if capital:
        return "CAPITAL_IMPAIRMENT", joined_hits
    if joined_hits["delistingReview"]:
        return "DELISTING_REVIEW_FAILED", joined_hits
    return None, joined_hits


def selftest():
    checks = []

    def check(name, cond):
        checks.append((name, bool(cond)))

    r, h = classify_report_nms(["주권매매거래정지(자진상장폐지 신청)", "감사보고서제출"])
    check("자진상장폐지 → VOLUNTARY", r == "VOLUNTARY")

    r, h = classify_report_nms(["회생절차개시결정", "감사보고서제출"])
    check("회생절차개시결정 → BANKRUPTCY", r == "BANKRUPTCY")

    r, h = classify_report_nms(["파산신청기각", "파산신청", "감사보고서제출"])
    check("파산신청/파산신청기각은 BANKRUPTCY로 오분류하지 않는다(결정된 사건 아님)", r is None)

    r, h = classify_report_nms(["'25사업연도 감사의견 거절 관련 상장폐지 절차 미진행"])
    check("감사의견거절 단독 → AUDIT_OPINION", r == "AUDIT_OPINION")

    r, h = classify_report_nms(["자본잠식50%이상또는매출액50억원미만사실발생"])
    check("자본잠식 단독 → CAPITAL_IMPAIRMENT", r == "CAPITAL_IMPAIRMENT")

    r, h = classify_report_nms(["반기검토의견부적정,의견거절또는완전자본잠식사실발생"])
    check("의견부적정+자본잠식 같은 제목에 동시 등장 → 모호, UNKNOWN(None)", r is None)
    check("모호 판정에도 양쪽 히트가 진단에 남는다", h["auditOpinion"] and h["capitalImpairment"])

    r, h = classify_report_nms(["기타시장안내(상장적격성 실질심사 대상 결정)"])
    check("실질심사만 있고 다른 신호 없음 → DELISTING_REVIEW_FAILED", r == "DELISTING_REVIEW_FAILED")

    r, h = classify_report_nms(["기타시장안내(상장적격성 실질심사 대상 결정)", "자본잠식50%이상"])
    check("실질심사+자본잠식 동시 → 더 구체적인 CAPITAL_IMPAIRMENT 우선", r == "CAPITAL_IMPAIRMENT")

    r, h = classify_report_nms(["주주총회소집결의", "최대주주변경"])
    check("다섯 카테고리 어디에도 안 걸리면 None(UNKNOWN 유지, 지어내지 않음)", r is None)

    r, h = classify_report_nms(["주권매매거래정지(자진상장폐지 신청)", "회생절차개시결정"])
    check("자진상장폐지+회생절차 동시 → VOLUNTARY 우선(회사의 실제 선택)", r == "VOLUNTARY")

    ok = all(c for _, c in checks)
    for name, c in checks:
        print(("  PASS  " if c else "  FAIL  ") + name)
    print()
    print("통과 %d · 실패 %d" % (sum(c for _, c in checks), sum(not c for _, c in checks)))
    return 0 if ok else 1


# ── DART ───────────────────────────────────────────────────────
def dart_get(key, endpoint, params):
    last = (None, "unknown", "unknown")
    for i in range(RETRY_ATTEMPTS):
        try:
            import requests
            r = requests.get(f"{BASE}/{endpoint}", params={"crtfc_key": key, **params}, timeout=30)
        except Exception as e:  # noqa: BLE001
            last = (None, "EXC", f"{type(e).__name__}: {str(e)[:150]}")
        else:
            if not (200 <= r.status_code < 300):
                last = (None, f"HTTP{r.status_code}", f"HTTP {r.status_code}")
            else:
                try:
                    j = r.json()
                except Exception as e:  # noqa: BLE001
                    last = (None, "PARSE", f"{type(e).__name__}: {str(e)[:150]}")
                else:
                    st = str(j.get("status", ""))
                    if st == "000":
                        return j, "000", None
                    if st in (DART_NO_DATA, QUOTA_EXCEEDED_STATUS):
                        return None, st, str(j.get("message", ""))[:150]
                    last = (None, st, str(j.get("message", ""))[:150])
        if i < RETRY_ATTEMPTS - 1:
            time.sleep(RETRY_BACKOFF_BASE ** i)
    return last


def list_disclosures_i(key, corp, bgn_de, end_de, counters):
    rows, page = [], 1
    while True:
        j, st, err = dart_get(key, "list.json", {
            "corp_code": corp, "bgn_de": bgn_de, "end_de": end_de,
            "pblntf_ty": "I", "page_no": str(page), "page_count": "100"})
        counters["calls"] += 1
        if st == "013":
            return rows
        if st != "000":
            counters["listErrors"][st] = counters["listErrors"].get(st, 0) + 1
            return rows
        rows.extend(j.get("list") or [])
        total_page = j.get("total_page", 1)
        if page >= total_page:
            return rows
        page += 1
        time.sleep(REQUEST_SLEEP_SECONDS)


def run():
    key = os.environ.get("DART_API_KEY", "")
    if not key:
        print("DART_API_KEY 없음 — .env를 셸에 로드했는지 확인")
        return 1

    exit_rows, tier_a_corps = load_tier_a_classified()
    pool = [r for r in exit_rows if r["corp"] not in tier_a_corps]
    print(f"Tier B 대상: {len(pool)}종목 (exitAtConfirmed 총 {len(exit_rows)} - Tier A {len(tier_a_corps)})")

    counters = {"calls": 0, "listErrors": {}}
    classified, unclassified = [], []
    windowBuckets = {"ambiguousAuditCapital": 0, "noSignal": 0}
    t0 = time.time()
    for i, row in enumerate(pool, 1):
        corp, ticker = row["corp"], row.get("ticker")
        exit_at = to_date(row["exitAtConfirmed"])
        bgn_de = (exit_at - datetime.timedelta(days=WINDOW_DAYS)).strftime("%Y%m%d")
        end_de = exit_at.strftime("%Y%m%d")
        rows = list_disclosures_i(key, corp, bgn_de, end_de, counters)
        report_nms = [str(r.get("report_nm") or "") for r in rows]
        reason, evidence = classify_report_nms(report_nms)
        if reason == "AMBIGUOUS_MARKER":  # unreachable, defensive
            pass
        if reason:
            classified.append({
                "corp": corp, "ticker": ticker, "corpName": row.get("corpName"),
                "exitReason": reason, "exitAtConfirmed": row["exitAtConfirmed"],
                "matchedReportNms": {k: v for k, v in evidence.items() if v},
                "source": "dart-list-i-tierB",
            })
        else:
            if evidence["auditOpinion"] and evidence["capitalImpairment"]:
                windowBuckets["ambiguousAuditCapital"] += 1
            elif not any(evidence.values()):
                windowBuckets["noSignal"] += 1
            unclassified.append({
                "corp": corp, "ticker": ticker, "corpName": row.get("corpName"),
                "exitAtConfirmed": row["exitAtConfirmed"],
                "anyHits": {k: v for k, v in evidence.items() if v},
            })
        if i % 50 == 0:
            print(f"  {i}/{len(pool)} · 분류 {len(classified)} · 호출 {counters['calls']} · {time.time()-t0:.0f}s")

    out = {
        "generatedAt": datetime.datetime.now().isoformat(timespec="seconds"),
        "tier": "B",
        "windowDays": WINDOW_DAYS,
        "note": "로컬 진단 산출물 — data/backfill/에 쓰지 않는다(규칙 4). "
                "실제 반영은 Tier A와 함께 별도 GitHub Actions 승격 단계에서.",
        "poolSize": len(pool),
        "callsTotal": counters["calls"],
        "listErrors": counters["listErrors"],
        "classifiedCount": len(classified),
        "classifiedRate": round(len(classified) / len(pool), 4) if pool else None,
        "unclassifiedBuckets": windowBuckets,
        "distribution": {},
        "classified": classified,
        "unclassified": unclassified,
    }
    dist = {}
    for c in classified:
        dist[c["exitReason"]] = dist.get(c["exitReason"], 0) + 1
    out["distribution"] = dist

    with open(OUT_PATH, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=2)
    print(f"\nclassified: {len(classified)} / {len(pool)} ({100*len(classified)/len(pool):.1f}%)" if pool else "")
    print("distribution:", json.dumps(dist, ensure_ascii=False))
    print("unclassifiedBuckets:", json.dumps(windowBuckets, ensure_ascii=False))
    print("wrote", OUT_PATH)
    return 0


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--selftest", action="store_true")
    args = ap.parse_args()
    if args.selftest:
        return selftest()
    return run()


if __name__ == "__main__":
    sys.exit(main())
