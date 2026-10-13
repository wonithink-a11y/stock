#!/usr/bin/env python3
"""장 마감 리포트용 숫자 묶음(fact pack) — 숫자는 이 스크립트만 만든다. Claude 루틴은 해석만 한다.

사용:
  python scripts/market-close-facts.py kr [--out PATH]          # 평일 18:10 KST 한국장 마감 리포트
  python scripts/market-close-facts.py us [--ah TSLA,ORCL] [--out PATH]   # 평일 07:00 KST 미국장 마감 리포트
  python scripts/market-close-facts.py --selftest               # 네트워크 없이 계산 함수만 확인

출처(전부 키 없음): Yahoo chart v8(지수·ETF·금리·환율·원자재·선물) · 네이버 모바일 증권 API
(국내 상승/하락 종목 수·투자자별 순매수·프로그램·거래대금·시총 상위) · FRED CSV(미국 2년물, 하루 늦다).
값마다 barDate/asOf 와 fresh 를 붙인다. 못 받은 것은 추정으로 채우지 않고 missing 에 남긴다.

sessionOpen=false 면 그날 정규장이 없었다(휴장) 또는 기준 지수가 아직 갱신 안 됐다 — 루틴은 리포트를 쓰지 않는다.
"""
import argparse
import json
import sys
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

KST = ZoneInfo("Asia/Seoul")
NY = ZoneInfo("America/New_York")
UA = {"User-Agent": "Mozilla/5.0 (market-close-facts)"}
REPO = Path(__file__).resolve().parent.parent

# (심볼, 표시 이름, 그룹, 종류) — 종류: regular(그 시장 정규장 종가) / around(24시간·다른 시장, 시각만 기록)
KR_SERIES = [
    ("^KS11", "KOSPI", "지수", "regular"), ("^KQ11", "KOSDAQ", "지수", "regular"),
    ("091160.KS", "KODEX 반도체", "업종ETF", "regular"), ("091180.KS", "KODEX 자동차", "업종ETF", "regular"),
    ("466920.KS", "SOL 조선TOP3플러스", "업종ETF", "regular"), ("139230.KS", "TIGER 200 중공업", "업종ETF", "regular"),
    ("449450.KS", "PLUS K방산", "업종ETF", "regular"), ("244580.KS", "KODEX 바이오", "업종ETF", "regular"),
    ("143860.KS", "TIGER 헬스케어", "업종ETF", "regular"), ("305720.KS", "KODEX 2차전지산업", "업종ETF", "regular"),
    ("091170.KS", "KODEX 은행", "업종ETF", "regular"), ("102970.KS", "KODEX 증권", "업종ETF", "regular"),
    ("117460.KS", "KODEX 에너지화학", "업종ETF", "regular"), ("117680.KS", "KODEX 철강", "업종ETF", "regular"),
    ("117700.KS", "KODEX 건설", "업종ETF", "regular"),
    ("KRW=X", "원/달러", "환율", "around"), ("ES=F", "S&P500 선물", "미국선물", "around"),
    ("NQ=F", "나스닥100 선물", "미국선물", "around"),
]
US_SERIES = [
    ("^GSPC", "S&P 500", "지수", "regular"), ("^IXIC", "NASDAQ", "지수", "regular"),
    ("^DJI", "다우", "지수", "regular"), ("^RUT", "러셀 2000", "지수", "regular"),
    ("^SOX", "필라델피아 반도체", "지수", "regular"),
    ("SPY", "SPY(시총가중)", "시장폭", "regular"), ("RSP", "RSP(동일가중)", "시장폭", "regular"),
    ("XLK", "기술", "섹터", "regular"), ("XLC", "커뮤니케이션", "섹터", "regular"),
    ("XLY", "임의소비재", "섹터", "regular"), ("XLF", "금융", "섹터", "regular"),
    ("XLV", "헬스케어", "섹터", "regular"), ("XLI", "산업재", "섹터", "regular"),
    ("XLE", "에너지", "섹터", "regular"), ("XLP", "필수소비재", "섹터", "regular"),
    ("XLU", "유틸리티", "섹터", "regular"), ("XLB", "소재", "섹터", "regular"),
    ("XLRE", "부동산", "섹터", "regular"),
    ("EWY", "EWY(미국 상장 한국 ETF)", "한국연결", "regular"),
    ("^VIX", "VIX", "위험", "regular"), ("^TNX", "미국 10년물 금리(%)", "금리", "regular"),
    ("DX-Y.NYB", "달러인덱스", "환율", "around"), ("KRW=X", "원/달러", "환율", "around"),
    ("CL=F", "WTI", "원자재", "around"), ("GC=F", "금", "원자재", "around"),
    ("BTC-USD", "비트코인", "크립토", "around"),
    ("ES=F", "S&P500 선물", "미국선물", "around"), ("NQ=F", "나스닥100 선물", "미국선물", "around"),
]
US_MEGACAPS = ["NVDA", "AAPL", "MSFT", "AMZN", "GOOGL", "META", "AVGO", "TSLA"]

