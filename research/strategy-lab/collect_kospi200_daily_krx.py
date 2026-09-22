# -*- coding: utf-8 -*-
"""KOSPI200 선물 일봉 전 기간 수집기 (KRX drv/fut_bydd_trd).

연구 전용, .cache/ 아래. production 무변경.
- 영업일 후보: 2010-01-04~오늘의 평일 열거, 휴장일은 응답이 빈 배열이라 그냥 지나감.
- 매일 모든 계약행을 연도별 parquet에 누적 저장.
- 상태 파일로 재개 가능. KRX 멱종(빈 응답이 연속으로 오면 잠시 멈춤) 대비.
- 빈 응답(휴장일)은 EMPTY_SETTLE_DAYS 지난 날짜만 state["empty"]에 기록하고 다시 조회하지 않는다
  (2026-09-23: 기록이 없어 매 실행마다 2010년 이후 휴장일 전부를 재조회, 8건마다 60초 대기 -> RV20 주문이
  09:05 가 아니라 09:35 에 나갔다). 최근 날짜는 늦게 게시될 수 있어 계속 재조회한다.
  실제 거래일이 빈 응답으로 잘못 기록됐다고 의심되면 state["empty"]에서 그 날짜를 지우면 다시 조회한다.
"""
import datetime as dt
import json
import os
import ssl
import time
import urllib.request
from pathlib import Path

import pandas as pd

REPO = Path(__file__).resolve().parents[2]  # 로컬 Windows 전용 하드코딩이던 것을
# 2026-09-14에 포터블로 바꿈 - VM(Linux)에서 rv20-futures-paper-order.timer가
# 이 스크립트를 직접 부르면서 처음 걸림(FileNotFoundError: 'C:\...\.env' 없음).
OUT_DIR = REPO / "research" / "strategy-lab" / ".cache" / "kospi200_daily"
STATE = OUT_DIR / "_state.json"

EMPTY_SETTLE_DAYS = 7  # 이만큼 지난 빈 응답만 휴장일로 확정

_CTX = ssl.create_default_context()
_CTX.check_hostname = False
_CTX.verify_mode = ssl.CERT_NONE


def load_env():
    """저장소 루트 .env(로컬 개발환경)와 systemd EnvironmentFile(VM, 파일이
    collector-venv/.env처럼 다른 자리에 있고 os.environ으로 이미 주입돼
    있음) 둘 다 지원한다 - kisVtsClient.py/_load_env()와 같은 패턴
    (2026-09-14, VM 실측: REPO/.env가 없어 FileNotFoundError로 죽던 문제)."""
    env = {}
    p = REPO / ".env"
    if p.exists():
        for line in p.read_text(encoding="utf-8").splitlines():
            k, _, v = line.partition("=")
            if k.strip():
                env[k.strip()] = v.strip()
    if os.environ.get("KRX_OPENAPI_KEY"):
        env["KRX_OPENAPI_KEY"] = os.environ["KRX_OPENAPI_KEY"]
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
    empty = set(state.get("empty", []))

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
        if d8 in done or d8 in empty:
            continue
        try:
            rows = krx_futures(d8)
        except Exception as e:
            print("[%d] %s ERR %s" % (i, d8, repr(e)), flush=True)
            time.sleep(5)
            continue
        if not rows:
            if (end - d).days >= EMPTY_SETTLE_DAYS:
                empty.add(d8)
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
            state["empty"] = sorted(empty)
            STATE.write_text(json.dumps(state), encoding="utf-8")
            for y, recs in frames.items():
                if recs:
                    pd.DataFrame(recs).to_parquet(OUT_DIR / ("kospi200_%d.parquet" % y), index=False)
            rate = (time.time() - t0) / (i + 1)
            print("[%d] %s 누적 일봉 %d행 rate=%.2fs" % (i, d8, got, rate), flush=True)
        time.sleep(0.5)

    state["done"] = sorted(done)
    state["empty"] = sorted(empty)
    STATE.write_text(json.dumps(state), encoding="utf-8")
    for y, recs in frames.items():
        if recs:
            pd.DataFrame(recs).to_parquet(OUT_DIR / ("kospi200_%d.parquet" % y), index=False)
    print("완료. 수집 일봉 %d행, 날짜 %d개" % (got, len(done)))


if __name__ == "__main__":
    main()