#!/usr/bin/env python3
"""A3b 회귀 — 합성 픽스처로 계약의 갈리는 지점을 밟는다.
  python scripts/test-fundamentals-a3b.py

네트워크도 수집 산출물도 필요 없다.

**이 파일은 ChatGPT 계약 대조의 자리를 대신한다.** 계약(`docs/A3b-1.0-배당EPS계약.md`)과
정책(`fundamentals.v1.json`의 `a3b`)이 정한 것을 구현이 실제로 **읽는지**를 기계로
강제한다 — 눈으로 보는 대조는 "정책에 적혀 있고 코드에도 같은 값이 박혀 있다"를 통과로
읽지만, 그건 값이 두 곳에 있는 상태다. 여기서는 **정책을 바꿔 놓고 동작이 따라오는지**를
본다. 안 따라오면 그 값은 하드코딩이다.

지키려는 것 셋:
  1. 배당의 세 갈래가 유지되는가 — 0(무배당)과 null(결측)이 합쳐지면 배당 안 주는
     회사가 전부 유보가 된다. 조용히 틀리고, 점수도 등급도 정상으로 보인다.
  2. PIT가 A3와 같은 방향인가 — availableFrom <= periodEnd 는 look-ahead 다.
  3. 스캔한 셀이 결과 없이도 남는가 — A3가 798법인 중 599의 조회 여부를 잃은 자리다.
"""
import copy
import gzip
import importlib.util
import io
import json
import os
import sys
import tempfile
from contextlib import redirect_stdout

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
os.chdir(ROOT)
spec = importlib.util.spec_from_file_location(
    "a3b", os.path.join(ROOT, "scripts", "build-fundamentals-a3b.py"))
m = importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)

POL = json.load(open("config/policies/fundamentals.v1.json", encoding="utf-8"))
A3B = POL["a3b"]

passed = failed = 0


def ok(label, cond, detail=""):
    global passed, failed
    print(("  OK    " if cond else "  FAIL  ") + label
          + (f"  — {detail}" if not cond and detail else ""))
    if cond:
        passed += 1
    else:
        failed += 1


def row(se, thstrm, knd="보통주", rcept="20250311000123", stlm="2024-12-31"):
    return {"rcept_no": rcept, "stlm_dt": stlm, "se": se,
            "thstrm": thstrm, "stock_knd": knd}


def rec(rows, a3b=None):
    r, why = m.build_record("00126380", "005930", 2024, rows, a3b or A3B)
    return r, why


# ── 1. 배당 세 갈래 (계약 §5.1) ────────────────────────────────────
print("[1] 배당 세 갈래 — 0과 null 을 합치지 않는다")

r, _ = rec([row("(연결)주당순이익(원)", "8,057"), row("주당현금배당금(원)", "1,444")])
ok("값이 있으면 숫자", r["dividendRowPresent"] is True and r["dividendPerShare"] == 1444,
   str(r["dividendPerShare"]))

for empty in ("", "-", "  "):
    r, _ = rec([row("(연결)주당순이익(원)", "8,057"), row("주당현금배당금(원)", empty)])
    ok(f"행 있고 값 {empty!r} → 무배당 0 (결측 아님)",
       r["dividendRowPresent"] is True and r["dividendPerShare"] == 0,
       f"present={r['dividendRowPresent']} dps={r['dividendPerShare']}")

r, _ = rec([row("(연결)주당순이익(원)", "8,057")])
ok("행 자체가 없으면 결측 null",
   r["dividendRowPresent"] is False and r["dividendPerShare"] is None,
   f"present={r['dividendRowPresent']} dps={r['dividendPerShare']}")

ok("0 과 null 은 서로 다른 값이다 (합치면 무배당이 전부 유보가 된다)",
   rec([row("(연결)주당순이익(원)", "1"), row("주당현금배당금(원)", "-")])[0]["dividendPerShare"]
   is not rec([row("(연결)주당순이익(원)", "1")])[0]["dividendPerShare"])

