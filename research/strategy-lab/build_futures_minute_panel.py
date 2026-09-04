#!/usr/bin/env python3
"""KRX 주요 선물 30초봉 패널 수집 (연구 전용, 주간 + 야간).

data/backfill/ 에 쓰지 않는다 - PEAD build_quarterly_earnings_panel.py 와 같은
스코프(정책 파일·GH Actions·manifest 없음). 산출물은
.cache/futures_minute/<product>_<session>/<date>.parquet.

목적: "선물이 현물보다 선행하는가"를 이 저장소의 주식 분봉 패널(261거래일)과
붙여 검증하기 위한 원재료. 가설 검증 자체는 이 스크립트가 하지 않는다.

── 2026-09-04 Phase 0 실측으로 확정된 것 ────────────────────────────────
계약 선택   KRX Open API drv/fut_bydd_trd (무료·로그인 불필요, 2016~).
            그날 실제 거래된 계약과 거래량을 주므로 롤오버가 자동으로 잡힌다.
코드 변환   KRX ISU_CD(8) -> KIS FID_INPUT_ISCD(6)
            앞 4자 + 5번째 문자(월: 1~9 -> 01~09, A/B/C -> 10/11/12)
            A0169000 -> A01609 · 101W9000 -> 101W09
            * 2026년물부터 접두가 101 -> A016 으로 바뀌었다. 연도 문자를
              외삽하면 틀린다 - 반드시 KRX 에서 그날 코드를 읽는다.
시장구분    지수선물 주간 = F · 금리/통화선물 주간 = CF · 전 상품 야간 = CM
            (A65609 를 F 로 부르면 조용히 0행이 온다)
해상도      FID_HOUR_CLS_CODE=30(30초)이 과거 조회가 되는 최소값.
            1·5·10초는 당일만. 60·120·300·600 은 과거 가능.
콜당        102건 고정. 주간 약 8페이지 · 야간 약 15페이지.
보존창      2025-08-27 O · 2025-08-25 X (오늘-약 1년 롤링, 매일 앞이 잘린다)
야간 표기   stck_cntg_hour 가 18:00~30:00(30시 = 익일 06:00). 그대로 저장한다 -
            "야간 D 가 주간 D 의 뒤인가 앞인가"는 Phase 2 에서 가격 연속성으로
            판정할 문제이지 수집기가 지어낼 것이 아니다(교훈75).

교훈81 게이트: rt_cd=0 이어도 요청일과 다른 날짜를 조용히 돌려준다(만기된
계약에 미래 날짜를 넣으면 그 계약 만기일 데이터가 온다). stck_bsop_date 가
요청일과 다른 행은 버리고 진단에 센다.

    python research/strategy-lab/build_futures_minute_panel.py --selftest
    python research/strategy-lab/build_futures_minute_panel.py --limit 2
    python research/strategy-lab/build_futures_minute_panel.py            # 전량
    python research/strategy-lab/build_futures_minute_panel.py \
        --products kospi200,usd --sessions night
"""
import argparse
import json
import os
import ssl
import time
import urllib.request
from pathlib import Path

import pandas as pd
import requests

REPO = Path(__file__).resolve().parents[2]
OUT_DIR = REPO / "research" / "strategy-lab" / ".cache" / "futures_minute"
STATE = OUT_DIR / "_state.json"
MANIFEST_DIR = REPO / "data" / "backfill" / "minute" / "manifest"
KIS_BASE = "https://openapi.koreainvestment.com:9443"
KRX_BASE = "https://data-dbg.krx.co.kr/svc/apis/"
MINUTE_PATH = "/uapi/domestic-futureoption/v1/quotations/inquire-time-fuopchartprice"
MINUTE_TR = "FHKIF03020200"
HOUR_CLS = "30"
MAX_PAGES = 20

