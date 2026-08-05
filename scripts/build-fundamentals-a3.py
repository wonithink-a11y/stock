#!/usr/bin/env python3
"""A3 — 재무 (PIT) 백필 (BF-1.1)

A1a 2,579 + A1b 1,222 = 3,801개 법인의 연간 재무제표를 DART에서 받아 사업연도별로
나눠 저장한다. 정의는 config/policies/fundamentals.v1.json(FN-1.0)이 단일 산출점이다.

A3의 본질은 재무 수치가 아니라 시점이다. 운영 수집기(scripts/fetch-fundamentals-kr.js)는
'현재 값'을 쓰고, 여기는 '그 시점에 알 수 있었던 값'을 쓴다. 그 축이 availableFrom이고,
availableFrom > periodEnd가 성립하지 않으면 백테스트에 look-ahead가 들어간다.

소스는 fnlttSinglAcnt(주요계정)이고 **당기(thstrm) 열만** 쓴다. 같은 응답의 전기·전전기를
쓰면 그 값들의 availableFrom이 '그 보고서의 접수일'이 되어 과거 연도를 실제보다 늦게
안 것으로 기록한다(교훈47). 3개 연도를 한 번에 준다는 사실은 호출량을 줄일 유혹이지
시점을 바꿀 근거가 아니다 — 이 규칙이 무너지면 엔드포인트를 고른 이득이 그대로 사고가 된다.

두 모드로 돈다. A2a와 같은 이유(실행 축과 저장 축의 분리)에 더해, A3에는 이유가 하나 더
있다 — DART 일 한도 20,000건이라 수집이 여러 날에 걸친다.

  --shard N --shards M   법인 부분집합 수집 → _shards/shard-N.jsonl (+ resume 상태)
  --finalize             전 샤드 병합 → 정렬 → 사업연도 분할 → gzip → 인수 조건 → 산출

resume이 A2a와 다른 점: A2a의 샤드는 한 실행 안에서 artifact로 넘겼지만, A3는 실행이
날짜를 넘기므로 artifact로 이어받을 수 없다. 그래서 _shards/를 Actions가 커밋하고,
finalize가 성공하면 지운다.

입력:
  config/policies/fundamentals.v1.json
  data/backfill/universe/a1a/current.jsonl    대상 법인 (A1a)
  data/backfill/universe/a1b/delisted.jsonl   대상 법인 (A1b)
출력:
  data/backfill/fundamentals/a3/{YYYY}.jsonl.gz
  data/backfill/fundamentals/a3/_diagnostics.json
"""
import argparse
import glob
import gzip
import hashlib
import io
import json
import os
import re
import sys
import time
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone
from statistics import median

# requests는 수집 경로에서만 필요하다. 최상단에서 import하면 --summary·--finalize처럼
# 네트워크를 쓰지 않는 경로가 그 의존성 때문에 죽는다 — 실제로 죽었다(collect #2의
# persist 잡에는 Install deps 스텝이 없어 ModuleNotFoundError로 진행 커밋이 스킵됐다).
# 읽기 전용 경로가 HTTP 라이브러리를 요구하지 않는 것이 옳고, 그것이 이 지연 import의
# 이유다. 워크플로에 pip install을 한 줄 더 넣는 것은 같은 결합을 다른 자리에 남긴다.
requests = None

POLICY = "config/policies/fundamentals.v1.json"
A1A = "data/backfill/universe/a1a/current.jsonl"
A1B = "data/backfill/universe/a1b/delisted.jsonl"
OUT_DIR = "data/backfill/fundamentals/a3"
SHARD_DIR = "data/backfill/fundamentals/_shards"
# 운영 승인 목록. 정책이 아니라 예외이므로 config/policies가 아니다.
# registry.approvals.declaredGapsA3와 같은 파일을 가리켜야 한다 — 갈라지면
# manifest의 approvalHash가 수집기가 실제로 읽은 목록과 다른 것을 증명하게 된다.
DECLARED_GAPS = "config/backfill/declared-gaps-a3.json"
BASE = "https://opendart.fss.or.kr/api"
KEY = os.environ.get("DART_API_KEY", "")
KST = timezone(timedelta(hours=9))
STAGE_VERSION = "A3.0"

DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
DATE8_RE = re.compile(r"^\d{8}$")
CORP_RE = re.compile(r"^[0-9]{8}$")
TICKER_RE = re.compile(r"^[0-9A-Z]{6}$")
# thstrm_dt는 "2023.01.01 ~ 2023.12.31"과 "2023.12.31 현재" 두 형태로 온다.
# 회계기간말은 어느 쪽이든 마지막 날짜다.
DT_IN_TEXT = re.compile(r"(\d{4})[.\-/](\d{2})[.\-/](\d{2})")

# 013(조회된 데이터 없음)은 실패가 아니다 — 그 법인이 그 해에 보고서를 안 냈다는 정상 사실이다.
# 여기 넣으면 폐지 법인 구간에서 서킷 브레이커가 즉시 열린다.
DART_NO_DATA = "013"

fails, warns = [], []


def chk(cond, msg):
    print(("  OK  " if cond else "  FAIL") + "  " + msg)
    if not cond:
        fails.append(msg)


def warn(cond, msg):
    print(("  OK  " if cond else "  WARN") + "  " + msg)
    if not cond:
        warns.append(msg)


def _abort(reason, diag, path, extra=None):
    """실패해도 진단은 남긴다(교훈39). 중단 경로도 산출이다."""
    diag.update({"aborted": True, "abortReason": reason, **(extra or {})})
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        json.dump(diag, f, ensure_ascii=False, indent=2)
    print(f"\n중단: {reason}")
    sys.exit(2)


def load_json(path):
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def load_jsonl(path):
    with open(path, encoding="utf-8") as f:
        return [json.loads(l) for l in f if l.strip()]


def today_kst():
    return datetime.now(KST).strftime("%Y-%m-%d")


# ── 수집 계약 ──────────────────────────────────────────────────
def dig(obj, path):
    for part in path.split("."):
        obj = obj[part]
    return obj


def collection_contract_hash(pol):
    """이미 모은 레코드의 내용을 결정하는 필드들의 해시.

    resume 호환 판정의 단일 출처다. FN-1.2까지는 정책 version 문자열을 비교했는데,
    그것은 '재개해도 되는가'의 대리 지표로 너무 거칠었다 — 임계 하나를 고쳐 version이
    올라가면 8샤드의 상태가 전부 폐기되고 이미 쓴 DART 호출이 사라진다. 수집이 여러
    날에 걸치는 단계에서는 그 폐기가 조용한 하루 손실이다.

    경로 목록 자체도 해시에 넣는다. 목록을 바꾸는 것은 '무엇이 계약인가'를 바꾸는
    일이므로 그때는 이어받지 않는 쪽(재수집)으로 틀리는 편이 안전하다.
    """
    spec = pol["collectionContract"]["fields"]
    payload = {"fields": list(spec), "values": {p: dig(pol, p) for p in spec}}
    blob = json.dumps(payload, ensure_ascii=False, sort_keys=True,
                      separators=(",", ":")).encode("utf-8")
    return "sha256:" + hashlib.sha256(blob).hexdigest()[:16]


def run_identity():
    """Actions 실행 식별자. 로컬 실행에서는 전건 None이다.

    셋을 다 남기는 이유는 'Re-run failed jobs'가 run id를 유지하고 attempt만 올리기
    때문이다 — id만으로는 1회차 실패인지 2회차 실패인지 갈리지 않는다.
    상태에 None이 섞여 있으면 그것 자체가 '로컬 실행분이 커밋됐다'는 신호다
    (CLAUDE.md 절대 규칙 4의 사후 검출).
    """
    def g(k):
        return os.environ.get(k) or None
    return {"lastAttemptRunId": g("GITHUB_RUN_ID"),
            "lastAttemptRunNumber": g("GITHUB_RUN_NUMBER"),
            "lastAttemptRunAttempt": g("GITHUB_RUN_ATTEMPT")}


def is_retryable(status, pol):
    """분류표에 없는 실패는 재시도 가능으로 본다 — 기본값이 계약이다.

    반대로 두면 DART가 새 오류 코드를 내놓는 날마다 그 법인들이 조용히 '수집 불가'로
    승격되고 복구 가능한 데이터가 영구히 버려진다.
    """
    fc = pol["failureClassification"]
    if status is not None and str(status) in fc["nonRetryableStatuses"]:
        return False
    return bool(fc["defaultRetryable"])


# ── DART 호출 ──────────────────────────────────────────────────
def require_requests():
    """수집 경로 진입 시점에 requests를 올리고 전역 timeout 기본값을 심는다.

    호출부에 timeout= 인자가 없다고 timeout이 없는 것이 아니다 — 이 몽키패치가
    인자 없는 모든 요청에 (10, 60)을 넣는다. 실측 최댓값 1.55초/호출의 약 39배
    여유이며, 지연 편차가 경합이 아니라 DART 쪽 변동에서 오므로 빡빡하게 잡지 않는다.
    """
    global requests
    if requests is not None:
        return requests
    import requests as _r

    _orig_send = _r.adapters.HTTPAdapter.send

    def _send(self, request, **kw):
        if kw.get("timeout") is None:
            kw["timeout"] = (10, 60)
        return _orig_send(self, request, **kw)

    _r.adapters.HTTPAdapter.send = _send
    requests = _r
    return _r

