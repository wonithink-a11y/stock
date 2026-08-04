#!/usr/bin/env python3
"""
A1 — 시점별 유니버스 복원 + corp_code 구간 매핑 + 폐지 사유

백필의 병목이자 생존편향 제거의 전부다. 현재 살아 있는 종목만으로 과거를 채우면
백테스트는 '살아남은 기업만 대상으로 한 역사'가 된다.

입력: data/backfill/calendar.json (A0.5)
출력:
  data/backfill/universe/monthly.jsonl    월별 구성 (사실)
  data/backfill/universe/intervals.jsonl  ticker 구간 매핑 (effectiveFrom/To + corp_code)
  data/backfill/universe/_diagnostics.json 매핑 실패·중복·폐지사유 원문 분포

첫 실행의 목적은 완성이 아니라 **폐지 사유 원문 분포와 corp_code 매핑 품질 확보**다.
UNKNOWN이 많이 나오는 것이 정상이며, 그 원문 목록이 매핑 규칙의 입력이다.
"""
import io
import json
import os
import re
import sys
import time
import zipfile
from collections import defaultdict

CAL = "data/backfill/calendar.json"
OUT_DIR = "data/backfill/universe"
CACHE_CORP = "data/cache/corpCodeMap.json"
MARKETS = ["KOSPI", "KOSDAQ"]
DART_KEY = os.environ.get("DART_API_KEY", "")

# ── 네트워크 가드 ──────────────────────────────────────────────
# pykrx는 requests에 timeout을 넘기지 않는다. KRX가 응답을 끌면 요청 하나가 무한 대기하고,
# 재시도 4회 × 148개월이 곱해져 14시간짜리 '무한 루프'가 된다. 어댑터 기본값을 강제한다.
# 동시에 KRX 원본 응답 앞부분을 보관한다 — 실패 원인(로그인 페이지인지 차단인지)의 유일한 증거다.
import requests as _rq

LAST_KRX = {"url": None, "status": None, "head": None}
_orig_send = _rq.adapters.HTTPAdapter.send


def _send(self, request, **kw):
    if kw.get("timeout") is None:
        kw["timeout"] = (10, 20)          # (connect, read)
    r = _orig_send(self, request, **kw)
    if "krx.co.kr" in (request.url or "") and not kw.get("stream"):
        try:
            LAST_KRX.update(url=request.url, status=r.status_code, head=(r.text or "")[:800])
        except Exception:  # noqa: BLE001
            pass
    return r


_rq.adapters.HTTPAdapter.send = _send

fails, warns = [], []


def chk(cond, msg):
    print(("  OK  " if cond else "  FAIL") + "  " + msg)
    if not cond:
        fails.append(msg)


def warn(cond, msg):
    print(("  OK  " if cond else "  WARN") + "  " + msg)
    if not cond:
        warns.append(msg)


def _retry(fn, what, allow_empty=False, attempts=4):
    """빈 결과도 실패로 본다.

    A0.5에서 드러난 함정: pykrx의 @dataframe_empty_handler가 예외를 삼키고 빈 DataFrame을
    돌려주므로, 예외만 잡는 재시도는 한 번도 돌지 않는다. 그대로 두면 특정 월·종목이
    조용히 누락된 채 '성공'으로 기록된다 — 되돌리기 어려운 실패다.
    attempts: 정찰·폴백 경로는 짧게(2) 돌려 총 소요를 억제한다.
    """
    last = None
    for i in range(attempts):
        try:
            r = fn()
            empty = r is None or (hasattr(r, "empty") and r.empty) or (isinstance(r, (list, dict)) and len(r) == 0)
            if empty and not allow_empty:
                last = ValueError("빈 응답")
            else:
                return r
        except Exception as e:  # noqa: BLE001
            last = e
        if i < attempts - 1:
            time.sleep(2 ** i)
    print(f"    ! {what} 실패: {type(last).__name__}: {last}")
    return None


