"""probe-price-a2b-kis.py — A2b 대체경로 ④ 정찰 (KIS 국내주식기간별시세)

배경(docs/control/세션인수인계-2026-08-16.md §4): ③(KRX-native adjStkPrc=2)은
3,000캔들 캡은 없었으나 액면분할 조정이 전혀 안 돼(005930 2018-05-04 전후 51배
단절) 그대로 쓸 수 없다고 판정됐다. 다음 후보 ④는 KIS
inquire-daily-itemchartprice(FHKST03010100)의 FID_ORG_ADJ_PRC(수정/원주가
플래그) — probe-minute-kis.py가 이미 이 엔드포인트로 단일 호출을 검증했지만
"실제 이력 깊이·페이지네이션"은 미확인(UNCONFIRMED)이었다. 그 빈칸만 잰다.

확인 항목:
  1. 전체기간(2014~2026) 요청 시 실제 반환 행수·시작일/종료일 (캡 여부)
  2. 캡이 있다면 FID_INPUT_DATE_2를 뒤로 돌리는 페이지네이션으로 과거를 더 주는가
  3. FID_ORG_ADJ_PRC 0/1 대조 — 정말 수정/원주가로 갈리는가
  4. 005930 2018-05-04 액면분할 전후 종가 연속성(수정주가 축이면 끊기지 않아야 한다)

입력: .env의 KIS_APP_KEY · KIS_APP_SECRET (probe-minute-kis.py와 동일 토큰 캐시 재사용)
출력: data/backfill/_probe-price-a2b-kis.json
정찰은 판정이 산출물이다 — 수집이 아니며 exit 0 고정.
"""
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
OUT = REPO / "data" / "backfill" / "_probe-price-a2b-kis.json"
TOKEN_CACHE = REPO / ".token_cache_kis.json"
CALENDAR = REPO / "data" / "backfill" / "calendar.json"

KST = timezone(timedelta(hours=9))
BASE = "https://openapi.koreainvestment.com:9443"
PATH_DAILY = "/uapi/domestic-stock/v1/quotations/inquire-daily-itemchartprice"
TR_DAILY = "FHKST03010100"

TICKER = "005930"
TICKER_CONTROL = "000660"
SPLIT_WINDOW = ("20180420", "20180511")


def stamp():
    return datetime.now(KST).strftime("%Y-%m-%d %H:%M:%S KST")


def load_env():
    env = {}
    p = REPO / ".env"
    if p.exists():
        for line in p.read_text(encoding="utf-8").splitlines():
            k, _, v = line.partition("=")
            if k.strip():
                env[k.strip()] = v.strip()
    for k in ("KIS_APP_KEY", "KIS_APP_SECRET"):
        if os.environ.get(k):
            env[k] = os.environ[k]
    return env


ENV = load_env()
KEY = ENV.get("KIS_APP_KEY", "")
SECRET = ENV.get("KIS_APP_SECRET", "")


def get_token():
    if TOKEN_CACHE.exists():
        try:
            c = json.loads(TOKEN_CACHE.read_text(encoding="utf-8"))
            exp = datetime.fromisoformat(c["expiresAt"])
            if exp.tzinfo is None:
                exp = exp.replace(tzinfo=KST)
            if exp - timedelta(minutes=10) > datetime.now(KST) and c.get("appKeyTail") == KEY[-4:]:
                print("  토큰: 캐시 재사용 (만료 " + c["expiresAt"] + ")")
                return c["accessToken"]
        except Exception:
            pass

    print("  토큰: 신규 발급")
    r = requests.post(BASE + "/oauth2/tokenP",
                      data=json.dumps({"grant_type": "client_credentials",
                                       "appkey": KEY, "appsecret": SECRET}),
                      headers={"content-type": "application/json"}, timeout=20)
    body = r.json()
    if r.status_code != 200 or "access_token" not in body:
        raise SystemExit("토큰 발급 실패")
    tok = body["access_token"]
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


TOKEN = None


def call_daily(ticker, d1, d2, adj):
    """국내주식기간별시세 1회. adj '0'=수정주가 '1'=원주가."""
    r = requests.get(
        BASE + PATH_DAILY,
        headers={"content-type": "application/json",
                 "authorization": "Bearer " + TOKEN,
                 "appkey": KEY, "appsecret": SECRET,
                 "tr_id": TR_DAILY, "custtype": "P"},
        params={"FID_COND_MRKT_DIV_CODE": "J", "FID_INPUT_ISCD": ticker,
                "FID_INPUT_DATE_1": d1, "FID_INPUT_DATE_2": d2,
                "FID_PERIOD_DIV_CODE": "D", "FID_ORG_ADJ_PRC": adj},
        timeout=15)
    b = r.json()
    o2 = b.get("output2") or []
    rows = {x.get("stck_bsop_date"): x for x in o2 if x.get("stck_bsop_date")}
    return {"http": r.status_code, "rtCd": b.get("rt_cd"),
            "msg": (b.get("msg1") or "")[:120], "rowCount": len(rows), "rows": rows}