LAST_HTTP = {"endpoint": None, "httpStatus": None, "dartStatus": None, "bytes": None}


def dart_call(endpoint, params, pol, counters):
    """(rows, dartStatus, hardError)

    DART는 조회 실패도 HTTP 200 + status 필드로 돌려준다 — HTTP status만 보는 재시도는
    0회 돈다(교훈38). 그래서 두 축을 다 보고, 재시도는 '하드 실패'에만 건다.
    '데이터 없음'을 재시도하면 폐지 법인 구간에서 호출 예산을 헛되이 태운다.

    crtfc_key는 params로만 넘기고 로그·산출물 어디에도 남기지 않는다.
    """
    # last_status는 '마지막 시도'의 것이어야 한다. 비-DART 실패(전송·HTTP·파싱)에서
    # 이전 시도의 DART status가 남아 있으면 분류가 그것을 보고 오판한다 —
    # 1차 100 → 2차 HTTP 503이면 마지막 실패는 재시도 가능인데 non-retryable이 된다.
    # 그래서 매 시도가 두 값을 함께 덮고, 비-DART 실패는 status를 None으로 둔다.
    last_status, last_err = None, None
    for i in range(pol["retryAttempts"]):
        counters["calls"] += 1
        try:
            r = requests.get(f"{BASE}/{endpoint}", params={"crtfc_key": KEY, **params})
        except Exception as e:  # noqa: BLE001
            last_status, last_err = None, f"{type(e).__name__}: {str(e)[:150]}"
            LAST_HTTP.update(endpoint=endpoint, httpStatus=None, dartStatus=None, bytes=None)
        else:
            body = r.content or b""
            LAST_HTTP.update(endpoint=endpoint, httpStatus=r.status_code, bytes=len(body))
            if 200 <= r.status_code < 300:
                try:
                    j = r.json()
                except Exception as e:  # noqa: BLE001
                    last_status, last_err = None, f"PARSE {type(e).__name__}: {str(e)[:150]}"
                else:
                    st = str(j.get("status", ""))
                    LAST_HTTP["dartStatus"] = st
                    counters["dartStatus"][st] += 1
                    if st == "000":
                        return (j.get("list") or []), st, None
                    # 데이터 없음과 한도 초과는 재시도 대상이 아니다.
                    # 전자는 정상 사실이고 후자는 기다린다고 풀리지 않는다.
                    if st in (DART_NO_DATA, pol["quota"]["quotaExceededStatus"]):
                        return [], st, None
                    last_status, last_err = st, str(j.get("message", ""))[:150]
            else:
                last_status, last_err = None, f"HTTP {r.status_code}"
        if i < pol["retryAttempts"] - 1:
            time.sleep(pol["retryBackoffBase"] ** i)
    return [], last_status, (last_err or "unknown")


# ── 계정 매칭 ──────────────────────────────────────────────────
def id_tail(account_id):
    """'ifrs-full_Equity' · 'ifrs_Equity' → 'Equity'.

    2019년 전후로 IFRS 태그 접두사가 바뀌었다. 접두사째 비교하면 옛 사업연도가
    통째로 미매칭으로 잡히고, 그 결과가 '그 해에 소스가 무너졌다'로 오독된다.
    """
    s = (account_id or "").strip()
    if not s or s.startswith("-"):     # '-표준계정코드 미사용-'
        return None
    return s.split("_", 1)[1] if "_" in s else s


def to_amount(raw):
    if raw is None:
        return None
    t = str(raw).replace(",", "").strip()
    if not t or t == "-":
        return None
    try:
        return int(float(t))
    except ValueError:
        return None


def match_accounts(rows, spec_all, order):
    """(값, 매칭수단). 어느 수단으로 잡았는지를 남기는 이유는 계약 2다 —
    연도별 매칭률이 떨어졌을 때 소스 변화인지 이름 변주인지 사후에 갈라야 한다."""
    vals, how = {}, {}
    for key, spec in spec_all.items():
        cand = [r for r in rows if str(r.get("sj_div", "")) in spec["sj"]] or rows
        found_row, found_how = None, None
        for mode in order:
            if mode == "id":
                tails = set(spec["idTails"])
                for r in cand:
                    if id_tail(r.get("account_id")) in tails:
                        found_row, found_how = r, "id"
                        break
            elif mode == "nameExact":
                ex = set(spec["exact"])
                for r in cand:
                    if str(r.get("account_nm", "")).replace(" ", "") in ex:
                        found_row, found_how = r, "nameExact"
                        break
            elif mode == "nameContains":
                for r in cand:
                    nm = str(r.get("account_nm", "")).replace(" ", "")
                    if any(c in nm for c in spec["contains"]):
                        found_row, found_how = r, "nameContains"
                        break
            if found_row is not None:
                break
        # 계정은 잡혔는데 금액이 비어 있는 경우가 있다. 그때 매칭수단을 남기면
        # '잡았다'로 집계되어 커버리지가 실제보다 높아진다 — 값이 없으면 미매칭이다.
        amt = to_amount(found_row.get("thstrm_amount")) if found_row is not None else None
        vals[key] = amt
        how[key] = found_how if amt is not None else None
    return vals, how


def parse_period_end(rows):
    """보고서가 스스로 말하는 회계기간말. 결산월로 계산하지 않는 이유는
    결산월 변경 이력과 어긋나고, A1b 폐지 법인에는 그 필드가 아예 없기 때문이다."""
    for r in rows:
        for field in ("thstrm_dt", "thstrm_nm"):
            hits = DT_IN_TEXT.findall(str(r.get(field, "")))
            if hits:
                y, m, d = hits[-1]
                return f"{y}-{m}-{d}"
    return None


def build_record(corp, ticker, year, rows, fs_div, sic, pol):
    rcept = str(rows[0].get("rcept_no", "")).strip()
    if not DATE8_RE.match(rcept[:8]):
        return None, "RCEPT_NO_NOT_DATE"
    period_end = parse_period_end(rows)
    if not period_end:
        return None, "PERIOD_END_UNPARSED"

    vals, how = match_accounts(rows, pol["accounts"]["spec"], pol["accounts"]["matchOrder"])
    rec = {
        "corp": corp,
        "ticker": ticker,
        "fiscalYear": year,
        "availableFrom": f"{rcept[:4]}-{rcept[4:6]}-{rcept[6:8]}",
        "rceptNo": rcept,
        "fsDiv": fs_div,
        "periodEnd": period_end,
        "currency": str(rows[0].get("currency", "")).strip() or None,
        "sicCode": sic,
        **vals,
        "accountSource": how,
    }
    return rec, None


# ── 수집 ───────────────────────────────────────────────────────
def target_corps():
    """corp → ticker. 조인 키는 corp_code다(계약 4). ticker는 사람이 읽는 보조 필드다.

    A1b가 A0.7 − A1a 차집합이라 겹칠 수 없지만, 겹치면 A1a를 우선한다 —
    ticker 재사용 시 현재 상장분의 ticker가 맞다.
    """
    out = {}
    for r in load_jsonl(A1B):
        out[r["corp"]] = {"ticker": r["ticker"], "group": "delisted"}
    for r in load_jsonl(A1A):
        out[r["corp"]] = {"ticker": r["ticker"], "group": "current"}
    return out


def state_path(shard):
    return f"{SHARD_DIR}/_state-{shard}.json"


def shard_path(shard):
    return f"{SHARD_DIR}/shard-{shard}.jsonl"


# collectionContractHash 도입 전(FN-1.2 이하)에 쓰인 상태를 이어받기 위한 표.
# 여기 있는 버전은 '그 버전의 collectionContract 필드 값이 현재와 같다'가 대조로
# 확인된 것만이다 — FN-1.2 → FN-1.3 diff에서 기존 줄 중 바뀐 것은 version 문자열
# 하나뿐이었다. 확인 없이 이 표에 버전을 추가하면 다른 규칙으로 모은 레코드를
# 이어받게 되고, 그것이 바로 이 판정이 막으려던 실패다.
LEGACY_CONTRACT_POLICIES = {"FN-1.2"}


