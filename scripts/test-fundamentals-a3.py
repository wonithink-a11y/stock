#!/usr/bin/env python3
"""A3 재무(PIT) 회귀 테스트 — 합성 픽스처로 분기를 전부 밟는다.
  python scripts/test-fundamentals-a3.py

네트워크도 수집 산출물도 필요 없다. 지키려는 것은 A3의 존재 이유 하나다:
**availableFrom은 공시 접수일이지 회계기간말이 아니다.** 이 축이 무너지면 백테스트가
그 시점에 존재하지 않던 숫자로 채점되고, 결과는 '좋게 나온 거짓 백테스트'가 된다.
그 실패는 조용하다 — 점수도 등급도 정상으로 보인다. 그래서 여기서 막는다.

밟는 분기:
  1. IFRS 태그 접두사 변경(ifrs_ → ifrs-full_)을 넘어 계정을 잡는가
  2. 계정은 잡혔는데 금액이 비면 '미매칭'으로 세는가 (커버리지 과대계상 방지)
  3. 금융업 양식(유동자산·유동부채 부재)이 커버리지 분자에서 빠져 있는가
  4. thstrm_dt 두 형태에서 회계기간말을 뽑는가 (12월 결산이 아닌 52종목이 여기 걸린다)
  5. availableFrom <= periodEnd 위반이 FAIL로 잡히는가
  6. 정정공시(같은 corp·fiscalYear에 다른 availableFrom)를 중복으로 오판하지 않는가
  7. 같은 키가 정말 두 벌이면 FAIL인가
  8. 연도별 매칭률 급락이 WARN으로 잡히는가 (계약 2)
  9. |ROE| > 200%와 자본잠식을 제거하지 않고 보고만 하는가 (계약 3)
"""
import importlib.util
import io
import json
import os
import sys
from contextlib import redirect_stdout

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
spec = importlib.util.spec_from_file_location(
    "a3", os.path.join(ROOT, "scripts", "build-fundamentals-a3.py"))
m = importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)

POL = json.load(open(os.path.join(ROOT, "config/policies/fundamentals.v1.json"),
                     encoding="utf-8"))

passed = failed = 0

# 합성 픽스처는 법인 수가 적어 규모 WARN이 항상 뜬다. 이 테스트의 대상이 아니다.
SCALE_WARNS = ("재무 확보 법인", "필수 ")


def ok(name, cond, detail=""):
    global passed, failed
    if cond:
        passed += 1
        print(f"  OK    {name}")
    else:
        failed += 1
        print(f"  FAIL  {name}{('  — ' + detail) if detail else ''}")


# ── 픽스처 ─────────────────────────────────────────────────────
def bs(account_id, name, amount, sj="BS"):
    return {"sj_div": sj, "account_id": account_id, "account_nm": name,
            "thstrm_amount": amount, "rcept_no": "20170331000001",
            "thstrm_dt": "2016.12.31 현재", "currency": "KRW"}


def is_(account_id, name, amount):
    return {"sj_div": "IS", "account_id": account_id, "account_nm": name,
            "thstrm_amount": amount, "rcept_no": "20170331000001",
            "thstrm_dt": "2016.01.01 ~ 2016.12.31", "currency": "KRW"}


def full_statement(prefix="ifrs-full", equity="1,000", net="100"):
    """일반 제조업 양식 — 7계정 전부."""
    return [
        bs(f"{prefix}_CurrentAssets", "유동자산", "500"),
        bs(f"{prefix}_CurrentLiabilities", "유동부채", "300"),
        bs(f"{prefix}_Liabilities", "부채총계", "800"),
        bs(f"{prefix}_Equity", "자본총계", equity),
        is_(f"{prefix}_Revenue", "수익(매출액)", "2,000"),
        is_("dart_OperatingIncomeLoss", "영업이익", "150"),
        is_(f"{prefix}_ProfitLoss", "당기순이익", net),
    ]


