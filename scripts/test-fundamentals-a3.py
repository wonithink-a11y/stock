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

# 아래 fake_run은 m.dart_call·m.scan_corp을 갈아끼우고 되돌리지 않는다 — 그 뒤 테스트가
# 가짜를 계속 본다. 실물을 대상으로 하는 테스트는 여기서 잡아둔 참조를 쓴다.
# m.<이름>을 그냥 부르면 앞선 테스트가 남긴 가짜를 조용히 검사하게 되고, 그때는
# 통과든 실패든 실물에 대한 정보가 아니다.
REAL_DART_CALL = m.dart_call
REAL_SCAN_CORP = m.scan_corp

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

# 주요계정(fnlttSinglAcnt) 양식 — account_id가 없고 CFS·OFS가 한 응답에 함께 온다.
# FN-1.1이 실제로 쓰는 형태이므로 여기가 회귀의 본진이다.
def acnt_rows(fs_div, equity="1,000"):
    def row(sj, nm, amt):
        return {"fs_div": fs_div, "sj_div": sj, "account_nm": nm,
                "thstrm_amount": amt, "rcept_no": "20170331000001",
                "thstrm_dt": "2016.12.31 현재" if sj == "BS" else "2016.01.01 ~ 2016.12.31",
                "currency": "KRW"}
    return [row("BS", "유동자산", "500"), row("BS", "유동부채", "300"),
            row("BS", "부채총계", "800"), row("BS", "자본총계", equity),
            row("IS", "매출액", "2,000"), row("IS", "영업이익", "150"),
            row("IS", "당기순이익", "100")]


mixed = acnt_rows("CFS") + acnt_rows("OFS", equity="900")
sel, div = m.pick_fs_div(mixed, POL["source"]["fsDivPreference"])
ok("주요계정 응답에서 연결(CFS)을 먼저 고른다", div == "CFS" and len(sel) == 7, f"{div} {len(sel)}")
sel_o, div_o = m.pick_fs_div(acnt_rows("OFS"), POL["source"]["fsDivPreference"])
ok("연결이 없으면 별도(OFS)를 쓴다", div_o == "OFS" and len(sel_o) == 7, f"{div_o} {len(sel_o)}")

vals_a, how_a = m.match_accounts(sel, SPEC, ORDER)
ok("주요계정 양식에서 7계정 전부 (account_id 없이)",
   all(v is not None for v in vals_a.values()), str(vals_a))
ok("매칭 수단이 이름으로 기록된다 (태그가 없으므로)",
   all(h in ("nameExact", "nameContains") for h in how_a.values()), str(how_a))
ok("연결을 골랐으면 연결 값이 들어온다", vals_a["equity"] == 1000, str(vals_a["equity"]))

rec_a, why_a = m.build_record("00126380", "005930", 2016, sel, div, "26410", POL)
ok("주요계정 레코드도 PIT 계약을 만족한다",
   rec_a is not None and rec_a["availableFrom"] == "2017-03-31"
   and rec_a["periodEnd"] == "2016-12-31" and rec_a["fsDiv"] == "CFS", str(why_a))

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


def run_validate(rows, corps=None, reports_found=None, rejected=None):
    """reports_found·rejected는 finalize가 샤드 상태에서 집계해 넣는 값이다.
    기본값은 '버린 보고서 없음'이라 파싱률 100%가 된다."""
    m.fails.clear()
    m.warns.clear()
    n = len(rows) if reports_found is None else reports_found
    rej = rejected or {}
    diag = {"reportsFound": n, "recordRejected": rej,
            "periodEndParsedRate": (round(1 - rej.get("PERIOD_END_UNPARSED", 0) / n, 5)
                                    if n else None)}
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

print("\n[PIT 앵커 파싱률 — 분모가 산출물에 없는 손실]")
rows = healthy_rows()
# 확보한 보고서의 절반을 periodEnd 파싱 실패로 버렸다. 산출물만 보면 완벽하다 —
# 버려진 보고서는 레코드가 되지 않으므로 periodEndMissing은 여전히 0이다.
f, w, d = run_validate(rows, reports_found=len(rows) * 2,
                       rejected={"PERIOD_END_UNPARSED": len(rows)})
ok("확보 보고서의 절반을 버리면 FAIL",
   any("회계기간말 파싱률" in x for x in f) and d["periodEndParsedRate"] == 0.5, str(f))
ok("그래도 periodEndMissing 검사는 통과한다 (그래서 이 게이트가 필요하다)",
   not any("periodEnd 존재" in x for x in f), str(f))

f, w, d = run_validate(rows, reports_found=400, rejected={"PERIOD_END_UNPARSED": 1})
ok("400건 중 1건 손실(99.75%)은 임계 안이라 통과",
   d["periodEndParsedRate"] == 0.9975 and not any("회계기간말 파싱률" in x for x in f),
   f"{d['periodEndParsedRate']} {f}")

f, w, d = run_validate(rows, rejected={"RCEPT_NO_NOT_DATE": 5})
ok("rcept 실패는 파싱률을 깎지 않는다 (사유를 섞으면 원인이 흐려진다)",
   d["periodEndParsedRate"] == 1.0 and not any("회계기간말 파싱률" in x for x in f), str(f))

print("\n[계정별 매칭률 — 전수 기준선]")
rows = healthy_rows()
rows[0] = R("00000001", 2016, "2017-03-31", "2016-12-31",
            revenue=None, accountSource={**{k: "id" for k in SPEC}, "revenue": None})
f, w, d = run_validate(rows)
a = d["accountMappingHitRateByAccount"]
ok("계정별 매칭률이 남는다", a["revenue"]["hit"] == len(rows) - 1, str(a["revenue"]))
ok("매칭 수단별 분해가 남는다", a["revenue"]["byMethod"].get("MISS") == 1, str(a["revenue"]))
ok("커버리지 분자 여부를 표시한다",
   a["equity"]["inCoverageNumerator"] and not a["currentAssets"]["inCoverageNumerator"],
   str({k: v["inCoverageNumerator"] for k, v in a.items()}))

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

# ── resume 무결성 (FN-1.3) ────────────────────────────────────
# 여기서 지키는 것은 PIT가 아니라 상태다. 조용히 무너지는 방식이 같다 — 하드 실패로
# 0레코드인 법인이 '완료'로 기록되면 점수도 등급도 정상으로 보이고, 그 법인의 재무만
# 영원히 비어 있다. 진단에도 흔적이 남지 않는다(그 법인은 done에 있으니까).
import copy
import shutil
import tempfile

print("\n[실패 분류 — 기본값이 계약이다]")
ok("100·101은 재시도 불가 (파라미터 계약 위반이라 같은 답이 온다)",
   not m.is_retryable("100", POL) and not m.is_retryable("101", POL))
ok("800·900은 재시도 가능", m.is_retryable("800", POL) and m.is_retryable("900", POL))
ok("전송 실패(status 없음)는 재시도 가능", m.is_retryable(None, POL))
ok("분류표에 없는 새 status는 재시도 가능 — 모르는 실패는 '못 한다'가 아니다",
   m.is_retryable("777", POL))

print("\n[수집 계약 해시 — 범위를 표로 고정한다]")
base = m.collection_contract_hash(POL)


def mutate(fn):
    p = copy.deepcopy(POL)
    fn(p)
    return m.collection_contract_hash(p)


