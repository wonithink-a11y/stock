"""ETF 일별 OHLC·NAV·기초지수 원본 수집 — ETF 횡단면 실험용(2026-09-22 사용자 수집 승인).

소스: KRX Open API `etp/etf_bydd_trd`(기존 scripts/build-etf-price-history.py 와 같은 키·호출). 그 스크립트는 종가만
남기지만, 이 실험(종가→익일 시가 신호)은 **시가**가 필요하고 국내/해외 기초자산 분류에 **기초지수명(IDX_IND_NM)** 이
필요해 응답 필드를 **전부** 그대로 저장한다.

★ 생존편향 없음: 날짜별 응답은 **그날 상장돼 있던 ETF 전부**다(나중에 폐지된 것 포함). pykrx·yfinance 경로보다 낫다.
★ 조회했더니 없음 ≠ 조회 안 함(교훈 75): 날마다 `{"_day": ..., "n": 행수}` 표시 줄을 남긴다. 휴장일은 n=0.
   2014 이전은 거래일 달력이 없어 평일 전부를 묻고 빈 응답을 휴장으로 기록한다.
★ 이어받기: 표시 줄이 있는 날은 건너뛴다. 연속 3회 실패하면 멈춘다(호출 한도 모름 — 다음 실행이 이어 간다).
   행을 쓰고 표시 줄 전에 죽으면 그날 행이 두 번 들어갈 수 있다 — 읽는 쪽이 (BAS_DD, ISU_CD) 로 중복을 없앤다.
★ 저장: research/strategy-lab/data/etf-ohlc/<연도>.jsonl (gitignore). 연구 데이터라 저장소에 올리지 않는다.

    python research/strategy-lab/collect_etf_ohlc_krx.py                 # 2010-01-04 ~ 어제
    python research/strategy-lab/collect_etf_ohlc_krx.py --report         # 수집 현황만(네트워크 없음)
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import os
import sys
import time
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
OUT = REPO / "research" / "strategy-lab" / "data" / "etf-ohlc"
CAL = REPO / "data" / "backfill" / "calendar.json"
KST = timezone(timedelta(hours=9))

_spec = importlib.util.spec_from_file_location("etfhist", REPO / "scripts" / "build-etf-price-history.py")
_etf = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_etf)                          # krx_get 재사용(같은 키·같은 호출)


def load_key() -> str:
    if os.environ.get("KRX_OPENAPI_KEY"):
        return os.environ["KRX_OPENAPI_KEY"]
    for line in (REPO / ".env").read_text(encoding="utf-8").splitlines():
        if line.startswith("KRX_OPENAPI_KEY="):
            return line.split("=", 1)[1].strip().strip('"').strip("'")
    raise SystemExit("KRX_OPENAPI_KEY 가 없다(환경변수 또는 .env)")


def days_to_ask(start: date, end: date) -> list:
    cal = set(json.loads(CAL.read_text(encoding="utf-8"))["tradingDays"])
    first_cal = min(cal)
    out, d = [], start
    while d <= end:
        iso = d.isoformat()
        if iso < first_cal:
            if d.weekday() < 5:
                out.append(iso)                         # 달력 이전: 평일 전부(빈 응답 = 휴장)
        elif iso in cal:
            out.append(iso)
        d += timedelta(days=1)
    return out


def done_days() -> dict:
    got = {}
    for f in OUT.glob("*.jsonl"):
        for line in f.open(encoding="utf-8"):
            if line.startswith('{"_day"'):
                r = json.loads(line)
                got[r["_day"]] = r["n"]
    return got


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--start", default="2010-01-04")
    ap.add_argument("--end", default=(datetime.now(KST).date() - timedelta(days=1)).isoformat())
    ap.add_argument("--report", action="store_true")
    ap.add_argument("--sleep", type=float, default=0.3)
    a = ap.parse_args()
    todo_all = days_to_ask(date.fromisoformat(a.start), date.fromisoformat(a.end))
    done = done_days()
    todo = [d for d in todo_all if d not in done]
    print(f"대상 {len(todo_all)}일 · 완료 {len(done)}일(행 {sum(done.values()):,}) · 남음 {len(todo)}일")
    if a.report or not todo:
        return 0
    key = load_key()
    OUT.mkdir(parents=True, exist_ok=True)
    fails = 0
    for i, d in enumerate(todo, 1):
        try:
            rows = _etf.krx_get(key, "etp/etf_bydd_trd", d.replace("-", ""))
        except Exception as e:                          # noqa: BLE001
            fails += 1
            print(f"{d} 실패 {type(e).__name__}: {e}"[:160], flush=True)
            if fails >= 3:
                print("연속 3회 실패 — 멈춘다(다시 실행하면 이어 받는다)")
                return 1
            time.sleep(5)
            continue
        fails = 0
        with (OUT / f"{d[:4]}.jsonl").open("a", encoding="utf-8") as f:
            for r in rows:
                f.write(json.dumps(r, ensure_ascii=False) + "\n")
            f.write(json.dumps({"_day": d, "n": len(rows)}) + "\n")   # 표시 줄은 행 뒤에 — 도중에 죽으면 그날을 다시 받는다
        if i % 100 == 0 or i == len(todo):
            print(f"{i}/{len(todo)} {d} {len(rows)}행", flush=True)
        time.sleep(a.sleep)
    return 0


if __name__ == "__main__":
    sys.exit(main())
