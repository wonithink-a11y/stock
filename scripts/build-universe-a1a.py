#!/usr/bin/env python3
"""A1a — 현재 상장 유니버스 (BF-1.1)

KIND 상장법인목록에서 KOSPI·KOSDAQ 보통주 유니버스를 확정하고 corp_code를 매핑한다.
정의는 config/policies/universe.v1.json(UN-1.0)이 단일 산출점이다 — 이 스크립트에
시장·SPAC·중복 규칙을 하드코딩하지 않는다.

입력:
  config/policies/universe.v1.json
  data/backfill/dart/corpcode.jsonl   corp_code 역인덱스 (A0.7 산출물, 단일 출처)
출력:
  data/backfill/universe/a1a/current.jsonl    유니버스 (사실)
  data/backfill/universe/a1a/excluded.jsonl   KONEX·SPAC 제외분 (corp 포함 — A1b 차집합용)
  data/backfill/universe/a1a/_diagnostics.json

BF-1.0의 '월별 전종목 스냅샷' 방식은 폐기했다 — KRX bulk 조회가 Actions에서
영구 차단됐다(BF-1.1 §10). 폐지 이력은 A1b가 따로 담당한다.
"""
import io
import json
import os
import re
import sys
import time
from collections import Counter, defaultdict

import pandas as pd
import requests

POLICY = "config/policies/universe.v1.json"
OUT_DIR = "data/backfill/universe/a1a"
CORP_INDEX_PATH = "data/backfill/dart/corpcode.jsonl"
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/124.0 Safari/537.36")

fails, warns = [], []


def chk(cond, msg):
    print(("  OK  " if cond else "  FAIL") + "  " + msg)
    if not cond:
        fails.append(msg)


def warn(cond, msg):
    print(("  OK  " if cond else "  WARN") + "  " + msg)
    if not cond:
        warns.append(msg)


# ── 네트워크 가드 ──────────────────────────────────────────────
# 외부 라이브러리의 기본 timeout이 None이면 재시도 로직이 지연 증폭기가 된다(교훈31).
_orig_send = requests.adapters.HTTPAdapter.send

LAST_HTTP = {"url": None, "status": None, "bytes": None, "head": None}


def _send(self, request, **kw):
    if kw.get("timeout") is None:
        kw["timeout"] = (10, 40)
    return _orig_send(self, request, **kw)


requests.adapters.HTTPAdapter.send = _send


def _http(sess, url, **kw):
    """비2xx를 예외로 올린다.

    Response 객체는 비어 있지도 예외도 아니므로, 상태를 보지 않는 재시도는 403·503에서
    한 번도 돌지 않는다 — 재시도가 붙어 있다는 사실이 오히려 안심시킨다.
    마지막 응답을 보관한다: 중단 시 원본 status/head가 다음 라운드의 유일한 입력이다.
    """
    r = (sess or requests).get(url, **kw)
    body = r.content or b""
    LAST_HTTP.update(url=r.url, status=r.status_code, bytes=len(body),
                     head=body[:400].decode("euc-kr", "replace"))
    if not (200 <= r.status_code < 300):
        raise requests.HTTPError(f"HTTP {r.status_code} ({len(body)}B)")
    return r


def _retry(fn, what, attempts=4, base=2):
    """빈 결과도 실패로 본다. 조회 실패를 성공으로 위장하면 종목이 조용히 사라진다."""
    last = None
    for i in range(attempts):
        try:
            r = fn()
            empty = r is None or (hasattr(r, "empty") and r.empty) or \
                    (isinstance(r, (list, dict)) and len(r) == 0)
            if empty:
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
    """실패해도 진단은 남긴다. 증거 없는 중단은 다음 라운드를 추측으로 만든다(교훈28)."""
    diag.update({"aborted": True, "abortReason": reason, "lastHttp": LAST_HTTP,
                 **(extra or {})})
    os.makedirs(OUT_DIR, exist_ok=True)
    with open(f"{OUT_DIR}/_diagnostics.json", "w", encoding="utf-8", newline="\n") as f:
        json.dump(diag, f, ensure_ascii=False, indent=2)
    print(f"\n중단: {reason}")
    print(f"  마지막 응답 status={LAST_HTTP['status']} bytes={LAST_HTTP['bytes']} "
          f"url={LAST_HTTP['url']}")
    print(f"  head: {(LAST_HTTP['head'] or '')[:300]}")
    sys.exit(2)