# '9개 필드'라는 개수가 아니라 **무엇이 들어가는가**가 계약이다. 이 표가 없으면
# 몇 달 뒤 누군가 stopAfter를 빼거나 requestSleepSeconds를 넣어도 아무도 모른다.
# 판단 기준: 이 값이 달랐다면 어제와 다른 수집 결과가 나왔는가?
SAME = [
    ("정책 version 승격", lambda p: p.update(version="FN-9.9")),
    ("인수 조건 임계", lambda p: p["acceptance"].update(coverageRateMinWarn=0.42)),
    ("일 한도·안전 여유분", lambda p: p["quota"].update(safetyMarginCalls=9999)),
    ("재시도 횟수·백오프",
     lambda p: p.update(retryAttempts=99, retryBackoffBase=5)),
    ("요청 간격(사실상 timeout류 운영값)",
     lambda p: p.update(requestSleepSeconds=9.9)),
    ("정책에 없던 새 운영 키 추가(timeout 등)",
     lambda p: p.update(timeout=[10, 40], someDiagnosticsToggle=True)),
    ("서킷 브레이커 임계", lambda p: p.update(circuitBreakerConsecutiveFailures=3)),
    ("정찰 대상·연도", lambda p: p.update(probeCorps=["00000001"], probeYear=1999)),
    ("산출 형식(정렬·압축)", lambda p: p["output"].update(gzipCompressLevel=1)),
    ("주석만 수정", lambda p: p["source"].update(endpointNote="바뀐 설명")),
    # 한 번 계약에 넣었다가 뺐다. retryable은 todo·shard_status·완료 게이트 어디에도
    # 들어가지 않아 수집 결과를 바꾸지 않는다 — 아래 [실패 분류는 수집을 가르지
    # 않는다] 절이 그것을 직접 검증한다. 넣으면 표를 고칠 때마다 수집을 잃는 비용만 남는다.
    ("실패 분류표(nonRetryableStatuses)",
     lambda p: p["failureClassification"].update(nonRetryableStatuses=["100", "800"])),
    ("실패 분류 기본값(defaultRetryable)",
     lambda p: p["failureClassification"].update(defaultRetryable=False)),
]
DIFF = [
    ("엔드포인트", lambda p: p["source"].update(endpoint="fnlttSinglAcntAll.json")),
    ("보고서 코드(reprtCode)", lambda p: p["source"].update(reprtCode="11012")),
    ("연결·별도 선별 순서",
     lambda p: p["source"].update(fsDivPreference=["OFS", "CFS"])),
    ("업종 엔드포인트", lambda p: p["source"].update(companyEndpoint="other.json")),
    ("사업연도 시작", lambda p: p.update(fiscalYearFrom=2016)),
    ("사업연도 끝", lambda p: p.update(fiscalYearTo=2024)),
    ("계정 매칭 순서", lambda p: p["accounts"].update(matchOrder=["nameExact", "id"])),
    ("계정 매칭 규칙(accounts.spec)",
     lambda p: p["accounts"]["spec"]["equity"].update(exact=["자본총계", "자본"])),
    ("조기 종료 연수(stopAfter)",
     lambda p: p.update(stopAfterConsecutiveEmptyYears=9)),
    # 목록 자체를 바꾸는 것은 '무엇이 계약인가'를 바꾸는 일이다.
    ("계약 경로 목록에서 하나 제거",
     lambda p: p["collectionContract"].update(
         fields=POL["collectionContract"]["fields"][:-1])),
    ("계약 경로 목록에 운영값 추가",
     lambda p: p["collectionContract"]["fields"].append("retryAttempts")),
]
for name, fn in SAME:
    ok(f"해시 동일 — {name}", mutate(fn) == base)
for name, fn in DIFF:
    ok(f"해시 변경 — {name}", mutate(fn) != base)
# 계약에 선언된 경로는 전부 실제로 해시에 반영돼야 한다. 선언만 되고 값이 안 읽히면
# 목록이 장식이 되고, 그 사실은 어떤 개별 테스트로도 드러나지 않는다.
for path in POL["collectionContract"]["fields"]:
    ok(f"선언된 경로가 실제로 해시에 반영된다 — {path}",
       m.dig(POL, path) is not None)

print("\n[완료 판정 — 저장하지 않고 계산한다]")
st = {"shard": 0, "corpsAssigned": 10, "corpsDone": [f"{i:08d}" for i in range(10)],
      "hardSkipped": {}}
ok("담당분을 다 모으면 완료", m.shard_status(st)["complete"])
st2 = {"shard": 0, "corpsAssigned": 10, "corpsDone": [f"{i:08d}" for i in range(9)],
       "hardSkipped": {"00000009": {"retryable": True}}}
s2 = m.shard_status(st2)
ok("미승인 하드스킵이 있으면 완료가 아니다 (남은 것이 0이어도)",
   s2["corpsRemaining"] == 0 and s2["hardSkippedOpen"] == 1 and not s2["complete"], str(s2))
# 보존식은 사실만으로 성립해야 한다 — remaining이 open이 아니라 hardSkipped 전체를
# 뺀 값이라야 승인 하나가 생기는 순간 남은 수가 흔들리지 않는다. 등식을 '검사'로
# 되돌리지 않고(구성상 항상 참이다, 교훈72) remaining의 정의로 확인한다.
ok("남은 수는 승인이 아니라 hardSkipped 전체를 뺀다 (사실이 먼저다)",
   s2["corpsRemaining"] == 10 - s2["corpsDone"] - s2["hardSkipped"], str(s2))
ok("conservationOk 필드는 없다 — 유도값으로 그 식을 검사하면 항상 참이다(교훈72)",
   "conservationOk" not in s2, str(sorted(s2)))
st3 = {"shard": 0, "corpsAssigned": 10, "corpsDone": [f"{i:08d}" for i in range(5)],
       "hardSkipped": {}}
ok("아직 안 돈 법인이 남으면 완료가 아니다", not m.shard_status(st3)["complete"])
# 분모를 모르는 상태(계약 해시 도입 전)를 0으로 읽으면 '남음 -1381' 같은 거짓 수치가
# 나오고, 그 거짓 수치가 게이트를 오탐시킨다. 모르는 것은 0이 아니다.
s4 = m.shard_status({"shard": 0, "corpsDone": ["00000001"], "hardSkipped": {}})
ok("담당 법인 수를 모르면 남은 수가 None이고 완료가 부정된다",
   s4["corpsRemaining"] is None and not s4["complete"]
   and not s4["corpsAssignedKnown"], str(s4))

print("\n[수집 루프 — done.add가 hard를 본다]")


def fake_run(tmp, script, prev_state=None, pol=None):
    """run_shard를 네트워크 없이 돌린다. scan_corp만 갈아끼우고 나머지는 실물이다 —
    분기를 흉내 내면 그 분기가 실제로 실행되는지는 검증하지 못한다."""
    m.SHARD_DIR = tmp
    m.KEY = "test-key"
    corps = {c: {"ticker": "000001", "group": "current"} for c in script}
    m.target_corps = lambda: corps
    m.dart_call = lambda *a, **k: ([{"rcept_no": "20200101000001"}], "000", None, None)
    if prev_state is not None:
        os.makedirs(tmp, exist_ok=True)
        json.dump(prev_state, open(f"{tmp}/_state-0.json", "w", encoding="utf-8"))

    def fake_scan(corp, ticker, pol, counters, state):
        return script[corp]
    m.scan_corp = fake_scan
    real_sleep = m.time.sleep
    m.time.sleep = lambda *a: None      # m.time은 실제 time 모듈이다 — 반드시 되돌린다
    try:
        with redirect_stdout(io.StringIO()) as buf:
            rc = m.run_shard(0, 1, copy.deepcopy(pol or POL), 0)
    finally:
        m.time.sleep = real_sleep
    return rc, json.load(open(f"{tmp}/_state-0.json", encoding="utf-8")), buf.getvalue()


# lastCause는 scan_corp이 돌려주는 계약의 일부다. 픽스처에서 빼면 run_shard이
# KeyError로 죽고, 그것이 '계약이 넷이다'를 강제하는 방식이다.
NO_FAIL = {"count": 0, "lastStatus": None, "lastReason": None, "lastCause": None}
HARD = {"count": 1, "lastStatus": None, "lastReason": "HTTP 503",
        "lastCause": "http:503"}
HARD_PERM = {"count": 1, "lastStatus": "100", "lastReason": "부적절한 값",
             "lastCause": "dart:100"}


def rec_for(corp):
    return {"corp": corp, "ticker": "000001", "fiscalYear": 2020,
            "availableFrom": "2021-03-31", "periodEnd": "2020-12-31"}


