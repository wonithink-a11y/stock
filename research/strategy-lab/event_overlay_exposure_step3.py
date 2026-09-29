#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""뉴스·공시 오버레이 3단계 — 계약 해지·횡령배임 공시의 '노출 점검' (건수만, 수익률 없음).

findings/event-overlay-exposure-step0-2-2026-09.md 의 0단계 고정 기준을 그대로 쓴다:
  대상 = pbr_value_v1_combined selection.json 의 3,402 슬롯(150종목) · 걸림 = 공시 접수일이 슬롯 날짜 0~30일 전
  · 충분 = 유형별 걸린 슬롯 >= 100 그리고 서로 다른 종목 >= 30 · 미달이면 그 유형은 사전등록 없이 종결.
DART 목록 API(list.json)는 제목·접수일만 준다 - 금액·매출비중은 없다. 분류는 보고서명 정규식만 쓴다.

  python event_overlay_exposure_step3.py --probe 3     # 3개 종목만 받아 호출 수를 추정하고 끝낸다
  python event_overlay_exposure_step3.py               # 150종목 전부(캐시가 있으면 재사용)
"""
import argparse
import json
import os
import re
import sys
import time
import urllib.request
from collections import defaultdict
from datetime import datetime, timedelta

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
CACHE = os.path.join(HERE, "data", "dart_event_titles")
SEL = os.path.join(HERE, "strategies", "pbr_value_v1_combined", "selection.json")
BGN, END = "20151201", "20260831"            # 첫 슬롯(2016-02) 30일 전 ~ 마지막 슬롯 이후
WINDOW_DAYS = 30
MIN_SLOTS, MIN_TICKERS = 100, 30

# 분류는 공백을 뺀 보고서명에 건다. 정정 공시는 원공시와 중복이라 뺀다.
RULES = [
    ("계약해지", r"(단일판매|공급계약).*해지"),          # 자기주식취득신탁계약해지 는 고객 계약이 아니라 뺀다
    ("횡령배임", r"횡령|배임"),
    ("거래정지", r"매매거래정지"),          # 2단계 거래량 0 대용치의 교차 확인(기록 전용)
    ("관리종목", r"관리종목"),
]


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


def dart_list(key, corp, page):
    url = (f"https://opendart.fss.or.kr/api/list.json?crtfc_key={key}&corp_code={corp}&bgn_de={BGN}&end_de={END}"
           f"&pblntf_ty=I&page_no={page}&page_count=100")
    for attempt in range(3):
        try:
            d = json.load(urllib.request.urlopen(url, timeout=60))
            break
        except Exception:
            if attempt == 2:
                raise
            time.sleep(5)
    st = d.get("status")
    if st == "013":
        return [], 0
    if st != "000":
        raise RuntimeError(f"DART list {st} {d.get('message')}")
    return d.get("list", []), int(d.get("total_page") or 1)


def fetch_corp(key, corp, calls):
    """한 회사의 거래소공시(I) 제목 전부. calls 는 호출 수 누적용 리스트."""
    path = os.path.join(CACHE, f"{corp}.json")
    if os.path.exists(path):
        return json.load(open(path, encoding="utf-8"))
    rows, page = [], 1
    while True:
        lst, total = dart_list(key, corp, page)
        calls[0] += 1
        rows += [{"d": r["rcept_dt"], "nm": r["report_nm"], "no": r["rcept_no"]} for r in lst]
        if page >= total:
            break
        page += 1
        time.sleep(0.05)
    os.makedirs(CACHE, exist_ok=True)
    json.dump(rows, open(path, "w", encoding="utf-8"), ensure_ascii=False)
    return rows


def classify(nm):
    n = re.sub(r"\s+", "", nm or "")
    if re.match(r"\[(기재|첨부)정정\]|\[정정\]", n):
        return None
    for cat, pat in RULES:
        if re.search(pat, n):
            return cat
    return None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--probe", type=int, default=0)
    a = ap.parse_args()
    sel = json.load(open(SEL, encoding="utf-8"))["selection"]
    tickers = sorted(sel)
    corp = {}
    for line in open(os.path.join(ROOT, "data", "backfill", "dart", "corpcode.jsonl"), encoding="utf-8"):
        j = json.loads(line)
        corp[j.get("ticker")] = j.get("corp")
    nocorp = [t for t in tickers if not corp.get(t)]
    key = load_env().get("DART_API_KEY")
    if not key:
        sys.exit("DART_API_KEY 없음(.env)")
    calls = [0]
    if a.probe:
        tk = [t for t in tickers if corp.get(t)][: a.probe]
        for t in tk:
            n0 = calls[0]
            rows = fetch_corp(key, corp[t], calls)
            print(f"{t} 거래소공시 {len(rows)}건 · 호출 {calls[0] - n0}회")
        per = calls[0] / len(tk)
        print(f"평균 {per:.1f}회/종목 → 150종목 추정 {per * 150:.0f}회 (DART 일일 한도 20,000)")
        return
    by_t = {}
    for i, t in enumerate(tickers, 1):
        if not corp.get(t):
            continue
        by_t[t] = fetch_corp(key, corp[t], calls)
        if i % 30 == 0:
            print(f"  {i}/{len(tickers)} 호출 {calls[0]}", flush=True)
    print(f"수집 완료 · 이번 호출 {calls[0]}회 · corp_code 없음 {len(nocorp)}: {nocorp}")

    # 유형별 공시(30일 중복 제거) 목록
    ev = defaultdict(lambda: defaultdict(list))         # cat -> ticker -> [date]
    for t, rows in by_t.items():
        for r in sorted(rows, key=lambda x: x["d"]):
            c = classify(r["nm"])
            if c:
                ev[c][t].append(r["d"])
    out = {}
    for cat, _ in RULES:
        n_ev = sum(len(v) for v in ev[cat].values())
        tick = len(ev[cat])
        hit_slots, hit_tick, tot = 0, set(), 0
        for t, slots in sel.items():
            ds = ev[cat].get(t, [])
            for s in slots:
                tot += 1
                d0 = datetime.strptime(s["date"], "%Y-%m-%d")
                lo = (d0 - timedelta(days=WINDOW_DAYS)).strftime("%Y%m%d")
                hi = d0.strftime("%Y%m%d")
                # 공시일 다음 거래일부터 반영 - 슬롯 당일 접수분은 뺀다(lo <= d < hi)
                if any(lo <= d.replace("-", "") < hi for d in ds):
                    hit_slots += 1
                    hit_tick.add(t)
        ok = hit_slots >= MIN_SLOTS and len(hit_tick) >= MIN_TICKERS
        out[cat] = dict(events=n_ev, tickers_with_events=tick, slots=tot, hit_slots=hit_slots,
                        hit_pct=round(hit_slots / tot * 100, 2), hit_tickers=len(hit_tick), enough=ok)
        print(f"{cat}: 공시 {n_ev}건({tick}종목) · 걸린 슬롯 {hit_slots}/{tot} = {hit_slots / tot * 100:.2f}% · "
              f"종목 {len(hit_tick)} → {'충분' if ok else '미달(종결)'}")
    json.dump(out, open(os.path.join(HERE, "reports", "event_overlay_exposure_step3.json"), "w", encoding="utf-8"),
              ensure_ascii=False, indent=1)


if __name__ == "__main__":
    main()
