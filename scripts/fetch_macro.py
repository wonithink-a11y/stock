#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
매크로 지표 수집기 — FRED(무료·무키 CSV) + Stooq(무료) 에서 값을 받아
docs/data/macro.json 을 생성한다. 표준 라이브러리만 사용(설치 불필요).

지표별로 try/except 로 감싸 하나가 실패해도 나머지는 정상 기록한다.
GitHub Actions(인터넷 개방) 러너에서 매일 1회 실행하는 용도.
"""
import json
import re
import ssl
import sys
import urllib.request
from datetime import date, datetime, timezone

UA = "Mozilla/5.0 (macro-fetch; +https://github.com)"
CTX = ssl.create_default_context()

# docs/data/macro.json 로 저장 (저장소 루트에서 실행한다고 가정)
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
    for line in txt.splitlines()[1:]:  # 헤더 스킵
        parts = line.split(",")
        if len(parts) < 2:
            continue
        d, v = parts[0].strip(), parts[-1].strip()
        if not v or v == ".":
            continue
        try:
            out.append((d, float(v)))
        except ValueError:
            continue
    return out


def stooq_daily(sym):
    """Stooq 일봉 CSV -> [(date, close), ...]."""
    txt = http_get("https://stooq.com/q/d/l/?s=%s&i=d" % sym)
    out = []
    for line in txt.splitlines()[1:]:
        p = line.split(",")
        if len(p) < 5:
            continue
        try:
            out.append((p[0], float(p[4])))  # Date,Open,High,Low,Close,Volume
        except ValueError:
            continue
    return out


def last(obs):
    return obs[-1] if obs else (None, None)


def ago(obs, n):
    """n 관측치 이전 값(부족하면 가장 오래된 값)."""
    if not obs:
        return None
    i = max(0, len(obs) - 1 - n)
    return obs[i][1]


def pct_change(new, old):
    if not old:
        return None
    return (new / old - 1.0) * 100.0


def ind(key, value, display, as_of, signal):
    return {"key": key, "value": value, "display": display,
            "asOf": as_of, "signal": signal}


def band(v, green_below, yellow_below):
    """작을수록 좋은 지표: v<green→green, <yellow→yellow, else red."""
    if v < green_below:
        return "green"
    if v < yellow_below:
        return "yellow"
    return "red"


def collect():
    items = []

    # 1) 일드커브 10Y-2Y (%)  — 클수록 정상, 역전(음수) 위험
    try:
        d, v = last(fred("T10Y2Y"))
        sig = "green" if v > 0.5 else ("yellow" if v >= 0 else "red")
        items.append(ind("yieldcurve", round(v, 2),
                         ("+%.2f" % v if v >= 0 else "%.2f" % v) + "%p", d, sig))
    except Exception as e:
        print("yieldcurve fail:", e, file=sys.stderr)

    # 2) 하이일드 스프레드 (%) — 작을수록 정상
    try:
        d, v = last(fred("BAMLH0A0HYM2"))
        items.append(ind("hyspread", round(v, 2), "%.2f%%" % v, d,
                         band(v, 3.5, 5.0)))
    except Exception as e:
        print("hyspread fail:", e, file=sys.stderr)

    # 3) VIX — <20 정상, 20~30 경계, >30 위험
    try:
        d, v = last(fred("VIXCLS"))
        items.append(ind("vix", round(v, 1), "%.1f" % v, d, band(v, 20, 30)))
    except Exception as e:
        print("vix fail:", e, file=sys.stderr)

    # 4) M2 유동성 전년비 (%) — 월간, 증가=우호
    try:
        obs = fred("M2SL")
        d, v = last(obs)
        yoy = pct_change(v, ago(obs, 12))
        sig = "green" if yoy > 3 else ("yellow" if yoy >= 0 else "red")
        items.append(ind("liquidity", round(yoy, 1),
                         ("+%.1f" % yoy if yoy >= 0 else "%.1f" % yoy) + "% YoY",
                         d, sig))
    except Exception as e:
        print("liquidity fail:", e, file=sys.stderr)

    # 5) 달러 지수(브로드) — 3개월 급등=EM 역풍(red), 약세=green
    try:
        obs = fred("DTWEXBGS")
        d, v = last(obs)
        chg = pct_change(v, ago(obs, 63))
        sig = "red" if chg > 3 else ("green" if chg < 0 else "yellow")
        items.append(ind("dollar", round(v, 1),
                         "%.1f (%s%.1f%% 3m)" % (v, "+" if chg >= 0 else "", chg),
                         d, sig))
    except Exception as e:
        print("dollar fail:", e, file=sys.stderr)

    # 6) 스타일 성장/가치 IWF/IWD 비율 추세 (Stooq)
    try:
        f = dict(stooq_daily("iwf.us"))
        d = dict(stooq_daily("iwd.us"))
        common = sorted(set(f) & set(d))
        ser = [(dt, f[dt] / d[dt]) for dt in common if d[dt]]
        dt, ratio = ser[-1]
        prev = ser[max(0, len(ser) - 1 - 63)][1]
        arrow = "▲ 성장주도" if ratio >= prev else "▼ 가치주도"
        items.append(ind("style", round(ratio, 3),
                         "%.3f %s" % (ratio, arrow), dt, "neutral"))
    except Exception as e:
        print("style fail:", e, file=sys.stderr)

    # 7) 시장 폭 proxy RSP/SPY (동일가중/시총가중)
    try:
        r = dict(stooq_daily("rsp.us"))
        s = dict(stooq_daily("spy.us"))
        common = sorted(set(r) & set(s))
        ser = [(dt, r[dt] / s[dt]) for dt in common if s[dt]]
        dt, ratio = ser[-1]
        prev = ser[max(0, len(ser) - 1 - 63)][1]
        rising = ratio >= prev
        items.append(ind("breadth", round(ratio, 3),
                         "%.3f %s" % (ratio, "▲ 확산" if rising else "▼ 쏠림"),
                         dt, "green" if rising else "red"))
    except Exception as e:
        print("breadth fail:", e, file=sys.stderr)

    # 8) 버핏지수 (베스트에포트): Wilshire 5000 총가치 / GDP
    #    시리즈 가용성이 바뀌므로 후보를 순차 시도, 실패 시 생략.
    try:
        wil = None
        for sid in ("WILL5000INDFC", "WILL5000IND", "WILL5000PRFC"):
            try:
                wil = fred(sid)
                if wil:
                    break
            except Exception:
                continue
        gdp = fred("GDP")  # 분기, 10억 달러 단위(연율)
        if wil and gdp:
            _, w = last(wil)
            _, g = last(gdp)
            ratio = w / g * 100.0  # WILL...INDFC 는 대략 10억$ 단위 → % 근사
            if 50 <= ratio <= 400:  # 말이 되는 범위만
                sig = "green" if ratio < 120 else ("yellow" if ratio < 160 else "red")
                items.append(ind("buffett", round(ratio, 0),
                                 "%.0f%%" % ratio, last(wil)[0], sig))
    except Exception as e:
        print("buffett fail:", e, file=sys.stderr)

    # 9) CAPE (실러 PER) 베스트에포트: multpl.com 스크레이프
    try:
        html = http_get("https://www.multpl.com/shiller-pe")
        m = re.search(r"Current[^0-9]{0,40}([0-9]{2}\.[0-9]{1,2})", html)
        if m:
            v = float(m.group(1))
            sig = "green" if v < 25 else ("yellow" if v < 33 else "red")
            items.append(ind("cape", v, "%.1f" % v,
                             date.today().isoformat(), sig))
    except Exception as e:
        print("cape fail:", e, file=sys.stderr)

    return items


def main():
    data = {
        "updatedAt": datetime.now(timezone.utc).date().isoformat(),
        "generatedAtUTC": datetime.now(timezone.utc).isoformat(timespec="minutes"),
        "indicators": collect(),
    }
    import os
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    with open(OUT, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    print("wrote %s (%d indicators)" % (OUT, len(data["indicators"])))


if __name__ == "__main__":
    main()