# 루틴이 재사용할 수 있는 저장소 JSON — Actions 가 늦게(중앙 4~5시간) 갱신하므로 날짜를 반드시 본다.
REPO_JSON = ["market-movers", "market_flows", "sector-strength", "disclosures", "news", "events", "stock-events"]


def get_json(url):
    with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=20) as r:
        return json.load(r)


def daily_closes(chart):
    """Yahoo chart 결과 → [(date, close)] (None 제거). 마지막 봉은 meta.regularMarketPrice 로 확정값을 덮는다."""
    meta = chart["meta"]
    tz = ZoneInfo(meta.get("exchangeTimezoneName") or "UTC")
    rows = []
    for ts, c in zip(chart.get("timestamp") or [], chart["indicators"]["quote"][0].get("close") or []):
        if c is not None:
            rows.append((datetime.fromtimestamp(ts, tz).date(), float(c)))
    rmt, rmp = meta.get("regularMarketTime"), meta.get("regularMarketPrice")
    if rmt and rmp is not None:
        d = datetime.fromtimestamp(rmt, tz).date()
        rows = [r for r in rows if r[0] != d] + [(d, float(rmp))]
        rows.sort()
    return rows


def pct(a, b):
    return None if a is None or b in (None, 0) else round((a / b - 1) * 100, 2)


def series_row(sym, name, group, kind, expected, now_utc):
    try:
        ch = get_json(f"https://query1.finance.yahoo.com/v8/finance/chart/{sym}?range=1mo&interval=1d")["chart"]["result"][0]
    except Exception as e:  # noqa: BLE001 — 실패는 missing 으로 보고한다
        return {"sym": sym, "name": name, "group": group, "error": str(e)[:120]}
    rows = daily_closes(ch)
    if len(rows) < 2:
        return {"sym": sym, "name": name, "group": group, "error": "봉 부족"}
    (d, c), (_, p) = rows[-1], rows[-2]
    c5 = rows[-6][1] if len(rows) >= 6 else None
    rmt = ch["meta"].get("regularMarketTime")
    at = datetime.fromtimestamp(rmt, timezone.utc).astimezone(KST) if rmt else None
    row = {"sym": sym, "name": name, "group": group, "kind": kind, "close": round(c, 4), "prevClose": round(p, 4),
           "chgPct": pct(c, p), "chg5dPct": pct(c, c5), "barDate": d.isoformat(),
           "lastTradeKST": at.isoformat(timespec="minutes") if at else None, "source": "Yahoo chart"}
    if group == "금리":  # 수익률(%) 계열은 변화율이 아니라 bp
        row["chgBp"] = round((c - p) * 100, 1)
    if kind == "regular":
        row["fresh"] = d == expected
    else:  # 24시간·타 시장: 12시간 안 값이면 fresh
        row["fresh"] = bool(at) and (now_utc - at) < timedelta(hours=12)
    return row


def naver_kr(expected):
    out, missing = {}, []
    for code in ("KOSPI", "KOSDAQ"):
        try:
            integ = get_json(f"https://m.stock.naver.com/api/index/{code}/integration")
            poll = get_json(f"https://polling.finance.naver.com/api/realtime/domestic/index/{code}")["datas"][0]
        except Exception as e:  # noqa: BLE001
            missing.append(f"네이버 {code}: {str(e)[:80]}")
            continue
        num = lambda s: None if s in (None, "", "N/A") else float(str(s).replace(",", "").replace("+", ""))  # noqa: E731
        ud, deal, prog = integ.get("upDownStockInfo") or {}, integ.get("dealTrendInfo") or {}, integ.get("programTrendInfo") or {}
        biz = deal.get("bizdate")
        out[code] = {
            "marketStatus": poll.get("marketStatus"), "localTradedAt": poll.get("localTradedAt"),
            "tradingValue조원": round(num(poll.get("accumulatedTradingValueRaw")) / 1e12, 2) if poll.get("accumulatedTradingValueRaw") else None,
            "breadth": {k: int(num(ud.get(f)) or 0) for k, f in
                        (("상승", "riseCount"), ("상한", "upperCount"), ("보합", "steadyCount"), ("하락", "fallCount"), ("하한", "lowerCount"))},
            "flows억원": {"bizdate": biz, "개인": num(deal.get("personalValue")), "외국인": num(deal.get("foreignValue")),
                         "기관": num(deal.get("institutionalValue"))},
            "program억원": {"bizdate": prog.get("bizdate"), "차익": num(prog.get("indexDifferenceReal")),
                           "비차익": num(prog.get("indexBiDifferenceReal")), "합계": num(prog.get("indexTotalReal"))},
            "topByMcap": [{"code": s.get("itemCode"), "name": s.get("stockName"), "chgPct": num(s.get("fluctuationsRatio")),
                           "mcap조원": round(num(s.get("marketValueRaw")) / 1e12, 1) if s.get("marketValueRaw") else None}
                          for s in (integ.get("enrollStocks") or [])],
            "fresh": biz == expected.strftime("%Y%m%d") and poll.get("marketStatus") == "CLOSE",
            "note": "네이버 장 마감 잠정치(투자자별은 KRX 확정치와 다를 수 있다). 시총 상위는 네이버 표시 순서.",
        }
    return out, missing


