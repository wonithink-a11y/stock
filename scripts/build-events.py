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
  usdata    미국 경제지표  Nasdaq 경제지표 캘린더(키 없음, 앞 21일) — 핵심 지표만(US_DATA). 예상(컨센서스)·직전값을 note 에. status='nasdaq'
                         비공식 엔드포인트라 값이 틀릴 수 있다 — 같은 지표의 월·연 값이 따로 줄을 이룬다(구분 표기 없음). scope='data'(알림·홈 카드 제외)
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
US_DATA_DAYS = 21   # Nasdaq 경제지표는 3주 앞까지만 값이 있다(그 뒤는 data=null)
US_DATA = {"cpi", "core cpi", "ppi", "core ppi", "pce price index", "core pce price index", "gdp", "retail sales",
           "core retail sales", "nonfarm payrolls", "unemployment rate", "jolts job openings", "adp nonfarm employment change",
           "ism manufacturing pmi", "ism non-manufacturing pmi", "cb consumer confidence", "michigan consumer sentiment"}


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


def nasdaq_econ(d):
    req = urllib.request.Request(f"https://api.nasdaq.com/api/calendar/economicevents?date={d}",
                                 headers={"User-Agent": "Mozilla/5.0", "Accept": "application/json"})
    try:
        data = json.loads(urllib.request.urlopen(req, timeout=30).read().decode()).get("data")
    except Exception:
        return None
    return (data or {}).get("rows") if data else None


def kst_label(d, hhmm):
    """Nasdaq 'gmt' 열은 UTC-4 고정 시각이다(서머타임이 끝나도 안 바뀐다: 11월 CPI 가 08:30 이 아니라 09:30 으로 나온다).
    그래서 한국 시각 = 열 값 + 13시간이다. 실패하면 빈 문자열."""
    try:
        t = datetime.combine(d, datetime.strptime(hhmm, "%H:%M").time(), tzinfo=timezone(timedelta(hours=-4))).astimezone(KST)
        return f"한국 {t:%m-%d %H:%M}"
    except Exception:
        return ""


def us_data_events(t0, days=US_DATA_DAYS, fetch=nasdaq_econ):
    out, ok, n = [], 0, 0
    for i in range(days + 1):
        d = t0 + timedelta(days=i)
        if d.weekday() >= 5:
            continue
        n += 1
        rows = fetch(d)
        if rows is None:
            continue
        ok += 1
        seen = set()
        for r in rows:
            name = (r.get("eventName") or "").strip()
            if r.get("country") != "United States" or name.casefold() not in US_DATA:
                continue
            cons, prev, act = (r.get(k, "").replace("&nbsp;", "").strip() for k in ("consensus", "previous", "actual"))
            if (name, cons, prev) in seen:
                continue
            seen.add((name, cons, prev))
            note = " · ".join(x for x in (kst_label(d, r.get("gmt", "")), f"발표 {act}" if act else "",
                                         f"예상 {cons}" if cons else "", f"직전 {prev}" if prev else "") if x)
            out.append({"date": d.isoformat(), "kind": "usdata", "scope": "data", "status": "nasdaq",
                        "title": f"미국 {name}", "note": note, "source": "nasdaq:economicevents"})
        time.sleep(0.3)
    return out, ok, n


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
    usd, usd_ok, usd_n = us_data_events(t0)
    if usd_ok == 0:
        warn.append("미국 경제지표: Nasdaq 조회 전부 실패 — 이번 파일에 미국 지표 일정이 없다(없다는 뜻은 아님)")
    events += macro + rule_events(t0) + usd
    events.sort(key=lambda e: (e["date"], {"held": 0, "macro": 1, "data": 1, "watch": 2}[e["scope"]], e.get("name", "")))
    return {"generatedAtKST": datetime.now(KST).isoformat(timespec="seconds"), "asOf": t0.isoformat(), "horizonDays": HORIZON,
            "counts": {"watchlist": n, "yahooFail": fail, "kospiCodes": len(kospi), "nasdaqDates": f"{nasdaq_ok}/{len(us_dates)}", "usDataDays": f"{usd_ok}/{usd_n}"},
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
    rows = [{"country": "United States", "eventName": "CPI", "gmt": "08:30", "actual": "&nbsp;", "consensus": " ", "previous": "0.6%"},
            {"country": "United States", "eventName": "CPI", "gmt": "08:30", "actual": "&nbsp;", "consensus": " ", "previous": "3.7%"},
            {"country": "United States", "eventName": "CPI", "gmt": "08:30", "actual": "&nbsp;", "consensus": " ", "previous": "3.7%"},
            {"country": "United States", "eventName": "Redbook", "gmt": "08:55", "actual": "", "consensus": "", "previous": "9%"},
            {"country": "Japan", "eventName": "GDP", "gmt": "03:00", "actual": "", "consensus": "1%", "previous": "2%"}]
    ev, ok, n = us_data_events(date(2026, 11, 9), 0, lambda d: rows)   # 월요일 하루
    assert (ok, n) == (1, 1) and [e["note"].split("직전 ")[-1] for e in ev] == ["0.6%", "3.7%"], "핵심 지표만·같은 값 줄은 한 번·타국 제외"
    assert ev[0]["scope"] == "data" and "예상" not in ev[0]["note"] and kst_label(date(2026, 11, 9), "09:30") == "한국 11-09 22:30" and kst_label(date(2026, 11, 9), "") == ""
    assert us_data_events(date(2026, 11, 9), 0, lambda d: None) == ([], 0, 1), "조회 실패는 빈 목록이 아니라 실패로 센다"
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
          f"Nasdaq {c['nasdaqDates']} · 미국지표 {c['usDataDays']} · 경고 {out['warnings']}")


if __name__ == "__main__":
    sys.exit(main())