def financial_statement():
    """금융업 양식 — 유동자산·유동부채가 없다. 결측이 아니라 양식이다."""
    return [
        bs("ifrs-full_Liabilities", "부채총계", "9,000"),
        bs("ifrs-full_Equity", "자본총계", "1,000"),
        is_("ifrs-full_Revenue", "영업수익", "800"),
        is_("dart_OperatingIncomeLoss", "영업이익", "120"),
        is_("ifrs-full_ProfitLoss", "당기순이익", "90"),
    ]


SPEC = POL["accounts"]["spec"]
ORDER = POL["accounts"]["matchOrder"]
REQ = POL["accounts"]["requiredForCoverage"]

print("[계정 매칭]")

vals, how = m.match_accounts(full_statement("ifrs-full"), SPEC, ORDER)
ok("현행 IFRS 태그로 7계정 전부", all(v is not None for v in vals.values()),
   str({k: v for k, v in vals.items() if v is None}))
ok("매칭 수단이 id로 기록된다",
   how["equity"] == "id" and how["netIncome"] == "id", str(how))

# 2019년 전후 접두사 변경. 접두사째 비교하면 옛 사업연도가 통째로 미매칭이 되고,
# 그 결과가 '그 해에 소스가 무너졌다'로 오독된다.
vals_old, how_old = m.match_accounts(full_statement("ifrs"), SPEC, ORDER)
ok("옛 IFRS 접두사(ifrs_)도 같은 계정을 잡는다",
   all(v is not None for v in vals_old.values()) and how_old["equity"] == "id",
   str(how_old))

# 태그가 없으면 이름으로 내려간다 — 그래도 잡혀야 한다.
no_tag = [dict(r, account_id="-표준계정코드 미사용-") for r in full_statement()]
vals_nt, how_nt = m.match_accounts(no_tag, SPEC, ORDER)
ok("표준계정코드 미사용 보고서를 이름으로 잡는다",
   all(v is not None for v in vals_nt.values())
   and how_nt["equity"] in ("nameExact", "nameContains"), str(how_nt))

# 계정은 잡혔는데 금액이 빈 경우. 매칭수단을 남기면 커버리지가 실제보다 높아진다.
blank = [dict(r, thstrm_amount="-") if r["account_nm"] == "자본총계" else r
         for r in full_statement()]
vals_b, how_b = m.match_accounts(blank, SPEC, ORDER)
ok("금액이 비면 미매칭으로 센다 (커버리지 과대계상 방지)",
   vals_b["equity"] is None and how_b["equity"] is None, str(how_b))

vals_f, _ = m.match_accounts(financial_statement(), SPEC, ORDER)
ok("금융업 양식은 유동자산·유동부채만 결측",
   vals_f["currentAssets"] is None and vals_f["currentLiab"] is None
   and vals_f["equity"] is not None, str(vals_f))
ok("금융업 양식도 커버리지 분자를 만족한다 (업종이 품질로 위장하지 않는다)",
   m.coverage_of(vals_f, REQ), str(REQ))

print("\n[회계기간말 파싱]")
ok("'2016.12.31 현재' 형태", m.parse_period_end([bs("x", "y", "1")]) == "2016-12-31")
ok("'2016.01.01 ~ 2016.12.31' 형태 — 마지막 날짜를 쓴다",
   m.parse_period_end([is_("x", "y", "1")]) == "2016-12-31")
ok("3월 결산도 그대로 읽는다 (12월 결산이 아닌 52종목)",
   m.parse_period_end([dict(bs("x", "y", "1"),
                            thstrm_dt="2017.03.31 현재")]) == "2017-03-31")
ok("파싱 불가는 None (추정하지 않는다)",
   m.parse_period_end([dict(bs("x", "y", "1"), thstrm_dt="", thstrm_nm="제 5 기")]) is None)

print("\n[레코드 조립]")
rec, why = m.build_record("00126380", "005930", 2016, full_statement(), "CFS", "26410", POL)
ok("availableFrom은 rcept_no 앞 8자리",
   rec is not None and rec["availableFrom"] == "2017-03-31", str(rec))
ok("availableFrom > periodEnd", rec["availableFrom"] > rec["periodEnd"])
ok("조인 키 corp가 첫 필드", list(rec)[0] == "corp")