# ── 1. 월별 유니버스 ────────────────────────────────────────────
def _tickers_from_frame(df):
    if df is None or getattr(df, "empty", True):
        return None
    return {str(t).zfill(6): None for t in df.index}


def fetch_month(date_yyyymmdd, market, attempts=4):
    """4단계 폴백. A0.5에서 지수 API는 막히고 주식 API는 살아 있었듯 KRX는 엔드포인트별로
    가용성이 다르다(교훈25). 이름 없는 목록이라도 확보하는 쪽이 그 달을 통째로 버리는 것보다 낫다."""
    from pykrx.website import krx
    from pykrx import stock

    s = _retry(lambda: krx.get_market_ticker_and_name(date_yyyymmdd, market),
               f"{market} {date_yyyymmdd} (name)", attempts=attempts)
    if s is not None:
        return {str(t).zfill(6): str(n) for t, n in s.items()}

    lst = _retry(lambda: stock.get_market_ticker_list(date_yyyymmdd, market),
                 f"{market} {date_yyyymmdd} (list)", attempts=attempts)
    if lst is not None:
        return {str(t).zfill(6): None for t in lst}

    for fname in ("get_market_cap", "get_market_cap_by_ticker",
                  "get_market_ohlcv", "get_market_ohlcv_by_ticker"):
        fn = getattr(stock, fname, None)
        if fn is None:
            continue
        got = _tickers_from_frame(
            _retry(lambda f=fn: f(date_yyyymmdd, market=market),
                   f"{market} {date_yyyymmdd} ({fname})", attempts=2))
        if got:
            return got
    return None


def _abort(reason, extra):
    """실패해도 진단은 남긴다. KRX 원본 응답이 다음 라운드의 유일한 입력이다(교훈28)."""
    os.makedirs(OUT_DIR, exist_ok=True)
    with open(f"{OUT_DIR}/_diagnostics.json", "w", encoding="utf-8", newline="\n") as f:
        json.dump({"stage": "A1-preflight-abort", "reason": reason,
                   "krxCredentialsPresent": bool(os.environ.get("KRX_ID") and os.environ.get("KRX_PW")),
                   "krxLastResponse": LAST_KRX, **extra}, f, ensure_ascii=False, indent=2)
    print(f"\n중단: {reason}")
    print(f"  KRX 마지막 응답 status={LAST_KRX['status']} url={LAST_KRX['url']}")
    print(f"  head: {(LAST_KRX['head'] or '')[:400]}")
    sys.exit(2)


def collect_monthly(month_first):
    months = sorted(month_first.keys())

    # 정찰 — 최신월·최초월 각 1회. 여기서 전 경로가 막히면 148개월을 도는 의미가 없다.
    probes = [months[-1], months[0]]
    print(f"  정찰 {probes}")
    if not any(fetch_month(month_first[m].replace("-", ""), "KOSPI", attempts=2) for m in probes):
        _abort("KRX 종목목록 조회가 전 경로(name/list/cap/ohlcv)에서 실패", {"probedMonths": probes})

    out, streak = {}, 0
    for i, m in enumerate(months, 1):
        d = month_first[m].replace("-", "")
        per_market = {}
        for mk in MARKETS:
            got = fetch_month(d, mk)
            if got is None:
                print(f"    ! {m} {mk} 수집 불가 — 이 달은 기록하지 않는다(빈 달을 0종목으로 쓰면 전원 폐지로 오독된다)")
                per_market = None
                break
            per_market[mk] = got
        if per_market:
            out[m] = per_market
            streak = 0
        else:
            streak += 1
            # 일시 장애와 구조적 차단을 구분한다. 5개월 연속이면 후자다.
            if streak >= 5:
                _abort(f"연속 {streak}개월 수집 실패 — 일시 장애가 아니라 구조적 차단",
                       {"lastMonth": m, "collectedMonths": len(out)})
        if i % 12 == 0:
            print(f"  … {m} ({i}/{len(months)}) 수집 {len(out)}")
    return out


