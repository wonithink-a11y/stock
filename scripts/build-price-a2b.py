#!/usr/bin/env python3
"""A2b — 폐지분 일봉 가격 (BF-1.1)

A1b가 남긴 폐지 후보 1,223건의 일봉을 받아 연도별로 저장하고, A1b가 null로 비워둔
exitAt을 확정한다. 정의는 config/policies/price.v1.json의 `a2b` 블록(PR-1.5)이다.

PR-1.5부터 소스가 KIS다(그 전엔 A2a와 같은 pykrx/Naver). 세션인수인계-2026-08-16.md
§4가 이유다 — Naver 우회 경로는 "오늘 기준 최근 3,000캔들"만 주는 롤링 윈도우라
폐지 종목의 과거 구간이 조용히 잘렸고, KRX-native 대체 경로(adjStkPrc=2)는 액면분할을
조정하지 않아 부적합 판정을 받았다. KIS(FHKST03010100, FID_ORG_ADJ_PRC=0)만 두 조건을
다 통과했다 — 콜당 100행 캡은 있지만 날짜 커서 페이지네이션으로 전량 확보되고,
005930 2018년 분할도 연속적으로 조정된다(커밋 4f3a52b 프로브 실측).

수집기는 A2a의 복사에 가깝다. **그대로 복사하면 안 되는 곳이 넷**이고, 이 파일에서
A2a와 다른 코드는 전부 그 넷 중 하나다. (소스가 KIS로 바뀐 것은 이 넷과 무관한
다섯 번째 차이다 — fetch 방식만 바뀌고 validate()·exitAt·커버리지 로직은 그대로다.)

  1. 기대 거래일을 상장기간으로 한정한다
     A2a는 '실제 최초 거래일 ~ 캘린더 끝'이다. 폐지 종목의 끝은 캘린더의 끝이 아니라
     자기 마지막 거래일이라, 그대로 쓰면 폐지 이후 구간이 통째로 누락으로 잡힌다.
  2. 빈 응답이 정상이다
     정찰 실측 591/1,222(48.4%)가 전 구간 0행이며 '2014-05 이전 폐지'의 기대 응답이다.
     A2a의 '연속 빈 응답 20건 → 중단'을 그대로 쓰면 정상 데이터에서 멈춘다.
     A1b가 corp 오름차순이라 옛 폐지가 뭉쳐 있어 더욱 그렇다. 서킷은 예외만 센다.
  3. exitAt을 확정한다
     확보한 마지막 거래일이 A1b가 비워둔 exitAt의 확정값이다(dartModifyDate가 아니다).
     다만 마지막 '거래일'이지 폐지 '효력일'은 아니므로 필드명과 스탬프로 구분한다.
  4. 커버리지의 분모가 다르다
     A1b 후보 전체(51.6%)는 커버리지가 아니다. 분석 구간과 겹치는 폐지 종목이 분모이며,
     확보 실패는 lastTraded를 모르므로 '전부 구간 밖'이라는 가정 위에서만 셀 수 있다.
     그 가정을 진단에 스탬프로 남긴다.

품질 판별(±50% · 거래량 0 · 인접 거래일)과 gzip 결정론은 A2a와 공유한다 — 같은 정책
블록(dailyChange·qualityExclusion)이 두 단계를 다 정의하므로, 코드를 복사하면 정책은
하나인데 구현이 둘이 된다. 그래서 순수 함수만 A2a 모듈에서 가져다 쓴다.

  --shard N --shards M   후보 부분집합 수집 → _shards_a2b/shard-N.jsonl (커밋 안 함)
                         PR-1.5부터 shards=1 고정이다 — KIS 토큰 발급이 5분당 1회
                         제한이라 여러 프로세스(Actions matrix job)로 나누면 서로
                         발급을 다툰다. 병렬성은 프로세스 안에서 스레드 동시성
                         (a2b.source.concurrency)으로 낸다.
  --finalize             병합 → 검증 → 연도 분할 → exitAt 산출 → gzip

입력:
  config/policies/price.v1.json          (a2b 블록)
  data/backfill/universe/a1b/delisted.jsonl   대상 후보 (A1b)
  data/backfill/calendar.json                 거래일·analysisFrom (A0.5)
출력:
  data/backfill/price/a2b/{YYYY}.jsonl.gz
  data/backfill/price/a2b/delisted-exit.jsonl.gz      exitAt 확정값
  data/backfill/price/a2b/price-quality-excluded.jsonl.gz
  data/backfill/price/a2b/_diagnostics.json
"""
import argparse
import glob
import importlib.util
import json
import os
import re
import sys
import time
from collections import Counter, defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timedelta, timezone