r, _ = rec([row("(연결)주당순이익(원)", "8,057"), row("주당현금배당금(원)", "1,000", knd="우선주"),
            row("주당현금배당금(원)", "500", knd="보통주")])
ok("stock_knd 보통주를 우선 고른다", r["dividendPerShare"] == 500, str(r["dividendPerShare"]))

# ── 2. eps 는 배당과 다르다 ────────────────────────────────────────
print("\n[2] eps — 빈 값을 0으로 읽지 않는다")
r, _ = rec([row("(연결)주당순이익(원)", "-"), row("주당현금배당금(원)", "100")])
ok("eps 행이 있어도 값이 비면 null ('주당순이익 0'과 섞이면 안 된다)", r["eps"] is None)
r, _ = rec([row("(연결)주당순이익(원)", "0"), row("주당현금배당금(원)", "100")])
ok("eps 0 은 관측된 값이라 0으로 남는다", r["eps"] == 0)
r, _ = rec([row("(연결)주당순이익(원)", "-1,234"), row("주당현금배당금(원)", "0")])
ok("음수 eps 를 읽는다", r["eps"] == -1234, str(r["eps"]))

# ── 3. PIT (계약 §4) ──────────────────────────────────────────────
print("\n[3] PIT — availableFrom 은 rcept_no, periodEnd 는 stlm_dt")
r, _ = rec([row("(연결)주당순이익(원)", "1")])
ok("availableFrom 이 rcept_no 앞 8자리다", r["availableFrom"] == "20250311")
ok("periodEnd 가 stlm_dt 다 (thstrm_dt 가 아니다)", r["periodEnd"] == "20241231")
ok("rceptNo 를 그대로 남긴다", r["rceptNo"] == "20250311000123")

r, _ = rec([row("(연결)주당순이익(원)", "1", stlm="2024.12.31 현재")])
ok("stlm_dt 가 문장형이어도 마지막 날짜를 캔다 (형태를 가정하지 않는다)",
   r["periodEnd"] == "20241231", str(r["periodEnd"]))

for bad, why in (([{"stlm_dt": "2024-12-31", "se": "x", "thstrm": "1"}], "RCEPT_NO_MISSING"),
                 ([row("x", "1", rcept="123")], "RCEPT_NO_MALFORMED"),
                 ([row("x", "1", stlm="")], "PERIOD_END_UNPARSED")):
    r, w = rec(bad)
    ok(f"{why} 는 레코드를 만들지 않고 사유를 돌려준다", r is None and w == why, str(w))

# ── 4. ★ 계약을 읽는가 (하드코딩 검출) ─────────────────────────────
print("\n[4] 구현이 정책을 읽는가 — 값이 코드에 박혀 있으면 여기서 걸린다")

alt = copy.deepcopy(A3B)
alt["source"]["epsPreference"] = ["(별도)주당순이익"]
r, _ = rec([row("(연결)주당순이익(원)", "111"), row("(별도)주당순이익(원)", "222"),
            row("주당현금배당금(원)", "1")], alt)
ok("epsPreference 를 바꾸면 고르는 행이 따라 바뀐다", r["eps"] == 222, str(r["eps"]))
ok("epsSource 에 어느 라벨로 골랐는지 남는다", r["epsSource"] == "(별도)주당순이익",
   str(r["epsSource"]))

alt2 = copy.deepcopy(A3B)
alt2["source"]["dividendPreference"] = ["주당주식배당"]
r, _ = rec([row("주당현금배당금(원)", "500"), row("주당주식배당(주)", "7")], alt2)
ok("dividendPreference 를 바꾸면 고르는 행이 따라 바뀐다", r["dividendPerShare"] == 7,
   str(r["dividendPerShare"]))

alt3 = copy.deepcopy(A3B)
alt3["pointInTime"]["periodEndSource"] = "someOtherField"
r, w = rec([row("(연결)주당순이익(원)", "1")], alt3)
ok("periodEndSource 를 바꾸면 stlm_dt 를 안 본다", r is None and w == "PERIOD_END_UNPARSED",
   str(w))