# 2026-09-03 거래대금 실측으로 고른 것. 금(5억)·위안(4억)·유로(28억)·
# 엔(218억)·변동성지수(2억)는 30초봉에 체결이 거의 없어 뺐다. 원유는 KRX 미상장.
# (KRX 접두, ISU_NM 접두, 주간 시장구분)
PRODUCTS = {
    "kospi200":  ("A016", "코스피200 F", "F"),    # 40.8조/일
    "kosdaq150": ("A066", "코스닥150 F", "F"),    # 2.9조/일
    "usd":       ("A756", "미국달러 F", "CF"),     # 10.7조/일
    "ktb3":      ("A656", "3년국채", "CF"),        # 14.6조/일
    "ktb10":     ("A676", "10년국채", "CF"),       # 7.0조/일
}
# 세션: (마감시각=페이지 시작, 개장시각=여기까지 파면 끝, 야간 시장구분 여부)
SESSIONS = {
    "day":   ("154500", "084500", False),
    "night": ("300000", "180000", True),
}

_CTX = ssl.create_default_context()
_CTX.check_hostname = False
_CTX.verify_mode = ssl.CERT_NONE

MONTH_CHARS = {**{str(i): "%02d" % i for i in range(1, 10)},
               "A": "10", "B": "11", "C": "12"}

ENV = {}
_TOK = {"tok": None, "exp": 0.0}


# ------------------------------------------------------------ 순수 함수

def krx_to_kis_code(isu_cd):
    """KRX 파생 ISU_CD(8) -> KIS FID_INPUT_ISCD(6). 못 바꾸면 None."""
    if not isu_cd or len(isu_cd) != 8:
        return None
    mm = MONTH_CHARS.get(isu_cd[4])
    return None if mm is None else isu_cd[:4] + mm


def expiry_ym(isu_nm):
    """'코스피200 F 202609 (주간)' -> '202609'. 못 읽으면 None."""
    for tok in isu_nm.split():
        if len(tok) == 6 and tok.isdigit():
            return tok
    return None


def pick_front(rows, product):
    """그날 거래된 해당 상품 주간물 중 거래량 최대(=근월) KRX 행. 없으면 None.

    거래량 기준이라 롤오버가 자동으로 반영된다. 야간물은 주간물과 ISU_CD 가
    같으므로(실측) 계약 선택은 주간 행만 보면 된다.
    """
    prefix, nm_prefix, _ = PRODUCTS[product]
    cands = [r for r in rows
             if r.get("ISU_CD", "").startswith(prefix)
             and r.get("ISU_NM", "").startswith(nm_prefix)
             and "(주간)" in r.get("ISU_NM", "")
             and expiry_ym(r["ISU_NM"])]
    return max(cands, key=lambda r: int(r.get("ACC_TRDVOL") or 0)) if cands else None