import requests

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
POLICY = "config/policies/price.v1.json"
UNIVERSE = "data/backfill/universe/a1b/delisted.jsonl"
CALENDAR = "data/backfill/calendar.json"
TOKEN_CACHE = os.path.join(ROOT, ".token_cache_kis.json")
KIS_BASE = "https://openapi.koreainvestment.com:9443"
KIS_DAILY_PATH = "/uapi/domestic-stock/v1/quotations/inquire-daily-itemchartprice"
KST = timezone(timedelta(hours=9))

TICKER_RE = re.compile(r"^[0-9A-Z]{6}$")
DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
FIELDS = ["ticker", "date", "open", "high", "low", "close", "volume"]

fails, warns = [], []


def _load_a2a():
    """A2a 모듈에서 순수 함수만 가져온다(품질 판별·gzip 결정론·레코드 변환).

    파일명에 하이픈이 있어 import 문으로는 못 읽는다. scripts/test-price-a2a.py가
    쓰는 것과 같은 방식이다. A2a 모듈의 최상위는 상수·함수 정의뿐이라 부작용이 없고,
    가져오는 함수 중 어느 것도 A2a의 fails/warns를 건드리지 않는다 — A2b는 자기
    게이트 상태를 따로 들고 있다."""
    spec = importlib.util.spec_from_file_location(
        "a2a", os.path.join(ROOT, "scripts", "build-price-a2a.py"))
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


A2A = _load_a2a()


def chk(cond, msg):
    print(("  OK  " if cond else "  FAIL") + "  " + msg)
    if not cond:
        fails.append(msg)


def warn(cond, msg):
    print(("  OK  " if cond else "  WARN") + "  " + msg)
    if not cond:
        warns.append(msg)


def _abort(reason, diag, path, extra=None):
    """실패해도 진단은 남긴다(교훈39)."""
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


# ── 수집 (KIS) ─────────────────────────────────────────────────
def _kis_env():
    key = os.environ.get("KIS_APP_KEY", "")
    secret = os.environ.get("KIS_APP_SECRET", "")
    if not key or not secret:
        raise SystemExit("KIS_APP_KEY / KIS_APP_SECRET 환경변수가 없다")
    return key, secret


def _kis_token(key, secret):
    """토큰 캐시가 유효하면 재사용한다. KIS는 발급을 5분당 1회로 제한하므로
    (프로브에서 실측) shards=1로 프로세스당 발급을 최대 1회로 묶어야 한다 —
    캐시가 없어도 이 프로세스 안에서는 한 번만 발급된다."""
    if os.path.exists(TOKEN_CACHE):
        try:
            c = json.load(open(TOKEN_CACHE, encoding="utf-8"))
            exp = datetime.fromisoformat(c["expiresAt"].replace(" ", "T")).replace(tzinfo=KST)
            if exp - timedelta(minutes=10) > datetime.now(KST) and c.get("appKeyTail") == key[-4:]:
                return c["accessToken"]
        except Exception:
            pass
    r = requests.post(
        KIS_BASE + "/oauth2/tokenP",
        data=json.dumps({"grant_type": "client_credentials",
                         "appkey": key, "appsecret": secret}),
        headers={"content-type": "application/json"}, timeout=20)
    body = r.json()
    if r.status_code != 200 or "access_token" not in body:
        raise SystemExit(f"KIS 토큰 발급 실패: {body.get('error_description', body)}")
    tok = body["access_token"]
    with open(TOKEN_CACHE, "w", encoding="utf-8", newline="\n") as f:
        json.dump({"accessToken": tok,
                   "expiresAt": body.get("access_token_token_expired", ""),
                   "appKeyTail": key[-4:]}, f, ensure_ascii=False, indent=2)
    return tok


def _kis_call_page(key, secret, token, ticker, d1, d2, tr_id, adj_flag):
    """1페이지(최대 100행). 예외는 호출부(fetch_one)가 kind='exception'으로 분류한다."""
    r = requests.get(
        KIS_BASE + KIS_DAILY_PATH,
        headers={"content-type": "application/json",
                 "authorization": "Bearer " + token,
                 "appkey": key, "appsecret": secret,
                 "tr_id": tr_id, "custtype": "P"},
        params={"FID_COND_MRKT_DIV_CODE": "J", "FID_INPUT_ISCD": ticker,
                "FID_INPUT_DATE_1": d1, "FID_INPUT_DATE_2": d2,
                "FID_PERIOD_DIV_CODE": "D", "FID_ORG_ADJ_PRC": adj_flag},
        timeout=15)
    b = r.json()
    o2 = b.get("output2") or []
    rows = {x.get("stck_bsop_date"): x for x in o2 if x.get("stck_bsop_date")}
    return {"rtCd": b.get("rt_cd"), "msgCd": b.get("msg_cd"),
            "msg": (b.get("msg1") or "")[:150], "rows": rows}