# ── 식별자 정규화 (BF-1.1 §1.1) ────────────────────────────────
def normalize_ticker(raw, pattern):
    """길이 보정만 한다. 비숫자 제거는 하지 않는다 — 0218L0 → 02180 파괴를 막는 유일한 지점.
    실패는 예외로 올린다. 조용히 버리면 종목이 사라진 것을 아무도 모른다."""
    s = str(raw).strip().upper().zfill(6)
    if not re.fullmatch(pattern, s):
        raise ValueError(f"ticker 계약 위반: {raw!r} → {s!r}")
    return s


# ── 1. 소스 수집 ───────────────────────────────────────────────
def _parse_corp_html(content, encoding):
    return pd.read_html(io.StringIO(content.decode(encoding, "replace")))[0]


def fetch_corp_list(src, diag):
    """3단계 폴백. 한 경로가 막혀도 정의(정책 파일)는 바뀌지 않으므로 소스 경로만 바꾼다."""
    enc = src["encoding"]
    hdr = {"User-Agent": UA}
    attempts = []

    # (a) 단발 GET — 정상 경로
    r = _retry(lambda: _http(None, src["url"], params=src["params"], headers=hdr),
               "corpList 단발 GET")
    attempts.append({"path": "plain", "status": LAST_HTTP["status"],
                     "bytes": LAST_HTTP["bytes"]})
    if r is not None:
        diag["sourcePath"] = "plain"
        diag["sourceAttempts"] = attempts
        return _parse_corp_html(r.content, enc), len(r.content)

    # (b) 세션 시드 + Referer — 봇 판정으로 막히는 경우
    def seeded():
        s2 = requests.Session()
        s2.headers.update(hdr)
        s2.get("https://kind.krx.co.kr/corpgeneral/corpList.do",
               params={"method": "loadInitPage"})
        return _http(s2, src["url"], params=src["params"],
                     headers={"Referer": "https://kind.krx.co.kr/corpgeneral/corpList.do"})

    r = _retry(seeded, "corpList 세션 시드 GET", attempts=3)
    attempts.append({"path": "seeded", "status": LAST_HTTP["status"],
                     "bytes": LAST_HTTP["bytes"]})
    if r is not None:
        diag["sourcePath"] = "seeded"
        diag["sourceAttempts"] = attempts
        return _parse_corp_html(r.content, enc), len(r.content)

    # (c) 시장별 분할 — 대용량 단일 응답이 막힐 때. 합집합이 전체와 같아야 한다
    parts, total = [], 0
    for mt in ("stockMkt", "kosdaqMkt", "konexMkt"):
        p = dict(src["params"]); p["marketType"] = mt
        rr = _retry(lambda pp=p: _http(None, src["url"], params=pp, headers=hdr),
                    f"corpList {mt}", attempts=3)
        attempts.append({"path": mt, "status": LAST_HTTP["status"],
                         "bytes": LAST_HTTP["bytes"]})
        if rr is None:
            continue
        parts.append(_parse_corp_html(rr.content, enc))
        total += len(rr.content)
    if parts:
        diag["sourcePath"] = "perMarket"
        diag["sourceAttempts"] = attempts
        diag["perMarketRows"] = [len(x) for x in parts]
        return pd.concat(parts, ignore_index=True), total

    _abort("KIND 상장법인목록 전 경로 실패 (plain / seeded / perMarket)", diag,
           {"sourceAttempts": attempts})