# ── 2. corp_code 매핑 ──────────────────────────────────────────
def load_corp_map():
    """stock_code → corp_code. 폐지 법인은 corpCode.xml에서 빠져 있을 수 있다 —
    그 누락률을 별도 리포트하지 않으면 생존편향이 corp_code 쪽 뒷문으로 들어온다."""
    if os.path.exists(CACHE_CORP):
        try:
            with open(CACHE_CORP, encoding="utf-8") as f:
                c = json.load(f)
            if isinstance(c, dict) and c.get("map"):
                print(f"  corpCodeMap 캐시 사용 ({len(c['map'])}건)")
                return c["map"]
        except Exception as e:  # noqa: BLE001
            print(f"  캐시 무시: {e}")

    if not DART_KEY:
        print("  ! DART_API_KEY 없음 — corp_code 매핑 생략")
        return {}

    import requests
    import xml.etree.ElementTree as ET

    url = f"https://opendart.fss.or.kr/api/corpCode.xml?crtfc_key={DART_KEY}"
    r = _retry(lambda: requests.get(url, timeout=60), "corpCode.xml")
    if r is None or r.status_code != 200:
        print("  ! corpCode.xml 수신 실패")
        return {}

    try:
        zf = zipfile.ZipFile(io.BytesIO(r.content))
        root = ET.fromstring(zf.read(zf.namelist()[0]).decode("utf-8"))
    except Exception as e:  # noqa: BLE001
        print(f"  ! corpCode.xml 파싱 실패: {e}")
        return {}

    m = {}
    for it in root.iter("list"):
        sc = (it.findtext("stock_code") or "").strip()
        cc = (it.findtext("corp_code") or "").strip()
        if sc and cc:
            m[sc] = cc
    os.makedirs(os.path.dirname(CACHE_CORP), exist_ok=True)
    with open(CACHE_CORP, "w", encoding="utf-8", newline="\n") as f:
        json.dump({"fetchedAt": time.strftime("%Y-%m-%d"), "map": m}, f, ensure_ascii=False)
    print(f"  corpCodeMap 신규 수집 ({len(m)}건)")
    return m


# ── 3. 폐지 사유 ───────────────────────────────────────────────
EXIT_PATTERNS = [
    ("AUDIT_OPINION",           r"감사의견|의견거절|한정"),
    ("CAPITAL_IMPAIRMENT",      r"자본잠식"),
    ("BANKRUPTCY",              r"파산|회생절차|부도|해산"),
    ("MERGED",                  r"합병|피흡수"),
    ("SPINOFF",                 r"분할"),
    ("VOLUNTARY",               r"자진|신청.*폐지|공개매수"),
    ("DELISTING_REVIEW_FAILED", r"실질심사|상장적격성"),
]


def map_exit_reason(raw):
    if not raw:
        return "UNKNOWN"
    for code, pat in EXIT_PATTERNS:
        if re.search(pat, raw):
            return code
    return "UNKNOWN"


def fetch_exit_reasons():
    """KIND 상장폐지 현황. 실패해도 A1 전체를 죽이지 않는다 —
    유니버스 복원(신뢰 가능)과 사유 수집(취약)은 실패 특성이 다르다."""
    import requests

    url = "https://kind.krx.co.kr/investwarn/delcompany.do"
    payload = {"method": "searchDelCompanyMain", "currentPageSize": "3000",
               "pageIndex": "1", "forward": "delcompany_down", "searchCodeType": "",
               "repIsuSrtCd": "", "searchCorpName": "", "orderMode": "1", "orderStat": "D"}
    try:
        r = requests.post(url, data=payload, timeout=60,
                          headers={"User-Agent": "Mozilla/5.0"})
        body = r.text
    except Exception as e:  # noqa: BLE001
        return {}, {"source": "unavailable", "error": f"{type(e).__name__}: {e}"}

    try:
        import pandas as pd
        tables = pd.read_html(io.StringIO(body))
    except Exception as e:  # noqa: BLE001
        return {}, {"source": "unavailable", "error": f"parse: {e}",
                    "responseBytes": len(body), "head": body[:1500]}

    for df in tables:
        cols = [str(c) for c in df.columns]
        code_col = next((c for c in cols if re.search(r"종목코드|단축코드", c)), None)
        reason_col = next((c for c in cols if re.search(r"사유|폐지사유", c)), None)
        date_col = next((c for c in cols if re.search(r"폐지일|상장폐지일", c)), None)
        if code_col and reason_col:
            out = {}
            for _, row in df.iterrows():
                code = re.sub(r"\D", "", str(row[code_col])).zfill(6)[-6:]
                if len(code) != 6:
                    continue
                out[code] = {"rawExitReason": str(row[reason_col]).strip(),
                             "exitAtSource": str(row[date_col]).strip() if date_col else None}
            if out:
                return out, {"source": "kind", "rows": len(out)}

    return {}, {"source": "unavailable", "error": "표에서 종목코드·사유 컬럼을 찾지 못함",
                "responseBytes": len(body), "tableCount": len(tables), "head": body[:1500]}