def _call_page_with_retry(call_page, ticker, d1, d2, src):
    """EGW00201(초당 거래건수 초과)은 재시도 가능으로 분류한다(CLAUDE.md 운영기준).
    표본 프로브(297콜)에서 동시성 2·0.15초 간격으로 0회였지만 전량(약 9,000콜)의
    3%뿐이라 재시도는 그대로 남겨둔다."""
    r = None
    for attempt in range(src["egw00201RetryAttempts"]):
        r = call_page(ticker, d1, d2)
        if r.get("msgCd") == "EGW00201":
            time.sleep(src["egw00201RetryBackoffBase"] ** attempt)
            continue
        return r
    return r


def fetch_one(call_page, ticker, frm, to, pol):
    """(rows, kind, error)를 돌려준다. kind는 'ok' | 'empty' | 'exception'.
    rows는 {날짜YYYYMMDD: KIS 원본 행} — A2a의 DataFrame과 다른 이유는 소스가
    REST/JSON이기 때문이지 차이 2(빈 응답·예외 구분)와는 무관하다. 그 구분 자체는
    A2a의 fetch_one과 여전히 다르게 유지한다 — 문자열이 아니라 kind로 가른다.

    call_page(ticker, d1, d2) -> {"rtCd", "msgCd", "msg", "rows"} 를 주입받는다.
    테스트가 네트워크 없이 이 함수를 스텁할 수 있게 하기 위해서다."""
    src = pol["a2b"]["source"]
    collected, cur_to = {}, to
    for _ in range(src["maxPagesPerTicker"]):
        try:
            r = _call_page_with_retry(call_page, ticker, frm, cur_to, src)
        except Exception as e:  # noqa: BLE001
            return None, "exception", f"{type(e).__name__}: {e}"
        if r.get("rtCd") != "0":
            return None, "exception", f"rtCd={r.get('rtCd')} msgCd={r.get('msgCd')} {r.get('msg')}"
        page_rows = r.get("rows") or {}
        if not page_rows:
            break
        collected.update(page_rows)
        earliest = min(page_rows)
        if earliest <= frm or len(page_rows) < src["emptyPageThreshold"]:
            break
        cur_to = (datetime.strptime(earliest, "%Y%m%d") - timedelta(days=1)).strftime("%Y%m%d")
        time.sleep(src["sleepBetweenCallsSeconds"])
    if not collected:
        return None, "empty", None
    return collected, "ok", None


def to_records_kis(ticker, rows):
    out = []
    for d, r in rows.items():
        out.append({
            "ticker": ticker,
            "date": f"{d[:4]}-{d[4:6]}-{d[6:]}",
            "open": int(r["stck_oprc"]),
            "high": int(r["stck_hgpr"]),
            "low": int(r["stck_lwpr"]),
            "close": int(r["stck_clpr"]),
            "volume": int(r["acml_vol"]),
        })
    return out


def _kis_environment():
    try:
        from importlib.metadata import version
        req_ver = version("requests")
    except Exception:  # noqa: BLE001
        req_ver = "unknown"
    return {"requests": req_ver, "python": sys.version.split()[0], "kisSource": True}


