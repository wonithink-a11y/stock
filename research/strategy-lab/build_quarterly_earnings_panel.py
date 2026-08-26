#!/usr/bin/env python
"""분기 순이익(SUE 원재료) 전체 유니버스 수집 - findings/pead-quarterly-pilot-
2026-08.md가 유동성 상위 100종목·2,250콜 파일럿에서 경계선 신호(T+60 IC
t=1.96)를 확인한 뒤, 사용자 확인 후 전면 수집을 진행한다.

**연구 전용 - production A-series가 아니다.** valuation-panel.jsonl(PBR)·
market_regime_features.parquet(거시)와 같은 패턴: 새 DART 데이터를 모으지만
data/backfill/(규칙 4, GH Actions 전용)에는 안 쓴다 - PEAD는 여전히 "연구
후보, production 미확정" 단계라 config/policies·GH Actions 워크플로 같은
정식 A3-계열 인프라를 미리 짓지 않는다(과잉 설계 - 채택이 결정되면 그때
정식화한다).

DART_API_KEY는 커밋 안 함, 매 실행 인라인 env로만 쓴다. 일일 한도는
config/policies/fundamentals.v1.json의 dailyCallLimit=40,000(2026-08-13
확정)과 같은 계정 키를 공유하므로, 이 스크립트도 안전마진을 두고
`--daily-budget`(기본 36,000, A3/A3b/A3c와 같은 날 겹쳐 돌 가능성을 감안한
여유)에서 멈춘다. quotaExceeded(status 020)도 별도로 감지해 즉시 중단한다.
KST 날짜가 바뀌면 카운터만 리셋하고 진행 상황(doneKeys)은 그대로 이어간다 -
재실행이 선택이 아니라 계약이다(A3 계약과 동일 원칙).

전체 25,531 corp-year x 3콜(Q1·반기·3분기) ≈ 76,600콜 - 일 한도 안에서
여러 날에 걸쳐 나눠 실행한다(하루에 한 번 이상 실행해도 안전 - state 파일이
막아준다).

  python build_quarterly_earnings_panel.py                 # 이어서 계속
  python build_quarterly_earnings_panel.py --daily-budget 30000
"""
import argparse
import gzip
import json
import os
import re
import sys
import time
from datetime import datetime, timezone, timedelta

import requests

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
A3_DIR = os.path.join(REPO_ROOT, "data", "backfill", "fundamentals", "a3")
OUT_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "quarterly-earnings")
OUT_PANEL = os.path.join(OUT_DIR, "quarterly-earnings-panel.jsonl")
STATE_PATH = os.path.join(OUT_DIR, "_state.json")
BASE = "https://opendart.fss.or.kr/api"
KEY = os.environ.get("DART_API_KEY", "")
SECRET_RE = re.compile(r"(crtfc_key=)[^&\s\"')]+")
QUOTA_EXCEEDED_STATUS = "020"
REPRT_CODES = ["11013", "11012", "11014"]  # Q1·반기(Q2단독)·3분기(Q3단독)
KST = timezone(timedelta(hours=9))


def redact(s):
    return SECRET_RE.sub(r"\1<redacted>", str(s))


def today_kst():
    return datetime.now(KST).strftime("%Y-%m-%d")


def load_state():
    if os.path.exists(STATE_PATH):
        with open(STATE_PATH, encoding="utf-8") as f:
            state = json.load(f)
    else:
        state = {"date": today_kst(), "callsUsedToday": 0, "doneKeys": []}
    if state["date"] != today_kst():
        state["date"] = today_kst()
        state["callsUsedToday"] = 0
    state["doneKeys"] = set(state["doneKeys"])
    return state


def save_state(state):
    os.makedirs(OUT_DIR, exist_ok=True)
    with open(STATE_PATH, "w", encoding="utf-8") as f:
        json.dump({**state, "doneKeys": sorted(state["doneKeys"])}, f, ensure_ascii=False, indent=2)


def load_a3_grid():
    rows = []
    for fname in sorted(os.listdir(A3_DIR)):
        if not fname.endswith(".jsonl.gz"):
            continue
        with gzip.open(os.path.join(A3_DIR, fname), "rt", encoding="utf-8") as f:
            for line in f:
                d = json.loads(line)
                rows.append({"ticker": d["ticker"], "corp": d["corp"], "fiscalYear": d["fiscalYear"]})
    rows.sort(key=lambda r: (r["ticker"], r["fiscalYear"]))
    return rows


