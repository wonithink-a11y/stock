#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""build-stock-context.py — 종목 맥락 스냅샷: 52주 고저 + 증권사 목표가(국내) → docs/data/stock-context.json

화면(메인 표 펼침·해독 탭) 맥락 표시 전용. **점수·추천·매매에 쓰지 않는다**(절대 규칙 1 — 추정치는 맥락용).

  52주   docs/data/prices.json(daily-analysis 가 방금 쓴 것)의 최근 250봉 고가 최대·저가 최소. 새 수집 없음.
  목표가 KIS invest-opinion(FHKST663300C0, 읽기 전용) — latest.json 의 KR 종목만, 최근 180일 창.
         증권사별 **가장 최근** 목표가(0·빈값 제외)의 중앙값. 연구 신호로는 09-21 에 접었다
         (docs/control/KIS-목표가-커버리지-프로브-2026-09-21.md — 소형 가치주 91% 결측). 여기선 보여 주기만 한다.
         목표가 없는 종목은 0 이 아니라 status 'none'. 조회 실패는 'error'(교훈 57).
         KIS 키·토큰이 없으면 목표가는 직전 파일 값을 그 asOf 그대로 이어 쓴다(새 값인 척 안 한다).

  python scripts/build-stock-context.py              # 52주 + 목표가
  python scripts/build-stock-context.py --no-kis     # 52주만(목표가는 직전 값 유지)
  python scripts/build-stock-context.py --selftest   # 네트워크 없이 요약 로직 확인
