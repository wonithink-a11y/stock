#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""미국 S&P500 PIT 재무 항목 매핑 — us-map-1.0 (감사: docs/control/미국-재무매핑감사-2026-09-26.md).

A3e(a3e_account_map.py)와 같은 규율: **정의를 결과 전에 동결**한다. 이 파일을 바꾸면 이후 결과가 다시 태어나므로
바꿀 때는 MAP_VERSION 을 올리고 감사를 다시 돈다. 수익률은 여기서 보지 않는다.

입력: data/us-pit/raw/edgar_facts/<cik>.json.gz(SEC companyfacts 원본) · data/us-pit/raw/yf|tiingo_prices(분할 이벤트)
PIT: 값은 **filed 다음 날부터** 쓴다. 같은 회계기간말(end)의 정정은 그 filed 부터 새 값(과거 소급 없음).

자본(book) — 지배주주 몫, 우선주 포함(한국 PBR 의 '지배 자본총계'와 같은 쪽)
  1. us-gaap:StockholdersEquity
  2. StockholdersEquityIncludingPortionAttributableToNoncontrollingInterest − MinorityInterest(같은 end)
     (CAT·PG·T·VZ 등은 1 이 비차원 값으로 없다 — 2026-09-26 실측 15 CIK). MI 가 그 end 에 없으면 포함값 그대로(표시)
  3. PartnersCapital · MembersEquity · ifrs-full:EquityAttributableToOwnersOfParent
주식수 — **모든 보통주 클래스 합계**(시가총액 = 가격 × 전체 주식수, 야후·S&P 관례)
  CIK 별로 dei:EntityCommonStockSharesOutstanding(표지) → us-gaap:CommonStockSharesOutstanding → WeightedAverageNumberOfSharesOutstandingBasic.
  단 dei/CSO 는 그 CIK 의 이력 중앙 비율(값 ÷ 같은 무렵 WAB)이 [0.9, 1.1] 밖이면 **그 CIK 에서 버린다** — 복수 클래스
  회사가 한 클래스만 비차원으로 적는 경우(부분값)를 막는다. WAB 는 NI÷EPS 와 일치함을 실측(GOOGL·META·CMCSA·UPS·NWS 등).
  2019 표지 태깅 규칙 뒤로 복수 증권 등록사는 dei 를 차원으로만 적어 companyfacts 에서 빠진다(Ford·Comcast·Visa·Accenture…).
분할: 가격은 조정 종가다. 공시 주식수는 **filed 시점 단위**(filed 전 분할은 재무제표가 소급 반영).
  ★ 야후 splits 열에는 **분사(spin-off) 가격 조정도 섞여 있다**(DD 1.487·0.4725·2.39, HON 0.9535 — 2026-09-26 실측).
  분사 계수는 과거 가격만 바꾸고 주식수는 안 바꾼다. 그래서 둘을 가른다 — 깨끗한 비율(k·1/k·3:2·5:4·4:3·5:2)만 진짜 분할.
  시가총액(t) = 조정종가(t) × 주식수 × Π(t 이후 모든 계수) × Π(filed < d ≤ t 인 진짜 분할). 전부 진짜 분할이면
  Π(filed 이후 분할) 로 줄어든다(유도: 감사 문서 §2).
주식수 출처 수동 지정: SHARE_SOURCE_OVERRIDE(근거 필수) — 기준(WAB) 자체가 단위 오류라 비율 검사가 거꾸로 판정한 경우.
신선도: end 가 기준일 − STALE_DAYS 보다 오래면 없음(None — 0 이 아니다, 교훈 57).
주식수 이상값: 한 공시의 단위 오타(×1000 · ×0.001 — AJG·EIX·GRMN·PKG·YUM·CCL·COP·NTAP 실측)와 분사 직후 자리표시 0 은
  같은 출처의 앞뒤 ±730일 값 중앙값과 SH_OUTLIER 배 넘게 다르거나 SH_MIN 미만이면 버린다(합병 ×2 는 살아남는다).