alt4 = copy.deepcopy(A3B)
alt4["dividend"]["semantics"] = "twoWay"
r, _ = rec([row("(연결)주당순이익(원)", "1"), row("주당현금배당금(원)", "-")], alt4)
ok("dividend.semantics 가 threeWay 가 아니면 0으로 읽지 않는다",
   r["dividendPerShare"] is None, str(r["dividendPerShare"]))

_bad_pol = copy.deepcopy(POL)
_bad_pol["a3b"]["grid"]["mode"] = "somethingNew"
try:
    m.build_grid(_bad_pol)
    ok("모르는 grid.mode 는 예외다", False, "폴백했다")
except ValueError as e:
    ok("모르는 grid.mode 는 조용히 폴백하지 않고 예외다", "grid.mode" in str(e))

# ── 5. parse_amount ──────────────────────────────────────────────
print("\n[5] parse_amount — 빈 값과 못 읽는 값을 가른다")
for raw, want in (("1,234", (1234, "numeric")), ("0", (0, "numeric")),
                  ("-5", (-5, "numeric")), ("△5", (-5, "numeric")),
                  ("", (None, "empty")), ("-", (None, "empty")),
                  (None, (None, "empty")), ("N/A", (None, "empty")),
                  ("abc", (None, "unparsable"))):
    ok(f"parse_amount({raw!r}) == {want}", m.parse_amount(raw) == want,
       str(m.parse_amount(raw)))

# ── 6. ★ 스캔 기록 (계약 §7) ──────────────────────────────────────
print("\n[6] 스캔 기록 — 결과가 없어도 남긴다")

_responses = {}


def fake_get(endpoint, params):
    k = (params["corp_code"], int(params["bsns_year"]))
    v = _responses.get(k)
    if v is None:
        return None, "013", "조회된 데이타가 없습니다."
    return {"list": v}, "000", None


m.dart_get = fake_get
_pol = copy.deepcopy(POL)
_pol["requestSleepSeconds"] = 0
_pol["stopAfterConsecutiveEmptyYears"] = 2

_responses = {("00000001", 2024): [row("(연결)주당순이익(원)", "10")]}
st = {"callsUsedToday": 0}
cnt = {"calls": 0, "emptyCells": 0, "rejected": __import__("collections").Counter()}
recs, scanned = m.scan_corp("00000001", "005930", [2021, 2022, 2023, 2024], _pol, st, cnt)
ok("013 인 해도 scanned 에 남는다", scanned.get("2021") == "013", str(scanned))
ok("조기 종료 뒤의 해는 EARLY_STOP 으로 남는다 ('조회 안 함'과 013 을 가른다)",
   scanned.get("2023") == "EARLY_STOP" and scanned.get("2024") == "EARLY_STOP", str(scanned))
ok("스캔한 셀이 하나도 빠지지 않는다", set(scanned) == {"2021", "2022", "2023", "2024"},
   str(sorted(scanned)))
ok("조기 종료가 실제로 호출을 줄인다", cnt["calls"] == 2, str(cnt["calls"]))

_responses = {("00000002", y): [row("(연결)주당순이익(원)", str(y))] for y in (2023, 2024)}
st = {"callsUsedToday": 0}
cnt = {"calls": 0, "emptyCells": 0, "rejected": __import__("collections").Counter()}
recs, scanned = m.scan_corp("00000002", "005930", [2023, 2024], _pol, st, cnt)
ok("전부 성공하면 OK 로 남는다", list(scanned.values()) == ["OK", "OK"], str(scanned))
ok("레코드 2건", len(recs) == 2)
ok("callsUsedToday 가 누적된다", st["callsUsedToday"] == 2)

# ── 7. 인수 조건 ──────────────────────────────────────────────────
print("\n[7] 인수 조건")


