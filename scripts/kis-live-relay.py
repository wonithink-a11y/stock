#!/usr/bin/env python3
"""kis-live-relay.py — KIS 모의투자(VTS) 실시간체결가 웹소켓 → 브라우저 중계 서버

배경: docs/index.html은 GitHub Actions 배치로 몇 분~하루 간격으로만 갱신되는
정적 페이지다. "지금 이 순간의 체결가"를 보려면 상시 켜진 서버가 KIS와
연결을 유지해야 한다 — 이 스크립트가 그 역할이다. stock-new VM에서 systemd
서비스로 상시 실행된다(deploy/kis-live-relay.service).

라이브 키(KIS_APP_KEY)가 아니라 KIS_VTS_APP_KEY/SECRET만 쓴다 — 실전 계좌
토큰은 이미 A2b·분봉수집기·ETF 일일수집이 스케줄대로 쓰고 있어서, 이 상시
연결이 같은 앱키의 토큰을 다투면(EGW00123) 그 배치 작업들이 깨진다. KIS
공식 예제(github.com/koreainvestment/open-trading-api)가 실시간체결가
(H0STCNT0)는 "웹소켓은 실전/모의 동일 TR_ID 사용"이라고 명시하고, 2026-09-01
실측으로도 모의투자 키로 20초간 36틱 정상 수신을 확인했다 — 그 확인을 그대로
상시 서비스로 옮긴 것이다.

구독 종목은 원래 docs/data/live-watchlist.json 고정 목록이었다(v1) —
클라이언트별 동적 구독은 다루지 않는다. 브라우저는 이 서버가 흘려보내는
스트림 중 보고 싶은 종목만 골라서 표시하면 된다. 이 종목 목록은
scripts/kis-live-relay.py·scripts/build-watchlist-daily.py·docs/index.html
셋이 그대로 공유한다 - 바꾸려면 docs/data/live-watchlist.json 하나만
고치면 된다(예전엔 세 곳에 각각 하드코딩돼 있었다).

★ v2(2026-09-02) — scripts/kis-portfolio-holdings.py(실전계좌 잔고조회,
KIS_APP_KEY 사용 - 이 파일과는 다른 키)가 로컬에 써 둔 보유종목 파일이
있으면 그걸 우선 쓴다. 이 파일은 저장소 밖(홈 디렉터리)에만 존재하고
git에 절대 안 올라간다 - 실제 보유종목·수량·평가금액은 이 저장소가
공개라 노출되면 안 된다(사용자 확인). 그 파일이 없거나·비었거나·깨졌으면
정적 목록(live-watchlist.json)으로 조용히 폴백한다(fail-soft) - 이 서버가
"내 보유종목이 없다"는 이유로 안 뜨면 안 된다.

.env(이 스크립트와 같은 디렉터리)에 KIS_VTS_APP_KEY/KIS_VTS_APP_SECRET 필요.
"""
import asyncio
import json
import os
import time
from pathlib import Path

import requests
import websockets

HERE = Path(__file__).resolve().parent
ENV_PATH = HERE / ".env"
REPO_ROOT = HERE.parent
WATCHLIST_PATH = REPO_ROOT / "docs" / "data" / "live-watchlist.json"
HOLDINGS_PATH = Path(os.environ.get("KIS_HOLDINGS_PATH") or (Path.home() / ".kis-holdings.json"))

VPS_BASE = "https://openapivts.koreainvestment.com:29443"
VOPS_WS = "ws://ops.koreainvestment.com:31000"
LISTEN_HOST = "127.0.0.1"
LISTEN_PORT = 8765


def load_watchlist():
    if HOLDINGS_PATH.exists():
        try:
            h = json.loads(HOLDINGS_PATH.read_text(encoding="utf-8"))
            tickers = [(r["ticker"], r["name"]) for r in h.get("holdings", []) if r.get("ticker")]
            if tickers:
                return tickers
        except Exception as e:
            print(f"보유종목 파일 읽기 실패({e}) - 정적 목록으로 폴백")
    d = json.loads(WATCHLIST_PATH.read_text(encoding="utf-8"))
    return [(t["ticker"], t["name"]) for t in d["tickers"]]


