#!/usr/bin/env python3
"""A3d — 공시 기반 기업행위 라벨 (FN-1.8, A5-3 D4)

계약은 `docs/A5-3-peg-조정기준-결정브리프.md` §16~19, 정의는
`config/policies/fundamentals.v1.json`의 `a3d` 블록이 단일 산출점이다.
이 스크립트에 카테고리 정규식·엔드포인트·임계를 하드코딩하지 않는다 —
회귀(`test-fundamentals-a3d.py`)가 그것을 강제한다.

A3c의 복사에 가깝다(샤드/재개/finalize 패턴 재사용). 다른 곳은 넷이다.

  1. 격자 단위가 (corp) 하나다
     A3c는 (corp, fiscalYear, reprtCode)지만 여기는 corp당 list.json 1회
     (날짜범위 전체, §3.6 실측3)다 — 연도별로 안 쪼갠다.
  2. 2단계 수집이다
     1단계: list.json(B·I 타입)으로 report_nm을 분류한다. 2단계: 카테고리별
     상세(piicDecsn·crDecsn·fricDecsn)를 그 corp에 대해 각 최대 1회만 부른다
     (§19.3 — 상세 API가 날짜범위 전체의 매칭분을 한 번에 준다, crDecsn 실측 확인).
  3. splitLike 중 split·reverseOrConsolidation은 상세 API가 없다 — 이미
     수집된 A3c 산출물(로컬 파일, 새 호출 없음)에서 공시일을 감싸는
     istcTotqy 전이 비율로 배수를 낸다(§19.1, 000860 실측 ×2 검증됨).
     ★ 둘 다 report_nm이 "주권매매거래정지해제(액면분할/액면병합...)" 형태다
     (2026-08-20, goldenset 3,756건 실사례로 재확인 — 독립된 "주식분할결정"류
     타이틀이 아니었다). 원래 있던 haltLiftSplit 카테고리는 이 재확인으로
     split/reverseOrConsolidation에 흡수됐다(별도 report_nm 패턴이 아니었다).
  4. PIT 개념이 다르다
     A3c는 '그 시점에 안 값'이 핵심이지만 A3d는 '그 사건이 언제 났는가'가
     핵심이다 — availableFrom이 아니라 disclosureDate(rcept_dt)를 낸다. 이
     값을 어떻게 쓰는지는 resolver.js(corporateActionAdjustment.js)의 몫이고
     여기서는 사실만 낸다.

일 예산·샤드 배분은 A3의 `shard_budget()`을 가져다 쓴다(A3c와 동일, 같은
DART_API_KEY라 일 한도를 공유 — 같은 날 A3/A3b/A3c와 겹쳐 돌리지 않는다).

  --shard N --shards M   담당 법인 수집 → _shards_a3d/shard-N.jsonl (Actions가 커밋)
  --finalize             병합 → 인수 조건 → 카테고리 분할 → gzip
  --revalidate           커밋된 산출물만으로 인수 조건 재판정
  --plan                 네트워크 없이 격자만 계산해 출력한다

입력:
  config/policies/fundamentals.v1.json      a3d 블록
  data/backfill/universe/a1a/current.jsonl  · a1b/delisted.jsonl (대상 법인)
  data/backfill/fundamentals/a3c/*.jsonl.gz (splitLike 배수 소스, 새 호출 없음)
출력:
  data/backfill/fundamentals/a3d/{category}.jsonl.gz
  data/backfill/fundamentals/a3d/_diagnostics.json
"""
import argparse
import datetime
import glob
import gzip
import importlib.util
import json
import os
import re
import sys
import time
from collections import Counter, defaultdict

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
POLICY = "config/policies/fundamentals.v1.json"
A3C_DIR = "data/backfill/fundamentals/a3c"
BASE = "https://opendart.fss.or.kr/api"
KEY = os.environ.get("DART_API_KEY", "")

STAGE_VERSION = "A3d.0"
CORP_RE = re.compile(r"^[0-9]{8}$")
DATE8 = re.compile(r"^\d{8}$")

fails, warns = [], []


def _load_module(name, filename):
    spec = importlib.util.spec_from_file_location(
        name, os.path.join(ROOT, "scripts", filename))
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


A3C = _load_module("a3c", "build-fundamentals-a3c.py")
A3 = A3C.A3  # A3c가 이미 A3 모듈을 로드해 둔다 (requests 어댑터 가드는 한 번만)
target_corps = A3C.target_corps
shard_budget = A3.shard_budget
today_kst = A3.today_kst

import requests  # noqa: E402


def chk(cond, msg):
    print(("  OK  " if cond else "  FAIL") + "  " + msg)
    if not cond:
        fails.append(msg)


def warn(cond, msg):
    print(("  OK  " if cond else "  WARN") + "  " + msg)
    if not cond:
        warns.append(msg)


def load_json(path):
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def load_jsonl(path):
    if not os.path.exists(path):
        return []
    with open(path, encoding="utf-8") as f:
        return [json.loads(l) for l in f if l.strip()]