def run_validate(rows, extra=None, from_output_only=False, pol=None):
    m.fails.clear()
    m.warns.clear()
    diag = {"plannedCells": len(rows), "scannedCells": len(rows),
            "rceptNoPresentRate": 1.0, "corpsIncomplete": 0,
            "targetCorps": 1, "corpsDone": 1}
    diag.update(extra or {})
    corps = {r["corp"]: {"ticker": r["ticker"], "group": "current"} for r in rows}
    with redirect_stdout(io.StringIO()):
        m.validate(rows, pol or POL, diag, {}, corps, from_output_only)
    return list(m.fails), list(m.warns), diag


good = [{"corp": "00126380", "ticker": "005930", "fiscalYear": 2024,
         "availableFrom": "20250311", "rceptNo": "20250311000123",
         "periodEnd": "20241231", "eps": 8057, "epsSource": "(연결)주당순이익",
         "dividendRowPresent": True, "dividendPerShare": 1444,
         "dividendStockKnd": "보통주"}]
f, w, d = run_validate(good)
ok("정상 1건은 FAIL 0", not f, str(f))

bad_pit = copy.deepcopy(good)
bad_pit[0]["availableFrom"] = "20241130"        # periodEnd 이전 = look-ahead
f, w, d = run_validate(bad_pit)
ok("availableFrom <= periodEnd 는 FAIL 이다 (look-ahead)",
   any("계약 1" in x for x in f), str(f))
ok("위반 표본을 진단에 남긴다", len(d["pitContractViolationSample"]) == 1)

dup = good + copy.deepcopy(good)
f, w, d = run_validate(dup)
ok("(corp, fiscalYear, availableFrom) 중복은 FAIL", any("중복" in x for x in f), str(f))

f, w, d = run_validate(good, extra={"scannedCells": 999})
ok("격자 셀과 스캔 셀이 다르면 FAIL", any("스캔 셀" in x for x in f), str(f))

f, w, d = run_validate(good, extra={"rceptNoPresentRate": 0.5})
ok("rcept_no 존재율 미달은 FAIL", any("rcept_no" in x for x in f), str(f))

# ★ 그 비율의 분모. 013(보고서 없음)을 분모에 넣으면 '보고서가 없다'가
#   'rcept_no 를 안 준다'로 읽힌다 — 실측 격자면 0.74가 나와 하드 FAIL 이다.
with tempfile.TemporaryDirectory() as _d:
    json.dump({"corpsDone": ["c1", "c2"], "callsUsedToday": 5,
               "scanned": {"c1": {"2024": "OK", "2023": "OK"},
                           "c2": {"2024": "013", "2023": "013", "2022": "EARLY_STOP"}}},
              open(f"{_d}/_state-0.json", "w", encoding="utf-8"))
    _d2 = {}
    m._merge_state(_d, _d2)
ok("rceptNoPresentRate 의 분모가 '행이 돌아온 셀'이다 (013·EARLY_STOP 제외)",
   _d2["respondedCells"] == 2 and _d2["rceptNoPresentRate"] == 1.0,
   f"responded={_d2['respondedCells']} rate={_d2['rceptNoPresentRate']}")
ok("스캔 셀은 전부 세되 분모와 구분한다",
   _d2["scannedCells"] == 5, str(_d2["scannedCells"]))

with tempfile.TemporaryDirectory() as _d:
    json.dump({"corpsDone": ["c1"], "callsUsedToday": 4,
               "scanned": {"c1": {"2024": "OK", "2023": "REJECTED:RCEPT_NO_MISSING",
                                  "2022": "REJECTED:PERIOD_END_UNPARSED",
                                  "2021": "013"}}},
              open(f"{_d}/_state-0.json", "w", encoding="utf-8"))
    _d3 = {}
    m._merge_state(_d, _d3)
ok("rcept_no 때문에 버린 셀만 분자에서 뺀다 (periodEnd 실패는 rcept_no 가 있었다)",
   _d3["respondedCells"] == 3 and _d3["rceptNoPresentRate"] == round(2 / 3, 5),
   f"responded={_d3['respondedCells']} rate={_d3['rceptNoPresentRate']}")