def run_shard(shard, shards, pol, limit):
    a2b = pol["a2b"]
    src = a2b["source"]
    key, secret = _kis_env()
    token = _kis_token(key, secret)

    def call_page(ticker, d1, d2):
        return _kis_call_page(key, secret, token, ticker, d1, d2,
                              src["trId"], src["adjustedFlag"])

    shard_dir = a2b["output"]["shardDir"]
    diag_path = f"{shard_dir}/_diagnostics-shard-{shard}.json"
    diag = {"stage": "A2b", "mode": "shard", "shard": shard, "shards": shards,
            "pricePolicy": pol["version"], "environment": _kis_environment()}
    if limit:
        diag["smokeTest"] = True

    cand = load_jsonl(UNIVERSE)
    cal = load_json(CALENDAR)
    frm = pol["collectFrom"].replace("-", "")
    to = cal["tradingDays"][-1].replace("-", "")

    tickers = sorted(x["ticker"] for x in cand)
    mine = [t for i, t in enumerate(tickers) if i % shards == shard]
    if limit:
        mine = mine[:limit]
    print(f"A2b 샤드 {shard}/{shards} — {len(mine)}종목 · 구간 {frm}~{to} · "
          f"KIS {src['trId']} · 동시성 {src['concurrency']}")

    # 정찰 2회(교훈32). 현재 상장 종목의 최근 1일로 경로만 본다 — 폐지 종목으로
    # 정찰하면 '경로가 막힘'과 '그 종목이 구간 밖'이 구분되지 않는다.
    probes = []
    for pt in pol["probeTickers"]:
        _, kind, err = fetch_one(call_page, pt, to, to, pol)
        probes.append({"ticker": pt, "ok": kind == "ok", "kind": kind, "error": err})
    diag["probes"] = probes
    if not any(p["ok"] for p in probes):
        _abort("정찰 전건 실패 — 수집 경로가 막혔다", diag, diag_path)
    print(f"  정찰 {sum(1 for p in probes if p['ok'])}/{len(probes)} 통과")

    cb = a2b["circuitBreaker"]
    rows, empty, exc, consec_exc = [], [], [], 0
    t0 = time.time()
    done = 0

    def _work(tk):
        return tk, fetch_one(call_page, tk, frm, to, pol)

    # 동시성은 티커 단위 스레드로 낸다(a2b.source.concurrency, 표본 프로브에서
    # 실측된 값). '연속' 예외는 여기서부터는 제출 순서가 아니라 완료 순서
    # 기준이다 — 병렬이라 완전히 같지는 않지만, 경로가 실제로 막히면 완료
    # 순서에서도 예외가 뭉치므로 서킷의 목적(막힘 감지)은 그대로 유지된다.
    with ThreadPoolExecutor(max_workers=src["concurrency"]) as ex:
        futs = {ex.submit(_work, tk): tk for tk in mine}
        for fut in as_completed(futs):
            tk, (kis_rows, kind, err) = fut.result()
            if kind == "ok":
                rows.extend(to_records_kis(tk, kis_rows))
                consec_exc = 0
            elif kind == "empty":
                # 정상 결과다(차이 2). 전 구간 0행 = 2014-05 이전 폐지이거나 상장 이력 없음.
                # 서킷을 걸지 않는다 — 과다 여부는 finalize의 emptyRate·규모 게이트가 본다.
                empty.append(tk)
                consec_exc = 0
            else:
                exc.append({"ticker": tk, "error": err})
                consec_exc += 1
                if consec_exc >= cb["consecutiveExceptions"]:
                    diag.update(rowCount=len(rows), emptyTickers=empty, exceptionTickers=exc)
                    _abort(f"연속 예외 {consec_exc}건 — 루프 도중 경로가 막혔다",
                           diag, diag_path)
            done += 1
            if done % 100 == 0:
                print(f"  {done}/{len(mine)} · {len(rows)}행 · 빈 응답 {len(empty)} · "
                      f"예외 {len(exc)} · {time.time()-t0:.0f}s")

    diag.update(tickerCount=len(mine), rowCount=len(rows),
                emptyTickers=empty, emptyCount=len(empty),
                exceptionTickers=exc, exceptionCount=len(exc),
                elapsedSeconds=round(time.time() - t0, 1))

    os.makedirs(shard_dir, exist_ok=True)
    with open(f"{shard_dir}/shard-{shard}.jsonl", "w", encoding="utf-8", newline="\n") as f:
        for x in rows:
            f.write(json.dumps(x, ensure_ascii=False) + "\n")
    with open(diag_path, "w", encoding="utf-8", newline="\n") as f:
        json.dump(diag, f, ensure_ascii=False, indent=2)

    print(f"\n{shard_dir}/shard-{shard}.jsonl — {len(rows)}행 "
          f"({len(mine)}종목 중 빈 응답 {len(empty)} · 예외 {len(exc)}, "
          f"{diag['elapsedSeconds']}s)")
    return 0


