"""probe-kis-vts-connection.py — KIS 모의투자(VTS) 연결 확인. 읽기 전용.

Paper Trading Engine 3단계 착수 전 스모크 테스트 - 토큰 발급과 잔고 조회만
한다. 주문 API는 호출하지 않는다. 이 스크립트가 성공해야만 다음 단계
(KISVtsBroker의 실제 주문 코드)로 넘어간다.

도메인·TR_ID는 KIS 공식 예제(github.com/koreainvestment/open-trading-api,
examples_user/kis_auth.py·examples_user/domestic_stock/domestic_stock_functions.py)
에서 그대로 가져왔다 - 라이브 도메인(openapi.koreainvestment.com:9443)은
이 파일 어디에도 나오지 않는다. 모의투자 도메인(openapivts...)만 하드코딩.

입력: .env의 KIS_VTS_APP_KEY · KIS_VTS_APP_SECRET · KIS_VTS_ACCOUNT_NO
      (라이브 KIS_APP_KEY 등은 이 스크립트가 아예 안 읽는다)
출력: 화면에 요약만(예수금 총액·보유종목 수) - 전체 응답 JSON은 안 찍는다.
      모의투자 계좌라 예수금 자체는 민감정보가 아니지만, 원칙은 지킨다.

사용:
    python scripts/probe-kis-vts-connection.py
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
TOKEN_CACHE = REPO / ".token_cache_kis_vts.json"

KST = timezone(timedelta(hours=9))
# 모의투자 전용 도메인. 이 스크립트에 라이브 도메인은 등장하지 않는다.
BASE = "https://openapivts.koreainvestment.com:29443"
PATH_BALANCE = "/uapi/domestic-stock/v1/trading/inquire-balance"
TR_BALANCE_DEMO = "VTTC8434R"


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
    for k in ("KIS_VTS_APP_KEY", "KIS_VTS_APP_SECRET", "KIS_VTS_ACCOUNT_NO"):
        if os.environ.get(k):
            env[k] = os.environ[k]
    return env


ENV = load_env()
KEY = ENV.get("KIS_VTS_APP_KEY", "")
SECRET = ENV.get("KIS_VTS_APP_SECRET", "")
ACCOUNT_RAW = ENV.get("KIS_VTS_ACCOUNT_NO", "")

if not (KEY and SECRET and ACCOUNT_RAW):
    print("[중단] KIS_VTS_APP_KEY / KIS_VTS_APP_SECRET / KIS_VTS_ACCOUNT_NO 중 하나가 .env에 없습니다.")
    print("       python scripts/setup-kis-vts-key.py 를 먼저 실행하세요.")
    sys.exit(1)

# CANO(8자리)+ACNT_PRDT_CD(2자리). "12345678-01"과 "12345678" 둘 다 받는다 -
# 상품코드를 안 붙인 경우가 실측으로 흔하다(대부분 "01"이 맞다).
if "-" in ACCOUNT_RAW:
    CANO, ACNT_PRDT_CD = ACCOUNT_RAW.split("-", 1)
else:
    CANO, ACNT_PRDT_CD = ACCOUNT_RAW, "01"


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

    print("  토큰: 신규 발급 (모의투자 도메인)")
    r = requests.post(BASE + "/oauth2/tokenP",
                       data=json.dumps({"grant_type": "client_credentials",
                                        "appkey": KEY, "appsecret": SECRET}),
                       headers={"content-type": "application/json"}, timeout=20)
    body = r.json()
    if r.status_code != 200 or "access_token" not in body:
        print("[실패] 토큰 발급 실패:", body.get("error_description", body))
        sys.exit(1)
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


def inquire_balance(token):
    headers = {
        "content-type": "application/json; charset=utf-8",
        "authorization": "Bearer " + token,
        "appkey": KEY,
        "appsecret": SECRET,
        "tr_id": TR_BALANCE_DEMO,
        "custtype": "P",
    }
    params = {
        "CANO": CANO,
        "ACNT_PRDT_CD": ACNT_PRDT_CD,
        "AFHR_FLPR_YN": "N",
        "OFL_YN": "",
        "INQR_DVSN": "02",
        "UNPR_DVSN": "01",
        "FUND_STTL_ICLD_YN": "N",
        "FNCG_AMT_AUTO_RDPT_YN": "N",
        "PRCS_DVSN": "00",
        "CTX_AREA_FK100": "",
        "CTX_AREA_NK100": "",
    }
    r = requests.get(BASE + PATH_BALANCE, headers=headers, params=params, timeout=20)
    return r


def main():
    print()
    print("  KIS 모의투자 연결 확인 (읽기 전용 - 주문 없음)")
    print("  도메인:", BASE)
    print("  계좌:", CANO[:4] + "****", "/", ACNT_PRDT_CD)
    print()

    token = get_token()
    r = inquire_balance(token)

    if r.status_code != 200:
        print("[실패] HTTP", r.status_code, "-", r.text[:500])
        sys.exit(1)

    body = r.json()
    if body.get("rt_cd") != "0":
        print("[실패] KIS 오류:", body.get("msg_cd"), body.get("msg1"))
        sys.exit(1)

    holdings = body.get("output1", [])
    summary = body.get("output2", [{}])
    cash = summary[0].get("dnca_tot_amt") if summary else None
    eval_total = summary[0].get("tot_evlu_amt") if summary else None

    print("[성공] 모의투자 계좌 연결 확인됨")
    print("  보유 종목 수:", len([h for h in holdings if h.get("hldg_qty", "0") != "0"]))
    print("  예수금(모의투자 가상자금):", cash)
    print("  평가금액 총액:", eval_total)
    print()
    print("  이 결과는 진단 전용이다 - 아무것도 커밋하지 않는다.")


if __name__ == "__main__":
    main()
