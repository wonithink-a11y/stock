"""collect-minute-kis.py — 분봉 Collector v1 (KIS 주식일별분봉조회)

계약: docs/MN-1.0-분봉Raw저장계약.md · 정책: config/policies/minute.v1.json

v1의 범위는 '메커니즘'이다. 정책 값은 policy의 pendingT1 블록에 격리되어 있고
T1(§6.1) 뒤에 승격한다. 메커니즘과 정책을 분리하는 이유는 되돌릴 수 있는 쪽과
없는 쪽이 다르기 때문이다 — 정책은 나중에 고치면 되고, 못 받은 하루는 못 고친다.

들어 있는 것
    요청일자 게이트(P0) · rt_cd 검사 · EGW00201 재시도 · exponential backoff
    resume · manifest · gapReason 분류 · parquet writer · 스키마 검증 · 인수 조건

들어 있지 않은 것
    빈 응답 재시도 횟수의 확정  · 거래정지 재수집 여부 · 최종 rate limit 정책
    이 셋은 T1 결과가 있어야 정할 수 있다. pendingT1에 보수적 기본값으로 있다.

두 축을 섞지 않는다
    gapReason     왜 시장 데이터가 없는가  (HALT · PRE_LIST · HOLIDAY · EMPTY ...)
    failureClass  왜 수집이 실패했는가      (RATE_LIMIT · NETWORK · DATE_MISMATCH ...)
    섞으면 일시적 장애가 영구 결손으로 기록되고, 재수집 없이는 되돌릴 수 없다.

네트워크는 transport 하나로만 나간다. 테스트는 그것을 갈아끼워 실호출 없이 돈다.

사용:
    python scripts/collect-minute-kis.py --date 2026-08-03 --tickers 005930,000660
    python scripts/collect-minute-kis.py --date 2026-08-03 --universe broad
    python scripts/collect-minute-kis.py --date 2026-08-03 --universe broad --resume
    python scripts/collect-minute-kis.py --selftest      # 네트워크 없이 인수 조건 검증
"""

import argparse
import hashlib
import json
import os
import random
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from pathlib import Path

for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(errors="replace")
    except Exception:
        pass

REPO = Path(__file__).resolve().parent.parent
POLICY_PATH = REPO / "config" / "policies" / "minute.v1.json"
CALENDAR_PATH = REPO / "data" / "backfill" / "calendar.json"
KST = timezone(timedelta(hours=9))
BASE = "https://openapi.koreainvestment.com:9443"
PATH_MIN = "/uapi/domestic-stock/v1/quotations/inquire-time-dailychartprice"

SCHEMA = ["ticker", "ts", "open", "high", "low", "close", "volume"]


# ---------------------------------------------------------------- 기본

def now_kst():
    return datetime.now(KST)


def stamp():
    return now_kst().strftime("%Y-%m-%dT%H:%M:%S+09:00")


def compact(date):
    return "".join(c for c in str(date) if c.isdigit())


def dashed(yyyymmdd):
    s = compact(yyyymmdd)
    return s[:4] + "-" + s[4:6] + "-" + s[6:8]


def load_policy(path=None):
    return json.loads(Path(path or POLICY_PATH).read_text(encoding="utf-8"))


def sha256_bytes(b):
    return hashlib.sha256(b).hexdigest()


def policy_hash(pol):
    return sha256_bytes(json.dumps(pol, sort_keys=True, ensure_ascii=False)
                        .encode("utf-8"))


# ---------------------------------------------------------------- 결과 타입

class Outcome:
    """한 (ticker, date)의 수집 결과.

    셋 중 하나다. 이 셋을 섞지 않는 것이 이 모듈의 핵심이다.
      OK          캔들을 받았다
      GAP         받을 것이 없다는 사실을 확인했다 (gapReason)
      UNRESOLVED  아직 모른다. 재시도가 소진됐거나 조회하지 않았다 (failureClass)
    """

    def __init__(self, ticker, date, status, rows=None, gap_reason=None,
                 failure_class=None, attempts=0, detail=None):
        self.ticker = ticker
        self.date = date
        self.status = status
        self.rows = rows or []
        self.gap_reason = gap_reason
        self.failure_class = failure_class
        self.attempts = attempts
        self.detail = detail or {}

    def to_state(self):
        d = {"ticker": self.ticker, "status": self.status,
             "attempts": self.attempts}
        if self.status == "OK":
            d["rows"] = len(self.rows)
        if self.gap_reason:
            d["gapReason"] = self.gap_reason
        if self.failure_class:
            d["failureClass"] = self.failure_class
        if self.detail:
            d["detail"] = self.detail
        return d


# ---------------------------------------------------------------- transport

class KisTransport:
    """실제 KIS 호출. 이 클래스만 네트워크를 안다.

    테스트는 이것과 같은 fetch() 시그니처를 가진 가짜를 넣는다.
    """

    def __init__(self, app_key, app_secret, token, base=BASE):
        self.app_key = app_key
        self.app_secret = app_secret
        self.token = token
        self.base = base

    def fetch(self, ticker, sent_date, hour, pol):
        import requests
        cc = pol["collectionContract"]
        try:
            r = requests.get(
                self.base + PATH_MIN,
                headers={"content-type": "application/json",
                         "authorization": "Bearer " + self.token,
                         "appkey": self.app_key, "appsecret": self.app_secret,
                         "tr_id": pol["trId"], "custtype": "P"},
                params={"FID_COND_MRKT_DIV_CODE": cc["marketDivCode"],
                        "FID_INPUT_ISCD": ticker,
                        "FID_INPUT_HOUR_1": hour,
                        "FID_INPUT_DATE_1": sent_date,
                        "FID_PW_DATA_INCU_YN": cc["pastDataFlag"],
                        "FID_FAKE_TICK_INCU_YN": cc["fakeTickFlag"]},
                timeout=20)
        except Exception as e:
            return {"transportError": type(e).__name__}
        out = {"http": r.status_code}
        try:
            out["body"] = r.json()
        except Exception:
            out["bodyNotJson"] = True
        return out


