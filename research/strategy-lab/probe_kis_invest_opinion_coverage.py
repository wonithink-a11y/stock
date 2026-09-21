#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""KIS invest-opinion(FHKST663300C0) 커버리지 프로브 — 읽기 전용 조회, 약 140콜.

질문: 우리 종목(PBR 슬리브 보유·유동 유니버스)에 애널리스트 의견·목표가 이벤트가 얼마나 있는가.
수익률·성과는 계산하지 않는다. 결과 원행은 reports/(gitignore)에만 남긴다.

**판정 기준(결과 전 고정, docs/control/애널리스트-추정치-소스조사-2026-09-21.md §3):**
  '커버됨' = 최근 12개월 창에서 의견 행 ≥ 1건 ∧ 서로 다른 증권사 ≥ 2곳(컨센서스라 부를 최소)
  PBR 슬리브 보유 종목의 '커버됨' 비율 < 50% → 이 경로는 접는다(옵션 D). ≥ 50% → 목표가 대리 지표 설계로.
검증: 응답 일자가 요청 창 밖이면 그 호출은 '창 위반'으로 기록(성공 코드는 내 질문에 답했다는 뜻이 아니다 — 교훈 81).

  python probe_kis_invest_opinion_coverage.py --validate   # 삼성전자 3콜로 규격·창 검증만
  python probe_kis_invest_opinion_coverage.py              # 전체 프로브