def after_hours(syms):
    """미국 정규장 종가 vs 지금까지의 시간외 마지막 체결(5분봉, includePrePost). 정규장 수익률과 합치지 않는다."""
    rows = []
    for s in syms:
        try:
            ch = get_json(f"https://query1.finance.yahoo.com/v8/finance/chart/{s}?range=1d&interval=5m&includePrePost=true")["chart"]["result"][0]
        except Exception as e:  # noqa: BLE001
            rows.append({"sym": s, "error": str(e)[:120]})
            continue
        meta = ch["meta"]
        reg = meta.get("regularMarketPrice")
        last = None
        for ts, c in zip(ch.get("timestamp") or [], ch["indicators"]["quote"][0].get("close") or []):
            t = datetime.fromtimestamp(ts, NY)
            if c is not None and (t.hour, t.minute) >= (16, 0):
                last = (t, float(c))
        rows.append({"sym": s, "regularClose": reg,
                     "regularChgPct": pct(reg, meta.get("chartPreviousClose")),
                     "ahLast": round(last[1], 4) if last else None,
                     "ahTimeET": last[0].isoformat(timespec="minutes") if last else None,
                     "ahChgPct": pct(last[1], reg) if last else None})
    return rows


def fred_last(series):
    try:
        with urllib.request.urlopen(urllib.request.Request(
                f"https://fred.stlouisfed.org/graph/fredgraph.csv?id={series}", headers=UA), timeout=20) as r:
            lines = [l.split(",") for l in r.read().decode().strip().splitlines()[1:]]
        vals = [(d, float(v)) for d, v in lines if v not in (".", "")]
        (d1, v1), (d0, v0) = vals[-1], vals[-2]
        return {"series": series, "date": d1, "value": v1, "chgBp": round((v1 - v0) * 100, 1),
                "source": "FRED(보통 하루 늦다 — date 확인)"}
    except Exception as e:  # noqa: BLE001
        return {"series": series, "error": str(e)[:120]}


def repo_freshness(now_kst):
    out = []
    for f in REPO_JSON:
        p = REPO / "docs" / "data" / f"{f}.json"
        try:
            j = json.loads(p.read_text(encoding="utf-8"))
        except Exception as e:  # noqa: BLE001
            out.append({"file": f, "error": str(e)[:80]})
            continue
        rec = {"file": f"docs/data/{f}.json"}
        for k in ("asOf", "generatedAtKST", "updatedAt"):
            if isinstance(j, dict) and isinstance(j.get(k), str):
                rec[k] = j[k]
        stamp = rec.get("generatedAtKST") or rec.get("updatedAt")
        if stamp:
            t = datetime.fromisoformat(stamp.replace("Z", "+00:00"))
            rec["ageHours"] = round((now_kst - t).total_seconds() / 3600, 1)
        out.append(rec)
    return out


def expected_session(market, now_kst):
    """그 리포트가 다룰 정규장 날짜. 주말이면 None(휴장일은 기준 지수 barDate 로 판정)."""
    d = now_kst.date() if market == "kr" else now_kst.astimezone(NY).date()
    return d if d.weekday() < 5 else None


def session_ended(market, exp, now_utc):
    """정규장 종료 + 15분 지났는가 (KR 15:30 · US 16:00 현지)."""
    if not exp:
        return False
    tz, close = (KST, (15, 45)) if market == "kr" else (NY, (16, 15))
    now = now_utc.astimezone(tz)
    return now.date() > exp or (now.date() == exp and (now.hour, now.minute) >= close)