WATCHLIST = load_watchlist()

# H0STCNT0 응답 컬럼 순서 (KIS 공식 예제 domestic_stock_functions_ws.py 그대로)
COLUMNS = [
    "MKSC_SHRN_ISCD", "STCK_CNTG_HOUR", "STCK_PRPR", "PRDY_VRSS_SIGN",
    "PRDY_VRSS", "PRDY_CTRT", "WGHN_AVRG_STCK_PRC", "STCK_OPRC",
    "STCK_HGPR", "STCK_LWPR", "ASKP1", "BIDP1", "CNTG_VOL", "ACML_VOL",
    "ACML_TR_PBMN", "SELN_CNTG_CSNU", "SHNU_CNTG_CSNU", "NTBY_CNTG_CSNU",
    "CTTR", "SELN_CNTG_SMTN", "SHNU_CNTG_SMTN", "CCLD_DVSN", "SHNU_RATE",
    "PRDY_VOL_VRSS_ACML_VOL_RATE", "OPRC_HOUR", "OPRC_VRSS_PRPR_SIGN",
    "OPRC_VRSS_PRPR", "HGPR_HOUR", "HGPR_VRSS_PRPR_SIGN", "HGPR_VRSS_PRPR",
    "LWPR_HOUR", "LWPR_VRSS_PRPR_SIGN", "LWPR_VRSS_PRPR", "BSOP_DATE",
    "NEW_MKOP_CLS_CODE", "TRHT_YN", "ASKP_RSQN1", "BIDP_RSQN1",
    "TOTAL_ASKP_RSQN", "TOTAL_BIDP_RSQN", "VOL_TNRT",
    "PRDY_SMNS_HOUR_ACML_VOL", "PRDY_SMNS_HOUR_ACML_VOL_RATE",
    "HOUR_CLS_CODE", "MRKT_TRTM_CLS_CODE", "VI_STND_PRC",
]

NAME_BY_CODE = dict(WATCHLIST)
clients = set()


def load_env():
    """systemd의 EnvironmentFile이 이미 os.environ에 값을 넣어준다(운영 경로).
    로컬에서 systemd 없이 돌릴 때만 .env 파일을 대신 읽는다."""
    import os
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


def get_approval_key(app_key, app_secret):
    r = requests.post(
        VPS_BASE + "/oauth2/Approval",
        data=json.dumps({"grant_type": "client_credentials", "appkey": app_key, "secretkey": app_secret}),
        headers={"content-type": "application/json; utf-8"},
        timeout=15,
    )
    body = r.json()
    if "approval_key" not in body:
        raise RuntimeError(f"Approval 실패: {body}")
    return body["approval_key"]


def parse_ticks(line):
    """한 메시지에 여러 건이 이어붙는 경우(필드수가 COLUMNS의 배수)까지 포함해 전부 뽑는다."""
    parts = line.split("|")
    if len(parts) < 4:
        return []
    fields = parts[3].split("^")
    n = len(COLUMNS)
    out = []
    for i in range(0, len(fields) - n + 1, n):
        d = dict(zip(COLUMNS, fields[i:i + n]))
        code = d.get("MKSC_SHRN_ISCD")
        out.append({
            "ticker": code,
            "name": NAME_BY_CODE.get(code, code),
            "time": d.get("STCK_CNTG_HOUR"),
            "price": d.get("STCK_PRPR"),
            "change": d.get("PRDY_VRSS"),
            "changePct": d.get("PRDY_CTRT"),
            "open": d.get("STCK_OPRC"),
            "high": d.get("STCK_HGPR"),
            "low": d.get("STCK_LWPR"),
            "volume": d.get("CNTG_VOL"),
            "accVolume": d.get("ACML_VOL"),
        })
    return out


async def broadcast(queue):
    while True:
        tick = await queue.get()
        if clients:
            msg = json.dumps(tick, ensure_ascii=False)
            await asyncio.gather(*(c.send(msg) for c in list(clients)), return_exceptions=True)