def _abort(reason, diag, path, extra=None):
    diag.update({"aborted": True, "abortReason": reason, **(extra or {})})
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        json.dump(diag, f, ensure_ascii=False, indent=2)
    print(f"\n중단: {reason}")
    sys.exit(2)


def num(raw):
    """"1,234"|"-"|None → float|None. crDecsn.cr_rt_ostk·fricDecsn.nstk_ascnt_ps_ostk
    둘 다 소수를 쓸 수 있어 int가 아니라 float다(예: cr_rt_ostk='87.50')."""
    s = str(raw if raw is not None else "").replace(",", "").strip()
    if not s or s == "-":
        return None
    try:
        return float(s)
    except ValueError:
        return None


# ── DART ───────────────────────────────────────────────────────
DART_NO_DATA = "013"


def dart_get(endpoint, params, pol=None):
    """A3c와 동일한 재시도 규약. (json, dartStatus, error)."""
    attempts = (pol or {}).get("retryAttempts", 1)
    base = (pol or {}).get("retryBackoffBase", 2)
    quota_status = ((pol or {}).get("quota") or {}).get("quotaExceededStatus", "020")
    last = (None, "unknown", "unknown")
    for i in range(attempts):
        try:
            r = requests.get(f"{BASE}/{endpoint}", params={"crtfc_key": KEY, **params}, timeout=30)
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
                    if st in (DART_NO_DATA, quota_status):
                        return None, st, str(j.get("message", ""))[:150]
                    last = (None, st, str(j.get("message", ""))[:150])
        if i < attempts - 1:
            time.sleep(base ** i)
    return last


def list_disclosures(corp, pblntf_ty, bgn_de, end_de, pol, counters):
    """list.json 전 페이지. I타입은 100건 캡에 자주 걸린다(§15 버그2 실측,
    2,578종목 중 1,754개가 다중 페이지 필요) — page_no를 total_page까지 돈다.
    B타입도 방어적으로 같은 루프를 쓴다(total_page=1이면 추가 콜 0)."""
    rows, page = [], 1
    while True:
        j, st, err = dart_get("list.json", {
            "corp_code": corp, "bgn_de": bgn_de, "end_de": end_de,
            "pblntf_ty": pblntf_ty, "page_no": str(page), "page_count": "100"}, pol)
        counters["calls"] += 1
        if st == "013":
            return rows  # 그 유형 공시가 없다 — 정상
        if st != "000":
            counters["listErrors"][f"{pblntf_ty}:{st}"] += 1
            return rows
        rows.extend(j.get("list") or [])
        total_page = j.get("total_page", 1)
        if page >= total_page:
            return rows
        page += 1
        time.sleep(pol["requestSleepSeconds"])


# 정정·보완 공시 접두어 — 같은 사건에 대한 관리행위(오탈자·첨부파일 정정 등)일
# 뿐이지 새 사건이 아니다. 2026-08-20 스모크 3차에서 000860 실사례로 발견 —
# "[기재정정]주식분할결정"이 원본과 별개의 split 레코드를 만들어 같은 사건
# 하나가 COMPOUND_EVENT로 잘못 유보될 뻔했다(rightsOffering·capitalReduction·
# bonusIssue는 이미 §19.3 재설계로 상세 API 직접 수집이라 이 문제가 없다 —
# 여기는 상세 API가 없는 split·reverseOrConsolidation·mergerSpinoff에만 남는다).
_CORRECTION_PREFIX = re.compile(r"^\[(기재정정|첨부정정|첨부추가|연장결정)\]")


def classify(report_nm, categories):
    """report_nm(공백 제거) → 매칭 카테고리 이름 목록. 정정·보완 공시는
    원본과 같은 사건이므로 빈 리스트를 낸다(위 _CORRECTION_PREFIX)."""
    nm = re.sub(r"\s", "", str(report_nm or ""))
    if _CORRECTION_PREFIX.match(nm):
        return []
    out = []
    for c in categories:
        if re.search(c["reportNmPattern"], nm):
            out.append(c["category"])
    return out


# ── 상세 조회 (카테고리당 corp당 최대 1회) ──────────────────────
def fetch_detail_by_rcept(endpoint, corp, bgn_de, end_de, pol, counters):
    """{rcept_no: row} — corp_code+날짜범위로 그 구간의 매칭분을 전부 받는다
    (crDecsn 실측으로 확인된 동작, §19.3). 013(해당 없음)은 정상."""
    j, st, err = dart_get(endpoint, {
        "corp_code": corp, "bgn_de": bgn_de, "end_de": end_de}, pol)
    counters["calls"] += 1
    if st != "000":
        return {}
    return {str(r.get("rcept_no") or ""): r for r in (j.get("list") or [])}


def sub_classify_rights(ic_mthn, cls_pol):
    nm = str(ic_mthn or "")
    if re.search(cls_pol["rightsOffering"]["icMthnShareholdersPattern"], nm):
        return "rightsOfferingShareholders"
    if re.search(cls_pol["rightsOffering"]["icMthnThirdPartyPattern"], nm):
        return "rightsOfferingThirdParty"
    return None  # 알려지지 않은 ic_mthn — DART_MATCH_FAIL류로 유보(resolver.js 몫)


