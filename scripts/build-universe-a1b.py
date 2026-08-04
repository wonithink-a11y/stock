#!/usr/bin/env python3
"""A1b — 폐지 이력 유니버스 (BF-1.1)

A0.7 DART corpCode 스냅샷의 corp 집합에서 A1a가 확정한 현재 상장분(current)과
제외분(excluded)을 뺀 차집합이 폐지 후보다. 정의는 config/policies/universe.v1.json의
a1b 블록(UN-1.2)이 단일 산출점이다 — 이 스크립트에 임계값·경로를 하드코딩하지 않는다.

네트워크를 쓰지 않는다. 입력 3개가 모두 커밋된 산출물이므로 A1b는 순수 집합 연산이고,
재현성은 상류 manifest 해시(A0.7·A1a)가 보장한다.

입력:
  config/policies/universe.v1.json          a1b 블록
  data/backfill/dart/corpcode.jsonl         base (A0.7)
  data/backfill/universe/a1a/current.jsonl  차집합 대상 (A1a)
  data/backfill/universe/a1a/excluded.jsonl 차집합 대상 (A1a, KONEX·SPAC)
출력:
  data/backfill/universe/a1b/delisted.jsonl
  data/backfill/universe/a1b/_diagnostics.json

폐지 사유(exitReason)와 폐지일(exitAt)은 여기서 채우지 않는다. A1b가 아는 것은
'DART에 법인은 있는데 현재 상장 목록에 없다'는 사실 하나뿐이다.
"""
import json
import os
import re
import sys
from collections import defaultdict

POLICY = "config/policies/universe.v1.json"
OUT_DIR = "data/backfill/universe/a1b"

# 식별자 계약(CLAUDE.md §식별자 계약). A0.7이 수집 시점에 이미 강제하지만 여기서 다시 본다 —
# 차집합의 조인 키라서, 여기서 통과한 것이 하류 전부의 전제가 된다.
CORP_PATTERN = r"^[0-9]{8}$"

fails, warns = [], []


def chk(cond, msg):
    print(("  OK  " if cond else "  FAIL") + "  " + msg)
    if not cond:
        fails.append(msg)


def warn(cond, msg):
    print(("  OK  " if cond else "  WARN") + "  " + msg)
    if not cond:
        warns.append(msg)


def _abort(reason, diag, extra=None):
    """실패해도 진단은 남긴다(교훈39). 증거 없는 중단은 다음 라운드를 추측으로 만든다."""
    diag.update({"aborted": True, "abortReason": reason, **(extra or {})})
    os.makedirs(OUT_DIR, exist_ok=True)
    with open(f"{OUT_DIR}/_diagnostics.json", "w", encoding="utf-8", newline="\n") as f:
        json.dump(diag, f, ensure_ascii=False, indent=2)
    print(f"\n중단: {reason}")
    sys.exit(2)


def read_jsonl(path, diag):
    if not os.path.exists(path):
        _abort(f"{path} 없음 — 상류 단계를 먼저 실행하라", diag)
    rows = []
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                rows.append(json.loads(line))
    if not rows:
        _abort(f"{path} 0행 — 빈 입력을 성공으로 오인하면 후보가 폭증한다", diag)
    return rows


# ── 1. 차집합 ──────────────────────────────────────────────────
def build(base, subtract_sets, a1b, diag):
    """corp 기준 차집합 → ticker 기준 안전망 제거."""
    sub_corp, sub_ticker = subtract_sets

    step1 = [x for x in base if x["corp"] not in sub_corp]
    diag["candidatesAfterCorpDiff"] = len(step1)

    # 안전망: A1a에서 corp 매핑에 실패한 종목은 corp 차집합을 그대로 통과해 폐지 후보로
    # 새어 들어온다. 그것을 ticker로 한 번 더 거른다. 걸린 건수 자체가 진단값이므로
    # 목록을 전수 남긴다 — 0건이면 A1a의 corp 매핑이 전건 성공했다는 뜻이다.
    hit = [x for x in step1 if x["ticker"] in sub_ticker]
    step2 = [x for x in step1 if x["ticker"] not in sub_ticker]
    diag["tickerSafetyNetRemoved"] = [
        {"corp": x["corp"], "ticker": x["ticker"], "corpName": x["corpName"]} for x in hit
    ]

    # 스키마 키 순서 고정 (BF-1.1 §3 — JSON 키 순서는 스키마 정의 순서)
    rows = [{
        "corp": x["corp"],
        "ticker": x["ticker"],
        "corpName": x["corpName"],
        "exitReason": a1b["exitReasonDefault"],
        "exitAt": a1b["exitAtDefault"],
        "dartModifyDate": x["modifyDate"],   # 폐지일이 아니다 — A2의 역탐색 구간 힌트
        "source": a1b["sourceTag"],
    } for x in step2]
    rows.sort(key=lambda x: x["corp"])
    return rows


