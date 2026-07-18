#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
매크로 지표 수집기 — FRED(무료·무키 CSV) + Stooq(무료) 에서 값을 받아
docs/data/macro.json 을 생성한다. 표준 라이브러리만 사용(설치 불필요).

각 지표는 현재값 + 신호등 + '이력(history)'을 함께 저장해, 앱에서 미니
추이 그래프(스파크라인)로 과거→현재 흐름을 볼 수 있게 한다.
지표별 try/except 로 감싸 하나가 실패해도 나머지는 정상 기록한다.
GitHub Actions(인터넷 개방) 러너에서 매일 1회 실행하는 용도.
"""
import json
import os
import re
import ssl
import sys
import urllib.request
from datetime import date, datetime, timezone

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


def ind(key, value, display, as_of, signal, history=None):
    o = {"key": key, "value": value, "display": display,
         "asOf": as_of, "signal": signal}
    if history:
        o["history"] = history
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
                         weekly(obs)))
    except Exception as e:
        print("yieldcurve fail:", e, file=sys.stderr)

    # 2) 하이일드 스프레드 (%)
    try:
        obs = fred("BAMLH0A0HYM2")
        d, v = last(obs)
        sig = "green" if v < 3.5 else ("yellow" if v < 5 else "red")
        items.append(ind("hyspread", round(v, 2), "%.2f%%" % v, d, sig,
                         weekly(obs)))
    except Exception as e:
        print("hyspread fail:", e, file=sys.stderr)

    # 3) VIX
    try:
        obs = fred("VIXCLS")
        d, v = last(obs)
        sig = "green" if v < 20 else ("yellow" if v < 30 else "red")
        items.append(ind("vix", round(v, 1), "%.1f" % v, d, sig, weekly(obs)))
    except Exception as e:
        print("vix fail:", e, file=sys.stderr)

    # 4) M2 유동성 전년비 (%) — 월간
    try:
        obs = fred("M2SL")
        d, v = last(obs)
        yoy = pct_change(v, ago(obs, 12))
        sig = "green" if yoy > 3 else ("yellow" if yoy >= 0 else "red")
        yoy_series = [[obs[i][0], round(pct_change(obs[i][1], obs[i - 12][1]), 2)]
                      for i in range(12, len(obs))]
        items.append(ind("liquidity", round(yoy, 1),
                         ("+%.1f" % yoy if yoy >= 0 else "%.1f" % yoy) + "% YoY",
                         d, sig, yoy_series[-24:]))
    except Exception as e:
        print("liquidity fail:", e, file=sys.stderr)

    # 5) 달러 지수(브로드)
    try:
        obs = fred("DTWEXBGS")
        d, v = last(obs)
        chg = pct_change(v, ago(obs, 63))
        sig = "red" if chg > 3 else ("green" if chg < 0 else "yellow")
        items.append(ind("dollar", round(v, 1),
                         "%.1f (%s%.1f%% 3m)" % (v, "+" if chg >= 0 else "", chg),
                         d, sig, weekly(obs, nd=2)))
    except Exception as e:
        print("dollar fail:", e, file=sys.stderr)

    # 6) 스타일 성장/가치 IWF/IWD 비율
    try:
        f = dict(price_series("iwf.us", "IWF", "style/IWF"))
        g = dict(price_series("iwd.us", "IWD", "style/IWD"))
        common = sorted(set(f) & set(g))
        ser = [(dt, f[dt] / g[dt]) for dt in common if g[dt]]
        dt, ratio = ser[-1]
        prev = ser[max(0, len(ser) - 1 - 63)][1]
        arrow = "▲ 성장주도" if ratio >= prev else "▼ 가치주도"
        items.append(ind("style", round(ratio, 3),
                         "%.3f %s" % (ratio, arrow), dt, "neutral",
                         weekly(ser)))
    except Exception as e:
        print("style fail:", e, file=sys.stderr)

    # 7) 시장 폭 proxy RSP/SPY
    try:
        r = dict(price_series("rsp.us", "RSP", "breadth/RSP"))
        s = dict(price_series("spy.us", "SPY", "breadth/SPY"))
        common = sorted(set(r) & set(s))
        ser = [(dt, r[dt] / s[dt]) for dt in common if s[dt]]
        dt, ratio = ser[-1]
        prev = ser[max(0, len(ser) - 1 - 63)][1]
        rising = ratio >= prev
        items.append(ind("breadth", round(ratio, 3),
                         "%.3f %s" % (ratio, "▲ 확산" if rising else "▼ 쏠림"),
                         dt, "green" if rising else "red", weekly(ser)))
    except Exception as e:
        print("breadth fail:", e, file=sys.stderr)

    # 8) 버핏지수 (베스트에포트)
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
                # 이력: 최근 wilshire 를 최신 GDP 로 나눈 근사 추이
                hist = [[d, round(x / g * 100.0, 1)] for d, x in weekly(wil, nd=1)]
                items.append(ind("buffett", round(ratio, 0),
                                 "%.0f%%" % ratio, last(wil)[0], sig, hist))
    except Exception as e:
        print("buffett fail:", e, file=sys.stderr)

    # 9) CAPE (실러 PER) 베스트에포트: multpl.com
    try:
        html = http_get("https://www.multpl.com/shiller-pe")
        m = re.search(r"Current[^0-9]{0,40}([0-9]{2}\.[0-9]{1,2})", html)
        if m:
            v = float(m.group(1))
            sig = "green" if v < 25 else ("yellow" if v < 33 else "red")
            items.append(ind("cape", v, "%.1f" % v, date.today().isoformat(), sig))
    except Exception as e:
        print("cape fail:", e, file=sys.stderr)

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