def sub_classify_capital_reduction(cr_mth, cls_pol):
    nm = str(cr_mth or "")
    if re.search(cls_pol["capitalReduction"]["crMthFreePattern"], nm):
        return "capitalReductionFree"
    if re.search(cls_pol["capitalReduction"]["crMthPaidPattern"], nm):
        return "capitalReductionPaid"
    return cls_pol["capitalReduction"]["unmatchedCategory"]  # capitalReductionUnknown


# ── A3c 브래킷 (새 호출 없음 — 로컬 산출물 읽기) ───────────────────
# A3c pointInTime.tieBreakOnSameAvailableFrom(사업보고서>반기>3분기>1분기)과
# 정확히 같은 우선순위 — lib/a5/pitSelector.js의 규칙(fiscalYear 최댓값 먼저,
# 그다음 이 우선순위)을 파이썬 쪽에서 재현한다(§19.5 1번이 남겼던 문제,
# 2026-08-20 스모크 테스트 3차 실행에서 실제로 잡음 — 009810 사례 아래 참조).
_REPRT_PRIORITY = {"11011": 4, "11012": 3, "11014": 2, "11013": 1}


def load_a3c_timeline():
    """{ticker: [(availableFrom, fiscalYear, reprtCode, istcTotqy), ...]} —
    오름차순. istcTotqy가 있는 레코드만. 정수배 사건(§19.1)의 배수를 여기서
    브래킷으로 계산한다."""
    out = defaultdict(list)
    for p in sorted(glob.glob(f"{A3C_DIR}/*.jsonl.gz")):
        with gzip.open(p, "rt", encoding="utf-8") as f:
            for line in f:
                if not line.strip():
                    continue
                r = json.loads(line)
                if r.get("ticker") and isinstance(r.get("istcTotqy"), (int, float)):
                    out[r["ticker"]].append(
                        (r["availableFrom"], r["fiscalYear"], r["reprtCode"], r["istcTotqy"]))
    for t in out:
        out[t].sort(key=lambda x: x[0])
    return out


def _pit_select_asof(rows, asof_date):
    """lib/a5/pitSelector.js의 selectAsOf()와 같은 규칙 — availableFrom이
    asof_date 이하인 것 중 fiscalYear 최댓값, 그다음 availableFrom 최댓값
    (실제 접수일 기준 최신). reprtCode 우선순위는 **같은 availableFrom**에
    여러 회계연도/보고서가 한꺼번에(catch-up) 몰아서 접수됐을 때만 마지막
    tie-break로 쓴다 — A3c 자신의 PIT 규칙(lib/a5/pitSelector.js 규칙 2·3)을
    그대로 가져와야 한다.

    ★ 2026-08-21 수정 — 원래는 정렬키가 (fiscalYear, priority, availableFrom)
    순이라 같은 회계연도 안에서 priority가 availableFrom(실제 접수 시점)보다
    먼저 비교됐다. 069640 실사례(2025 3분기 보고서가 2025 반기보고서보다
    3개월 늦게 접수됐는데도, priority표에서 반기(11012=3)가 3분기(11014=2)
    보다 높아 더 오래된 반기 값이 "PIT 최신"으로 잘못 선택됨)로 발견 —
    reverseOrConsolidation A3d 후보 69건 중 56건(81%)이 배수>1(논리적으로
    모순, 병합은 배수<1이어야 함)이던 원인이었다. 009810 catch-up 회귀
    (아래 테스트)는 그대로 통과한다 — 그 사례는 애초에 availableFrom이
    완전히 같은 날이라 이 정렬키 순서 변경의 영향을 안 받는다."""
    candidates = [r for r in rows if r[0] <= asof_date]
    if not candidates:
        return None
    return max(candidates, key=lambda r: (r[1], r[0], _REPRT_PRIORITY.get(r[2], 0)))


def a3c_bracket_ratio(ticker, disclosure_date, timeline):
    """disclosure_date 시점의 PIT 선택값(before)과, 그 뒤로 **PIT 선택값이
    실제로 달라지는 첫 시점**(after)의 비율.

    ★ '직후 첫 레코드'가 아니라 '값이 달라진 첫 레코드'다(2026-08-20, 회귀
    작성 중 000860 실사례로 발견) — 91일 지연(브리프 §5.1)이 여기서도 그대로
    나타난다. 000860의 1분기보고서(접수 2025-05-15)는 분할(공시 2025-03-26)
    보다 나중에 접수됐는데도 여전히 분할 전 값을 낸다.

    ★ raw 시간순이 아니라 PIT 선택(_pit_select_asof)을 쓴다(2026-08-20,
    스모크 3차에서 009810 실사례로 발견) — 2020-10-23에 세 회계연도(2019
    사업보고서·2020 반기·2020 3분기)가 한꺼번에 접수됐는데, 단순 시간순
    정렬은 그중 임의의 하나를 "그 날짜의 값"으로 잘못 골라 배수가
    0.81038처럼 지저분하게 나왔다 — PIT 규칙(최댓값 회계연도 우선)을 쓰면
    올바른 값으로 좁혀진다.

    before가 아예 없으면(그 corp의 첫 레코드보다도 이른 공시) None. after를
    못 찾으면(그 뒤로 영영 안 바뀜 — 아직 반영 전이거나 데이터 끝) None.
    지어내지 않는다(교훈57)."""
    rows = timeline.get(ticker) or []
    before_row = _pit_select_asof(rows, disclosure_date)
    if before_row is None:
        return None
    before = before_row[3]

    future_dates = sorted({af for af, *_ in rows if af > disclosure_date})
    after = None
    for af in future_dates:
        val = _pit_select_asof(rows, af)[3]
        if val != before:
            after = val
            break
    if after is None or before == 0:
        return None
    return after / before