def load_state(shard, shards, pol):
    p = state_path(shard)
    contract = collection_contract_hash(pol)
    if os.path.exists(p):
        st = load_json(p)
        prev = st.get("collectionContractHash")
        if prev is None and st.get("fundamentalsPolicy") in LEGACY_CONTRACT_POLICIES:
            # 일회성 이관. 값 대조로 계약 동일성이 확인된 버전에만 적용된다.
            print(f"  상태 이관 — {st.get('fundamentalsPolicy')}의 수집 계약은 현재와 같다. "
                  f"{contract}로 채운다")
            prev = contract
            st["collectionContractHash"] = contract
        if st.get("shards") == shards and prev == contract:
            return st
        # 담당 법인 배분(shards)이나 레코드 내용을 결정하는 계약이 바뀌면, 이미 모은
        # 레코드가 어느 규칙에서 나온 것인지 알 수 없으므로 버리고 다시 시작한다.
        # 판정을 정책 version이 아니라 계약 해시로 하는 이유는 반대 실패 때문이다 —
        # 임계 하나를 고쳐 version이 올라갔다고 며칠치 수집을 버리면 안 된다.
        if st.get("shards") != shards:
            print(f"  이전 상태 폐기 — shards {st.get('shards')}→{shards} "
                  f"(담당 법인 배분이 달라진다)")
        else:
            print(f"  이전 상태 폐기 — 수집 계약 {prev}→{contract} "
                  f"(정책 {st.get('fundamentalsPolicy')}→{pol['version']})")
    return {"stage": "A3", "shard": shard, "shards": shards,
            "collectionContractHash": contract,
            # 이 완화로 하나의 산출물이 여러 정책 버전에 걸쳐 수집될 수 있다.
            # 옛 판정이 암묵적으로 주던 '한 버전에서 나왔다'는 정보를 값으로 대체한다.
            "policyVersions": [], "fundamentalsPolicy": pol["version"],
            "corpsAssigned": 0, "corpsDone": [],
            # 하드 실패로 0레코드인 법인. done도 아니고 남은 것도 아닌 세 번째 상태다.
            # 이것이 없으면 그런 법인이 done에 들어가 영구히 건너뛰어진다.
            "hardSkipped": {}, "corpsPartialHard": 0,
            "callsUsedToday": 0, "lastRunDate": None,
            # 누적 카운터. 샤드 진단은 실행마다 덮이는데 수집은 며칠에 걸치므로,
            # 전수 비율을 내려면 여기 쌓여야 한다. periodEnd를 못 읽어 버린 보고서는
            # 산출물에 흔적이 없다 — 분모가 남지 않는 손실이라 여기서만 셀 수 있다.
            "reportsFound": 0, "recordRejected": {},
            # 수집이 며칠에 걸치므로 산출물은 혼합 시점 스냅샷이 된다. PIT는 깨지지 않지만
            # (각 레코드가 자기 availableFrom을 들고 있다) 재현성은 깨진다 — 재수집 시
            # 바이트가 달라졌을 때 그게 버그인지 정정공시인지 가를 근거를 여기 남긴다.
            "runDates": []}


# ── 완료 판정 — 저장하지 않고 매번 계산한다 ────────────────────
#
# 관통 원칙: 상태는 단조하게 축적되고, 판정은 언제든 다시 계산할 수 있어야 한다.
# complete를 저장하면 승인 목록이 바뀌는 즉시 낡고, 그것을 맞추려고 상태를 다시 쓰고
# 싶어진다. 그 유혹을 없애는 것이 이 분리의 목적이다.
#
#   정의     complete ≡ corpsRemaining == 0 AND hardSkippedOpen == 0
#   파생성질 complete ⇒ corpsAssigned == corpsDone + declaredHardSkipped
#
# 둘은 동치가 아니다. 아래는 정의에서 따라오는 성질일 뿐이며, 이 구분을 적어두지 않으면
# 언젠가 '정의는 그대로 두고 항등식만 맞추는' 수정이 들어온다 — 완료의 의미를 바꾸면서
# 바꾸지 않은 것처럼 보이게 만드는 수정이다.
_declared_cache = None


def declared_gaps():
    """승인된 공백 — 사람이 '이 법인은 재시도해도 안 된다'고 인정한 목록.

    **승인은 수집 동작을 바꾸지 않는다.** 승인된 법인도 다음 실행에서 똑같이 재시도되며,
    승인이 하는 일은 완료 판정에서 그 공백을 '열린 것'으로 세지 않는 것뿐이다.
    이 분리가 approvalHash를 collectionContractHash와 따로 두는 근거다 — 승인이 수집
    결과를 바꾸면 그것은 승인이 아니라 규칙이고, 규칙이라면 수집 계약 해시에 들어가야 한다.

    파일이 없으면 빈 집합이 아니라 예외다. '승인이 없다'와 '채널이 배선되지 않았다'는
    다르고, 후자를 조용히 통과시키면 승인 체계가 있는 척만 하게 된다.
    """
    global _declared_cache
    if _declared_cache is None:
        if not os.path.exists(DECLARED_GAPS):
            raise FileNotFoundError(
                f"{DECLARED_GAPS} 없음 — 빈 목록이라도 파일은 존재해야 한다. "
                f"파일 부재는 '승인이 없다'가 아니라 '승인 채널이 배선되지 않았다'는 뜻이다")
        doc = load_json(DECLARED_GAPS)
        gaps = doc.get("gaps")
        if not isinstance(gaps, list):
            raise ValueError(f"{DECLARED_GAPS}의 gaps가 배열이 아니다")
        out = set()
        for g in gaps:
            corp = (g or {}).get("corp")
            if not CORP_RE.match(corp or ""):
                raise ValueError(f"{DECLARED_GAPS}의 corp 계약 위반: {corp!r}")
            if not str((g or {}).get("reason") or "").strip():
                # 사유 없는 승인은 다음 사람이 재검토할 근거를 남기지 않는다.
                raise ValueError(f"{DECLARED_GAPS}의 {corp}에 reason이 없다")
            out.add(corp)
        _declared_cache = out
    return _declared_cache


def shard_status(state):
    """상태 하나에서 완료 판정과 항등식 항을 유도한다. 사실만 읽고 아무것도 쓰지 않는다.

    corpsAssigned가 없는 상태(계약 해시 도입 전에 쓰인 것)는 분모를 모른다. 0으로
    읽으면 '남음 -1381' 같은 거짓 수치가 나오고 보존식이 손상으로 오탐된다 —
    모르는 것은 0이 아니다. 그때는 remaining을 None으로 두고 완료를 부정한다.
    담당 법인 수는 다음 collect 실행이 채운다.
    """
    assigned = state.get("corpsAssigned")
    known = assigned is not None
    done = len(state.get("corpsDone") or [])
    hard = dict(state.get("hardSkipped") or {})
    declared = declared_gaps()
    open_hard = [c for c in hard if c not in declared]
    remaining = (assigned - done - len(hard)) if known else None
    return {
        "shard": state.get("shard"),
        "corpsAssigned": assigned,
        "corpsAssignedKnown": known,
        "corpsDone": done,
        "hardSkipped": len(hard),
        "hardSkippedOpen": len(open_hard),
        "hardSkippedOpenCorps": sorted(open_hard),
        "declaredHardSkipped": len(hard) - len(open_hard),
        "corpsRemaining": remaining,
        # 보존식이다. 사실만으로 성립하며 승인 정책이 바뀌어도 흔들리지 않는다 —
        # 그래서 open이 아니라 hardSkipped 전체가 들어간다. open만 쓰면 승인이
        # 하나 생기는 순간 등식이 깨진다. 분모를 모르면 잴 수 없으므로 검사에서 뺀다
        # (통과시키는 것이 아니라 판정 대상이 아니다 — 완료가 이미 부정된다).
        "conservationOk": (assigned == done + len(hard) + remaining) if known else True,
        "complete": known and remaining == 0 and not open_hard,
    }


def save_progress(shard, state, records):
    """상태와 산출을 함께 쓴다. 산출은 매번 통째로 다시 쓴다 — append로 이어붙이면
    법인 스캔 도중에 죽었을 때 부분 레코드가 남고, 재개하면 같은 키가 두 벌이 된다."""
    os.makedirs(SHARD_DIR, exist_ok=True)
    with open(shard_path(shard), "w", encoding="utf-8", newline="\n") as f:
        for k in sorted(records):
            f.write(json.dumps(records[k], ensure_ascii=False) + "\n")
    with open(state_path(shard), "w", encoding="utf-8", newline="\n") as f:
        json.dump(state, f, ensure_ascii=False, indent=2)


def fold_counters(state, counters):
    """이번 실행분을 상태의 누적으로 접고 비운다. 두 번 접히면 이중계상이므로
    비우는 것까지가 한 동작이다."""
    state["callsUsedToday"] += counters["calls"]
    state["reportsFound"] = state.get("reportsFound", 0) + counters["reportsFound"]
    rej = dict(state.get("recordRejected") or {})
    for k, v in counters["recordRejected"].items():
        rej[k] = rej.get(k, 0) + v
    state["recordRejected"] = rej
    counters["calls"] = 0
    counters["reportsFound"] = 0
    counters["recordRejected"] = Counter()


def rec_key(r):
    # 정정공시는 중복이 아니라 사실이다. availableFrom을 키에서 빼면 '그 시점에 알던 값'이 사라진다.
    return (r["corp"], r["fiscalYear"], r["availableFrom"])