tmp = tempfile.mkdtemp()
try:
    script = {
        "00000001": ([rec_for("00000001")], NO_FAIL, False),   # 정상
        "00000002": ([], HARD, False),                          # 하드 실패 0레코드
        "00000003": ([rec_for("00000003")], HARD, False),        # 일부 연도만 실패
    }
    rc, st, log = fake_run(tmp, script)
    ok("하드 실패로 0레코드인 법인은 done에 들어가지 않는다",
       "00000002" not in st["corpsDone"], str(st["corpsDone"]))
    ok("그 법인은 hardSkipped에 남는다 (done도 남은 것도 아닌 세 번째 상태)",
       "00000002" in st["hardSkipped"], str(list(st["hardSkipped"])))
    ok("레코드가 나온 법인은 done이다",
       "00000001" in st["corpsDone"] and "00000003" in st["corpsDone"])
    ok("일부 연도만 실패한 법인은 done이되 부분실패로 센다",
       st["corpsPartialHard"] == 1, str(st["corpsPartialHard"]))
    hs = st["hardSkipped"]["00000002"]
    ok("hardSkipped는 사유와 재시도 가능 여부를 남긴다",
       hs["lastReason"] == "HTTP 503" and hs["retryable"] is True, str(hs))
    ok("attempts는 1에서 시작하고 firstSeen·lastSeen이 같다",
       hs["attempts"] == 1 and hs["firstSeen"] == hs["lastSeen"], str(hs))
    ok("complete는 상태 파일에 저장되지 않는다", "complete" not in st, str(list(st)))
    ok("미완료다 — 미승인 하드스킵이 남아 있다",
       not m.shard_status(st)["complete"] and m.shard_status(st)["hardSkippedOpen"] == 1)
    # 실물 수집 루프가 남긴 상태에 S(상태 불변식)를 그대로 건다. 픽스처가 아니라
    # run_shard이 실제로 쓴 파일이라, 루프가 상태를 어떻게 만드는지가 검사 대상이다.
    ok("실행이 남긴 상태가 S1·S2·S3를 모두 만족한다",
       m.state_invariant_violations(st) == [], str(m.state_invariant_violations(st)))

    # 두 번째 실행 — 재시도되고 성공하면 hardSkipped에서 빠진다
    script2 = dict(script)
    script2["00000002"] = ([rec_for("00000002")], NO_FAIL, False)
    read_paths = []
    orig_load = m.load_json

    def spy_load(path):
        read_paths.append(str(path))
        return orig_load(path)
    m.load_json = spy_load
    rc, st2, log2 = fake_run(tmp, script2)
    m.load_json = orig_load
    ok("재시도해 성공하면 done으로 옮겨진다",
       "00000002" in st2["corpsDone"], str(st2["corpsDone"]))
    ok("성공하면 hardSkipped에서 지워진다 (안 지우면 두 집합이 겹쳐 보존식이 깨진다)",
       "00000002" not in st2["hardSkipped"], str(list(st2["hardSkipped"])))
    ok("이제 완료다", m.shard_status(st2)["complete"], str(m.shard_status(st2)))
    # 원칙 3 — resume은 diagnostics를 읽지 않는다. 문장으로만 두면 다음 사람이
    # 편의상 진단을 읽어도 아무도 모른다.
    ok("resume 경로가 _diagnostics를 읽지 않는다 (운영 계약과 진단 계약의 분리)",
       not any("_diagnostics" in p for p in read_paths),
       str([p for p in read_paths if "_diagnostics" in p]))

    # 재시도 불가 실패는 승인 없이는 안 닫힌다
    tmp2 = tempfile.mkdtemp()
    rc, st3, _ = fake_run(tmp2, {"00000004": ([], HARD_PERM, False)})
    ok("재시도 불가(100)로 분류된다",
       st3["hardSkipped"]["00000004"]["retryable"] is False,
       str(st3["hardSkipped"]["00000004"]))
    ok("승인 채널이 없으므로 열린 채로 남는다 (조용히 통과하는 것보다 낫다)",
       m.shard_status(st3)["hardSkippedOpen"] == 1)
    shutil.rmtree(tmp2, ignore_errors=True)

    print("\n[실패 분류는 수집을 가르지 않는다 — 계약 해시에서 뺀 근거]")
    # 이 절이 없으면 failureClassification을 계약 해시에서 뺀 판단이 검증되지 않은
    # 주장으로 남는다. retryable이 todo·완료 게이트를 가르기 시작하면 여기가 먼저 깨지고,
    # 그때는 그 표가 collectionContract.fields로 들어가야 한다.
    lenient = copy.deepcopy(POL)
    lenient["failureClassification"]["nonRetryableStatuses"] = []   # 100도 재시도 가능
    tmp_r1, tmp_r2 = tempfile.mkdtemp(), tempfile.mkdtemp()
    _, s_strict, _ = fake_run(tmp_r1, {"00000004": ([], HARD_PERM, False)})
    _, s_lenient, _ = fake_run(tmp_r2, {"00000004": ([], HARD_PERM, False)}, pol=lenient)
    ok("분류표가 라벨을 실제로 바꾼다 (검사가 무의미하지 않다는 확인)",
       s_strict["hardSkipped"]["00000004"]["retryable"] is False
       and s_lenient["hardSkipped"]["00000004"]["retryable"] is True)
    strip = lambda s: json.dumps(  # noqa: E731
        {**s, "hardSkipped": {k: {kk: vv for kk, vv in v.items() if kk != "retryable"}
                              for k, v in s["hardSkipped"].items()}},
        ensure_ascii=False, sort_keys=True)
    ok("라벨을 빼면 두 실행의 상태가 완전히 같다 — 분류는 수집 결과를 바꾸지 않는다",
       strip(s_strict) == strip(s_lenient))
    ok("재시도 불가로 분류돼도 완료 판정은 같다 (게이트는 retryable을 보지 않는다)",
       m.shard_status(s_strict) == m.shard_status(s_lenient), str(m.shard_status(s_strict)))
    # 라벨은 다음 재시도에서 현재 표로 다시 계산된다 — 낡음이 자가 치유되므로
    # 표를 바꿨다고 이미 모은 것을 버릴 이유가 없다.
    _, s_healed, _ = fake_run(tmp_r1, {"00000004": ([], HARD_PERM, False)}, pol=lenient)
    ok("표를 바꾸고 다시 돌리면 옛 라벨이 현재 표로 갱신된다 (낡음이 자가 치유된다)",
       s_healed["hardSkipped"]["00000004"]["retryable"] is True
       and s_healed["hardSkipped"]["00000004"]["attempts"] == 2,
       str(s_healed["hardSkipped"]["00000004"]))
    shutil.rmtree(tmp_r1, ignore_errors=True)
    shutil.rmtree(tmp_r2, ignore_errors=True)

    print("\n[승인 채널 — 수집을 바꾸지 않고 완료 판정만 닫는다]")
    REG = json.load(open(os.path.join(ROOT, "config/policies/registry.json"),
                         encoding="utf-8"))
    ok("수집기가 읽는 승인 파일이 registry.approvals와 같다 (갈라지면 approvalHash가 "
       "실제로 읽은 목록과 다른 것을 증명하게 된다)",
       m.DECLARED_GAPS == REG["approvals"]["declaredGapsA3"],
       f'{m.DECLARED_GAPS} vs {REG["approvals"]["declaredGapsA3"]}')
    ok("커밋된 승인 목록은 비어 있다 (빈 배열도 해시 대상이다)",
       m.declared_gaps() == set(), str(m.declared_gaps()))

    tmp4 = tempfile.mkdtemp()
    st_perm = {"shard": 0, "corpsAssigned": 2, "corpsDone": ["00000003"],
               "hardSkipped": {"00000004": {"retryable": False}}}
    ok("승인 전에는 열린 공백이라 완료가 아니다",
       not m.shard_status(st_perm)["complete"]
       and m.shard_status(st_perm)["hardSkippedOpen"] == 1)
    m._declared_cache = {"00000004"}
    s_ok = m.shard_status(st_perm)
    ok("승인하면 완료된다 (열린 공백이 0이 된다)",
       s_ok["complete"] and s_ok["hardSkippedOpen"] == 0
       and s_ok["declaredHardSkipped"] == 1, str(s_ok))
    # 사실은 승인과 무관하다. hardSkipped 전체와 남은 수는 승인 전후로 같고,
    # 승인이 움직이는 것은 분류(hardSkippedOpen)와 그것이 낳는 완료 판정뿐이다.
    ok("승인해도 사실은 그대로다 (hardSkipped 전체와 남은 수가 안 흔들린다)",
       s_ok["hardSkipped"] == 1
       and s_ok["corpsRemaining"] == m.shard_status(st_perm)["corpsRemaining"], str(s_ok))
    # 원칙 4 — 승인은 규칙이 아니라 운영 결정이므로 수집 동작을 바꾸지 않는다.
    # 바꾼다면 그것은 승인이 아니라 규칙이고, 수집 계약 해시에 들어가야 한다.
    #
    # 이것을 '재시도되더라' 수준이 아니라 **산출물 바이트 동일성**으로 증명한다.
    # 승인 유무로 collect 결과(state·JSONL·attempts)가 한 바이트라도 갈리면
    # approvalHash를 collectionContractHash와 분리해 둘 근거가 사라진다.
    GAP_SCRIPT = {"00000004": ([], HARD_PERM, False),
                  "00000006": ([rec_for("00000006")], NO_FAIL, False)}

    def collect_twice(declared):
        """같은 시나리오를 승인 설정만 바꿔 두 번 실행하고 산출물을 통째로 돌려준다."""
        d = tempfile.mkdtemp()
        m._declared_cache = set(declared)
        for _ in range(2):          # 두 번 돌려 attempts 증가 경로까지 밟는다
            fake_run(d, GAP_SCRIPT)
        st = open(f"{d}/_state-0.json", encoding="utf-8").read()
        jl = open(f"{d}/shard-0.jsonl", encoding="utf-8").read()
        shutil.rmtree(d, ignore_errors=True)
        return st, jl

    st_open, jl_open = collect_twice([])
    st_appr, jl_appr = collect_twice(["00000004"])
    ok("승인 유무와 무관하게 collect의 state 바이트가 동일하다",
       st_open == st_appr,
       "state가 갈렸다 — 승인이 수집을 바꾸면 두 해시를 분리할 수 없다")
    ok("승인 유무와 무관하게 collect의 JSONL 바이트가 동일하다", jl_open == jl_appr)
    s_open = json.loads(st_open)
    ok("두 실행 모두 attempts가 2까지 올라간다 (승인이 재시도를 멈추지 않는다)",
       s_open["hardSkipped"]["00000004"]["attempts"] == 2
       and json.loads(st_appr)["hardSkipped"]["00000004"]["attempts"] == 2,
       str(s_open["hardSkipped"]["00000004"]["attempts"]))
    # 갈리는 것은 계산값 둘뿐이어야 한다.
    m._declared_cache = set()
    a = m.shard_status(s_open)
    m._declared_cache = {"00000004"}
    b = m.shard_status(s_open)
    ok("승인이 바꾸는 것은 hardSkippedOpen·complete 계산뿐이다",
       not a["complete"] and a["hardSkippedOpen"] == 1
       and b["complete"] and b["hardSkippedOpen"] == 0,
       f"{a} vs {b}")
    ok("승인해도 사실 항(corpsDone·hardSkipped·corpsRemaining)은 그대로다",
       (a["corpsDone"], a["hardSkipped"], a["corpsRemaining"])
       == (b["corpsDone"], b["hardSkipped"], b["corpsRemaining"]), f"{a} vs {b}")

    # finalize 게이트가 실제로 뒤집히는지 — 같은 상태·같은 산출물로 승인만 바꾼다.
    def finalize_verdict(declared):
        d, out = tempfile.mkdtemp(), tempfile.mkdtemp()
        m._declared_cache = set(declared)
        fake_run(d, GAP_SCRIPT)
        m.SHARD_DIR, m.OUT_DIR = d, out
        m.target_corps = lambda: {c: {"ticker": "000001", "group": "current"}
                                  for c in GAP_SCRIPT}
        try:
            with redirect_stdout(io.StringIO()):
                m.run_finalize(copy.deepcopy(POL))
        except SystemExit:
            pass
        diag = json.load(open(f"{out}/_diagnostics.json", encoding="utf-8"))
        shutil.rmtree(d, ignore_errors=True)
        shutil.rmtree(out, ignore_errors=True)
        return diag

    d_open = finalize_verdict([])
    d_appr = finalize_verdict(["00000004"])
    ok("승인 전 finalize는 미완료 샤드에서 막힌다",
       d_open.get("aborted") is True
       and "담당분을 마치지 않은" in d_open.get("abortReason", ""),
       str(d_open.get("abortReason"))[:120])
    ok("승인 후 finalize는 그 게이트를 통과한다 (이후는 인수 조건의 몫이다)",
       not d_appr.get("aborted"), str(d_appr.get("abortReason"))[:120])
    ok("승인이 진단에 값으로 남는다 (approvalHash는 어느 목록인지만 고정한다)",
       d_appr.get("declaredGaps") == ["00000004"]
       and d_appr.get("declaredGapsCount") == 1, str(d_appr.get("declaredGaps")))
    m._declared_cache = set()
    shutil.rmtree(tmp4, ignore_errors=True)

    real_path = m.DECLARED_GAPS
    for bad, why in [
        ({"gaps": [{"corp": "123", "reason": "x"}]}, "corp 계약 위반"),
        ({"gaps": [{"corp": "00000004", "reason": "  "}]}, "사유 없는 승인"),
        ({"gaps": "not-a-list"}, "gaps가 배열이 아님"),
    ]:
        p = os.path.join(tmp, "bad-gaps.json")
        json.dump(bad, open(p, "w", encoding="utf-8"))
        m.DECLARED_GAPS, m._declared_cache = p, None
        try:
            m.declared_gaps()
            ok(f"승인 목록 거부 — {why}", False, "예외가 안 났다")
        except (ValueError, KeyError):
            ok(f"승인 목록 거부 — {why}", True)
    m.DECLARED_GAPS, m._declared_cache = os.path.join(tmp, "nope.json"), None
    try:
        m.declared_gaps()
        ok("승인 파일 부재는 빈 목록이 아니라 오류다", False, "예외가 안 났다")
    except FileNotFoundError:
        ok("승인 파일 부재는 빈 목록이 아니라 오류다 "
           "('승인이 없다'와 '채널이 배선되지 않았다'는 다르다)", True)
    m.DECLARED_GAPS, m._declared_cache = real_path, None

    print("\n[상태 이관 — 버전 승격이 수집을 버리지 않는다]")
    tmp3 = tempfile.mkdtemp()
    m.SHARD_DIR = tmp3
    legacy = {"stage": "A3", "shard": 0, "shards": 1, "fundamentalsPolicy": "FN-1.2",
              "corpsDone": ["00000001"], "callsUsedToday": 0, "lastRunDate": None,
              "reportsFound": 3, "recordRejected": {}, "runDates": ["2026-08-05"],
              "complete": False}
    os.makedirs(tmp3, exist_ok=True)
    json.dump(legacy, open(f"{tmp3}/_state-0.json", "w", encoding="utf-8"))
    with redirect_stdout(io.StringIO()):
        got = m.load_state(0, 1, POL)
    ok("계약 해시 도입 전(FN-1.2) 상태를 이어받는다 — 1,381법인이 버려지지 않는다",
       got["corpsDone"] == ["00000001"] and got["reportsFound"] == 3, str(got))
    ok("이관 시 현재 계약 해시가 채워진다",
       got["collectionContractHash"] == base, str(got.get("collectionContractHash")))

    # 실제 파일에서 run_shard 전체를 거쳐 이어받는지까지 본다. load_state만 보면
    # '읽기는 했다'까지고, 이어받은 상태로 수집이 실제로 이어지는지는 모른다 —
    # 다음 정책 승격에서 안전하다고 말하려면 이 경로가 회귀에 있어야 한다.
    tmp5 = tempfile.mkdtemp()
    legacy5 = {"stage": "A3", "shard": 0, "shards": 1,
               "fundamentalsPolicy": "FN-1.2", "corpsDone": ["00000001"],
               "callsUsedToday": 0, "lastRunDate": None,
               "reportsFound": 5, "recordRejected": {"RCEPT_NO_NOT_DATE": 1},
               "runDates": ["2026-08-05"], "complete": False}
    os.makedirs(tmp5, exist_ok=True)
    json.dump(legacy5, open(f"{tmp5}/_state-0.json", "w", encoding="utf-8"))
    with open(f"{tmp5}/shard-0.jsonl", "w", encoding="utf-8") as fh:
        fh.write(json.dumps(rec_for("00000001"), ensure_ascii=False) + "\n")
    scanned = []

    def scan_spy(corp, ticker, pol, counters, state):
        scanned.append(corp)
        return ([rec_for(corp)], NO_FAIL, False)

    m.SHARD_DIR = tmp5
    m.KEY = "test-key"
    m.target_corps = lambda: {c: {"ticker": "000001", "group": "current"}
                              for c in ("00000001", "00000005")}
    m.dart_call = lambda *a, **k: ([{"rcept_no": "20200101000001"}], "000", None, None)
    m.scan_corp = scan_spy
    _sleep = m.time.sleep
    m.time.sleep = lambda *a: None
    try:
        with redirect_stdout(io.StringIO()):
            m.run_shard(0, 1, copy.deepcopy(POL), 0)
    finally:
        m.time.sleep = _sleep
    st5 = json.load(open(f"{tmp5}/_state-0.json", encoding="utf-8"))
    recs5 = [json.loads(l) for l in open(f"{tmp5}/shard-0.jsonl", encoding="utf-8")]
    ok("legacy 상태에서 run_shard가 이미 끝난 법인을 다시 수집하지 않는다",
       scanned == ["00000005"], str(scanned))
    ok("legacy 산출물의 레코드가 보존된다 (재개분과 합쳐진다)",
       sorted(r["corp"] for r in recs5) == ["00000001", "00000005"], str(recs5))
    ok("legacy 누적 카운터가 이어진다 (파싱률의 분모가 조용히 작아지지 않는다)",
       st5["reportsFound"] == 5 and st5["recordRejected"] == {"RCEPT_NO_NOT_DATE": 1},
       str({k: st5[k] for k in ("reportsFound", "recordRejected")}))
    ok("이관된 상태에 정책 버전 이력이 누적되기 시작한다",
       st5["policyVersions"] == [POL["version"]], str(st5.get("policyVersions")))
    ok("이관 후 담당 법인 수가 채워져 완료 판정이 가능해진다",
       m.shard_status(st5)["corpsAssignedKnown"]
       and m.shard_status(st5)["complete"], str(m.shard_status(st5)))
    shutil.rmtree(tmp5, ignore_errors=True)
    m.SHARD_DIR = tmp3
    json.dump({**legacy, "fundamentalsPolicy": "FN-0.9"},
              open(f"{tmp3}/_state-0.json", "w", encoding="utf-8"))
    with redirect_stdout(io.StringIO()):
        got2 = m.load_state(0, 1, POL)
    ok("대조하지 않은 옛 버전은 이관하지 않는다 (다른 규칙의 레코드를 이어받는 경로)",
       got2["corpsDone"] == [], str(got2["corpsDone"]))
    # 이관은 일회성 경로다. FN-1.3부터 상태가 collectionContractHash를 들고 다니므로
    # 이후 버전 승격에는 이관이 필요 없다 — 계약이 같으면 해시가 같아 그냥 이어받고,
    # 계약이 바뀌었으면 폐기가 의도된 동작이다. 따라서 이 집합은 자라면 안 된다.
    # 자라는 순간 '값 대조 없이 다른 규칙의 상태를 이어받는' 경로가 열린다.
    ok("legacy 이관 목록은 FN-1.2 하나뿐이다 (이관은 일회성이며 자라면 안 된다)",
       m.LEGACY_CONTRACT_POLICIES == {"FN-1.2"},
       str(m.LEGACY_CONTRACT_POLICIES))
    json.dump({**legacy, "collectionContractHash": "sha256:deadbeefdeadbeef"},
              open(f"{tmp3}/_state-0.json", "w", encoding="utf-8"))
    with redirect_stdout(io.StringIO()):
        got3 = m.load_state(0, 1, POL)
    ok("계약 해시가 다르면 폐기한다 (레코드 내용 규칙이 바뀐 경우)",
       got3["corpsDone"] == [], str(got3["corpsDone"]))
    with redirect_stdout(io.StringIO()):
        got4 = m.load_state(0, 4, POL)
    ok("샤드 수가 바뀌어도 폐기한다 (담당 법인 배분이 달라진다)",
       got4["corpsDone"] == [], str(got4["corpsDone"]))
    shutil.rmtree(tmp3, ignore_errors=True)