def _clean_ratio_distance(ratio):
    """ratio가 정수 또는 그 역수(1/N)에서 얼마나 떨어져 있는지(비율). 정수배
    분할·병합은 이 값이 0에 가까워야 한다(000860 실측 0.0)."""
    if ratio is None or ratio <= 0:
        return None
    candidates = [round(ratio)] + ([1 / round(1 / ratio)] if ratio < 1 else [])
    best = min(abs(ratio - c) / c for c in candidates if c > 0)
    return best


# ── 격자 (네트워크 없음) ───────────────────────────────────────
def build_grid(pol):
    a3d = pol["a3d"]
    if a3d["grid"]["mode"] != "corpOnly":
        raise ValueError(f"a3d.grid.mode '{a3d['grid']['mode']}' — 허용값은 corpOnly뿐이다")
    corps = target_corps()
    return sorted(corps), corps


# ── 수집 ───────────────────────────────────────────────────────
def _base_record(corp, ticker, rcept_no, disclosure_date, report_nm):
    return {"corp": corp, "ticker": ticker, "rceptNo": rcept_no,
            "disclosureDate": disclosure_date, "reportNm": report_nm,
            "multiplier": None, "multiplierSource": None,
            "rawIcMthn": None, "rawCrMth": None}


def _dedup_same_event(recs, a3d, counters):
    """같은 corp·category·배수(반올림 4자리)가 sameEventDedupWindowDays 안에
    여럿이면 가장 늦은 것만 남긴다 — "결정" 공시와 "거래정지해제/변경상장"
    공시가 같은 사건을 두 번 내는 패턴(011040 실사례, §19 정책 주석 참조).
    '[기재정정]'류와 다른 중복이라 classify()의 정정 접두어 필터로는 안
    잡힌다. 창을 넘는 간격은 합치지 않는다 — 실제로 다른 사건일 수 있다."""
    window = a3d["multiplierSource"]["sameEventDedupWindowDays"]
    by_key = defaultdict(list)
    for r in recs:
        by_key[(r["category"], round(r["multiplier"], 4))].append(r)

    kept = []
    for group in by_key.values():
        group.sort(key=lambda r: r["disclosureDate"])
        cluster = [group[0]]
        for r in group[1:]:
            if _epoch_days(r["disclosureDate"]) - _epoch_days(cluster[-1]["disclosureDate"]) <= window:
                cluster.append(r)
            else:
                kept.append(cluster[-1])
                counters["dedupSameEvent"] += len(cluster) - 1
                cluster = [r]
        kept.append(cluster[-1])
        counters["dedupSameEvent"] += len(cluster) - 1
    return kept


def _epoch_days(yyyymmdd):
    return (datetime.date(int(yyyymmdd[:4]), int(yyyymmdd[4:6]), int(yyyymmdd[6:8]))
            - datetime.date(1970, 1, 1)).days