# ── 2. corp_code 역인덱스 (A0.7 산출물이 단일 출처) ────────────────
def load_corp_index(diag):
    """ticker → [A0.7 레코드...]. 값이 리스트인 이유: A0.7은 ticker 재사용을 병합하지
    않고 그대로 남긴다 — 같은 ticker에 corp가 둘 이상이면 여기서 이미 모호하다.
    data/cache/corpCodeMap.json(단방향 맵)을 대체한다. 그 캐시는 재사용 발생 시
    한쪽을 조용히 덮어써 A1b가 잡아야 할 폐지사가 입력에서부터 사라졌다."""
    if not os.path.exists(CORP_INDEX_PATH):
        _abort(f"{CORP_INDEX_PATH} 없음 — A0.7을 먼저 실행하라", diag)
    idx = defaultdict(list)
    with open(CORP_INDEX_PATH, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            r = json.loads(line)
            idx[r["ticker"]].append(r)
    print(f"  corp 역인덱스 {len(idx)} ticker "
          f"({sum(len(v) for v in idx.values())}건)")
    return idx


def resolve_corp(ticker, idx, diag):
    """1:1이면 매핑, 0건이면 None(결측 — 기존 WARN 경로), 2건 이상이면 결측 처리하고
    충돌을 기록한다. 모호한 매핑을 아무거나 골라 조용히 채우지 않는다."""
    cands = idx.get(ticker, [])
    if len(cands) == 1:
        return cands[0]["corp"]
    if len(cands) > 1:
        diag["tickerCollisions"].append({
            "ticker": ticker,
            "corps": [{"corp": c["corp"], "corpName": c["corpName"],
                       "modifyDate": c["modifyDate"]} for c in cands],
        })
    return None


# ── 3. 필터 파이프라인 ─────────────────────────────────────────
def build(df, pol, corp_idx, diag):
    src = pol["source"]
    mmap = src["marketMap"]
    pat = pol["tickerPattern"]

    # 3-1 정규화
    bad = []
    rows = []
    for _, r in df.iterrows():
        try:
            t = normalize_ticker(r["종목코드"], pat)
        except ValueError as e:
            bad.append(str(e))
            continue
        rows.append({
            "ticker": t,
            "name": str(r["회사명"]).strip(),
            "market": mmap.get(str(r["시장구분"]).strip(), str(r["시장구분"]).strip()),
            "listedAt": str(r["상장일"]).strip(),
            "sector": str(r["업종"]).strip() if pd.notna(r.get("업종")) else None,
            "fiscalMonth": str(r["결산월"]).strip() if pd.notna(r.get("결산월")) else None,
        })
    diag["tickerContractViolations"] = bad
    diag["alnumTickersSource"] = sorted({x["ticker"] for x in rows if not x["ticker"].isdigit()})

    # 3-2 중복 — 전 필드 일치만 제거한다. 한 필드라도 다르면 회사 교체일 수 있으므로 FAIL.
    by_ticker = defaultdict(list)
    for x in rows:
        by_ticker[x["ticker"]].append(x)
    kept, exact_removed, partial = [], 0, []
    for t, group in by_ticker.items():
        if len(group) == 1:
            kept.append(group[0])
            continue
        uniq = {json.dumps(g, ensure_ascii=False, sort_keys=True) for g in group}
        if len(uniq) == 1:
            kept.append(group[0])
            exact_removed += len(group) - 1
        else:
            partial.append({"ticker": t, "rows": group})
            kept.extend(group)          # 제거하지 않는다 — 사람이 판정한다
    diag["exactDuplicateRemoved"] = exact_removed
    diag["partialDuplicates"] = partial

    # 3-3 corp_code — dedup 직후로 옮긴다. 이후 시장·SPAC 필터로 갈라져 excluded에
    # 담길 레코드도 corp가 있어야 A1b의 차집합(corp 기준)에서 새어 들어가지 않는다.
    for x in kept:
        x["corp"] = resolve_corp(x["ticker"], corp_idx, diag)

    # 3-4 시장 필터
    pre_market = Counter(x["market"] for x in kept)
    diag["marketCountsBeforeFilter"] = dict(pre_market)
    konex_excluded = [x for x in kept if x["market"] in pol["excludeMarkets"]]
    kept = [x for x in kept if x["market"] in pol["includeMarkets"]]
    diag["konexExcluded"] = len(konex_excluded)

    # 3-5 SPAC — 회사명만으로 판정한다. 업종은 교차 집계만.
    spac_re = re.compile(pol["spacNamePattern"])
    spacs = [x for x in kept if spac_re.search(x["name"])]
    if pol.get("excludeSpac"):
        kept = [x for x in kept if not spac_re.search(x["name"])]
    diag["spacExcluded"] = len(spacs)
    diag["spacSample"] = [{"ticker": s["ticker"], "name": s["name"],
                           "market": s["market"], "sector": s["sector"]}
                          for s in spacs[:20]]
    hint = set(pol.get("spacSectorHint") or [])
    diag["spacSectorCross"] = {
        "nameHitSectorHit": sum(1 for s in spacs if s["sector"] in hint),
        "nameHitSectorMiss": sum(1 for s in spacs if s["sector"] not in hint),
        "nameMissSectorHit": sum(1 for x in kept if x["sector"] in hint),
    }

    # 3-6 제외 목록 — 필터 순서상 KONEX가 이미 우선(SPAC 검사 전에 빠진다).
    # 동시 해당은 배열로 남기지 않고 진단 카운터로만 잰다(소비자 분기 부담 방지).
    diag["konexAndSpac"] = sum(1 for x in konex_excluded if spac_re.search(x["name"]))
    excluded = ([dict(x, exclusionReason="KONEX") for x in konex_excluded]
                + [dict(x, exclusionReason="SPAC") for x in spacs])
    diag["excludedCorpMissing"] = [x["ticker"] for x in excluded if not x["corp"]]

    # 스키마 키 순서 고정 (BF-1.1 §3 — JSON 키 순서는 스키마 정의 순서)
    order = ["ticker", "name", "market", "corp", "listedAt", "sector", "fiscalMonth"]
    kept = [{k: x.get(k) for k in order} for x in kept]
    kept.sort(key=lambda x: x["ticker"])
    excluded = [{**{k: x.get(k) for k in order}, "exclusionReason": x["exclusionReason"]}
                for x in excluded]
    excluded.sort(key=lambda x: x["ticker"])

    diag["alnumTickersFinal"] = sorted(x["ticker"] for x in kept if not x["ticker"].isdigit())
    return kept, excluded


# ── 4. 인수 조건 ───────────────────────────────────────────────
DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def validate(uni, pol, diag, src_rows):
    a = pol["acceptance"]
    print("\n[인수 조건]")

    # 게이트 검증용 주입. 조건을 '더 엄격하게'만 만들 수 있고 느슨하게는 못 만든다 —
    # 통과시키는 방향의 우회로가 생기면 그게 곧 정책 무력화 경로다.
    inject = os.environ.get("A1A_FAIL_INJECTION", "").strip()
    if inject:
        diag["failInjection"] = inject
        chk(False, f"[FAIL INJECTION] {inject} — 게이트 검증용 강제 실패")

    chk(a["sourceRowsMin"] <= src_rows <= a["sourceRowsMax"],
        f"소스 행 수 {src_rows} ∈ [{a['sourceRowsMin']}, {a['sourceRowsMax']}]")

    chk(not diag["tickerContractViolations"],
        f"ticker 계약 {pol['tickerPattern']} 전건 통과 "
        f"(위반 {len(diag['tickerContractViolations'])}건)")

    chk(len(diag["partialDuplicates"]) == a["partialDuplicate"],
        f"부분 일치 중복 {len(diag['partialDuplicates'])}건 (0이어야 함 — 회사 교체 가능성, 사람 판정)")

    codes = [x["ticker"] for x in uni]
    resid = len(codes) - len(set(codes))
    chk(resid == a["residualDuplicate"], f"잔여 ticker 중복 {resid}건")

    mc = Counter(x["market"] for x in uni)
    chk(mc.get("KOSPI", 0) >= a["kospiMin"], f"KOSPI {mc.get('KOSPI', 0)} >= {a['kospiMin']}")
    chk(mc.get("KOSDAQ", 0) >= a["kosdaqMin"], f"KOSDAQ {mc.get('KOSDAQ', 0)} >= {a['kosdaqMin']}")
    chk(mc.get("KONEX", 0) == a["konexAfterFilter"], f"KONEX 잔존 {mc.get('KONEX', 0)}건")

    # 제외 건수가 0이면 데이터가 아니라 필터 파손이다 — 스팩·코넥스는 상시 존재한다
    chk(diag["spacExcluded"] >= a["spacExcludedMin"],
        f"SPAC 제외 {diag['spacExcluded']}건 >= {a['spacExcludedMin']} (0이면 정규식 파손)")
    chk(diag["konexExcluded"] >= a["konexExcludedMin"],
        f"KONEX 제외 {diag['konexExcluded']}건 >= {a['konexExcludedMin']}")
    spac_re = re.compile(pol["spacNamePattern"])
    left = [x["ticker"] for x in uni if spac_re.search(x["name"])]
    chk(len(left) == a["spacAfterFilter"], f"SPAC 잔존 {len(left)}건")

    ok_date = [x for x in uni if DATE_RE.match(x["listedAt"] or "")]
    rate = len(ok_date) / len(uni) if uni else 0
    chk(rate >= a["listedAtParseRate"], f"상장일 파싱률 {rate*100:.2f}%")
    today = time.strftime("%Y-%m-%d")
    future = [x["ticker"] for x in uni if (x["listedAt"] or "") > today]
    chk(len(future) == a["futureListedAt"], f"미래 상장일 {len(future)}건")
    diag["futureListedAt"] = future

    miss = [x["ticker"] for x in uni if not x["corp"]]
    mrate = len(miss) / len(uni) if uni else 0
    warn(mrate < a["corpCodeMissingRateWarn"],
         f"corp_code 매핑 실패율 {mrate*100:.1f}% ({len(miss)}/{len(uni)})")
    diag["corpCodeMissing"] = miss[:500]

    # corp_code 유일성 — UN-1.1에서 WARN → FAIL 승격(실측 0건 확인)
    cc = [x["corp"] for x in uni if x["corp"]]
    cdup = len(cc) - len(set(cc))
    chk(cdup == a["corpCodeDuplicate"],
        f"corp_code 유일성 (non-null 중 중복 {cdup}건) — 1 corp → N ticker 후보")
    if cdup:
        bag = defaultdict(list)
        for x in uni:
            if x["corp"]:
                bag[x["corp"]].append({"ticker": x["ticker"], "name": x["name"],
                                       "market": x["market"]})
        diag["corpCodeDuplicates"] = {k: v for k, v in bag.items() if len(v) > 1}

    # A0.7 역인덱스가 같은 ticker에 corp 2개 이상을 낸 경우 — 아무거나 골라 채우지 않고
    # 결측 처리했으므로, 그 결측이 실제로 남아 있는지 여기서 다시 확인한다.
    chk(not diag["tickerCollisions"],
        f"ticker→corp 충돌 {len(diag['tickerCollisions'])}건 (모호한 매핑, 사람 판정 필요)")

    # excluded(KONEX+SPAC)에 corp가 없으면 A1b의 corp 기준 차집합에서 그 종목이
    # 폐지 후보로 새어 들어간다 — corp 매핑을 dedup 직후로 옮긴 이유가 이것이다.
    chk(not diag["excludedCorpMissing"],
        f"excluded corp 결측 {len(diag['excludedCorpMissing'])}건")


# ── 5. main ────────────────────────────────────────────────────
def main() -> int:
    if not os.path.exists(POLICY):
        print(f"{POLICY} 없음 — UN-1.0 정책 파일이 필요하다")
        return 1
    with open(POLICY, encoding="utf-8") as f:
        pol = json.load(f)
    print(f"유니버스 정책 {pol['version']} · 시장 {pol['includeMarkets']} · "
          f"SPAC제외={pol['excludeSpac']}")

    # stageVersion은 여기 안 둔다 — manifest(node write-manifest.js --stageVersion)가
    # 단일 출처다. 두 곳에 두면 갱신을 하나만 하고 잊는 경로가 생긴다.
    diag = {"stage": "A1a", "universePolicy": pol["version"], "tickerCollisions": []}

    print("\n[1/3] KIND 상장법인목록")
    df, nbytes = fetch_corp_list(pol["source"], diag)
    print(f"  {len(df)}행 / {nbytes}바이트 · 경로={diag.get('sourcePath')}")
    diag["sourceRows"] = len(df)
    diag["sourceBytes"] = nbytes

    print("\n[2/3] corp_code 역인덱스 (A0.7)")
    corp_idx = load_corp_index(diag)

    print("\n[3/3] 필터 파이프라인")
    uni, excluded = build(df, pol, corp_idx, diag)
    mc = Counter(x["market"] for x in uni)
    print(f"  최종 {len(uni)}종목  {dict(mc)}  "
          f"(중복제거 {diag['exactDuplicateRemoved']} · "
          f"KONEX -{diag['konexExcluded']} · SPAC -{diag['spacExcluded']})")

    diag["finalCount"] = len(uni)
    diag["marketCounts"] = dict(mc)
    diag["excludedCount"] = len(excluded)

    validate(uni, pol, diag, len(df))

    os.makedirs(OUT_DIR, exist_ok=True)

    # 진단은 중단 경로에도 남긴다(교훈 39). 실패 원인 판별의 유일한 근거다.
    diag["acceptanceFails"] = list(fails)
    diag["acceptanceWarns"] = list(warns)
    diag["acceptancePassed"] = not fails
    with open(f"{OUT_DIR}/_diagnostics.json", "w", encoding="utf-8", newline="\n") as f:
        json.dump(diag, f, ensure_ascii=False, indent=2, sort_keys=False)

    if warns:
        print(f"\nWARN {len(warns)}건 (실패 아님, 확인 필요):")
        for w in warns:
            print(f"  - {w}")

    # 인수 조건 실패 시 산출물을 쓰지 않는다.
    # 쓰고 나서 exit(1)하면 워크스페이스에 깨진 파일이 남고, manifest 단계가
    # 그 파일에 해시를 찍어 하류가 verifyUpstream을 정상 통과한다.
    # manifest는 '파일이 안 바뀌었다'만 증명하지 '검사를 통과했다'는 증명하지 않는다.
    if fails:
        print(f"\n인수 조건 {len(fails)}건 실패 — 산출물을 쓰지 않는다")
        for x in fails:
            print(f"  - {x}")
        return 1

    with open(f"{OUT_DIR}/current.jsonl", "w", encoding="utf-8", newline="\n") as f:
        for x in uni:
            f.write(json.dumps(x, ensure_ascii=False, sort_keys=False) + "\n")

    with open(f"{OUT_DIR}/excluded.jsonl", "w", encoding="utf-8", newline="\n") as f:
        for x in excluded:
            f.write(json.dumps(x, ensure_ascii=False, sort_keys=False) + "\n")

    print(f"\n{OUT_DIR}/current.jsonl — {len(uni)}종목 "
          f"(영숫자 티커 {len(diag['alnumTickersFinal'])}건)")
    print(f"{OUT_DIR}/excluded.jsonl — {len(excluded)}건 "
          f"(KONEX {diag['konexExcluded']} · SPAC {diag['spacExcluded']} · "
          f"동시해당 {diag['konexAndSpac']})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