# ---------------------------------------------------------------- 분류

def classify_response(resp, sent_date, pol):
    """응답 하나를 (kind, failure_class) 로 가른다.

    kind: OK · EMPTY · DATE_MISMATCH · FAIL
    성공 판정은 rt_cd만으로 하지 않는다(교훈81).
    """
    gate = pol["successGate"]

    if resp.get("transportError"):
        return "FAIL", "NETWORK"
    if resp.get("bodyNotJson"):
        return "FAIL", "HTTP_ERROR"

    http = resp.get("http")
    if http is not None and http != 200:
        return "FAIL", "HTTP_ERROR"

    body = resp.get("body") or {}
    msg_cd = str(body.get("msg_cd") or "")
    if msg_cd in pol["retry"]["retryableMsgCodes"]:
        return "FAIL", "RATE_LIMIT"

    if str(body.get("rt_cd")) != gate["requireRtCd"]:
        return "FAIL", "API_ERROR"

    out2 = body.get("output2") or []
    if not out2:
        return "EMPTY", None

    if gate["requireRequestedDateInResponse"]:
        dates = {str(r.get("stck_bsop_date")) for r in out2}
        if sent_date not in dates:
            # 오류가 아니라 '그 날짜에 데이터가 없다'는 증거다.
            return "DATE_MISMATCH", "DATE_MISMATCH"

    return "OK", None


def calendar_covers(date, ctx):
    """캘린더가 이 날짜에 대해 말할 자격이 있는가.

    캘린더는 A0.5가 만들고 매일 갱신되지 않는다. 커버 범위 밖의 날짜를
    '거래일 목록에 없다'는 이유로 휴장이라 부르면, 캘린더가 하루 낡을 때마다
    그날의 모든 결손이 HOLIDAY로 굳는다 - 재수집으로도 되돌릴 수 없는
    거짓이다(교훈57·75). 모르는 것은 '휴장'이 아니라 '모른다'이다.
    """
    tds = ctx.get("tradingDays") or set()
    if not tds:
        return False
    lo = ctx.get("calendarFrom") or min(tds)
    hi = ctx.get("calendarTo") or max(tds)
    return lo <= date <= hi


def resolve_gap_reason(kind, ticker, date, ctx):
    """결손의 사유를 확정한다. 응답을 본 자리에서 남긴다(교훈75).

    ctx: {"tradingDays": set, "calendarFrom": str, "calendarTo": str,
          "listedAt": {ticker: 'YYYY-MM-DD'}, "delistedAt": {...}}
    """
    if calendar_covers(date, ctx) and date not in ctx["tradingDays"]:
        return "HOLIDAY"
    listed = (ctx.get("listedAt") or {}).get(ticker)
    if listed and date < listed:
        return "PRE_LIST"
    delisted = (ctx.get("delistedAt") or {}).get(ticker)
    if delisted and date >= delisted:
        return "DELISTED"
    if kind == "DATE_MISMATCH":
        # 상장 중이고 영업일인데 그 날짜가 없다 = 거래정지가 가장 그럴듯하다.
        # 단정하지 않고 라벨만 남긴다 - 확정은 상장/정지 원장이 생긴 뒤다.
        return "HALT"
    return "EMPTY"


def day_verdict(date, outcomes, ctx):
    """그날 장이 섰는가. 이것은 종목 하나로는 잴 수 없다(교훈73).

    개별 응답은 '이 종목의 그날이 없다'까지만 말한다. 그런데 2,559개가
    동시에 거래정지일 수는 없으므로, 전부 비었다는 사실 자체가 휴장의
    증거다 - 병합 범위에서만 나오는 정보다.

    캘린더가 그 날짜를 덮으면 캘린더가 진실이다. 덮지 못할 때만 추론한다.
    """
    if calendar_covers(date, ctx):
        return (("TRADING_CONFIRMED" if date in ctx["tradingDays"]
                 else "CLOSED_CONFIRMED"), "calendar")
    if any(o.status == "OK" for o in outcomes):
        return "TRADING_OBSERVED", "rows"
    if any(o.status == "UNRESOLVED" for o in outcomes):
        # 못 받은 것이 있는데 '없다'고 단정하지 않는다. 장애와 휴장은 다르다.
        return "UNKNOWN", "unresolved"
    if not [o for o in outcomes if o.gap_reason != "NOT_QUERIED"]:
        return "UNKNOWN", "not-queried"
    return "CLOSED_INFERRED", "all-empty"


def probe_market_open(transport, tickers, date, pol, ctx, sleeper=time.sleep):
    """장이 섰는지 소수 종목으로 먼저 묻는다.

    휴장일에 Broad 전체를 도는 것은 약 9,200호출을 버리는 일이다. 유동성
    상위 몇 개만 먼저 물어 하나라도 캔들이 오면 전체를 돈다.

    하나라도 OK면 즉시 멈춘다 - 장이 섰다는 사실은 한 종목으로 충분하다.
    반대로 '전부 비었다'는 여러 개를 봐야 한다. 한 종목의 거래정지와
    휴장을 구분하지 못하기 때문이다.
    """
    outs = []
    for t in tickers:
        o = collect_symbol_day(transport, t, date, pol, ctx, sleeper=sleeper)
        outs.append(o)
        if o.status == "OK":
            break
    return outs


