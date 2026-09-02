#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""kis-portfolio-holdings.py — 실전계좌 잔고조회로 실시간 탭 관심종목을
내가 실제로 투자한 종목에 자동으로 맞춘다.

research/strategy-lab/engine/live/kisVtsClient.py(모의투자, 검증된 코드)의
inquire_balance()와 완전히 같은 엔드포인트·요청 구조를 실전 도메인/TR_ID로
바꾼 것뿐이다 - 새로 설계하지 않았다. KIS는 실전/모의를 도메인과 TR_ID
접두사(T=실전·V=모의)로만 가르고 응답 스키마는 동일하다.

★ 이 파일이 만드는 결과물(docs/data/가 아니라 홈 디렉터리)은 절대 git에
올리지 않는다 - 실제 보유종목·수량·평가금액은 이 저장소가 공개라 노출되면
안 되는 정보다(사용자 확인, 2026-09-02). kis-live-relay.py가 이 로컬
파일을 직접 읽어 구독 목록을 정하고, docs/data/live-watchlist.json(공개
정적 목록)은 이 파일이 없거나 비어있을 때의 폴백으로만 남는다.

토큰 캐시는 scripts/build-price-a2b.py·build-etf-etn-daily.py와 같은
.token_cache_kis.json을 공유한다 - 다들 상시 연결이 아니라 가끔 호출하는
REST 콜이라 캐시를 나눠 쓰면 불필요한 재발급(KIS 5분당 1회 제한)을 줄인다.
상시 웹소켓(kis-live-relay.py 자체)만 별도 앱키(KIS_VTS_APP_KEY)를 써서
이 재발급과 완전히 무관하다 - CLAUDE.md AI협업 논의에서 확정된 원칙.

사용:
    python scripts/kis-portfolio-holdings.py
    python scripts/kis-portfolio-holdings.py --selftest
    python scripts/kis-portfolio-holdings.py --dry-run   # 조회만 하고 파일에 안 씀
