# -*- coding: utf-8 -*-
"""코스피200 옵션 일별 전 기간 수집기 (KRX Open API drv/opt_bydd_trd) — 옵션 감마 연구 전용.

사전등록: findings/kospi200-option-gamma-preregistration-2026-09.md. .cache/ 아래(gitignore), production 무변경.
- 남기는 상품: 코스피200 옵션 · 코스피200 위클리(월/목) 옵션 · 미니코스피200 옵션. 야간행은 버린다(주간 종가 기준).
- 선물 수집기(collect_kospi200_daily_krx.py)와 같은 이어받기·휴장일 확정 규칙. 키·SSL 설정은 그 모듈 것을 쓴다.
- ★ 같은 키를 RV20 09:05 선물 수집이 쓴다 — 전량 수집은 장 시작 전에 끝나게 밤에 돌린다.

  python research/strategy-lab/collect_kospi200_options_krx.py [--start 2010-01-04] [--end 2026-09-28] [--max-calls N]
"""
import argparse
import datetime as dt
import json
import time
import urllib.request

import pandas as pd

from collect_kospi200_daily_krx import _CTX, ENV, EMPTY_SETTLE_DAYS, REPO, business_days

OUT_DIR = REPO / "research" / "strategy-lab" / ".cache" / "kospi200_options"
STATE = OUT_DIR / "_state.json"
PRODUCTS = {"코스피200 옵션", "코스피200 위클리(월) 옵션", "코스피200 위클리(목) 옵션", "미니코스피200 옵션"}
KEEP = ["BAS_DD", "PROD_NM", "RGHT_TP_NM", "ISU_CD", "ISU_NM", "TDD_CLSPRC", "IMP_VOLT", "ACC_TRDVOL", "ACC_OPNINT_QTY"]


def krx_options(date8):
    req = urllib.request.Request(
        "https://data-dbg.krx.co.kr/svc/apis/drv/opt_bydd_trd?basDd=" + date8,
        headers={"AUTH_KEY": ENV["KRX_OPENAPI_KEY"], "User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=60, context=_CTX) as r:
        return json.loads(r.read().decode("utf-8")).get("OutBlock_1") or []


def keep_rows(rows):
    return [{k: r.get(k, "") for k in KEEP} for r in rows
            if r.get("PROD_NM") in PRODUCTS and "(야간)" not in r.get("ISU_NM", "")]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--start", default="2010-01-04")
    ap.add_argument("--end", default=dt.date.today().isoformat())
    ap.add_argument("--max-calls", type=int, default=0, help="0=제한 없음")
    a = ap.parse_args()
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    state = json.loads(STATE.read_text(encoding="utf-8")) if STATE.exists() else {"done": [], "empty": []}
    done, empty = set(state["done"]), set(state.get("empty", []))
    start, end = dt.date.fromisoformat(a.start), dt.date.fromisoformat(a.end)
    frames = {}

    def flush():
        state["done"], state["empty"] = sorted(done), sorted(empty)
        for y, recs in frames.items():
            f = OUT_DIR / f"options_{y}.parquet"
            old = pd.read_parquet(f) if f.exists() else None
            df = pd.DataFrame(recs)
            if old is not None:
                df = pd.concat([old[~old["BAS_DD"].isin(df["BAS_DD"].unique())], df], ignore_index=True)
            df.to_parquet(f, index=False)
        frames.clear()
        STATE.write_text(json.dumps(state), encoding="utf-8")   # 파일을 쓴 뒤에 상태 — 반대면 끊겼을 때 날짜가 샌다

    calls = empty_run = fails = 0
    t0 = time.time()
    for d in business_days(start, end):
        d8 = d.strftime("%Y%m%d")
        if d8 in done or d8 in empty:
            continue
        if a.max_calls and calls >= a.max_calls:
            break
        calls += 1
        try:
            rows = krx_options(d8)
            fails = 0
        except Exception as e:
            fails += 1
            print(f"{d8} ERR {e!r}", flush=True)
            if fails >= 3:
                print("연속 3회 실패 — 멈춘다(다음 실행이 이어 간다)")
                break
            time.sleep(5)
            continue
        if not rows:
            if (dt.date.today() - d).days >= EMPTY_SETTLE_DAYS:
                empty.add(d8)
            empty_run += 1
            if empty_run >= 8:
                print(f"{d8} 빈 응답 8연속 — 60초 대기", flush=True)
                time.sleep(60)
                empty_run = 0
            continue
        empty_run = 0
        kept = keep_rows(rows)
        if not kept:   # 응답은 있는데 코스피200 옵션이 0행 — 휴장일이 아니다. 조용히 넘기지 않는다(교훈75)
            print(f"{d8} 응답 {len(rows)}행 중 코스피200 옵션 0행 — 기록 안 함", flush=True)
            continue
        frames.setdefault(d.year, []).extend(kept)
        done.add(d8)
        if calls % 25 == 0:
            flush()
            print(f"{d8} 호출 {calls} · 날짜 {len(done)} · {(time.time() - t0) / calls:.2f}s/콜", flush=True)
        time.sleep(0.3)
    flush()
    print(f"완료. 호출 {calls} · 수집 날짜 {len(done)} · 휴장 확정 {len(empty)}")


if __name__ == "__main__":
    main()