"""
import argparse
import json
import os
import random
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pandas as pd
import requests

for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(errors="replace")
    except Exception:
        pass

LAB = Path(__file__).resolve().parent
REPO = LAB.parent.parent
TOKEN_CACHE = REPO / ".token_cache_kis.json"
OUT_DIR = LAB / "reports" / "2026-09-21-kis-opinion-coverage-probe"
KST = timezone(timedelta(hours=9))
BASE = "https://openapi.koreainvestment.com:9443"
PATH = "/uapi/domestic-stock/v1/quotations/invest-opinion"
TR = "FHKST663300C0"
SEED = 20260921
RECENT = ("20250922", "20260921")
Y2020 = ("20200101", "20201231")
N_LIQUID, N_2020 = 40, 30
SLEEP = 0.35
FIN = "금융|보험|은행|저축|신탁|집합투자|증권|상품 중개"


def load_env():
    env = {}
    p = REPO / ".env"
    if p.exists():
        for line in p.read_text(encoding="utf-8").splitlines():
            k, _, v = line.partition("=")
            if k.strip():
                env[k.strip()] = v.strip()
    for k in ("KIS_APP_KEY", "KIS_APP_SECRET"):
        if os.environ.get(k):
            env[k] = os.environ[k]
    return env


ENV = load_env()
KEY, SECRET = ENV.get("KIS_APP_KEY", ""), ENV.get("KIS_APP_SECRET", "")


def get_token():
    if TOKEN_CACHE.exists():
        try:
            c = json.loads(TOKEN_CACHE.read_text(encoding="utf-8"))
            exp = datetime.fromisoformat(c["expiresAt"])
            if exp.tzinfo is None:
                exp = exp.replace(tzinfo=KST)
            if exp - timedelta(minutes=10) > datetime.now(KST) and c.get("appKeyTail") == KEY[-4:]:
                return c["accessToken"]
        except Exception:
            pass
    r = requests.post(BASE + "/oauth2/tokenP", data=json.dumps({"grant_type": "client_credentials", "appkey": KEY, "appsecret": SECRET}),
                      headers={"content-type": "application/json"}, timeout=20)
    body = r.json()
    if r.status_code != 200 or "access_token" not in body:
        raise SystemExit("토큰 발급 실패")
    TOKEN_CACHE.write_text(json.dumps({"accessToken": body["access_token"], "expiresAt": body.get("access_token_token_expired", ""),
                                       "issuedAt": datetime.now(KST).strftime("%Y-%m-%d %H:%M:%S KST"), "appKeyTail": KEY[-4:]},
                                      ensure_ascii=False, indent=2), encoding="utf-8")
    return body["access_token"]


def fetch(tok, ticker, d1, d2, tries=4):
    """(rows, err). 날짜 파라미터는 문서 예시대로 '00'+YYYYMMDD 10자리."""
    headers = {"content-type": "application/json; charset=utf-8", "authorization": "Bearer " + tok, "appkey": KEY,
               "appsecret": SECRET, "tr_id": TR, "custtype": "P"}
    params = {"FID_COND_MRKT_DIV_CODE": "J", "FID_COND_SCR_DIV_CODE": "16633", "FID_INPUT_ISCD": ticker,
              "FID_INPUT_DATE_1": "00" + d1, "FID_INPUT_DATE_2": "00" + d2}
    for k in range(tries):
        time.sleep(SLEEP * (2 ** k) if k else SLEEP)
        try:
            r = requests.get(BASE + PATH, headers=headers, params=params, timeout=20)
            b = r.json()
        except Exception as e:
            err = f"요청 예외 {type(e).__name__}"
            continue
        if b.get("rt_cd") == "0":
            return b.get("output") or [], None
        err = f"{b.get('msg_cd')} {b.get('msg1')}"
        if b.get("msg_cd") != "EGW00201":     # 초당 거래건수 초과만 재시도
            break
    return [], err


def summarize(rows, d1, d2):
    dates = [str(r.get("stck_bsop_date", "")) for r in rows]
    goals = [int(float(r["hts_goal_prc"])) for r in rows if str(r.get("hts_goal_prc", "")).strip() not in ("", "0")]
    return {"nRows": len(rows), "nBrokers": len({r.get("mbcr_name") for r in rows if r.get("mbcr_name")}),
            "nWithTarget": len(goals), "saturated": len(rows) >= 100,
            "minDate": min(dates) if dates else None, "maxDate": max(dates) if dates else None,
            "windowViolations": sum(1 for x in dates if not (d1 <= x <= d2))}


def sleeve_tickers():
    sel = json.load(open(LAB / "strategies" / "pbr_value_v1_combined" / "selection.json", encoding="utf-8"))["selection"]
    recent = sorted({e["date"] for es in sel.values() for e in es})[-24:]
    return sorted({t for t, es in sel.items() if any(e["date"] in recent for e in es)})


def liquid_tickers(exclude):
    p = pd.read_parquet(LAB / "data" / "factor-panel" / "kr-monthly-v1.parquet", columns=["ticker", "date", "sector", "liquid"])
    last = p[p["date"] == p["date"].max()]
    last = last[last["liquid"] & ~last["sector"].fillna("").str.contains(FIN)]
    pool = sorted(set(last["ticker"]) - set(exclude))
    return pool, random.Random(SEED).sample(pool, N_LIQUID)


def validate():
    tok = get_token()
    for name, t, w in [("삼성전자 2015", "005930", ("20150101", "20151231")), ("삼성전자 2010(하한 확인)", "005930", ("20100101", "20101231")),
                       ("삼성전자 최근12개월", "005930", RECENT)]:
        rows, err = fetch(tok, t, *w)
        s = summarize(rows, *w) if rows else {}
        print(f"{name}: err={err} {s}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--validate", action="store_true")
    if ap.parse_args().validate:
        return validate()
    tok = get_token()
    sleeve = sleeve_tickers()
    pool, liquid = liquid_tickers(sleeve)
    rng = random.Random(SEED + 1)
    sub2020 = sorted(rng.sample(sleeve, N_2020))
    plan = [("sleeve_recent", t, RECENT) for t in sleeve] + [("liquid_recent", t, RECENT) for t in liquid] + \
           [("sleeve_2020", t, Y2020) for t in sub2020]
    print(f"슬리브 {len(sleeve)} · 유동 표본 {len(liquid)}(모집단 {len(pool)}) · 2020 표본 {len(sub2020)} → 총 {len(plan)}콜", flush=True)
    results, errs = [], 0
    for i, (grp, t, w) in enumerate(plan, 1):
        rows, err = fetch(tok, t, *w)
        s = summarize(rows, *w)
        s.update({"group": grp, "ticker": t, "window": w, "err": err,
                  "rows": [{k: r.get(k) for k in ("stck_bsop_date", "mbcr_name", "hts_goal_prc", "invt_opnn")} for r in rows]})
        errs += bool(err)
        results.append(s)
        if i % 20 == 0:
            print(f"  {i}/{len(plan)} (오류 {errs})", flush=True)
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    json.dump({"generatedAt": datetime.now(KST).isoformat(), "seed": SEED, "calls": len(plan), "results": results},
              open(OUT_DIR / "probe.json", "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print(f"저장: {OUT_DIR / 'probe.json'}")


if __name__ == "__main__":
    main()