# ── 검증 ───────────────────────────────────────────────────────
def validate(rows, cand, cal, pol, diag):
    """반환값은 (남길 행, 품질 제외 목록, exitAt 레코드)다."""
    a2b = pol["a2b"]
    a = a2b["acceptance"]
    print("\n[인수 조건]")

    inject = os.environ.get("A2B_FAIL_INJECTION", "").strip()
    if inject:
        diag["failInjection"] = inject
        chk(False, f"[FAIL INJECTION] {inject} — 게이트 검증용 강제 실패")

    # ── 구조 계약 ──────────────────────────────────────────────
    bad_date = [x for x in rows if not DATE_RE.match(x["date"] or "")]
    chk(len(bad_date) == a["dateContractViolations"],
        f"date 계약 YYYY-MM-DD (위반 {len(bad_date)}건)")
    nonpos = [x for x in rows if x["close"] <= 0]
    chk(len(nonpos) == a["closeNonPositive"], f"close > 0 (위반 {len(nonpos)}건)")
    hl = [x for x in rows if x["high"] < x["low"]]
    chk(len(hl) == a["highLowOrderViolations"], f"high >= low (위반 {len(hl)}건)")
    dup = len(rows) - len({(x["ticker"], x["date"]) for x in rows})
    chk(dup == a["duplicateKeys"], f"(ticker,date) 중복 {dup}건")

    # 영숫자 티커는 정상이다(0218L0 등). 숫자 6자리로 좁히면 정상을 위반으로 잡는다.
    bad_tk = sorted({x["ticker"] for x in rows if not TICKER_RE.match(x["ticker"] or "")})
    diag["tickerContractViolations"] = len(bad_tk)
    diag["tickerContractViolationSample"] = bad_tk[:20]
    chk(len(bad_tk) == a["tickerContractViolations"],
        f"ticker 계약 [0-9A-Z]{{6}} (위반 {len(bad_tk)}종목)")

    cal_days = cal["tradingDays"]
    cal_idx = {d: i for i, d in enumerate(cal_days)}
    off_cal = [x for x in rows if x["date"] not in cal_idx]
    diag["datesNotInCalendar"] = len(off_cal)
    diag["datesNotInCalendarSample"] = sorted({x["date"] for x in off_cal})[:20]
    chk(len(off_cal) == a["datesNotInCalendar"], f"캘린더 밖 날짜 {len(off_cal)}행")

    by_ticker = defaultdict(list)
    for x in rows:
        by_ticker[x["ticker"]].append(x)
    for xs in by_ticker.values():
        xs.sort(key=lambda x: x["date"])

    # A1b에는 market이 없다. name만 채우고 market은 null로 남긴다 — 폐지 종목의
    # 시장 구분을 얻을 경로가 없다는 것이 정찰의 결론이므로 추정하지 않는다.
    uni_by_ticker = {x["ticker"]: {"name": x.get("corpName"), "market": None}
                     for x in cand}

    # ── 품질 제외 (A2a와 공유하는 판별) ─────────────────────────
    viol, stats = A2A.find_violations(by_ticker, cal_idx, pol, diag)
    diag.update(stats)
    excluded = A2A.build_exclusions(viol, uni_by_ticker, by_ticker)
    ex_set = {e["ticker"] for e in excluded}
    diag["qualityExcluded"] = excluded
    diag["qualityExcludedCount"] = len(excluded)
    diag["qualityExcludedByReason"] = dict(Counter(e["reason"] for e in excluded))
    ex_rate = len(ex_set) / max(len(by_ticker), 1)
    diag["qualityExcludedRate"] = round(ex_rate, 5)
    # A2a는 이 검사가 FAIL이다. A2b에는 폐지 종목의 실측이 없어 WARN으로 시작한다 —
    # 정리매매 구간의 가격 급변이 A2a보다 잦을 수 있다. 첫 수집 후 승격한다.
    warn(ex_rate <= a["qualityExcludedRateWarn"],
         f"품질 제외율 {ex_rate*100:.2f}% <= {a['qualityExcludedRateWarn']*100:.0f}% "
         f"({len(ex_set)}종목 / {len(by_ticker)}) {diag['qualityExcludedByReason']}")

    kept = {tk: xs for tk, xs in by_ticker.items() if tk not in ex_set}
    residual, kept_stats = A2A.find_violations(kept, cal_idx, pol, diag)
    diag["keptZeroVolumeTransitions"] = kept_stats["zeroVolumeTransitions"]
    diag["keptComparableTransitions"] = kept_stats["comparableTransitions"]
    chk(len(residual) == a["residualDailyChangeViolations"],
        f"제외 후 잔여 ±{pol['acceptance']['dailyChangeAbsMax']*100:.0f}% 위반 "
        f"{len(residual)}종목")

    # ── 차이 1 — 기대 거래일을 상장기간으로 한정한다 ─────────────
    first_traded = {tk: xs[0]["date"] for tk, xs in kept.items()}
    last_traded = {tk: xs[-1]["date"] for tk, xs in kept.items()}
    expected = {tk: sum(1 for d in cal_days if first_traded[tk] <= d <= last_traded[tk])
                for tk in kept}
    total_exp = sum(expected.values())
    total_got = sum(len(v) for v in kept.values())
    rate = 1 - (total_got / total_exp) if total_exp else 1
    diag["expectedRowsBasis"] = a2b["expectedRows"]["basis"]
    diag["expectedRows"] = total_exp
    diag["missingRate"] = round(rate, 5)
    warn(rate <= a["missingRateWarn"],
         f"거래일 누락률 {rate*100:.3f}% <= {a['missingRateWarn']*100:.0f}% "
         f"(기대 {total_exp} / 실측 {total_got}) — 상장기간 한정 기준")

    worst = sorted(
        ({"ticker": tk, "firstTraded": first_traded[tk], "lastTraded": last_traded[tk],
          "expected": expected[tk], "got": len(kept[tk]),
          "missingRate": round(1 - len(kept[tk]) / expected[tk], 4)}
         for tk in kept if expected[tk] > 0),
        key=lambda x: -x["missingRate"])
    over = [w for w in worst if w["missingRate"] > a["perTickerMissingRateWarn"]]
    diag["perTickerMissingWorst"] = worst[:50]
    diag["perTickerMissingOver"] = over[:50]
    warn(not over,
         f"종목별 누락률 {a['perTickerMissingRateWarn']*100:.0f}% 초과 {len(over)}종목 "
         f"{[w['ticker'] for w in over[:5]]} (폐지 전 장기 거래정지 — 정상 시장 상태)")

    # ── 차이 4 — 커버리지의 분모 ────────────────────────────────
    analysis_from = cal["analysisFrom"]
    in_window = {tk for tk in kept if last_traded[tk] >= analysis_from}
    diag["analysisFrom"] = analysis_from
    diag["candidateCount"] = len(cand)
    diag["tickersWithData"] = len(kept)
    diag["tickersInAnalysisWindow"] = len(in_window)
    diag["tickersOutOfAnalysisWindow"] = len(kept) - len(in_window)
    # A1b 후보 전체를 분모로 쓴 비율. 게이트가 아니라 정찰 대조용으로만 남긴다.
    diag["rawCandidateCoverageRate"] = round(len(kept) / max(len(cand), 1), 4)
    diag["coverageAssumesFailuresOutOfWindow"] = True
    diag["coverageAssumptionNote"] = a2b["coverage"]["assumptionNote"]

    chk(len(kept) >= a["minTickersWithData"],
        f"데이터 확보 종목 {len(kept)} >= {a['minTickersWithData']} "
        f"(후보 {len(cand)} − 품질 제외 {len(ex_set)}) [정찰 전수 실측 631]")
    chk(len(in_window) >= a["minTickersInAnalysisWindow"],
        f"분석 구간({analysis_from}) 내 폐지 {len(in_window)} >= "
        f"{a['minTickersInAnalysisWindow']} [정찰 전수 실측 572]")

    empty_rate = diag["emptyCount"] / max(len(cand), 1)
    diag["emptyRate"] = round(empty_rate, 4)
    warn(empty_rate <= a["emptyRateWarn"],
         f"빈 응답률 {empty_rate*100:.1f}% <= {a['emptyRateWarn']*100:.0f}% "
         f"({diag['emptyCount']}/{len(cand)}) — 구간 밖 폐지는 정상이다")

    # ── 차이 3 — exitAt 확정 ────────────────────────────────────
    cand_by_ticker = {x["ticker"]: x for x in cand}

    def _norm(d):
        d = d or ""
        return f"{d[:4]}-{d[4:6]}-{d[6:]}" if len(d) == 8 and d.isdigit() else d

    # 소스를 정책에서 읽어 분기한다. 상수로 박아두면 아래 세 검사가 자기 자신을
    # 검사하는 동어반복이 되고, 게이트가 아무것도 막지 못한다(교훈45).
    # 이렇게 두면 dartModifyDate로 바꾸는 순간 게이트가 걸린다 — 그 경로가 실제로
    # 시도될 만한 지름길이라 막는 것이 목적이다.
    src = a2b["exitAt"]["source"]
    exits = []
    for tk in sorted(kept):
        c = cand_by_ticker.get(tk, {})
        if src == "lastTradedDate":
            val = last_traded[tk]
        elif src == "dartModifyDate":
            val = _norm(c.get("dartModifyDate"))
        else:
            val = None
        exits.append({
            "ticker": tk,
            "corp": c.get("corp"),
            "corpName": c.get("corpName"),
            "exitAtConfirmed": val,
            "exitAtSource": src,
            "firstTraded": first_traded[tk],
            "tradingDays": len(kept[tk]),
            "inAnalysisWindow": tk in in_window,
            "dartModifyDate": c.get("dartModifyDate"),
        })

    chk(src in ("lastTradedDate",),
        f"exitAt 소스 '{src}' — 허용된 값은 lastTradedDate뿐이다")

    miss = [e for e in exits if not e["exitAtConfirmed"]]
    chk(len(miss) == a["exitAtMissing"], f"exitAt 누락 {len(miss)}종목")
    not_td = [e for e in exits if e["exitAtConfirmed"] not in cal_idx]
    chk(len(not_td) == a["exitAtNotTradingDay"],
        f"exitAt이 캘린더 거래일이 아닌 종목 {len(not_td)}건")
    # 값의 출처 계약 — exitAt은 그 종목이 실제로 거래한 날 중 하나여야 한다.
    # dartModifyDate는 그 종목의 거래일과 일치할 이유가 없으므로 여기서 걸린다.
    traded = {tk: {x["date"] for x in xs} for tk, xs in kept.items()}
    off_rows = [e for e in exits if e["exitAtConfirmed"] not in traded[e["ticker"]]]
    chk(len(off_rows) == a["exitAtNotInTickerRows"],
        f"exitAt이 그 종목의 거래일이 아닌 종목 {len(off_rows)}건 "
        f"{[e['ticker'] for e in off_rows[:5]]}")
    count_diff = abs(len(exits) - len(kept))
    chk(count_diff == a["exitAtCountMismatch"],
        f"exitAt 레코드 {len(exits)}건 = 확보 종목 {len(kept)}건 (차 {count_diff})")

    # dartModifyDate를 exitAt으로 쓰면 안 된다는 것을 실측으로 남긴다.
    # 같은 날인 경우가 없지는 않으나(우연) 분포가 그것이 폐지일이 아님을 보인다.
    diffs = []
    for e in exits:
        dm = _norm(e.get("dartModifyDate"))
        # exitAt이 비어 있는 경로(소스 오지정)에서도 진단은 남아야 한다 —
        # 여기서 죽으면 게이트가 판정을 내리기 전에 중단되고 진단 파일이 없다(교훈39).
        if DATE_RE.match(dm or "") and DATE_RE.match(e["exitAtConfirmed"] or ""):
            diffs.append((e["exitAtConfirmed"], dm))
    same = sum(1 for a_, b_ in diffs if a_ == b_)
    later = sum(1 for a_, b_ in diffs if b_ > a_)
    earlier = sum(1 for a_, b_ in diffs if b_ < a_)
    diag["exitAtVsDartModifyDate"] = {
        "comparable": len(diffs), "same": same,
        "dartLater": later, "dartEarlier": earlier,
        "note": "dartModifyDate는 DART 레코드 최종 수정일이지 폐지일이 아니다. "
                "이 분포는 그 사실의 실측이며, 하류가 dartModifyDate를 exitAt으로 "
                "승격하지 못하게 하는 근거다.",
    }
    diag["exitAtIsLastTradedNotEffectiveDate"] = True
    diag["exitAtSemanticsNote"] = a2b["exitAt"]["semanticsNote"]

    # A1b 오분류 신호 — 지금도 거래 중일 가능성
    cutoff = cal_days[max(0, len(cal_days) - 1 - a["stillTradingSuspectDaysWarn"])]
    suspects = sorted(tk for tk in kept if last_traded[tk] >= cutoff)
    diag["stillTradingSuspects"] = suspects[:50]
    diag["stillTradingSuspectCount"] = len(suspects)
    warn(not suspects,
         f"마지막 거래일이 캘린더 끝 {a['stillTradingSuspectDaysWarn']}거래일 이내인 "
         f"종목 {len(suspects)}건 {suspects[:5]} — 폐지가 아니라 거래 중일 수 있다"
         f"(A1b 차집합의 오분류 신호)")

    keep_rows = [x for x in rows if x["ticker"] not in ex_set]
    return keep_rows, excluded, exits


