#!/usr/bin/env python3
"""KOSPI200 선물 30초봉 패널 수집 (연구 전용).

data/backfill/ 에 쓰지 않는다 - PEAD build_quarterly_earnings_panel.py 와 같은
스코프(정책 파일·GH Actions·manifest 없음). 산출물은 .cache/futures_minute/.

경로 (2026-09-04 Phase 0 실측으로 확정):
  계약 선택   KRX Open API drv/fut_bydd_trd (무료·로그인 불필요, 2016~)
              그날 실제 거래된 계약과 거래량을 주므로 롤오버가 자동으로 잡힌다.
  코드 변환   KRX ISU_CD(8자리) -> KIS FID_INPUT_ISCD(6자리)
              101W9000 -> 101W09 · A0169000 -> A01609
              앞 4자 + 5번째 문자(월: 1~9,A,B,C)를 2자리 숫자로.
              * 2026년물부터 접두가 101 -> A016 으로 바뀌었다. 연도 문자를
                외삽하면 틀린다 - 반드시 KRX 에서 그날 코드를 읽는다.
  분봉        KIS inquire-time-fuopchartprice / FHKIF03020200 / 실전 도메인
              FID_HOUR_CLS_CODE=30 이 과거 조회가 되는 최소 해상도.
              (1·5·10초는 당일만. 60·120·300·600 은 과거 가능)
              콜당 102건 고정 -> 하루 30초봉 약 816건 = 8페이지.
  보존창      2025-08-29 O · 2025-08-25 X (오늘-약 1년 롤링, 매일 앞이 잘린다)

교훈81 게이트: rt_cd=0 이어도 요청일과 다른 날짜를 조용히 돌려준다
  (만기된 계약에 미래 날짜를 넣으면 그 계약 만기일 데이터가 온다).
  stck_bsop_date != 요청일 인 행은 버리고 진단에 센다.

    python research/strategy-lab/build_futures_minute_panel.py --selftest
    python research/strategy-lab/build_futures_minute_panel.py --limit 3
    python research/strategy-lab/build_futures_minute_panel.py
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
HOUR_CLS = "30"          # 30초 - 과거 조회가 되는 최소 해상도
SESSION_END = "154500"
SESSION_OPEN = "084500"  # 이보다 오래된 페이지가 나오면 그만 판다
MAX_PAGES = 12
THROTTLE = 1.1

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
    """코스피200 F 202609 (주간) -> 202609. 못 읽으면 None."""
    for tok in isu_nm.split():
        if len(tok) == 6 and tok.isdigit():
            return tok
    return None


def pick_contracts(rows):
    """그날 거래된 코스피200 주간선물에서 (근월, 차근월) KRX 행을 고른다.

    근월은 거래량 최대(롤오버가 자동으로 반영된다), 차근월은 그 다음 만기.
    미니선물(미니 코스피200)과 야간물은 뺀다.
    """
    k = [r for r in rows
         if r.get("ISU_NM", "").startswith("코스피200 F")
         and "(주간)" in r.get("ISU_NM", "")
         and expiry_ym(r["ISU_NM"])]
    if not k:
        return []
    front = max(k, key=lambda r: int(r.get("ACC_TRDVOL") or 0))
    later = sorted((r for r in k
                    if expiry_ym(r["ISU_NM"]) > expiry_ym(front["ISU_NM"])),
                   key=lambda r: expiry_ym(r["ISU_NM"]))
    return [front] + later[:1]


def prev_hour(hhmmss, step_seconds=1):
    """페이지네이션용: 마지막으로 받은 시각의 한 칸 앞."""
    h, m, s = int(hhmmss[:2]), int(hhmmss[2:4]), int(hhmmss[4:])
    t = h * 3600 + m * 60 + s - step_seconds
    if t < 0:
        return None
    return "%02d%02d%02d" % (t // 3600, t % 3600 // 60, t % 60)


def trading_dates():
    """우리 분봉 manifest 가 곧 KRX 실제 거래일 목록이다(추정 캘린더 금지)."""
    return sorted(p.stem for p in MANIFEST_DIR.glob("*.json"))


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
    for _ in range(6):
        r = requests.post(KIS_BASE + "/oauth2/tokenP",
                          json={"grant_type": "client_credentials",
                                "appkey": ENV["KIS_APP_KEY"],
                                "appsecret": ENV["KIS_APP_SECRET"]}, timeout=20).json()
        if "access_token" in r:
            _TOK.update(tok=r["access_token"], exp=time.time() + 3600 * 20)
            return _TOK["tok"]
        time.sleep(20)
    raise SystemExit("KIS 토큰 발급 실패")


def krx_futures(date):
    req = urllib.request.Request(KRX_BASE + "drv/fut_bydd_trd?basDd=" + date,
                                 headers={"AUTH_KEY": ENV["KRX_OPENAPI_KEY"],
                                          "User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=30, context=_CTX) as r:
        return json.loads(r.read().decode("utf-8")).get("OutBlock_1") or []


def fetch_page(code, date, hour):
    tok = kis_token()
    for _ in range(4):
        r = requests.get(KIS_BASE + MINUTE_PATH,
                         headers={"content-type": "application/json",
                                  "authorization": "Bearer " + tok,
                                  "appkey": ENV["KIS_APP_KEY"],
                                  "appsecret": ENV["KIS_APP_SECRET"],
                                  "tr_id": MINUTE_TR, "custtype": "P"},
                         params={"FID_COND_MRKT_DIV_CODE": "F",
                                 "FID_INPUT_ISCD": code,
                                 "FID_HOUR_CLS_CODE": HOUR_CLS,
                                 "FID_PW_DATA_INCU_YN": "Y",
                                 "FID_FAKE_TICK_INCU_YN": "N",
                                 "FID_INPUT_DATE_1": date,
                                 "FID_INPUT_HOUR_1": hour},
                         timeout=25)
        if r.status_code == 200:
            return r.json()
        time.sleep(3)
    return {}


def fetch_day(code, date):
    """하루치 30초봉. (bars, dateMismatch) - 요청일과 다른 날짜 행은 버린다."""
    bars, mismatch, hour = {}, 0, SESSION_END
    for _ in range(MAX_PAGES):
        out2 = (fetch_page(code, date, hour).get("output2") or [])
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
        # 새 봉이 하나도 안 늘면 더 파도 소용없다(차근월처럼 체결이 드문 계약에서
        # 페이지가 전부 다른 날짜로 채워지는 것을 막는다)
        if oldest is None or len(bars) == before or oldest <= SESSION_OPEN:
            break
        hour = prev_hour(oldest)
        if hour is None:
            break
        time.sleep(THROTTLE)
    return bars, mismatch


# ------------------------------------------------------------ 실행

def run(limit=None, since=None):
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    state = json.loads(STATE.read_text()) if STATE.exists() else {"done": [], "empty": []}
    done, empty = set(state["done"]), set(state.get("empty", []))
    dates = [d for d in trading_dates() if not since or d >= since]
    dates = [d for d in dates if d not in done and d not in empty]
    if limit:
        dates = dates[-limit:]
    print("대상 %d일 (완료 %d · 빈날 %d)" % (len(dates), len(done), len(empty)), flush=True)

    for i, date in enumerate(dates, 1):
        d8 = date.replace("-", "")
        try:
            picks = pick_contracts(krx_futures(d8))
        except Exception as e:
            print("  %s KRX 실패 %s - 건너뜀" % (date, type(e).__name__), flush=True)
            continue
        if not picks:
            empty.add(date)
            print("[%d/%d] %s KRX 계약 없음" % (i, len(dates), date), flush=True)
            continue
        frames, note = [], []
        for rank, row in enumerate(picks):
            kis = krx_to_kis_code(row["ISU_CD"])
            if not kis:
                continue
            bars, mism = fetch_day(kis, d8)
            note.append("%s:%d%s" % (kis, len(bars), "(mism %d)" % mism if mism else ""))
            for hh, r in bars.items():
                frames.append({"date": date, "hhmmss": hh, "krxCode": row["ISU_CD"],
                               "kisCode": kis, "rank": rank,
                               "expiryYm": expiry_ym(row["ISU_NM"]),
                               "open": float(r["futs_oprc"]), "high": float(r["futs_hgpr"]),
                               "low": float(r["futs_lwpr"]), "close": float(r["futs_prpr"]),
                               "volume": int(r["cntg_vol"])})
            time.sleep(THROTTLE)
        if not frames:
            empty.add(date)
        else:
            (pd.DataFrame(frames).sort_values(["rank", "hhmmss"])
             .to_parquet(OUT_DIR / (date + ".parquet"), index=False))
            done.add(date)
        state["done"], state["empty"] = sorted(done), sorted(empty)
        STATE.write_text(json.dumps(state, indent=1))
        print("[%d/%d] %s %s" % (i, len(dates), date, " ".join(note) or "EMPTY"), flush=True)
    print("끝. 완료 %d일 · 빈날 %d일" % (len(done), len(empty)), flush=True)


def selftest():
    assert krx_to_kis_code("101W9000") == "101W09"
    assert krx_to_kis_code("A0169000") == "A01609"
    assert krx_to_kis_code("A016C000") == "A01612"   # C = 12월
    assert krx_to_kis_code("101L3000") == "101L03"
    assert krx_to_kis_code("A016900") is None        # 길이 위반
    assert krx_to_kis_code("A016X000") is None       # 월 문자 아님
    assert expiry_ym("코스피200 F 202609 (주간)") == "202609"
    assert expiry_ym("코스피200 F (주간)") is None
    assert prev_hour("153000") == "152959"
    assert prev_hour("090000") == "085959"
    assert prev_hour("000000") is None
    rows = [{"ISU_CD": "A0169000", "ISU_NM": "코스피200 F 202609 (주간)", "ACC_TRDVOL": "22676"},
            {"ISU_CD": "A016C000", "ISU_NM": "코스피200 F 202612 (주간)", "ACC_TRDVOL": "1877"},
            {"ISU_CD": "A0179000", "ISU_NM": "코스피200 F 202709 (주간)", "ACC_TRDVOL": "3"},
            {"ISU_CD": "A0569000", "ISU_NM": "미니 코스피200 F 202609 (주간)", "ACC_TRDVOL": "999999"},
            {"ISU_CD": "A0169000", "ISU_NM": "코스피200 F 202609 (야간)", "ACC_TRDVOL": "50000"}]
    got = pick_contracts(rows)
    assert [r["ISU_CD"] for r in got] == ["A0169000", "A016C000"], got
    assert all(r["ISU_NM"].endswith("(주간)") for r in got)
    assert pick_contracts([]) == []
    ds = trading_dates()
    assert len(ds) > 200 and ds[0] < ds[-1], len(ds)
    print("selftest 통과 (14건, 거래일 %d개: %s~%s)" % (len(ds), ds[0], ds[-1]))


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--selftest", action="store_true")
    ap.add_argument("--limit", type=int)
    ap.add_argument("--since", help="YYYY-MM-DD 이후만")
    a = ap.parse_args()
    if a.selftest:
        selftest()
    else:
        ENV = load_env()
        run(limit=a.limit, since=a.since)