# ── 4. 구간 매핑 ───────────────────────────────────────────────
def build_intervals(monthly, month_first, corp_map, exit_info):
    months = sorted(monthly.keys())
    presence = defaultdict(list)   # ticker → [(month, market, name)]
    for m in months:
        for mk, d in monthly[m].items():
            for t, n in d.items():
                presence[t].append((m, mk, n))

    last_month = months[-1]
    idx = {m: i for i, m in enumerate(months)}
    intervals, name_changes = [], []

    for t, seq in presence.items():
        seq.sort(key=lambda x: x[0])
        # 연속 구간 분해. 중간에 빠졌다 돌아오면 재상장이므로 구간을 나눈다.
        runs, cur = [], [seq[0]]
        for prev, nxt in zip(seq, seq[1:]):
            if idx[nxt[0]] == idx[prev[0]] + 1:
                cur.append(nxt)
            else:
                runs.append(cur)
                cur = [nxt]
        runs.append(cur)

        names = [(m, n) for m, _, n in seq if n]
        hist = []
        for m, n in names:
            if not hist or hist[-1]["name"] != n:
                hist.append({"from": m, "name": n})
        if len(hist) > 1:
            name_changes.append({"ticker": t, "history": hist})

        for ri, run in enumerate(runs):
            fm, lm = run[0][0], run[-1][0]
            alive = (lm == last_month)
            gap = None
            if not alive:
                nxt = months[idx[lm] + 1] if idx[lm] + 1 < len(months) else None
                gap = [month_first[lm], month_first[nxt]] if nxt else None
            relisted = (not alive) and ri < len(runs) - 1
            ei = exit_info.get(t, {}) if (not alive and not relisted) else {}
            raw = ei.get("rawExitReason")
            intervals.append({
                "ticker": t,
                "name": run[-1][2],
                "corp": corp_map.get(t),
                "market": run[-1][1],
                "segment": ri,
                "effectiveFrom": month_first[fm],
                "effectiveTo": None if alive else month_first[lm],
                "firstObservedMonth": fm,
                "lastObservedMonth": lm,
                # 월 샘플링이라 폐지 시점은 점이 아니라 구간이다. 정확한 exitAt은 A2의
                # 마지막 가격일로 확정한다 — 하나를 고르지 말고 구간으로 보고한다(교훈7).
                "exitDetectedBetween": gap,
                "listingStatus": "ACTIVE" if alive else ("RELISTED" if relisted else "DELISTED"),
                "rawExitReason": raw,
                # RELISTED는 폐지가 아니라 공백이다 — EP-1.0의 continue 모드와 대응한다
                "exitReason": None if alive else ("RELISTED" if relisted else map_exit_reason(raw)),
                "exitAtSource": ei.get("exitAtSource"),
                "nameHistory": hist,
            })

    intervals.sort(key=lambda r: (r["ticker"], r["segment"]))
    return intervals, name_changes


# ── 5. 검증 ────────────────────────────────────────────────────
PREF = re.compile(r"우[B]?$|[0-9]우")


