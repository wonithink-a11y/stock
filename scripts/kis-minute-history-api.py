#!/usr/bin/env python3
"""kis-minute-history-api.py — 과거 날짜 1분봉 조회 HTTP API

옛 Claude Cowork "주식" 프로젝트의 kis.py가 쓰던 방식 그대로:
KIS inquire-time-dailychartprice(TR FHKST03010230)에 날짜를 지정해서
그날의 1분봉을 직접 받는다. 우리가 따로 쌓아둔 분봉 저장소(MN-1.0)를
전혀 안 읽는다 - KIS가 그날 걸 그대로 주므로 저장할 필요가 없다.

한 콜에 최근 120개(분)만 오므로 09:00까지 기준시각을 뒤로 당기며
페이지네이션한다(옛 kis.py의 _collect_minute_day와 동일 로직).

GET /minute-history?ticker=005930&date=20260828
  -> {"ticker":"005930","date":"20260828","bars":[{time,open,high,low,close,volume}, ...]}

.env(이 스크립트와 같은 디렉터리, kis-live-relay.py와 공유)에
KIS_VTS_APP_KEY/KIS_VTS_APP_SECRET 필요.
"""
import asyncio
import json
import os
import time
from pathlib import Path

import requests
from aiohttp import web

HERE = Path(__file__).resolve().parent
ENV_PATH = HERE / ".env"
TOKEN_CACHE = HERE / ".vts_token_cache.json"

VPS_BASE = "https://openapivts.koreainvestment.com:29443"
LISTEN_HOST = "127.0.0.1"
LISTEN_PORT = 8766
MAX_BATCHES = 15


def load_env():
    env = {}
    if ENV_PATH.exists():
        for line in ENV_PATH.read_text(encoding="utf-8").splitlines():
            k, _, v = line.partition("=")
            if k.strip():
                env[k.strip()] = v.strip()
    for k in ("KIS_VTS_APP_KEY", "KIS_VTS_APP_SECRET"):
        if os.environ.get(k):
            env[k] = os.environ[k]
    return env


ENV = load_env()
APP_KEY = ENV.get("KIS_VTS_APP_KEY", "")
APP_SECRET = ENV.get("KIS_VTS_APP_SECRET", "")
_token_lock = asyncio.Lock()


def _get_token_sync():
    if TOKEN_CACHE.exists():
        try:
            c = json.loads(TOKEN_CACHE.read_text(encoding="utf-8"))
            if time.time() < c["exp"] - 600:
                return c["token"]
        except Exception:
            pass
    r = requests.post(
        VPS_BASE + "/oauth2/tokenP",
        data=json.dumps({"grant_type": "client_credentials", "appkey": APP_KEY, "appsecret": APP_SECRET}),
        headers={"content-type": "application/json"}, timeout=15,
    )
    body = r.json()
    if "access_token" not in body:
        raise RuntimeError(f"토큰 발급 실패: {body}")
    tok = body["access_token"]
    TOKEN_CACHE.write_text(json.dumps({"token": tok, "exp": time.time() + 3600 * 20}), encoding="utf-8")
    return tok


async def get_token():
    async with _token_lock:
        return await asyncio.to_thread(_get_token_sync)


def _fetch_page_sync(token, ticker, date, hour):
    headers = {
        "content-type": "application/json; charset=utf-8",
        "authorization": f"Bearer {token}",
        "appkey": APP_KEY, "appsecret": APP_SECRET,
        "tr_id": "FHKST03010230", "custtype": "P",
    }
    params = {
        "FID_ETC_CLS_CODE": "", "FID_COND_MRKT_DIV_CODE": "J",
        "FID_INPUT_ISCD": ticker, "FID_INPUT_HOUR_1": hour,
        "FID_PW_DATA_INCU_YN": "N", "FID_INPUT_DATE_1": date,
        "FID_FAKE_TICK_INCU_YN": "N",
    }
    r = requests.get(VPS_BASE + "/uapi/domestic-stock/v1/quotations/inquire-time-dailychartprice",
                      headers=headers, params=params, timeout=15)
    return r.json()


async def collect_day(ticker, date):
    """옛 kis.py _collect_minute_day와 동일 페이지네이션 - 09:00까지 뒤로 당긴다."""
    token = await get_token()
    cur = "153000"
    seen = {}
    for _ in range(MAX_BATCHES):
        d = await asyncio.to_thread(_fetch_page_sync, token, ticker, date, cur)
        rows = [r for r in (d.get("output2") or []) if r.get("stck_cntg_hour")]
        if not rows:
            break
        for r in rows:
            t = r["stck_cntg_hour"]
            if t in seen:
                continue
            seen[t] = {
                "time": t,
                "open": int(float(r.get("stck_oprc") or 0)),
                "high": int(float(r.get("stck_hgpr") or 0)),
                "low": int(float(r.get("stck_lwpr") or 0)),
                "close": int(float(r.get("stck_prpr") or 0)),
                "volume": int(float(r.get("cntg_vol") or 0)),
            }
        earliest = min(r["stck_cntg_hour"] for r in rows)
        if earliest <= "090000":
            break
        m = int(earliest[:2]) * 60 + int(earliest[2:4]) - 1
        if m < 9 * 60:
            break
        cur = "%02d%02d00" % (m // 60, m % 60)
        await asyncio.sleep(0.15)  # 초당 요청 제한 회피(정찰에서 실측된 제약)
    bars = [seen[t] for t in sorted(seen) if seen[t]["close"] > 0]
    return bars


async def handle_minute_history(request):
    ticker = request.query.get("ticker", "")
    date = request.query.get("date", "")
    if not (ticker.isdigit() and len(ticker) == 6):
        return web.json_response({"error": "ticker는 6자리 숫자여야 한다"}, status=400)
    if not (date.isdigit() and len(date) == 8):
        return web.json_response({"error": "date는 YYYYMMDD 형식이어야 한다"}, status=400)
    try:
        bars = await collect_day(ticker, date)
    except Exception as e:
        return web.json_response({"error": str(e)}, status=502)
    return web.json_response({"ticker": ticker, "date": date, "bars": bars})


def main():
    if not (APP_KEY and APP_SECRET):
        raise SystemExit("KIS_VTS_APP_KEY/KIS_VTS_APP_SECRET이 없다")
    app = web.Application()
    app.router.add_get("/minute-history", handle_minute_history)
    print(f"minute-history API 시작: http://{LISTEN_HOST}:{LISTEN_PORT}/minute-history")
    web.run_app(app, host=LISTEN_HOST, port=LISTEN_PORT, print=None)


if __name__ == "__main__":
    main()