def scan_corp(corp, ticker, pol, timeline, counters):
    """
    ★ 2026-08-20 스모크 테스트(gh run 32362600405)로 구조 자체를 다시 짰다.

    원래는 list.json(B타입)에서 report_nm으로 후보를 고른 뒤 rcept_no로
    상세(piicDecsn 등)를 대조했다. 실사례로 보니 이게 근본적으로 틀렸다 —
    "[기재정정]"류 정정공시가 원본과 별개의 list.json row를 만드는데(예:
    00100258 하나에 '유상증자결정' 매칭 40건), 상세 API는 실제 결정
    "건"당 하나만 낸다(같은 corp에서 14건뿐). 정정공시 대부분이 상세를
    못 찾아 RIGHTS_ICMTHN_UNMATCHED로 떨어졌다(160건 vs 정상 수용 158건 —
    거절이 수용보다 많았다).

    고친 구조: rightsOffering·capitalReduction·bonusIssue는 **상세 API
    자체를 그 corp의 사건 목록으로 직접 쓴다** — list.json으로 먼저 걸러
    대조하지 않는다. crDecsn 실측(§16.3)으로 이미 확인된 사실 그대로다 —
    상세 API가 corp_code+날짜범위로 그 구간의 실제 결정을 전부 준다.
    rcept_no 앞 8자리가 접수일이다(A3c의 availableFrom 규칙과 동일 근거).
    list.json(B타입)은 이제 상세 API가 없는 mergerSpinoff에만 쓴다.
    """
    a3d = pol["a3d"]
    scan_from = a3d["scanFrom"].replace("-", "")
    scan_to = today_kst().replace("-", "")
    categories = a3d["categories"]
    cls_pol = a3d["classification"]
    endpoints = a3d["source"]["detailEndpoints"]

    records = []

    # split·reverseOrConsolidation — I타입 list.json, 상세 API 없음(§19.1).
    i_rows = list_disclosures(corp, "I", scan_from, scan_to, pol, counters)
    split_candidates = []
    for r in i_rows:
        for base_cat in classify(r.get("report_nm"), categories):
            if base_cat not in ("split", "reverseOrConsolidation"):
                continue
            rcept_no = str(r.get("rcept_no") or "")
            disclosure_date = str(r.get("rcept_dt") or "")
            if not rcept_no or not DATE8.match(disclosure_date):
                counters["rejected"]["RCEPT_OR_DATE_INVALID"] += 1
                continue
            ratio = a3c_bracket_ratio(ticker, disclosure_date, timeline)
            if ratio is None:
                counters["rejected"][f"{base_cat}:BRACKET_MISSING"] += 1
                continue
            dist = _clean_ratio_distance(ratio)
            counters["bracketDistances"].append(dist)
            if dist is not None and dist > a3d["acceptance"]["a3cBracketOutOfToleranceWarn"]:
                counters["bracketOutOfTolerance"] += 1
            rec = _base_record(corp, ticker, rcept_no, disclosure_date, str(r.get("report_nm") or ""))
            rec["category"] = base_cat
            rec["multiplier"] = round(ratio, 6)
            rec["multiplierSource"] = "a3cBracket"
            split_candidates.append(rec)
    records.extend(_dedup_same_event(split_candidates, a3d, counters))

    # mergerSpinoff — B타입 list.json, 상세 API 없음(§16.3, D4 범위 밖·분류만).
    b_rows = list_disclosures(corp, "B", scan_from, scan_to, pol, counters)
    for r in b_rows:
        if "mergerSpinoff" not in classify(r.get("report_nm"), categories):
            continue
        rcept_no = str(r.get("rcept_no") or "")
        disclosure_date = str(r.get("rcept_dt") or "")
        if not rcept_no or not DATE8.match(disclosure_date):
            counters["rejected"]["RCEPT_OR_DATE_INVALID"] += 1
            continue
        rec = _base_record(corp, ticker, rcept_no, disclosure_date, str(r.get("report_nm") or ""))
        rec["category"] = "mergerSpinoff"
        records.append(rec)

    # rightsOffering — piicDecsn 자체가 사건 목록이다(무조건 호출).
    for row in fetch_detail_by_rcept(
            endpoints["rightsOffering"]["endpoint"], corp, scan_from, scan_to, pol, counters
    ).values():
        rcept_no = str(row.get("rcept_no") or "")
        if not rcept_no or not DATE8.match(rcept_no[:8]):
            counters["rejected"]["RCEPT_OR_DATE_INVALID"] += 1
            continue
        ic_mthn = row.get("ic_mthn")
        sub = sub_classify_rights(ic_mthn, cls_pol)
        if sub is None:
            counters["rejected"]["RIGHTS_ICMTHN_UNMATCHED"] += 1
            continue
        rec = _base_record(corp, ticker, rcept_no, rcept_no[:8], "")
        rec["category"] = sub
        rec["rawIcMthn"] = ic_mthn
        records.append(rec)

    # capitalReduction — crDecsn 자체가 사건 목록이다(무조건 호출).
    for row in fetch_detail_by_rcept(
            endpoints["capitalReduction"]["endpoint"], corp, scan_from, scan_to, pol, counters
    ).values():
        rcept_no = str(row.get("rcept_no") or "")
        if not rcept_no or not DATE8.match(rcept_no[:8]):
            counters["rejected"]["RCEPT_OR_DATE_INVALID"] += 1
            continue
        cr_mth = row.get("cr_mth")
        cr_rt = num(row.get("cr_rt_ostk"))
        sub = sub_classify_capital_reduction(cr_mth, cls_pol)
        rec = _base_record(corp, ticker, rcept_no, rcept_no[:8], "")
        rec["category"] = sub
        rec["rawCrMth"] = cr_mth
        if sub == "capitalReductionFree":
            if cr_rt is None:
                counters["rejected"]["CR_RATIO_MISSING"] += 1
                continue
            rec["multiplier"] = round(1 - cr_rt / 100, 6)
            rec["multiplierSource"] = "crDecsn"
        records.append(rec)

    # bonusIssue — fricDecsn 자체가 사건 목록이다(무조건 호출).
    for row in fetch_detail_by_rcept(
            endpoints["bonusIssue"]["endpoint"], corp, scan_from, scan_to, pol, counters
    ).values():
        rcept_no = str(row.get("rcept_no") or "")
        if not rcept_no or not DATE8.match(rcept_no[:8]):
            counters["rejected"]["RCEPT_OR_DATE_INVALID"] += 1
            continue
        ratio = num(row.get("nstk_ascnt_ps_ostk"))
        if ratio is None:
            counters["rejected"]["BONUS_RATIO_MISSING"] += 1
            continue
        rec = _base_record(corp, ticker, rcept_no, rcept_no[:8], "")
        rec["category"] = "bonusIssue"
        rec["multiplier"] = round(1 + ratio, 6)
        rec["multiplierSource"] = "fricDecsn"
        records.append(rec)

    return records