def validate(monthly, intervals, corp_map, exit_meta, diag):
    months = sorted(monthly.keys())
    print("\n[인수 조건]")

    dup = []
    for m in months:
        seen = set()
        for mk, d in monthly[m].items():
            for t in d:
                if t in seen:
                    dup.append(f"{m}/{t}")
                seen.add(t)
    chk(not dup, f"(month, ticker) 유일성 (중복 {len(dup)}건{': ' + ', '.join(dup[:5]) if dup else ''})")

    # (month, corp) 유일성은 FAIL 기준이 될 수 없다 — 우선주는 보통주와 corp_code를 공유한다
    # (삼성전자 005930 / 삼성전자우 005935 → 같은 법인). 중복을 우선주와 그 외로 나눠 본다.
    corp_dup_other = []
    for m in months:
        bag = defaultdict(list)
        for mk, d in monthly[m].items():
            for t in d:
                c = corp_map.get(t)
                if c:
                    bag[c].append(t)
        for c, ts in bag.items():
            if len(ts) > 1 and not any(PREF.search(x) or not x.endswith("0") for x in ts[1:]):
                corp_dup_other.append(f"{m}/{c}:{','.join(ts)}")
    warn(not corp_dup_other,
         f"(month, corp) 중복 중 우선주로 설명 안 되는 건 {len(corp_dup_other)}건 (사람 확인 필요)")

    counts = {m: sum(len(d) for d in monthly[m].values()) for m in months}
    jump = [f"{b}({counts[a]}→{counts[b]})" for a, b in zip(months, months[1:])
            if counts[a] and abs(counts[b] - counts[a]) / counts[a] > 0.05]
    chk(not jump, f"월간 종목 수 변화 ±5% 이내 (이상 {len(jump)}건{': ' + ', '.join(jump[:5]) if jump else ''})")

    gone = [r for r in intervals if r["listingStatus"] == "DELISTED"]
    chk(len(gone) > 0, f"폐지 감지 > 0건 (0이면 생존편향 제거 실패) — {len(gone)}건")
    chk(len(gone) >= 100, f"10년 폐지 감지 >= 100건 (실측 {len(gone)}건)")

    if corp_map:
        miss = [r for r in intervals if not r["corp"]]
        miss_gone = [r for r in gone if not r["corp"]]
        rate = len(miss) / len(intervals) * 100
        grate = (len(miss_gone) / len(gone) * 100) if gone else 0
        warn(rate < 10, f"corp_code 매핑 실패율 전체 {rate:.1f}% ({len(miss)}/{len(intervals)})")
        # 전체 실패율에 묻히면 안 보인다. 폐지 종목은 반드시 따로 본다.
        warn(grate < 30, f"corp_code 매핑 실패율 **폐지종목** {grate:.1f}% ({len(miss_gone)}/{len(gone)})")
    else:
        warns.append("corp_code 매핑 없음 (DART_API_KEY 미설정)")
        print("  WARN  corp_code 매핑 없음 — A3 조인 전에 반드시 채워야 한다")

    unk = [r for r in gone if r["exitReason"] == "UNKNOWN"]
    if exit_meta.get("source") == "kind":
        n, ratio = len(unk), (len(unk) / len(gone) if gone else 0)
        chk(not ((ratio > 0.20 and n > 30) or n > 100),
            f"exitReason UNKNOWN {n}건 / {ratio*100:.1f}% (FAIL: 비율>20% AND 건수>30, 또는 건수>100)")
    else:
        # 소스가 아예 없는 것을 '전건 UNKNOWN 실패'로 처리하면 유니버스 산출물까지 버리게 된다.
        # 판정 불가를 실패로도 통과로도 위조하지 않고, 보류 상태로 명시한다.
        print(f"  HOLD  폐지사유 소스 미확보({exit_meta.get('error','')[:60]}) — UNKNOWN 임계 판정 보류")
        diag["exitReasonsPending"] = True

    keys = [(r["ticker"], r["segment"]) for r in intervals]
    chk(len(set(keys)) == len(keys), f"(ticker, segment) 유일성 (중복 {len(keys) - len(set(keys))}건)")