finally:
    shutil.rmtree(tmp, ignore_errors=True)

print("\n[네트워크 의존성 격리 — 읽기 전용 경로는 requests를 요구하지 않는다]")
# collect #2에서 persist 잡이 여기서 죽었다. 그 잡에는 Install deps 스텝이 없는데
# 스크립트가 최상단에서 requests를 import하고 있었고, 그 결과 7샤드의 하루치 진행이
# 커밋되지 않았다. 네트워크를 쓰지 않는 경로가 HTTP 라이브러리 때문에 죽으면 안 된다.
import subprocess

_blocker = tempfile.mkdtemp()
with open(os.path.join(_blocker, "requests.py"), "w", encoding="utf-8") as fh:
    fh.write("raise ImportError('requests 없음 — 이 테스트가 만든 상황이다')\n")
_shards_dir = tempfile.mkdtemp()
json.dump({"stage": "A3", "shard": 0, "shards": 8, "corpsAssigned": 2,
           "corpsDone": ["00000001"], "hardSkipped": {}, "callsUsedToday": 10,
           "lastRunDate": "2026-08-06", "reportsFound": 3, "recordRejected": {},
           "runDates": ["2026-08-06"]},
          open(os.path.join(_shards_dir, "_state-0.json"), "w", encoding="utf-8"))

