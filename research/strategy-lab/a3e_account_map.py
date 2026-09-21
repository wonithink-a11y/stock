"""A3e 확장 재무 패널의 계정 매핑 — 결과(수익률)를 보기 전에 동결한다 (2026-09-21).

패널 행은 [sj_div, account_id, account_nm, 당기금액] 원문이다(수집기는 산식을 굳히지 않는다).
여기서 '어느 행이 무엇인가'를 정한다. 이 파일을 바꾸면 그 뒤의 모든 결과가 다시 태어나므로,
바꾸려면 새 버전 파일을 만든다(정책 동결과 같은 원칙).

정의를 정한 근거는 docs/control/A3e-계정매핑감사-2026-09-21.md.
"""
import re

MAP_VERSION = "a3e-map-1.1"  # 1.0 → 1.1: 차입금 모호(대체·총액)·무차입 가정 플래그 추가 (감사 후, 수익률 확인 전)

_PREFIX = re.compile(r"^(ifrs-full_|ifrs_)")  # 2015~2018 은 ifrs_, 이후는 ifrs-full_


def norm_id(i):
    return _PREFIX.sub("I:", i or "")


IS_SJ = ("CIS", "IS")  # 포괄손익계산서 / 손익계산서 — 기업이 둘 중 하나로 낸다

# 단일 표준코드 개념: 개념 -> (허용 sj_div, 표준코드)
SINGLE = {
    "assets": (("BS",), "I:Assets"),
    "equity": (("BS",), "I:Equity"),
    "cash": (("BS",), "I:CashAndCashEquivalents"),          # 단기금융상품 미포함 — 순차입금이 과대
    "revenue": (IS_SJ, "I:Revenue"),
    "gross_profit": (IS_SJ, "I:GrossProfit"),
    "op_income": (IS_SJ, "dart_OperatingIncomeLoss"),
    "net_income": (IS_SJ, "I:ProfitLoss"),
    "cfo": (("CF",), "I:CashFlowsFromUsedInOperatingActivities"),
    "finance_cost": (IS_SJ, "I:FinanceCosts"),               # 이자비용이 아니라 금융원가(외환손실 등 포함)
    "capex_ppe": (("CF",), "I:PurchaseOfPropertyPlantAndEquipmentClassifiedAsInvestingActivities"),
    "capex_intang": (("CF",), "I:PurchaseOfIntangibleAssetsClassifiedAsInvestingActivities"),
    "depreciation": (("CF",), "dart_AdjustmentsForDepreciationExpense"),   # 커버리지 낮음 — 부분 표본용
    "amortisation": (("CF",), "dart_AdjustmentsForAmortisationExpense"),
}

# 차입금: BS 행을 '이름'으로 잡는다(표준코드가 dart_ 확장으로 파편화 — 아래 감사 참고).
# 리스부채는 넣지 않는다(2019 이후 IFRS16 으로 공시 방식이 달라 연도 간 비교가 깨진다).
_DEBT_NAME = re.compile(r"(차입금|사채|전환사채|교환사채|신주인수권부사채)")
_DEBT_EXCLUDE = re.compile(r"(할인|할증|조정|상환|상각|손실|이익|이자|평가|자본|배당|미지급|선급|리스)")


def debt_rows(rows):
    """BS 의 차입금성 행 (sj, id, nm, v) 목록. 소계·구성항목 중복은 감사에서 잰다."""
    out = []
    for sj, i, nm, v in rows:
        if sj != "BS" or v is None:
            continue
        if _DEBT_NAME.search(nm or "") and not _DEBT_EXCLUDE.search(nm or ""):
            out.append((sj, i, nm, v))
    return out


def extract(rec):
    """패널 레코드 하나 -> {개념: 값}, 없는 개념은 키 자체가 없다(0 으로 채우지 않는다 — 교훈57)."""
    idx = {}
    dup = set()
    for sj, i, nm, v in rec["rows"]:
        if v is None:
            continue
        k = (sj, norm_id(i))
        if k in idx:
            dup.add(k)
        else:
            idx[k] = v
    out = {}
    for name, (sjs, code) in SINGLE.items():
        for sj in sjs:
            if (sj, code) in idx:
                out[name] = idx[(sj, code)]
                if (sj, code) in dup:
                    out.setdefault("_dup", []).append(name)
                break
    d = debt_rows(rec["rows"])
    if d:
        out["debt"] = sum(v for *_, v in d)
        out["_debt_n"] = len(d)
        # '총액'(대체 전 합계)·'유동성 대체 부분'(공제) 행은 부호가 일정하지 않아(대체 행 697개 중 97개 음수)
        # 이중계상/과소계상을 규칙으로 못 가린다 — 추측하지 않고 모호로 표시, 주 분석에서 뺀다.
        if any(("대체" in nm) or ("총액" in nm) for _, _, nm, _v in d):
            out["debt_ambiguous"] = True
    elif "assets" in out:
        # 재무상태표가 있는데 차입 행이 하나도 없다: 무차입으로 보되 '가정'임을 남긴다(교훈57).
        # 주 분석은 0 으로 쓰고, 민감도로 '실제 잡힌 표본만' 결과를 함께 낸다.
        out["debt_zero_assumed"] = True
    if "debt" in out and not out.get("debt_ambiguous"):
        out["debt_eff"] = out["debt"]
    elif out.get("debt_zero_assumed"):
        out["debt_eff"] = 0.0
    return out