"""
import argparse
import json
import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import requests

REPO_ROOT = Path(__file__).resolve().parent.parent
TOKEN_CACHE = Path(os.environ.get("KIS_TOKEN_CACHE") or (REPO_ROOT / ".token_cache_kis.json"))
OUT_PATH = Path(os.environ.get("KIS_HOLDINGS_PATH") or (Path.home() / ".kis-holdings.json"))
KST = timezone(timedelta(hours=9))

BASE_URL = "https://openapi.koreainvestment.com:9443"
PATH_BALANCE = "/uapi/domestic-stock/v1/trading/inquire-balance"
TR_BALANCE = "TTTC8434R"  # 실전계좌 잔고조회 (모의투자는 VTTC8434R, kisVtsClient.py 참고)

# KIS 웹소켓 실시간 등록 한도(2026-04-20 공지 기준, 세션당 41건 - 우리는
# 체결가만 구독해 호가와 안 나눠 쓰므로 이 41건이 그대로 우리 상한이다).
MAX_TICKERS = 41


class HoldingsError(RuntimeError):
    pass


def _load_env():
    env = {}
    p = REPO_ROOT / ".env"
    if p.exists():
        for line in p.read_text(encoding="utf-8").splitlines():
            k, _, v = line.partition("=")
            if k.strip():
                env[k.strip()] = v.strip()
    for k in ("KIS_APP_KEY", "KIS_APP_SECRET", "KIS_ACCOUNT_NO"):
        if os.environ.get(k):
            env[k] = os.environ[k]
    return env


def _get_token(key, secret):
    if TOKEN_CACHE.exists():
        try:
            c = json.loads(TOKEN_CACHE.read_text(encoding="utf-8"))
            exp = datetime.fromisoformat(c["expiresAt"].replace(" ", "T"))
            if exp.tzinfo is None:
                exp = exp.replace(tzinfo=KST)
            if exp - timedelta(minutes=10) > datetime.now(KST) and c.get("appKeyTail") == key[-4:]:
                return c["accessToken"]
        except Exception:
            pass
    r = requests.post(BASE_URL + "/oauth2/tokenP",
                       data=json.dumps({"grant_type": "client_credentials",
                                        "appkey": key, "appsecret": secret}),
                       headers={"content-type": "application/json"}, timeout=20)
    body = r.json()
    if r.status_code != 200 or "access_token" not in body:
        raise HoldingsError("토큰 발급 실패: " + str(body.get("error_description", body)))
    tok = body["access_token"]
    TOKEN_CACHE.write_text(json.dumps({
        "accessToken": tok, "expiresAt": body.get("access_token_token_expired", ""),
        "appKeyTail": key[-4:],
    }, ensure_ascii=False, indent=2), encoding="utf-8")
    try:
        os.chmod(TOKEN_CACHE, 0o600)
    except Exception:
        pass
    return tok


def fetch_holdings():
    env = _load_env()
    key, secret, account_raw = env.get("KIS_APP_KEY", ""), env.get("KIS_APP_SECRET", ""), env.get("KIS_ACCOUNT_NO", "")
    if not (key and secret and account_raw):
        raise HoldingsError("KIS_APP_KEY/KIS_APP_SECRET/KIS_ACCOUNT_NO 중 하나가 없다 - "
                             "scripts/setup-keys-interactive.py로 먼저 저장한다.")
    cano, acnt_prdt_cd = account_raw.split("-", 1) if "-" in account_raw else (account_raw, "01")
    token = _get_token(key, secret)
    headers = {
        "content-type": "application/json; charset=utf-8",
        "authorization": "Bearer " + token,
        "appkey": key, "appsecret": secret, "tr_id": TR_BALANCE, "custtype": "P",
    }
    params = {
        "CANO": cano, "ACNT_PRDT_CD": acnt_prdt_cd,
        "AFHR_FLPR_YN": "N", "OFL_YN": "", "INQR_DVSN": "02", "UNPR_DVSN": "01",
        "FUND_STTL_ICLD_YN": "N", "FNCG_AMT_AUTO_RDPT_YN": "N", "PRCS_DVSN": "00",
        "CTX_AREA_FK100": "", "CTX_AREA_NK100": "",
    }
    r = requests.get(BASE_URL + PATH_BALANCE, headers=headers, params=params, timeout=20)
    resp = r.json()
    if r.status_code != 200 or resp.get("rt_cd") != "0":
        raise HoldingsError(f"잔고 조회 실패: {resp.get('msg_cd')} {resp.get('msg1')}")
    return resp.get("output1", [])


def to_rows(raw_holdings):
    """0주 보유(과거 매도 완료 잔여 레코드)는 뺀다. 평가금액 내림차순 -
    41종목을 넘으면 큰 것부터 남긴다(잘라내는 건 작은 포지션이어야 한다)."""
    rows = []
    for h in raw_holdings:
        qty = int(h.get("hldg_qty") or 0)
        if qty <= 0:
            continue
        rows.append({
            "ticker": h.get("pdno"),
            "name": h.get("prdt_name"),
            "quantity": qty,
            "evalAmount": int(h.get("evlu_amt") or 0),
        })
    rows.sort(key=lambda r: r["evalAmount"], reverse=True)
    return rows[:MAX_TICKERS]


def selftest():
    raw = [
        {"pdno": "005930", "prdt_name": "삼성전자", "hldg_qty": "10", "evlu_amt": "1000000"},
        {"pdno": "000660", "prdt_name": "SK하이닉스", "hldg_qty": "0", "evlu_amt": "0"},
        {"pdno": "035420", "prdt_name": "NAVER", "hldg_qty": "5", "evlu_amt": "900000"},
    ]
    rows = to_rows(raw)
    assert len(rows) == 2, "0주 보유(청산 완료 잔여 레코드)는 빠져야 한다"
    assert rows[0]["ticker"] == "005930", "평가금액 큰 순으로 정렬돼야 한다"
    assert rows[1]["ticker"] == "035420"

    many = [{"pdno": f"{i:06d}", "prdt_name": f"종목{i}", "hldg_qty": "1", "evlu_amt": str(i)}
            for i in range(1, 60)]
    capped = to_rows(many)
    assert len(capped) == MAX_TICKERS, "KIS 웹소켓 세션 한도(41건)를 넘으면 안 된다"
    assert capped[0]["evalAmount"] == 59, "잘리는 건 평가금액이 작은 쪽이어야 한다"
    print("selftest OK")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--selftest", action="store_true")
    ap.add_argument("--dry-run", action="store_true", help="조회만 하고 파일에 쓰지 않는다")
    args = ap.parse_args()
    if args.selftest:
        return selftest()

    raw = fetch_holdings()
    rows = to_rows(raw)
    if not rows:
        print("보유종목 0건 - kis-live-relay.py는 docs/data/live-watchlist.json으로 폴백한다", file=sys.stderr)

    payload = {"generatedAtKST": datetime.now(KST).isoformat(), "holdings": rows}
    if args.dry_run:
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        return
    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUT_PATH.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    try:
        os.chmod(OUT_PATH, 0o600)
    except Exception:
        pass
    print(f"wrote {OUT_PATH} (holdings={len(rows)})")


if __name__ == "__main__":
    main()