_probe = f'''
import sys, importlib.util
sys.path.insert(0, {_blocker!r})
try:
    import requests
    print("BLOCKER_FAILED"); sys.exit(9)
except ImportError:
    pass
spec = importlib.util.spec_from_file_location("a3", {os.path.join(ROOT, "scripts", "build-fundamentals-a3.py")!r})
m = importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)
m.SHARD_DIR = {_shards_dir!r}
sys.exit(m.run_summary())
'''
_r = subprocess.run([sys.executable, "-c", _probe], capture_output=True, text=True,
                    encoding="utf-8", cwd=ROOT)
ok("requests가 없어도 모듈이 import된다 (최상단 import가 아니다)",
   "BLOCKER_FAILED" not in _r.stdout and "ModuleNotFoundError" not in (_r.stderr or "")
   and "No module named 'requests'" not in (_r.stderr or ""),
   (_r.stderr or "")[-300:])
ok("requests가 없어도 --summary가 정상 종료한다 (persist가 진행을 커밋할 수 있다)",
   _r.returncode == 0, f"exit={_r.returncode} {(_r.stderr or '')[-300:]}")
ok("그 상태에서도 요약이 실제 수치를 낸다",
   "법인 완료 1/2" in _r.stdout, _r.stdout[:200])
shutil.rmtree(_blocker, ignore_errors=True)
shutil.rmtree(_shards_dir, ignore_errors=True)

print("\n[상태 전이 불변식 — 네 식이 서로 독립으로 발동한다]")
# 완료 상태 · 실패 상태 · 담당 범위 · 산출물 일관성. 복구 절차에서 쓴 계약을
# 저장소로 옮긴 것이다 — 매 실행 성립해야 하는 불변식이라 임시 스크립트에만
# 두면 다음 실행부터 아무도 확인하지 않는다.
_PREV = {"done": {"A", "B"}, "hard": {"X"}, "assigned": 10}
_now = lambda **kw: {"corpsDone": ["A", "B"], "hardSkipped": {"X": {}},   # noqa: E731
                     "corpsAssigned": 10, **kw}
_R = lambda *cs: [{"corp": c} for c in cs]                                # noqa: E731