def rec_key(r):
    return (r["corp"], r["disclosureDate"], r["rceptNo"], r["category"])


def run_shard(shard, shards, pol, limit):
    a3d = pol["a3d"]
    out = a3d["output"]
    sdir = out["stateDir"]
    os.makedirs(sdir, exist_ok=True)
    spath = f"{sdir}/_state-{shard}.json"
    dpath = f"{sdir}/_diagnostics-shard-{shard}.json"
    today = today_kst()

    diag = {"stage": "A3d", "mode": "shard", "shard": shard, "shards": shards,
            "stageVersion": STAGE_VERSION, "fundamentalsPolicy": pol["version"],
            "runDate": today}

    if not KEY:
        _abort("DART_API_KEY 없음", diag, dpath)

    grid_corps, corps = build_grid(pol)
    diag["targetCorps"] = len(grid_corps)
    mine = grid_corps[shard::shards]
    if limit:
        mine = mine[:limit]
        diag["smokeTest"] = True

    state = load_json(spath) if os.path.exists(spath) else {
        "shard": shard, "corpsDone": [], "callsUsedToday": 0,
        "lastRunDate": None, "corpsAssigned": 0}
    if state.get("lastRunDate") != today:
        state["callsUsedToday"] = 0
        state["lastRunDate"] = today
    state["corpsAssigned"] = len(mine)

    budget, bdetail = shard_budget(pol, shards, shard, state["callsUsedToday"],
                                    today, state_dir=sdir)
    diag["shardBudget"] = bdetail

    print("A3c 브래킷 타임라인 로드 중...")
    timeline = load_a3c_timeline()
    print(f"  {len(timeline)}종목 · 로컬 산출물, 새 호출 없음")

    done = set(state["corpsDone"])
    todo = [c for c in mine if c not in done]
    print(f"A3d 샤드 {shard}/{shards} — 담당 {len(mine)}법인 · 완료 {len(mine)-len(todo)} "
          f"· 남음 {len(todo)} · 오늘 예산 {budget - state['callsUsedToday']}/{budget}")

    records = {}
    rpath = f"{sdir}/shard-{shard}.jsonl"
    if os.path.exists(rpath):
        for r in load_jsonl(rpath):
            if r["corp"] in done:
                records[rec_key(r)] = r

    counters = {"calls": 0, "listErrors": Counter(), "rejected": Counter(),
                "bracketDistances": [], "bracketOutOfTolerance": 0, "dedupSameEvent": 0}
    budget_hit = False
    t0 = time.time()
    for i, corp in enumerate(todo, 1):
        if state["callsUsedToday"] >= budget:
            budget_hit = True
            break
        before_calls = counters["calls"]
        recs = scan_corp(corp, corps[corp]["ticker"], pol, timeline, counters)
        state["callsUsedToday"] += counters["calls"] - before_calls
        for r in recs:
            records[rec_key(r)] = r
        done.add(corp)
        if i % 200 == 0:
            print(f"  {i}/{len(todo)} · {len(records)}행 · 호출 {state['callsUsedToday']} "
                  f"· {time.time()-t0:.0f}s")

    state["corpsDone"] = sorted(done)
    diag.update(corpsAssigned=len(mine), corpsDone=len(done),
                corpsRemaining=len(mine) - len(done),
                calls=state["callsUsedToday"], budget=budget,
                budgetExhausted=budget_hit, rowCount=len(records),
                listErrors=dict(counters["listErrors"]),
                rejected=dict(counters["rejected"]),
                bracketOutOfTolerance=counters["bracketOutOfTolerance"],
                bracketSamples=len(counters["bracketDistances"]),
                dedupSameEvent=counters["dedupSameEvent"],
                elapsedSeconds=round(time.time() - t0, 1))

    with open(rpath, "w", encoding="utf-8", newline="\n") as f:
        for k in sorted(records):
            f.write(json.dumps(records[k], ensure_ascii=False) + "\n")
    with open(spath, "w", encoding="utf-8", newline="\n") as f:
        json.dump(state, f, ensure_ascii=False, indent=2)
    with open(dpath, "w", encoding="utf-8", newline="\n") as f:
        json.dump(diag, f, ensure_ascii=False, indent=2)

    print(f"\n{rpath} — {len(records)}행 · 호출 {state['callsUsedToday']} · "
          f"""{'예산 소진 (다음 실행이 이어받는다)' if budget_hit else '담당분 완료'}""")
    return 0


