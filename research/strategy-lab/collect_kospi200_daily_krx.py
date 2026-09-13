# -*- coding: utf-8 -*-
"""KOSPI200 선물 일봉 전 기간 수집기 (KRX drv/fut_bydd_trd).

연구 전용, .cache/ 아래. production 무변경.
- 영업일 후보: 2010-01-04~오늘의 평일 열거, 휴장일은 응답이 빈 배열이라 그냥 지나감.
- 매일 모든 계약행을 연도별 parquet에 누적 저장.
- 상태 파일로 재개 가능. KRX 멱종(빈 응답이 연속으로 오면 잠시 멈춤) 대비.
"""
import datetime as dt
import json
import ssl
import time
import urllib.request
from pathlib import Path

import pandas as pd

REPO = Path(r"C:\Users\User\projects\stock")
OUT_DIR = REPO / "research" / "strategy-lab" / ".cache" / "kospi200_daily"
STATE = OUT_DIR / "_state.json"

_CTX = ssl.create_default_context()
_CTX.check_hostname = False
_CTX.verify_mode = ssl.CERT_NONE


def load_env():
    env = {}
    p = REPO / ".env"
    for line in p.read_text(encoding="utf-8").splitlines():
        k, _, v = line.partition("=")
        if k.strip():
            env[k.strip()] = v.strip()
    return env


ENV = load_env()


def krx_futures(date8):
    req = urllib.request.Request(
        "https://data-dbg.krx.co.kr/svc/apis/drv/fut_bydd_trd?basDd=" + date8,
        headers={"AUTH_KEY": ENV["KRX_OPENAPI_KEY"], "User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=30, context=_CTX) as r:
        return json.loads(r.read().decode("utf-8")).get("OutBlock_1") or []


def business_days(start, end):
    d = start
    while d <= end:
        if d.weekday() < 5:
            yield d
        d += dt.timedelta(days=1)


def main():
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    state = json.loads(STATE.read_text(encoding="utf-8")) if STATE.exists() else {"done": []}
    done = set(state["done"])

    start = dt.date(2010, 1, 4)
    end = dt.date.today()
    skip_night = True  # 야간행은 Skip (주간만 수집, stage3-2는 주간 기준)
    got = 0
    empty_run = 0

    frames = {y: [] for y in range(start.year, end.year + 1)}
    # 기존 년도 파켓이 있으면 먼저 로드 (재개 시 병합)
    for y in frames:
        f = OUT_DIR / ("kospi200_%d.parquet" % y)
        if f.exists():
            frames[y] = pd.read_parquet(f).to_dict("records")

    t0 = time.time()
    for i, d in enumerate(business_days(start, end)):
        d8 = d.strftime("%Y%m%d")
        if d8 in done:
            continue
        try:
            rows = krx_futures(d8)
        except Exception as e:
            print("[%d] %s ERR %s" % (i, d8, repr(e)), flush=True)
            time.sleep(5)
            continue
        if not rows:
            empty_run += 1
            if empty_run >= 8:  # 멱종 의심: 8연속 빈 응답
                print("[%d] %s 한도 추정 - 60초 대기" % (i, d8), flush=True)
                time.sleep(60)
                empty_run = 0
            continue
        empty_run = 0
        kospi = [r for r in rows if r.get("ISU_NM", "").startswith("코스피200 F ")]
        if skip_night:
            kospi = [r for r in kospi if "(야간)" not in r["ISU_NM"]]
        if kospi:
            got += len(kospi)
            frames[d.year].extend(kospi)
        done.add(d8)
        if i % 25 == 0:
            state["done"] = sorted(done)
            STATE.write_text(json.dumps(state), encoding="utf-8")
            for y, recs in frames.items():
                if recs:
                    pd.DataFrame(recs).to_parquet(OUT_DIR / ("kospi200_%d.parquet" % y), index=False)
            rate = (time.time() - t0) / (i + 1)
            print("[%d] %s 누적 일봉 %d행 rate=%.2fs" % (i, d8, got, rate), flush=True)
        time.sleep(0.5)

    state["done"] = sorted(done)
    STATE.write_text(json.dumps(state), encoding="utf-8")
    for y, recs in frames.items():
        if recs:
            pd.DataFrame(recs).to_parquet(OUT_DIR / ("kospi200_%d.parquet" % y), index=False)
    print("완료. 수집 일봉 %d행, 날짜 %d개" % (got, len(done)))


if __name__ == "__main__":
    main()