ok("버린 사유를 진단에 남긴다",
   _d3["rejectReasons"] == {"RCEPT_NO_MISSING": 1, "PERIOD_END_UNPARSED": 1},
   str(_d3["rejectReasons"]))

# 예산 소진으로 중단된 샤드가 섞이면 부분 수집물에 manifest 가 찍힌다(교훈43).
f, w, d = run_validate(good, extra={"corpsIncomplete": 12})
ok("미완료 법인이 남아 있으면 FAIL", any("미완료 법인" in x for x in f), str(f))

three = good + [dict(good[0], fiscalYear=2023, availableFrom="20240311",
                     dividendPerShare=0),
                dict(good[0], fiscalYear=2022, availableFrom="20230311",
                     dividendRowPresent=False, dividendPerShare=None)]
f, w, d = run_validate(three)
ok("배당 세 갈래 분포를 진단에 남긴다",
   d["dividendThreeWayDistribution"] == {"numeric": 1, "zeroNoDividend": 1, "absent": 1},
   str(d["dividendThreeWayDistribution"]))

os.environ["A3B_FAIL_INJECTION"] = "gate-test"
f, w, d = run_validate(good)
os.environ.pop("A3B_FAIL_INJECTION")
ok("FAIL_INJECTION 이 게이트를 강제 실패시킨다", any("FAIL INJECTION" in x for x in f))

# ── 8. --revalidate 범위 (계약 §9) ────────────────────────────────
print("\n[8] --revalidate — 상태가 필요한 항목은 건너뛴다")
f, w, d = run_validate(good, extra={"scannedCells": 999, "rceptNoPresentRate": 0.1},
                       from_output_only=True)
ok("산출물만으로는 스캔 셀·rcept_no 존재율을 판정하지 않는다", not f, str(f))
ok("건너뛴 사실을 진단에 남긴다", d.get("revalidatedFromOutputOnly") is True)
ok("산출물로 잴 수 있는 항목은 그대로 잰다", "dividendThreeWayDistribution" in d)

_declared = set(A3B["revalidate"]["fromOutput"])
_state_only = set(A3B["revalidate"]["requiresState"])
ok("revalidate 선언이 두 집합으로 갈려 있다 (겹치면 무엇이 가능한지 흐려진다)",
   not (_declared & _state_only), str(_declared & _state_only))

# ── 9. 계약 대조 — 정책 선언과 구현 산출이 같은가 ────────────────────
print("\n[9] 계약 대조 (ChatGPT 대조의 자리)")
r, _ = rec([row("(연결)주당순이익(원)", "8,057"), row("주당현금배당금(원)", "1,444")])
ok("build_record 의 키가 policy.a3b.output.fields 를 전부 덮는다",
   set(A3B["output"]["fields"]) <= set(r), str(set(A3B["output"]["fields"]) - set(r)))
ok("sortKey 가 전부 레코드에 있다",
   set(A3B["output"]["sortKey"]) <= set(r), str(set(A3B["output"]["sortKey"]) - set(r)))
ok("manifest.upstream 이 lib/backfillManifest.js 의 표와 같다",
   A3B["manifest"]["upstream"] == ["A1a", "A1b", "A3"], str(A3B["manifest"]["upstream"]))
ok("collectionContract 에 quota 가 없다 (있으면 FN-1.4 예산 변경이 resume 을 깬다)",
   not any("quota" in f for f in A3B["collectionContract"]["fields"]))
ok("collectionContract 에 acceptance 가 없다 (임계 승격이 수집을 폐기하면 안 된다)",
   not any("acceptance" in f for f in A3B["collectionContract"]["fields"]))
_vd = open("scripts/verify-diagnostics.js", encoding="utf-8").read()
for k in ("scannedCells", "dividendThreeWayDistribution", "currentListedEpsRate",
          "rceptNoVsA3"):
    ok(f"verify-diagnostics 가 {k} 를 요구한다", f"'{k}'" in _vd)

print(f"\n{'='*54}")
print(f"통과 {passed} · 실패 {failed}")
sys.exit(0 if failed == 0 else 1)