# ---------------------------------------------------------------- 수집

def collect_symbol_day(transport, ticker, date, pol, ctx, sleeper=time.sleep,
                       rnd=random.random):
    """한 종목의 하루. 커서를 돌려 전량을 모은다.

    재시도는 '메커니즘'이라 여기 있고, 몇 번 돌지는 policy가 정한다.
    """
    cc = pol["collectionContract"]
    rt = pol["retry"]
    sent = compact(date)
    cursor = cc["cursorSeed"]
    seen = {}
    attempts = 0
    pages = 0

    while pages < 12:
        kind = fclass = None
        for attempt in range(1, rt["maxAttempts"] + 1):
            attempts += 1
            resp = transport.fetch(ticker, sent, cursor, pol)
            kind, fclass = classify_response(resp, sent, pol)
            if kind != "FAIL":
                break
            retryable = (
                (fclass == "RATE_LIMIT")
                or (fclass == "NETWORK" and rt["retryOnTransport"])
                or (fclass == "HTTP_ERROR" and rt["retryOnHttp5xx"])
                or (fclass == "API_ERROR" and rt["defaultUnknownRetryable"])
            )
            if not retryable or attempt >= rt["maxAttempts"]:
                break
            delay = min(rt["backoffBaseSeconds"] * (2 ** (attempt - 1)),
                        rt["backoffMaxSeconds"])
            delay *= 1.0 + rt["jitterRatio"] * (rnd() * 2 - 1)
            sleeper(max(0.0, delay))

        if kind == "FAIL":
            if seen:
                # 일부는 받았다. 부분 성공을 성공으로 쓰지 않는다 -
                # 하루가 온전하지 않으면 미해결이다.
                return Outcome(ticker, date, "UNRESOLVED", attempts=attempts,
                               failure_class=fclass,
                               detail={"partialRows": len(seen), "pages": pages})
            return Outcome(ticker, date, "UNRESOLVED", attempts=attempts,
                           failure_class=fclass)

        if kind in ("EMPTY", "DATE_MISMATCH"):
            if seen:
                break            # 앞 페이지까지가 그 날의 전부다
            reason = resolve_gap_reason(kind, ticker, date, ctx)
            return Outcome(ticker, date, "GAP", gap_reason=reason,
                           attempts=attempts,
                           failure_class=("DATE_MISMATCH"
                                          if kind == "DATE_MISMATCH" else None))

        body = None
        # kind == OK
        resp_body = resp.get("body") or {}
        body = [r for r in (resp_body.get("output2") or [])
                if str(r.get("stck_bsop_date")) == sent]
        pages += 1
        new = 0
        for r in body:
            h = str(r.get("stck_cntg_hour"))
            if h not in seen:
                seen[h] = r
                new += 1
        if not body:
            break
        mn = min(str(r.get("stck_cntg_hour")) for r in body)
        if new == 0 or mn == cursor:
            break
        cursor = mn

    if not seen:
        return Outcome(ticker, date, "GAP",
                       gap_reason=resolve_gap_reason("EMPTY", ticker, date, ctx),
                       attempts=attempts)

    rows = []
    d = dashed(date)
    for h in sorted(seen):
        r = seen[h]
        rows.append({
            "ticker": ticker,
            "ts": d + "T" + h[:2] + ":" + h[2:4] + "+09:00",
            "open": int(r["stck_oprc"]), "high": int(r["stck_hgpr"]),
            "low": int(r["stck_lwpr"]), "close": int(r["stck_prpr"]),
            "volume": int(r.get("cntg_vol", 0)),
        })
    return Outcome(ticker, date, "OK", rows=rows, attempts=attempts)


# ---------------------------------------------------------------- 검증

def validate_rows(rows, date, pol):
    """스키마·중복·일자·OHLC를 본다. 위반을 말하고 복구는 말하지 않는다(교훈74).

    (위반, 관측)을 돌려준다.

    OHLC 불변식을 셋으로 가른 이유는 개수가 원인을 지목하지 못하기
    때문이다(교훈67). 'ohlcInconsistent' 하나로는 low>high(진짜 손상)와
    09:00의 open(소스의 표기 방식)이 같은 칸에 들어간다. 둘은 대응이 전혀
    다르다 - 하나는 수집을 멈출 일이고 하나는 세어 두기만 할 일이다.

    관측은 계약이 면제한 것을 그래도 센 것이다. 면제는 눈감는 것이 아니다.
    """
    val = pol.get("validation") or {}
    exempt = set(val.get("openWithinRangeExemptMinutes") or [])
    v, obs = [], {}
    d = dashed(date)
    keys = set()
    for i, r in enumerate(rows):
        if list(r.keys()) != SCHEMA:
            v.append({"row": i, "why": "schemaMismatch", "got": list(r.keys())})
            continue
        if not str(r["ts"]).startswith(d):
            v.append({"row": i, "why": "dateMismatch", "ts": r["ts"]})
        k = (r["ticker"], r["ts"])
        if k in keys:
            v.append({"row": i, "why": "duplicateKey", "key": list(k)})
        keys.add(k)

        if val.get("requireLowLeHigh", True) and r["low"] > r["high"]:
            v.append({"row": i, "why": "lowAboveHigh", "key": list(k)})
        if (val.get("requireCloseWithinRange", True)
                and not (r["low"] <= r["close"] <= r["high"])):
            v.append({"row": i, "why": "closeOutOfRange", "key": list(k)})
        if not (r["low"] <= r["open"] <= r["high"]):
            # 09:00의 open은 시가단일가 체결가라 그 1분의 체결 범위 밖일 수
            # 있다. 소스가 약속하지 않은 것을 위반으로 세지 않는다.
            if str(r["ts"])[11:16] in exempt:
                obs["openOutOfRangeAtSessionOpen"] = (
                    obs.get("openOutOfRangeAtSessionOpen", 0) + 1)
            elif val.get("requireOpenWithinRange", True):
                v.append({"row": i, "why": "openOutOfRange", "key": list(k)})
        if r["volume"] < 0:
            v.append({"row": i, "why": "negativeVolume", "key": list(k)})
    return v, obs


