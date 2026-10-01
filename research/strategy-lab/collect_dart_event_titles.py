#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""공시·뉴스 점수화 A/B — DART 공시 제목 수집 (사전등록 findings/disclosure-news-score-ab-preregistration-2026-10.md §1).

A5 valuation-panel 의 1,724종목 × 공시 두 종류(I 거래소공시 · B 주요사항보고) 의 제목·접수일만 받는다. 수익률은 계산하지 않는다.
종목마다 캐시 파일 하나(data/dart_event_titles/{corp}.json = {"I": [...], "B": [...]}) — 있으면 건너뛰므로 중단 후 이어받기 가능.
DART 한도(status 020)가 오면 그 자리에서 멈춘다(캐시는 보존).

  python collect_dart_event_titles.py --probe 3     # 3종목만 받아 호출 수를 추정하고 끝낸다
  python collect_dart_event_titles.py               # 전량
  python collect_dart_event_titles.py selftest
"""
import argparse
import json
import os
import sys
import time
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
CACHE = os.path.join(HERE, "data", "dart_event_titles")
PANEL = os.path.join(HERE, "reports", "2026-08-21-a5-valuation-precheck", "valuation-panel.jsonl")
CORPS = os.path.join(ROOT, "data", "backfill", "dart", "corpcode.jsonl")
BGN, END = "20151201", "20260930"
TYPES = ("I", "B")


class LimitReached(Exception):
    pass


def load_env():
    env = {}
    p = os.path.join(ROOT, ".env")
    if os.path.exists(p):
        for line in open(p, encoding="utf-8").read().splitlines():
            k, _, v = line.partition("=")
            env[k.strip()] = v.strip()
    if os.environ.get("DART_API_KEY"):
        env["DART_API_KEY"] = os.environ["DART_API_KEY"]
    return env


def dart_list(key, corp, ty, page):
    url = (f"https://opendart.fss.or.kr/api/list.json?crtfc_key={key}&corp_code={corp}&bgn_de={BGN}&end_de={END}"
           f"&pblntf_ty={ty}&page_no={page}&page_count=100")
    for attempt in range(3):
        try:
            d = json.load(urllib.request.urlopen(url, timeout=60))
            break
        except Exception:
            if attempt == 2:
                raise
            time.sleep(5)
    st = d.get("status")
    if st == "013":                        # 조회된 데이터 없음
        return [], 0
    if st == "020":
        raise LimitReached(d.get("message"))
    if st != "000":
        raise RuntimeError(f"DART list {st} {d.get('message')}")
    return d.get("list", []), int(d.get("total_page") or 1)


def fetch_corp(key, corp, calls, lister=dart_list):
    """한 회사의 I·B 공시 제목 전부. 캐시가 있으면 그대로 돌려준다. calls 는 호출 수 누적용 리스트."""
    path = os.path.join(CACHE, f"{corp}.json")
    if os.path.exists(path):
        return json.load(open(path, encoding="utf-8"))
    out = {}
    for ty in TYPES:
        rows, page = [], 1
        while True:
            lst, total = lister(key, corp, ty, page)
            calls[0] += 1
            rows += [{"d": r["rcept_dt"], "nm": r["report_nm"], "no": r["rcept_no"]} for r in lst]
            if page >= total:
                break
            page += 1
            time.sleep(0.05)
        out[ty] = rows
    os.makedirs(CACHE, exist_ok=True)
    tmp = path + ".tmp"
    json.dump(out, open(tmp, "w", encoding="utf-8"), ensure_ascii=False)
    os.replace(tmp, path)                  # 중단돼도 반쪽 캐시가 남지 않게
    return out


def selftest():
    import tempfile
    global CACHE
    CACHE = tempfile.mkdtemp()
    pages = {("I", 1): ([{"rcept_dt": "20200101", "report_nm": "a", "rcept_no": "1"}], 2),
             ("I", 2): ([{"rcept_dt": "20200102", "report_nm": "b", "rcept_no": "2"}], 2),
             ("B", 1): ([], 0)}
    n = [0]

    def lister(key, corp, ty, page):
        n[0] += 1
        return pages[(ty, page)]
    calls = [0]
    r = fetch_corp("k", "00000001", calls, lister)
    assert [x["no"] for x in r["I"]] == ["1", "2"] and r["B"] == [] and calls[0] == 3
    r2 = fetch_corp("k", "00000001", calls, lister)           # 캐시 재사용 — 호출 없음
    assert r2 == r and calls[0] == 3 and n[0] == 3
    print("selftest ok")
    return 0


def main():
    if len(sys.argv) > 1 and sys.argv[1] == "selftest":
        return selftest()
    ap = argparse.ArgumentParser()
    ap.add_argument("--probe", type=int, default=0)
    a = ap.parse_args()
    tickers = sorted({json.loads(l)["ticker"] for l in open(PANEL, encoding="utf-8")})
    corp = {}
    for line in open(CORPS, encoding="utf-8"):
        j = json.loads(line)
        corp[j.get("ticker")] = j.get("corp")
    key = load_env().get("DART_API_KEY")
    if not key:
        sys.exit("DART_API_KEY 없음(.env)")
    todo = [t for t in tickers if corp.get(t)]
    calls = [0]
    if a.probe:
        for t in todo[: a.probe]:
            n0 = calls[0]
            r = fetch_corp(key, corp[t], calls)
            print(f"{t} I {len(r['I'])}건 · B {len(r['B'])}건 · 호출 {calls[0] - n0}회")
        per = calls[0] / a.probe
        print(f"평균 {per:.1f}회/종목 → {len(todo)}종목 추정 {per * len(todo):.0f}회 (DART 일일 한도 20,000)")
        return 0
    try:
        for i, t in enumerate(todo, 1):
            fetch_corp(key, corp[t], calls)
            if i % 50 == 0:
                print(f"  {i}/{len(todo)} 호출 {calls[0]}", flush=True)
    except LimitReached as e:
        print(f"DART 한도 도달 — 여기서 멈춤(캐시 보존, 내일 이어받기): {e}")
        return 3
    print(f"수집 완료 · 이번 호출 {calls[0]}회 · 종목 {len(todo)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