for _label, _st, _recs, _want in [
    ("정상 — 변화 없음", _now(), _R("A"), 0),
    ("정상 — 하드스킵이 done으로 해소",
     _now(corpsDone=["A", "B", "X"], hardSkipped={}), _R("A", "X"), 0),
    ("정상 — 보고서 0건 법인은 산출물에 없어도 된다", _now(), _R(), 0),
    ("1 위반 — corpsDone 후퇴", _now(corpsDone=["A"]), _R(), 1),
    ("2 위반 — 하드스킵이 해결되지도 남지도 않고 사라짐", _now(hardSkipped={}), _R(), 1),
    ("3 위반 — corpsAssigned가 바뀜", _now(corpsAssigned=12), _R(), 1),
    ("4 위반 — 산출물에 corpsDone 밖의 법인", _now(), _R("A", "Z"), 1),
    # 겹침은 전이가 아니라 상태의 성질이다. 여기서 빠졌다는 것을 못 박는다 —
    # 양쪽에 두면 계약이 두 벌이 되고 한 곳만 고치는 경로가 생긴다(교훈44).
    ("겹침은 전이 검사의 소관이 아니다 (상태 불변식 5가 든다)",
     _now(corpsDone=["A", "B", "X"], hardSkipped={"X": {}}), _R(), 0),
]:
    _v = m.state_transition_violations(_PREV, _st, _recs)
    ok(f"{_label}", (1 if _v else 0) == _want, str(_v[:1]))


print("\n[상태 불변식 — 실행 여부와 무관한 성질은 읽는 쪽에서도 잰다]")
# 전이 검사는 run_shard에서만, 그 실행이 건드린 샤드에 대해서만 돈다. 예산 소진으로
# 즉시 끝난 샤드나 잡이 죽어 안 돌아간 샤드는 아무도 보지 않는다 — finalize가
# 다시 재는 이유다. 5번은 코드의 현재 모양(done.add와 hardSkipped.pop이 붙어 있음)이
# 지켜주는 것이지 상태가 지켜주는 것이 아니라서 특히 그렇다.
_HASH = "sha256:0000000000000000"


def _stt(**kw):
    return {"shard": 0, "corpsDone": ["A", "B"], "hardSkipped": {"X": {}},
            "corpsAssigned": 10, "collectionContractHash": _HASH, **kw}


for _label, _st, _want in [
    ("정상 상태는 위반이 없다", _stt(), 0),
    ("5 위반 — done ∩ hardSkipped != ∅",
     _stt(corpsDone=["A", "B", "X"]), 1),
    ("6 위반 — collectionContractHash가 None",
     _stt(collectionContractHash=None), 1),
    ("6 위반 — 키 자체가 없어도 같다 (FN-1.3 이전 상태)",
     {k: v for k, v in _stt().items() if k != "collectionContractHash"}, 1),
    ("7 위반 — done + hardSkipped > assigned", _stt(corpsAssigned=2), 1),
    # 모르는 것은 0이 아니다(교훈57). 분모를 모르면 7번은 판정 대상이 아니다 —
    # 0으로 읽으면 담당분을 아직 못 센 샤드가 전부 손상으로 잡힌다.
    ("corpsAssigned가 None이면 7번을 재지 않는다", _stt(corpsAssigned=None), 0),
]:
    _v = m.state_invariant_violations(_st)
    ok(_label, (1 if _v else 0) == _want, str(_v[:1]))

ok("위반이 여럿이면 여럿을 돌려준다 (첫 건에서 멈추지 않는다)",
   len(m.state_invariant_violations(
       {"shard": 3, "corpsDone": ["A", "X"], "hardSkipped": {"X": {}},
        "corpsAssigned": 1})) == 3,
   str(m.state_invariant_violations(
       {"shard": 3, "corpsDone": ["A", "X"], "hardSkipped": {"X": {}},
        "corpsAssigned": 1})))
ok("위반 메시지가 어느 샤드인지 말한다 (8개를 뒤지지 않게)",
   all("샤드 3" in v for v in m.state_invariant_violations(
       {"shard": 3, "corpsDone": ["X"], "hardSkipped": {"X": {}}})))

# 같은 손상 상태를 두 눈으로 본다. shard_status는 remaining을 음수로 내놓을 뿐
# 아무 판정도 하지 않고(그 자리에 있던 conservationOk는 구성상 항상 참이라 제거했다),
# 손상을 말하는 것은 S가 유일하다. 필드가 되살아나면 첫 단언이 깨진다.
_bad_st = {"shard": 0, "corpsDone": ["A", "X"], "hardSkipped": {"X": {}},
           "corpsAssigned": 1, "collectionContractHash": _HASH}
_bad = m.shard_status(_bad_st)
ok("shard_status에 conservationOk가 없다 (유도값으로 그 식을 검사하면 항상 참)",
   "conservationOk" not in _bad, str(sorted(_bad)))
ok("손상은 remaining을 음수로 만들 뿐 스스로 신고하지 않는다",
   _bad["corpsRemaining"] == -2, str(_bad))
ok("그 손상을 말하는 것은 S다 (S1 겹침 · S3 범위 초과)",
   len(m.state_invariant_violations(_bad_st)) == 2,
   str(m.state_invariant_violations(_bad_st)))

# S2는 읽는 쪽 검사다. 쓰는 쪽에서도 막아야 그런 파일이 애초에 안 생긴다 —
# 저쪽은 이미 디스크에 있는 잘못된 파일을 발견할 뿐이다.
_tmp_sp = tempfile.mkdtemp()
_saved_dir, m.SHARD_DIR = m.SHARD_DIR, _tmp_sp
try:
    m.save_progress(0, {"shard": 0, "corpsDone": [], "hardSkipped": {}}, {})
    _sp_raised = False
except RuntimeError:
    _sp_raised = True
finally:
    m.SHARD_DIR = _saved_dir
    shutil.rmtree(_tmp_sp, ignore_errors=True)
ok("save_progress가 계약 해시 없는 상태를 쓰기를 거부한다 (쓰는 쪽에서 막는다)",
   _sp_raised)


print("\n[병합 검사 M — 샤드 하나로는 잴 수 없어 finalize에만 있다]")
# 기준은 하나다: 이 검사가 샤드 단위에서 가능한가, 병합된 전체에서만 가능한가.
# 후자면 finalize에 있어야 한다. M1·M2가 그 사례다 — 각 샤드는 자기 안에서 전부
# 정상으로 보이고, 합쳐야만 샤딩이 달라졌다는 것이 드러난다.
_WF3 = os.path.join(ROOT, ".github/workflows/fundamentals-a3.yml")
_wf3 = open(_WF3, encoding="utf-8").read()
ok("워크플로의 SHARDS와 정책의 shards가 같다 (M1의 분모가 갈리는 첫 경로)",
   f"SHARDS: {POL['shards']}" in _wf3, f"정책 shards={POL['shards']}")

_src = open(os.path.join(ROOT, "scripts/build-fundamentals-a3.py"),
            encoding="utf-8").read()
ok("M 검사가 finalize에만 있다 (run_shard은 자기 샤드만 보므로 잴 수 없다)",
   _src.count("stateMergedViolations") >= 1
   and "stateMergedViolations" not in _src.split("def run_finalize")[0],
   "run_shard 쪽에 M이 새어 들어갔다")
ok("M 위반도 완료 판정보다 먼저 중단시킨다",
   _src.index("if invariant_bad or merged_bad") < _src.index("if incomplete:"))
# M1의 분모에 빠진 항이 있으면 판정하지 않는다. 실제로 이것 없이 돌렸더니
# '합계 3326 != 대상 3801'이 나왔는데, 그 475는 샤딩 변경이 아니라 담당분을 아직
# 안 센 샤드 6이었다 — 거짓 수치가 게이트를 엉뚱한 원인으로 물게 한다(교훈57).
ok("담당분을 모르는 샤드가 있으면 M1을 재지 않는다 (0으로 읽지 않는다)",
   "if assigned_unknown:" in _src
   and _src.index("if assigned_unknown:") < _src.index("elif assigned_sum != len(targets)"))


