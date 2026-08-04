#!/usr/bin/env python3
"""A0.7 — DART corpCode 스냅샷 (BF-1.1)

DART corpCode.xml 전체를 그대로 스냅샷으로 남긴다. A1a·A1b·A3가 각자 corpCode.xml을
받으면 서로 다른 날짜의 스냅샷을 조인하게 되므로, 이 스크립트가 단일 수집점이다.

data/cache/corpCodeMap.json(ticker → corp_code 단방향 맵)을 대체한다. 그 캐시는
ticker 재사용이 발생하면 한쪽을 조용히 덮어써, A1b가 잡아야 할 폐지사가 입력에서부터
사라졌다. 이 스크립트는 같은 ticker가 여러 corp에 걸쳐 나오는 것을 그대로 남긴다
(재사용 탐지는 산출물의 정상 형태다 — 병합하지 않는다).

입력: 없음 (DART_API_KEY 환경변수)
출력:
  data/backfill/dart/corpcode.jsonl   stock_code 보유 법인, corp 오름차순
  data/backfill/dart/_diagnostics.json
"""
import io
import json
import os
import re
import sys
import time
import zipfile
import xml.etree.ElementTree as ET
from collections import defaultdict
from datetime import datetime, timedelta, timezone

import requests

OUT_DIR = "data/backfill/dart"
DART_KEY = os.environ.get("DART_API_KEY", "")
STAGE_VERSION = "A0.7.0"
KST = timezone(timedelta(hours=9))

TICKER_PATTERN = r"^[0-9A-Z]{6}$"
CORP_PATTERN = r"^[0-9]{8}$"

# 인수 조건 임계값 (트랙A-인수인계-ClaudeCode전환.md §3). 정책 파일로 뽑지 않은 이유:
# 이 값들은 채점 정책이 아니라 DART 소스 자체의 구조적 기대치(전체 법인 수·stock_code
# 보유 수)이고, 유니버스·채점 규칙처럼 사람이 의도적으로 조정할 대상이 아니다.
ACCEPTANCE = {
    "corpCountExpected": 118583,
    "corpCountTolerance": 0.05,
    "stockTickerCountExpected": 3981,
    "stockTickerCountTolerance": 0.10,
    "maxModifyDateStalenessDays": 90,
}

fails, warns = [], []


def chk(cond, msg):
    print(("  OK  " if cond else "  FAIL") + "  " + msg)
    if not cond:
        fails.append(msg)


def warn(cond, msg):
    print(("  OK  " if cond else "  WARN") + "  " + msg)
    if not cond:
        warns.append(msg)


# ── 네트워크 가드 (교훈31) ──────────────────────────────────────
_orig_send = requests.adapters.HTTPAdapter.send

LAST_HTTP = {"url": None, "status": None, "bytes": None, "head": None}


def _send(self, request, **kw):
    if kw.get("timeout") is None:
        kw["timeout"] = (10, 90)
    return _orig_send(self, request, **kw)


requests.adapters.HTTPAdapter.send = _send


def _http(url, **kw):
    """비2xx를 예외로 올린다(교훈38) — _retry가 status를 보게 하는 유일한 지점."""
    r = requests.get(url, **kw)
    body = r.content or b""
    LAST_HTTP.update(url=r.url, status=r.status_code, bytes=len(body),
                     head=body[:400].hex())
    if not (200 <= r.status_code < 300):
        raise requests.HTTPError(f"HTTP {r.status_code} ({len(body)}B)")
    return r


def _retry(fn, what, attempts=4, base=2):
    last = None
    for i in range(attempts):
        try:
            r = fn()
            if r is None:
                last = ValueError("빈 응답")
            else:
                return r
        except Exception as e:  # noqa: BLE001
            last = e
        if i < attempts - 1:
            time.sleep(base ** i)
    print(f"  ! {what} 실패: {type(last).__name__}: {last}")
    return None


def _abort(reason, diag, extra=None):
    """실패해도 진단은 남긴다(교훈39) — 중단 경로도 산출이다."""
    diag.update({"aborted": True, "abortReason": reason, "lastHttp": LAST_HTTP,
                 **(extra or {})})
    os.makedirs(OUT_DIR, exist_ok=True)
    with open(f"{OUT_DIR}/_diagnostics.json", "w", encoding="utf-8", newline="\n") as f:
        json.dump(diag, f, ensure_ascii=False, indent=2)
    print(f"\n중단: {reason}")
    print(f"  마지막 응답 status={LAST_HTTP['status']} bytes={LAST_HTTP['bytes']} "
          f"url={LAST_HTTP['url']}")
    sys.exit(2)


