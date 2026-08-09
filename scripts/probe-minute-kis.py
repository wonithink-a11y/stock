"""probe-minute-kis.py — 분봉 T0 정찰 (KIS 주식일별분봉조회)

정찰은 질문에 답하는 프로그램이지 데이터를 모으는 프로그램이 아니다.
재시도·resume·manifest·샤딩을 넣지 않는다(교훈39·51).
산출물은 데이터가 아니라 패턴이다.

채우는 빈칸은 docs/MN-1.0-분봉Raw저장계약.md §6의 11개 + 즉시 재조회 재현성이다.
개수로 적지 않고 CHECKLIST 리터럴 목록으로 못 박는다(교훈59).

입력: .env의 KIS_APP_KEY · KIS_APP_SECRET
      data/backfill/calendar.json (영업일 선택)
      data/backfill/price/a2a/*.jsonl.gz (수정주가·거래량 대조군, 없으면 건너뛴다)
출력: data/backfill/_probe-minute-kis.json

주의: 토큰은 갱신 6시간·발급 5분당 1회 제한이 있다. 캐시를 반드시 쓴다.
      시각은 전부 KST로 적는다.
"""

import gzip
import json
import os
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

import requests

for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(errors="replace")
    except Exception:
        pass

REPO = Path(__file__).resolve().parent.parent
OUT = REPO / "data" / "backfill" / "_probe-minute-kis.json"
TOKEN_CACHE = REPO / ".token_cache_kis.json"
CALENDAR = REPO / "data" / "backfill" / "calendar.json"
A2A_DIR = REPO / "data" / "backfill" / "price" / "a2a"

KST = timezone(timedelta(hours=9))
BASE = "https://openapi.koreainvestment.com:9443"
PATH_DAILY_MIN = "/uapi/domestic-stock/v1/quotations/inquire-time-dailychartprice"
TR_DAILY_MIN = "FHKST03010230"
# 수정주가 판정용. 이 엔드포인트만 수정/원주가 플래그를 가진다.
PATH_DAILY = "/uapi/domestic-stock/v1/quotations/inquire-daily-itemchartprice"
TR_DAILY = "FHKST03010100"

TICKER = "005930"        # 삼성전자. 유동성이 높아 빈 분이 적다
TICKER_THIN = "000020"   # 동화약품. 거래가 얇은 쪽의 응답을 함께 본다

# 이 목록이 T0의 범위다. 늘리거나 줄이려면 여기를 고친다.
CHECKLIST = [
    "1_보존기간", "2_페이지크기", "3_페이지네이션", "4_ratelimit",
    "5_수정주가", "6_타임존과캔들기준", "7_거래량의미", "8_휴장일응답",
    "9_모의계좌", "10_오류코드체계", "11_거래정지액면분할",
    "12_즉시재조회재현성",
]


def now_kst():
    return datetime.now(KST)


def stamp():
    return now_kst().strftime("%Y-%m-%d %H:%M:%S KST")


def say(msg=""):
    print(msg, flush=True)


# ---------------------------------------------------------------- 자격증명

def load_env():
    env = {}
    p = REPO / ".env"
    if p.exists():
        for line in p.read_text(encoding="utf-8").splitlines():
            k, _, v = line.partition("=")
            if k.strip():
                env[k.strip()] = v.strip()
    # 환경변수가 있으면 그쪽이 이긴다.
    for k in ("KIS_APP_KEY", "KIS_APP_SECRET"):
        if os.environ.get(k):
            env[k] = os.environ[k]
    return env


ENV = load_env()
KEY = ENV.get("KIS_APP_KEY", "")
SECRET = ENV.get("KIS_APP_SECRET", "")

# 문자열이 나가는 지점에서 지운다. 자르기 전에 지운다(교훈65).
_SECRETS = [v for v in (KEY, SECRET) if v]


def scrub(s, limit=500):
    s = str(s)
    for v in _SECRETS:
        s = s.replace(v, "<redacted>")
    tok = _TOKEN.get("value")
    if tok:
        s = s.replace(tok, "<token>")
    return s[:limit]


_TOKEN = {}