def pick_fs_div(rows, preference):
    """주요계정은 fs_div가 요청 파라미터가 아니라 응답 행의 필드다 — 한 번의 응답에
    연결·별도가 함께 온다. 그래서 이것은 재시도 순서가 아니라 행 선별 순서다."""
    for div in preference:
        sel = [r for r in rows if str(r.get("fs_div", "")) == div]
        if sel:
            return sel, div
    return rows, (str(rows[0].get("fs_div", "")) or None)


def scan_corp(corp, ticker, pol, counters, state):
    """한 법인의 전 사업연도. (레코드 목록, 하드실패 정보, 한도초과 여부)

    하드실패를 개수가 아니라 정보로 돌려주는 이유는 호출자가 재시도 가능 여부를
    판정해야 하기 때문이다 — 개수만으로는 '무엇이 막혔는지'를 알 수 없고,
    "수집 경로가 막혔다"는 단일 문구가 원인을 지목하지 못한다(교훈41).
    """
    years = range(pol["fiscalYearFrom"], pol["fiscalYearTo"] + 1)
    preference = list(pol["source"]["fsDivPreference"])
    quota_status = pol["quota"]["quotaExceededStatus"]
    out, any_found, empty_run = [], False, 0
    fail = {"count": 0, "lastStatus": None, "lastReason": None}
    sic = None

    for y in years:
        got, year_hard = None, False
        rows, st, err = dart_call(pol["source"]["endpoint"], {
            "corp_code": corp, "bsns_year": str(y),
            "reprt_code": pol["source"]["reprtCode"]}, pol, counters)
        time.sleep(pol["requestSleepSeconds"])
        if st == quota_status:
            return out, fail, True
        if err:
            fail["count"] += 1
            fail["lastStatus"] = st
            fail["lastReason"] = err
            year_hard = True
            counters["hardErrors"] += 1
        elif rows:
            got = pick_fs_div(rows, preference)
        if got is None:
            # 하드 실패한 해를 '보고서 없음'으로 세지 않는다. 그렇게 하면 일시적인
            # 네트워크 오류 세 번이 조기 종료를 불러 그 법인의 이후 이력을 통째로 자른다.
            if any_found and not year_hard:
                empty_run += 1
                if empty_run >= pol["stopAfterConsecutiveEmptyYears"]:
                    # 보고서를 낸 적 있는 법인이 연속으로 비면 그 뒤는 영원히 빈다.
                    # 폐지 법인 1,222건의 호출을 크게 줄이는 지점이다.
                    counters["earlyStopped"] += 1
                    break
            continue

        empty_run = 0
        if not any_found:
            any_found = True
            # 업종은 보고서가 하나라도 있는 법인에만 묻는다. 전 법인에 묻으면
            # 재무가 아예 없는 법인 몫으로 호출 예산이 새어 나간다.
            # 조회 실패는 레코드를 버리는 사유가 아니다 — sicCode 결측은 하류에서
            # 'general'로 채점되는 정상 경로이고, 여기서 버리면 재무 전체를 잃는다.
            sic = fetch_sic(corp, pol, counters)

        counters["reportsFound"] += 1
        rec, why = build_record(corp, ticker, y, got[0], got[1], sic, pol)
        if rec is None:
            # 사유별로 센다. 파싱률을 별도 카운터로 두면 rcept 실패가 periodEnd 실패로
            # 섞여 들어간다 — 비율은 reportsFound와 이 표에서 정확히 유도된다.
            counters["recordRejected"][why] += 1
            continue
        out.append(rec)

    return out, fail, False


def fetch_sic(corp, pol, counters):
    """company.json은 list가 아니라 최상위 필드로 온다 — 전용 경로가 필요하다."""
    for i in range(pol["retryAttempts"]):
        counters["calls"] += 1
        try:
            r = requests.get(f"{BASE}/{pol['source']['companyEndpoint']}",
                             params={"crtfc_key": KEY, "corp_code": corp})
            if 200 <= r.status_code < 300:
                j = r.json()
                st = str(j.get("status", ""))
                counters["dartStatus"][st] += 1
                if st == "000":
                    return (str(j.get("induty_code", "")).strip() or None)
                if st in (DART_NO_DATA, pol["quota"]["quotaExceededStatus"]):
                    return None
        except Exception:  # noqa: BLE001
            pass
        if i < pol["retryAttempts"] - 1:
            time.sleep(pol["retryBackoffBase"] ** i)
    counters["sicFetchFailed"] += 1
    return None