def normalize_ticker(raw):
    """길이 보정만 한다. 비숫자 제거는 하지 않는다 — 0218L0 → 02180 파괴를 막는다."""
    return str(raw).strip().upper().zfill(6)


# ── 1. 수집 (인수 조건 8: HTTP + zip 시그니처 + XML 파싱 3단 확인) ─
def fetch_corpcode_xml(diag):
    if not DART_KEY:
        _abort("DART_API_KEY 없음", diag)

    def get():
        return _http("https://opendart.fss.or.kr/api/corpCode.xml",
                     params={"crtfc_key": DART_KEY})

    r = _retry(get, "corpCode.xml GET")
    if r is None:
        _abort("corpCode.xml HTTP 요청 전 경로 실패", diag,
               {"httpStage": "failed"})
    diag["httpStage"] = "ok"
    body = r.content

    if body[:2] != b"PK":
        _abort(f"corpCode.xml zip 시그니처 불일치 (head={body[:16].hex()})", diag,
               {"httpStage": "ok", "zipStage": "failed"})
    diag["zipStage"] = "ok"

    try:
        zf = zipfile.ZipFile(io.BytesIO(body))
        inner_name = zf.namelist()[0]
        root = ET.fromstring(zf.read(inner_name))
    except Exception as e:  # noqa: BLE001
        _abort(f"corpCode.xml 파싱 실패: {type(e).__name__}: {e}", diag,
               {"httpStage": "ok", "zipStage": "ok", "xmlStage": "failed"})

    entries = list(root.iter("list"))
    if not entries:
        _abort("corpCode.xml 파싱 결과 0건 — 빈 응답을 성공으로 오인 방지(교훈38)", diag,
               {"httpStage": "ok", "zipStage": "ok", "xmlStage": "failed"})
    diag["xmlStage"] = "ok"
    return entries


# ── 2. 레코드 빌드 ─────────────────────────────────────────────
def build(entries, diag):
    diag["corpCount"] = len(entries)

    holders = []
    for it in entries:
        sc = (it.findtext("stock_code") or "").strip()
        if not sc:
            continue
        holders.append({
            "corp": (it.findtext("corp_code") or "").strip(),
            "ticker": sc,
            "corpName": (it.findtext("corp_name") or "").strip(),
            "modifyDate": (it.findtext("modify_date") or "").strip(),
        })
    diag["stockHolderCountRaw"] = len(holders)

    corp_bad, ticker_bad, rows = [], [], []
    for x in holders:
        corp = x["corp"].zfill(8)
        ticker = normalize_ticker(x["ticker"])
        if not re.fullmatch(CORP_PATTERN, corp):
            corp_bad.append({"corp": x["corp"], "ticker": x["ticker"]})
            continue
        if not re.fullmatch(TICKER_PATTERN, ticker):
            ticker_bad.append({"corp": x["corp"], "ticker": x["ticker"]})
            continue
        rows.append({"corp": corp, "ticker": ticker,
                     "corpName": x["corpName"], "modifyDate": x["modifyDate"]})
    diag["corpContractViolations"] = corp_bad
    diag["tickerContractViolations"] = ticker_bad

    rows.sort(key=lambda x: x["corp"])
    return rows


def ticker_reuse(rows):
    by_ticker = defaultdict(list)
    for x in rows:
        by_ticker[x["ticker"]].append(x)
    out = []
    for t, group in sorted(by_ticker.items()):
        corps = {g["corp"] for g in group}
        if len(corps) <= 1:
            continue
        ordered = sorted(group, key=lambda g: g["modifyDate"])
        out.append({
            "ticker": t,
            "corps": [{"corp": g["corp"], "corpName": g["corpName"],
                       "modifyDate": g["modifyDate"]} for g in ordered],
        })
    return out