def dart_call(reprt_code, corp, year):
    params = {"crtfc_key": KEY, "corp_code": corp, "bsns_year": str(year), "reprt_code": reprt_code}
    try:
        r = requests.get(f"{BASE}/fnlttSinglAcnt.json", params=params, timeout=(10, 60))
    except Exception as e:
        return None, "transport:" + redact(str(e))
    try:
        body = r.json()
    except Exception as e:
        return None, "parse:" + redact(str(e))
    status = body.get("status")
    if status != "000":
        return None, status
    return body.get("list", []), None


def extract_net_income(rows):
    for fs_div in ("CFS", "OFS"):
        cands = [r for r in rows if r.get("fs_div") == fs_div and r.get("sj_div") == "IS"
                 and r.get("account_nm") == "당기순이익(손실)"]
        if cands:
            cands.sort(key=lambda r: int(r.get("ord", 999)))
            r = cands[0]

            def num(x):
                try:
                    return float(str(x).replace(",", ""))
                except (TypeError, ValueError):
                    return None
            return {"thstrm": num(r.get("thstrm_amount")), "frmtrm": num(r.get("frmtrm_amount")),
                     "rceptNo": r.get("rcept_no")}
    return None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--daily-budget", type=int, default=36_000)
    ap.add_argument("--sleep", type=float, default=0.15)
    args = ap.parse_args()

    if not KEY:
        print("DART_API_KEY not set")
        sys.exit(1)

    grid = load_a3_grid()
    print(f"A3 grid: {len(grid)} corp-years, {len({r['ticker'] for r in grid})} tickers")

    state = load_state()
    print(f"resuming: date={state['date']} callsUsedToday={state['callsUsedToday']} "
          f"done={len(state['doneKeys'])}/{len(grid)}")

    os.makedirs(OUT_DIR, exist_ok=True)
    out_f = open(OUT_PANEL, "a", encoding="utf-8")

    t0 = time.time()
    n_new_records, n_new_calls, n_fail = 0, 0, 0
    quota_hit = False
    for row in grid:
        key = f"{row['ticker']}|{row['fiscalYear']}"
        if key in state["doneKeys"]:
            continue
        if state["callsUsedToday"] + len(REPRT_CODES) > args.daily_budget:
            print(f"\ndaily budget reached ({state['callsUsedToday']}/{args.daily_budget}) - "
                  f"내일 다시 실행하면 이어서 계속한다")
            break
        for reprt_code, q_label in zip(REPRT_CODES, ["Q1", "Q2", "Q3"]):
            rows_, err = dart_call(reprt_code, row["corp"], row["fiscalYear"])
            state["callsUsedToday"] += 1
            n_new_calls += 1
            if err == QUOTA_EXCEEDED_STATUS:
                print(f"\nquotaExceeded(020) at {n_new_calls} calls this run - 중단, 내일 이어감")
                quota_hit = True
                break
            if err:
                n_fail += 1
                continue
            info = extract_net_income(rows_)
            if info is None or info["thstrm"] is None or info["frmtrm"] is None or not info["rceptNo"]:
                continue
            rec = {"ticker": row["ticker"], "corp": row["corp"], "fiscalYear": row["fiscalYear"],
                   "quarter": q_label, "availableFrom": info["rceptNo"][:8],
                   "thstrm": info["thstrm"], "frmtrm": info["frmtrm"]}
            out_f.write(json.dumps(rec, ensure_ascii=False) + "\n")
            n_new_records += 1
            time.sleep(args.sleep)
        if quota_hit:
            break
        state["doneKeys"].add(key)
        if n_new_calls % 300 == 0:
            out_f.flush()
            save_state(state)
            elapsed = time.time() - t0
            print(f"  progress: done={len(state['doneKeys'])}/{len(grid)} "
                  f"callsToday={state['callsUsedToday']} newRecords={n_new_records} "
                  f"fails={n_fail} ({elapsed:.0f}s)", end="\r")

    out_f.close()
    save_state(state)
    print(f"\nrun complete: newCalls={n_new_calls} newRecords={n_new_records} newFails={n_fail} "
          f"({time.time()-t0:.0f}s)")
    print(f"total done: {len(state['doneKeys'])}/{len(grid)}")
    if len(state["doneKeys"]) < len(grid):
        print("아직 안 끝남 - 다시 실행하면 이어서 계속한다")
    else:
        print("전체 완료")


if __name__ == "__main__":
    main()