def acceptance(outcomes, row_count, violations, date, pol):
    """하루치가 인수 조건을 통과했는가. 실패면 parquet를 쓰지 않는다.

    행을 통째로 받지 않는다 - 배치마다 검증한 위반만 누적해 넘긴다.
    검사를 추가하기 전에 그 검사가 어느 범위에서 잴 수 있는지 먼저 정한다(교훈73).
    """
    acc = pol["acceptance"]
    n = len(outcomes)
    unresolved = [o for o in outcomes if o.status == "UNRESOLVED"]
    checks = []

    def add(name, passed, detail):
        checks.append({"항목": name, "통과": bool(passed), "실측": detail})

    rate = (len(unresolved) / n) if n else 0.0
    add("미해결 비율 상한", rate <= acc["maxUnresolvedRate"],
        {"미해결": len(unresolved), "전체": n, "비율": round(rate, 4),
         "상한": acc["maxUnresolvedRate"]})

    add("스키마·중복·일자·OHLC 위반 0", len(violations) == 0,
        {"위반": len(violations), "샘플": violations[:3]})

    unknown_gap = [o.gap_reason for o in outcomes
                   if o.status == "GAP"
                   and o.gap_reason not in pol["gapReason"]["values"]]
    add("gapReason이 계약 안의 값", not unknown_gap, {"미등록": unknown_gap[:5]})

    add("행이 있거나 전부 결손으로 설명된다",
        row_count > 0 or all(o.status != "OK" for o in outcomes),
        {"행": row_count})

    return checks, all(c["통과"] for c in checks)


# ---------------------------------------------------------------- 저장

def write_parquet(rows, date, out_root, part=0, subdir=None):
    """한 조각을 쓴다. pyarrow가 없으면 알린다.

    하루치를 한 번에 쓰지 않는 이유는 메모리다. Broad 하루 562,974행을
    다 모으면 피크 RSS 389MB로 1GB VM에서 기존 모니터와 공존하지 못한다.
    §3의 레이아웃이 part-*.parquet인 것은 이것을 전제한 것이다.
    """
    try:
        import pyarrow as pa
        import pyarrow.parquet as pq
    except ImportError:
        return None, "pyarrow 없음 — Collector 착수 전 설치한다(MN-1.0 §1.1)"

    d = dashed(date)
    out_dir = Path(out_root) / ("date=" + d)
    if subdir:
        out_dir = out_dir / subdir
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / ("part-%03d.parquet" % part)
    table = pa.table({k: [r[k] for r in rows] for k in SCHEMA})
    pq.write_table(table, path, compression="zstd")
    return path, None


def next_part_index(stage_dir):
    """스테이징에 이미 있는 조각 다음 번호. 이름이 겹치면 앞 조각을 덮는다."""
    top = -1
    if Path(stage_dir).exists():
        for f in Path(stage_dir).glob("part-*.parquet"):
            try:
                top = max(top, int(f.stem.split("-")[1]))
            except (IndexError, ValueError):
                pass
    return top + 1


def adopt_staged_parts(stage_dir):
    """앞 실행이 남긴 스테이징 조각을 이 실행의 것으로 이어받는다.

    행 수는 파일에서 다시 읽는다. 상태 파일이 들고 있는 종목별 행 수를
    합치지 않는 이유는, 그것이 '받았다고 기록한 수'이지 '파일에 있는 수'가
    아니기 때문이다 - 두 개가 갈리는 순간을 manifest가 잡아야 한다.
    """
    try:
        import pyarrow.parquet as pq
    except ImportError:
        return []
    out = []
    for f in sorted(Path(stage_dir).glob("part-*.parquet")):
        try:
            n = pq.ParquetFile(str(f)).metadata.num_rows
        except Exception:
            continue
        out.append({"name": f.name, "rows": n,
                    "sha256": sha256_bytes(f.read_bytes())})
    return out


def combined_sha(parts):
    """조각들의 결합 해시. 이름으로 정렬해 순서를 고정한다.

    조각이 하나뿐이어도 같은 식을 쓴다 - 조각 수에 따라 식이 달라지면
    나중에 둘을 비교할 수 없다.
    """
    body = "\n".join(p["name"] + " " + p["sha256"]
                     for p in sorted(parts, key=lambda x: x["name"]))
    return sha256_bytes(body.encode("utf-8"))


def build_manifest(date, outcomes, row_count, pol, sha, checks, passed,
                   raw_path, run, parts=None):
    gaps = {}
    for o in outcomes:
        if o.status == "GAP":
            gaps[o.gap_reason] = gaps.get(o.gap_reason, 0) + 1
    unresolved = {}
    for o in outcomes:
        if o.status == "UNRESOLVED":
            unresolved[o.failure_class] = unresolved.get(o.failure_class, 0) + 1
    return {
        "schemaVersion": "MN-1.0",
        "date": dashed(date),
        "rows": row_count,
        "symbols": len(outcomes),
        "sha256": sha,
        "shaMethod": "combined: sha256 of sorted 'name sha' lines",
        "parts": parts or [],
        "rawPath": str(raw_path) if raw_path else None,
        "source": pol["source"],
        "endpoint": pol["endpoint"],
        "adjusted": pol["adjusted"],
        "market": pol["market"],
        "requestedAt": stamp(),
        "createdAt": stamp(),
        "policyVersion": pol["version"],
        "policyHash": policy_hash(pol),
        "gapReasons": gaps,
        "unresolved": unresolved,
        "acceptance": checks,
        "acceptancePassed": passed,
        "execution": {
            "runId": run.get("runId"),
            "runAttempt": run.get("runAttempt"),
            "workflow": run.get("workflow"),
            "host": run.get("host"),
        },
    }