async def kis_upstream(queue, app_key, app_secret):
    while True:
        try:
            approval_key = get_approval_key(app_key, app_secret)
            print(f"[{time.strftime('%H:%M:%S')}] approval_key 발급 성공, KIS 웹소켓 접속 시도")
            async with websockets.connect(VOPS_WS, ping_interval=None) as ws:
                for code, _name in WATCHLIST:
                    sub = {
                        "header": {"approval_key": approval_key, "custtype": "P", "tr_type": "1", "content-type": "utf-8"},
                        "body": {"input": {"tr_id": "H0STCNT0", "tr_key": code}},
                    }
                    await ws.send(json.dumps(sub))
                    await asyncio.sleep(0.1)
                print(f"[{time.strftime('%H:%M:%S')}] {len(WATCHLIST)}종목 구독 완료")

                async for raw in ws:
                    if isinstance(raw, str) and raw and raw[0] in "0123456789":
                        for tick in parse_ticks(raw):
                            await queue.put(tick)
                        continue
                    try:
                        j = json.loads(raw)
                    except Exception:
                        continue
                    if j.get("header", {}).get("tr_id") == "PINGPONG":
                        await ws.pong()
        except Exception as e:
            print(f"[{time.strftime('%H:%M:%S')}] KIS 연결 끊김({e!r}), 5초 후 재접속")
            await asyncio.sleep(5)


async def client_handler(websocket):
    clients.add(websocket)
    print(f"[{time.strftime('%H:%M:%S')}] 브라우저 클라이언트 연결, 현재 {len(clients)}개")
    try:
        async for _ in websocket:
            pass  # v1: 클라이언트→서버 메시지는 안 받는다(구독 요청 없음, 전체 스트림 브로드캐스트)
    finally:
        clients.discard(websocket)
        print(f"[{time.strftime('%H:%M:%S')}] 클라이언트 종료, 현재 {len(clients)}개")


async def main():
    env = load_env()
    app_key = env.get("KIS_VTS_APP_KEY", "")
    app_secret = env.get("KIS_VTS_APP_SECRET", "")
    if not (app_key and app_secret):
        raise SystemExit("KIS_VTS_APP_KEY/KIS_VTS_APP_SECRET이 .env에 없다")

    queue = asyncio.Queue()
    async with websockets.serve(client_handler, LISTEN_HOST, LISTEN_PORT):
        print(f"[{time.strftime('%H:%M:%S')}] 중계 서버 시작: ws://{LISTEN_HOST}:{LISTEN_PORT}")
        await asyncio.gather(kis_upstream(queue, app_key, app_secret), broadcast(queue))


def _selftest():
    """실측 샘플(2026-09-01 정찰, 삼성전자 1건)로 parse_ticks()만 검증. 네트워크 없음."""
    sample = ("0|H0STCNT0|001|005930^123739^259500^5^-500^-0.19^258272.30^256500^262500^254000^"
               "260000^259500^1^7125812^1840399910000^41812^55293^13481^124.96^3054614^3817177^"
               "5^0.54^39.00^090005^2^3000^100104^5^-3000^091441^2^5500^20260901^20^N^75900^"
               "49002^770706^444757^0.12^8554864^83.30^0^^256500")
    ticks = parse_ticks(sample)
    assert len(ticks) == 1, f"1건이어야 하는데 {len(ticks)}건"
    t = ticks[0]
    assert t["ticker"] == "005930", t
    assert t["name"] == "삼성전자", t
    assert t["price"] == "259500", t
    assert t["time"] == "123739", t

    # 2건이 이어붙은 메시지도 전부 뽑히는지
    double_msg = "0|H0STCNT0|002|" + sample.split("|")[3] + "^" + sample.split("|")[3]
    ticks2 = parse_ticks(double_msg)
    assert len(ticks2) == 2, f"2건이어야 하는데 {len(ticks2)}건"

    # 필드 부족한 쓰레기 라인은 조용히 빈 리스트
    assert parse_ticks("garbage") == []

    print("selftest OK")


if __name__ == "__main__":
    import sys
    if "--selftest" in sys.argv:
        _selftest()
    else:
        asyncio.run(main())