# M3 — 한 법인의 레코드가 한 샤드에서만 나오는가. 실물 run_finalize를 2샤드 구성으로
# 돌린다. 상태는 배타적으로 두고 **산출물만** 갈라놓는 것이 핵심이다 — M2(상태)가
# 통과하는데 M3(산출물)가 잡아야 겹치지 않는 검사임이 증명된다.
def m3_verdict(shard0_rows, shard1_rows, done0, done1):
    d, out = tempfile.mkdtemp(), tempfile.mkdtemp()
    os.makedirs(d, exist_ok=True)
    _h = m.collection_contract_hash(POL)
    for i, (rws, dn) in enumerate([(shard0_rows, done0), (shard1_rows, done1)]):
        with open(f"{d}/shard-{i}.jsonl", "w", encoding="utf-8") as f:
            for r in rws:
                f.write(json.dumps(r, ensure_ascii=False) + "\n")
        json.dump({"shard": i, "shards": 2, "corpsDone": sorted(dn), "hardSkipped": {},
                   "corpsAssigned": len(dn), "collectionContractHash": _h,
                   "reportsFound": len(rws), "recordRejected": {}, "runDates": ["2026-08-06"],
                   "policyVersions": [POL["version"]], "callsUsedToday": 0},
                  open(f"{d}/_state-{i}.json", "w", encoding="utf-8"))
    saved_dir, saved_out, saved_tc = m.SHARD_DIR, m.OUT_DIR, m.target_corps
    m.SHARD_DIR, m.OUT_DIR = d, out
    m.target_corps = lambda: {c: {"ticker": "000001", "group": "current"}
                              for c in sorted(set(done0) | set(done1))}
    try:
        with redirect_stdout(io.StringIO()):
            m.run_finalize(copy.deepcopy(POL))
    except SystemExit:
        pass
    finally:
        m.SHARD_DIR, m.OUT_DIR, m.target_corps = saved_dir, saved_out, saved_tc
    dg = json.load(open(f"{out}/_diagnostics.json", encoding="utf-8"))
    shutil.rmtree(d, ignore_errors=True)
    shutil.rmtree(out, ignore_errors=True)
    return dg


def _rec(corp, year, af):
    return {"corp": corp, "ticker": "000001", "fiscalYear": year, "availableFrom": af,
            "periodEnd": f"{year}-12-31"}


# 정상 — 법인이 샤드별로 나뉘어 있고 레코드도 따라간다
_m3_ok = m3_verdict([_rec("00000001", 2020, "2021-03-31")],
                    [_rec("00000002", 2020, "2021-03-31")],
                    ["00000001"], ["00000002"])
ok("정상 병합은 M3 위반이 없다",
   _m3_ok.get("corpsSplitAcrossShards") == 0
   and _m3_ok.get("recordKeysInMultipleShards") == 0, str(_m3_ok.get("abortReason"))[:150])

# 분산 — 같은 법인의 다른 사업연도가 두 샤드에. 상태(corpsDone)는 배타적으로 두므로
# M2는 통과하고, 키도 안 겹쳐 중복 검사도 통과한다. M3 없이는 아무도 못 보던 경우다.
_m3_split = m3_verdict([_rec("00000001", 2020, "2021-03-31")],
                       [_rec("00000001", 2021, "2022-03-31")],
                       ["00000001"], ["00000002"])
ok("분산 픽스처에서 M2(상태)는 통과한다 — 두 검사가 겹치지 않는다는 증거",
   _m3_split.get("stateMergedViolations") == [],
   str(_m3_split.get("stateMergedViolations")))
ok("분산 — 키가 안 겹쳐도 한 법인이 두 샤드에 걸치면 M3 위반",
   _m3_split.get("aborted") is True
   and _m3_split.get("corpsSplitAcrossShards") == 1, str(_m3_split.get("abortReason"))[:150])
ok("분산은 '분산'이라고 이름을 말한다 (복제와 대응이 다르다)",
   "분산이다" in _m3_split.get("abortReason", ""),
   _m3_split.get("abortReason", "")[:150])
ok("분산에서는 겹치는 레코드 키가 0이다 (중복 검사로는 안 잡힌다는 증거)",
   _m3_split.get("recordKeysInMultipleShards") == 0)

# 복제 — 같은 키가 두 샤드에. validate의 중복 검사도 잡지만 '데이터 중복'이라고만
# 말한다. M3가 먼저 돌아 원인이 샤딩임을 지목한다.
_m3_dup = m3_verdict([_rec("00000001", 2020, "2021-03-31")],
                     [_rec("00000001", 2020, "2021-03-31")],
                     ["00000001"], ["00000002"])
ok("복제 — 같은 레코드 키가 두 샤드에 있으면 M3 위반",
   _m3_dup.get("aborted") is True
   and _m3_dup.get("recordKeysInMultipleShards") == 1,
   str(_m3_dup.get("abortReason"))[:150])
ok("복제는 '복제'라고 이름을 말한다 — 원인이 샤딩임을 지목한다",
   "복제다" in _m3_dup.get("abortReason", ""), _m3_dup.get("abortReason", "")[:150])

# 첫 실행에서 담당분이 처음 채워지는 것은 범위 변경이 아니다 —
# corpsAssigned 기본값을 0으로 두면 여기가 '0 → 476'으로 오탐된다(교훈57).
ok("담당분을 몰랐다가 알게 되는 것은 위반이 아니다",
   not m.state_transition_violations(
       {"done": set(), "hard": set(), "assigned": None},
       {"corpsDone": [], "hardSkipped": {}, "corpsAssigned": 476}, []))
ok("새 상태의 corpsAssigned 기본값이 None이다 (0이 아니다)",
   m.load_state(99, 1, POL)["corpsAssigned"] is None)

print("\n[시크릿 — 진단에 API 키가 남지 않는다]")
# collect #2 샤드 6의 ConnectTimeout 메시지에 crtfc_key 앞 26자가 그대로 들어갔다.
# requests의 예외는 요청 URL을 통째로 담고 그 URL에 키가 있다. "params로만 넘긴다"는
# 규율은 예외 경로를 막지 못한다 — 문자열로 나가는 지점에서 지워야 한다.
# 저장소는 공개이고 아티팩트도 내려받을 수 있다(절대 규칙 2).
_KEY = "ab9ac09b48dd77a90b77439c9e0123456789abcd"
_url = (f"HTTPSConnectionPool(host='opendart.fss.or.kr', port=443): Max retries "
        f"exceeded with url: /api/fnlttSinglAcnt.json?crtfc_key={_KEY}&corp_code=00126380")
ok("예외 메시지의 키가 지워진다", _KEY not in m.redact(_url), m.redact(_url)[:120])
ok("지운 자리에 표시가 남는다 (조용히 사라지지 않는다)",
   "crtfc_key=<redacted>" in m.redact(_url), m.redact(_url)[:120])
ok("자르기 전에 지운다 — 잘린 조각도 남지 않는다",
   _KEY[:20] not in f"{m.redact(_url)[:150]}", m.redact(_url)[:150])
ok("키가 없는 메시지는 그대로 둔다",
   m.redact("HTTP 503 Service Unavailable") == "HTTP 503 Service Unavailable")


class _Boom(Exception):
    pass


def _raise_with_key(*a, **k):
    raise _Boom(_url)


_saved = m.requests
m.requests = type("R", (), {"get": staticmethod(_raise_with_key)})()
_c = {"calls": 0, "dartStatus": __import__("collections").Counter()}
_rows, _st, _err, _cause = m.dart_call("fnlttSinglAcnt.json", {"corp_code": "00126380"},
                                       {**POL, "retryAttempts": 1}, _c)
m.requests = _saved
ok("dart_call이 돌려주는 오류에도 키가 없다 (진단에 저장되는 값이다)",
   _KEY not in (_err or ""), (_err or "")[:120])
ok("원인 계층에도 키가 없다 (예외명만 쓴다)", _KEY not in (_cause or ""), _cause or "")


print("\n[오류 원인 분해 — hardErrors 하나로는 원인을 지목하지 못한다]")
# 교훈41의 재발 방지. 진단에 남는 것이 개수뿐이면 collect가 막혔을 때 남는 정보는
# "수집 경로가 막혔다" 한 줄이고, 그것은 전송 장애인지 DART 업무 오류인지 게이트웨이
# 오류인지 가르지 않는다. 세 실패는 대응이 전부 다르다 — 기다린다 / 승인한다 / 키를 본다.
Counter_ = __import__("collections").Counter


class _FakeResp:
    def __init__(self, code, payload=None, raw=None):
        self.status_code, self._p, self._raw = code, payload, raw
        self.content = b"x"

    def json(self):
        if self._raw is not None:
            raise ValueError("Expecting value: line 1 column 1 (char 0)")
        return self._p


