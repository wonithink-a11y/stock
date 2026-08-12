#!/usr/bin/env python3
"""A3c 회귀 — 합성 픽스처로 계약의 갈리는 지점을 밟는다.
  python scripts/test-fundamentals-a3c.py

A3b 회귀와 같은 역할이다 — 정책(fundamentals.v1.json의 a3c)이 정한 것을 구현이
실제로 읽는지 기계로 강제한다. A3b와 다른 부분만 추가로 지킨다:

  1. istc_totqy 행 선택이 '보통주'→'합계' 순이고 rows[0] 같은 임의 폴백이 없는가
  2. 조기 종료가 '그 해 4개 reprtCode 전부 013'일 때만 걸리는가
     (A3b는 단일 호출이라 이 축이 아예 없었다)
  3. replay_metrics(select_with_carryforward 재생)가 probe와 같은 함수를 쓰는가
     — 정책이 하나면 구현도 하나여야 한다(중복 구현 금지)
"""
import copy
import importlib.util
import io
import json
import os
import sys
import tempfile
from collections import Counter
from contextlib import redirect_stdout

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
os.chdir(ROOT)
spec = importlib.util.spec_from_file_location(
    "a3c", os.path.join(ROOT, "scripts", "build-fundamentals-a3c.py"))
m = importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)

POL = json.load(open("config/policies/fundamentals.v1.json", encoding="utf-8"))
A3C = POL["a3c"]

passed = failed = 0


def ok(label, cond, detail=""):
    global passed, failed
    print(("  OK    " if cond else "  FAIL  ") + label
          + (f"  — {detail}" if not cond and detail else ""))
    if cond:
        passed += 1
    else:
        failed += 1


def row(se, istc, isu=None, distb=None, rcept="20250311000123", stlm="2024-12-31"):
    return {"rcept_no": rcept, "stlm_dt": stlm, "se": se, "istc_totqy": istc,
            "isu_stock_totqy": isu or istc, "distb_stock_co": distb or istc}


def rec(rows, year=2024, code="11011", label="사업보고서"):
    return m.build_record("00126380", "005930", year, code, label, rows)


# ── 0. select_with_carryforward·REPRT_PRIORITY가 probe와 같은 함수인가 ──
print("[0] probe-fundamentals-a3c.py와 단일 구현을 공유하는가")
ok("select_with_carryforward가 probe 모듈 것과 동일 객체다",
   m.select_with_carryforward is m.PROBE.select_with_carryforward)
ok("REPRT_PRIORITY가 probe 모듈 것과 동일 객체다", m.REPRT_PRIORITY is m.PROBE.REPRT_PRIORITY)
ok("REPRT_CODES가 probe 모듈 것과 동일 객체다", m.REPRT_CODES is m.PROBE.REPRT_CODES)

# ── 1. istc_totqy 행 선택 — 보통주 → 합계, 임의 폴백 없음 ──────────────
print("\n[1] istc_totqy 행 선택 — 보통주 우선, 없으면 합계, 둘 다 없으면 None")

r, _ = rec([row("보통주", "5,969,782,550"), row("합계", "6,000,000,000")])
ok("보통주가 있으면 보통주를 쓴다", r["istcTotqy"] == 5969782550, str(r.get("istcTotqy")))
ok("selectedFrom이 보통주로 남는다", r["istcTotqySelectedFrom"] == "보통주")

r, _ = rec([row("비고", "-"), row("합계", "68,469,040")])
ok("보통주가 없으면 합계를 쓴다", r["istcTotqy"] == 68469040, str(r.get("istcTotqy")))
ok("selectedFrom이 합계로 남는다", r["istcTotqySelectedFrom"] == "합계")

r, _ = rec([row("비고", "-")])
ok("보통주도 합계도 없으면 None이다 (rows[0]로 임의 폴백하지 않는다)",
   r["istcTotqy"] is None and r["istcTotqySelectedFrom"] is None)
ok("scanStatus가 EMPTY다 (레코드 자체는 만든다 — 013과 다르다)", r["scanStatus"] == "EMPTY")