단위 배수: BRK 는 공시 주식수가 A주 환산인데 가격은 B주(1/1500) → SHARE_MULT.
"""
import gzip
import json
from functools import lru_cache
from pathlib import Path

import pandas as pd

MAP_VERSION = "us-map-1.0"
HERE = Path(__file__).resolve().parent
RAW = HERE / "data" / "us-pit" / "raw"
FORMS = {"10-K", "10-Q", "10-K/A", "10-Q/A", "20-F", "40-F", "10-KT", "10-QT"}
FILED_FROM = "2014-01-01"
STALE_DAYS = 400
RATIO_BAND = (0.9, 1.1)
SH_MIN = 1e6
SH_OUTLIER = 3.0
SHARE_MULT = {(1067983, "BRK-B"): 1500.0}   # Berkshire: WAB 는 A주 환산, B주 = A주 1/1500(2010-01 분할 이후)
# COP: WAB 가 2016~2020 공시에서 천 주 단위(1.2M = 실제 12억 주)라 dei/WAB 비율 960 → 비율 검사가 옳은 dei 를 버렸다
SHARE_SOURCE_OVERRIDE = {1163165: ("dei",)}
CLEAN_SPLITS = (1.5, 1.25, 4 / 3, 2.5)
# 야후가 병합 분할과 분사 조정을 한 계수로 합친 사건 — 주식수 몫만 손으로 준다(감사 V9 에서 발견)
SPLIT_SHARE_PART = {("DD", "2019-06-03"): 1 / 3}   # 0.4725 = 1:3 병합 × Corteva 분사 조정

EQUITY_PRIMARY = ("us-gaap", "StockholdersEquity")
EQUITY_INCL_NCI = ("us-gaap", "StockholdersEquityIncludingPortionAttributableToNoncontrollingInterest")
MINORITY = ("us-gaap", "MinorityInterest")
EQUITY_OTHER = (("us-gaap", "PartnersCapital"), ("us-gaap", "MembersEquity"), ("ifrs-full", "EquityAttributableToOwnersOfParent"))
SH_DEI = ("dei", "EntityCommonStockSharesOutstanding")
SH_CSO = ("us-gaap", "CommonStockSharesOutstanding")
SH_WAB = ("us-gaap", "WeightedAverageNumberOfSharesOutstandingBasic")


def _records(j, tax, tag, instant):
    """(end, filed, val, days) 리스트 — 정기보고서만, 비차원 값만(companyfacts 가 원래 비차원만 준다)."""
    t = j.get("facts", {}).get(tax, {}).get(tag)
    if not t:
        return []
    out = []
    for unit, xs in t["units"].items():
        for x in xs:
            if x.get("form") not in FORMS or x.get("filed", "") < FILED_FROM or x.get("val") is None:
                continue
            if instant and "start" in x:
                continue
            days = 0 if "start" not in x else (pd.Timestamp(x["end"]) - pd.Timestamp(x["start"])).days
            out.append((x["end"], x["filed"], float(x["val"]), days))
    return sorted(set(out))


def drop_share_outliers(recs):
    """단위 오타·자리표시 값을 버린다 — 같은 출처의 ±730일 이웃(자기 제외) 중앙값 대비 SH_OUTLIER 배 밖, 또는 SH_MIN 미만."""
    keep = []
    for i, r in enumerate(recs):
        if r[2] < SH_MIN:
            continue
        e = pd.Timestamp(r[0])
        nb = [x[2] for j, x in enumerate(recs) if j != i and x[2] >= SH_MIN and abs((pd.Timestamp(x[0]) - e).days) <= 730]
        if len(nb) >= 3:
            med = float(pd.Series(nb).median())
            if not (1 / SH_OUTLIER <= r[2] / med <= SH_OUTLIER):
                continue
        keep.append(r)
    return keep


@lru_cache(maxsize=None)
def facts(cik):
    f = RAW / "edgar_facts" / f"{int(cik)}.json.gz"
    if not f.exists():
        return None
    j = json.loads(gzip.decompress(f.read_bytes()))
    return {
        "se": _records(j, *EQUITY_PRIMARY, True), "sen": _records(j, *EQUITY_INCL_NCI, True), "mi": _records(j, *MINORITY, True),
        "eqo": [r for tt in EQUITY_OTHER for r in _records(j, *tt, True)],
        "dei": drop_share_outliers(_records(j, *SH_DEI, True)), "cso": drop_share_outliers(_records(j, *SH_CSO, True)),
        "wab": drop_share_outliers(_records(j, *SH_WAB, False)),
    }


def pit(recs, asof):
    """asof(Timestamp) 에 알 수 있던 최신 값: filed < asof 인 것 중 end 최대 → 그 end 의 최신 filed → 짧은 기간 우선.
    (end, filed, val) 또는 None. filed '다음 날부터' 이므로 filed < asof."""
    a = asof.strftime("%Y-%m-%d")
    c = [r for r in recs if r[1] < a]
    if not c:
        return None
    e = max(r[0] for r in c)
    if pd.Timestamp(e) < asof - pd.Timedelta(STALE_DAYS, unit="D"):
        return None
    same = [r for r in c if r[0] == e]
    f = max(r[1] for r in same)
    r = min((r for r in same if r[1] == f), key=lambda r: r[3])
    return r[0], r[1], r[2]


def equity(cik, asof):
    """(값, 출처) 또는 (None, 사유)."""
    F = facts(cik)
    if F is None:
        return None, "facts 없음"
    p = pit(F["se"], asof)
    if p:
        return p[2], "SE"
    p = pit(F["sen"], asof)
    if p:
        mi = [r for r in F["mi"] if r[0] == p[0] and r[1] < asof.strftime("%Y-%m-%d")]
        if mi:
            return p[2] - max(mi, key=lambda r: r[1])[2], "SEN-MI"
        return p[2], "SEN(MI없음)"
    p = pit(F["eqo"], asof)
    if p:
        return p[2], "OTHER"
    return None, "자본 없음"


@lru_cache(maxsize=None)
def share_sources(cik):
    """이 CIK 에서 믿을 수 있는 주식수 출처 순서. dei/CSO 는 WAB 대비 이력 중앙 비율이 RATIO_BAND 안일 때만."""
    F = facts(cik)
    if F is None:
        return (), {}
    if int(cik) in SHARE_SOURCE_OVERRIDE:
        return SHARE_SOURCE_OVERRIDE[int(cik)], {"override": 1.0}
    wab = F["wab"]
    ratios, keep = {}, []
    for k in ("dei", "cso"):
        rs = []
        for end, filed, val, _ in F[k]:
            w = pit(wab, pd.Timestamp(filed) + pd.Timedelta(1, unit="D"))
            if w and w[2] > 0 and abs((pd.Timestamp(w[0]) - pd.Timestamp(end)).days) <= 200:
                rs.append(val / w[2])
        med = float(pd.Series(rs).median()) if rs else None
        ratios[k] = med
        if F[k] and (med is None or RATIO_BAND[0] <= med <= RATIO_BAND[1]):
            keep.append(k)
    if wab:
        keep.append("wab")
    return tuple(keep), ratios


def shares(cik, asof):
    """(주식수 원값, filed, 출처) 또는 (None, None, 사유)."""
    order, _ = share_sources(cik)
    F = facts(cik)
    for k in order:
        p = pit(F[k], asof)
        if p and p[2] > 0:
            return p[2], p[1], k
    return None, None, "주식수 없음" if F else "facts 없음"


@lru_cache(maxsize=None)
def split_events(price_symbol, source):
    """[(date, ratio)] — yfinance splits 열 · Tiingo splitFactor. ratio 2 = 1주가 2주로."""
    if source == "yfinance":
        f = RAW / "yf" / f"{price_symbol}.parquet"
        if not f.exists():
            return ()
        d = pd.read_parquet(f).reset_index()
        d = d[d["splits"].fillna(0) > 0]
        return tuple((pd.Timestamp(x).tz_localize(None).normalize(), float(r)) for x, r in zip(d["date"], d["splits"]))
    f = RAW / "tiingo_prices" / f"{price_symbol}.json.gz"
    if not f.exists():
        return ()
    js = json.loads(gzip.decompress(f.read_bytes())) or []
    return tuple((pd.Timestamp(x["date"][:10]), float(x["splitFactor"])) for x in js if x.get("splitFactor") not in (None, 1, 1.0))


def share_mult(cik, price_symbol):
    return SHARE_MULT.get((int(cik), price_symbol), 1.0)


def is_clean_split(r):
    """진짜 주식 분할 비율인가 — 정수 k, 1/k, 또는 3:2·5:4·4:3·5:2. 분사 가격 조정(1.487 등)은 아니다."""
    for x in (r, 1 / r):
        if x >= 1.5 and abs(x - round(x)) / x < 0.005:
            return True
    return any(abs(r - c) / c < 0.005 or abs(1 / r - c) / c < 0.005 for c in CLEAN_SPLITS)


def mcap_factor(price_symbol, source, filed, t):
    """시가총액(t) = 조정종가(t) × 공시 주식수 × 이 값."""
    f, fd, t = 1.0, pd.Timestamp(filed), pd.Timestamp(t)
    for d, r in split_events(price_symbol, source):
        if d > t:
            f *= r                          # 조정종가를 t 시점 원가로 되돌린다(분할·분사 모두)
        elif d > fd:
            part = SPLIT_SHARE_PART.get((price_symbol, d.strftime("%Y-%m-%d")))
            if part is not None:
                f *= part                   # 합쳐진 사건: 주식수 몫만
            elif is_clean_split(r):
                f *= r                      # filed 뒤 진짜 분할만 주식수를 바꾼다
    return f


def selftest():
    recs = [("2020-03-31", "2020-05-01", 10.0, 0), ("2020-06-30", "2020-08-01", 11.0, 0), ("2020-06-30", "2020-09-15", 12.0, 0)]
    assert pit(recs, pd.Timestamp("2020-05-01")) is None, "filed 당일은 아직 못 쓴다"
    assert pit(recs, pd.Timestamp("2020-05-02"))[2] == 10.0
    assert pit(recs, pd.Timestamp("2020-08-15"))[2] == 11.0, "정정 전"
    assert pit(recs, pd.Timestamp("2020-09-16"))[2] == 12.0, "정정은 그 filed 부터"
    assert pit(recs, pd.Timestamp("2021-12-31")) is None, "400일 넘게 낡으면 없음"
    dur = [("2020-06-30", "2020-08-01", 100.0, 181), ("2020-06-30", "2020-08-01", 90.0, 91)]
    assert pit(dur, pd.Timestamp("2020-09-01"))[2] == 90.0, "같은 end·filed 면 짧은 기간(분기)"
    sh = [("2020-%02d-28" % m, "2020-%02d-28" % m, v, 0) for m, v in zip(range(1, 8), [5e8, 5e8, 5e11, 5e8, 5e5, 5e8, 1e9])]
    kept = [r[2] for r in drop_share_outliers(sh)]
    assert kept == [5e8, 5e8, 5e8, 5e8, 1e9], kept   # ×1000 오타·1M 미만 버림, 합병 ×2 는 남김
    assert share_mult(1067983, "BRK-B") == 1500.0 and share_mult(320193, "AAPL") == 1.0
    assert all(is_clean_split(x) for x in (2, 4, 7, 20, 0.5, 1 / 3, 0.1, 1.5, 1.25)), "진짜 분할"
    assert not any(is_clean_split(x) for x in (1.487, 0.4725, 2.39, 0.9535)), "분사 가격 조정(야후 splits 열)"
    print("us_account_map selftest: 통과")


if __name__ == "__main__":
    selftest()