# ---------------------------------------------------------------- resume

def state_path(root, date):
    return Path(root) / ("state-" + dashed(date) + ".json")


def load_state(root, date, pol):
    p = state_path(root, date)
    if not p.exists():
        return None
    st = json.loads(p.read_text(encoding="utf-8"))
    # 재개 호환의 기준은 '이 값이 달랐다면 어제 다른 레코드가 나왔는가'뿐이다.
    # 정책 version 문자열이 아니라 collectionContract 해시를 본다(교훈55).
    mine = sha256_bytes(json.dumps(pol["collectionContract"], sort_keys=True,
                                   ensure_ascii=False).encode("utf-8"))
    if st.get("contractHash") != mine:
        return {"incompatible": True, "storedHash": st.get("contractHash"),
                "currentHash": mine}
    return st


def save_state(root, date, pol, done):
    p = state_path(root, date)
    p.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "date": dashed(date),
        "contractHash": sha256_bytes(
            json.dumps(pol["collectionContract"], sort_keys=True,
                       ensure_ascii=False).encode("utf-8")),
        "updatedAt": stamp(),
        "symbols": done,
    }
    # Path.write_text(newline=)은 3.10부터다. VM은 3.8이라 open으로 쓴다.
    with open(p, "w", encoding="utf-8", newline="\n") as f:
        f.write(json.dumps(payload, ensure_ascii=False, indent=2))


# ---------------------------------------------------------------- 실행

def is_resolved(rec):
    """이 종목의 그날이 끝났는가. NOT_QUERIED는 끝난 것이 아니다.

    '조회하지 않았다'를 GAP이라는 이유로 완료로 세면, 휴장 추론으로
    건너뛴 종목이 다음 재개에서 영영 조회되지 않는다. §2.1이 EMPTY와
    NOT_QUERIED의 경계를 지우지 말라고 한 것이 이 자리다.
    """
    return (rec.get("status") in ("OK", "GAP")
            and rec.get("gapReason") != "NOT_QUERIED")