def get_token():
    """캐시가 유효하면 재사용한다. 발급은 5분당 1회·갱신은 6시간 초과 시다."""
    if TOKEN_CACHE.exists():
        try:
            c = json.loads(TOKEN_CACHE.read_text(encoding="utf-8"))
            exp = datetime.fromisoformat(c["expiresAt"])
            if exp.tzinfo is None:
                exp = exp.replace(tzinfo=KST)
            # 만료 10분 전부터는 새로 받는다.
            if exp - timedelta(minutes=10) > now_kst() and c.get("appKeyTail") == KEY[-4:]:
                _TOKEN["value"] = c["accessToken"]
                say("  토큰: 캐시 재사용 (만료 " + c["expiresAt"] + ")")
                return c["accessToken"]
        except Exception:
            pass

    say("  토큰: 신규 발급")
    r = requests.post(
        BASE + "/oauth2/tokenP",
        data=json.dumps({"grant_type": "client_credentials",
                         "appkey": KEY, "appsecret": SECRET}),
        headers={"content-type": "application/json"}, timeout=20,
    )
    body = r.json()
    if r.status_code != 200 or "access_token" not in body:
        raise SystemExit("토큰 발급 실패: " + scrub(json.dumps(body, ensure_ascii=False)))

    tok = body["access_token"]
    _TOKEN["value"] = tok
    TOKEN_CACHE.write_text(json.dumps({
        "accessToken": tok,
        "expiresAt": body.get("access_token_token_expired", ""),
        "issuedAt": stamp(),
        "appKeyTail": KEY[-4:],
    }, ensure_ascii=False, indent=2), encoding="utf-8")
    try:
        os.chmod(TOKEN_CACHE, 0o600)
    except Exception:
        pass
    return tok


# ---------------------------------------------------------------- 호출

CALL_LOG = []


def compact(date):
    """'2026-08-03' -> '20260803'. API는 구분자를 받지 않는다."""
    return "".join(c for c in str(date) if c.isdigit())


def call_minute(ticker, date, hour="153000", past="Y", mrkt="J", fake="",
                timeout=15, raw_date=False):
    """주식일별분봉조회 1회. 예외를 던지지 않고 결과 dict로 돌려준다.

    raw_date=True면 date를 그대로 보낸다(형식 오류 사례 측정용).
    """
    t0 = time.time()
    sent = str(date) if raw_date else compact(date)
    rec = {"ticker": ticker, "date": date, "sentDate": sent, "hour": hour,
           "past": past, "at": stamp()}
    try:
        r = requests.get(
            BASE + PATH_DAILY_MIN,
            headers={
                "content-type": "application/json",
                "authorization": "Bearer " + _TOKEN["value"],
                "appkey": KEY, "appsecret": SECRET,
                "tr_id": TR_DAILY_MIN, "custtype": "P",
            },
            params={
                "FID_COND_MRKT_DIV_CODE": mrkt,
                "FID_INPUT_ISCD": ticker,
                "FID_INPUT_HOUR_1": hour,
                "FID_INPUT_DATE_1": sent,
                "FID_PW_DATA_INCU_YN": past,
                "FID_FAKE_TICK_INCU_YN": fake,
            },
            timeout=timeout,
        )
    except Exception as e:
        rec.update({"transport": scrub(type(e).__name__ + ": " + str(e)),
                    "elapsed": round(time.time() - t0, 3)})
        CALL_LOG.append(rec)
        return rec

    rec["http"] = r.status_code
    rec["elapsed"] = round(time.time() - t0, 3)
    try:
        b = r.json()
    except Exception:
        rec["bodyNotJson"] = scrub(r.text, 200)
        CALL_LOG.append(rec)
        return rec

    rec["rtCd"] = b.get("rt_cd")
    rec["msgCd"] = b.get("msg_cd")
    rec["msg"] = scrub(b.get("msg1", ""), 120)
    o2 = b.get("output2") or []
    rec["rows"] = len(o2)
    rec["respDates"] = sorted({r.get("stck_bsop_date") for r in o2})
    # 요청한 날짜가 응답에 없으면 API가 질문을 무시한 것이다.
    # 실측: 날짜를 '2026-08-03'으로 보내면 형식 오류를 알리지 않고
    # 최근 영업일을 돌려준다. 성공으로 세면 보존 기간이 3년으로 잡힌다.
    rec["dateHonored"] = (sent in rec["respDates"]) if o2 else None
    rec["output1"] = b.get("output1") or {}
    rec["output2"] = o2
    CALL_LOG.append(rec)
    return rec