# ── 인수 조건 ──────────────────────────────────────────────────
def validate(rows, pol, diag, from_output_only=False):
    a = pol["a3d"]["acceptance"]
    print("\n[인수 조건]")

    inject = os.environ.get("A3D_FAIL_INJECTION", "").strip()
    if inject:
        diag["failInjection"] = inject
        chk(False, f"[FAIL INJECTION] {inject} — 게이트 검증용 강제 실패")

    bad_date = [r for r in rows if not DATE8.match(r.get("disclosureDate") or "")]
    chk(len(bad_date) == a["dateContractViolations"], f"날짜 계약 YYYYMMDD (위반 {len(bad_date)}건)")

    bad_corp = [r for r in rows if not CORP_RE.match(r.get("corp") or "")]
    chk(len(bad_corp) == a["corpContractViolations"], f"corp 계약 [0-9]{{8}} (위반 {len(bad_corp)}건)")

    dup = len(rows) - len({rec_key(r) for r in rows})
    chk(dup == a["duplicateKeys"], f"(corp, disclosureDate, rceptNo, category) 중복 {dup}건")

    # categories 표엔 이제 split·reverseOrConsolidation·mergerSpinoff만 있다(list.json
    # 매칭 대상). rightsOffering·capitalReduction·bonusIssue는 상세 API에서 직접
    # 나오는 최종 category라 표에 없다 — 여기서 명시적으로 더한다(2026-08-20 재작성).
    known_categories = {c["category"] for c in pol["a3d"]["categories"]}
    known_categories |= {"bonusIssue", "rightsOfferingThirdParty", "rightsOfferingShareholders",
                         "capitalReductionFree", "capitalReductionPaid", "capitalReductionUnknown"}
    unknown = [r for r in rows if r.get("category") not in known_categories]
    diag["categoryUnknownSample"] = [r["category"] for r in unknown[:20]]
    chk(len(unknown) == a["categoryUnknownCount"], f"알 수 없는 category {len(unknown)}건")

    dist = Counter(r["category"] for r in rows)
    diag["categoryDistribution"] = dict(dist)
    print(f"  --  카테고리 분포: {dict(dist)}")

    if from_output_only:
        diag["revalidatedFromOutputOnly"] = True
        print("  --  상태가 있어야 잴 수 있는 항목은 건너뛴다")
        return

    incomplete = diag.get("corpsIncomplete")
    chk(incomplete == a["corpsIncomplete"],
        f"미완료 법인 {incomplete}건 (담당 {diag.get('targetCorps')} · 완료 {diag.get('corpsDone')})")

    ratio = diag.get("bracketOutOfTolerance", 0) / diag["bracketSamples"] if diag.get("bracketSamples") else 0
    diag["bracketOutOfToleranceRate"] = round(ratio, 4)
    warn(ratio <= a["a3cBracketOutOfToleranceWarn"],
         f"A3c 브래킷 허용오차 초과율 {ratio*100:.2f}% <= {a['a3cBracketOutOfToleranceWarn']*100:.0f}%")


# ── finalize ───────────────────────────────────────────────────
def _merge_state(sdir, diag):
    done_all, calls = set(), 0
    rejected, list_errors = Counter(), Counter()
    bracket_oot, bracket_n = 0, 0
    for p in sorted(glob.glob(f"{sdir}/_state-*.json")):
        st = load_json(p)
        done_all |= set(st.get("corpsDone") or [])
        calls += st.get("callsUsedToday", 0)
    for p in sorted(glob.glob(f"{sdir}/_diagnostics-shard-*.json")):
        d = load_json(p)
        rejected.update(d.get("rejected") or {})
        list_errors.update(d.get("listErrors") or {})
        bracket_oot += d.get("bracketOutOfTolerance", 0)
        bracket_n += d.get("bracketSamples", 0)
    diag["corpsDone"] = len(done_all)
    diag["callsTotal"] = calls
    diag["rejected"] = dict(rejected)
    diag["listErrors"] = dict(list_errors)
    diag["bracketOutOfTolerance"] = bracket_oot
    diag["bracketSamples"] = bracket_n
    return done_all