# ── finalize ───────────────────────────────────────────────────
def run_finalize(pol):
    a2b = pol["a2b"]
    out_dir = a2b["output"]["dir"]
    shard_dir = a2b["output"]["shardDir"]
    gz_pol = {**pol, "output": a2b["output"]}
    diag_path = f"{out_dir}/_diagnostics.json"
    diag = {"stage": "A2b", "mode": "finalize", "pricePolicy": pol["version"],
            "environment": _kis_environment()}

    shard_files = sorted(glob.glob(f"{shard_dir}/shard-*.jsonl"))
    if not shard_files:
        _abort(f"{shard_dir}에 샤드 산출물이 없다 — 수집 잡을 먼저 돌려라", diag, diag_path)

    rows = []
    for p in shard_files:
        rows.extend(load_jsonl(p))
    diag["shardFiles"] = [os.path.basename(p) for p in shard_files]
    diag["shardCount"] = len(shard_files)
    diag["rowCount"] = len(rows)
    print(f"[1/3] 샤드 {len(shard_files)}개 병합 — {len(rows)}행")

    if not rows:
        _abort("병합 결과 0행", diag, diag_path)

    # 빈 응답·예외는 샤드 진단에만 남는다. 커버리지의 분모라서 finalize가 반드시
    # 모아야 한다 — A2a는 이 값을 쓰지 않으므로 여기가 A2a와 다른 곳이다.
    empty_n = exc_n = 0
    exc_sample = []
    for p in shard_files:
        d = f"{shard_dir}/_diagnostics-{os.path.basename(p).replace('.jsonl','')}.json"
        if not os.path.exists(d):
            _abort(f"샤드 진단 없음: {d} — 빈 응답 수를 모르면 커버리지를 셀 수 없다",
                   diag, diag_path)
        sd = load_json(d)
        if sd.get("smokeTest"):
            diag["smokeTest"] = True
        empty_n += sd.get("emptyCount", 0)
        exc_n += sd.get("exceptionCount", 0)
        exc_sample.extend(sd.get("exceptionTickers", [])[:10])
    diag["emptyCount"] = empty_n
    diag["exceptionCount"] = exc_n
    diag["exceptionSample"] = exc_sample[:20]

    cand = load_jsonl(UNIVERSE)
    cal = load_json(CALENDAR)
    diag["calendarStart"] = cal["tradingDays"][0]
    diag["calendarEnd"] = cal["tradingDays"][-1]
    diag["actualDataFrom"] = min(x["date"] for x in rows)
    diag["actualDataTo"] = max(x["date"] for x in rows)
    print(f"[2/3] 구간 — 캘린더 {diag['calendarStart']}~{diag['calendarEnd']} / "
          f"실측 {diag['actualDataFrom']}~{diag['actualDataTo']} · "
          f"빈 응답 {empty_n} · 예외 {exc_n}")

    rows, excluded, exits = validate(rows, cand, cal, pol, diag)
    diag["rowCountAfterExclusion"] = len(rows)
    diag["exitRecordCount"] = len(exits)

    os.makedirs(out_dir, exist_ok=True)
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

    print("\n[3/3] 연도 분할 · gzip")
    rows.sort(key=lambda x: (x["date"], x["ticker"]))
    by_year = defaultdict(list)
    for x in rows:
        by_year[x["date"][:4]].append(x)

    for old in glob.glob(f"{out_dir}/*.jsonl.gz"):
        os.remove(old)

    years = {}
    for y in sorted(by_year):
        raw, gz = A2A.write_gz(f"{out_dir}/{y}.jsonl.gz",
                               [{k: x[k] for k in FIELDS} for x in by_year[y]], gz_pol)
        years[y] = {"rows": len(by_year[y]), "rawBytes": raw, "gzBytes": gz}
        print(f"  {y}.jsonl.gz  {len(by_year[y]):>7}행  "
              f"{raw/1e6:6.1f}MB → {gz/1e6:5.1f}MB")
    diag["years"] = years

    # exitAt 확정값. A1b가 비워둔 칸을 채우는 산출물이며 EP(§6)가 읽는다.
    _, exit_bytes = A2A.write_gz(f"{out_dir}/{a2b['exitAt']['file']}", exits, gz_pol)
    print(f"  {a2b['exitAt']['file']}  {len(exits):>7}종목  {exit_bytes/1e3:5.1f}KB")

    qx = pol["qualityExclusion"]["file"]
    _, qx_bytes = A2A.write_gz(f"{out_dir}/{qx}", excluded, gz_pol)
    print(f"  {qx}  {len(excluded):>7}종목  {qx_bytes/1e3:5.1f}KB  "
          f"{diag['qualityExcludedByReason']}")

    diag["totalGzBytes"] = (sum(v["gzBytes"] for v in years.values())
                            + exit_bytes + qx_bytes)
    with open(diag_path, "w", encoding="utf-8", newline="\n") as f:
        json.dump(diag, f, ensure_ascii=False, indent=2)

    print(f"\n{out_dir} — 연도 {len(years)}개 + exitAt 1개 + 제외 1개 · {len(rows)}행 · "
          f"{diag['totalGzBytes']/1e6:.1f}MB")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--shard", type=int)
    ap.add_argument("--shards", type=int)
    ap.add_argument("--finalize", action="store_true")
    ap.add_argument("--limit", type=int, default=0,
                    help="스모크 테스트용. 진단에 smokeTest 플래그가 박히고 CI가 거부한다")
    args = ap.parse_args()

    if not os.path.exists(POLICY):
        print(f"{POLICY} 없음 — 정책 파일이 필요하다")
        return 1
    pol = load_json(POLICY)
    if "a2b" not in pol or "source" not in pol.get("a2b", {}):
        print(f"{POLICY}에 a2b.source 블록이 없다 — PR-1.5 미만이다")
        return 1

    if args.finalize:
        return run_finalize(pol)
    if args.shard is None:
        print("--shard N --shards M 또는 --finalize 중 하나가 필요하다")
        return 1
    shards = args.shards or pol["a2b"]["shards"]
    if not (0 <= args.shard < shards):
        print(f"--shard는 0 이상 {shards} 미만이어야 한다")
        return 1
    return run_shard(args.shard, shards, pol, args.limit)


if __name__ == "__main__":
    raise SystemExit(main())
