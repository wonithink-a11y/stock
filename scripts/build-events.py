#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""build-events.py — 다가오는 일정 D-day → docs/data/events.json (대시보드 '일정' 탭 · VM 아침 텔레그램).

  python scripts/build-events.py              # 전 관심종목(Yahoo) + 거시 + 규칙 일정
  python scripts/build-events.py --limit 20   # 시험용
  python scripts/build-events.py --selftest

일정 종류와 출처(날짜의 성격을 섞지 않는다 — 각 일정에 status 를 단다):
  earnings  실적 발표   Yahoo(yfinance calendar). 날짜가 둘이면 '범위(range)' = 아직 미정. 미국은 Nasdaq 실적 캘린더에
                         같은 날 올라 있으면 confirmedBy='nasdaq'. Yahoo 는 확정/예상을 구분해 주지 않는다 → 기본 status='yahoo'
  exdiv     배당락일     Yahoo. 지난 날짜는 버린다
  fomc·bok  금리 결정   config/macro-calendar.json(공식 페이지에서 손으로 옮김, 확인일 기록) — status='official'
  expiry    국내 옵션 만기(매월 둘째 목요일) · 동시만기(3·6·9·12월) — 규칙 계산, 휴장이면 직전 영업일로 당겨질 수 있다 — status='rule'
