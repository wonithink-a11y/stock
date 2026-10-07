#!/usr/bin/env python3
"""분기(1분기·반기·3분기·사업보고서) 매출·영업이익·순이익 수집 — DART fnlttMultiAcnt(다중회사 주요계정, 호출당 최대 100사).

collect_half_year_multi.py 의 일반화판: 보고서 종류 4개 × 연도 11개 ≈ 1,364콜. 3개월(thstrm_amount)·전년 동기·누적(add)·기간(thstrm_dt)을 모두 저장한다.

연구 전용(data/backfill 에 쓰지 않는다). 종목-연도당 1콜이던 기존 분기 패널(≈7.7만콜)과 달리 100사를 한 번에 받아
3,003종목 × 11개 연도 ≈ 340콜이다. 반기 보고서 한 건에 당기 반기 누적(thstrm_add_amount)과 전년 같은 기간 누적
(frmtrm_add_amount)이 함께 들어 있어 YoY 를 한 보고서 안에서 계산한다(전년 보고서·fsDiv 불일치 문제 없음).

    python research/strategy-lab/collect_quarterly_multi.py --probe          # 1콜 점검(저장 안 함)
    python research/strategy-lab/collect_quarterly_multi.py                  # 수집(이어받기)

DART_API_KEY 는 .env 또는 환경변수. 출력: data/quarterly-multi/quarterly-multi-panel.jsonl(gitignore) · _state.json
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
from pathlib import Path

import requests

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent.parent
CORP_SRC = HERE / "data" / "fundamentals-ext" / "annual-ext-panel.jsonl"
OUT_DIR = HERE / "data" / "quarterly-multi"
OUT = OUT_DIR / "quarterly-multi-panel.jsonl"
STATE = OUT_DIR / "_state.json"
CODES = ("11013", "11012", "11014", "11011")   # 1분기·반기·3분기·사업
URL = "https://opendart.fss.or.kr/api/fnlttMultiAcnt.json"
YEARS = list(range(2015, 2026))      # bsns_year → 공시 2015~2025 (A2a 가격은 2016~, 2015 는 참고)
BATCH = 100
WANT = {"매출액": "revenue", "영업이익": "op_income", "당기순이익(손실)": "net_income"}
SECRET = re.compile(r"(crtfc_key=)[^&\s\"')]+")


def key():
    k = os.environ.get("DART_API_KEY", "")
    if not k and (ROOT / ".env").exists():
        for line in open(ROOT / ".env", encoding="utf-8"):
            m = re.match(r"\s*DART_API_KEY\s*=\s*(.+?)\s*$", line)
            if m:
                k = m.group(1).strip().strip("\"'")
    return k


def num(x):
    try:
        return float(str(x).replace(",", ""))
    except (TypeError, ValueError):
        return None


def corp_list():
    tick, seen = {}, {}
    for line in open(CORP_SRC, encoding="utf-8"):
        r = json.loads(line)
        seen.setdefault(r["corp"], r["ticker"])
    return seen        # corp → ticker


def parse(rows, corp2tk):
    """응답 list → [{ticker, corp, year, fsDiv, rceptNo, availableFrom, revenue:{cur,prev}, ...}] (corp·fsDiv 별 1건)."""
    by = {}
    for r in rows:
        if r.get("sj_div") != "IS" and r.get("sj_nm") != "손익계산서":
            continue
        name = WANT.get(r.get("account_nm"))
        if not name:
            continue
        k = (r["corp_code"], r["bsns_year"], r["reprt_code"], r["fs_div"])
        rec = by.setdefault(k, {"ticker": corp2tk.get(r["corp_code"]), "corp": r["corp_code"], "year": int(r["bsns_year"]),
                                "reprt": r["reprt_code"], "fsDiv": r["fs_div"], "rceptNo": r.get("rcept_no"),
                                "availableFrom": (r.get("rcept_no") or "")[:8], "dt": r.get("thstrm_dt")})
        if name not in rec:     # 같은 계정이 둘이면(당기순이익 중복 행) 첫 행
            rec[name] = {"cur": num(r.get("thstrm_amount")), "prev": num(r.get("frmtrm_amount")),
                         "cur_add": num(r.get("thstrm_add_amount")), "prev_add": num(r.get("frmtrm_add_amount"))}
    return list(by.values())


def call(k, corps, year, code):
    p = {"crtfc_key": k, "corp_code": ",".join(corps), "bsns_year": str(year), "reprt_code": code}
    try:
        r = requests.get(URL, params=p, timeout=(10, 90))
        body = r.json()
    except Exception as e:
        return None, "transport:" + SECRET.sub(r"\1<redacted>", str(e))
    st = body.get("status")
    if st == "013":              # 조회된 데이터 없음
        return [], None
    if st != "000":
        return None, st
    return body.get("list", []), None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--probe", action="store_true")
    ap.add_argument("--code", default=None, help="보고서 코드 하나만(병렬 실행용) — 출력·상태 파일이 코드별로 갈린다")
    ap.add_argument("--sleep", type=float, default=0.3)
    a = ap.parse_args()
    k = key()
    if not k:
        print("DART_API_KEY 없음")
        return 1
    corp2tk = corp_list()
    corps = sorted(corp2tk)
    batches = [corps[i:i + BATCH] for i in range(0, len(corps), BATCH)]
    if a.probe:
        rows, err = call(k, batches[0], 2020, "11013")
        print("status err:", err, "| rows:", len(rows or []), "| parsed:", len(parse(rows or [], corp2tk)))
        return 0
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    codes = (a.code,) if a.code else CODES
    out_path = OUT_DIR / f"quarterly-multi-panel-{a.code}.jsonl" if a.code else OUT
    state_path = OUT_DIR / f"_state-{a.code}.json" if a.code else STATE
    done = set(json.load(open(state_path, encoding="utf-8"))["done"]) if state_path.exists() else set()
    calls = 0
    for y in YEARS:
      for code in codes:
        for bi, b in enumerate(batches):
            tag = f"{y}:{code}:{bi}"
            if tag in done:
                continue
            rows, err = call(k, b, y, code)
            calls += 1
            if err:
                print("중단:", tag, err)
                json.dump({"done": sorted(done)}, open(state_path, "w", encoding="utf-8"))
                return 2 if err == "020" else 1
            with open(out_path, "a", encoding="utf-8") as f:
                for rec in parse(rows, corp2tk):
                    f.write(json.dumps(rec, ensure_ascii=False) + "\n")
            done.add(tag)
            json.dump({"done": sorted(done)}, open(state_path, "w", encoding="utf-8"))
            time.sleep(a.sleep)
        print("연도 완료", y, "누적 콜", calls)
    print("완료. 호출", calls)
    return 0


if __name__ == "__main__":
    sys.exit(main())
