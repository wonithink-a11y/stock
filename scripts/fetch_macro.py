#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
매크로 지표 수집기 — FRED(무료·무키 CSV) + Stooq(무료) + Yahoo Finance(무료)에서
값을 받아 docs/data/macro.json 을 생성한다. 표준 라이브러리만 사용(설치 불필요).

각 지표는 현재값 + 신호등 + '이력(history, 스파크라인용)' + '다구간 변화율
(changes: 1일/30일/90일/180일/365일 전 대비, 캘린더일 기준 - 휴장일은 직전
거래일 값으로 자동 대체)'을 함께 저장한다.
지표별 try/except 로 감싸 하나가 실패해도 나머지는 정상 기록한다.
GitHub Actions(인터넷 개방) 러너에서 매일 1회 실행하는 용도.
"""
import json
import os
import re
import ssl
import sys
import urllib.request
from datetime import date, datetime, timedelta, timezone

UA = "Mozilla/5.0 (macro-fetch; +https://github.com)"
CTX = ssl.create_default_context()
OUT = "docs/data/macro.json"


def http_get(url, timeout=20):
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=timeout, context=CTX) as r:
        return r.read().decode("utf-8", "replace")


def fred(series):
    """FRED CSV -> [(YYYY-MM-DD, float), ...] (결측 '.' 제외)."""
    txt = http_get(
        "https://fred.stlouisfed.org/graph/fredgraph.csv?id=" + series)
    out = []
    for line in txt.splitlines()[1:]:
        p = line.split(",")
        if len(p) < 2:
            continue
        d, v = p[0].strip(), p[-1].strip()
        if not v or v == ".":
            continue
        try:
            out.append((d, float(v)))
        except ValueError:
            continue
    return out


DIAG = []  # 소스별 성공/실패 기록 (macro.json 에 남겨 원인 추적)


def stooq_daily(sym):
    """Stooq 일봉 CSV -> [(date, close), ...]. .com 실패 시 .pl 재시도."""
    last = None
    for host in ("https://stooq.com", "https://stooq.pl"):
        try:
            txt = http_get("%s/q/d/l/?s=%s&i=d" % (host, sym))
            out = []
            for line in txt.splitlines()[1:]:
                p = line.split(",")
                if len(p) < 5:
                    continue
                try:
                    out.append((p[0], float(p[4])))
                except ValueError:
                    continue
            if len(out) > 20:
                return out
            last = "행 부족(%d) - 차단/빈응답 의심" % len(out)
        except Exception as e:
            last = "%s: %s" % (type(e).__name__, e)
    raise RuntimeError("stooq %s" % last)


def yahoo_daily(sym):
    """Yahoo Finance chart API -> [(date, close), ...] (무료·무키 대체 소스)."""
    last = None
    for host in ("query1", "query2"):
        try:
            txt = http_get(
                "https://%s.finance.yahoo.com/v8/finance/chart/%s?range=2y&interval=1d" % (host, sym))
            j = json.loads(txt)
            res = j["chart"]["result"][0]
            ts = res["timestamp"]
            closes = res["indicators"]["quote"][0]["close"]
            out = []
            for t, c in zip(ts, closes):
                if c is None:
                    continue
                out.append((datetime.fromtimestamp(t, timezone.utc).date().isoformat(), float(c)))
            if len(out) > 20:
                return out
            last = "행 부족(%d)" % len(out)
        except Exception as e:
            last = "%s: %s" % (type(e).__name__, e)
    raise RuntimeError("yahoo %s" % last)


def naver_daily(symbol, count=500):
    """네이버 차트 API(무인증, EUC-KR XML) -> [(YYYY-MM-DD, close), ...].
    KOSPI200처럼 Stooq·Yahoo에 신뢰할 만한 이력이 없는 한국 지수용
    (실측: Yahoo ^KS200 은 2y range 요청에도 유효 종가가 1개뿐이었다)."""
    xml = http_get("https://fchart.stock.naver.com/sise.nhn?symbol=%s&timeframe=day"
                    "&count=%d&requestType=0" % (symbol, count))
    out = []
    for m in re.finditer(r'<item data="([^"]+)"\s*/>', xml):
        p = m.group(1).split("|")
        if len(p) < 5 or len(p[0]) != 8:
            continue
        try:
            out.append(("%s-%s-%s" % (p[0][:4], p[0][4:6], p[0][6:8]), float(p[4])))
        except ValueError:
            continue
    if len(out) <= 20:
        raise RuntimeError("naver %s 행 부족(%d)" % (symbol, len(out)))
    return out


def price_series(stooq_sym, yahoo_sym, label):
    """Stooq → Yahoo 순으로 시도. 어느 소스가 됐는지 DIAG 에 기록."""
    errors = []
    for name, fn, arg in (("stooq", stooq_daily, stooq_sym), ("yahoo", yahoo_daily, yahoo_sym)):
        try:
            rows = fn(arg)
            DIAG.append("%s: %s OK (%d행)" % (label, name, len(rows)))
            return rows
        except Exception as e:
            errors.append("%s=%s" % (name, e))
    DIAG.append("%s: 전 소스 실패 (%s)" % (label, " | ".join(errors)))
    raise RuntimeError("%s 전 소스 실패" % label)


def last(obs):
    return obs[-1] if obs else (None, None)


def ago(obs, n):
    if not obs:
        return None
    return obs[max(0, len(obs) - 1 - n)][1]


def pct_change(new, old):
    return None if not old else (new / old - 1.0) * 100.0


def weekly(obs, cap=80, step=5, nd=4):
    """일간 시계열을 주간(step=5)으로 솎아 최근 cap개만 [[date,val],...]."""
    if not obs:
        return []
    sl = obs[-cap * step:] if len(obs) > cap * step else obs
    picked = sl[::step]
    if picked and picked[-1][0] != sl[-1][0]:
        picked.append(sl[-1])
    return [[d, round(v, nd)] for d, v in picked]


def monthly(obs, cap=24, nd=2):
    return [[d, round(v, nd)] for d, v in obs[-cap:]]


def value_asof(obs, target_date):
    """obs(오름차순 (date,value))에서 target_date 이하 최신 값 - 그 날짜에
    거래·발표가 없으면(주말·휴장·비영업일) 직전 값을 쓴다. 없으면 None."""
    best = None
    for d, v in obs:
        if d <= target_date:
            best = v
        else:
            break
    return best


HORIZONS = (("d1", 1), ("d30", 30), ("d90", 90), ("d180", 180), ("d365", 365))


def horizon_changes(obs, kind):
    """1/30/90/180/365일(캘린더 기준) 전 대비 변화 dict.
    kind='pct': 상대 %변화(가격·지수류). kind='pp': 절대 포인트차(금리·
    스프레드·비율류, %p 단위 - bp가 아니라 %p임에 주의). 데이터가 그 구간
    만큼 없으면 해당 항목은 None(지어내지 않음)."""
    if not obs:
        return {}
    ld, v = last(obs)
    ld_date = date.fromisoformat(ld)
    out = {}
    for key, days in HORIZONS:
        old = value_asof(obs, (ld_date - timedelta(days=days)).isoformat())
        if old is None or old == 0:
            out[key] = None
        elif kind == "pct":
            out[key] = round((v / old - 1.0) * 100.0, 2)
        else:
            out[key] = round(v - old, 3)
    return out


def ind(key, value, display, as_of, signal, history=None, changes=None, change_kind=None):
    o = {"key": key, "value": value, "display": display,
         "asOf": as_of, "signal": signal}
    if history:
        o["history"] = history
    if changes:
        o["changes"] = changes
        o["changeUnit"] = "%p" if change_kind == "pp" else "%"
    return o


def collect():
    items = []

    # 1) 일드커브 10Y-2Y (%)
    try:
        obs = fred("T10Y2Y")
        d, v = last(obs)
        sig = "green" if v > 0.5 else ("yellow" if v >= 0 else "red")
        items.append(ind("yieldcurve", round(v, 2),
                         ("+%.2f" % v if v >= 0 else "%.2f" % v) + "%p", d, sig,
                         weekly(obs), horizon_changes(obs, "pp"), "pp"))
    except Exception as e:
        print("yieldcurve fail:", e, file=sys.stderr)

    # 2) 하이일드 스프레드 (%)
    try:
        obs = fred("BAMLH0A0HYM2")
        d, v = last(obs)
        sig = "green" if v < 3.5 else ("yellow" if v < 5 else "red")
        items.append(ind("hyspread", round(v, 2), "%.2f%%" % v, d, sig,
                         weekly(obs), horizon_changes(obs, "pp"), "pp"))
    except Exception as e:
        print("hyspread fail:", e, file=sys.stderr)

    # 3) VIX
    try:
        obs = fred("VIXCLS")
        d, v = last(obs)
        sig = "green" if v < 20 else ("yellow" if v < 30 else "red")
        items.append(ind("vix", round(v, 1), "%.1f" % v, d, sig, weekly(obs),
                         horizon_changes(obs, "pp"), "pp"))
    except Exception as e:
        print("vix fail:", e, file=sys.stderr)

    # 4) M2 유동성 전년비 (%) — 월간
    try:
        obs = fred("M2SL")
        d, v = last(obs)
        yoy = pct_change(v, ago(obs, 12))
        sig = "green" if yoy > 3 else ("yellow" if yoy >= 0 else "red")
        yoy_series = [(obs[i][0], round(pct_change(obs[i][1], obs[i - 12][1]), 2))
                      for i in range(12, len(obs))]
        items.append(ind("liquidity", round(yoy, 1),
                         ("+%.1f" % yoy if yoy >= 0 else "%.1f" % yoy) + "% YoY",
                         d, sig, yoy_series[-24:], horizon_changes(yoy_series, "pp"), "pp"))
    except Exception as e:
        print("liquidity fail:", e, file=sys.stderr)

    # 5) 달러 지수(브로드)
    try:
        obs = fred("DTWEXBGS")
        d, v = last(obs)
        changes = horizon_changes(obs, "pct")
        c90 = changes.get("d90")
        sig = "yellow" if c90 is None else ("red" if c90 > 3 else ("green" if c90 < 0 else "yellow"))
        items.append(ind("dollar", round(v, 1), "%.1f" % v, d, sig,
                         weekly(obs, nd=2), changes, "pct"))
    except Exception as e:
        print("dollar fail:", e, file=sys.stderr)

    # 6) 스타일 성장/가치 IWF/IWD 비율
    try:
        f = dict(price_series("iwf.us", "IWF", "style/IWF"))
        g = dict(price_series("iwd.us", "IWD", "style/IWD"))
        common = sorted(set(f) & set(g))
        ser = [(dt, f[dt] / g[dt]) for dt in common if g[dt]]
        dt, ratio = ser[-1]
        changes = horizon_changes(ser, "pct")
        c90 = changes.get("d90")
        arrow = "▲ 성장주도" if (c90 is None or c90 >= 0) else "▼ 가치주도"
        items.append(ind("style", round(ratio, 3),
                         "%.3f %s" % (ratio, arrow), dt, "neutral",
                         weekly(ser), changes, "pct"))
    except Exception as e:
        print("style fail:", e, file=sys.stderr)

    # 7) 시장 폭 proxy RSP/SPY
    try:
        r = dict(price_series("rsp.us", "RSP", "breadth/RSP"))
        s = dict(price_series("spy.us", "SPY", "breadth/SPY"))
        common = sorted(set(r) & set(s))
        ser = [(dt, r[dt] / s[dt]) for dt in common if s[dt]]
        dt, ratio = ser[-1]
        changes = horizon_changes(ser, "pct")
        c90 = changes.get("d90")
        rising = c90 is None or c90 >= 0
        items.append(ind("breadth", round(ratio, 3),
                         "%.3f %s" % (ratio, "▲ 확산" if rising else "▼ 쏠림"),
                         dt, "green" if rising else "red", weekly(ser), changes, "pct"))
    except Exception as e:
        print("breadth fail:", e, file=sys.stderr)

    # 8) 버핏지수 (베스트에포트: Wilshire5000 / GDP)
    try:
        wil = None
        for sid in ("WILL5000INDFC", "WILL5000IND", "WILL5000PRFC"):
            try:
                wil = fred(sid)
                if wil:
                    break
            except Exception:
                continue
        gdp = fred("GDP")
        if wil and gdp:
            _, w = last(wil)
            _, g = last(gdp)
            ratio = w / g * 100.0
            if 50 <= ratio <= 400:
                sig = "green" if ratio < 120 else ("yellow" if ratio < 160 else "red")
                # 각 날짜의 wilshire 를 최신 GDP(고정값)로 나눈 근사 추이 -
                # GDP는 분기 발표라 시점별 정확도보다 흐름 파악이 목적
                ratio_series = [(d, x / g * 100.0) for d, x in wil]
                items.append(ind("buffett", round(ratio, 0), "%.0f%%" % ratio,
                                 last(wil)[0], sig, weekly(ratio_series, nd=1),
                                 horizon_changes(ratio_series, "pp"), "pp"))
    except Exception as e:
        print("buffett fail:", e, file=sys.stderr)

    # 9) CAPE (실러 PER) 베스트에포트: multpl.com — 현재값만 제공, 이력 없음
    try:
        html = http_get("https://www.multpl.com/shiller-pe")
        m = re.search(r"Current[^0-9]{0,40}([0-9]{2}\.[0-9]{1,2})", html)
        if m:
            v = float(m.group(1))
            sig = "green" if v < 25 else ("yellow" if v < 33 else "red")
            items.append(ind("cape", v, "%.1f" % v, date.today().isoformat(), sig))
    except Exception as e:
        print("cape fail:", e, file=sys.stderr)

    # 10) KOSPI 지수
    try:
        obs = price_series("^kospi", "^KS11", "KOSPI")
        d, v = last(obs)
        changes = horizon_changes(obs, "pct")
        c90 = changes.get("d90")
        sig = "yellow" if c90 is None else ("green" if c90 > 5 else ("red" if c90 < -5 else "yellow"))
        items.append(ind("kospi", round(v, 1), "%.1f" % v, d, sig, weekly(obs), changes, "pct"))
    except Exception as e:
        print("kospi fail:", e, file=sys.stderr)

    # 11) KOSDAQ 지수
    try:
        obs = price_series("^kosdaq", "^KQ11", "KOSDAQ")
        d, v = last(obs)
        changes = horizon_changes(obs, "pct")
        c90 = changes.get("d90")
        sig = "yellow" if c90 is None else ("green" if c90 > 5 else ("red" if c90 < -5 else "yellow"))
        items.append(ind("kosdaq", round(v, 1), "%.1f" % v, d, sig, weekly(obs), changes, "pct"))
    except Exception as e:
        print("kosdaq fail:", e, file=sys.stderr)

    # 12) KOSPI200 — 무료로 재구성 가능한 "연속 선물" 소스가 없어(실측: Naver
    # futures 심볼·Yahoo 선물 심볼 둘 다 빈 응답/404) 지수(KOSPI200 현물)로
    # 대체한다. 선물이 아니라 지수임을 라벨에 명시 - 지어내지 않는다(절대
    # 규칙 1). Yahoo(^KS200)는 이력이 사실상 없어(실측 2y range에 유효 종가
    # 1개) Naver를 우선 시도하고, 실패하면 Yahoo로 폴백한다
    try:
        try:
            obs = naver_daily("KPI200")
            DIAG.append("KOSPI200: naver OK (%d행)" % len(obs))
        except Exception as e1:
            DIAG.append("KOSPI200: naver 실패 (%s) - yahoo 폴백" % e1)
            obs = price_series("^ks200", "^KS200", "KOSPI200")
        d, v = last(obs)
        changes = horizon_changes(obs, "pct")
        c90 = changes.get("d90")
        sig = "yellow" if c90 is None else ("green" if c90 > 5 else ("red" if c90 < -5 else "yellow"))
        items.append(ind("kospi200", round(v, 2), "%.2f" % v, d, sig, weekly(obs), changes, "pct"))
    except Exception as e:
        print("kospi200 fail:", e, file=sys.stderr)

    # 13) USD/KRW 환율
    try:
        obs = price_series("usdkrw", "KRW=X", "USD/KRW")
        d, v = last(obs)
        changes = horizon_changes(obs, "pct")
        c90 = changes.get("d90")
        # 원화 강세(환율 하락) 유리
        sig = "yellow" if c90 is None else ("green" if c90 < -3 else ("red" if c90 > 3 else "yellow"))
        items.append(ind("usdkrw", round(v, 1), "%.1f" % v, d, sig, weekly(obs), changes, "pct"))
    except Exception as e:
        print("usdkrw fail:", e, file=sys.stderr)

    # 14~16) 미국 국채금리 2년/10년/30년 (FRED, %) — 만기별로 반복 패턴이라 루프로
    for key, series_id in (("us2y", "DGS2"), ("us10y", "DGS10"), ("us30y", "DGS30")):
        try:
            obs = fred(series_id)
            d, v = last(obs)
            changes = horizon_changes(obs, "pp")
            c90 = changes.get("d90")
            # 3m +30bp 이상 상승 시 위험(red), -10bp 이하 하락 시 완화(green) —
            # 관례적 구간, config/policies 급 정책 아님
            sig = "yellow" if c90 is None else ("red" if c90 > 0.3 else ("green" if c90 < -0.1 else "yellow"))
            items.append(ind(key, round(v, 2), "%.2f%%" % v, d, sig, weekly(obs), changes, "pp"))
        except Exception as e:
            print("%s fail:" % key, e, file=sys.stderr)

    # 17) WTI 원유 현물 (FRED DCOILWTICO, $/배럴)
    try:
        obs = fred("DCOILWTICO")
        d, v = last(obs)
        changes = horizon_changes(obs, "pct")
        c90 = changes.get("d90")
        sig = "yellow" if c90 is None else ("red" if c90 > 15 else ("green" if c90 < -10 else "yellow"))
        items.append(ind("wti", round(v, 2), "$%.2f" % v, d, sig, weekly(obs), changes, "pct"))
    except Exception as e:
        print("wti fail:", e, file=sys.stderr)

    # 18) BTC/USD (Yahoo Finance BTC-USD)
    try:
        obs = price_series("btc.v", "BTC-USD", "BTC")
        d, v = last(obs)
        changes = horizon_changes(obs, "pct")
        c90 = changes.get("d90")
        sig = "yellow" if c90 is None else ("green" if c90 > 20 else ("red" if c90 < -20 else "yellow"))
        items.append(ind("btc", round(v, 1), "%.1f" % v, d, sig, weekly(obs), changes, "pct"))
    except Exception as e:
        print("btc fail:", e, file=sys.stderr)

    return items


def main():
    items = collect()
    data = {
        "updatedAt": datetime.now(timezone.utc).date().isoformat(),
        "generatedAtUTC": datetime.now(timezone.utc).isoformat(timespec="minutes"),
        "indicators": items,
        # 어떤 소스가 성공/실패했는지 남겨 로그를 뒤지지 않고도 원인 파악
        "_diagnostics": {
            "collected": [i["key"] for i in items],
            "sources": DIAG,
        },
    }
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    with open(OUT, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    print("wrote %s (%d indicators)" % (OUT, len(data["indicators"])))


if __name__ == "__main__":
    main()