# ── 3. 인수 조건 ───────────────────────────────────────────────
def validate(rows, diag):
    a = ACCEPTANCE
    print("\n[인수 조건]")

    lo1 = a["corpCountExpected"] * (1 - a["corpCountTolerance"])
    hi1 = a["corpCountExpected"] * (1 + a["corpCountTolerance"])
    chk(lo1 <= diag["corpCount"] <= hi1,
        f"총 법인 {diag['corpCount']} ∈ [{lo1:.0f}, {hi1:.0f}] (기대 {a['corpCountExpected']} ±5%)")

    lo2 = a["stockTickerCountExpected"] * (1 - a["stockTickerCountTolerance"])
    hi2 = a["stockTickerCountExpected"] * (1 + a["stockTickerCountTolerance"])
    chk(lo2 <= diag["stockHolderCountRaw"] <= hi2,
        f"stock_code 보유 {diag['stockHolderCountRaw']} ∈ [{lo2:.0f}, {hi2:.0f}] "
        f"(기대 {a['stockTickerCountExpected']} ±10%)")

    corps = [x["corp"] for x in rows]
    cdup = len(corps) - len(set(corps))
    chk(cdup == 0, f"corp 유일성 (중복 {cdup}건)")

    chk(not diag["corpContractViolations"],
        f"corp 계약 {CORP_PATTERN} 전건 통과 (위반 {len(diag['corpContractViolations'])}건)")
    chk(not diag["tickerContractViolations"],
        f"ticker 계약 {TICKER_PATTERN} 전건 통과 (위반 {len(diag['tickerContractViolations'])}건)")

    reuse = ticker_reuse(rows)
    diag["tickerReuse"] = reuse
    # 조건 6: 재사용은 사실이다 — 존재 자체는 항상 통과. 진단 기록 여부만 검사한다.
    chk("tickerReuse" in diag, f"ticker 중복(재사용) 전수 진단 기록 ({len(reuse)}건)")

    max_md = max((x["modifyDate"] for x in rows if x["modifyDate"]), default="")
    diag["maxModifyDate"] = max_md
    if max_md:
        try:
            md_date = datetime.strptime(max_md, "%Y%m%d").replace(tzinfo=KST).date()
            floor = (datetime.now(KST) - timedelta(days=a["maxModifyDateStalenessDays"])).date()
            warn(md_date >= floor,
                 f"maxModifyDate {max_md} >= 실행일 -{a['maxModifyDateStalenessDays']}일 ({floor})")
        except ValueError:
            warn(False, f"maxModifyDate {max_md} 파싱 실패")
    else:
        warn(False, "maxModifyDate 없음 (modifyDate 필드 전건 공란)")


# ── 4. main ────────────────────────────────────────────────────
def main() -> int:
    diag = {"stage": "A0.7", "stageVersion": STAGE_VERSION}
    snapshot_date = datetime.now(KST).strftime("%Y-%m-%d")
    diag["snapshotDate"] = snapshot_date

    print("[1/2] DART corpCode.xml 수집")
    entries = fetch_corpcode_xml(diag)
    print(f"  법인 {len(entries)}건 · http/zip/xml 3단 확인 통과")

    print("\n[2/2] stock_code 보유 법인 필터")
    rows = build(entries, diag)
    print(f"  stock_code 보유 {diag['stockHolderCountRaw']}건 → "
          f"유효 {len(rows)}건 (corp 위반 {len(diag['corpContractViolations'])} · "
          f"ticker 위반 {len(diag['tickerContractViolations'])})")

    validate(rows, diag)

    os.makedirs(OUT_DIR, exist_ok=True)
    diag["finalCount"] = len(rows)
    diag["acceptanceFails"] = list(fails)
    diag["acceptanceWarns"] = list(warns)
    diag["acceptancePassed"] = not fails
    with open(f"{OUT_DIR}/_diagnostics.json", "w", encoding="utf-8", newline="\n") as f:
        json.dump(diag, f, ensure_ascii=False, indent=2, sort_keys=False)

    if warns:
        print(f"\nWARN {len(warns)}건 (실패 아님, 확인 필요):")
        for w in warns:
            print(f"  - {w}")

    # 인수 조건 실패 시 산출물을 쓰지 않는다 — manifest는 '파일이 안 바뀌었다'만
    # 증명하지 '검사를 통과했다'는 증명하지 않는다.
    if fails:
        print(f"\n인수 조건 {len(fails)}건 실패 — 산출물을 쓰지 않는다")
        for x in fails:
            print(f"  - {x}")
        return 1

    order = ["corp", "ticker", "corpName", "modifyDate"]
    with open(f"{OUT_DIR}/corpcode.jsonl", "w", encoding="utf-8", newline="\n") as f:
        for x in rows:
            f.write(json.dumps({k: x[k] for k in order}, ensure_ascii=False) + "\n")

    print(f"\n{OUT_DIR}/corpcode.jsonl — {len(rows)}건 "
          f"(snapshotDate={snapshot_date}, maxModifyDate={diag['maxModifyDate']})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