def prev_hour(hhmmss):
    """페이지네이션용: 마지막으로 받은 시각의 1초 앞. 야간 30시 표기도 처리."""
    t = int(hhmmss[:2]) * 3600 + int(hhmmss[2:4]) * 60 + int(hhmmss[4:]) - 1
    if t < 0:
        return None
    return "%02d%02d%02d" % (t // 3600, t % 3600 // 60, t % 60)


def trading_dates():
    """우리 분봉 manifest 가 곧 KRX 실제 거래일 목록이다(추정 캘린더 금지)."""
    return sorted(p.stem for p in MANIFEST_DIR.glob("*.json"))


def market_div(product, session):
    return "CM" if SESSIONS[session][2] else PRODUCTS[product][2]


# ------------------------------------------------------------ 네트워크

def load_env():
    env = {}
    p = REPO / ".env"
    if p.exists():
        for line in p.read_text(encoding="utf-8").splitlines():
            k, _, v = line.partition("=")
            if k.strip():
                env[k.strip()] = v.strip()
    env.update({k: v for k, v in os.environ.items() if k.startswith(("KIS_", "KRX_"))})
    return env


def kis_token():
    if _TOK["tok"] and time.time() < _TOK["exp"]:
        return _TOK["tok"]
    for _ in range(8):
        r = requests.post(KIS_BASE + "/oauth2/tokenP",
                          json={"grant_type": "client_credentials",
                                "appkey": ENV["KIS_APP_KEY"],
                                "appsecret": ENV["KIS_APP_SECRET"]}, timeout=20).json()
        if "access_token" in r:
            _TOK.update(tok=r["access_token"], exp=time.time() + 3600 * 18)
            return _TOK["tok"]
        time.sleep(20)
    raise SystemExit("KIS 토큰 발급 실패")


def krx_futures(date):
    req = urllib.request.Request(KRX_BASE + "drv/fut_bydd_trd?basDd=" + date,
                                 headers={"AUTH_KEY": ENV["KRX_OPENAPI_KEY"],
                                          "User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=30, context=_CTX) as r:
        return json.loads(r.read().decode("utf-8")).get("OutBlock_1") or []


def fetch_page(code, div, date, hour):
    tok = kis_token()
    for attempt in range(4):
        try:
            r = requests.get(KIS_BASE + MINUTE_PATH,
                             headers={"content-type": "application/json",
                                      "authorization": "Bearer " + tok,
                                      "appkey": ENV["KIS_APP_KEY"],
                                      "appsecret": ENV["KIS_APP_SECRET"],
                                      "tr_id": MINUTE_TR, "custtype": "P"},
                             params={"FID_COND_MRKT_DIV_CODE": div,
                                     "FID_INPUT_ISCD": code,
                                     "FID_HOUR_CLS_CODE": HOUR_CLS,
                                     "FID_PW_DATA_INCU_YN": "Y",
                                     "FID_FAKE_TICK_INCU_YN": "N",
                                     "FID_INPUT_DATE_1": date,
                                     "FID_INPUT_HOUR_1": hour},
                             timeout=25)
            if r.status_code == 200:
                return r.json()
        except Exception:
            pass
        time.sleep(2 + 2 * attempt)
    return {}


def fetch_session(code, div, date, session, throttle):
    """하루치 한 세션. (bars, dateMismatch) - 요청일과 다른 날짜 행은 버린다."""
    end, open_, _ = SESSIONS[session]
    bars, mismatch, hour = {}, 0, end
    for _ in range(MAX_PAGES):
        out2 = (fetch_page(code, div, date, hour).get("output2") or [])
        if not out2:
            break
        oldest, before = None, len(bars)
        for row in out2:
            if row.get("stck_bsop_date") != date:
                mismatch += 1
                continue
            hh = row.get("stck_cntg_hour")
            bars[hh] = row
            oldest = hh if oldest is None or hh < oldest else oldest
        # 새 봉이 안 늘면 더 파도 소용없다(체결이 드문 계약에서 페이지가 전부
        # 다른 날짜로 채워지는 것을 막는다)
        if oldest is None or len(bars) == before or oldest <= open_:
            break
        hour = prev_hour(oldest)
        if hour is None:
            break
        time.sleep(throttle)
    return bars, mismatch


# ------------------------------------------------------------ 실행

def run(products, sessions, limit=None, since=None, throttle=0.5):
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    state = json.loads(STATE.read_text()) if STATE.exists() else {"done": {}}
    done = state.setdefault("done", {})
    dates = [d for d in trading_dates() if not since or d >= since]
    if limit:
        dates = dates[-limit:]
    todo = [(d, p, s) for d in dates for p in products for s in sessions
            if "%s|%s|%s" % (d, p, s) not in done]
    print("대상 %d건 (날짜 %d · 상품 %d · 세션 %d) · 이미 완료 %d건"
          % (len(todo), len(dates), len(products), len(sessions), len(done)), flush=True)

    krx_cache, t0 = {}, time.time()
    for n, (date, product, session) in enumerate(todo, 1):
        d8 = date.replace("-", "")
        if d8 not in krx_cache:
            try:
                krx_cache[d8] = krx_futures(d8)
            except Exception as e:
                print("  %s KRX 실패 %s - 건너뜀" % (date, type(e).__name__), flush=True)
                continue
        row = pick_front(krx_cache[d8], product)
        key = "%s|%s|%s" % (date, product, session)
        if row is None:
            done[key] = 0
            STATE.write_text(json.dumps(state))
            continue
        kis = krx_to_kis_code(row["ISU_CD"])
        if not kis:
            done[key] = 0
            STATE.write_text(json.dumps(state))
            continue
        bars, mism = fetch_session(kis, market_div(product, session), d8, session, throttle)
        if bars:
            frames = [{"date": date, "session": session, "product": product,
                       "hhmmss": hh, "krxCode": row["ISU_CD"], "kisCode": kis,
                       "expiryYm": expiry_ym(row["ISU_NM"]),
                       "open": float(r["futs_oprc"]), "high": float(r["futs_hgpr"]),
                       "low": float(r["futs_lwpr"]), "close": float(r["futs_prpr"]),
                       "volume": int(r["cntg_vol"])} for hh, r in bars.items()]
            sub = OUT_DIR / ("%s_%s" % (product, session))
            sub.mkdir(exist_ok=True)
            (pd.DataFrame(frames).sort_values("hhmmss")
             .to_parquet(sub / (date + ".parquet"), index=False))
        done[key] = len(bars)
        STATE.write_text(json.dumps(state))
        rate = (time.time() - t0) / n
        print("[%d/%d] %s %-9s %-5s %s bars=%d%s  (남은 %.0f분)"
              % (n, len(todo), date, product, session, kis, len(bars),
                 " mism=%d" % mism if mism else "", rate * (len(todo) - n) / 60),
              flush=True)
    got = sum(1 for v in done.values() if v)
    print("끝. 수집 %d건 · 빈 조합 %d건" % (got, len(done) - got), flush=True)


def selftest():
    assert krx_to_kis_code("101W9000") == "101W09"
    assert krx_to_kis_code("A0169000") == "A01609"
    assert krx_to_kis_code("A016C000") == "A01612"      # C = 12월
    assert krx_to_kis_code("A6569000") == "A65609"      # 3년국채
    assert krx_to_kis_code("101L3000") == "101L03"
    assert krx_to_kis_code("A016900") is None           # 길이 위반
    assert krx_to_kis_code("A016X000") is None          # 월 문자 아님
    assert expiry_ym("코스피200 F 202609 (주간)") == "202609"
    assert expiry_ym("코스피200 F (주간)") is None
    assert prev_hour("153000") == "152959"
    assert prev_hour("300000") == "295959"              # 야간 30시 표기
    assert prev_hour("000000") is None
    assert market_div("kospi200", "day") == "F"
    assert market_div("ktb3", "day") == "CF"            # 금리선물은 F 가 아니다
    assert market_div("ktb3", "night") == "CM"
    assert market_div("kospi200", "night") == "CM"
    rows = [{"ISU_CD": "A0169000", "ISU_NM": "코스피200 F 202609 (주간)", "ACC_TRDVOL": "22676"},
            {"ISU_CD": "A016C000", "ISU_NM": "코스피200 F 202612 (주간)", "ACC_TRDVOL": "1877"},
            {"ISU_CD": "A0169000", "ISU_NM": "코스피200 F 202609 (야간)", "ACC_TRDVOL": "99999"},
            {"ISU_CD": "A0569000", "ISU_NM": "미니코스피 F 202609 (주간)", "ACC_TRDVOL": "30075"},
            {"ISU_CD": "A6569000", "ISU_NM": "3년국채    F 202609 (주간)", "ACC_TRDVOL": "1034"}]
    assert pick_front(rows, "kospi200")["ISU_CD"] == "A0169000"
    assert "(주간)" in pick_front(rows, "kospi200")["ISU_NM"]     # 야간물을 안 고른다
    assert pick_front(rows, "ktb3")["ISU_CD"] == "A6569000"      # 미니에 안 끌려간다
    assert pick_front(rows, "kosdaq150") is None
    assert pick_front([], "kospi200") is None
    ds = trading_dates()
    assert len(ds) > 200 and ds[0] < ds[-1], len(ds)
    print("selftest 통과 (23건, 거래일 %d개: %s~%s)" % (len(ds), ds[0], ds[-1]))


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--selftest", action="store_true")
    ap.add_argument("--products", default=",".join(PRODUCTS))
    ap.add_argument("--sessions", default=",".join(SESSIONS))
    ap.add_argument("--limit", type=int)
    ap.add_argument("--since", help="YYYY-MM-DD 이후만")
    ap.add_argument("--throttle", type=float, default=0.5, help="콜 간격(초)")
    a = ap.parse_args()
    if a.selftest:
        selftest()
    else:
        ENV = load_env()
        run([p.strip() for p in a.products.split(",") if p.strip()],
            [s.strip() for s in a.sessions.split(",") if s.strip()],
            limit=a.limit, since=a.since, throttle=a.throttle)