def _cause_of(responder, attempts=1, pol=None):
    """dart_call을 한 번 돌리고 (cause, 시도별 분해)를 돌려준다."""
    saved = m.requests
    m.requests = type("R", (), {"get": staticmethod(responder)})()
    c = {"calls": 0, "dartStatus": Counter_()}
    real_sleep, m.time.sleep = m.time.sleep, lambda *a: None
    try:
        _, _, _, cause = REAL_DART_CALL("fnlttSinglAcnt.json", {},
                                        {**(pol or POL), "retryAttempts": attempts}, c)
    finally:
        m.requests, m.time.sleep = saved, real_sleep
    return cause, c.get("callFailuresByCause", Counter_())


class _Timeout(Exception):
    pass


def _boom(*a, **k):
    raise _Timeout("timed out")


ok("전송 실패는 transport:<예외명>", _cause_of(_boom)[0] == "transport:_Timeout",
   _cause_of(_boom)[0])
ok("비-2xx는 http:<코드> (DART status가 없으므로 dartStatus 표에 안 잡힌다)",
   _cause_of(lambda *a, **k: _FakeResp(503))[0] == "http:503",
   _cause_of(lambda *a, **k: _FakeResp(503))[0])
ok("2xx인데 JSON이 아니면 parse:<예외명>",
   _cause_of(lambda *a, **k: _FakeResp(200, raw=b"<html>"))[0] == "parse:ValueError",
   _cause_of(lambda *a, **k: _FakeResp(200, raw=b"<html>"))[0])
ok("DART 업무 오류는 dart:<status>",
   _cause_of(lambda *a, **k: _FakeResp(200, {"status": "800", "message": "점검"}))[0]
   == "dart:800")

# 실패가 아닌 것은 원인 분해에 들어가지 않는다. 013을 실패로 세면 폐지 법인 구간에서
# 원인 표가 정상 사실로 가득 차 진짜 장애가 묻힌다.
_c013, _b013 = _cause_of(lambda *a, **k: _FakeResp(200, {"status": "013"}))
ok("013(데이터 없음)은 원인이 아니다", _c013 is None and not _b013, f"{_c013} {dict(_b013)}")
_cq, _bq = _cause_of(lambda *a, **k: _FakeResp(
    200, {"status": POL["quota"]["quotaExceededStatus"]}))
ok("한도 초과도 원인이 아니다 (실패가 아니라 대기다)", _cq is None and not _bq,
   f"{_cq} {dict(_bq)}")
ok("성공은 원인이 아니다",
   _cause_of(lambda *a, **k: _FakeResp(200, {"status": "000", "list": [1]}))[0] is None)

# 마지막 시도의 원인을 쓴다 — lastStatus와 같은 규칙이다. 1차 dart:100 → 2차 HTTP 503
# 이면 그 법인-연도를 실제로 포기시킨 것은 503이고, 승인 판단도 그것을 봐야 한다.
_seq = [_FakeResp(200, {"status": "100", "message": "부적절"}), _FakeResp(503)]
_cause_mixed, _by_attempt = _cause_of(lambda *a, **k: _seq.pop(0), attempts=2)
ok("여러 시도가 섞이면 마지막 시도의 원인을 쓴다", _cause_mixed == "http:503", _cause_mixed)
ok("시도 단위 분해는 둘 다 센다 (재시도가 흡수한 실패도 남는다)",
   dict(_by_attempt) == {"dart:100": 1, "http:503": 1}, str(dict(_by_attempt)))

# 분모가 다르다는 것이 이 두 표를 나눈 이유다. 한 표로 합치면 재시도 횟수가
# 실패율로 둔갑한다.
_retried, _by2 = _cause_of(_boom, attempts=3)
ok("한 번의 하드 실패가 시도 분해에서는 retryAttempts만큼 센다",
   sum(_by2.values()) == 3, str(dict(_by2)))

# hardErrorsByCause는 검사가 아니라 분해다 — 남김없이 갈라져야 값이 있다.
# 누군가 hardErrors를 다른 자리에서도 올리면 여기서 깨진다.
_pol3 = {**POL, "fiscalYearFrom": 2020, "fiscalYearTo": 2022, "retryAttempts": 1,
         "requestSleepSeconds": 0}
_causes = ["transport:X", "http:503", "http:503"]
_saved_dc, _saved_sleep = m.dart_call, m.time.sleep
m.time.sleep = lambda *a: None
m.dart_call = lambda *a, **k: ([], None, "boom", _causes.pop(0))
_sc = {"calls": 0, "dartStatus": Counter_(), "hardErrors": 0, "earlyStopped": 0,
       "sicFetchFailed": 0, "callFailuresByCause": Counter_(),
       "hardErrorsByCause": Counter_(), "reportsFound": 0,
       "recordRejected": Counter_()}
_out, _fail, _quota = REAL_SCAN_CORP("00000001", "000001", _pol3, _sc, {})
m.dart_call, m.time.sleep = _saved_dc, _saved_sleep
ok("hardErrors를 남김없이 분해한다 (sum == hardErrors)",
   sum(_sc["hardErrorsByCause"].values()) == _sc["hardErrors"] == 3,
   f"{dict(_sc['hardErrorsByCause'])} vs {_sc['hardErrors']}")
ok("같은 원인은 합산되고 다른 원인은 갈린다",
   dict(_sc["hardErrorsByCause"]) == {"transport:X": 1, "http:503": 2},
   str(dict(_sc["hardErrorsByCause"])))
ok("하드스킵 기록이 마지막 원인을 든다 (lastStatus가 None인 실패를 가르는 유일한 값)",
   _fail["lastCause"] == "http:503" and _fail["lastStatus"] is None, str(_fail))

print("\n[아티팩트 범위 — 자기 샤드 파일만 올린다]")
# 이번 사고의 근본 원인은 '병합이 잘못됐다'가 아니라 **애초에 병합 대상이 자기 것이
# 아니었다**는 것이다. _shards/가 저장소에 커밋된 뒤로 각 샤드의 checkout에는 남의
# 전날 상태가 들어 있었고, 디렉터리째 올리니 merge-multiple이 그것으로 남의 오늘치를
# 덮을 수 있었다. collect #1이 무사했던 건 그때 _shards/가 비어 있었기 때문이다.
#
# 그래서 계약을 '병합이 올바르게 된다'가 아니라 '병합 대상이 자기 샤드 파일뿐이다'로
# 고정한다. 누군가 path를 디렉터리로 되돌리면 여기서 즉시 깨진다.
# YAML 파서에 의존하지 않는다 — 이 테스트는 A3 finalize 잡에서 도는데 그 잡은
# requests만 설치한다.
WF = os.path.join(ROOT, ".github/workflows/fundamentals-a3.yml")
_lines = open(WF, encoding="utf-8").read().splitlines()
_start = next((i for i, l in enumerate(_lines)
               if "name: a3-shard-" in l and "matrix.shard" in l), None)
ok("collect의 업로드 스텝을 찾을 수 있다", _start is not None)

_paths = []
if _start is not None:
    for i in range(_start, min(_start + 12, len(_lines))):
        s = _lines[i].strip()
        if s.startswith("path:"):
            rest = s[len("path:"):].strip()
            if rest and rest != "|":
                _paths.append(rest)
            else:                       # 블록 스칼라 — 들여쓴 줄을 모은다
                indent = len(_lines[i]) - len(_lines[i].lstrip())
                for j in range(i + 1, len(_lines)):
                    t = _lines[j]
                    if not t.strip():
                        continue
                    if len(t) - len(t.lstrip()) <= indent:
                        break
                    _paths.append(t.strip())
            break

ok("업로드 경로가 하나 이상 선언돼 있다", bool(_paths), str(_paths))
ok("모든 업로드 경로가 자기 샤드를 지목한다 (matrix.shard 참조)",
   bool(_paths) and all("matrix.shard" in p for p in _paths),
   str([p for p in _paths if "matrix.shard" not in p]))
ok("디렉터리째 올리지 않는다 (남의 상태 파일이 아티팩트에 섞이는 경로)",
   all(not p.rstrip("/").endswith("_shards") for p in _paths), str(_paths))
ok("자기 샤드의 상태·산출·진단 세 파일을 모두 올린다",
   all(any(k in p for p in _paths) for k in ("_state-", "shard-", "_diagnostics-shard-")),
   str(_paths))

print(f"\n{'='*54}")
print(f"통과 {passed} · 실패 {failed}")
sys.exit(0 if failed == 0 else 1)