bad_rcept = [dict(r, rcept_no="NOTADATE0001") for r in full_statement()]
rec_b, why_b = m.build_record("00126380", "005930", 2016, bad_rcept, "CFS", None, POL)
ok("rcept_no가 날짜가 아니면 레코드를 만들지 않는다",
   rec_b is None and why_b == "RCEPT_NO_NOT_DATE", str(why_b))

no_dt = [dict(r, thstrm_dt="", thstrm_nm="제 5 기") for r in full_statement()]
rec_n, why_n = m.build_record("00126380", "005930", 2016, no_dt, "CFS", None, POL)
ok("회계기간말을 못 읽으면 레코드를 만들지 않는다 (계약 1을 잴 수 없으므로)",
   rec_n is None and why_n == "PERIOD_END_UNPARSED", str(why_n))


# ── validate() 게이트 ──────────────────────────────────────────
def R(corp, year, af, pe, **kw):
    base = {"corp": corp, "ticker": "005930", "fiscalYear": year,
            "availableFrom": af, "rceptNo": af.replace("-", "") + "000001",
            "fsDiv": "CFS", "periodEnd": pe, "currency": "KRW", "sicCode": "26410",
            "currentAssets": 500, "currentLiab": 300, "liabilities": 800,
            "equity": 1000, "revenue": 2000, "opProfit": 150, "netIncome": 100,
            "accountSource": {k: "id" for k in SPEC}}
    base.update(kw)
    return base


CORPS = {f"{i:08d}": {"ticker": f"{i:06d}", "group": "current"} for i in range(1, 6)}
CORPS["00000009"] = {"ticker": "000009", "group": "delisted"}
YEARS = list(range(POL["fiscalYearFrom"], POL["fiscalYearTo"] + 1))


def healthy_rows():
    """전 사업연도가 채워진 정상 집합. 연도가 하나라도 비면 yearsWithNoData가 FAIL이다."""
    out = []
    for c in CORPS:
        for y in YEARS:
            out.append(R(c, y, f"{y+1}-03-31", f"{y}-12-31"))
    return out


def run_validate(rows, corps=None):
    m.fails.clear()
    m.warns.clear()
    diag = {}
    with redirect_stdout(io.StringIO()):
        m.validate(list(rows), corps or CORPS, POL, diag)
    real_warns = [w for w in m.warns if not w.startswith(SCALE_WARNS)]
    return list(m.fails), real_warns, diag


print("\n[인수 조건 게이트]")

f, w, d = run_validate(healthy_rows())
ok("정상 집합은 FAIL 0건", not f, str(f))
ok("정상 집합은 계약 1 위반 0건", d["availableFromNotAfterPeriodEnd"] == 0)
ok("커버리지 100%", d["coverageRate"] == 1.0, str(d["coverageRate"]))

# 계약 1 — A3의 존재 이유. 여기가 뚫리면 백테스트에 look-ahead가 들어간다.
rows = healthy_rows()
rows[0] = R("00000001", 2016, "2016-12-31", "2016-12-31")     # 같은 날 = 위반
f, w, d = run_validate(rows)
ok("availableFrom == periodEnd는 FAIL (초과여야 한다)",
   any("availableFrom > periodEnd" in x for x in f), str(f))

rows = healthy_rows()
rows[0] = R("00000001", 2016, "2016-06-30", "2016-12-31")     # 기간말 이전 = 반전
f, w, d = run_validate(rows)
ok("availableFrom < periodEnd는 FAIL (로직 반전)",
   any("availableFrom > periodEnd" in x for x in f)
   and d["availableFromNotAfterPeriodEnd"] == 1, str(f))

rows = healthy_rows()
rows[0] = R("00000001", 2016, "", "2016-12-31")
f, w, d = run_validate(rows)
ok("availableFrom 부재는 FAIL", any("availableFrom 존재" in x for x in f), str(f))

rows = healthy_rows()
rows[0] = R("00000001", 2016, "2017-03-31", "")
f, w, d = run_validate(rows)
ok("periodEnd 부재는 FAIL", any("periodEnd 존재" in x for x in f), str(f))

rows = healthy_rows()
rows[0] = R("12345", 2016, "2017-03-31", "2016-12-31")
f, w, d = run_validate(rows)
ok("corp_code 8자리 위반은 FAIL", any("corp_code 계약" in x for x in f), str(f))