r, _ = rec([row("보통주", "-")])
ok("보통주 행이 있어도 값이 '-'면 None이다 (0으로 지어내지 않는다)", r["istcTotqy"] is None)

r, _ = rec([row("보통주", "1,234,567")])
ok("scanStatus가 OK다 (값이 실제로 있으면)", r["scanStatus"] == "OK")

# ── 2. num() — 콤마·'-'·빈 문자열 처리 ─────────────────────────────
print("\n[2] num() — '-'·빈 값·비숫자는 전부 None이다 (0이 아니다)")
for raw, want in (("1,234", 1234), ("0", 0), ("-", None), ("", None),
                  (None, None), ("N/A", None), ("abc", None)):
    ok(f"num({raw!r}) == {want}", m.num(raw) == want, str(m.num(raw)))

# ── 3. PIT ──────────────────────────────────────────────────────
print("\n[3] PIT — availableFrom은 rcept_no, periodEnd는 stlm_dt")
r, _ = rec([row("보통주", "100")])
ok("availableFrom이 rcept_no 앞 8자리다", r["availableFrom"] == "20250311")
ok("periodEnd가 stlm_dt다", r["periodEnd"] == "20241231")
ok("reprtCode를 그대로 남긴다", r["reprtCode"] == "11011")

r, _ = rec([row("보통주", "100", stlm="2024.12.31 현재")])
ok("stlm_dt가 문장형이어도 마지막 날짜를 캔다", r["periodEnd"] == "20241231", str(r["periodEnd"]))

for bad, why in (
    ([{"stlm_dt": "2024-12-31", "se": "보통주", "istc_totqy": "1"}], "RCEPT_NO_MISSING"),
    ([row("보통주", "1", rcept="123")], "RCEPT_NO_MALFORMED"),
    ([row("보통주", "1", stlm="")], "PERIOD_END_UNPARSED"),
):
    r, w = rec(bad)
    ok(f"{why}는 레코드를 만들지 않고 사유를 돌려준다", r is None and w == why, str(w))

# ── 4. 조기 종료 — '그 해 4개 reprtCode 전부 013'일 때만 ────────────
print("\n[4] 조기 종료 — A3b와 다른 축(단일 호출이 아니라 연 4회 조회)")

_responses = {}


def fake_get(endpoint, params, pol=None):
    k = (params["corp_code"], int(params["bsns_year"]), params["reprt_code"])
    v = _responses.get(k)
    if v is None:
        return None, "013", "조회된 데이타가 없습니다."
    return {"list": v}, "000", None


_real_dart_get = m.dart_get
m.dart_get = fake_get
_pol = copy.deepcopy(POL)
_pol["requestSleepSeconds"] = 0
_pol["stopAfterConsecutiveEmptyYears"] = 2

# 2024년은 사업보고서만 있고 나머지 3개 reprtCode는 013 — 그래도 "빈 해"가 아니다.
_responses = {("00000001", 2024, "11011"): [row("보통주", "100")]}
st = {"callsUsedToday": 0}
cnt = {"calls": 0, "emptyCells": 0, "quotaHits": 0, "rejected": Counter()}
recs, scanned, _q = m.scan_corp("00000001", "005930", [2024, 2023, 2022, 2021],
                                _pol, st, cnt)
ok("사업보고서만 있어도 그 해는 빈 해가 아니다 (분기 의무 없는 회사 대응)",
   "2024" in scanned and any(v == "OK" for v in scanned["2024"].values()), str(scanned.get("2024")))
ok("2024년에 4개 reprtCode를 전부 조회한다", len(scanned["2024"]) == 4, str(scanned["2024"]))
ok("2023년(consec=1)·2022년(consec=2, 아직 조회)을 거쳐 2021년째 조기 종료로 남는다",
   scanned.get("2022") is not None and all(v == "013" for v in scanned["2022"].values())
   and scanned.get("2021") is not None and all(v == "EARLY_STOP" for v in scanned["2021"].values()),
   f"2022={scanned.get('2022')} 2021={scanned.get('2021')}")