def run_shard(shard, shards, pol, limit):
    require_requests()      # 수집 경로에서만 필요하다 (--summary·--finalize는 안 쓴다)
    diag_path = f"{SHARD_DIR}/_diagnostics-shard-{shard}.json"
    counters = {"calls": 0, "dartStatus": Counter(), "hardErrors": 0,
                "earlyStopped": 0, "sicFetchFailed": 0,
                "reportsFound": 0, "recordRejected": Counter()}
    diag = {"stage": "A3", "mode": "shard", "shard": shard, "shards": shards,
            "fundamentalsPolicy": pol["version"], "runDate": today_kst()}
    if limit:
        # 스모크 테스트는 산출물을 만들 수 있지만 verify-diagnostics가 이 플래그를 보고
        # 거부한다. 통과를 만들 수 없는 한 방향 훅이다.
        diag["smokeTest"] = True

    if not KEY:
        _abort("DART_API_KEY 환경변수가 없다", diag, diag_path)

    corps = target_corps()
    ordered = sorted(corps)
    # 라운드로빈 — 연속 구간으로 자르면 폐지 법인이 특정 샤드에 몰려 소요가 크게 갈린다.
    mine = [c for i, c in enumerate(ordered) if i % shards == shard]
    if limit:
        mine = mine[:limit]

    state = load_state(shard, shards, pol)
    if state["lastRunDate"] != diag["runDate"]:
        state["callsUsedToday"] = 0     # DART 한도는 KST 하루 단위다
        state["lastRunDate"] = diag["runDate"]
    state.setdefault("runDates", [])
    if diag["runDate"] not in state["runDates"]:
        state["runDates"].append(diag["runDate"])
    # 이관된 상태에는 새 필드가 없다. 사실 축적형이므로 기본값으로 열어두면 되고,
    # 여기서 지우거나 다시 계산하지 않는다(원칙 1 — 상태는 단조하게 축적된다).
    state.setdefault("hardSkipped", {})
    state.setdefault("corpsPartialHard", 0)
    state.setdefault("policyVersions", [])
    state.pop("complete", None)      # 원칙 2 — 판정은 저장하지 않는다
    state["fundamentalsPolicy"] = pol["version"]
    if pol["version"] not in state["policyVersions"]:
        state["policyVersions"].append(pol["version"])
    # 담당 법인 수는 사실이고 완료 판정의 분모다. 상태에 있어야 finalize와 persist가
    # 샤딩을 다시 계산하지 않고도 완료를 유도할 수 있다.
    state["corpsAssigned"] = len(mine)
    budget = (pol["quota"]["dailyCallLimit"] - pol["quota"]["safetyMarginCalls"]) // shards

    done = set(state["corpsDone"])
    hard_skipped = dict(state["hardSkipped"])
    # 이전 실행의 산출을 읽되 '완료된 법인'의 것만 남긴다. 스캔 도중 죽은 법인의
    # 부분 레코드를 그대로 두면 재개분과 겹쳐 같은 키가 두 벌이 된다.
    records = {}
    if os.path.exists(shard_path(shard)):
        for r in load_jsonl(shard_path(shard)):
            if r["corp"] in done:
                records[rec_key(r)] = r

    todo = [c for c in mine if c not in done]
    print(f"A3 샤드 {shard}/{shards} — 담당 {len(mine)}법인 · 완료 {len(mine)-len(todo)} · "
          f"남음 {len(todo)}")
    print(f"  사업연도 {pol['fiscalYearFrom']}~{pol['fiscalYearTo']} · "
          f"오늘 예산 {budget - state['callsUsedToday']}/{budget}건 "
          f"(사용 {state['callsUsedToday']})")

    # 정찰 2회(교훈32) — 경로가 막혔으면 3,801법인을 돌리지 않고 즉시 중단한다.
    probes = []
    for pc in pol["probeCorps"]:
        rows, st, err = dart_call(pol["source"]["endpoint"], {
            "corp_code": pc, "bsns_year": str(pol["probeYear"]),
            "reprt_code": pol["source"]["reprtCode"]}, pol, counters)
        probes.append({"corp": pc, "ok": bool(rows), "dartStatus": st, "error": err})
        time.sleep(pol["requestSleepSeconds"])
    diag["probes"] = probes
    if not any(p["ok"] for p in probes):
        _abort("정찰 전건 실패 — 수집 경로가 막혔다", diag, diag_path,
               {"lastHttp": LAST_HTTP})
    print(f"  정찰 {sum(1 for p in probes if p['ok'])}/{len(probes)} 통과")

    consec_hard, quota_hit, budget_hit = 0, False, False
    t0 = time.time()
    processed = 0
    # 이번 실행분의 항등식 항. 누적(corpsDone)과 시계가 다르므로 한 식에 섞지 않는다 —
    # 섞으면 이틀째부터 항상 깨진다.
    done_added, hard_this_run, quota_deferred = 0, 0, 0
    # 루프 진입 시점에서 센다. 출구 쪽 카운터(done_added·hard_this_run)와 세는 자리가
    # 달라야 항등식이 무언가를 잡는다 — 같은 자리에서 세면 구성상 항상 맞는 검사가 된다.
    attempted = 0
    done_before = len(done)
    ident = run_identity()

    for corp in todo:
        if state["callsUsedToday"] + counters["calls"] >= budget:
            budget_hit = True
            break
        attempted += 1
        recs, fail, quota = scan_corp(corp, corps[corp]["ticker"], pol, counters, state)
        if quota:
            # 한도를 만나면 부분 레코드를 버리고 즉시 멈춘다. 이 법인은 done도
            # hardSkipped도 아닌 '연기'이며 다음 실행이 처음부터 다시 한다.
            quota_hit = True
            quota_deferred = 1
            break
        for r in recs:
            records[rec_key(r)] = r
        processed += 1

        if fail["count"] and not recs:
            # 하드 실패로 0레코드다. 여기서 done에 넣으면 그 법인은 영구히
            # 건너뛰어지고, complete가 그것을 완료로 계산해 finalize의 미완료 검사도
            # 통과한다 — 데이터가 빈 채로 인수 조건을 지나간다.
            prev = hard_skipped.get(corp) or {}
            hard_skipped[corp] = {
                "corp": corp,
                # attempts는 실행(일) 단위다. 정책의 retryAttempts는 한 실행 안의
                # 재시도라, 그것까지 합치면 5가 하루치인지 닷새치인지 갈리지 않아
                # firstSeen·lastSeen 두 타임스탬프가 무의미해진다.
                "attempts": (prev.get("attempts") or 0) + 1,
                "firstSeen": prev.get("firstSeen") or diag["runDate"],
                "lastSeen": diag["runDate"],
                "lastStatus": fail["lastStatus"],
                "lastReason": fail["lastReason"],
                "retryable": is_retryable(fail["lastStatus"], pol),
                **ident,
            }
            hard_this_run += 1
            consec_hard += 1
        else:
            # 성공했다면 이전 실행의 하드 실패 기록을 지운다. 남겨두면 done과
            # hardSkipped가 겹쳐 보존식이 깨진다.
            hard_skipped.pop(corp, None)
            done.add(corp)
            done_added += 1
            consec_hard = 0
            if fail["count"]:
                # 일부 연도만 실패하고 레코드는 나온 법인. done으로 두되(그 법인의
                # 재무는 확보됐다) 몇 건인지는 남긴다 — 세지 않으면 부분 공백이
                # 완전 수집과 구분되지 않는다.
                state["corpsPartialHard"] = state.get("corpsPartialHard", 0) + 1

        state["corpsDone"] = sorted(done)
        state["hardSkipped"] = hard_skipped

        if consec_hard >= pol["circuitBreakerConsecutiveFailures"]:
            fold_counters(state, counters)
            save_progress(shard, state, records)
            diag.update(corpsProcessed=processed, recordCount=len(records),
                        calls=counters["calls"], lastHttp=LAST_HTTP)
            _abort(f"연속 하드 실패 {consec_hard}법인 — 루프 도중 경로가 막혔다",
                   diag, diag_path)

        if processed % 25 == 0:
            # 누적 카운터를 상태로 접고 비운다. 접지 않으면 잡이 중간에 죽었을 때
            # corpsDone에는 들어갔는데 그 구간의 보고서 수는 사라져, 파싱률의 분모가
            # 조용히 작아진다. 체크포인트가 옮기지 않는 값은 체크포인트가 잃는 값이다.
            fold_counters(state, counters)
            save_progress(shard, state, records)
            print(f"  {processed}/{len(todo)} · {len(records)}레코드 · "
                  f"호출 {state['callsUsedToday']} · {time.time()-t0:.0f}s")

    fold_counters(state, counters)
    save_progress(shard, state, records)

    status = shard_status(state)
    # 실행 항등식. corpsAttempted는 이번 실행분이고 corpsDone은 누적이라 시계가 다르다 —
    # 한 식에 섞으면 이틀째부터 항상 깨진다. quotaDeferred는 0 또는 1이다
    # (한도를 만나면 즉시 break하고 부분 레코드는 버린다).
    # 두 번째 항은 done 집합의 실제 증가분과 대조한다. 카운터가 아니라 집합을 보므로
    # 같은 법인이 두 번 세어지거나 다른 경로로 done에 들어가는 것을 잡는다.
    run_identity_ok = (attempted == done_added + hard_this_run + quota_deferred
                       and len(done) - done_before == done_added)
    diag.update(
        corpsAssigned=status["corpsAssigned"], corpsDone=status["corpsDone"],
        corpsProcessed=processed, recordCount=len(records),
        calls=state["callsUsedToday"], budget=budget,
        dartStatus=dict(counters["dartStatus"]), hardErrors=counters["hardErrors"],
        earlyStopped=counters["earlyStopped"], sicFetchFailed=counters["sicFetchFailed"],
        # 진단은 이 실행의 기록이고 누적은 상태에 있다. 둘을 섞으면 며칠에 걸친
        # 수집에서 어느 쪽이 전수인지 모호해진다.
        reportsFoundCumulative=state["reportsFound"],
        recordRejectedCumulative=dict(state["recordRejected"]),
        quotaExceeded=quota_hit, budgetExhausted=budget_hit,
        # 완료는 계산값이다(원칙 2). 상태에 저장하지 않고 여기서 유도한다.
        collectionContractHash=state["collectionContractHash"],
        policyVersions=list(state["policyVersions"]),
        hardSkipped=status["hardSkipped"], hardSkippedOpen=status["hardSkippedOpen"],
        hardSkippedDetail=state["hardSkipped"],
        corpsPartialHard=state.get("corpsPartialHard", 0),
        corpsRemaining=status["corpsRemaining"],
        conservationOk=status["conservationOk"],
        corpsAttemptedThisRun=attempted, doneAddedThisRun=done_added,
        hardSkippedThisRun=hard_this_run, quotaDeferred=quota_deferred,
        runIdentityOk=run_identity_ok,
        complete=status["complete"], elapsedSeconds=round(time.time() - t0, 1))
    with open(f"{SHARD_DIR}/_diagnostics-shard-{shard}.json", "w",
              encoding="utf-8", newline="\n") as f:
        json.dump(diag, f, ensure_ascii=False, indent=2)

    tail = ("완료" if status["complete"] else
            "한도 초과 — 다음 실행이 이어받는다" if quota_hit else
            "오늘 예산 소진 — 다음 실행이 이어받는다" if budget_hit else
            f"재시도 대기 {status['hardSkippedOpen']}법인" if status["hardSkippedOpen"] else
            "중단(원인 미상)")
    print(f"\n{shard_path(shard)} — {len(records)}레코드 · "
          f"법인 {status['corpsDone']}/{status['corpsAssigned']} · "
          f"하드스킵 {status['hardSkipped']}(열림 {status['hardSkippedOpen']}) · "
          f"남음 {status['corpsRemaining']} · 호출 {state['callsUsedToday']} · {tail}")
    if not status["conservationOk"]:
        print("  경고: 보존식 위반 — "
              f"assigned {status['corpsAssigned']} != done {status['corpsDone']} + "
              f"hardSkipped {status['hardSkipped']} + remaining {status['corpsRemaining']}")
    if not run_identity_ok:
        print(f"  경고: 실행 항등식 위반 — attempted {attempted} vs "
              f"done+{done_added} / hardSkip+{hard_this_run} / quotaDeferred "
              f"{quota_deferred} · done 집합 증가분 {len(done) - done_before}")
    # 예산 소진은 실패가 아니라 정상적인 분할 실행이다. exit(1)을 내면 매일 빨간 불이 된다.
    return 0