def depth_and_pagination(ticker, frm, to, adj):
    """전체구간 1회 요청 후, 캡에 걸리면 응답의 가장 이른 날짜를 새 d2로 삼아 재요청."""
    calls = []
    cur_to = to
    collected = {}
    for _ in range(40):  # 100행/콜 캡이면 2014~2026(약 3,097거래일)을 다 받는 데 약 32콜
        r = call_daily(ticker, frm, cur_to, adj)
        calls.append({"d1": frm, "d2": cur_to, "rowCount": r["rowCount"],
                      "rtCd": r["rtCd"], "msg": r["msg"]})
        if r["rtCd"] != "0" or not r["rows"]:
            break
        collected.update(r["rows"])
        earliest = min(r["rows"])
        if earliest <= frm or r["rowCount"] < 90:
            # 90 미만이면 이 창에서 더 줄 게 없다고 본다(캡이 100 근처일 때의 신호)
            break
        cur_to = (datetime.strptime(earliest, "%Y%m%d") - timedelta(days=1)).strftime("%Y%m%d")
        time.sleep(0.2)
    dates = sorted(collected)
    return {
        "requestedRange": [frm, to],
        "calls": calls,
        "totalRowsAfterPaging": len(collected),
        "first": dates[0] if dates else None,
        "last": dates[-1] if dates else None,
        "singleCallCap": calls[0]["rowCount"] if calls else None,
        "paginationWorked": len(calls) > 1 and calls[-1]["rowCount"] > 0,
    }


def main():
    global TOKEN
    if not KEY or not SECRET:
        raise SystemExit("KIS_APP_KEY / KIS_APP_SECRET 이 없다. .env를 본다.")

    cal = json.loads(CALENDAR.read_text(encoding="utf-8"))
    frm = cal["tradingDays"][0].replace("-", "")
    to = cal["tradingDays"][-1].replace("-", "")

    print(f"KIS 기간별시세(FHKST03010100) 프로브 — {TICKER}/{TICKER_CONTROL} · {frm}~{to}\n")
    TOKEN = get_token()

    results = {}
    for tk in (TICKER, TICKER_CONTROL):
        print(f"  [{tk}] 1~2. 전체기간 + 페이지네이션 (수정주가)")
        depth = depth_and_pagination(tk, frm, to, "0")
        print(f"    캡 {depth['singleCallCap']} · 페이징후 {depth['totalRowsAfterPaging']}행 "
              f"· {depth['first']}~{depth['last']}")

        print(f"  [{tk}] 3. 수정/원주가 대조")
        adj0 = call_daily(tk, frm, to, "0")
        time.sleep(0.2)
        adj1 = call_daily(tk, frm, to, "1")
        common = set(adj0["rows"]) & set(adj1["rows"])
        diffCount = sum(1 for d in common
                        if adj0["rows"][d].get("stck_clpr") != adj1["rows"][d].get("stck_clpr"))
        adjustCompare = {
            "commonDates": len(common),
            "closeDiffers": diffCount,
            "판정": "수정/원주가 축이 갈린다" if diffCount else "이 구간에서 두 축이 동일 (기업행위 없음일 수도)",
        }

        entry = {"depthAndPagination": depth, "adjustVsRaw": adjustCompare}

        if tk == TICKER:
            print(f"  [{tk}] 4. 액면분할 연속성 (2018-05-04)")
            time.sleep(0.2)
            w_adj = call_daily(tk, *SPLIT_WINDOW, "0")
            time.sleep(0.2)
            w_raw = call_daily(tk, *SPLIT_WINDOW, "1")
            closes_adj = {d: int(v["stck_clpr"]) for d, v in sorted(w_adj["rows"].items())
                         if v.get("stck_clpr")}
            closes_raw = {d: int(v["stck_clpr"]) for d, v in sorted(w_raw["rows"].items())
                         if v.get("stck_clpr")}
            entry["splitContinuity"] = {
                "adjustedCloses": closes_adj,
                "rawCloses": closes_raw,
                "주석": "adjustedCloses가 분할일(0504) 전후로 연속적이고 rawCloses가 "
                        "그 지점에서 단절되면 FID_ORG_ADJ_PRC=0이 진짜 분할조정이다",
            }

        results[tk] = entry
        time.sleep(0.2)

    out = {
        "probedAt": stamp(),
        "purpose": "A2b 대체경로 ④(KIS FHKST03010100) 이력 깊이·페이지네이션·분할연속성 프로브 — 수집 아님",
        "endpoint": {"path": PATH_DAILY, "trId": TR_DAILY},
        "window": {"from": frm, "to": to},
        "results": results,
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8", newline="\n")
    print(f"\n{OUT.relative_to(REPO)}")


if __name__ == "__main__":
    main()
