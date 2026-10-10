#!/usr/bin/env python3
"""DART 기업개황(company.json)의 업종 코드(induty_code) 보충 수집 — 업종 단위 실적 모멘텀 연구의 생존편향 보완.

A3 백필(data/backfill/fundamentals/a3)에 sicCode 가 이미 있는 3,003종목은 건너뛰고, 그 밖에서
가격이 있는 상장폐지 종목(A2b) + 현재 상장(A1a) 중 sicCode 없는 종목만 받는다(2026-10-10 실측 257종목).

    python research/strategy-lab/collect_company_induty.py --dry-run   # 대상 수만 출력(네트워크 없음)
    python research/strategy-lab/collect_company_induty.py             # 수집(이어받기)

출력: data/company-induty/induty.jsonl (gitignore). 한 줄 = {ticker, corp, induty_code|null, status}.
"""
from __future__ import annotations

import argparse
import gzip
import glob
import json
import sys
import time
from pathlib import Path

import requests

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent.parent
sys.path.insert(0, str(HERE))
from collect_quarterly_multi import key, SECRET  # noqa: E402

BF = ROOT / "data" / "backfill"
OUT = HERE / "data" / "company-induty" / "induty.jsonl"
URL = "https://opendart.fss.or.kr/api/company.json"


def targets():
    sic = set()
    for f in glob.glob(str(BF / "fundamentals" / "a3" / "*.jsonl.gz")):
        for line in gzip.open(f, "rt", encoding="utf-8"):
            d = json.loads(line)
            if d.get("sicCode"):
                sic.add(d["ticker"])
    corp = {}
    for p in ("a1a/current.jsonl", "a1b/delisted.jsonl"):
        for line in open(BF / "universe" / p, encoding="utf-8"):
            d = json.loads(line)
            corp.setdefault(d["ticker"], d.get("corp"))
    a2b = set()
    for f in glob.glob(str(BF / "price" / "a2b" / "*.jsonl.gz")):
        for line in gzip.open(f, "rt", encoding="utf-8"):
            a2b.add(json.loads(line)["ticker"])
    cur = {json.loads(l)["ticker"] for l in open(BF / "universe" / "a1a" / "current.jsonl", encoding="utf-8")}
    want = sorted((a2b | cur) - sic)
    return [(t, corp.get(t)) for t in want]


def fetch(k, corp):
    for i in range(3):
        try:
            r = requests.get(URL, params={"crtfc_key": k, "corp_code": corp}, timeout=20)
            j = r.json()
            st = str(j.get("status", ""))
            if st == "000":
                return (str(j.get("induty_code", "")).strip() or None), st
            if st in ("013", "020"):           # 데이터 없음 · 한도 초과
                return None, st
        except Exception as e:  # noqa: BLE001
            st = "transport:" + SECRET.sub(r"\1<redacted>", str(e))[:120]
        time.sleep(2 ** i)
    return None, st


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args()
    T = targets()
    done = set()
    if OUT.exists():
        done = {json.loads(l)["ticker"] for l in open(OUT, encoding="utf-8")}
    todo = [(t, c) for t, c in T if t not in done]
    print(f"대상 {len(T)} · 완료 {len(done)} · 남음 {len(todo)} · corp 없음 {sum(1 for _, c in todo if not c)}")
    if a.dry_run:
        return
    k = key()
    if not k:
        sys.exit("DART_API_KEY 없음")
    OUT.parent.mkdir(parents=True, exist_ok=True)
    with open(OUT, "a", encoding="utf-8") as f:
        for n, (t, c) in enumerate(todo, 1):
            code, st = fetch(k, c) if c else (None, "no-corp")
            if st == "020":
                sys.exit("DART 한도 초과 — 내일 이어받기")
            f.write(json.dumps({"ticker": t, "corp": c, "induty_code": code, "status": st}, ensure_ascii=False) + "\n")
            f.flush()
            if n % 50 == 0:
                print(n, "/", len(todo))
            time.sleep(0.15)
    print("완료")


if __name__ == "__main__":
    main()