def run_summary():
    """샤드 상태를 읽어 진행을 요약한다. 읽기 전용이며 아무것도 쓰지 않는다.

    워크플로가 이것을 부르는 이유는 완료 판정이 계산값이 되면서다 — YAML 안에
    같은 계산을 다시 적으면 계약이 두 벌이 되고 둘이 같이 틀린다(교훈44).
    """
    states = sorted(glob.glob(f"{SHARD_DIR}/_state-*.json"))
    if not states:
        print("샤드 상태 없음 — 수집을 아직 돌리지 않았다")
        return 0
    tot = Counter()
    complete, unknown = 0, 0
    for p in states:
        st = load_json(p)
        s = shard_status(st)
        complete += 1 if s["complete"] else 0
        for k in ("corpsDone", "hardSkipped", "hardSkippedOpen"):
            tot[k] += s[k]
        if s["corpsAssignedKnown"]:
            tot["corpsAssigned"] += s["corpsAssigned"]
            tot["corpsRemaining"] += s["corpsRemaining"]
        else:
            unknown += 1
        tot["calls"] += st.get("callsUsedToday", 0)
        tot["partialHard"] += st.get("corpsPartialHard", 0)
    recs = sum(sum(1 for _ in open(p, encoding="utf-8"))
               for p in sorted(glob.glob(f"{SHARD_DIR}/shard-*.jsonl")))
    denom = "?" if unknown else tot["corpsAssigned"]
    print(f"법인 완료 {tot['corpsDone']}/{denom} · 레코드 {recs} · "
          f"오늘 호출 {tot['calls']} · 완료 샤드 {complete}/{len(states)}")
    print(f"하드스킵 {tot['hardSkipped']}(미승인 {tot['hardSkippedOpen']}) · "
          f"부분실패 {tot['partialHard']} · "
          f"남음 {'?' if unknown else tot['corpsRemaining']}")
    if unknown:
        print(f"  샤드 {unknown}개가 담당 법인 수를 모른다 — 계약 해시 도입 전에 쓰인 "
              f"상태다. 다음 collect 실행이 채운다")
    if complete == len(states):
        print("전 샤드 완료 — finalize를 돌려라")
    elif tot["hardSkippedOpen"]:
        print("collect를 다시 dispatch하면 이어받는다. 미승인 하드스킵은 재시도되며, "
              "재시도 불가로 분류된 것만 승인 대상이다")
    else:
        print("collect를 다시 dispatch하면 이어받는다 (DART 한도는 KST 자정에 초기화된다)")
    return 0


# ── finalize ───────────────────────────────────────────────────
def write_gz(path, records, pol, fields=None):
    o = pol["output"]
    buf = io.BytesIO()
    for x in records:
        row = {k: x.get(k) for k in fields} if fields else x
        buf.write((json.dumps(row, ensure_ascii=False) + "\n").encode("utf-8"))
    raw = buf.getvalue()
    with open(path, "wb") as fh:
        gz = gzip.GzipFile(filename="", mode="wb", fileobj=fh,
                           compresslevel=o["gzipCompressLevel"], mtime=o["gzipMtime"])
        gz.write(raw)
        gz.close()
    return len(raw), os.path.getsize(path)


def coverage_of(rec, required):
    return all(rec.get(k) is not None for k in required)


