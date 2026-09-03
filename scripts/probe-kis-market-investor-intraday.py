#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""장중(잠정) 투자자별 수급을 KIS로 받을 수 있는지 정찰한다 - 읽기 전용, 저장 없음.

배경: docs/data/market_flows.json은 pykrx 일별 '확정치'라 장 마감 후에야 나온다
(평일 18:20 KST). 사용자가 "당일 실시간이나 지연으로라도" 기관·외국인·개인
수급을 보고 싶다고 해서, 이미 갖고 있는 KIS 키로 되는지부터 확인한다.

후보 두 개:
  A. foreign-institution-total (FHPTJ04400000) - 국내기관·외국인 매매종목 가집계.
     장중 갱신되는 '가집계'라 확정치와 다를 수 있다(KIS 문서 명시).
  B. inquire-investor-time-by-market (FHPTJ04030000) - 시장별 투자자매매동향 시간대별.

  python scripts/probe-kis-market-investor-intraday.py [--live]
"""
import argparse
import json
import os
import sys
import time
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parent.parent
ENV_PATH = Path(os.environ.get("KIS_ENV_PATH", ROOT / ".env"))
VPS = "https://openapivts.koreainvestment.com:29443"
PROD = "https://openapi.koreainvestment.com:9443"


def load_env():
    env = {}
    if ENV_PATH.exists():
        for line in ENV_PATH.read_text(encoding="utf-8").splitlines():
            k, _, v = line.partition("=")
            if k.strip() and not k.strip().startswith("#"):
                env[k.strip()] = v.strip()
    env.update({k: v for k, v in os.environ.items() if k.startswith("KIS_")})
    return env


def get_token(base, key, secret):
    # KIS는 토큰 발급을 분당 1회로 제한한다 - 다른 VTS 스크립트와 같은 캐시를 쓴다.
    cache = ROOT / (".token_cache_kis_vts.json" if "vts" in base else ".token_cache_kis.json")
    if cache.exists():
        try:
            c = json.loads(cache.read_text(encoding="utf-8"))
            if time.time() < c["exp"] - 600:
                return c["token"]
        except Exception:
            pass
    r = requests.post(base + "/oauth2/tokenP",
                      data=json.dumps({"grant_type": "client_credentials", "appkey": key, "appsecret": secret}),
                      headers={"content-type": "application/json"}, timeout=15)
    body = r.json()
    if "access_token" not in body:
        raise SystemExit(f"토큰 발급 실패: {body}")
    cache.write_text(json.dumps({"token": body["access_token"], "exp": time.time() + 3600 * 20}), encoding="utf-8")
    return body["access_token"]


def call(base, token, key, secret, path, tr_id, params):
    h = {"content-type": "application/json; charset=utf-8", "authorization": f"Bearer {token}",
         "appkey": key, "appsecret": secret, "tr_id": tr_id, "custtype": "P"}
    r = requests.get(base + path, headers=h, params=params, timeout=15)
    try:
        return r.status_code, r.json()
    except Exception:
        return r.status_code, {"_raw": r.text[:300]}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--live", action="store_true", help="실전 도메인·실전 앱키 사용(기본은 모의)")
    args = ap.parse_args()

    env = load_env()
    if args.live:
        base, key, secret = PROD, env.get("KIS_APP_KEY", ""), env.get("KIS_APP_SECRET", "")
    else:
        base, key, secret = VPS, env.get("KIS_VTS_APP_KEY", ""), env.get("KIS_VTS_APP_SECRET", "")
    if not key or not secret:
        raise SystemExit("앱키 없음 - .env 확인")
    token = get_token(base, key, secret)
    print(f"domain={base} token ok\n")

    probes = [
        ("A. 외국인·기관 매매종목 가집계(장중)",
         "/uapi/domestic-stock/v1/quotations/foreign-institution-total", "FHPTJ04400000",
         {"FID_COND_MRKT_DIV_CODE": "V", "FID_COND_SCR_DIV_CODE": "16449", "FID_INPUT_ISCD": "0000",
          "FID_DIV_CLS_CODE": "0", "FID_RANK_SORT_CLS_CODE": "0", "FID_ETC_CLS_CODE": "0"}),
        ("B. 시장별 투자자매매동향(시간대별)",
         "/uapi/domestic-stock/v1/quotations/inquire-investor-time-by-market", "FHPTJ04030000",
         {"FID_INPUT_ISCD": "0001", "FID_INPUT_ISCD_2": "0001", "FID_COND_MRKT_DIV_CODE": "U"}),
    ]
    for label, path, tr, params in probes:
        code, body = call(base, token, key, secret, path, tr, params)
        rt, msg = body.get("rt_cd"), body.get("msg1", "")
        rows = body.get("output") or body.get("output1") or body.get("output2") or []
        print(f"{label}\n  tr_id={tr} http={code} rt_cd={rt} msg={msg.strip()}")
        if isinstance(rows, list) and rows:
            print(f"  rows={len(rows)} 첫행 키={list(rows[0])[:14]}")
            print(f"  첫행={json.dumps(rows[0], ensure_ascii=False)[:400]}")
        elif isinstance(rows, dict) and rows:
            print(f"  단일행 키={list(rows)[:14]}")
            print(f"  값={json.dumps(rows, ensure_ascii=False)[:400]}")
        else:
            print(f"  본문={json.dumps(body, ensure_ascii=False)[:300]}")
        print()
        time.sleep(0.5)


if __name__ == "__main__":
    main()
