#!/usr/bin/env python3
"""장 마감 리포트용 숫자 묶음(fact pack) — 숫자는 이 스크립트만 만든다. Claude 루틴은 해석만 한다.

사용:
  python scripts/market-close-facts.py kr [--out PATH]          # 평일 18:10 KST 한국장 마감 리포트
  python scripts/market-close-facts.py us [--ah TSLA,ORCL] [--out PATH]   # 평일 07:00 KST 미국장 마감 리포트
  python scripts/market-close-facts.py --selftest               # 네트워크 없이 계산 함수만 확인

출처(전부 키 없음): Yahoo chart v8(지수·ETF·금리·환율·원자재·선물) · 네이버 모바일 증권 API
(국내 상승/하락 종목 수·투자자별 순매수·프로그램·거래대금·시총 상위 — 시총 상위 등락률은 네이버 차트 API 의 KRX 정규장 일봉으로 다시 계산) · 미 재무부 일일 금리(미국 2년물, 실패 시 FRED) · 구글 뉴스 RSS(원인 후보 기사 제목).
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
    ("434730.KS", "HANARO 원자력iSelect", "업종ETF", "regular"), ("487240.KS", "KODEX AI전력핵심설비", "업종ETF", "regular"),
    ("228790.KS", "TIGER 화장품", "업종ETF", "regular"), ("266360.KS", "KODEX K콘텐츠", "업종ETF", "regular"),
    # 한국만의 움직임인지 가르는 대조군(반대 증거) — 대만은 반도체 비중이 비슷하다
    ("^N225", "닛케이225", "아시아", "regular"), ("^TWII", "대만 가권", "아시아", "regular"),
    ("000001.SS", "상해종합", "아시아", "regular"), ("^HSI", "항셍", "아시아", "regular"),
    ("KRW=X", "원/달러", "환율", "around"), ("ES=F", "S&P500 선물", "미국선물", "around"),
    ("NQ=F", "나스닥100 선물", "미국선물", "around"),
    ("CL=F", "WTI", "원자재", "around"),
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


def regular_chg(rows, expected):
    """[(date, close)] → expected 날의 정규장 등락률(%). 그날 봉이 없거나 직전 봉이 없으면 None(추정 안 함)."""
    if not rows or rows[-1][0] != expected or len(rows) < 2:
        return None
    return pct(rows[-1][1], rows[-2][1])


def after_move(close, price, at, expected):
    """애프터마켓(NXT) 칸 — 정규장 종가 대비(전일 대비 아님, 인베스팅닷컴 '폐장후'와 같은 기준).
    그날 15:30 뒤 체결이 있고 정규장 종가를 알 때만 낸다. 아니면 빈 dict(칸 숨김) — 정규장 값과 섞지 않는다(2026-11-01)."""
    if close is None or price is None or not at:
        return {}
    try:
        t = datetime.fromisoformat(at).astimezone(KST)
    except ValueError:
        return {}
    if t.date() != expected or (t.hour, t.minute) <= (15, 30):
        return {}
    return {"afterPrice": price, "afterChg": round(price - close, 4), "afterPct": pct(price, close), "afterAtKST": t.isoformat(timespec="minutes")}


def fix_top_chg(top, rows_by_code, expected):
    """시총 상위의 등락률을 KRX 정규장 종가 기준으로 바꾼다(2026-11-01, 출처 naver_daily_kr).
    네이버 fluctuationsRatio 는 18:10 엔 애프터마켓(NXT) 가격, 밤엔 '전일 종가'가 전날 애프터마켓 마지막 가격이라
    정규장 등락과 다르다(10-30 삼성전자 −3.88%·−4.96% vs 정규장 −4.34%). 정규장 값을 못 구한 종목만 네이버 값을 두고
    chgSource 로 구분한다 — 화면은 그걸 보고 '근사' 표시를 한다."""
    out = []
    for t in top:
        r = dict(t, chgPctNaver=t.get("chgPct"))
        rows = rows_by_code.get(t.get("code"))
        reg = regular_chg(rows, expected)
        if reg is not None:
            r["chgPct"], r["chgSource"], r["close"] = reg, "naver-krx-day", rows[-1][1]
        else:
            r["chgSource"] = "naver-integrated"
        r.update(after_move(r.get("close"), r.pop("afterPrice", None), r.pop("afterAt", None), expected))
        out.append(r)
    return out


def naver_daily_kr(code, expected, days=14):
    """국내 종목 KRX 정규장 일봉 [(date, close)] — 네이버 차트 API(api.stock.naver.com/chart/domestic/item/{code}/day).
    이 응답의 종가·거래량은 KRX 정규장만이다(10-27~10-30 삼성전자 225,000·245,000·230,500·220,500 = KIS 정규장, 거래량 19,485,781 = KRX 단독 — 11-01 실측).
    ★ Yahoo .KS 는 쓰지 않는다 — 개별 종목 일봉이 애프터마켓 가격을 섞는다(10-30 삼성전자 225,000 vs 정규장 220,500, 같은 날 현대차 282,000 vs 278,500).
    ★ 주식 현금배당은 수정하지 않고(2024-12-27 삼성전자 배당락 전후 원값 그대로) ETF 분배금은 수정한다
    (069500 10-29 분배락 136원 — 이전 종가가 ×0.99859, KRX 분배락 기준가·네이버 등락률 −1.10% 와 같음, 11-01 실측).
    실패하면 None(그 종목만 네이버 통합 등락률을 '근사'로 남긴다)."""
    try:
        a = (expected - timedelta(days=days)).strftime("%Y%m%d")
        j = get_json(f"https://api.stock.naver.com/chart/domestic/item/{code}/day?startDateTime={a}0000&endDateTime={expected.strftime('%Y%m%d')}2359")
        return sorted((datetime.strptime(x["localDate"], "%Y%m%d").date(), float(x["closePrice"])) for x in j if x.get("closePrice") is not None)
    except Exception:  # noqa: BLE001
        return None


def pick_kr_rows(yahoo, naver):
    """국내 ETF 일봉 고르기 — 네이버 차트(분배락 수정 = KRX 기준가)가 Yahoo 의 마지막 봉까지 있고 21봉 이상이면 네이버.
    18:10 에 네이버가 그날 봉을 아직 안 주면 Yahoo 를 그대로 쓴다(두 소스를 한 계열에 섞지 않는다)."""
    if naver and yahoo and naver[-1][0] >= yahoo[-1][0] and len(naver) >= 21:
        return [r for r in naver if r[0] <= yahoo[-1][0]], "naver-krx-day"
    return yahoo, "Yahoo chart"


def series_row(sym, name, group, kind, expected, now_utc, asof=None):
    try:
        ch = get_json(f"https://query1.finance.yahoo.com/v8/finance/chart/{sym}?range=3mo&interval=1d")["chart"]["result"][0]
    except Exception as e:  # noqa: BLE001 — 실패는 missing 으로 보고한다
        return {"sym": sym, "name": name, "group": group, "error": str(e)[:120]}
    rows = daily_closes(ch)
    if asof:
        rows = [r for r in rows if r[0] <= asof]
    src = "Yahoo chart"
    if sym.endswith(".KS"):  # 국내 ETF — Yahoo 종가는 분배락 미수정이라 분배락 날 등락·5/20일 수익률이 KRX 와 어긋난다
        nv = naver_daily_kr(sym[:-3], asof or expected or now_utc.astimezone(KST).date(), days=45)
        rows, src = pick_kr_rows(rows, nv)
    if len(rows) < 2:
        return {"sym": sym, "name": name, "group": group, "error": "봉 부족"}
    (d, c), (_, p) = rows[-1], rows[-2]
    c5 = rows[-6][1] if len(rows) >= 6 else None
    c20 = rows[-21][1] if len(rows) >= 21 else None
    rmt = ch["meta"].get("regularMarketTime")
    at = datetime.fromtimestamp(rmt, timezone.utc).astimezone(KST) if rmt and not asof else None
    row = {"sym": sym, "name": name, "group": group, "kind": kind, "close": round(c, 4), "prevClose": round(p, 4),
           "chgPct": pct(c, p), "chg5dPct": pct(c, c5), "chg20dPct": pct(c, c20), "barDate": d.isoformat(),
           "lastTradeKST": at.isoformat(timespec="minutes") if at else None, "source": src}
    if group == "금리":  # 수익률(%) 계열은 변화율이 아니라 bp
        row["chgBp"] = round((c - p) * 100, 1)
    if kind == "regular":
        row["fresh"] = d == expected
    elif asof:  # 과거 날짜: 그날 또는 직전 3일 안 봉
        row["fresh"] = (asof - d).days <= 3
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
                           "afterPrice": num(s.get("closePriceRaw")), "afterAt": s.get("localTradedAt"),   # 받는 시각의 통합(NXT 포함) 마지막 체결 — 애프터 칸용
                           "mcap조원": round(num(s.get("marketValueRaw")) / 1e12, 1) if s.get("marketValueRaw") else None}
                          for s in (integ.get("enrollStocks") or [])],
            "fresh": biz == expected.strftime("%Y%m%d") and poll.get("marketStatus") == "CLOSE",
            "note": "네이버 장 마감 잠정치(투자자별은 KRX 확정치와 다를 수 있다). 시총 상위는 네이버 표시 순서, "
                    "등락률은 KRX 정규장 종가 기준(chgSource=naver-krx-day, 못 구하면 naver-integrated = 애프터마켓 포함 근사).",
        }
        top = out[code]["topByMcap"]
        out[code]["topByMcap"] = fix_top_chg(top, {t["code"]: naver_daily_kr(t["code"], expected) for t in top if t.get("code")}, expected)
        nf = sum(1 for t in out[code]["topByMcap"] if t["chgSource"] != "naver-krx-day")
        if nf:
            missing.append(f"{code} 시총 상위 {nf}종목 정규장 등락 못 받음 — 네이버 통합 등락률(애프터마켓 포함 근사)")
    try:  # 코스피200 선물 투자자별 — 같은 응답 구조(dealTrendInfo). 네이버는 당일 값만 준다(과거 날짜 없음)
        fut = get_json("https://m.stock.naver.com/api/index/FUT/integration")
        deal = fut.get("dealTrendInfo") or {}
        num = lambda s: None if s in (None, "", "N/A") else float(str(s).replace(",", "").replace("+", ""))  # noqa: E731
        out["KOSPI200선물"] = {
            "month": fut.get("month"),
            "flows억원": {"bizdate": deal.get("bizdate"), "개인": num(deal.get("personalValue")),
                         "외국인": num(deal.get("foreignValue")), "기관": num(deal.get("institutionalValue"))},
            "fresh": deal.get("bizdate") == expected.strftime("%Y%m%d"),
            "note": "네이버 코스피200 선물(근월물 기준 화면) 투자자별 순매수, 억원으로 판단(계약 수 아님 — 10-16 −9,540 ≈ 기사 '선물 1.1조 매도', "
                    "미니선물 제외 추정). 현물 수급과 더하지 않는다.",
        }
    except Exception as e:  # noqa: BLE001
        missing.append(f"네이버 코스피200 선물 수급: {str(e)[:80]}")
    return out, missing


def repo_flows(asof):
    """과거 날짜의 국내 투자자별 순매수 — 저장소 market_flows.json(pykrx, KRX 확정치)."""
    try:
        j = json.loads((REPO / "docs" / "data" / "market_flows.json").read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return {}
    out = {}
    for code, m in (j.get("markets") or {}).items():
        day = next((d for d in m.get("days", []) if d.get("date") == asof.strftime("%Y%m%d")), None)
        if day:
            net = {i["name"]: round(i["net"] / 1e8) for i in day["items"]}
            out[code] = {"flows억원": {"bizdate": day["date"], "개인": net.get("개인"), "외국인": net.get("외국인"),
                                      "기관": net.get("기관합계")},
                         "fresh": True, "note": "KRX 확정치(pykrx, 저장소 market_flows.json). 종목 수·프로그램·시총 상위는 과거 날짜라 없음."}
    return out


def after_hours(syms, asof=None):
    """미국 정규장 종가 vs 그날 시간외 마지막 체결(5분봉, includePrePost). 정규장 수익률과 합치지 않는다.
    asof 면 정규장 종가는 일봉에서, 시간외는 그날 16:00~20:00 ET 5분봉에서(Yahoo 5분봉은 최근 60일만)."""
    rows = []
    for s in syms:
        try:
            if asof:
                day = [r for r in daily_closes(get_json(
                    f"https://query1.finance.yahoo.com/v8/finance/chart/{s}?range=3mo&interval=1d")["chart"]["result"][0]) if r[0] <= asof]
                if not day or day[-1][0] != asof:
                    raise ValueError("그날 일봉 없음")
                p1 = int(datetime(asof.year, asof.month, asof.day, 16, tzinfo=NY).timestamp())
                ch = get_json(f"https://query1.finance.yahoo.com/v8/finance/chart/{s}?interval=5m&includePrePost=true"
                              f"&period1={p1}&period2={p1 + 4 * 3600 + 300}")["chart"]["result"][0]
            else:
                ch = get_json(f"https://query1.finance.yahoo.com/v8/finance/chart/{s}?range=1d&interval=5m&includePrePost=true")["chart"]["result"][0]
        except Exception as e:  # noqa: BLE001
            rows.append({"sym": s, "error": str(e)[:120]})
            continue
        meta = ch["meta"]
        reg = day[-1][1] if asof else meta.get("regularMarketPrice")
        prev = day[-2][1] if asof else meta.get("chartPreviousClose")
        last = None
        for ts, c in zip(ch.get("timestamp") or [], ch["indicators"]["quote"][0].get("close") or []):
            t = datetime.fromtimestamp(ts, NY)
            if c is not None and (t.hour, t.minute) > (16, 0) and (not asof or t.date() == asof):
                last = (t, float(c))
        rows.append({"sym": s, "regularClose": round(reg, 4) if reg else None,
                     "regularChgPct": pct(reg, prev),
                     "ahLast": round(last[1], 4) if last else None,
                     "ahTimeET": last[0].isoformat(timespec="minutes") if last else None,
                     "ahChgPct": pct(last[1], reg) if last else None})
    return rows


def fred_last(series, asof=None):
    """FRED — 보통 하루 늦다. Yahoo 2YY=F(2년물 금리 선물)는 거래량 0·값 고정·월물 교체 때 튐(10-16 실측)이라 쓰지 않는다."""
    for attempt in range(2):   # 10-15 us 에서 20초 시간 초과 — 한 번 더 길게
        try:
            with urllib.request.urlopen(urllib.request.Request(
                    f"https://fred.stlouisfed.org/graph/fredgraph.csv?id={series}", headers=UA), timeout=20 + 20 * attempt) as r:
                lines = [l.split(",") for l in r.read().decode().strip().splitlines()[1:]]
            vals = [(d, float(v)) for d, v in lines if v not in (".", "") and (not asof or d <= asof.isoformat())]
            (d1, v1), (d0, v0) = vals[-1], vals[-2]
            return {"series": series, "date": d1, "value": v1, "chgBp": round((v1 - v0) * 100, 1),
                    "source": "FRED(보통 하루 늦다 — date 확인)"}
        except Exception as e:  # noqa: BLE001
            err = str(e)[:120]
    return {"series": series, "error": err}


def treasury_2y(exp, asof=None):
    """미 재무부 일일 국채 금리(Daily Treasury Par Yield Curve) — FRED DGS2 의 원본, 그날 저녁(보통 18:00 ET 전) 발표.
    월초엔 전일 값이 지난달에 있어 두 달을 읽는다."""
    import re
    day = asof or exp or datetime.now(NY).date()
    first = day.replace(day=1)
    vals = {}
    for m in (first - timedelta(days=1), first):
        with urllib.request.urlopen(urllib.request.Request(
                "https://home.treasury.gov/resource-center/data-chart-center/interest-rates/pages/xml"
                f"?data=daily_treasury_yield_curve&field_tdr_date_value_month={m:%Y%m}", headers=UA), timeout=30) as r:
            x = r.read().decode()
        vals.update(re.findall(r"<d:NEW_DATE[^>]*>(\d{4}-\d{2}-\d{2})T.*?<d:BC_2YEAR[^>]*>([\d.]+)<", x, re.S))
    rows = sorted((d, float(v)) for d, v in vals.items() if d <= day.isoformat())
    (d1, v1), (_, v0) = rows[-1], rows[-2]
    return {"series": "Treasury BC_2YEAR", "date": d1, "value": v1, "chgBp": round((v1 - v0) * 100, 1),
            "fresh": bool(exp) and d1 == exp.isoformat(),
            "source": "미 재무부 Daily Treasury Par Yield Curve(발표가 리포트 시각보다 늦으면 전날 값 — date·fresh 확인)"}


def z_last(closes, w=252):
    """마지막 일수익 ÷ 직전 w 개 일수익의 표본 표준편차(현재 제외) — 연구 zpast(us_overnight_study.py)와 같은 정의."""
    r = [b / a - 1 for a, b in zip(closes, closes[1:])]
    if len(r) < w + 1:
        return None
    prev = r[-w - 1:-1]
    m = sum(prev) / w
    sd = (sum((x - m) ** 2 for x in prev) / (w - 1)) ** 0.5
    return round(r[-1] / sd, 2) if sd else None


def sox_z(asof=None):
    try:
        rows = daily_closes(get_json("https://query1.finance.yahoo.com/v8/finance/chart/%5ESOX?range=2y&interval=1d")["chart"]["result"][0])
    except Exception as e:  # noqa: BLE001
        return {"error": str(e)[:120]}
    rows = [r for r in rows if not asof or r[0] <= asof]
    return {"date": rows[-1][0].isoformat(), "z": z_last([c for _, c in rows]),
            "note": "연구 메모 'SOX z ≥ 1' 조건 판정용. 미국 휴장이 끼면 연구는 여러 날 누적이라 근사다."}


def earnings_syms(day):
    """events.json(관심종목) 에서 그날 미국 실적 발표 종목 — 시간외 자동 조회용. 발표 시각(장 전/후)은 없다."""
    try:
        ev = json.loads((REPO / "docs" / "data" / "events.json").read_text(encoding="utf-8")).get("events") or []
    except Exception:  # noqa: BLE001
        return []
    return [e["code"] for e in ev if e.get("market") == "US" and e.get("kind") == "earnings"
            and e.get("date") == day.isoformat() and e.get("code")]


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


def build(market, ah_extra, now_utc=None, asof=None):
    now_utc = now_utc or datetime.now(timezone.utc)
    now_kst = now_utc.astimezone(KST)
    exp = (asof if asof.weekday() < 5 else None) if asof else expected_session(market, now_kst)
    spec = KR_SERIES if market == "kr" else US_SERIES
    series = [series_row(*s, exp, now_utc, asof) for s in spec]
    anchor = next((r for r in series if r["sym"] in ("^KS11", "^GSPC")), {})
    facts = {
        "market": market, "generatedAtKST": now_kst.isoformat(timespec="seconds"),
        "expectedSession": exp.isoformat() if exp else None,
        "sessionOpen": bool(exp) and anchor.get("barDate") == exp.isoformat(),
        # 장중에 돌리면 barDate 가 오늘이어도 종가가 아니다 — false 면 루틴은 쓰지 않는다
        "regularSessionEnded": session_ended(market, exp, now_utc),
        "backfill": bool(asof),
        "series": series, "missing": [f"{r['sym']} {r['name']}: {r['error']}" for r in series if "error" in r],
        "repoData": repo_freshness(now_kst),
    }
    if market == "kr":
        if asof:
            facts["kr"], miss = repo_flows(asof), ["상승/하락 종목 수·프로그램·거래대금·시총 상위·선물 투자자별(과거 날짜 — 네이버는 당일만)"]
            if not facts["kr"]:
                miss.append("투자자별 순매수(저장소 market_flows.json 에 그날 없음)")
        else:
            facts["kr"], miss = naver_kr(exp or now_kst.date())
        facts["missing"] += miss   # 상시 없는 것(시간외 단일가·지수 기여도)은 매일 같은 줄이라 뺐다 — 금지는 지시문 2절
    else:
        try:
            facts["us2y"] = treasury_2y(exp, asof)
        except Exception as e:  # noqa: BLE001 — 재무부가 막히면 하루 늦은 FRED
            facts["us2y"] = {**fred_last("DGS2", asof), "treasuryError": str(e)[:120]}
        facts["soxZ"] = sox_z(asof)
        earn = earnings_syms(exp) if exp else []
        facts["earningsToday"] = earn
        ah = list(dict.fromkeys(US_MEGACAPS + earn + ah_extra))
        facts["afterHours"] = after_hours(ah, asof)
    if exp:
        facts["news"], miss = news_candidates(market, exp, now_utc)
        facts["missing"] += miss
    return facts


NEWS_QUERIES = {
    "kr": ("hl=ko&gl=KR&ceid=KR:ko", ["코스피 마감", "코스닥 마감", "코스피 장중", "증시 외국인 순매도", "특징주 급등", "특징주 급락"]),
    "us": ("hl=en-US&gl=US&ceid=US:en", ["stock market today", "stock futures", "Wall Street stocks close", "Treasury yields",
                                          "stocks after the bell earnings", "Nasdaq chip stocks"]),
}


def news_candidates(market, day, now_utc):
    """원인 후보 기사 — 구글 뉴스 RSS 날짜 범위 검색(제목·게시 시각·링크만). 창 = 그날 00:00 ~ 리포트 시각
    (kr 그날 18:10 KST · us 다음 날 07:00 KST). 사후 해설이 섞이지 않게 리포트 시각 뒤 기사는 버린다."""
    import email.utils
    import urllib.parse
    import xml.etree.ElementTree as ET
    tz = KST if market == "kr" else NY
    start = datetime(day.year, day.month, day.day, tzinfo=tz)
    end = (datetime(day.year, day.month, day.day, 18, 10, tzinfo=KST) if market == "kr"
           else datetime(day.year, day.month, day.day, tzinfo=KST) + timedelta(days=1, hours=7))
    end = min(end, now_utc)
    hl, queries = NEWS_QUERIES[market]
    seen, items, errors = set(), [], []
    for q in queries:
        rng = f" after:{day - timedelta(days=1)} before:{day + timedelta(days=2)}"
        url = f"https://news.google.com/rss/search?q={urllib.parse.quote(q + rng)}&{hl}"
        try:
            with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=20) as r:
                root = ET.fromstring(r.read())
        except Exception as e:  # noqa: BLE001
            errors.append(f"뉴스 '{q}': {str(e)[:80]}")
            continue
        for it in root.iter("item"):
            title, pub = it.findtext("title") or "", it.findtext("pubDate")
            if not pub or title in seen:
                continue
            t = email.utils.parsedate_to_datetime(pub)
            if start <= t <= end:
                seen.add(title)
                items.append({"pubKST": t.astimezone(KST).isoformat(timespec="minutes"), "title": title,
                              "link": it.findtext("link"), "query": q})
    close_kst = (datetime(day.year, day.month, day.day, 15, 30, tzinfo=KST) if market == "kr"
                 else datetime(day.year, day.month, day.day, 16, tzinfo=NY)).astimezone(KST).isoformat(timespec="minutes")
    items.sort(key=lambda x: x["pubKST"])
    for i in items:
        i["afterClose"] = i["pubKST"] >= close_kst
    pre, post = [i for i in items if not i["afterClose"]], [i for i in items if i["afterClose"]]
    # 장중 기사(시각 대조의 재료)와 마감 해설을 따로 자른다 — 한 번에 뒤 60개로 자르면 마감 해설만 남는다(10-16 실측: 175건 중 장중 92건 전부 탈락)
    return {"window": [start.astimezone(KST).isoformat(timespec="minutes"), end.astimezone(KST).isoformat(timespec="minutes")],
            "closeKST": close_kst, "source": "Google News RSS(제목만 — 본문 확인 전엔 '언론 해석')",
            "items": pre[-80:] + post[-50:]}, errors


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
    assert z_last([100.0] * 100) is None                                                      # 표본 부족
    cl = [100.0]
    for i in range(253):
        cl.append(cl[-1] * (1.01 if i % 2 else 0.99))
    cl.append(cl[-1] * 1.03)
    assert 2.9 < z_last(cl) < 3.1, z_last(cl)                                                 # ±1% 진동 뒤 +3% ≈ z 3
    d29, d30 = datetime(2026, 10, 29).date(), datetime(2026, 10, 30).date()
    assert regular_chg([(d29, 230500.0), (d30, 220500.0)], d30) == -4.34                     # 10-30 삼성전자 정규장
    assert regular_chg([(d29, 230500.0)], d30) is None and regular_chg(None, d30) is None     # 그날 봉 없음 → 추정 안 함
    top = [{"code": "005930", "chgPct": -3.88}, {"code": "000660", "chgPct": -7.47}]
    fx = fix_top_chg(top, {"005930": [(d29, 230500.0), (d30, 220500.0)], "000660": None}, d30)
    assert fx[0]["chgPct"] == -4.34 and fx[0]["chgSource"] == "naver-krx-day" and fx[0]["chgPctNaver"] == -3.88
    assert fx[1]["chgPct"] == -7.47 and fx[1]["chgSource"] == "naver-integrated"             # 못 구하면 네이버 값 그대로 + 표시
    am = after_move(220500.0, 221000.0, "2026-10-30T18:09:00+09:00", d30)
    assert am["afterChg"] == 500.0 and am["afterPct"] == 0.23 and am["afterAtKST"].startswith("2026-10-30T18:09")   # 정규장 종가 대비
    assert after_move(220500.0, 221000.0, "2026-10-30T15:30:00+09:00", d30) == {}            # 15:30 이하 = 정규장 체결 → 애프터 아님
    assert after_move(220500.0, 221000.0, "2026-10-29T19:00:00+09:00", d30) == {}            # 다른 날 체결
    assert after_move(None, 221000.0, "2026-10-30T18:09:00+09:00", d30) == {}                # 정규장 종가 모름 → 칸 숨김
    fx2 = fix_top_chg([{"code": "005930", "chgPct": -3.88, "afterPrice": 221000.0, "afterAt": "2026-10-30T18:09:00+09:00"}],
                      {"005930": [(d29, 230500.0), (d30, 220500.0)]}, d30)
    assert fx2[0]["close"] == 220500.0 and fx2[0]["afterPct"] == 0.23 and "afterAt" not in fx2[0]
    days = [d29 - timedelta(days=i) for i in range(30, 0, -1)] + [d29, d30]
    nv = [(d, 95515.0 if d < d29 else 94465.0) for d in days]                                 # 069500 분배락 수정 계열
    yh = [(d, 95650.0 if d < d29 else 94465.0) for d in days]
    r, src = pick_kr_rows(yh, nv)
    assert src == "naver-krx-day" and r[-1][0] == d30 and pct(r[-2][1], r[-3][1]) == -1.10   # 10-29 = KRX 분배락 기준 −1.10%
    assert pick_kr_rows(yh, nv[:-1]) == (yh, "Yahoo chart")                                   # 네이버가 그날 봉 아직 없음 → 섞지 않음
    assert pick_kr_rows(yh, None) == (yh, "Yahoo chart") and pick_kr_rows(yh, nv[-5:])[1] == "Yahoo chart"   # 실패·20일 봉 부족
    assert pick_kr_rows(yh[:-1], nv)[0][-1][0] == d29                                         # 과거 날짜(asof): Yahoo 마지막 봉까지만
    print("selftest OK")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("market", nargs="?", choices=["kr", "us"])
    ap.add_argument("--ah", default="", help="미국 시간외를 볼 종목 추가(쉼표)")
    ap.add_argument("--out")
    ap.add_argument("--date", help="과거 날짜 YYYY-MM-DD(백필). 국내 수급은 저장소 KRX 확정치, 종목 수·시총 상위는 없음")
    ap.add_argument("--selftest", action="store_true")
    a = ap.parse_args()
    if a.selftest:
        return selftest()
    if not a.market:
        ap.error("kr 또는 us")
    asof = datetime.strptime(a.date, "%Y-%m-%d").date() if a.date else None
    facts = build(a.market, [s.strip().upper() for s in a.ah.split(",") if s.strip()], asof=asof)
    text = json.dumps(facts, ensure_ascii=False, indent=1)
    if a.out:
        Path(a.out).parent.mkdir(parents=True, exist_ok=True)
        Path(a.out).write_text(text + "\n", encoding="utf-8")
    sys.stdout.write(text + "\n")


if __name__ == "__main__":
    main()