"""
import argparse
import json
import os
import statistics
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
DATA = REPO / "docs" / "data"
OUT = DATA / "stock-context.json"
KST = timezone(timedelta(hours=9))
BASE = "https://openapi.koreainvestment.com:9443"
PATH = "/uapi/domestic-stock/v1/quotations/invest-opinion"
TR = "FHKST663300C0"
WINDOW_DAYS = 180
SLEEP = 0.35
MAX_ERROR_SHARE = 0.2     # 이보다 많이 실패하면 이번 목표가는 버리고 직전 값 유지


def summarize_targets(rows):
    """증권사별 가장 최근 목표가 → 중앙값. 목표가 있는 증권사가 없으면 None."""
    latest = {}
    for r in rows:
        b, d = (r.get("mbcr_name") or "").strip(), str(r.get("stck_bsop_date") or "")
        try:
            g = int(float(str(r.get("hts_goal_prc") or "0").strip() or 0))
        except ValueError:
            g = 0
        if not b or g <= 0:
            continue
        if b not in latest or d > latest[b][0]:
            latest[b] = (d, g)
    if not latest:
        return None
    goals = [g for _, g in latest.values()]
    return {"median": int(statistics.median(goals)), "min": min(goals), "max": max(goals),
            "brokers": len(goals), "lastDate": max(d for d, _ in latest.values())}


def week52(rec):
    h, l, d = rec.get("h") or [], rec.get("l") or [], rec.get("d") or []
    h, l = [x for x in h[-250:] if x], [x for x in l[-250:] if x]
    if len(h) < 120 or not l:          # 반년도 안 되는 이력은 '52주'라 부르지 않는다
        return None
    return {"high": max(h), "low": min(l), "bars": len(h), "asOf": d[-1] if d else None}


def load_env_file():
    env, p = {}, REPO / ".env"
    if p.exists():
        for line in p.read_text(encoding="utf-8").splitlines():
            k, _, v = line.partition("=")
            if k.strip():
                env[k.strip()] = v.strip().strip('"').strip("'")
    return env


def get_token(key, sec):
    # scripts/build-etf-etn-daily.py 와 같은 캐시 파일을 공유(불필요한 재발급 방지)
    import requests
    p = Path(os.environ.get("KIS_TOKEN_CACHE") or (REPO / ".token_cache_kis.json")).expanduser()
    try:
        c = json.loads(p.read_text(encoding="utf-8"))
        exp = datetime.fromisoformat(c["expiresAt"])
        if exp.tzinfo is None:
            exp = exp.replace(tzinfo=KST)
        if exp - timedelta(minutes=10) > datetime.now(KST) and c.get("appKeyTail") == key[-4:]:
            return c["accessToken"]
    except Exception:
        pass
    r = requests.post(BASE + "/oauth2/tokenP", data=json.dumps({"grant_type": "client_credentials", "appkey": key, "appsecret": sec}),
                      headers={"content-type": "application/json"}, timeout=20)
    b = r.json()
    if r.status_code != 200 or "access_token" not in b:
        return None
    p.write_text(json.dumps({"accessToken": b["access_token"], "expiresAt": b.get("access_token_token_expired", ""),
                             "appKeyTail": key[-4:]}, ensure_ascii=False), encoding="utf-8")
    try:
        os.chmod(p, 0o600)
    except Exception:
        pass
    return b["access_token"]


def fetch_opinions(tok, key, sec, ticker, d1, d2, tries=4):
    """(rows, err). 응답 일자가 창 밖인 행은 버린다(교훈 81)."""
    import requests
    headers = {"content-type": "application/json; charset=utf-8", "authorization": "Bearer " + tok, "appkey": key,
               "appsecret": sec, "tr_id": TR, "custtype": "P"}
    params = {"FID_COND_MRKT_DIV_CODE": "J", "FID_COND_SCR_DIV_CODE": "16633", "FID_INPUT_ISCD": ticker,
              "FID_INPUT_DATE_1": "00" + d1, "FID_INPUT_DATE_2": "00" + d2}
    err = None
    for k in range(tries):
        time.sleep(SLEEP * (2 ** k))
        try:
            b = requests.get(BASE + PATH, headers=headers, params=params, timeout=20).json()
        except Exception as e:
            err = "요청 예외 " + type(e).__name__
            continue
        if b.get("rt_cd") == "0":
            return [r for r in (b.get("output") or []) if d1 <= str(r.get("stck_bsop_date", "")) <= d2], None
        err = f"{b.get('msg_cd')} {b.get('msg1')}"
        if b.get("msg_cd") != "EGW00201":     # 초당 건수 초과만 재시도
            break
    return [], err


def build_targets(kr_tickers):
    env = load_env_file()
    key = os.environ.get("KIS_APP_KEY") or env.get("KIS_APP_KEY")
    sec = os.environ.get("KIS_APP_SECRET") or env.get("KIS_APP_SECRET")
    tok = key and sec and get_token(key, sec)
    if not tok:
        print("KIS 키/토큰 없음 — 목표가는 직전 값 유지")
        return None
    today = datetime.now(KST)
    d1, d2 = (today - timedelta(days=WINDOW_DAYS)).strftime("%Y%m%d"), today.strftime("%Y%m%d")
    out, errors = {}, 0
    for i, t in enumerate(kr_tickers):
        rows, err = fetch_opinions(tok, key, sec, t, d1, d2)
        if err:
            errors += 1
            out[t] = {"status": "error"}
        else:
            s = summarize_targets(rows)
            out[t] = {"status": "ok", **s} if s else {"status": "none"}
        if (i + 1) % 50 == 0:
            print(f"  {i + 1}/{len(kr_tickers)} (실패 {errors})")
    share = errors / max(1, len(kr_tickers))
    print(f"목표가: {len(kr_tickers)}종목 · 있음 {sum(v['status'] == 'ok' for v in out.values())} · 없음 "
          f"{sum(v['status'] == 'none' for v in out.values())} · 실패 {errors}")
    if share > MAX_ERROR_SHARE:
        print(f"실패 {share:.0%} > {MAX_ERROR_SHARE:.0%} — 이번 목표가 버림, 직전 값 유지")
        return None
    return {"asOf": today.strftime("%Y-%m-%d %H:%M KST"), "windowDays": WINDOW_DAYS, "byTicker": out}


def selftest():
    rows = [{"mbcr_name": "A", "stck_bsop_date": "20260801", "hts_goal_prc": "100000"},
            {"mbcr_name": "A", "stck_bsop_date": "20260901", "hts_goal_prc": "120000"},   # A 는 최신 값
            {"mbcr_name": "B", "stck_bsop_date": "20260815", "hts_goal_prc": "90000"},
            {"mbcr_name": "C", "stck_bsop_date": "20260820", "hts_goal_prc": "0"}]       # 목표가 없음 = 제외
    s = summarize_targets(rows)
    assert s == {"median": 105000, "min": 90000, "max": 120000, "brokers": 2, "lastDate": "20260901"}, s
    assert summarize_targets([{"mbcr_name": "C", "hts_goal_prc": ""}]) is None
    assert week52({"h": [1] * 100, "l": [1] * 100}) is None
    w = week52({"h": [5, 9] * 70, "l": [3, 4] * 70, "d": ["x"] * 140})
    assert (w["high"], w["low"]) == (9, 3), w
    print("selftest OK")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--no-kis", action="store_true")
    ap.add_argument("--selftest", action="store_true")
    a = ap.parse_args()
    if a.selftest:
        return selftest()
    prices = json.loads((DATA / "prices.json").read_text(encoding="utf-8")).get("byTicker", {})
    latest = json.loads((DATA / "latest.json").read_text(encoding="utf-8")).get("results", [])
    prev = json.loads(OUT.read_text(encoding="utf-8")) if OUT.exists() else {}
    w52 = {t: w for t, rec in prices.items() if (w := week52(rec))}
    targets = None if a.no_kis else build_targets([r["ticker"] for r in latest if r.get("market") == "KR"])
    doc = {"generatedAt": datetime.now(KST).strftime("%Y-%m-%d %H:%M KST"),
           "note": "맥락 표시 전용 — 점수·추천·매매에 쓰지 않는다. 목표가는 KIS 회원 증권사 의견만(컨센서스 아님).",
           "week52": w52, "targets": targets or prev.get("targets")}
    OUT.write_text(json.dumps(doc, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    print(f"52주 {len(w52)}종목 → {OUT.relative_to(REPO)}")


if __name__ == "__main__":
    sys.exit(main())