def build(market, ah_extra, now_utc=None):
    now_utc = now_utc or datetime.now(timezone.utc)
    now_kst = now_utc.astimezone(KST)
    exp = expected_session(market, now_kst)
    spec = KR_SERIES if market == "kr" else US_SERIES
    series = [series_row(*s, exp, now_utc) for s in spec]
    anchor = next((r for r in series if r["sym"] in ("^KS11", "^GSPC")), {})
    facts = {
        "market": market, "generatedAtKST": now_kst.isoformat(timespec="seconds"),
        "expectedSession": exp.isoformat() if exp else None,
        "sessionOpen": bool(exp) and anchor.get("barDate") == exp.isoformat(),
        # 장중에 돌리면 barDate 가 오늘이어도 종가가 아니다 — false 면 루틴은 쓰지 않는다
        "regularSessionEnded": session_ended(market, exp, now_utc),
        "series": series, "missing": [f"{r['sym']} {r['name']}: {r['error']}" for r in series if "error" in r],
        "repoData": repo_freshness(now_kst),
    }
    if market == "kr":
        facts["kr"], miss = naver_kr(exp or now_kst.date())
        facts["missing"] += miss + ["국내 시간외 단일가(키 없는 출처 없음)", "종목별 지수 기여도(지수 구성 비중 없음 — 쓰지 않는다)"]
    else:
        facts["us2y"] = fred_last("DGS2")
        facts["afterHours"] = after_hours(US_MEGACAPS + [s for s in ah_extra if s not in US_MEGACAPS])
        facts["missing"] += ["미국 상승/하락 종목 수(RSP−SPY 차이로 대체)", "종목별 지수 기여도(쓰지 않는다)"]
    return facts


def selftest():
    tz = "Asia/Seoul"
    t = lambda y, m, d: int(datetime(y, m, d, 6, tzinfo=timezone.utc).timestamp())  # noqa: E731
    ch = {"meta": {"exchangeTimezoneName": tz, "regularMarketTime": t(2026, 10, 13) + 3600, "regularMarketPrice": 101.0},
          "timestamp": [t(2026, 10, 9), t(2026, 10, 12), t(2026, 10, 13)],
          "indicators": {"quote": [{"close": [99.0, None, 100.0]}]}}
    rows = daily_closes(ch)
    assert [r[1] for r in rows] == [99.0, 101.0], rows          # None 제거 · 마지막 봉은 확정값으로 덮음
    assert rows[-1][0].isoformat() == "2026-10-13"
    assert pct(101, 100) == 1.0 and pct(1, 0) is None and pct(None, 1) is None
    sat = datetime(2026, 10, 17, 9, tzinfo=KST)
    assert expected_session("kr", sat) is None
    # 07:00 KST 화요일 = 뉴욕 월요일 18:00 → 미국 기준일은 월요일
    assert expected_session("us", datetime(2026, 10, 13, 7, tzinfo=KST)).isoformat() == "2026-10-12"
    u = lambda y, m, d, h, mi: datetime(y, m, d, h, mi, tzinfo=KST).astimezone(timezone.utc)  # noqa: E731
    d13 = datetime(2026, 10, 13).date()
    assert not session_ended("kr", d13, u(2026, 10, 13, 12, 0)) and session_ended("kr", d13, u(2026, 10, 13, 18, 10))
    assert session_ended("us", datetime(2026, 10, 12).date(), u(2026, 10, 13, 7, 0))       # 뉴욕 18:00
    assert not session_ended("us", datetime(2026, 10, 12).date(), u(2026, 10, 13, 4, 0))   # 뉴욕 15:00
    print("selftest OK")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("market", nargs="?", choices=["kr", "us"])
    ap.add_argument("--ah", default="", help="미국 시간외를 볼 종목 추가(쉼표)")
    ap.add_argument("--out")
    ap.add_argument("--selftest", action="store_true")
    a = ap.parse_args()
    if a.selftest:
        return selftest()
    if not a.market:
        ap.error("kr 또는 us")
    facts = build(a.market, [s.strip().upper() for s in a.ah.split(",") if s.strip()])
    text = json.dumps(facts, ensure_ascii=False, indent=1)
    if a.out:
        Path(a.out).parent.mkdir(parents=True, exist_ok=True)
        Path(a.out).write_text(text + "\n", encoding="utf-8")
    sys.stdout.write(text + "\n")


if __name__ == "__main__":
    main()