def ok(rec, need_date=True):
    """성공은 '응답이 왔다'가 아니라 '내가 물은 것에 답했다'이다."""
    if rec.get("rtCd") != "0" or rec.get("rows", 0) <= 0:
        return False
    if need_date and rec.get("dateHonored") is not True:
        return False
    return True


# ---------------------------------------------------------------- 대조군

def trading_days():
    d = json.loads(CALENDAR.read_text(encoding="utf-8"))
    return d["tradingDays"]


def call_daily(ticker, d1, d2, adj):
    """국내주식기간별시세. adj '0'=수정주가 '1'=원주가."""
    try:
        r = requests.get(
            BASE + PATH_DAILY,
            headers={"content-type": "application/json",
                     "authorization": "Bearer " + _TOKEN["value"],
                     "appkey": KEY, "appsecret": SECRET,
                     "tr_id": TR_DAILY, "custtype": "P"},
            params={"FID_COND_MRKT_DIV_CODE": "J", "FID_INPUT_ISCD": ticker,
                    "FID_INPUT_DATE_1": compact(d1), "FID_INPUT_DATE_2": compact(d2),
                    "FID_PERIOD_DIV_CODE": "D", "FID_ORG_ADJ_PRC": adj},
            timeout=15)
        b = r.json()
    except Exception as e:
        return {"err": scrub(type(e).__name__ + ": " + str(e))}
    o2 = b.get("output2") or []
    rows = {x.get("stck_bsop_date"): x for x in o2 if x.get("stck_bsop_date")}
    return {"rtCd": b.get("rt_cd"), "msg": scrub(b.get("msg1", ""), 80),
            "rows": rows}


def a2a_day(date):
    """A2a 일봉에서 그 날짜의 전 종목. 없으면 빈 dict."""
    p = A2A_DIR / (date[:4] + ".jsonl.gz")
    if not p.exists():
        return {}
    out = {}
    try:
        with gzip.open(p, "rt", encoding="utf-8") as f:
            for line in f:
                if date not in line:
                    continue
                r = json.loads(line)
                if r.get("date") == date:
                    out[r["ticker"]] = r
    except Exception:
        return {}
    return out


def a2a_daily(ticker, date):
    """A2a 일봉(수정주가)에서 한 행. 없으면 None."""
    year = date[:4]
    p = A2A_DIR / (year + ".jsonl.gz")
    if not p.exists():
        return None
    try:
        with gzip.open(p, "rt", encoding="utf-8") as f:
            for line in f:
                if ('"' + ticker + '"') not in line or date not in line:
                    continue
                r = json.loads(line)
                if r.get("ticker") == ticker and r.get("date") == date:
                    return r
    except Exception:
        return None
    return None


# ---------------------------------------------------------------- 정찰