def run_day(transport, tickers, date, pol, ctx, out_root, state_root,
            resume=False, run=None, sleeper=time.sleep, progress=None,
            keep_rows=True, not_queried=()):
    run = run or {}
    done = {}
    if resume:
        st = load_state(state_root, date, pol)
        if st and st.get("incompatible"):
            raise SystemExit("resume 불가: collectionContract가 바뀌었다. "
                             "이미 모은 것을 다시 쓸 수 없다")
        if st:
            done = st.get("symbols") or {}

    todo = sorted(t for t in tickers if not is_resolved(done.get(t, {})))

    outcomes = []
    for t in sorted(tickers):
        prev = done.get(t)
        if prev and is_resolved(prev):
            outcomes.append(Outcome(t, date, prev["status"],
                                    gap_reason=prev.get("gapReason"),
                                    attempts=prev.get("attempts", 0),
                                    detail={"fromState": True}))

    # 조회하지 않기로 한 종목. 호출하지 않았다는 사실을 그 자리에서 남긴다 -
    # 없는 행은 이유를 말하지 않는다(교훈75).
    for t in sorted(set(not_queried) - set(tickers)):
        o = Outcome(t, date, "GAP", gap_reason="NOT_QUERIED")
        done[t] = o.to_state()
        outcomes.append(o)

    # --- 수집하면서 흘려보낸다 ---------------------------------------------
    # 다 모은 뒤에 배치를 나누면 소용이 없다. Outcome이 이미 전부 들고 있기
    # 때문이다 - 실측으로 배치를 넣고도 피크가 389MB에서 371MB로만 내려갔다.
    # 행은 버퍼로 옮기고 Outcome에서 즉시 버린다.
    # 인수 조건 통과 전에는 최종 경로에 두지 않으므로 스테이징에 쓴다(교훈43).
    batch_n = pol["output"].get("flushEverySymbols", 200)
    staging = pol["output"].get("stagingDirName", "_staging")
    part_dir = Path(out_root) / ("date=" + dashed(date))
    stage_dir = part_dir / staging

    # 앞 실행이 스테이징에 남긴 조각을 이어받는다.
    # resume은 state가 완료로 아는 종목을 다시 부르지 않는다. 그러므로 그
    # 종목들의 행은 스테이징에만 있고, 여기서 지우면 영영 사라진다 -
    # 인수 조건에 걸린 하루는 '틀린 데이터'가 아니라 '아직 덜 모은 하루'다.
    carried = []
    if stage_dir.exists():
        if resume:
            carried = adopt_staged_parts(stage_dir)
        else:
            for f in stage_dir.glob("part-*.parquet"):
                f.unlink()

    parts, violations, observations = list(carried), [], {}
    row_count = sum(p["rows"] for p in carried)
    err = None
    keep = [] if keep_rows else None
    buf, part_i, since = [], next_part_index(stage_dir), 0

    def flush():
        nonlocal buf, part_i, row_count, err
        if not buf:
            return
        buf.sort(key=lambda r: (r["ticker"], r["ts"]))
        # 검증은 항상 돌린다. 상한은 '보관하는 표본'에만 건다 - 검증 자체를
        # 건너뛰면 관측치가 20건 이후로 조용히 멈춘다.
        vv, oo = validate_rows(buf, date, pol)
        if len(violations) < 20:
            violations.extend(vv[:20])
        for ok_, on_ in oo.items():
            observations[ok_] = observations.get(ok_, 0) + on_
        row_count += len(buf)
        pth, e = write_parquet(buf, date, out_root, part=part_i,
                               subdir=staging)
        if e:
            err = e
        else:
            parts.append({"name": pth.name, "rows": len(buf),
                          "sha256": sha256_bytes(pth.read_bytes())})
        part_i += 1
        buf = []

    def absorb(o):
        nonlocal since
        if o.rows:
            buf.extend(o.rows)
            if keep is not None:
                keep.extend(o.rows)
            o.rows = []          # 여기서 버리지 않으면 배치가 의미가 없다
        done[o.ticker] = o.to_state()
        outcomes.append(o)
        since += 1
        if since >= batch_n:
            flush()
            since = 0

    # 청크 단위로 제출한다. ThreadPoolExecutor.map은 전량을 즉시 제출하고
    # future가 결과를 쥐고 있어, 행을 버려도 피크가 안 내려간다 -
    # 실측으로 388.7 → 371.4 → 374.6으로 제자리였다.
    # 줄여야 하는 것은 '들고 있는 행'이 아니라 '인플라이트 작업'이다.
    conc = pol["concurrency"]["initial"]
    seen = 0
    if todo:
        with ThreadPoolExecutor(max_workers=max(1, conc)) as ex:
            for i in range(0, len(todo), batch_n):
                chunk = todo[i:i + batch_n]
                for o in ex.map(lambda t: collect_symbol_day(
                        transport, t, date, pol, ctx, sleeper=sleeper), chunk):
                    absorb(o)
                    seen += 1
                if progress:
                    progress(seen, len(todo))
    flush()

    # --- 날짜 단위 판정 -----------------------------------------------------
    # 여기서만 잴 수 있다. 개별 종목은 자기 결손밖에 모른다(교훈73).
    verdict, verdict_by = day_verdict(date, outcomes, ctx)
    if verdict == "CLOSED_INFERRED":
        # 휴장이 확정되면 개별 라벨의 HALT/EMPTY는 그 사유가 아니었다.
        # 원 사실(DATE_MISMATCH)은 failureClass에 그대로 남는다 - 지우지 않는다.
        for o in outcomes:
            if o.status == "GAP" and o.gap_reason in ("HALT", "EMPTY"):
                o.gap_reason = "HOLIDAY"
                done[o.ticker] = o.to_state()

    # resume 상태는 쓰는 시점에 강제한다. 읽는 시점의 발견보다 안전하다(교훈73).
    save_state(state_root, date, pol, done)

    checks, passed = acceptance(outcomes, row_count, violations, date, pol)

    raw_path = None
    if passed and parts and not err:
        # 스테이징을 최종 위치로 올린다.
        for p in list(stage_dir.glob("part-*.parquet")):
            p.replace(part_dir / p.name)
        try:
            stage_dir.rmdir()
        except OSError:
            pass
        raw_path = part_dir
    else:
        # 스테이징을 지우지 않는다. 다음 resume이 이어받는다 - state는 이미
        # 그 종목들을 완료로 알고 있어 다시 부르지 않으므로, 여기서 지우면
        # 그 행들은 재수집으로도 돌아오지 않는다.
        parts = [] if not passed else parts

    sha = combined_sha(parts) if (passed and parts and not err) else None
    man = build_manifest(date, outcomes, row_count, pol, sha, checks, passed,
                         raw_path, run, parts=parts if raw_path else [])
    man["dayVerdict"] = verdict
    man["dayVerdictBasis"] = verdict_by
    man["calendarCovered"] = calendar_covers(date, ctx)
    man["symbolsWithRows"] = sum(1 for o in outcomes if o.status == "OK")
    man["symbolsNotQueried"] = sum(1 for o in outcomes
                                   if o.gap_reason == "NOT_QUERIED")
    man["observations"] = observations
    man["observationsNote"] = ("이 실행이 검증한 행에 대한 수치다. 재개된 날은 "
                               "이월 조각을 다시 검증하지 않으므로 앞 실행의 "
                               "_failed manifest가 나머지를 들고 있다.")
    if err:
        man["writerError"] = err
    return {"outcomes": outcomes, "rows": keep, "rowCount": row_count,
            "manifest": man, "acceptancePassed": passed, "writerError": err,
            "dayVerdict": verdict}


def load_context():
    ctx = {"tradingDays": set(), "listedAt": {}, "delistedAt": {},
           "calendarFrom": None, "calendarTo": None}
    if CALENDAR_PATH.exists():
        try:
            cal = json.loads(CALENDAR_PATH.read_text(encoding="utf-8"))
            ctx["tradingDays"] = set(cal["tradingDays"])
            # 캘린더가 어디까지 말할 수 있는지를 함께 들고 다닌다.
            # 이것이 없으면 범위 밖 날짜를 휴장으로 오독한다.
            ctx["calendarFrom"] = cal.get("from") or min(ctx["tradingDays"])
            ctx["calendarTo"] = cal.get("to") or max(ctx["tradingDays"])
        except Exception:
            pass
    for r in read_a1a():
        if r.get("listedAt"):
            ctx["listedAt"][r["ticker"]] = r["listedAt"]
    return ctx


# ---------------------------------------------------------------- 실행 환경
#
# 경로·키·토큰은 여기 모은다. 하드코딩하지 않는다(VM 운영 기준 8) -
# VM은 코드(~/collector)와 자격증명(~/collector-venv)을 다른 곳에 둔다.

A1A_PATH = REPO / "data" / "backfill" / "universe" / "a1a" / "current.jsonl"

