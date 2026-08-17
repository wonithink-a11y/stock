"""probe-supply-demand.py — A4(수급: 외국인·기관·개인 매매) 착수 전 경로 정찰

배경: CLAUDE.md "안 한다" 항목의 A4(수급 백필)를 열기 전, 종목별 일별
외국인/기관/개인 매수·매도 금액·수량·순매수 데이터를 KIS Open API와 KRX(pykrx)
중 어느 경로로 장기 수집할 수 있는지 확인한다. 이 스크립트는 정책·코드를
쓰지 않는다 — 순수 정찰이다. A4 계약(config/policies/*)은 이 결과를 보고
따로 확정한다.

확인 항목:
  1. KIS "주식현재가 투자자"(TR FHKST01010900, inquire-investor)가 최근 거래일
     1종목에 대해 실제 값을 반환하는가. 반환되는 필드가 무엇인가.
  2. 이 KIS 엔드포인트가 과거 날짜 범위 조회를 지원하는가, 아니면 고정된
     최근 N거래일만 주는가(현재가류 엔드포인트의 전형적 한계).
  3. pykrx(KRX 스크레이핑)의 종목별 투자자 매매(get_market_trading_value_by_investor
     / get_market_trading_volume_by_investor)가 2016년 근방까지 실제로 응답하는가.
  4. 같은 종목·같은 날짜에서 KIS와 pykrx(KRX) 순매수 금액이 서로 맞는가
     (교차검증 가능성).
  5. 호출 간 소요 시간으로 대략적인 처리량 감을 잡는다(엄밀한 한도 측정 아님).

출력: 스크래치패드(레포 밖)에 JSON 저장. data/backfill/를 건드리지 않는다
(규칙 4 — 아직 A4 계약이 없어 backfill 산출물이 아니다).
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
TOKEN_CACHE = REPO / ".token_cache_kis.json"
OUT = Path(os.environ.get(
    "PROBE_OUT",
    r"C:\Users\User\AppData\Local\Temp\claude\C--Users-User-projects-stock\f86f939d-f1b4-4079-9e3c-1d1998dc03a2\scratchpad\probe-supply-demand.json"
))

KST = timezone(timedelta(hours=9))
BASE = "https://openapi.koreainvestment.com:9443"
PATH_INVESTOR = "/uapi/domestic-stock/v1/quotations/inquire-investor"
TR_INVESTOR = "FHKST01010900"

TICKER = "005930"          # 삼성전자 — 유동성 최상, 필드 관측용으로 최적
SECOND_TICKER = "000660"   # SK하이닉스 — 교차검증용 2번째 종목
THIRD_TICKER = "035420"    # NAVER — KRX 매핑 재검증용 3번째 종목


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
        raise SystemExit(f"토큰 발급 실패: {r.status_code} {body}")
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


def call_kis_investor(token, ticker):
    t0 = time.time()
    try:
        r = requests.get(
            BASE + PATH_INVESTOR,
            headers={"content-type": "application/json",
                     "authorization": "Bearer " + token,
                     "appkey": KEY, "appsecret": SECRET,
                     "tr_id": TR_INVESTOR, "custtype": "P"},
            params={"FID_COND_MRKT_DIV_CODE": "J", "FID_INPUT_ISCD": ticker},
            timeout=15)
    except Exception as e:  # noqa: BLE001
        return {"ok": False, "error": f"{type(e).__name__}: {e}", "elapsedSeconds": round(time.time() - t0, 2)}
    elapsed = round(time.time() - t0, 2)
    try:
        b = r.json()
    except Exception as e:  # noqa: BLE001
        return {"ok": False, "http": r.status_code, "error": f"json decode: {e}",
                "bodyHead": r.text[:300], "elapsedSeconds": elapsed}
    rows = b.get("output") or []
    return {
        "ok": (r.status_code == 200 and b.get("rt_cd") == "0"),
        "http": r.status_code,
        "rtCd": b.get("rt_cd"),
        "msgCd": b.get("msg_cd"),
        "msg": b.get("msg1"),
        "rowCount": len(rows),
        "fieldsObserved": sorted(rows[0].keys()) if rows else [],
        "firstRow": rows[0] if rows else None,
        "lastRow": rows[-1] if rows else None,
        "allDates": [row.get("stck_bsop_date") for row in rows if row.get("stck_bsop_date")],
        "allRows": rows,
        "elapsedSeconds": elapsed,
    }


def probe_pykrx():
    from pykrx import stock

    result = {"available": True, "tests": []}

    def timed(label, fn):
        t0 = time.time()
        try:
            df = fn()
            ok = df is not None and not df.empty
            rec = {
                "label": label, "ok": ok,
                "rowCount": 0 if df is None else len(df),
                "elapsedSeconds": round(time.time() - t0, 2),
            }
            if ok:
                rec["columns"] = [str(c) for c in df.columns]
                rec["indexSpan"] = [str(df.index.min()), str(df.index.max())]
                # 최신 1행만 JSON 안전 형태로 남긴다.
                last = df.iloc[-1]
                rec["lastRowSample"] = {str(k): (int(v) if hasattr(v, "item") else v)
                                         for k, v in last.items()}
            result["tests"].append(rec)
            return df
        except Exception as e:  # noqa: BLE001
            result["tests"].append({"label": label, "ok": False,
                                     "error": f"{type(e).__name__}: {e}",
                                     "elapsedSeconds": round(time.time() - t0, 2)})
            return None

    recent_df = timed(
        f"value_by_investor recent 5d {TICKER}",
        lambda: stock.get_market_trading_value_by_investor(
            (datetime.now() - timedelta(days=10)).strftime("%Y%m%d"),
            datetime.now().strftime("%Y%m%d"), TICKER))

    timed(
        f"volume_by_investor recent 5d {TICKER}",
        lambda: stock.get_market_trading_volume_by_investor(
            (datetime.now() - timedelta(days=10)).strftime("%Y%m%d"),
            datetime.now().strftime("%Y%m%d"), TICKER))

    # 역사 깊이 anchor — 2016~2023 구간이 실제로 응답하는지만 확인(전량 백필 아님).
    for anchor in ("20160104", "20180102", "20200102", "20230102"):
        end = (datetime.strptime(anchor, "%Y%m%d") + timedelta(days=5)).strftime("%Y%m%d")
        timed(f"history anchor {anchor} {TICKER}",
              lambda a=anchor, e=end: stock.get_market_trading_value_by_investor(a, e, TICKER))

    # 2번째 종목 교차검증용.
    timed(f"value_by_investor recent 5d {SECOND_TICKER}",
          lambda: stock.get_market_trading_value_by_investor(
              (datetime.now() - timedelta(days=10)).strftime("%Y%m%d"),
              datetime.now().strftime("%Y%m%d"), SECOND_TICKER))

    return result, recent_df


def main():
    if not KEY or not SECRET:
        raise SystemExit("KIS_APP_KEY / KIS_APP_SECRET 이 없다. .env를 본다.")

    print(f"수급 데이터 경로 정찰 시작 — {stamp()}\n")

    print("[1/3] KIS inquire-investor 프로브")
    token = get_token()
    kis_result = {
        TICKER: call_kis_investor(token, TICKER),
        SECOND_TICKER: call_kis_investor(token, SECOND_TICKER),
        THIRD_TICKER: call_kis_investor(token, THIRD_TICKER),
    }
    for tk, r in kis_result.items():
        print(f"  {tk}: ok={r.get('ok')} rows={r.get('rowCount')} "
              f"fields={len(r.get('fieldsObserved') or [])} "
              f"dates={(r.get('allDates') or [None])[0]}~{(r.get('allDates') or [None])[-1]} "
              f"({r.get('elapsedSeconds')}s)")
        if not r.get("ok"):
            print(f"    실패 상세: rtCd={r.get('rtCd')} msgCd={r.get('msgCd')} msg={r.get('msg')}")

    print("\n[2/3] pykrx(KRX) 프로브")
    pykrx_result, recent_df = probe_pykrx()
    for t in pykrx_result["tests"]:
        status = "ok" if t.get("ok") else "FAIL"
        print(f"  [{status}] {t['label']} — rows={t.get('rowCount', 0)} "
              f"({t.get('elapsedSeconds')}s)" + (f" — {t.get('error')}" if t.get("error") else ""))

    print("\n[3/3] 교차검증 (같은 날짜, KIS vs KRX/pykrx)")
    cross = {"ticker": TICKER, "note": None, "kisLatestRow": None, "pykrxLatestRow": None}
    kis_dates = kis_result[TICKER].get("allDates") or []
    if kis_dates and recent_df is not None and not recent_df.empty:
        latest_kis_date = kis_dates[0] if kis_dates[0] > (kis_dates[-1] or "") else kis_dates[-1]
        cross["kisLatestRow"] = kis_result[TICKER].get("firstRow")
        last_pykrx = recent_df.iloc[-1]
        cross["pykrxLatestRow"] = {str(k): (int(v) if hasattr(v, "item") else v)
                                    for k, v in last_pykrx.items()}
        cross["pykrxLatestDate"] = str(recent_df.index.max())
        cross["note"] = ("날짜가 정확히 일치하는지, 외국인/기관/개인 순매수 부호·크기가 "
                          "맞는지는 위 두 필드를 사람이 대조해서 판단한다 — 카테고리명이 "
                          "달라(KIS는 영문 필드, pykrx는 한글 컬럼) 자동 매칭은 안 했다.")
    else:
        cross["note"] = "한쪽 이상 데이터가 없어 교차검증 불가."
    print(f"  {cross['note']}")

    out = {
        "probedAt": stamp(),
        "purpose": "A4(수급) 착수 전 KIS/KRX 경로 정찰 — 정책 미확정, 코드 무변경",
        "kis": kis_result,
        "pykrx": pykrx_result,
        "crossValidation": cross,
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(out, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    print(f"\n전체 결과: {OUT}")


if __name__ == "__main__":
    main()