def main():
    if not KEY or not SECRET:
        raise SystemExit("KIS_APP_KEY / KIS_APP_SECRET 이 없다. .env를 본다.")

    started = time.time()
    say()
    say("  분봉 T0 정찰 — " + stamp())
    say()

    get_token()

    days = trading_days()
    recent = days[-1]              # 캘린더 마지막 영업일
    findings = {k: {"status": "미측정"} for k in CHECKLIST}
    ev = {}   # 근거

    # --- 기준 호출 : 스키마·페이지 크기 ------------------------------------
    say("  [1] 기준 호출 " + TICKER + " " + recent)
    base = call_minute(TICKER, recent)
    ev["baseCall"] = {k: base.get(k) for k in
                      ("http", "rtCd", "msgCd", "msg", "rows", "elapsed",
                       "sentDate", "respDates", "dateHonored")}

    if not ok(base):
        say("      실패: " + str(base.get("msg")) + " (rt_cd=" + str(base.get("rtCd")) + ")")
        # 실패해도 진단은 남긴다(교훈39).
    else:
        o2 = base["output2"]
        ev["output1Fields"] = sorted(base["output1"].keys())
        ev["output2Fields"] = sorted(o2[0].keys())
        ev["output2SampleFirst"] = o2[0]
        ev["output2SampleLast"] = o2[-1]

        findings["2_페이지크기"] = {
            "status": "측정됨",
            "rowsPerCall": len(o2),
            "문서값": "실전 120건",
            "일치": len(o2) == 120,
        }

        # --- 6 타임존·캔들 기준시각 ---------------------------------------
        hours = [r.get("stck_cntg_hour") for r in o2]
        dates = sorted({r.get("stck_bsop_date") for r in o2})
        uniq = sorted(set(hours))
        gaps = sorted({int(uniq[i + 1]) - int(uniq[i])
                       for i in range(len(uniq) - 1)}) if len(uniq) > 1 else []
        findings["6_타임존과캔들기준"] = {
            "status": "측정됨",
            "요청일자": recent,
            "응답일자집합": dates,
            "시각최소": uniq[0] if uniq else None,
            "시각최대": uniq[-1] if uniq else None,
            "정렬": ("내림차순" if hours == sorted(hours, reverse=True)
                    else "오름차순" if hours == sorted(hours) else "불규칙"),
            "간격종류": gaps[:5],
            "주석": "09:00 개장. 첫 캔들 시각이 090000이면 시작시각, "
                    "090100이면 종료시각 기준으로 읽는다",
        }

        # --- 7 거래량 의미 ------------------------------------------------
        try:
            vols = [int(r.get("cntg_vol", 0)) for r in o2]
            asc = list(reversed(vols)) if hours == sorted(hours, reverse=True) else vols
            monotonic = all(asc[i] <= asc[i + 1] for i in range(len(asc) - 1))
            findings["7_거래량의미"] = {
                "status": "측정됨",
                "필드": "cntg_vol",
                "구간합": sum(vols),
                "단조증가": monotonic,
                "판정": "누적" if monotonic else "구간(그 1분)",
                "output1_acml_vol": base["output1"].get("acml_vol"),
                "주석": "단조증가면 누적이다. naver 경로는 실측에서 누적이었다",
            }
        except Exception as e:
            findings["7_거래량의미"] = {"status": "실패", "이유": scrub(e)}

    # --- 3 페이지네이션 -----------------------------------------------------
    say("  [2] 페이지네이션")
    if ok(base):
        o2 = base["output2"]
        earliest = min(r["stck_cntg_hour"] for r in o2)
        nxt = call_minute(TICKER, recent, hour=earliest)
        got = set()
        if ok(nxt):
            got = {r["stck_cntg_hour"] for r in nxt["output2"]}
        prev = {r["stck_cntg_hour"] for r in o2}
        findings["3_페이지네이션"] = {
            "status": "측정됨" if ok(nxt) else "실패",
            "방식": "시각 커서 (FID_INPUT_HOUR_1 갱신)",
            "커서값": earliest,
            "다음페이지행수": nxt.get("rows"),
            "더과거를주는가": bool(got and min(got) < earliest),
            "겹침건수": len(got & prev),
            "주석": "커서는 응답의 최소 시각. 겹침이 있으면 수집기가 중복을 걸러야 한다",
        }
    time.sleep(0.2)

    # --- 12 즉시 재조회 재현성 ---------------------------------------------
    say("  [3] 즉시 재조회 재현성")
    again = call_minute(TICKER, recent)
    if ok(base) and ok(again):
        same = base["output2"] == again["output2"]
        findings["12_즉시재조회재현성"] = {
            "status": "측정됨",
            "동일": same,
            "행수": [base["rows"], again["rows"]],
            "주석": "T0는 '지금 두 번 부르면 같은가'다. "
                    "'며칠 뒤 다시 받으면 같은가'는 T1이다",
        }
    time.sleep(0.2)

    # --- 5 수정주가 · 대조군 -------------------------------------------------
    say("  [4] 수정주가 대조 (A2a 일봉)")
    if ok(base):
        o2 = base["output2"]
        day_rows = [r for r in o2 if r.get("stck_bsop_date") == compact(recent)]
        if day_rows:
            hi = max(int(r["stck_hgpr"]) for r in day_rows)
            lo = min(int(r["stck_lwpr"]) for r in day_rows)
            ref = a2a_daily(TICKER, recent)
            findings["5_수정주가"] = {
                "status": "측정됨" if ref else "대조군없음",
                "분봉구간고가": hi, "분봉구간저가": lo,
                "a2a일봉": ref,
                "주석": "이 호출은 120건이라 하루 전체가 아니다. "
                        "고저 비교는 참고값이며 확정은 하루 전체를 모은 뒤다. "
                        "엔드포인트에 수정주가 파라미터가 없다는 사실이 더 강한 신호다",
                "수정주가파라미터": "없음 (FID_* 목록에 adjust 계열 없음)",
            }

    # --- 8 휴장일 응답 -------------------------------------------------------
    say("  [5] 휴장일 응답")
    tset = set(days)
    holiday = None
    d = datetime.strptime(recent, "%Y-%m-%d")
    for i in range(1, 40):
        cand = (d - timedelta(days=i)).strftime("%Y-%m-%d")
        if cand not in tset:
            holiday = cand
            break
    if holiday:
        h = call_minute(TICKER, holiday)
        findings["8_휴장일응답"] = {
            "status": "측정됨",
            "휴장일": holiday,
            "http": h.get("http"), "rtCd": h.get("rtCd"),
            "msgCd": h.get("msgCd"), "msg": h.get("msg"),
            "rows": h.get("rows"),
            "dateHonored": h.get("dateHonored"),
            "형태": ("빈 응답" if h.get("rows") == 0 and h.get("rtCd") == "0"
                    else "오류" if h.get("rtCd") not in (None, "0")
                    else "요청 무시 · 다른 날짜 반환"
                    if h.get("dateHonored") is False
                    else "데이터 있음"),
            "응답일자": h.get("respDates"),
            "주석": "'조회하지 않음'과 '조회했더니 없음'은 다르다(교훈75). "
                    "휴장일이 빈 응답인지 다른 날짜로 대체되는지가 "
                    "수집기의 결손 기록 방식을 가른다",
        }
    time.sleep(0.2)

    # --- 10 오류 코드 체계 ---------------------------------------------------
    say("  [6] 오류 코드 체계")
    errs = {}
    for name, kw in (
        ("없는종목", dict(ticker="999999", date=recent)),
        ("잘못된시장코드", dict(ticker=TICKER, date=recent, mrkt="Z")),
        ("미래일자", dict(ticker=TICKER, date="20990101")),
        ("형식오류일자", dict(ticker=TICKER, date="notadate", raw_date=True)),
        # 이 정찰이 처음에 걸려 넘어진 함정. 오류를 내지 않고 다른 답을 준다.
        ("하이픈일자", dict(ticker=TICKER, date="2026-08-03", raw_date=True)),
    ):
        r = call_minute(**kw)
        errs[name] = {"http": r.get("http"), "rtCd": r.get("rtCd"),
                      "msgCd": r.get("msgCd"), "msg": r.get("msg"),
                      "rows": r.get("rows"), "sentDate": r.get("sentDate"),
                      "respDates": r.get("respDates"),
                      "dateHonored": r.get("dateHonored")}
        time.sleep(0.15)
    findings["10_오류코드체계"] = {
        "status": "측정됨", "사례": errs,
        "주석": "모르는 실패의 기본값은 재시도 가능이다(교훈56). "
                "이 표는 '재시도 불가'로 분류할 코드만 확정하는 데 쓴다. "
                "가장 위험한 것은 rt_cd=0으로 오는 실패다 — "
                "잘못된 일자 형식이 오류가 아니라 '다른 날짜의 정상 응답'이 된다",
    }

    # --- 1 보존 기간 ---------------------------------------------------------
    say("  [7] 보존 기간 (이분 탐색)")
    idx_last = len(days) - 1

    def has_data(i):
        dt = days[i]
        r = call_minute(TICKER, dt)
        time.sleep(0.15)
        return ok(r), r

    ladder = []
    lo_i, hi_i = None, None
    for back in (5, 20, 60, 120, 180, 240, 300, 360, 480, 720):
        i = idx_last - back
        if i < 0:
            break
        good, r = has_data(i)
        ladder.append({"영업일전": back, "일자": days[i], "데이터": good,
                       "rows": r.get("rows"), "msgCd": r.get("msgCd"),
                       "dateHonored": r.get("dateHonored"),
                       "응답일자": r.get("respDates")})
        say("      -" + str(back) + "영업일 " + days[i] + " → " +
            ("있음" if good else "없음"))
        if good:
            lo_i = i
        else:
            hi_i = i
            break

    boundary = None
    if lo_i is not None and hi_i is not None:
        a, b = hi_i, lo_i          # a: 없음(과거), b: 있음(최근)
        while b - a > 1:
            mid = (a + b) // 2
            good, _ = has_data(mid)
            if good:
                b = mid
            else:
                a = mid
        boundary = {"마지막가용일": days[b], "그이전": days[a],
                    "영업일수": idx_last - b}
        say("      경계: " + days[b] + " (약 " + str(idx_last - b) + "영업일)")

    findings["1_보존기간"] = {
        "status": "측정됨" if boundary else ("부분" if ladder else "실패"),
        "사다리": ladder, "경계": boundary,
        "문서값": "최대 1년 분봉 보관",
        "주석": "★ 백필 일정 전체가 여기 달렸다. "
                "경계는 오늘 기준이며 매일 하루씩 밀린다",
    }

    # --- 4 rate limit --------------------------------------------------------
    say("  [8] rate limit (동시 버스트)")
    # 순차로는 상한을 잴 수 없다. 호출 하나가 2초쯤 걸려 초당 0.5회를 넘지
    # 못하기 때문이다 — '막히지 않았다'가 '여유가 있다'로 잘못 읽힌다.
    # 상한은 동시성으로만 닿는다. 다만 신규 고객 초당 제한 공지가 있으므로
    # 8·16 두 라운드만 던지고 멈춘다. 상한 탐색이 아니라 존재 확인이다.
    from concurrent.futures import ThreadPoolExecutor

    ramp = []
    for n in (8, 16):
        t0 = time.time()
        with ThreadPoolExecutor(max_workers=n) as ex:
            res = list(ex.map(lambda _: call_minute(TICKER, recent, timeout=15),
                              range(n)))
        el = time.time() - t0
        bad = [{"http": x.get("http"), "rtCd": x.get("rtCd"),
                "msgCd": x.get("msgCd"), "msg": x.get("msg")}
               for x in res if x.get("http") != 200 or x.get("rtCd") not in ("0",)]
        ramp.append({"동시호출": n, "소요초": round(el, 2),
                     "실효초당": round(n / el, 1) if el else None,
                     "거부": len(bad), "거부샘플": bad[:3]})
        say("      동시 " + str(n) + "회 " + str(round(el, 2)) + "초 → 거부 " +
            str(len(bad)))
        if bad:
            break
        time.sleep(2.0)
    findings["4_ratelimit"] = {
        "status": "측정됨", "버스트": ramp,
        "거부발생": any(x["거부"] for x in ramp),
        "주석": "거부가 없으면 상한이 이 지점보다 높다는 뜻일 뿐 상한을 잰 것이 "
                "아니다. 순차 호출은 초당 0.5회라 상한 근처에도 못 간다 — "
                "배치 크기는 여기서 얻은 하한이 아니라 여유를 두고 정한다",
    }

    # --- 얇은 종목 -----------------------------------------------------------
    say("  [9] 거래 얇은 종목")
    thin = call_minute(TICKER_THIN, recent)
    ev["thinTicker"] = {"ticker": TICKER_THIN, "rows": thin.get("rows"),
                        "rtCd": thin.get("rtCd"), "msg": thin.get("msg")}
    if ok(thin):
        th = [r.get("stck_cntg_hour") for r in thin["output2"]]
        ev["thinTicker"]["시각최소"] = min(th)
        ev["thinTicker"]["시각최대"] = max(th)
        ev["thinTicker"]["거래량0인분"] = sum(
            1 for r in thin["output2"] if int(r.get("cntg_vol", 0)) == 0)

    # --- 하루 전량 : 5·6·7을 확정한다 ---------------------------------------
    # 120건 창 하나로는 개장 시각도 거래량 총량도 볼 수 없다.
    # 커서를 돌려 하루를 다 모은 뒤 A2a 일봉과 맞춰야 답이 나온다.
    say("  [10] 하루 전량 수집 후 일봉 대조")
    rows = {}
    cursor = "153000"
    pages = 0
    for _ in range(8):
        r = call_minute(TICKER, recent, hour=cursor)
        pages += 1
        if not ok(r):
            break
        got = [x for x in r["output2"]
               if x.get("stck_bsop_date") == compact(recent)]
        if not got:
            break
        new = 0
        for x in got:
            k = x["stck_cntg_hour"]
            if k not in rows:
                rows[k] = x
                new += 1
        mn = min(x["stck_cntg_hour"] for x in got)
        if new == 0 or mn == cursor:
            break
        cursor = mn
        time.sleep(0.15)

    if rows:
        times = sorted(rows)
        vol = sum(int(rows[t]["cntg_vol"]) for t in times)
        derived = {
            "open": int(rows[times[0]]["stck_oprc"]),
            "high": max(int(rows[t]["stck_hgpr"]) for t in times),
            "low": min(int(rows[t]["stck_lwpr"]) for t in times),
            "close": int(rows[times[-1]]["stck_prpr"]),
            "volume": vol,
        }
        ref = a2a_daily(TICKER, recent)
        ev["fullDay"] = {
            "ticker": TICKER, "date": recent, "pages": pages,
            "분캔들수": len(times),
            "첫시각": times[0], "끝시각": times[-1],
            "파생일봉": derived, "a2a일봉": ref,
        }

        findings["6_타임존과캔들기준"].update({
            "하루첫시각": times[0],
            "하루끝시각": times[-1],
            "판정": ("시작시각 기준 (09:00 캔들이 있다)" if times[0] == "090000"
                    else "종료시각 기준 (첫 캔들이 090100)" if times[0] == "090100"
                    else "판정보류 — 첫 시각 " + times[0]),
            "장전시간외포함": times[0] < "090000",
        })

        if ref:
            findings["7_거래량의미"].update({
                "하루합": vol,
                "a2a일거래량": ref["volume"],
                "비율": round(vol / ref["volume"], 4) if ref["volume"] else None,
                "확정": ("구간(그 1분) — 합이 일거래량과 맞는다"
                        if ref["volume"] and 0.97 <= vol / ref["volume"] <= 1.03
                        else "불일치 — 원인을 따로 본다"),
            })
            same_scale = (derived["close"] == ref["close"]
                          and derived["high"] == ref["high"]
                          and derived["low"] == ref["low"])
            findings["5_수정주가"].update({
                "파생일봉": derived, "a2a일봉": ref,
                "OHLC일치": same_scale,
                "확정": ("A2a(수정주가)와 같은 축" if same_scale
                        else "축이 다르다 — 분봉은 무수정일 가능성이 높다. "
                             "최근일은 수정계수가 1이라 과거일로 다시 재야 한다"),
            })

    # --- 5 확정 : 기업행위가 있었던 종목을 찾아 축을 가른다 -------------------
    # 최근일로는 원리상 증명이 안 된다. 기업행위가 없으면 수정주가와 원주가가
    # 같은 값이라 어느 축인지 구분되지 않는다. 보존 구간 안에서 두 축이
    # 실제로 갈린 종목을 먼저 찾고, 그 종목의 분봉이 어느 쪽에 붙는지 본다.
    say("  [11] 수정주가 축 판정 (기업행위 종목 탐색)")
    past_i = max(0, idx_last - 200)
    past_date = days[past_i]
    universe = a2a_day(past_date)
    picks, split_case, scanned = [], None, []
    if universe:
        codes = sorted(universe)
        step = max(1, len(codes) // 15)
        picks = codes[::step][:15]

    for tk in picks:
        adj0 = call_daily(tk, past_date, past_date, "0")   # 수정주가
        time.sleep(0.1)
        adj1 = call_daily(tk, past_date, past_date, "1")   # 원주가
        time.sleep(0.1)
        k = compact(past_date)
        r0 = (adj0.get("rows") or {}).get(k)
        r1 = (adj1.get("rows") or {}).get(k)
        if not r0 or not r1:
            continue
        c0, c1 = int(r0["stck_clpr"]), int(r1["stck_clpr"])
        scanned.append({"ticker": tk, "수정주가종가": c0, "원주가종가": c1,
                        "갈림": c0 != c1})
        if c0 != c1 and split_case is None:
            m = call_minute(tk, past_date, hour="153000")
            close_min = None
            if ok(m):
                day = [x for x in m["output2"]
                       if x["stck_bsop_date"] == compact(past_date)]
                if day:
                    close_min = int(max(day, key=lambda x: x["stck_cntg_hour"])
                                    ["stck_prpr"])
            split_case = {
                "ticker": tk, "일자": past_date,
                "수정주가종가": c0, "원주가종가": c1,
                "분봉종가": close_min,
                "판정": ("수정주가 축" if close_min == c0
                        else "원주가 축" if close_min == c1
                        else "둘 다 아님 — 따로 본다"),
                "a2a종가": (universe.get(tk) or {}).get("close"),
            }
            say("      " + tk + " 수정 " + str(c0) + " / 원주 " + str(c1) +
                " / 분봉 " + str(close_min) + " → " + split_case["판정"])
            break

    findings["5_수정주가"].update({
        "기준일": past_date,
        "표본수": len(scanned),
        "축이갈린종목수": sum(1 for s in scanned if s["갈림"]),
        "판정사례": split_case,
        "status": "확정" if split_case else "부분",
        "확정": (split_case["판정"] if split_case else
               "표본에서 기업행위 종목을 찾지 못했다. 최근일 OHLC가 A2a와 "
               "완전히 일치한다는 것은 '같은 축'이 아니라 '이 날짜에는 "
               "두 축이 같다'만 말한다 — 액면분할 종목으로 다시 재야 한다"),
        "표본": scanned,
    })

    # --- 잴 수 없는 것은 잴 수 없다고 적는다 ---------------------------------
    findings["9_모의계좌"] = {
        "status": "미측정",
        "이유": "모의계좌 앱키가 없다. 실전 키로는 잴 수 없다",
        "필요조건": "모의계좌를 추가신청해 별도 앱키를 받아야 한다",
    }
    findings["11_거래정지액면분할"] = {
        "status": "미측정",
        "이유": "단발 호출로는 '과거 값이 바뀌는가'를 잴 수 없다. "
                "이것은 T1(7일)의 질문이다",
        "T1로이관": True,
    }

    # --- 저장 ---------------------------------------------------------------
    out = {
        "schemaVersion": "PROBE-MIN-1.0",
        "probe": "minute-kis-T0",
        "startedAt": stamp(),
        "elapsedSeconds": round(time.time() - started, 1),
        "endpoint": {"base": BASE, "path": PATH_DAILY_MIN, "trId": TR_DAILY_MIN,
                     "이름": "주식일별분봉조회 [국내주식-213]"},
        "문서상수": {"페이지크기": "실전 120건", "보관": "최대 1년",
                  "토큰유효": "1일", "토큰갱신": "6시간 초과 시",
                  "토큰발급주기": "5분당 1회"},
        "checklist": CHECKLIST,
        "findings": findings,
        "evidence": ev,
        "callCount": len(CALL_LOG),
        "calls": [{k: v for k, v in c.items() if k not in ("output1", "output2")}
                  for c in CALL_LOG],
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(out, ensure_ascii=False, indent=2),
                   encoding="utf-8", newline="\n")

    say()
    say("  호출 " + str(len(CALL_LOG)) + "회 · " +
        str(out["elapsedSeconds"]) + "초")
    say("  " + str(OUT.relative_to(REPO)))
    say()
    for k in CHECKLIST:
        say("    " + k.ljust(24) + findings[k]["status"])
    say()


if __name__ == "__main__":
    main()