def ticker_reuse(rows):
    """같은 ticker가 여러 corp에 걸쳐 후보로 남은 경우. 재사용은 사실이므로 제거하지 않는다."""
    by_ticker = defaultdict(list)
    for x in rows:
        by_ticker[x["ticker"]].append(x)
    return [
        {"ticker": t,
         "corps": [{"corp": g["corp"], "corpName": g["corpName"],
                    "modifyDate": g["dartModifyDate"]} for g in
                   sorted(group, key=lambda g: g["dartModifyDate"])]}
        for t, group in sorted(by_ticker.items()) if len(group) > 1
    ]


# ── 2. 인수 조건 ───────────────────────────────────────────────
def validate(rows, pol, a1b, subtract_sets, diag):
    a = a1b["acceptance"]
    sub_corp, sub_ticker = subtract_sets
    print("\n[인수 조건]")

    # 게이트 검증용 주입. 조건을 '더 엄격하게'만 만들 수 있고 느슨하게는 못 만든다 —
    # 통과시키는 방향의 우회로가 생기면 그게 곧 정책 무력화 경로다.
    inject = os.environ.get("A1B_FAIL_INJECTION", "").strip()
    if inject:
        diag["failInjection"] = inject
        chk(False, f"[FAIL INJECTION] {inject} — 게이트 검증용 강제 실패")

    # 1) 상한이 하한보다 중요하다 — A1a가 망가져 base가 줄면 후보가 폭증하는데,
    #    하한만 있으면 그 폭증이 '성공'으로 통과한다.
    chk(a["candidateMin"] <= len(rows) <= a["candidateMax"],
        f"후보 수 {len(rows)} ∈ [{a['candidateMin']}, {a['candidateMax']}]")

    # 2·3) 사유·폐지일은 A1b가 모른다. 기본값이 아닌 값이 하나라도 있으면
    #      어딘가에서 추정이 승격됐다는 뜻이다.
    n_exit_at = sum(1 for x in rows if x["exitAt"] is not None)
    chk(n_exit_at == a["exitAtNonNull"],
        f"exitAt 전건 null (non-null {n_exit_at}건 — dartModifyDate의 exitAt 승격 금지)")
    n_reason = sum(1 for x in rows if x["exitReason"] != a1b["exitReasonDefault"])
    chk(n_reason == a["exitReasonNonDefault"],
        f"exitReason 전건 {a1b['exitReasonDefault']} (이탈 {n_reason}건)")
    chk(diag.get("exitReasonPending") is True,
        "_diagnostics.exitReasonPending = true (사유 복원이 미완임을 하류에 명시)")

    # 4) corp 결측·계약
    miss = [x["ticker"] for x in rows if not x["corp"]]
    chk(len(miss) == a["corpMissing"], f"corp 결측 {len(miss)}건")
    bad_corp = [x["corp"] for x in rows if not re.fullmatch(CORP_PATTERN, x["corp"] or "")]
    diag["corpContractViolations"] = bad_corp
    chk(not bad_corp, f"corp 계약 {CORP_PATTERN} 전건 통과 (위반 {len(bad_corp)}건)")

    # 5) A1a ∩ A1b = ∅ — corp 기준과 ticker 기준 둘 다 본다. corp만 보면 A1a에서
    #    corp 매핑에 실패한 종목이 폐지 후보로 남아 있어도 교집합 0으로 통과한다.
    ic = [x["corp"] for x in rows if x["corp"] in sub_corp]
    it = [x["ticker"] for x in rows if x["ticker"] in sub_ticker]
    chk(len(ic) == a["corpIntersectA1a"], f"A1a ∩ A1b (corp 기준) {len(ic)}건")
    chk(len(it) == a["tickerIntersectA1a"], f"A1a ∩ A1b (ticker 기준) {len(it)}건")
    diag["intersectA1aCorp"] = ic[:100]
    diag["intersectA1aTicker"] = it[:100]

    # 6) ticker 계약 — 최상위 tickerPattern을 그대로 쓴다(a1b 블록에 복제하지 않는다)
    pat = pol["tickerPattern"]
    bad_tk = [x["ticker"] for x in rows if not re.fullmatch(pat, x["ticker"] or "")]
    diag["tickerContractViolations"] = bad_tk
    chk(not bad_tk, f"ticker 계약 {pat} 전건 통과 (위반 {len(bad_tk)}건)")

    # 7) 재사용은 사실이다 — 존재 자체는 항상 통과. 진단 기록 여부만 검사한다.
    reuse = ticker_reuse(rows)
    diag["tickerReuse"] = reuse
    chk("tickerReuse" in diag, f"ticker 재사용 후보 전수 진단 기록 ({len(reuse)}건, 0이 아니어도 통과)")

    # 8) 상장 이력 없는 법인(비상장 stock_code 보유 등)의 혼입은 A1b에서 측정 불가다.
    #    KRX 조회가 없기 때문이며, A2가 마지막 거래일 역탐색으로 확정한다.
    chk(diag.get("listingHistoryUnverified") is True,
        "_diagnostics.listingHistoryUnverified = true (상장 이력 미검증을 하류에 명시)")