관찰용 — 점수·추천에 넣지 않는다. 일정이 목록에 없다는 것은 '일정이 없다'가 아니다(출처가 모를 뿐).
Yahoo 조회가 절반 넘게 실패하면 events.json 을 덮어쓰지 않고 exit 1(빈 목록을 '일정 없음'으로 내보내지 않는다).
"""
import argparse
import json
import os
import ssl
import sys
import time
import urllib.request
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
OUT = REPO / "docs" / "data" / "events.json"
KST = timezone(timedelta(hours=9))
HORIZON = 90


def today_kst():
    return datetime.now(KST).date()


def second_thursday(y, m):
    d = date(y, m, 1)
    first_thu = d + timedelta(days=(3 - d.weekday()) % 7)
    return first_thu + timedelta(days=7)


def rule_events(t0, horizon=HORIZON):
    out = []
    y, m = t0.year, t0.month
    for _ in range(5):
        d = second_thursday(y, m)
        if t0 <= d <= t0 + timedelta(days=horizon):
            quad = m in (3, 6, 9, 12)
            out.append({"date": d.isoformat(), "kind": "expiry", "scope": "macro", "status": "rule",
                        "title": "국내 선물·옵션 동시만기" if quad else "국내 옵션 만기",
                        "note": "매월 둘째 목요일(휴장이면 직전 영업일)" + (" · 주가지수 선물·옵션·개별주식 동시만기" if quad else "")})
        m += 1
        if m == 13:
            y, m = y + 1, 1
    return out


def macro_events(t0, cal, horizon=HORIZON):
    out, warn = [], []
    end = t0 + timedelta(days=horizon)
    for mt in cal["fomc"]["meetings"]:
        d = date.fromisoformat(mt["date"])
        if t0 <= d <= end:
            out.append({"date": d.isoformat(), "kind": "fomc", "scope": "macro", "status": "official",
                        "title": "FOMC 금리 결정" + (" (경제전망 포함)" if mt.get("sep") else ""),
                        "note": f"회의 {mt['days']} · 한국시간 {(d + timedelta(days=1)).strftime('%m-%d')} 새벽 발표", "source": cal["fomc"]["source"]})
    for mt in cal["bok"]["meetings"]:
        d = date.fromisoformat(mt["date"])
        if t0 <= d <= end:
            out.append({"date": d.isoformat(), "kind": "bok", "scope": "macro", "status": "official",
                        "title": "한국은행 금통위 기준금리 결정", "note": "오전 발표", "source": cal["bok"]["source"]})
    for k, label in (("fomc", "FOMC"), ("bok", "금통위")):
        if not any(date.fromisoformat(x["date"]) > t0 for x in cal[k]["meetings"] if date.fromisoformat(x["date"]) <= t0 + timedelta(days=120)):
            warn.append(f"{label}: 앞으로 120일 안의 일정이 macro-calendar.json 에 없다 — 공식 페이지에서 추가 필요")
    return out, warn


def kospi_codes():
    """KRX Open API 로 코스피 종목 코드(Yahoo 접미사 .KS/.KQ 구분용). 키가 없거나 실패하면 빈 집합."""
    key = os.environ.get("KRX_OPENAPI_KEY", "")
    if not key:
        return set()
    ctx = ssl.create_default_context()
    d = today_kst()
    for _ in range(10):
        d -= timedelta(days=1)
        req = urllib.request.Request(f"https://data-dbg.krx.co.kr/svc/apis/sto/stk_bydd_trd?basDd={d:%Y%m%d}",
                                     headers={"AUTH_KEY": key, "User-Agent": "Mozilla/5.0"})
        try:
            rows = json.loads(urllib.request.urlopen(req, timeout=30, context=ctx).read().decode()).get("OutBlock_1") or []
        except Exception:
            rows = []
        if rows:
            return {r["ISU_CD"] for r in rows}
    return set()


def yahoo_symbol(t, kospi):
    if t.get("market") == "US":
        return t["code"].replace(".", "-")
    return t["code"] + (".KS" if t["code"] in kospi else ".KQ")


def parse_calendar(cal, t0):
    """yfinance Ticker.calendar(dict) → [(kind, date, dateEnd|None)] (오늘 이후만)."""
    out = []
    ed = cal.get("Earnings Date") or []
    ed = [d for d in ed if isinstance(d, date)]
    if ed and max(ed) >= t0:
        out.append(("earnings", min(ed), max(ed) if len(ed) > 1 and max(ed) != min(ed) else None))
    xd = cal.get("Ex-Dividend Date")
    if isinstance(xd, date) and xd >= t0:
        out.append(("exdiv", xd, None))
    return out


def nasdaq_symbols(d):
    req = urllib.request.Request(f"https://api.nasdaq.com/api/calendar/earnings?date={d}",
                                 headers={"User-Agent": "Mozilla/5.0", "Accept": "application/json"})
    try:
        rows = ((json.loads(urllib.request.urlopen(req, timeout=30).read().decode()).get("data") or {}).get("rows") or [])
    except Exception:
        return None
    return {r.get("symbol") for r in rows}


def build(limit=None):
    import yfinance as yf
    t0 = today_kst()
    wl = json.loads((REPO / "config" / "watchlist.json").read_text(encoding="utf-8"))["tickers"]
    held = {h["code"] for h in json.loads((REPO / "config" / "holdings.json").read_text(encoding="utf-8")).get("holdings", [])}
    cal = json.loads((REPO / "config" / "macro-calendar.json").read_text(encoding="utf-8"))
    kospi = kospi_codes()
    events, fail, n = [], 0, 0
    for t in wl[:limit] if limit else wl:
        n += 1
        sym = yahoo_symbol(t, kospi)
        try:
            c = yf.Ticker(sym).calendar or {}
        except Exception:
            fail += 1
            continue
        for kind, d, d2 in parse_calendar(c, t0):
            if d > t0 + timedelta(days=HORIZON):
                continue
            e = {"date": d.isoformat(), "kind": kind, "scope": "held" if t["code"] in held else "watch", "code": t["code"],
                 "name": t["name"], "market": t.get("market", "KR"), "status": "range" if d2 else "yahoo", "source": f"yahoo:{sym}",
                 "title": "실적 발표" if kind == "earnings" else "배당락일"}
            if d2:
                e["dateEnd"] = d2.isoformat()
            events.append(e)
        time.sleep(0.25)
    if n and fail / n > 0.5:
        raise SystemExit(f"Yahoo 조회 실패 {fail}/{n} — 절반 넘게 실패해 events.json 을 덮어쓰지 않는다")
    # 미국 실적: Nasdaq 캘린더 교차 확인
    us_dates = sorted({e["date"] for e in events if e["kind"] == "earnings" and e["market"] == "US" and e["status"] != "range"})
    nasdaq_ok = 0
    for d in us_dates:
        syms = nasdaq_symbols(d)
        if syms is None:
            continue
        nasdaq_ok += 1
        for e in events:
            if e["date"] == d and e["kind"] == "earnings" and e["market"] == "US" and e["code"].replace("-", ".") in {s.replace("-", ".") for s in syms if s}:
                e["confirmedBy"] = "nasdaq"
        time.sleep(0.3)
    macro, warn = macro_events(t0, cal)
    events += macro + rule_events(t0)
    events.sort(key=lambda e: (e["date"], {"held": 0, "macro": 1, "watch": 2}[e["scope"]], e.get("name", "")))
    return {"generatedAtKST": datetime.now(KST).isoformat(timespec="seconds"), "asOf": t0.isoformat(), "horizonDays": HORIZON,
            "counts": {"watchlist": n, "yahooFail": fail, "kospiCodes": len(kospi), "nasdaqDates": f"{nasdaq_ok}/{len(us_dates)}"},
            "warnings": warn, "events": events}


def selftest():
    assert second_thursday(2026, 10) == date(2026, 10, 8) and second_thursday(2026, 12) == date(2026, 12, 10)
    r = rule_events(date(2026, 9, 26), 90)
    assert [e["date"] for e in r] == ["2026-10-08", "2026-11-12", "2026-12-10"] and "동시만기" in r[-1]["title"]
    t0 = date(2026, 9, 26)
    p = parse_calendar({"Earnings Date": [date(2026, 10, 28)], "Ex-Dividend Date": date(2026, 6, 29)}, t0)
    assert p == [("earnings", date(2026, 10, 28), None)], "지난 배당락은 버린다"
    p = parse_calendar({"Earnings Date": [date(2026, 10, 27), date(2026, 11, 2)]}, t0)
    assert p == [("earnings", date(2026, 10, 27), date(2026, 11, 2))], "두 날짜 = 범위(미정)"
    cal = {"fomc": {"source": "x", "meetings": [{"date": "2026-10-28", "days": "10-27~28"}]}, "bok": {"source": "y", "meetings": []}}
    ev, warn = macro_events(t0, cal)
    assert ev[0]["note"].endswith("10-29 새벽 발표") and any("금통위" in w for w in warn)
    assert yahoo_symbol({"code": "BRK.B", "market": "US"}, set()) == "BRK-B" and yahoo_symbol({"code": "005930", "market": "KR"}, {"005930"}) == "005930.KS"
    print("build-events selftest OK")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int)
    ap.add_argument("--selftest", action="store_true")
    a = ap.parse_args()
    if a.selftest:
        return selftest()
    out = build(a.limit)
    OUT.write_text(json.dumps(out, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    c = out["counts"]
    print(f"events: {len(out['events'])}건 · 관심 {c['watchlist']} · Yahoo 실패 {c['yahooFail']} · 코스피 코드 {c['kospiCodes']} · "
          f"Nasdaq {c['nasdaqDates']} · 경고 {out['warnings']}")


if __name__ == "__main__":
    sys.exit(main())
