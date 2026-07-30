#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
fetch-fundamentals-us.py  (v1.0)

미국 종목의 재무·밸류에이션 데이터를 자동 수집해 config/fundamentals.json 의
US 항목만 갱신합니다. 한국 종목(fetch-fundamentals-kr.js 산출물)은 절대 건드리지 않습니다.

── 데이터 소스 (2단 구조) ─────────────────────────────────────────
 1차: yfinance  — Yahoo Finance 재무제표 3종(income/balance/cashflow) + sector/industry
 2차: SEC EDGAR XBRL companyfacts — 1차에서 결측인 필드만 보완 (공식·무키·ToS 안전)
      한국의 DART와 같은 위치의 '원천' 소스입니다.

 인베스팅닷컴은 Cloudflare 차단 + 이용약관상 스크래핑 금지라 의도적으로 제외했습니다.

── 산출 필드 ──────────────────────────────────────────────────────
 [스코어링 직접 사용]
   roe, roeHistory5y, debtRatio, debtRatioRaw, currentRatio,
   operatingMarginTrend(-1~1), operatingMarginTrendPP(%p),
   revenueGrowthYoY, epsGrowthRate, buybackOrDividendHistory,
   sectorType, sectorResolved
 [매일 PER/PBR 재계산용 - collect.js 가 Stooq 종가와 나눠 씀]
   epsTtm, bvps, sectorPer, per, pbr, perRelative
 [진단]
   _source, _asOf, _fields (필드별 출처: yf | sec | null)

 ※ per/pbr 을 여기서 한 번만 박아두면 분기마다 낡습니다. 그래서 epsTtm·bvps 를 함께
   저장하고, collect.js 가 매일 Stooq 종가로 per=price/epsTtm, pbr=price/bvps 를
   다시 계산합니다(추가 네트워크 호출 0회). 여기 값은 계산 실패 시의 폴백입니다.

── 사용법 ─────────────────────────────────────────────────────────
   python scripts/fetch-fundamentals-us.py                 # 전체 US 종목
   python scripts/fetch-fundamentals-us.py --only AAPL,KO  # 일부만
   python scripts/fetch-fundamentals-us.py --dry-run       # 파일 저장 안 함
   python scripts/fetch-fundamentals-us.py --no-sec        # SEC 폴백 끄기
   python scripts/fetch-fundamentals-us.py --selftest      # 네트워크 없이 계산식 검증

 환경변수
   SEC_UA   SEC 요청 User-Agent (예: "stock-scoring wonithink@gmail.com"). SEC 규정상 필수.
   US_SLEEP 종목 간 대기(초, 기본 1.5). Yahoo 429 회피용.

설계 원칙 — 프로젝트의 '정직한 점수'를 따릅니다.
 · 수집 실패 필드는 추정하지 않고 null 로 남깁니다(기본점수 부여 금지).
 · 한 종목이 실패해도 전체가 죽지 않습니다.
 · 기존 파일에 이미 값이 있고 이번에 못 받았으면 기존 값을 지우지 않고 보존합니다.