# 정정공시 — 같은 (corp, fiscalYear)에 다른 availableFrom. 중복이 아니라 사실이다.
rows = healthy_rows() + [R("00000001", 2016, "2018-05-15", "2016-12-31")]
f, w, d = run_validate(rows)
ok("정정공시를 중복으로 오판하지 않는다",
   not any("중복" in x for x in f) and d["restatedFiscalYears"] == 1, str(f))

# 같은 키가 정말 두 벌이면 FAIL이어야 한다. 위 케이스와 갈리는 지점이 availableFrom이다.
rows = healthy_rows()
rows.append(dict(rows[0]))
f, w, d = run_validate(rows)
ok("(corp, fiscalYear, availableFrom) 완전 중복은 FAIL",
   any("중복" in x for x in f), str(f))

# 사업연도 구멍 — 수집이 통째로 빠진 해를 침묵으로 넘기지 않는다.
rows = [r for r in healthy_rows() if r["fiscalYear"] != 2019]
f, w, d = run_validate(rows)
ok("데이터가 0건인 사업연도는 FAIL",
   any("0건인 사업연도" in x for x in f) and d["yearsWithNoDataList"] == [2019], str(f))

print("\n[계약 2 — 연도별 매칭률]")
rows = []
for c in CORPS:
    for y in YEARS:
        # 2020년만 필수계정 하나를 비운다. 전체 평균으로 재면 묻히는 크기다.
        kw = {"revenue": None} if y == 2020 else {}
        rows.append(R(c, y, f"{y+1}-03-31", f"{y}-12-31", **kw))
f, w, d = run_validate(rows)
ok("특정 연도만 급락하면 WARN (FN-1.0에서는 아직 FAIL 아님)",
   any("연도별 매칭률" in x for x in w) and d["yearCoverageDropped"] == ["2020"],
   f"warns={w} dropped={d.get('yearCoverageDropped')}")
ok("연도별 계정 커버리지 리포트가 남는다",
   d["accountCoverageByYear"]["2020"]["revenue"] == 0.0,
   str(d["accountCoverageByYear"].get("2020")))

print("\n[계약 3 — ROE 이상치]")
rows = healthy_rows()
rows[0] = R("00000001", 2016, "2017-03-31", "2016-12-31", equity=10, netIncome=100)
rows[1] = R("00000001", 2017, "2018-03-31", "2017-12-31", equity=-500, netIncome=-1500)
f, w, d = run_validate(rows)
ok("|ROE| > 200% 건수를 센다", d["roeAbsOutlierCount"] == 2, str(d["roeAbsOutlierCount"]))
ok("자본잠식 건수를 센다", d["negativeEquityCount"] == 1)
ok("이상치를 제거하지 않는다 (사실이지 오류가 아니다)",
   not any("ROE" in x for x in f), str(f))
ok("이상치 표본이 진단에 남는다", len(d["roeAbsOutlierSample"]) == 2)

print("\n[그룹별 확보율]")
f, w, d = run_validate([r for r in healthy_rows() if r["corp"] != "00000009"])
ok("폐지 법인 확보율을 따로 남긴다 (전체 비율은 폐지분 공백을 가린다)",
   d["corpsWithDataRateByGroup"]["delisted"] == 0.0
   and d["corpsWithDataRateByGroup"]["current"] == 1.0,
   str(d["corpsWithDataRateByGroup"]))

print("\n[FAIL INJECTION]")
os.environ["A3_FAIL_INJECTION"] = "gate-test"
f, w, d = run_validate(healthy_rows())
ok("훅이 인수 조건을 강제 실패시킨다",
   any("FAIL INJECTION" in x for x in f) and d.get("failInjection") == "gate-test", str(f))
os.environ.pop("A3_FAIL_INJECTION")
f, w, d = run_validate(healthy_rows())
ok("훅을 끄면 다시 통과한다 (한 방향 훅이다)", not f, str(f))

print(f"\n{'='*54}")
print(f"통과 {passed} · 실패 {failed}")
sys.exit(0 if failed == 0 else 1)