def run_finalize(pol):
    a3d = pol["a3d"]
    out_dir, sdir = a3d["output"]["dir"], a3d["output"]["stateDir"]
    dpath = f"{out_dir}/_diagnostics.json"
    diag = {"stage": "A3d", "mode": "finalize", "stageVersion": STAGE_VERSION,
            "fundamentalsPolicy": pol["version"]}

    shard_files = sorted(glob.glob(f"{sdir}/shard-*.jsonl"))
    if not shard_files:
        _abort(f"{sdir}에 샤드 산출물이 없다 — 수집 잡을 먼저 돌려라", diag, dpath)

    rows = []
    for p in shard_files:
        rows.extend(load_jsonl(p))
    diag["shardCount"] = len(shard_files)
    diag["rowCount"] = len(rows)
    print(f"[1/3] 샤드 {len(shard_files)}개 병합 — {len(rows)}행")

    grid_corps, corps = build_grid(pol)
    diag["targetCorps"] = len(grid_corps)
    done_all = _merge_state(sdir, diag)
    diag["corpsIncomplete"] = len(grid_corps) - diag["corpsDone"]
    print(f"[2/3] 대상 {diag['targetCorps']}법인 · 완료 {diag['corpsDone']} · "
          f"호출 {diag['callsTotal']} · 미완료 {diag['corpsIncomplete']}")

    validate(rows, pol, diag)
    _write_diag(diag, dpath)
    if warns:
        print(f"\nWARN {len(warns)}건:")
        for w in warns:
            print(f"  - {w}")
    if fails:
        print(f"\n인수 조건 {len(fails)}건 실패 — 산출물을 쓰지 않는다")
        for x in fails:
            print(f"  - {x}")
        return 1

    print("\n[3/3] 카테고리 분할 · gzip")
    _write_categories(rows, a3d["output"], diag)
    _write_diag(diag, dpath)
    print(f"\n{out_dir} — {len(rows)}행")
    return 0


def run_revalidate(pol):
    a3d = pol["a3d"]
    out_dir = a3d["output"]["dir"]
    rows = []
    for p in sorted(glob.glob(f"{out_dir}/*.jsonl.gz")):
        with gzip.open(p, "rt", encoding="utf-8") as f:
            rows += [json.loads(l) for l in f if l.strip()]
    if not rows:
        print(f"{out_dir}에 산출물이 없다")
        return 1
    diag = {"stage": "A3d", "mode": "revalidate", "stageVersion": STAGE_VERSION,
            "fundamentalsPolicy": pol["version"], "rowCount": len(rows)}
    print(f"A3d 재판정 — {len(rows)}행 (산출물만)")
    validate(rows, pol, diag, from_output_only=True)
    _write_diag(diag, f"{out_dir}/_revalidate.json")
    print(f"\n{'통과' if not fails else '실패 ' + str(len(fails)) + '건'} · WARN {len(warns)}건")
    return 0 if not fails else 1


def _write_categories(rows, out, diag):
    os.makedirs(out["dir"], exist_ok=True)
    for old in glob.glob(f"{out['dir']}/*.jsonl.gz"):
        os.remove(old)
    key = out["sortKey"]
    rows.sort(key=lambda r: tuple(str(r[k]) for k in key))
    by_cat = defaultdict(list)
    for r in rows:
        by_cat[r["category"]].append(r)
    cats = {}
    for c in sorted(by_cat):
        payload = [{k: r.get(k) for k in out["fields"]} for r in by_cat[c]]
        raw = "".join(json.dumps(x, ensure_ascii=False) + "\n"
                      for x in payload).encode("utf-8")
        p = f"{out['dir']}/{c}.jsonl.gz"
        with gzip.GzipFile(p, "wb", compresslevel=out["gzipCompressLevel"],
                           mtime=out["gzipMtime"]) as f:
            f.write(raw)
        cats[c] = {"rows": len(payload), "gzBytes": os.path.getsize(p)}
        print(f"  {c}.jsonl.gz  {len(payload):>7}행")
    diag["categories"] = cats


def _write_diag(diag, path):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    diag["acceptanceFails"] = list(fails)
    diag["acceptanceWarns"] = list(warns)
    diag["acceptancePassed"] = not fails
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        json.dump(diag, f, ensure_ascii=False, indent=2)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--shard", type=int)
    ap.add_argument("--shards", type=int)
    ap.add_argument("--finalize", action="store_true")
    ap.add_argument("--revalidate", action="store_true")
    ap.add_argument("--plan", action="store_true")
    ap.add_argument("--limit", type=int, default=0,
                    help="스모크 테스트용. 진단에 smokeTest 플래그가 박힌다")
    args = ap.parse_args()

    if not os.path.exists(POLICY):
        print(f"{POLICY} 없음")
        return 1
    pol = load_json(POLICY)
    if "a3d" not in pol:
        print(f"{POLICY}({pol.get('version')})에 a3d 블록이 없다 — FN-1.8 이상이 필요하다")
        return 1

    if args.plan:
        grid_corps, corps = build_grid(pol)
        print(json.dumps({"targetCorps": len(grid_corps)}, ensure_ascii=False, indent=2))
        return 0
    if args.revalidate:
        return run_revalidate(pol)
    if args.finalize:
        return run_finalize(pol)
    if args.shard is None:
        print("--shard N --shards M · --finalize · --revalidate · --plan 중 하나가 필요하다")
        return 1
    shards = args.shards or pol["a3d"].get("shards") or pol["shards"]
    if not (0 <= args.shard < shards):
        print(f"--shard는 0 이상 {shards} 미만이어야 한다")
        return 1
    return run_shard(args.shard, shards, pol, args.limit)


if __name__ == "__main__":
    raise SystemExit(main())