"""

import argparse
import json
import os
import sys
import time
import datetime as dt
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
FUND_PATH = ROOT / "config" / "fundamentals.json"
WATCHLIST_PATH = ROOT / "config" / "watchlist.json"
SECTOR_MAP_PATH = ROOT / "config" / "sector-map-us.json"

SLEEP_SEC = float(os.environ.get("US_SLEEP", "1.5"))
SEC_UA = os.environ.get("SEC_UA", "stock-scoring-app contact@example.com")

# 은행·보험처럼 유동자산/유동부채 구분을 하지 않는 업종은 currentRatio 를 산출하지 않습니다.
NO_CURRENT_RATIO_SECTORS = {"financial", "reit"}


# ════════════════════════════════════════════════════════════════
# 계산 유틸 (순수 함수 — --selftest 로 검증)
# ════════════════════════════════════════════════════════════════

def r1(x, nd=1):
    """소수 자리 정리. None 안전."""
    if x is None:
        return None
    try:
        if x != x or x in (float("inf"), float("-inf")):  # NaN/Inf
            return None
    except TypeError:
        return None
    return round(float(x), nd)


def safe_div(a, b):
    if a is None or b is None:
        return None
    try:
        if float(b) == 0.0:
            return None
        return float(a) / float(b)
    except (TypeError, ValueError):
        return None


def pct(a, b):
    """a/b 를 % 로. b<=0 이면 None (자본잠식 기업의 ROE는 의미 없음)."""
    if a is None or b is None:
        return None
    try:
        if float(b) <= 0:
            return None
        return float(a) / float(b) * 100.0
    except (TypeError, ValueError):
        return None


def growth_pct(latest, prev):
    """YoY 성장률(%). prev<=0 이면 None — 적자→흑자 전환을 +9999% 로 만들지 않기 위함."""
    if latest is None or prev is None:
        return None
    try:
        if float(prev) <= 0:
            return None
        return (float(latest) - float(prev)) / abs(float(prev)) * 100.0
    except (TypeError, ValueError):
        return None


def margin_trend(margins):
    """
    영업이익률 추세.
    margins: 과거→최신 순 영업이익률(%) 리스트.
    반환: (trend, trendPP)
      trendPP = 최신 - 최초 (%p)
      trend   = clamp(trendPP / 5, -1, 1)   ← criteria 의 -1~1 스케일
                (fetch-fundamentals-kr.js 와 동일한 환산: 5%p 개선 = +1.0 만점)
    """
    vals = [v for v in margins if v is not None]
    if len(vals) < 2:
        return None, None
    pp = vals[-1] - vals[0]
    trend = max(-1.0, min(1.0, pp / 5.0))
    return round(trend, 2), r1(pp, 2)


def median(vals):
    v = sorted(x for x in vals if x is not None)
    if not v:
        return None
    n = len(v)
    return v[n // 2] if n % 2 else (v[n // 2 - 1] + v[n // 2]) / 2.0


# ════════════════════════════════════════════════════════════════
# 업종 분류 (config/sector-map-us.json)
# ════════════════════════════════════════════════════════════════

DEFAULT_SECTOR_MAP = {
    "default": "general",
    "byTicker": {},
    "byIndustryPattern": [],
    "bySectorPattern": [],
}


def load_sector_map():
    if SECTOR_MAP_PATH.exists():
        try:
            return json.loads(SECTOR_MAP_PATH.read_text(encoding="utf-8"))
        except Exception as e:
            print(f"[경고] sector-map-us.json 파싱 실패({e}) — 전부 general 로 진행")
    else:
        print("[경고] config/sector-map-us.json 없음 — 전부 general 로 진행")
    return DEFAULT_SECTOR_MAP


def resolve_sector_us(ticker, sector, industry, smap):
    """
    해결 순서: byTicker → byIndustryPattern → bySectorPattern → default
    한국판 sectorResolver.js 와 같은 철학: '조용한 오분류보다 시끄러운 미분류'.
    sector/industry 를 못 받으면 general + resolved=False (엔진이 unmappedSector 경고).
    """
    import re

    by_ticker = (smap.get("byTicker") or {}).get(ticker)
    if by_ticker:
        st = by_ticker if isinstance(by_ticker, str) else by_ticker.get("sectorType")
        return st, True, "byTicker"

    if industry:
        for rule in smap.get("byIndustryPattern") or []:
            try:
                if re.search(rule["pattern"], industry, re.I):
                    return rule["sectorType"], True, f"industry:{rule['pattern']}"
            except Exception:
                continue

    if sector:
        for rule in smap.get("bySectorPattern") or []:
            try:
                if re.search(rule["pattern"], sector, re.I):
                    return rule["sectorType"], True, f"sector:{rule['pattern']}"
            except Exception:
                continue

    has_class = bool(sector or industry)
    return smap.get("default", "general"), has_class, "default"


# ════════════════════════════════════════════════════════════════
# 1차 소스: yfinance
# ════════════════════════════════════════════════════════════════

def _row(df, names):
    """DataFrame 에서 후보 라벨 중 먼저 있는 행을 과거→최신 순 리스트로 반환."""
    if df is None or getattr(df, "empty", True):
        return None
    for name in names:
        if name in df.index:
            s = df.loc[name]
            # yfinance 는 컬럼이 최신→과거. 과거→최신으로 뒤집습니다.
            cols = list(s.index)[::-1]
            out = []
            for c in cols:
                v = s[c]
                try:
                    v = None if v != v else float(v)  # NaN → None
                except (TypeError, ValueError):
                    v = None
                out.append(v)
            return out
    return None


REV_LABELS = ["Total Revenue", "Operating Revenue", "Revenues"]
NI_LABELS = ["Net Income", "Net Income Common Stockholders",
             "Net Income Including Noncontrolling Interests", "Net Income Continuous Operations"]
OI_LABELS = ["Operating Income", "Total Operating Income As Reported", "EBIT"]
EPS_LABELS = ["Diluted EPS", "Basic EPS"]
EQ_LABELS = ["Stockholders Equity", "Total Equity Gross Minority Interest", "Common Stock Equity"]
LIAB_LABELS = ["Total Liabilities Net Minority Interest", "Total Liabilities"]
ASSET_LABELS = ["Total Assets"]
CA_LABELS = ["Current Assets", "Total Current Assets"]
CL_LABELS = ["Current Liabilities", "Total Current Liabilities"]
SHARES_LABELS = ["Ordinary Shares Number", "Share Issued", "Common Stock Shares Outstanding"]
BUYBACK_LABELS = ["Repurchase Of Capital Stock", "Repurchase Of Common Stock"]
DIV_LABELS = ["Cash Dividends Paid", "Common Stock Dividend Paid", "Dividends Paid"]


def fetch_yf(ticker):
    """yfinance 로 한 종목 수집. 실패 필드는 None."""
    import yfinance as yf

    out = {"_src": {}}
    t = yf.Ticker(ticker)

    # --- info (sector/industry/시장지표). 가장 잘 깨지는 부분이라 따로 감쌉니다.
    info = {}
    try:
        info = t.info or {}
    except Exception as e:
        print(f"    [경고] {ticker} info 실패: {type(e).__name__} {e}")

    out["sector"] = info.get("sector")
    out["industry"] = info.get("industry")
    out["per_info"] = info.get("trailingPE")
    out["pbr_info"] = info.get("priceToBook")
    out["price_info"] = info.get("currentPrice") or info.get("regularMarketPrice")
    out["shares_info"] = info.get("sharesOutstanding")
    out["eps_info"] = info.get("trailingEps")
    out["bvps_info"] = info.get("bookValue")

    # --- 재무제표 3종
    inc = bal = cf = qinc = None
    try:
        inc = t.income_stmt
    except Exception as e:
        print(f"    [경고] {ticker} income_stmt 실패: {e}")
    try:
        bal = t.balance_sheet
    except Exception as e:
        print(f"    [경고] {ticker} balance_sheet 실패: {e}")
    try:
        cf = t.cashflow
    except Exception as e:
        print(f"    [경고] {ticker} cashflow 실패: {e}")
    try:
        qinc = t.quarterly_income_stmt
    except Exception as e:
        print(f"    [경고] {ticker} quarterly_income_stmt 실패: {e}")

    out["revenue"] = _row(inc, REV_LABELS)
    out["netIncome"] = _row(inc, NI_LABELS)
    out["opIncome"] = _row(inc, OI_LABELS)
    out["eps"] = _row(inc, EPS_LABELS)
    out["equity"] = _row(bal, EQ_LABELS)
    out["liabilities"] = _row(bal, LIAB_LABELS)
    out["assets"] = _row(bal, ASSET_LABELS)
    out["currentAssets"] = _row(bal, CA_LABELS)
    out["currentLiab"] = _row(bal, CL_LABELS)
    out["shares"] = _row(bal, SHARES_LABELS)
    out["buyback"] = _row(cf, BUYBACK_LABELS)
    out["dividends"] = _row(cf, DIV_LABELS)
    out["epsQ"] = _row(qinc, EPS_LABELS)
    return out


# ════════════════════════════════════════════════════════════════
# 2차 소스: SEC EDGAR XBRL (companyfacts)
# ════════════════════════════════════════════════════════════════

_SEC_TICKER_MAP = None


def _sec_get(url):
    import urllib.request
    req = urllib.request.Request(url, headers={
        "User-Agent": SEC_UA,
        "Accept-Encoding": "gzip, deflate",
        "Host": url.split("/")[2],
    })
    import gzip, io
    with urllib.request.urlopen(req, timeout=30) as res:
        raw = res.read()
        if res.headers.get("Content-Encoding") == "gzip":
            raw = gzip.GzipFile(fileobj=io.BytesIO(raw)).read()
    return json.loads(raw.decode("utf-8"))


def sec_cik(ticker):
    """티커 → 10자리 CIK. BRK-B 처럼 클래스가 붙은 티커는 SEC 표기(BRK-B)와 대개 일치."""
    global _SEC_TICKER_MAP
    if _SEC_TICKER_MAP is None:
        try:
            data = _sec_get("https://www.sec.gov/files/company_tickers.json")
            _SEC_TICKER_MAP = {v["ticker"].upper(): str(v["cik_str"]).zfill(10) for v in data.values()}
        except Exception as e:
            print(f"  [경고] SEC 티커맵 로드 실패({e}) — SEC 폴백 비활성")
            _SEC_TICKER_MAP = {}
    key = ticker.upper()
    return _SEC_TICKER_MAP.get(key) or _SEC_TICKER_MAP.get(key.replace("-", "."))


def _annual_series(facts, concepts, unit="USD"):
    """
    companyfacts 에서 연간(10-K, FY) 값을 fy → value 로 정리해 과거→최신 리스트 반환.
    같은 fy 가 여러 번(정정공시) 나오면 가장 최근 filed 를 씁니다.
    """
    for cpt in concepts:
        node = ((facts.get("facts", {}).get("us-gaap", {}) or {}).get(cpt) or {})
        units = (node.get("units") or {}).get(unit)
        if not units:
            continue
        best = {}
        for e in units:
            if e.get("form") != "10-K" or e.get("fp") != "FY":
                continue
            fy = e.get("fy")
            if fy is None:
                continue
            # 기간 항목(손익·현금흐름)은 1년 구간만 채택 — 누적/분기 혼입 방지
            if e.get("start"):
                try:
                    d0 = dt.date.fromisoformat(e["start"])
                    d1 = dt.date.fromisoformat(e["end"])
                    if not (300 <= (d1 - d0).days <= 400):
                        continue
                except Exception:
                    continue
            prev = best.get(fy)
            if prev is None or (e.get("filed") or "") >= (prev.get("filed") or ""):
                best[fy] = e
        if best:
            years = sorted(best)
            return [float(best[y]["val"]) for y in years], cpt
    return None, None


def fetch_sec(ticker):
    """SEC XBRL 로 재무 시계열 수집. 실패 시 빈 dict."""
    cik = sec_cik(ticker)
    if not cik:
        return {}
    try:
        facts = _sec_get(f"https://data.sec.gov/api/xbrl/companyfacts/CIK{cik}.json")
    except Exception as e:
        print(f"    [경고] {ticker} SEC companyfacts 실패: {e}")
        return {}

    rev, _ = _annual_series(facts, [
        "RevenueFromContractWithCustomerExcludingAssessedTax",
        "RevenueFromContractWithCustomerIncludingAssessedTax",
        "Revenues", "SalesRevenueNet",
    ])
    ni, _ = _annual_series(facts, ["NetIncomeLoss", "ProfitLoss"])
    oi, _ = _annual_series(facts, ["OperatingIncomeLoss"])
    eq, _ = _annual_series(facts, [
        "StockholdersEquity",
        "StockholdersEquityIncludingPortionAttributableToNoncontrollingInterest",
    ])
    liab, _ = _annual_series(facts, ["Liabilities"])
    assets, _ = _annual_series(facts, ["Assets"])
    ca, _ = _annual_series(facts, ["AssetsCurrent"])
    cl, _ = _annual_series(facts, ["LiabilitiesCurrent"])
    eps, _ = _annual_series(facts, ["EarningsPerShareDiluted", "EarningsPerShareBasicAndDiluted"], unit="USD/shares")
    shares, _ = _annual_series(facts, [
        "WeightedAverageNumberOfDilutedSharesOutstanding",
        "CommonStockSharesOutstanding",
    ], unit="shares")
    buyback, _ = _annual_series(facts, ["PaymentsForRepurchaseOfCommonStock"])
    div, _ = _annual_series(facts, ["PaymentsOfDividendsCommonStock", "PaymentsOfDividends"])

    return {
        "revenue": rev, "netIncome": ni, "opIncome": oi, "equity": eq,
        "liabilities": liab, "assets": assets, "currentAssets": ca, "currentLiab": cl,
        "eps": eps, "shares": shares,
        # SEC 는 유출액을 양수로 기록 → yfinance(음수) 부호에 맞춥니다
        "buyback": [-v for v in buyback] if buyback else None,
        "dividends": [-v for v in div] if div else None,
    }


# ════════════════════════════════════════════════════════════════
# 소스 병합 → 스코어링 필드 산출
# ════════════════════════════════════════════════════════════════

SERIES_KEYS = ["revenue", "netIncome", "opIncome", "eps", "equity", "liabilities",
               "assets", "currentAssets", "currentLiab", "shares", "buyback", "dividends"]


def merge_sources(yf_data, sec_data):
    """yfinance 우선, 결측 시계열만 SEC 로 대체. 어떤 필드를 무엇으로 채웠는지 기록."""
    merged, src = {}, {}
    for k in SERIES_KEYS:
        a = (yf_data or {}).get(k)
        b = (sec_data or {}).get(k)
        if a and any(v is not None for v in a):
            merged[k], src[k] = a, "yf"
        elif b and any(v is not None for v in b):
            merged[k], src[k] = b, "sec"
        else:
            merged[k], src[k] = None, None
    for k in ("sector", "industry", "per_info", "pbr_info", "price_info",
              "shares_info", "eps_info", "bvps_info", "epsQ"):
        merged[k] = (yf_data or {}).get(k)
    return merged, src


def last(series, i=-1):
    if not series:
        return None
    try:
        return series[i]
    except IndexError:
        return None


def build_entry(ticker, m, src, smap, prev_entry):
    """병합된 시계열 → fundamentals.json 한 종목 엔트리."""
    eq = m.get("equity") or []
    ni = m.get("netIncome") or []
    rev = m.get("revenue") or []
    oi = m.get("opIncome") or []
    eps = m.get("eps") or []

    # ── ROE 시계열: 연도별 순이익 ÷ 기말 자본 (한국판과 동일 정의)
    n = min(len(eq), len(ni))
    roe_hist = []
    if n >= 1:
        for i in range(-n, 0):
            roe_hist.append(r1(pct(ni[i], eq[i])))
    roe_hist = [v for v in roe_hist if v is not None]
    roe = roe_hist[-1] if roe_hist else None

    # ── 부채비율 = 총부채 ÷ 자본 × 100 (한국 정의). Liabilities 없으면 자산-자본.
    liab_latest = last(m.get("liabilities"))
    if liab_latest is None:
        a, e = last(m.get("assets")), last(eq)
        liab_latest = (a - e) if (a is not None and e is not None) else None
    debt_raw = r1(pct(liab_latest, last(eq)))

    # ── 유동비율
    cr = r1(pct(last(m.get("currentAssets")), last(m.get("currentLiab"))))

    # ── 영업이익률 추세
    k = min(len(oi), len(rev))
    margins = []
    if k >= 2:
        for i in range(-k, 0):
            margins.append(pct(oi[i], rev[i]))
    trend, trend_pp = margin_trend(margins)

    # ── 성장률
    rev_g = r1(growth_pct(last(rev), last(rev, -2))) if len(rev) >= 2 else None
    eps_g = r1(growth_pct(last(eps), last(eps, -2))) if len(eps) >= 2 else None

    # ── 주주환원: 최근 3년 중 배당 또는 자사주매입이 있으면 True
    def any_outflow(series):
        if not series:
            return False
        return any(v is not None and abs(v) > 0 for v in series[-3:])

    has_return = any_outflow(m.get("dividends")) or any_outflow(m.get("buyback"))
    shareholder_return = True if has_return else (False if (m.get("dividends") or m.get("buyback")) else None)

    # ── 업종
    sector_type, resolved, how = resolve_sector_us(ticker, m.get("sector"), m.get("industry"), smap)
    if sector_type in NO_CURRENT_RATIO_SECTORS:
        cr = None  # criteria 의 excluded 처리와 중복이지만, 애초에 넣지 않는 편이 안전

    # ── 주당 지표 (collect.js 가 매일 종가와 나눠 per/pbr 재계산)
    eps_ttm = None
    epsq = m.get("epsQ")
    if epsq and len([v for v in epsq if v is not None]) >= 4:
        vals = [v for v in epsq if v is not None][-4:]
        eps_ttm = r1(sum(vals), 2)
    if eps_ttm is None:
        eps_ttm = r1(m.get("eps_info"), 2)
    if eps_ttm is None:
        eps_ttm = r1(last(eps), 2)

    # bvps 는 info.bookValue(직전 '분기' 자본 기준)를 우선합니다. 연말 자본으로 계산하면
    # Yahoo 가 주는 priceToBook 과 값이 어긋나(분기 시차) 같은 파일 안에서 PBR 이 두 개가 됩니다.
    bvps = r1(m.get("bvps_info"), 2)
    if bvps is None:
        shares = last(m.get("shares")) or m.get("shares_info")
        bvps = r1(safe_div(last(eq), shares), 2)

    per = r1(m.get("per_info"), 2)
    pbr = r1(m.get("pbr_info"), 2)
    price = m.get("price_info")
    if per is None and price and eps_ttm and eps_ttm > 0:
        per = r1(price / eps_ttm, 2)
    if pbr is None and price and bvps and bvps > 0:
        pbr = r1(price / bvps, 2)

    entry = {
        "roe": roe,
        "roeHistory5y": roe_hist[-5:] if roe_hist else None,
        "debtRatio": None if sector_type in ("financial",) else debt_raw,
        "debtRatioRaw": debt_raw,
        "currentRatio": cr,
        "operatingMarginTrend": trend,
        "operatingMarginTrendPP": trend_pp,
        "revenueGrowthYoY": rev_g,
        "epsGrowthRate": eps_g,
        "buybackOrDividendHistory": shareholder_return,
        "perRelative": None,          # 섹터 PER 산출 후 2패스에서 채움
        "per": per,
        "pbr": pbr,
        "epsTtm": eps_ttm,
        "bvps": bvps,
        "sectorType": sector_type,
        "sectorResolved": resolved,
        "sectorSource": how,
        "yfSector": m.get("sector"),
        "yfIndustry": m.get("industry"),
        "_source": "yfinance+SEC XBRL",
        "_asOf": dt.date.today().isoformat(),
        "_fields": {k: v for k, v in src.items() if v},
    }

    # ── 보존 규칙: 이번에 못 받은 필드는 기존 값을 지우지 않습니다.
    if prev_entry:
        kept = []
        for k, v in list(entry.items()):
            if k == "perRelative":
                continue  # 2패스(섹터 PER)에서 다시 채우므로 여기서 보존하면 이력이 혼탁해집니다
            if v is None and prev_entry.get(k) is not None and not k.startswith("_"):
                entry[k] = prev_entry[k]
                kept.append(k)
        if kept:
            entry["_kept"] = kept
    return entry


# ════════════════════════════════════════════════════════════════
# 메인
# ════════════════════════════════════════════════════════════════

def load_us_tickers(only=None):
    wl = json.loads(WATCHLIST_PATH.read_text(encoding="utf-8"))
    codes = [t["code"] for t in wl.get("tickers", []) if (t.get("market") or "KR") == "US"]
    if only:
        want = {c.strip().upper() for c in only.split(",") if c.strip()}
        codes = [c for c in codes if c.upper() in want]
    return codes


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--only", help="쉼표로 구분한 티커만 수집")
    ap.add_argument("--dry-run", action="store_true", help="파일 저장 안 함")
    ap.add_argument("--no-sec", action="store_true", help="SEC 폴백 비활성")
    ap.add_argument("--selftest", action="store_true", help="네트워크 없이 계산식 검증")
    args = ap.parse_args()

    if args.selftest:
        return selftest()

    smap = load_sector_map()
    tickers = load_us_tickers(args.only)
    if not tickers:
        print("US 종목이 watchlist 에 없습니다.")
        return 0

    fund = json.loads(FUND_PATH.read_text(encoding="utf-8"))
    by_ticker = fund.setdefault("byTicker", {})

    print(f"미국 재무 수집 시작: {len(tickers)}종목 (SEC 폴백 {'off' if args.no_sec else 'on'})")
    entries, failed = {}, []

    for i, tk in enumerate(tickers, 1):
        print(f"[{i}/{len(tickers)}] {tk}")
        yf_data, sec_data = None, None
        try:
            yf_data = fetch_yf(tk)
        except Exception as e:
            print(f"    [경고] {tk} yfinance 전체 실패: {type(e).__name__} {e}")

        need_sec = (not args.no_sec) and (
            yf_data is None
            or not (yf_data.get("equity") and yf_data.get("netIncome") and yf_data.get("revenue"))
        )
        if need_sec:
            print(f"    → SEC XBRL 폴백 시도")
            try:
                sec_data = fetch_sec(tk)
            except Exception as e:
                print(f"    [경고] {tk} SEC 실패: {type(e).__name__} {e}")

        m, src = merge_sources(yf_data, sec_data)
        entry = build_entry(tk, m, src, smap, by_ticker.get(tk))
        entries[tk] = entry

        filled = sum(1 for k in ("roe", "debtRatioRaw", "operatingMarginTrend",
                                 "revenueGrowthYoY", "epsGrowthRate", "epsTtm", "bvps")
                     if entry.get(k) is not None)
        print(f"    {entry['sectorType']:<10} ROE {entry['roe']}  부채 {entry['debtRatioRaw']}  "
              f"EPS(TTM) {entry['epsTtm']}  BPS {entry['bvps']}  채움 {filled}/7")
        if filled <= 2:
            failed.append(tk)

        if i < len(tickers):
            time.sleep(SLEEP_SEC)

    # ── 2패스: 섹터 PER 중위값 → perRelative
    #  같은 sectorType 그룹의 PER 중위값을 기준으로 씁니다. 표본이 3종목 미만이면
    #  대표성이 없어 산출하지 않습니다(추정값으로 점수를 만들지 않는다는 원칙).
    groups = {}
    for tk, e in entries.items():
        if e.get("per") and e["per"] > 0:
            groups.setdefault(e["sectorType"], []).append(e["per"])
    sector_per = {k: r1(median(v), 2) for k, v in groups.items() if len(v) >= 3}
    for tk, e in entries.items():
        sp = sector_per.get(e["sectorType"])
        e["sectorPer"] = sp
        if sp and e.get("per"):
            e["perRelative"] = r1(e["per"] / sp, 2)
        elif by_ticker.get(tk, {}).get("perRelative") is not None:
            e["perRelative"] = by_ticker[tk]["perRelative"]

    print(f"\n섹터 PER 중위값: {json.dumps(sector_per, ensure_ascii=False)}")
    if failed:
        print(f"⚠ 수집 부진 {len(failed)}종목: {', '.join(failed)}")

    if args.dry_run:
        print("\n--dry-run: 저장 생략")
        print(json.dumps({k: entries[k] for k in list(entries)[:2]}, ensure_ascii=False, indent=2))
        return 0

    by_ticker.update(entries)
    fund["updatedAt"] = dt.date.today().isoformat()
    fund["usUpdatedAt"] = dt.date.today().isoformat()
    fund["usSectorPer"] = sector_per
    FUND_PATH.write_text(json.dumps(fund, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"\n완료: {len(entries)}종목 → config/fundamentals.json")
    return 0


# ════════════════════════════════════════════════════════════════
# 셀프테스트 (네트워크 불필요)
# ════════════════════════════════════════════════════════════════

def selftest():
    ok = True

    def check(name, got, want):
        nonlocal ok
        good = got == want
        ok = ok and good
        print(f"  {'OK ' if good else 'FAIL'} {name}: {got} (기대 {want})")

    print("계산식 검증")
    check("pct(10,100)", r1(pct(10, 100)), 10.0)
    check("pct 자본잠식 → None", pct(10, -5), None)
    check("growth 적자기저 → None", growth_pct(10, -5), None)
    check("growth(110,100)", r1(growth_pct(110, 100)), 10.0)
    check("margin_trend PP 2.2 → 0.44", margin_trend([10.0, 11.0, 12.2])[0], 0.44)
    check("margin_trend clamp", margin_trend([1.0, 30.0])[0], 1.0)
    check("median [1,3,2]", median([1, 3, 2]), 2)

    print("\n엔트리 생성 검증 (일반 제조업)")
    m = {
        "revenue": [1000.0, 1100.0, 1200.0],
        "netIncome": [100.0, 120.0, 150.0],
        "opIncome": [100.0, 121.0, 144.0],   # 마진 10.0 → 11.0 → 12.0 (+2.0%p)
        "eps": [1.0, 1.2, 1.5],
        "equity": [1000.0, 1100.0, 1250.0],
        "liabilities": [500.0, 550.0, 625.0],
        "assets": [1500.0, 1650.0, 1875.0],
        "currentAssets": [400.0], "currentLiab": [200.0],
        "shares": [100.0], "dividends": [-10.0, -10.0, -10.0], "buyback": None,
        "sector": "Technology", "industry": "Semiconductors",
        "per_info": 20.0, "pbr_info": 3.0, "price_info": 30.0,
        "shares_info": 100.0, "eps_info": 1.5, "bvps_info": 12.5, "epsQ": None,
    }
    e = build_entry("TEST", m, {"revenue": "yf"}, DEFAULT_SECTOR_MAP, None)
    check("roe = 150/1250", e["roe"], 12.0)
    check("roeHistory5y", e["roeHistory5y"], [10.0, 10.9, 12.0])
    check("debtRatioRaw = 625/1250", e["debtRatioRaw"], 50.0)
    check("currentRatio", e["currentRatio"], 200.0)
    check("operatingMarginTrendPP", e["operatingMarginTrendPP"], 2.0)
    check("operatingMarginTrend", e["operatingMarginTrend"], 0.4)
    check("revenueGrowthYoY", e["revenueGrowthYoY"], 9.1)
    check("epsGrowthRate", e["epsGrowthRate"], 25.0)
    check("주주환원", e["buybackOrDividendHistory"], True)
    check("bvps = 1250/100", e["bvps"], 12.5)
    check("sectorType", e["sectorType"], "general")

    print("\n금융업 분기 검증")
    smap = {
        "default": "general", "byTicker": {},
        "byIndustryPattern": [{"pattern": "Banks", "sectorType": "financial"}],
        "bySectorPattern": [],
    }
    mf = dict(m, industry="Banks - Diversified", liabilities=[9000.0, 10000.0, 11000.0],
              equity=[1000.0, 1050.0, 1100.0], netIncome=[100.0, 110.0, 120.0])
    ef = build_entry("BANK", mf, {}, smap, None)
    check("sectorType", ef["sectorType"], "financial")
    check("debtRatio(일반기준용) None", ef["debtRatio"], None)
    check("debtRatioRaw = 11000/1100", ef["debtRatioRaw"], 1000.0)
    check("currentRatio 제외", ef["currentRatio"], None)

    print("\n기존값 보존 검증")
    m2 = dict(m, equity=None, netIncome=None, revenue=None, opIncome=None, eps=None)
    prev = {"roe": 9.9, "revenueGrowthYoY": 4.4, "perRelative": 0.8}
    e2 = build_entry("KEEP", m2, {}, DEFAULT_SECTOR_MAP, prev)
    check("결측 시 기존 roe 유지", e2["roe"], 9.9)
    check("_kept 기록", "roe" in (e2.get("_kept") or []), True)

    print("\nSEC 부호 정규화 검증")
    check("SEC 유출 양수 → 음수", [-v for v in [1000.0]], [-1000.0])

    print("\n" + ("전체 통과" if ok else "실패 항목 있음"))
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