def validate(rows, corps, pol, diag):
    a = pol["acceptance"]
    required = pol["accounts"]["requiredForCoverage"]
    print("\n[인수 조건]")

    inject = os.environ.get("A3_FAIL_INJECTION", "").strip()
    if inject:
        diag["failInjection"] = inject
        chk(False, f"[FAIL INJECTION] {inject} — 게이트 검증용 강제 실패")

    # ── 식별자·날짜 계약 ──────────────────────────────────────
    bad_corp = [r for r in rows if not CORP_RE.match(r.get("corp") or "")]
    chk(len(bad_corp) == a["corpContractViolations"],
        f"corp_code 계약 [0-9]{{8}} (위반 {len(bad_corp)}건) — 재무 조인은 이 키로만 한다")
    bad_ticker = [r for r in rows if not TICKER_RE.match(r.get("ticker") or "")]
    diag["tickerContractViolations"] = len(bad_ticker)
    warn(not bad_ticker, f"ticker 계약 [0-9A-Z]{{6}} 위반 {len(bad_ticker)}건 (보조 필드라 WARN)")

    no_af = [r for r in rows if not DATE_RE.match(r.get("availableFrom") or "")]
    chk(len(no_af) == a["availableFromMissing"],
        f"availableFrom 존재·형식 (위반 {len(no_af)}건)")
    no_pe = [r for r in rows if not DATE_RE.match(r.get("periodEnd") or "")]
    chk(len(no_pe) == a["periodEndMissing"], f"periodEnd 존재·형식 (위반 {len(no_pe)}건)")

    # ── PIT 계약 1 — A3의 존재 이유 ────────────────────────────
    bad_pit = [r for r in rows
               if DATE_RE.match(r.get("availableFrom") or "")
               and DATE_RE.match(r.get("periodEnd") or "")
               and not (r["availableFrom"] > r["periodEnd"])]
    diag["availableFromNotAfterPeriodEnd"] = len(bad_pit)
    diag["availableFromNotAfterPeriodEndSample"] = [
        {k: r[k] for k in ("corp", "fiscalYear", "availableFrom", "periodEnd")}
        for r in bad_pit[:20]]
    chk(len(bad_pit) == a["availableFromNotAfterPeriodEnd"],
        f"availableFrom > periodEnd (위반 {len(bad_pit)}건) — "
        f"위반은 로직 반전이거나 periodEnd 파싱 오류다")

    lags = sorted((datetime.strptime(r["availableFrom"], "%Y-%m-%d")
                   - datetime.strptime(r["periodEnd"], "%Y-%m-%d")).days
                  for r in rows
                  if DATE_RE.match(r.get("availableFrom") or "")
                  and DATE_RE.match(r.get("periodEnd") or ""))
    if lags:
        diag["disclosureLagDays"] = {
            "min": lags[0], "p50": lags[len(lags) // 2],
            "p95": lags[min(int(len(lags) * 0.95), len(lags) - 1)], "max": lags[-1]}
        print(f"  ..    공시지연 p50={diag['disclosureLagDays']['p50']}일 "
              f"p95={diag['disclosureLagDays']['p95']}일 "
              f"max={diag['disclosureLagDays']['max']}일 (관측 — 게이트 아님)")

    # ── 유일성 ────────────────────────────────────────────────
    keys = {rec_key(r) for r in rows}
    dup = len(rows) - len(keys)
    chk(dup == a["duplicateKeys"],
        f"(corp, fiscalYear, availableFrom) 중복 {dup}건 — 정정공시는 중복이 아니라 사실이다")

    restated = Counter((r["corp"], r["fiscalYear"]) for r in rows)
    n_restated = sum(1 for v in restated.values() if v > 1)
    diag["restatedFiscalYears"] = n_restated
    print(f"  ..    같은 (corp, fiscalYear)에 availableFrom이 둘 이상인 건 {n_restated}건 "
          f"(정정공시 — 병합하지 않는다)")

    # ── 사업연도 축 ───────────────────────────────────────────
    years = list(range(pol["fiscalYearFrom"], pol["fiscalYearTo"] + 1))
    by_year = defaultdict(list)
    for r in rows:
        by_year[r["fiscalYear"]].append(r)
    out_of_range = [r for r in rows if r["fiscalYear"] not in years]
    diag["fiscalYearOutOfRange"] = len(out_of_range)
    chk(not out_of_range, f"정책 구간 밖 사업연도 {len(out_of_range)}건")

    empty_years = [y for y in years if not by_year.get(y)]
    diag["yearsWithNoData"] = len(empty_years)
    diag["yearsWithNoDataList"] = empty_years
    chk(len(empty_years) == a["yearsWithNoData"],
        f"데이터가 0건인 사업연도 {len(empty_years)}개 {empty_years}")

    # ── 계약 2: 연도별 계정 매칭 성공률 ────────────────────────
    year_cov = {}
    for y in years:
        xs = by_year.get(y, [])
        full = sum(1 for r in xs if coverage_of(r, required))
        year_cov[str(y)] = {"records": len(xs), "full": full,
                            "rate": round(full / len(xs), 4) if xs else None}
    diag["yearCoverage"] = year_cov

    per_account_year = {}
    for y in years:
        xs = by_year.get(y, [])
        if not xs:
            continue
        per_account_year[str(y)] = {
            k: round(sum(1 for r in xs if r.get(k) is not None) / len(xs), 4)
            for k in pol["accounts"]["spec"]}
    diag["accountCoverageByYear"] = per_account_year

    rates = [v["rate"] for v in year_cov.values() if v["rate"] is not None]
    med = median(rates) if rates else 0
    dropped = [y for y, v in year_cov.items()
               if v["rate"] is not None and med - v["rate"] > a["yearCoverageDropWarn"]]
    diag["yearCoverageMedian"] = round(med, 4)
    diag["yearCoverageDropped"] = dropped
    # 계약 2. FN-1.0에서는 WARN이다 — 실측 기준선이 아직 없다.
    # 전체 평균이 아니라 중앙값 대비 낙폭을 보는 이유: 평균만 보면 한 해가 무너져도
    # 나머지 열 해가 가린다.
    warn(not dropped,
         f"연도별 매칭률이 중앙값({med:.1%}) 대비 "
         f"{a['yearCoverageDropWarn']*100:.0f}%p 이상 낮은 사업연도 {dropped}")

    # ── 커버리지 ──────────────────────────────────────────────
    full_cnt = sum(1 for r in rows if coverage_of(r, required))
    cov_rate = full_cnt / len(rows) if rows else 0
    diag["coverageRate"] = round(cov_rate, 5)
    diag["coverageRequiredAccounts"] = required
    warn(cov_rate >= a["coverageRateMinWarn"],
         f"필수 {len(required)}계정 전부 확보 {cov_rate*100:.1f}% >= "
         f"{a['coverageRateMinWarn']*100:.0f}% ({full_cnt}/{len(rows)})")

    corps_with = {r["corp"] for r in rows}
    diag["corpsWithData"] = len(corps_with)
    diag["corpsTargeted"] = len(corps)
    diag["corpsWithoutData"] = len(corps) - len(corps_with)
    by_group = Counter(corps[c]["group"] for c in corps_with if c in corps)
    tgt_group = Counter(v["group"] for v in corps.values())
    diag["corpsWithDataByGroup"] = dict(by_group)
    diag["corpsTargetedByGroup"] = dict(tgt_group)
    # 폐지 법인의 확보율을 따로 남긴다. 전체 비율만 보면 현재 상장분 2,579가
    # 폐지분 1,222의 공백을 가린다 — A2b 정찰에서 배운 것과 같은 분모 문제다.
    diag["corpsWithDataRateByGroup"] = {
        g: round(by_group.get(g, 0) / tgt_group[g], 4) for g in tgt_group}
    warn(len(corps_with) >= a["minCorpsWithDataWarn"],
         f"재무 확보 법인 {len(corps_with)} >= {a['minCorpsWithDataWarn']} "
         f"(대상 {len(corps)} · 그룹별 {diag['corpsWithDataRateByGroup']})")

    # ── 계약 3: |ROE| > 200% ──────────────────────────────────
    thr = a["roeAbsOutlierThreshold"]
    roes = [(r, r["netIncome"] / r["equity"])
            for r in rows
            if r.get("netIncome") is not None and r.get("equity")]
    outliers = [(r, v) for r, v in roes if abs(v) > thr]
    neg_eq = [r for r in rows if r.get("equity") is not None and r["equity"] < 0]
    diag["roeComputable"] = len(roes)
    diag["roeAbsOutlierCount"] = len(outliers)
    diag["roeAbsOutlierRate"] = round(len(outliers) / len(roes), 5) if roes else None
    diag["roeAbsOutlierSample"] = [
        {"corp": r["corp"], "ticker": r["ticker"], "fiscalYear": r["fiscalYear"],
         "roe": round(v, 3), "equity": r["equity"], "netIncome": r["netIncome"]}
        for r, v in sorted(outliers, key=lambda x: -abs(x[1]))[:30]]
    diag["negativeEquityCount"] = len(neg_eq)
    diag["negativeEquityRate"] = round(len(neg_eq) / len(rows), 5) if rows else None
    # 이상치를 제거하지 않는다. 자본잠식 기업의 ROE는 오류가 아니라 사실이고,
    # 여기서 도려내면 A5가 '정상 기업만 있는 세계'를 채점하게 된다 — 생존편향의 축소판이다.
    warn(diag["roeAbsOutlierRate"] is None
         or diag["roeAbsOutlierRate"] <= a["roeAbsOutlierRateWarn"],
         f"|ROE| > {thr*100:.0f}% {len(outliers)}건 "
         f"({(diag['roeAbsOutlierRate'] or 0)*100:.2f}%) — 제거하지 않고 보고만 한다")
    warn(diag["negativeEquityRate"] is None
         or diag["negativeEquityRate"] <= a["negativeEquityRateWarn"],
         f"자본총계 음수 {len(neg_eq)}건 ({(diag['negativeEquityRate'] or 0)*100:.2f}%)")

    diag["fsDivDistribution"] = dict(Counter(r.get("fsDiv") for r in rows))
    src = Counter()
    for r in rows:
        for k, v in (r.get("accountSource") or {}).items():
            src[f"{k}:{v or 'MISS'}"] += 1
    diag["accountSourceDistribution"] = dict(src)
    # 계정별 매칭률 — 전수 기준선이다. 정찰은 표본 32법인이라 이름 변주의 긴 꼬리를
    # 보지 못했다. 이 표가 있어야 나중에 계정명을 추가·변경할 때 회귀 여부를
    # 정량으로 판단할 수 있다(어느 수단으로 잡았는지까지 함께 남긴다).
    hit_by_account = {}
    for k in pol["accounts"]["spec"]:
        by_method = Counter((r.get("accountSource") or {}).get(k) or "MISS" for r in rows)
        hit = len(rows) - by_method["MISS"]
        hit_by_account[k] = {
            "hit": hit,
            "rate": round(hit / len(rows), 5) if rows else None,
            "byMethod": dict(by_method),
            "inCoverageNumerator": k in pol["accounts"]["requiredForCoverage"],
        }
    diag["accountMappingHitRateByAccount"] = hit_by_account
    diag["sicCodeMissing"] = sum(1 for r in rows if not r.get("sicCode"))

    # PIT 앵커 파싱률. 실측 전인데도 FAIL인 유일한 임계다 — 이 실패는 등급이 아니라
    # 이분적이기 때문이다(정찰 실측 240/240 대 0/240). 응답 형식이 바뀌거나 파서가
    # 깨지면 비율이 서서히 나빠지는 것이 아니라 통째로 무너진다.
    rate = diag.get("periodEndParsedRate")
    chk(rate is not None and rate >= a["periodEndParsedRateMin"],
        f"회계기간말 파싱률 {'측정 불가' if rate is None else f'{rate*100:.2f}%'} >= "
        f"{a['periodEndParsedRateMin']*100:.0f}% "
        f"(확보 보고서 {diag.get('reportsFound')} · 버림 {diag.get('recordRejected')})")

    return rows


def run_finalize(pol):
    diag_path = f"{OUT_DIR}/_diagnostics.json"
    diag = {"stage": "A3", "mode": "finalize", "fundamentalsPolicy": pol["version"],
            "stageVersion": STAGE_VERSION,
            # sicCode는 '현재의 업종'이라 전 사업연도에 같은 값이 붙는다.
            # 이 플래그가 사라지면 하류가 미확정값을 확정값으로 읽는다.
            "sectorNotPointInTime": True}

    shard_files = sorted(glob.glob(f"{SHARD_DIR}/shard-*.jsonl"))
    if not shard_files:
        _abort(f"{SHARD_DIR}에 샤드 산출물이 없다 — 수집 잡을 먼저 돌려라", diag, diag_path)

    # 전 샤드가 담당분을 끝냈는지 확인한다. 예산 소진으로 중단된 샤드가 섞이면
    # 부분 수집물에 manifest가 찍힌다 — manifest는 '인수 조건을 통과했다'는 뜻이다(교훈43).
    incomplete, run_dates = [], set()
    reports_found, rejected = 0, Counter()
    hard_all, open_all, partial_hard = {}, [], 0
    pol_versions, contract_hashes, conservation_bad = set(), set(), []
    for p in sorted(glob.glob(f"{SHARD_DIR}/_state-*.json")):
        st = load_json(p)
        run_dates.update(st.get("runDates") or [])
        reports_found += st.get("reportsFound", 0)
        rejected.update(st.get("recordRejected") or {})
        pol_versions.update(st.get("policyVersions") or
                            ([st["fundamentalsPolicy"]] if st.get("fundamentalsPolicy") else []))
        if st.get("collectionContractHash"):
            contract_hashes.add(st["collectionContractHash"])
        hard_all.update(st.get("hardSkipped") or {})
        partial_hard += st.get("corpsPartialHard", 0)
        # 완료는 상태에 저장돼 있지 않다. 현재 상태 + 현재 승인 목록에서 매번 유도한다 —
        # 저장하면 승인 목록이 바뀌는 즉시 낡는다(원칙 2).
        s = shard_status(st)
        open_all.extend(s["hardSkippedOpenCorps"])
        if not s["conservationOk"]:
            conservation_bad.append({"shard": s["shard"], "assigned": s["corpsAssigned"],
                                     "done": s["corpsDone"], "hardSkipped": s["hardSkipped"],
                                     "remaining": s["corpsRemaining"]})
        if not s["complete"]:
            incomplete.append({"shard": s["shard"], "done": s["corpsDone"],
                               # None이면 '아직 모른다'다. 0으로 읽으면 안 된다.
                               "remaining": s["corpsRemaining"],
                               "assignedKnown": s["corpsAssignedKnown"],
                               "hardSkippedOpen": s["hardSkippedOpen"]})
    diag["shardStatesIncomplete"] = incomplete
    # 수집이 여러 정책 버전에 걸칠 수 있게 됐으므로(FN-1.3 collectionContract),
    # 어느 버전들이 이 산출물을 만들었는지가 값으로 남아야 한다.
    diag["collectionPolicyVersions"] = sorted(pol_versions)
    diag["collectionContractHashes"] = sorted(contract_hashes)
    diag["corpsHardSkipped"] = len(hard_all)
    diag["corpsHardSkippedOpen"] = len(open_all)
    diag["hardSkippedDetail"] = hard_all
    diag["hardSkippedByRetryable"] = dict(Counter(
        ("retryable" if v.get("retryable") else "nonRetryable") for v in hard_all.values()))
    diag["corpsPartialHard"] = partial_hard
    diag["stateConservationViolations"] = conservation_bad
    # 승인은 실제 공백에 대응해야 한다. 대응하지 않는 승인은 '오래된 승인이 미래의
    # 공백을 미리 덮는' 경로이고, 그것이 승인 체계가 조용해지는 유일한 길이다.
    declared = declared_gaps()
    diag["declaredGaps"] = sorted(declared)
    diag["declaredGapsCount"] = len(declared)
    diag["declaredNotInHardSkipped"] = sorted(declared - set(hard_all))
    # 확보한 보고서 대비 레코드로 살아남은 비율. 이 분모는 산출물에 없다 —
    # 버려진 보고서는 흔적을 남기지 않으므로 여기서만 셀 수 있다.
    diag["reportsFound"] = reports_found
    diag["recordRejected"] = dict(rejected)
    pe_fail = rejected.get("PERIOD_END_UNPARSED", 0)
    diag["periodEndParsedRate"] = (round(1 - pe_fail / reports_found, 5)
                                   if reports_found else None)
    # 수집 창. 하루를 넘으면 산출물은 혼합 시점 스냅샷이며, 그 사실이 여기 남는다 —
    # 재수집으로 해시가 바뀌었을 때 정정공시라는 후보 원인을 가리키는 유일한 근거다.
    rd = sorted(run_dates)
    diag["collectionWindow"] = {"from": rd[0] if rd else None,
                                "to": rd[-1] if rd else None,
                                "runDays": len(rd)}
    if conservation_bad:
        # 사실의 보존식이 깨졌다는 것은 상태가 손상됐다는 뜻이다. 완료 판정보다 먼저
        # 본다 — 분해가 안 맞는 상태에서 내린 완료는 의미가 없다.
        _abort(f"상태 보존식 위반 샤드 {len(conservation_bad)}개 {conservation_bad} — "
               f"corpsAssigned = corpsDone + hardSkipped + corpsRemaining이 성립해야 한다",
               diag, diag_path)
    if len(contract_hashes) > 1:
        _abort(f"샤드들이 서로 다른 수집 계약으로 모았다 {sorted(contract_hashes)} — "
               f"한 산출물에 다른 규칙의 레코드가 섞인다", diag, diag_path)
    if incomplete:
        # 미완료의 사유가 둘로 갈린다. '아직 안 돌렸다'는 collect를 더 돌리면 되지만,
        # hardSkippedOpen은 재시도로 안 풀릴 수 있다 — retryable=false면 사람의 승인
        # (커밋 2의 declared-gaps 채널)이 있어야 닫힌다.
        blocked = [x for x in incomplete if x["hardSkippedOpen"]]
        hint = ("수집을 이어서 돌려라" if not blocked else
                f"그중 {len(blocked)}개는 미승인 하드스킵이 있다 — "
                f"재시도 불가 {diag['hardSkippedByRetryable'].get('nonRetryable', 0)}건은 "
                f"승인 채널이 필요하다")
        _abort(f"아직 담당분을 마치지 않은 샤드 {len(incomplete)}개 {incomplete} — {hint}",
               diag, diag_path)

    rows = []
    for p in shard_files:
        rows.extend(load_jsonl(p))
    diag["shardFiles"] = [os.path.basename(p) for p in shard_files]
    diag["shardCount"] = len(shard_files)
    diag["rowCount"] = len(rows)
    print(f"[1/3] 샤드 {len(shard_files)}개 병합 — {len(rows)}레코드")

    if not rows:
        _abort("병합 결과 0레코드", diag, diag_path)

    for p in shard_files:
        d = f"{SHARD_DIR}/_diagnostics-{os.path.basename(p).replace('.jsonl','')}.json"
        if os.path.exists(d) and load_json(d).get("smokeTest"):
            diag["smokeTest"] = True

    corps = target_corps()
    diag["fiscalYearFrom"] = pol["fiscalYearFrom"]
    diag["fiscalYearTo"] = pol["fiscalYearTo"]
    now = datetime.now(KST)
    expected_to = now.year - 1 if now.month >= 4 else now.year - 2
    diag["fiscalYearToExpectedByRule"] = expected_to
    cw = diag["collectionWindow"]
    print(f"[2/3] 사업연도 {pol['fiscalYearFrom']}~{pol['fiscalYearTo']} · "
          f"대상 법인 {len(corps)} · 수집 창 {cw['from']}~{cw['to']} ({cw['runDays']}일)")
    if cw["runDays"] > 1:
        print("  ..    수집이 하루를 넘었다 — 혼합 시점 스냅샷이다. PIT는 유지되지만"
              " 재수집 시 정정공시로 바이트가 달라질 수 있다")

    rows = validate(rows, corps, pol, diag)
    # 규칙 대조는 인수 조건 뒤에 둔다. 값을 박은 이유(재현성)와 낡음을 알리는 수단(WARN)이
    # 다른 층이라, 이것이 FAIL이면 해가 바뀔 때마다 파이프라인이 멈춘다.
    warn(pol["fiscalYearTo"] >= expected_to,
         f"fiscalYearTo {pol['fiscalYearTo']} >= 규칙상 최신 사업연도 {expected_to} "
         f"(WARN이면 정책 값을 올릴 때가 됐다는 뜻이다)")
    # 실제 공백에 대응하지 않는 승인. FAIL이 아닌 이유는 정당한 경우가 있어서다 —
    # 승인한 법인이 나중에 성공하면 hardSkipped에서 빠지고 승인만 남는다.
    # 다만 그대로 두면 다음 공백을 사람 눈에 안 띄게 덮으므로 정리 신호를 남긴다.
    warn(not diag["declaredNotInHardSkipped"],
         f"실제 공백에 대응하지 않는 승인 {len(diag['declaredNotInHardSkipped'])}건 "
         f"{diag['declaredNotInHardSkipped']} — 오래된 승인이 미래의 공백을 미리 덮는다")

    os.makedirs(OUT_DIR, exist_ok=True)
    diag["acceptanceFails"] = list(fails)
    diag["acceptanceWarns"] = list(warns)
    diag["acceptancePassed"] = not fails
    with open(diag_path, "w", encoding="utf-8", newline="\n") as f:
        json.dump(diag, f, ensure_ascii=False, indent=2)

    if warns:
        print(f"\nWARN {len(warns)}건 (실패 아님, 확인 필요):")
        for w in warns:
            print(f"  - {w}")

    # 인수 조건 실패 시 산출물을 쓰지 않는다(교훈43).
    if fails:
        print(f"\n인수 조건 {len(fails)}건 실패 — 산출물을 쓰지 않는다")
        for x in fails:
            print(f"  - {x}")
        return 1

    print("\n[3/3] 사업연도 분할 · gzip")
    fields = pol["output"]["fields"]
    rows.sort(key=lambda r: (r["fiscalYear"], r["corp"], r["availableFrom"]))
    by_year = defaultdict(list)
    for r in rows:
        by_year[r["fiscalYear"]].append(r)

    # 이전 실행의 잔재를 남기지 않는다 — 대상이 줄면 빈 연도 파일이 남아
    # 디렉터리 해시가 사실과 달라진다.
    for old in glob.glob(f"{OUT_DIR}/*.jsonl.gz"):
        os.remove(old)

    years = {}
    for y in sorted(by_year):
        raw, gz = write_gz(f"{OUT_DIR}/{y}.jsonl.gz", by_year[y], pol, fields)
        years[str(y)] = {"records": len(by_year[y]), "rawBytes": raw, "gzBytes": gz}
        print(f"  {y}.jsonl.gz  {len(by_year[y]):>6}레코드  "
              f"{raw/1e6:6.2f}MB → {gz/1e6:5.2f}MB")
    diag["years"] = years
    diag["totalGzBytes"] = sum(v["gzBytes"] for v in years.values())

    with open(diag_path, "w", encoding="utf-8", newline="\n") as f:
        json.dump(diag, f, ensure_ascii=False, indent=2)

    print(f"\n{OUT_DIR} — 사업연도 {len(years)}개 · {len(rows)}레코드 · "
          f"{diag['totalGzBytes']/1e6:.1f}MB")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--shard", type=int)
    ap.add_argument("--shards", type=int)
    ap.add_argument("--finalize", action="store_true")
    ap.add_argument("--summary", action="store_true",
                    help="샤드 상태에서 진행을 요약한다(읽기 전용). 워크플로가 쓴다")
    ap.add_argument("--limit", type=int, default=0,
                    help="스모크 테스트용. 진단에 smokeTest 플래그가 박히고 CI가 거부한다")
    args = ap.parse_args()

    if not os.path.exists(POLICY):
        print(f"{POLICY} 없음 — FN-1.0 정책 파일이 필요하다")
        return 1
    pol = load_json(POLICY)
    for p in (A1A, A1B):
        if not os.path.exists(p):
            print(f"{p} 없음 — 상류 단계(A1a·A1b)를 먼저 실행하라")
            return 1

    if args.summary:
        return run_summary()
    if args.finalize:
        return run_finalize(pol)
    if args.shard is None:
        print("--shard N --shards M 또는 --finalize 중 하나가 필요하다")
        return 1
    shards = args.shards or pol["shards"]
    if not (0 <= args.shard < shards):
        print(f"--shard는 0 이상 {shards} 미만이어야 한다")
        return 1
    return run_shard(args.shard, shards, pol, args.limit)


if __name__ == "__main__":
    raise SystemExit(main())