# 휴장 정찰용 기본 표본. 유동성 상위이고 상장 이력이 길어 정지 확률이 낮다.
# 유니버스 스냅샷이 있으면 그쪽 상위를 쓰고, 이것은 폴백이다.
PROBE_FALLBACK = ["005930", "000660", "035420"]


def read_a1a():
    if not A1A_PATH.exists():
        return []
    out = []
    for line in A1A_PATH.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            out.append(json.loads(line))
        except Exception:
            pass
    return out


def broad_tickers(date=None):
    """Broad = 전체 상장. 유니버스 스냅샷을 수집 필터로 쓰지 않는다.

    스냅샷은 거래대금 창(60거래일)을 채운 종목만 담는다 - 신규상장은
    20거래일이 쌓일 때까지 빠지고, 그 20일치는 나중에 받을 수 없다.
    §6.3의 '유니버스로 Raw를 거르지 않는다'가 정확히 이 자리를 말한 것이다.
    """
    out = []
    for r in read_a1a():
        tk = r.get("ticker")
        if not tk:
            continue
        if date and r.get("listedAt") and r["listedAt"] > date:
            continue
        out.append(tk)
    return sorted(set(out))


def probe_tickers(candidates, universe_dir=None):
    """정찰 표본. 유니버스 스냅샷의 거래대금 상위에서 고른다."""
    d = Path(universe_dir or (REPO / "data" / "backfill" / "minute" / "universe"))
    pool = set(candidates)
    snaps = sorted(d.glob("*.jsonl")) if d.exists() else []
    if snaps:
        try:
            rows = []
            for line in snaps[-1].read_text(encoding="utf-8").splitlines():
                if line.strip():
                    rows.append(json.loads(line))
            rows.sort(key=lambda r: r.get("turnoverEok") or 0, reverse=True)
            top = [r["ticker"] for r in rows if r["ticker"] in pool][:3]
            if len(top) == 3:
                return top
        except Exception:
            pass
    return [t for t in PROBE_FALLBACK if t in pool][:3]


def load_env_file(path=None):
    p = Path(path or os.environ.get("KIS_ENV_PATH")
             or (REPO / ".env")).expanduser()
    env = {}
    if p.exists():
        for line in p.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            k, _, v = line.partition("=")
            env[k.strip()] = v.strip()
    return env


def credentials():
    env = load_env_file()
    key = os.environ.get("KIS_APP_KEY") or env.get("KIS_APP_KEY")
    sec = os.environ.get("KIS_APP_SECRET") or env.get("KIS_APP_SECRET")
    if not key or not sec:
        raise SystemExit("KIS 키가 없다. scripts/setup-kis-key.py를 먼저 돌린다")
    return key, sec


def token_cache_path():
    return Path(os.environ.get("KIS_TOKEN_CACHE")
                or (REPO / ".token_cache_kis.json")).expanduser()


def _mint_token(key, sec):
    import requests
    r = requests.post(
        BASE + "/oauth2/tokenP",
        data=json.dumps({"grant_type": "client_credentials",
                         "appkey": key, "appsecret": sec}),
        headers={"content-type": "application/json"}, timeout=20)
    b = r.json()
    if r.status_code != 200 or "access_token" not in b:
        raise SystemExit("토큰 발급 실패: http=%s code=%s"
                         % (r.status_code, b.get("error_code", b.get("msg_cd"))))
    return b


def get_token(key, sec, cache=None, mint=None):
    """캐시가 살아 있으면 재사용하고 아니면 발급한다.

    무인 운영에서 이것이 없으면 24시간마다 사람이 붙어야 한다. 반대로
    매번 새로 받으면 발급 한도에 걸리고 같은 앱키를 쓰는 다른 프로세스의
    토큰까지 흔든다 - 만료 10분 전까지는 반드시 재사용한다.
    """
    p = Path(cache or token_cache_path())
    try:
        c = json.loads(p.read_text(encoding="utf-8"))
        exp = datetime.fromisoformat(c["expiresAt"])
        if exp.tzinfo is None:
            exp = exp.replace(tzinfo=KST)
        if (exp - timedelta(minutes=10) > now_kst()
                and c.get("appKeyTail") == key[-4:]):
            return c["accessToken"], "cache"
    except Exception:
        pass

    b = (mint or _mint_token)(key, sec)
    p.parent.mkdir(parents=True, exist_ok=True)
    with open(p, "w", encoding="utf-8", newline="\n") as f:
        f.write(json.dumps({"accessToken": b["access_token"],
                            "expiresAt": b.get("access_token_token_expired", ""),
                            "issuedAt": stamp(), "appKeyTail": key[-4:]},
                           ensure_ascii=False, indent=2))
    try:
        os.chmod(p, 0o600)
    except Exception:
        pass
    return b["access_token"], "minted"


def env_paths(pol=None):
    """Raw는 저장소 밖이다(§1). 기본값은 로컬 진단용이고 VM은 환경변수로 옮긴다."""
    pol = pol or load_policy()
    raw = Path(os.environ.get("MINUTE_RAW_ROOT")
               or (REPO / "data" / "minute")).expanduser()
    state = Path(os.environ.get("MINUTE_STATE_DIR")
                 or (raw / "_state")).expanduser()
    # 정책의 manifestDir은 저장소 상대 경로다. cwd 상대로 읽으면 systemd에서
    # WorkingDirectory에 따라 다른 곳에 쓴다.
    man = Path(os.environ.get("MINUTE_MANIFEST_DIR")
               or (REPO / pol["output"]["manifestDir"])).expanduser()
    return raw, state, man