# ── 6. main ────────────────────────────────────────────────────
def main():
    if not os.path.exists(CAL):
        print(f"{CAL} 없음 — A0.5를 먼저 실행하라")
        sys.exit(1)
    with open(CAL, encoding="utf-8") as f:
        cal = json.load(f)
    month_first = cal["monthFirst"]
    print(f"캘린더 {cal['from']} ~ {cal['to']} · {len(month_first)}개월")

    print("\n[1/4] 월별 유니버스")
    monthly = collect_monthly(month_first)
    if not monthly:
        print("수집 실패")
        sys.exit(1)

    print("\n[2/4] corp_code 매핑")
    corp_map = load_corp_map()

    print("\n[3/4] 폐지 사유")
    exit_info, exit_meta = fetch_exit_reasons()
    print(f"  source={exit_meta.get('source')} rows={exit_meta.get('rows', 0)}")

    print("\n[4/4] 구간 매핑")
    intervals, name_changes = build_intervals(monthly, month_first, corp_map, exit_info)
    print(f"  구간 {len(intervals)}건 · 사명변경 {len(name_changes)}종목")

    gone = [r for r in intervals if r["listingStatus"] == "DELISTED"]
    raw_dist = defaultdict(int)
    for r in gone:
        raw_dist[r["rawExitReason"] or "(없음)"] += 1

    diag = {
        "monthsCollected": len(monthly),
        "monthsExpected": len(month_first),
        "intervals": len(intervals),
        "delisted": len(gone),
        "relisted": sum(1 for r in intervals if r["listingStatus"] == "RELISTED"),
        "exitReasonSource": exit_meta,
        # 원문을 남기지 않으면 매핑 규칙을 개선할 수 없다. 첫 실행의 실제 산출물이 이것이다.
        "rawExitReasonDistribution": dict(sorted(raw_dist.items(), key=lambda x: -x[1])),
        "exitReasonMapped": dict(sorted(
            defaultdict(int, {r["exitReason"]: sum(1 for x in gone if x["exitReason"] == r["exitReason"])
                              for r in gone}).items(), key=lambda x: -x[1])),
        "nameChanges": name_changes,
        "corpCodeMissing": [r["ticker"] for r in intervals if not r["corp"]][:500],
        "corpCodeMissingDelisted": [r["ticker"] for r in gone if not r["corp"]],
    }

    validate(monthly, intervals, corp_map, exit_meta, diag)

    os.makedirs(OUT_DIR, exist_ok=True)
    with open(f"{OUT_DIR}/monthly.jsonl", "w", encoding="utf-8", newline="\n") as f:
        for m in sorted(monthly):
            for mk in MARKETS:
                if mk in monthly[m]:
                    f.write(json.dumps({"m": m, "date": month_first[m], "market": mk,
                                        "tickers": sorted(monthly[m][mk])},
                                       ensure_ascii=False, sort_keys=False) + "\n")
    with open(f"{OUT_DIR}/intervals.jsonl", "w", encoding="utf-8", newline="\n") as f:
        for r in intervals:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    with open(f"{OUT_DIR}/_diagnostics.json", "w", encoding="utf-8", newline="\n") as f:
        json.dump(diag, f, ensure_ascii=False, indent=2)

    print(f"\n{OUT_DIR}/ — 월 {len(monthly)} · 구간 {len(intervals)} · 폐지 {len(gone)}")
    print(f"폐지사유 원문 상위: {list(diag['rawExitReasonDistribution'].items())[:8]}")
    if warns:
        print(f"\nWARN {len(warns)}건 (실패 아님, 확인 필요):")
        for w in warns:
            print(f"  - {w}")
    if fails:
        print(f"\n인수 조건 {len(fails)}건 실패")
        sys.exit(1)


if __name__ == "__main__":
    main()