# 전부 결측인 해가 stopAfter만큼 이어지면 그 이후는 EARLY_STOP.
_responses = {}
st = {"callsUsedToday": 0}
cnt = {"calls": 0, "emptyCells": 0, "quotaHits": 0, "rejected": Counter()}
recs, scanned, _q = m.scan_corp("00000002", "005930", [2021, 2022, 2023], _pol, st, cnt)
ok("아무 reprtCode도 없는 해가 연속되면 조기 종료된다",
   all(v == "013" for v in scanned["2021"].values())
   and all(v == "EARLY_STOP" for v in scanned.get("2023", {}).values()), str(scanned))
ok("조기 종료가 실제로 호출을 줄인다 (2021·2022만 4호출씩 = 8, 2023은 0)",
   cnt["calls"] == 8, str(cnt["calls"]))

# ── 4.1 DART 일 한도 ───────────────────────────────────────────────
print("\n[4.1] DART 일 한도 — 조기 종료로 위장되면 안 된다")


def quota_get(endpoint, params, pol=None):
    return None, "020", "사용한도를 초과하였습니다."


m.dart_get = quota_get
st = {"callsUsedToday": 0}
cnt = {"calls": 0, "emptyCells": 0, "quotaHits": 0, "rejected": Counter()}
recs, scanned, hit = m.scan_corp("00000003", "005930", [2021, 2022], _pol, st, cnt)
ok("한도를 만나면 quota_hit을 올린다", hit is True)
ok("첫 호출에서 즉시 멈춘다", cnt["calls"] == 1, str(cnt["calls"]))
ok("부분 결과를 남기지 않는다", recs == [] and scanned == {}, f"recs={len(recs)} scanned={scanned}")
m.dart_get = fake_get

# ── 5. replay_metrics — probe의 replay_summary와 같은 판단을 내는가 ────
print("\n[5] replay_metrics — select_with_carryforward를 실제 레코드 형태에 재생한다")


def a3c_row(corp, fy, code, avail, istc):
    return {"corp": corp, "ticker": "T", "fiscalYear": fy, "reprtCode": code,
            "availableFrom": avail, "istcTotqy": istc}


rows = [
    a3c_row("A", 2025, "11013", "20250515", 100),
    a3c_row("A", 2025, "11012", "20250814", 110),
    a3c_row("A", 2025, "11014", "20251114", None),
    a3c_row("A", 2025, "11011", "20260318", 120),
    a3c_row("B", 2025, "11013", "20250814", None),
    a3c_row("B", 2025, "11012", "20250814", 200),
]
rm = m.replay_metrics(rows)
ok("법인×연도 수를 센다", rm["corpYearsObserved"] == 2, str(rm))
ok("동시접수를 1건 잡는다 (B사 1분기·반기 동일 접수일)", rm["coFilingCount"] == 1, str(rm))
ok("neverValidRatio가 0이다", rm["neverValidRatio"] == 0.0, str(rm))
ok("direct/carry-forward 비율이 숫자다",
   isinstance(rm["directRatio"], float) and isinstance(rm["carryForwardRatio"], float), str(rm))

# ── 6. 인수 조건 ──────────────────────────────────────────────────
print("\n[6] 인수 조건")


def run_validate(rows, extra=None, from_output_only=False, pol=None):
    m.fails.clear()
    m.warns.clear()
    diag = {"plannedCells": len(rows), "scannedCells": len(rows),
            "corpsIncomplete": 0, "targetCorps": 1, "corpsDone": 1}
    diag.update(extra or {})
    with redirect_stdout(io.StringIO()):
        m.validate(rows, pol or POL, diag, from_output_only)
    return list(m.fails), list(m.warns), diag


good = [{"corp": "00126380", "ticker": "005930", "fiscalYear": 2024, "reprtCode": "11011",
         "availableFrom": "20250311", "rceptNo": "20250311000123", "periodEnd": "20241231",
         "istcTotqy": 5969782550, "isuStockTotqy": 6000000000, "distbStockCo": 5969782550,
         "scanStatus": "OK"}]
f, w, d = run_validate(good)
ok("정상 1건은 FAIL 0", not f, str(f))