# ── 3. main ────────────────────────────────────────────────────
def main() -> int:
    if not os.path.exists(POLICY):
        print(f"{POLICY} 없음 — UN-1.2 정책 파일이 필요하다")
        return 1
    with open(POLICY, encoding="utf-8") as f:
        pol = json.load(f)
    a1b = pol.get("a1b")
    if not a1b:
        print(f"{POLICY}({pol.get('version')})에 a1b 블록이 없다 — UN-1.2 이상이 필요하다")
        return 1
    print(f"유니버스 정책 {pol['version']} · 차집합 키 {a1b['diffKey']} · "
          f"안전망 키 {a1b['safetyNetKey']}")

    # stageVersion은 여기 안 둔다 — manifest가 단일 출처다.
    # 두 플래그는 산출물의 성질이지 실행 결과가 아니므로 진단 초기값으로 고정한다.
    diag = {
        "stage": "A1b",
        "universePolicy": pol["version"],
        "exitReasonPending": True,
        "listingHistoryUnverified": True,
    }

    print("\n[1/3] 입력 적재")
    base = read_jsonl(a1b["base"], diag)
    subs = [read_jsonl(p, diag) for p in a1b["subtract"]]
    diag["baseCount"] = len(base)
    diag["subtractCounts"] = {p: len(r) for p, r in zip(a1b["subtract"], subs)}
    print(f"  base {len(base)}건 · 차집합 대상 {diag['subtractCounts']}")

    sub_corp = {x["corp"] for r in subs for x in r if x.get("corp")}
    sub_ticker = {x["ticker"] for r in subs for x in r if x.get("ticker")}
    diag["subtractCorpUnique"] = len(sub_corp)
    diag["subtractTickerUnique"] = len(sub_ticker)
    # A1a가 corp 매핑에 실패한 건수 = ticker는 있는데 corp가 없는 레코드
    diag["subtractCorpMissing"] = sum(1 for r in subs for x in r if not x.get("corp"))

    print("\n[2/3] 차집합")
    rows = build(base, (sub_corp, sub_ticker), a1b, diag)
    print(f"  corp 차집합 {diag['candidatesAfterCorpDiff']}건 "
          f"− ticker 안전망 {len(diag['tickerSafetyNetRemoved'])}건 = {len(rows)}건")

    diag["finalCount"] = len(rows)
    by_year = defaultdict(int)
    for x in rows:
        by_year[(x["dartModifyDate"] or "????")[:4]] += 1
    diag["dartModifyDateByYear"] = dict(sorted(by_year.items()))

    print("\n[3/3] 인수 조건")
    validate(rows, pol, a1b, (sub_corp, sub_ticker), diag)

    os.makedirs(OUT_DIR, exist_ok=True)
    diag["acceptanceFails"] = list(fails)
    diag["acceptanceWarns"] = list(warns)
    diag["acceptancePassed"] = not fails
    with open(f"{OUT_DIR}/_diagnostics.json", "w", encoding="utf-8", newline="\n") as f:
        json.dump(diag, f, ensure_ascii=False, indent=2, sort_keys=False)

    if warns:
        print(f"\nWARN {len(warns)}건 (실패 아님, 확인 필요):")
        for w in warns:
            print(f"  - {w}")

    # 인수 조건 실패 시 산출물을 쓰지 않는다. 쓰고 나서 exit(1)하면 manifest 단계가
    # 그 파일에 해시를 찍어 하류가 verifyUpstream을 정상 통과한다 — manifest는
    # '파일이 안 바뀌었다'만 증명하지 '검사를 통과했다'는 증명하지 않는다(교훈43).
    if fails:
        print(f"\n인수 조건 {len(fails)}건 실패 — 산출물을 쓰지 않는다")
        for x in fails:
            print(f"  - {x}")
        return 1

    with open(f"{OUT_DIR}/delisted.jsonl", "w", encoding="utf-8", newline="\n") as f:
        for x in rows:
            f.write(json.dumps(x, ensure_ascii=False, sort_keys=False) + "\n")

    print(f"\n{OUT_DIR}/delisted.jsonl — {len(rows)}건 "
          f"(exitReason 전건 {a1b['exitReasonDefault']} · exitAt 전건 null · "
          f"ticker 재사용 {len(diag['tickerReuse'])}건)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