def write_manifest(man, manifest_dir):
    """manifest는 '인수 조건을 통과했다'는 뜻이다(§5·교훈43).

    실패한 실행을 같은 자리에 쓰면 '파일이 있다'가 '통과했다'로 읽힌다.
    실패는 진단으로 _failed/에 남긴다 - 버리지도 않고 승격하지도 않는다.
    """
    d = Path(manifest_dir)
    if not man.get("acceptancePassed"):
        d = d / "_failed"
        name = man["date"] + "-" + now_kst().strftime("%H%M%S") + ".json"
    else:
        name = man["date"] + ".json"
    d.mkdir(parents=True, exist_ok=True)
    p = d / name
    with open(p, "w", encoding="utf-8", newline="\n") as f:
        f.write(json.dumps(man, ensure_ascii=False, indent=2) + "\n")
    return p


def collect_one_day(date, tickers, pol=None, ctx=None, resume=True,
                    probe=None, transport=None, paths=None, progress=None,
                    source=None):
    """하루치를 수집하고 manifest까지 쓴다. main()과 상시 러너의 공통 경로다.

    probe=True면 소수 종목으로 먼저 묻고, 전부 비면 나머지를 NOT_QUERIED로
    남긴 채 끝낸다. 기본값은 '캘린더가 그 날짜를 못 덮을 때만 정찰'이다 -
    캘린더가 거래일이라고 말하면 물어볼 것이 없다.
    """
    pol = pol or load_policy()
    ctx = ctx if ctx is not None else load_context()
    raw, state, mandir = paths or env_paths(pol)
    if probe is None:
        probe = not calendar_covers(date, ctx)

    if transport is None:
        key, sec = credentials()
        token, how = get_token(key, sec)
        transport = KisTransport(key, sec, token)
    else:
        how = "injected"

    run = {"host": os.environ.get("HOSTNAME")
           or os.environ.get("COMPUTERNAME") or "local",
           "tokenSource": how, "tickerSource": source}

    skipped = ()
    targets = list(tickers)
    if probe and len(tickers) > 8:
        pt = probe_tickers(tickers)
        outs = probe_market_open(transport, pt, date, pol, ctx)
        if pt and all(o.status == "GAP" for o in outs):
            # 전부 비었다. 휴장으로 보고 나머지는 부르지 않는다 -
            # 조회하지 않았다는 사실은 NOT_QUERIED로 남는다.
            targets = pt
            skipped = [t for t in tickers if t not in set(pt)]

    res = run_day(transport, targets, date, pol, ctx, raw, state,
                  resume=resume, run=run, progress=progress,
                  keep_rows=False, not_queried=skipped)
    res["manifestPath"] = str(write_manifest(res["manifest"], mandir))
    return res


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--date")
    ap.add_argument("--tickers", help="쉼표 구분")
    ap.add_argument("--tickers-file", help="한 줄에 하나")
    ap.add_argument("--universe", choices=["broad"],
                    help="broad = 전체 상장 (A1a current.jsonl)")
    ap.add_argument("--resume", action="store_true")
    ap.add_argument("--out")
    ap.add_argument("--state")
    ap.add_argument("--manifest-dir")
    ap.add_argument("--probe", dest="probe", action="store_true", default=None,
                    help="소수 종목으로 휴장 여부를 먼저 확인한다")
    ap.add_argument("--no-probe", dest="probe", action="store_false")
    ap.add_argument("--selftest", action="store_true")
    args = ap.parse_args()

    if args.selftest:
        sys.exit(selftest())

    if not args.date:
        ap.error("--date 가 필요하다 (또는 --selftest)")
    date = dashed(args.date)

    if args.universe == "broad":
        tickers, source = broad_tickers(date), "broad:a1a"
    elif args.tickers_file:
        tickers = [l.strip() for l in
                   Path(args.tickers_file).read_text(encoding="utf-8").splitlines()
                   if l.strip()]
        source = "file:" + Path(args.tickers_file).name
    elif args.tickers:
        tickers = [t.strip() for t in args.tickers.split(",") if t.strip()]
        source = "arg"
    else:
        ap.error("--universe · --tickers · --tickers-file 중 하나가 필요하다")

    if not tickers:
        raise SystemExit("종목이 비었다: " + source)

    pol = load_policy()
    raw, state, mandir = env_paths(pol)
    paths = (Path(args.out or raw), Path(args.state or state),
             Path(args.manifest_dir or mandir))

    res = collect_one_day(
        date, tickers, pol=pol, resume=args.resume, probe=args.probe,
        paths=paths, source=source,
        progress=lambda i, n: print("  %d/%d" % (i, n), flush=True))

    man = res["manifest"]
    print(json.dumps({k: man.get(k) for k in
                      ("date", "dayVerdict", "rows", "symbols",
                       "symbolsWithRows", "symbolsNotQueried",
                       "gapReasons", "unresolved", "acceptancePassed")},
                     ensure_ascii=False, indent=2))
    if not res["acceptancePassed"]:
        for c in man["acceptance"]:
            if not c["통과"]:
                print("  FAIL " + c["항목"] + " " +
                      json.dumps(c["실측"], ensure_ascii=False)[:160])
        return 1
    print("  manifest " + res["manifestPath"])
    return 0


def selftest():
    """네트워크 없이 인수 조건을 검증한다. 이 파일 하나로 돌아간다."""
    mod = sys.modules[__name__]
    import importlib.util
    spec = importlib.util.spec_from_file_location(
        "test_collect_minute", REPO / "scripts" / "test-collect-minute-kis.py")
    if not Path(spec.origin).exists():
        print("테스트 파일이 없다")
        return 1
    t = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(t)
    return t.run_all(mod)


if __name__ == "__main__":
    sys.exit(main())