bad_pit = copy.deepcopy(good)
bad_pit[0]["availableFrom"] = "20241130"
f, w, d = run_validate(bad_pit)
ok("availableFrom <= periodEnd는 FAIL(look-ahead)", any("계약" in x for x in f), str(f))
ok("위반 표본을 진단에 남긴다", len(d["pitContractViolationSample"]) == 1)

dup = good + copy.deepcopy(good)
f, w, d = run_validate(dup)
ok("(corp, fiscalYear, availableFrom, reprtCode) 중복은 FAIL", any("중복" in x for x in f), str(f))

f, w, d = run_validate(good, extra={"scannedCells": 999})
ok("격자 셀과 스캔 셀이 다르면 FAIL", any("스캔 셀" in x for x in f), str(f))

f, w, d = run_validate(good, extra={"corpsIncomplete": 12})
ok("미완료 법인이 남아 있으면 FAIL", any("미완료 법인" in x for x in f), str(f))

miss_pe = copy.deepcopy(good)
miss_pe[0]["periodEnd"] = None
f, w, d = run_validate(miss_pe)
ok("periodEnd 결측은 FAIL", any("periodEnd" in x for x in f), str(f))

os.environ["A3C_FAIL_INJECTION"] = "gate-test"
f, w, d = run_validate(good)
os.environ.pop("A3C_FAIL_INJECTION")
ok("FAIL_INJECTION이 게이트를 강제 실패시킨다", any("FAIL INJECTION" in x for x in f))

f, w, d = run_validate(good)
ok("replayMetrics가 진단에 남는다", "replayMetrics" in d, str(d.keys()))
ok("istcTotqyRowFoundRate가 진단에 남는다", "istcTotqyRowFoundRate" in d)

# ── 7. --revalidate 범위 ───────────────────────────────────────────
print("\n[7] --revalidate — 상태가 필요한 항목은 건너뛴다")
f, w, d = run_validate(good, extra={"scannedCells": 999}, from_output_only=True)
ok("산출물만으로는 스캔 셀·미완료 법인을 판정하지 않는다", not f, str(f))
ok("건너뛴 사실을 진단에 남긴다", d.get("revalidatedFromOutputOnly") is True)
ok("산출물로 잴 수 있는 항목(replayMetrics)은 그대로 잰다", "replayMetrics" in d)

# ── 8. 계약 대조 — 정책 선언과 구현 산출이 같은가 ───────────────────────
print("\n[8] 계약 대조")
r, _ = rec([row("보통주", "5,969,782,550")])
ok("build_record의 키가 policy.a3c.output.fields를 전부 덮는다",
   set(A3C["output"]["fields"]) <= set(r), str(set(A3C["output"]["fields"]) - set(r)))
ok("sortKey가 전부 레코드에 있다",
   set(A3C["output"]["sortKey"]) <= set(r), str(set(A3C["output"]["sortKey"]) - set(r)))
ok("manifest.upstream이 A1a·A1b·A3다", A3C["manifest"]["upstream"] == ["A1a", "A1b", "A3"])
ok("collectionContract에 quota가 없다",
   not any("quota" in f for f in A3C["collectionContract"]["fields"]))
ok("collectionContract에 acceptance가 없다",
   not any("acceptance" in f for f in A3C["collectionContract"]["fields"]))
ok("tieBreakOnSameAvailableFrom이 정책과 REPRT_PRIORITY 키 집합이 같다",
   set(A3C["pointInTime"]["tieBreakOnSameAvailableFrom"]) == set(m.REPRT_PRIORITY),
   str(set(A3C["pointInTime"]["tieBreakOnSameAvailableFrom"]) ^ set(m.REPRT_PRIORITY)))

_bad_pol = copy.deepcopy(POL)
_bad_pol["a3c"]["grid"]["mode"] = "somethingNew"
try:
    m.build_grid(_bad_pol)
    ok("모르는 grid.mode는 예외다", False, "폴백했다")
except ValueError as e:
    ok("모르는 grid.mode는 조용히 폴백하지 않고 예외다", "grid.mode" in str(e))

m.dart_get = _real_dart_get

print(f"\n{'='*54}")
print(f"통과 {passed} · 실패 {failed}")
sys.exit(0 if failed == 0 else 1)
