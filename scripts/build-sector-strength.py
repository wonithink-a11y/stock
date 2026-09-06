#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""섹터(업종그룹) 상대강도 스냅샷 -> docs/data/sector-strength.json

daily-analysis 가 이미 매일 쓰는 docs/data/prices.json(872종목 OHLCV 250일)을
그대로 읽는다 - 새 수집 없음. 업종은 A1a 의 KSIC 세분류를 config/sectorGroups.json
으로 20개 투자그룹에 묶어서 쓴다.

★ 이 파일은 '관찰용 지표'다. 예측력 주장이 아니다.
   research/strategy-lab/findings/sector-leadership-step0-2026-09.md 에서
   섹터 주도권 신호는 난수 바닥선을 못 넘어 REJECT 됐다. 그래서 대시보드는
   "지금 무엇이 강한가"만 보여주고 "그래서 사라"는 말은 하지 않는다.

가중 3종을 나란히 낸다(2026-09-06 추가). 셋은 서로 다른 질문에 답한다.

  EW   종목 수익률의 중앙값        "이 그룹의 보통 종목이 강한가"
  TV   거래대금 가중              "거래가 몰린 종목들이 강했는가"
  CAP  시가총액 가중              "이 그룹이 지수를 얼마나 밀어올렸는가"

기존 EW 는 대형주를 구조적으로 못 본다 - 삼성전자는 KSIC 상 '통신·네트워크'
9종목 중 하나라 중앙값에 거의 안 잡힌다. 실측(2026-09-04, 6개월): 유니버스
EW 중앙값 -7.4% vs 시총가중 +29.7%. 그 격차가 이 추가의 이유다.

★ 가중치는 **각 창의 시작 시점** 기준이다. 종료 시점으로 잡으면 오른 종목에
  오른 뒤의 비중을 주게 되어 결과가 부풀려진다 - 실측으로 6개월 벤치마크가
  +29.67%->+47.32%, 전자부품·디스플레이 RS 가 46%p->127%p 로 왜곡됐다.

★ CAP 에는 분면(주도/부상/둔화/약세) 라벨을 붙이지 않는다. 그 라벨은 EW 전용
  관찰 체계이고, 시총가중에 붙이면 "시총가중 주도"가 매매신호로 읽힌다.

  python scripts/build-sector-strength.py
  python scripts/build-sector-strength.py --selftest
"""
import argparse
import collections
import glob
import gzip
import json
import os
import re
import statistics
from datetime import datetime, timezone, timedelta

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PRICES = os.path.join(ROOT, "docs", "data", "prices.json")
A1A = os.path.join(ROOT, "data", "backfill", "universe", "a1a", "current.jsonl")
ROLLUP = os.path.join(ROOT, "config", "sectorGroups.json")
A3C = os.path.join(ROOT, "data", "backfill", "fundamentals", "a3c", "*.jsonl.gz")
SNAPSHOT = os.path.join(ROOT, "docs", "data", "shares-snapshot.json")
OUT = os.path.join(ROOT, "docs", "data", "sector-strength.json")

KST = timezone(timedelta(hours=9))
WINDOWS = {"1w": 5, "1m": 21, "3m": 63, "6m": 126}
MIN_MEMBERS = 5          # 이 미만인 그룹은 표시하지 않는다 (절대 규칙 1)
MIN_BARS = 130           # 6m 창을 채우지 못하는 종목은 그 창에서 제외
TV_LOOKBACK = 21         # 거래대금 가중치를 재는 구간(창 시작 직전 21세션)
STALE_WARN_DAYS = 180    # 주식수가 이보다 오래되면 경고. 계산에서 빼지는 않는다
SPLIT_UP, SPLIT_DOWN = 1.5, 2 / 3   # 주식수 급변 가드(양방향). 분할 판별기가 아니라
                                     # "현재 가격과 곱하기 위험한 종목" 차단기다.
A8_RATIO_TOLERANCE = 0.02  # A3c 폴백 경로 전용. 재구성/참조 시총비가 이만큼
                           # 벗어나면 제외한다 - 원인은 분류하지 않는다.


def load_rollup():
    with open(ROLLUP, encoding="utf-8") as f:
        groups = json.load(f)["groups"]
    return {ksic: g for g, ks in groups.items() for ksic in ks}


def load_sector_by_ticker(k2g):
    out = {}
    with open(A1A, encoding="utf-8") as f:
        for line in f:
            r = json.loads(line)
            t, s = r.get("ticker"), r.get("sector")
            if t and s and s in k2g:
                out[t] = k2g[s]
    return out


def ret(closes, n):
    """n 거래일 전 대비 수익률. 데이터가 모자라면 None(0 으로 채우지 않는다)."""
    if len(closes) < n + 1:
        return None
    a, b = closes[-1 - n], closes[-1]
    if not a or a <= 0 or not b or b <= 0:
        return None
    return b / a - 1.0


def sma_pos(closes, n):
    """종가가 n일 이동평균 위면 True. 데이터 부족하면 None."""
    if len(closes) < n:
        return None
    w = closes[-n:]
    if any(not c or c <= 0 for c in w):
        return None
    return closes[-1] > sum(w) / n


def d8(x):
    """날짜를 숫자 8자리로 정규화. A3 는 '2025-08-14', A3c 는 '20250515' 이고
    prices.json 의 asOf 는 '20260904' 다 - 셋을 문자열로 직접 비교하면 조용히
    틀린다."""
    s = re.sub(r"\D", "", str(x or ""))
    return s[:8] if len(s) >= 8 else None


def load_shares(asof):
    """A3c(DART 주식총수현황)에서 asof 시점에 공시돼 있던 최신 발행주식총수.

    istcTotqy 를 쓴다 - KRX 시가총액은 자사주를 **포함한** 상장주식수 기준이라
    distbStockCo(유통주식수)가 아니다. 2026-09-04 외부 대조에서 istcTotqy 는
    LG에너지솔루션·현대차·한미반도체 3종목이 주 단위로 일치(오차 0.00%)한 반면
    distbStockCo 는 -0.32~-3.94% 어긋났다. isuStockTotqy 는 수권주식수다.

    가드 둘을 여기서 건다(둘 다 '분할 판별'이 아니라 안전장치다):
      - 직전 레코드 대비 주식수가 1.5배 이상 늘거나 2/3 이하로 줄면 UNVERIFIED.
        마지막 공시 이후 액면분할·소각이 났는데 가격만 조정된 상태로 곱하면
        시총이 몇 배 틀린다(실측: 2025-01 이후 41.8%가 주식수 변경, 최대 +881%).
      - 발행주식총수가 수권주식수를 넘으면 UNVERIFIED(있을 수 없는 값).
    """
    asof = d8(asof)
    hist = {}
    for path in sorted(glob.glob(A3C)):
        with gzip.open(path, "rt", encoding="utf-8") as f:
            for line in f:
                r = json.loads(line)
                t, av = r.get("ticker"), d8(r.get("availableFrom"))
                if not t or not av or r.get("scanStatus") != "OK":
                    continue
                if not isinstance(r.get("istcTotqy"), int) or r["istcTotqy"] <= 0:
                    continue
                if asof and av > asof:
                    continue
                hist.setdefault(t, []).append((av, r["istcTotqy"], r.get("isuStockTotqy")))
    out = {}
    for t, rows in hist.items():
        rows.sort(key=lambda x: (x[0], x[1]))   # isuStockTotqy 는 None 일 수 있어 정렬키에서 뺀다
        av, shares, authorized = rows[-1]
        reason = None
        if isinstance(authorized, int) and authorized > 0 and shares > authorized:
            reason = "EXCEEDS_AUTHORIZED"
        elif len(rows) >= 2:
            # ★ 비교 대상은 '시간상 직전 레코드'다. '최근에 값이 달랐던 레코드'와
            #   비교하면 10년 전 사건에 발동한다 - 실제로 한국전력(2017)·삼성E&A
            #   (2016) 같은 안정된 종목 38건이 걸렸다(2026-09-06 실측). 직전
            #   레코드 대비로 보면 "마지막 공시 직전에 주식수가 급변했다"만 잡힌다.
            ratio = shares / rows[-2][1]
            if ratio >= SPLIT_UP or ratio <= SPLIT_DOWN:
                reason = "SHARES_JUMP"
        out[t] = {"shares": shares, "asOf": av, "unverified": reason}
    return out


def load_snapshot(path=SNAPSHOT):
    """KRX 상장주식수 현재 스냅샷(build-shares-snapshot.py). 없으면 {}."""
    if not os.path.exists(path):
        return {}
    d = json.load(open(path, encoding="utf-8"))
    if d.get("status") == "FAILED":
        return {}
    return d.get("shares") or {}


def load_a8_price_ratio(as_of, tickers, closes_by_ticker):
    """A8(KRX 공매도 잔고)에서 실제 체결 기준 주가를 복원해 prices.json 의
    조정주가와 비교한 배율. `잔고금액 / 잔고수량` 이 그 날의 실주가다(실측:
    005930 4일치가 prices.json 종가와 원 단위로 일치).

    쓰임은 하나다 - **A3c 폴백 경로의 안전장치**. A3c 주식수(현재 시점 하나)를
    조정주가와 곱하는 구성은 분할류를 상쇄하지만, 그 상쇄는 두 값이 같은
    기준일 때만 성립한다. 마지막 A3c 공시 이후에 자본변동이 나면 prices.json
    만 소급 재작성돼 기준이 어긋난다 - 그때 이 배율이 1 에서 벗어난다.

    배율의 의미를 원인으로 분류하지 않는다(분할·증자·소각·시점차 전부 섞여
    있다). 재구성 시총 / 참조 시총의 비로만 읽고, 벗어나면 그 종목을 CAP 에서
    뺀다. 주식수가 양쪽에서 같으므로 시총비 = 주가비로 약분된다.

    A8 은 갱신이 느리므로(실측 2026-09-06 기준 23일) 이 비교는 **KRX 스냅샷이
    없는 종목에만** 쓴다 - 최신 KRX 값이 있는데 낡은 A8 때문에 빼면 안 된다.

    ★ 날짜별 배율을 통째로 돌려준다. '가장 최신 날짜 하나'로 비교하면 안 된다 -
      사건이 지나가면 A8 도 새 기준으로 넘어가 배율이 1 로 돌아오기 때문이다.
      실측(LS ELECTRIC, 2026-09-06): 2026-04-13 에 5:1 분할이 났고 A3c 최신
      공시는 2026-03-18(분할 전)인데, 최신 날짜(2026-08-14) 배율은 1.0 이라
      아무것도 안 잡혔다. 판정은 **주식수 공시일 이후 구간**에서 해야 한다."""
    out = {}
    want = set(tickers)
    for year in sorted({(d8(as_of) or "")[:4], str(int((d8(as_of) or "0001")[:4]) - 1)}):
        path = os.path.join(ROOT, "data", "backfill", "shortSelling", "a8", year + ".jsonl.gz")
        if not year.isdigit() or not os.path.exists(path):
            continue
        with gzip.open(path, "rt", encoding="utf-8") as f:
            for line in f:
                r = json.loads(line)
                t = r.get("ticker")
                if t not in want or not r.get("shortBalanceShares") or not r.get("shortBalanceValue"):
                    continue
                d = d8(r.get("date"))
                adj = (closes_by_ticker.get(t) or {}).get(d) if d else None
                if not adj or adj <= 0:
                    continue
                raw = r["shortBalanceValue"] / r["shortBalanceShares"]
                if raw > 0:
                    out.setdefault(t, []).append((d, raw / adj))
    for t in out:
        out[t].sort()
    return out


def worst_ratio_since(series, since):
    """`since`(주식수 공시일) 이후 구간에서 1 에서 가장 많이 벗어난 배율.

    그 구간에 배율이 1 이 아닌 날이 있으면, 주식수가 공시된 뒤에 가격 기준이
    재작성됐다는 뜻이다 - 즉 지금 가진 주식수와 지금 가진 가격이 다른 기준이다.
    참조할 날이 없으면 None(모르는 것을 1 로 채우지 않는다)."""
    if not series:
        return None
    pool = [(d, r) for d, r in series if since is None or d >= since]
    if not pool:
        return None
    d, r = max(pool, key=lambda x: abs(x[1] - 1.0))
    return {"ratio": r, "on": d, "n": len(pool)}


def resolve_shares(tickers, snapshot, a3c, a8_ratio, as_of):
    """종목별 주식수를 출처와 함께 확정한다.

      KRX 스냅샷 있음 -> 그 값. A8 배율은 진단으로만 기록하고 제외 게이트로 안 쓴다
      없음            -> A3c. 이때만 A8 배율 검사를 제외 게이트로 건다
    """
    out = {}
    for t in tickers:
        snap = snapshot.get(t)
        series = a8_ratio.get(t)
        if snap and snap.get("listedShares"):
            # KRX 는 오늘의 주식수라 A8(23일 낡음) 배율로 제외하지 않는다.
            # 진단으로 마지막 배율만 남긴다.
            last = series[-1][1] if series else None
            out[t] = {"shares": snap["listedShares"], "asOf": d8(snap.get("sourceDate")),
                      "source": "KRX", "unverified": None,
                      "krxMarketCap": snap.get("krxMarketCap"),
                      "a8Ratio": (round(last, 4) if last is not None else None)}
            continue
        rec = a3c.get(t)
        if not rec or not rec.get("shares"):
            continue
        # A3c 는 '그 공시일 기준' 주식수다. 그 뒤에 가격 기준이 재작성됐는지를 본다.
        diag = worst_ratio_since(series, rec.get("asOf"))
        reason = rec.get("unverified")
        if reason is None and diag and abs(diag["ratio"] - 1.0) > A8_RATIO_TOLERANCE:
            reason = "PRICE_BASIS_MISMATCH"
        out[t] = {"shares": rec["shares"], "asOf": rec.get("asOf"), "source": "A3C",
                  "unverified": reason, "krxMarketCap": None,
                  "a8Ratio": (round(diag["ratio"], 4) if diag else None),
                  "a8RatioOn": (diag["on"] if diag else None)}
    return out


def stale_days(as_of, ref):
    a, b = d8(as_of), d8(ref)
    if not a or not b:
        return None
    fmt = "%Y%m%d"
    return (datetime.strptime(b, fmt) - datetime.strptime(a, fmt)).days


def med(vals):
    v = [x for x in vals if x is not None]
    return statistics.median(v) if v else None


def wavg(pairs):
    """(수익률, 가중치) 목록의 가중평균과 커버리지.

    가중치가 없는 종목은 **분자와 분모 양쪽에서** 빠진다 - 분모에만 남기면
    그 종목 수익률을 0으로 친 것과 같아진다(절대 규칙 1 · 교훈 57).
    커버리지는 '가중치를 쓸 수 있었던 종목 / 전체 종목'이다."""
    if not pairs:
        return None, None
    ok = [(r, w) for r, w in pairs if r is not None and w is not None and w > 0]
    cov = len(ok) / len(pairs)
    if not ok:
        return None, round(cov, 3)
    return sum(r * w for r, w in ok) / sum(w for _, w in ok), round(cov, 3)


def tv_weight(closes, volumes, n):
    """창 시작 직전 TV_LOOKBACK 세션의 평균 거래대금. 종료 시점이 아니라 시작
    시점 기준이라야 '그때 거래가 몰려 있던 종목'에 비중이 간다."""
    need = n + TV_LOOKBACK
    if len(closes) < need or len(volumes) < need:
        return None
    lo, hi = -1 - n - (TV_LOOKBACK - 1), (-n if n else None)
    c, v = closes[lo:hi], volumes[lo:hi]
    if len(c) != TV_LOOKBACK or any(x is None or x < 0 for x in c + v):
        return None
    tv = statistics.mean(a * b for a, b in zip(c, v))
    return tv if tv > 0 else None


def cap_weight(closes, shares, n):
    """창 시작일 종가 × 발행주식총수. 종료일로 잡으면 오른 종목에 오른 뒤의
    비중을 주게 되어 결과가 부풀려진다(docstring 참고)."""
    if shares is None or len(closes) < n + 1:
        return None
    c = closes[-1 - n]
    return c * shares if c and c > 0 else None


def frac_true(vals):
    v = [x for x in vals if x is not None]
    return (sum(1 for x in v if x) / len(v)) if v else None


def quadrant(rs_level, accel):
    """RRG 4분면. x=장기 상대강도, y=단기 가속."""
    if rs_level is None or accel is None:
        return None
    if rs_level >= 0:
        return "주도" if accel >= 0 else "둔화"
    return "부상" if accel >= 0 else "약세"


def r4(v):
    return None if v is None else round(v, 4)


def build(prices, sector_by_ticker, market="KR", shares_by_ticker=None):
    shares_by_ticker = shares_by_ticker or {}
    as_of = None
    for rec in prices["byTicker"].values():
        d = rec.get("d") or []
        if d:
            as_of = max(as_of, d[-1]) if as_of else d[-1]

    rows = []
    unmapped = 0
    unverified = []
    cap_checks = []
    for ticker, rec in prices["byTicker"].items():
        if rec.get("market") != market:
            continue
        g = sector_by_ticker.get(ticker)
        if not g:
            unmapped += 1
            continue
        c = [x for x in rec.get("c", [])]
        if len(c) < MIN_BARS:
            continue
        v = [x for x in rec.get("v", [])]
        sh = shares_by_ticker.get(ticker) or {}
        bad = sh.get("unverified")
        if bad:
            unverified.append({"ticker": ticker, "name": rec.get("name"), "reason": bad,
                               "source": sh.get("source"), "a8Ratio": sh.get("a8Ratio")})
        usable = sh.get("shares") if (sh.get("shares") and not bad) else None
        # KRX 가 함께 준 시가총액과 우리 재구성값을 대조한다 - **검증용이고
        # 게이트가 아니다**. CAP 계산 기준은 조정주가 × listedShares 하나뿐이다.
        if usable and sh.get("krxMarketCap") and sh.get("asOf"):
            ref_close = dict(zip(rec.get("d") or [], c)).get(sh["asOf"])
            if ref_close:
                cap_checks.append(usable * ref_close / sh["krxMarketCap"])
        rows.append({
            "ticker": ticker, "name": rec.get("name"), "group": g,
            "rets": {k: ret(c, n) for k, n in WINDOWS.items()},
            "capW": {k: cap_weight(c, usable, n) for k, n in WINDOWS.items()},
            "tvW": {k: tv_weight(c, v, n) for k, n in WINDOWS.items()},
            "sharesAsOf": sh.get("asOf"), "sharesSource": sh.get("source"),
            "staleDays": stale_days(sh.get("asOf"), as_of),
            "above20": sma_pos(c, 20), "above60": sma_pos(c, 60),
        })

    bench = {k: med([r["rets"][k] for r in rows]) for k in WINDOWS}
    cap_bench = {k: wavg([(r["rets"][k], r["capW"][k]) for r in rows])[0] for k in WINDOWS}
    tv_bench = {k: wavg([(r["rets"][k], r["tvW"][k]) for r in rows])[0] for k in WINDOWS}

    by_group = {}
    for r in rows:
        by_group.setdefault(r["group"], []).append(r)

    groups = []
    for g, members in by_group.items():
        if len(members) < MIN_MEMBERS:
            continue
        rets = {k: med([m["rets"][k] for m in members]) for k in WINDOWS}
        rs = {k: (None if rets[k] is None or bench[k] is None else rets[k] - bench[k])
              for k in WINDOWS}
        accel = (None if rs["1m"] is None or rs["3m"] is None else rs["1m"] - rs["3m"])

        cap, cap_cov, tv, tv_cov = {}, {}, {}, {}
        for k in WINDOWS:
            cap[k], cap_cov[k] = wavg([(m["rets"][k], m["capW"][k]) for m in members])
            tv[k], tv_cov[k] = wavg([(m["rets"][k], m["tvW"][k]) for m in members])
        sub = lambda a, b: {k: (None if a[k] is None or b[k] is None else a[k] - b[k]) for k in WINDOWS}

        # capTop 은 장식이 아니다 - KSIC 분류상 삼성전자가 '통신·네트워크' 에
        # 들어가 그 그룹 시총의 95%를 차지하는 식이라, 이걸 안 보여주면 시총가중
        # 값을 그룹 이야기로 오독한다(실측 19그룹 중 6개가 단일종목 비중 >= 49%).
        cap_top, cap_top_w = None, None
        weighted = [(m, m["capW"]["3m"]) for m in members if m["capW"]["3m"]]
        if weighted:
            m, w = max(weighted, key=lambda x: x[1])
            cap_top = {"ticker": m["ticker"], "name": m["name"],
                       "sharesAsOf": m["sharesAsOf"], "staleDays": m["staleDays"]}
            cap_top_w = round(w / sum(x for _, x in weighted), 3)

        stales = [m["staleDays"] for m in members if m["staleDays"] is not None]
        src = collections.Counter(m["sharesSource"] for m in members if m["sharesSource"])
        ranked = sorted((m for m in members if m["rets"]["1m"] is not None),
                        key=lambda m: m["rets"]["1m"], reverse=True)
        brief = lambda m: {"ticker": m["ticker"], "name": m["name"],
                           "ret1m": round(m["rets"]["1m"], 4),
                           "sharesAsOf": m["sharesAsOf"], "staleDays": m["staleDays"]}
        groups.append({
            "group": g, "n": len(members),
            "ret": {k: r4(v) for k, v in rets.items()},
            "rs": {k: r4(v) for k, v in rs.items()},
            "accel": r4(accel),
            "breadth20": (lambda v: None if v is None else round(v, 3))(frac_true([m["above20"] for m in members])),
            "breadth60": (lambda v: None if v is None else round(v, 3))(frac_true([m["above60"] for m in members])),
            "quadrant": quadrant(rs["3m"], accel),          # EW 전용. CAP/TV 에는 안 붙인다
            "capRet": {k: r4(v) for k, v in cap.items()},
            "capRs": {k: r4(v) for k, v in sub(cap, cap_bench).items()},
            "capCoverage": cap_cov,
            "capTop": cap_top, "capTopWeight": cap_top_w,
            "tvRet": {k: r4(v) for k, v in tv.items()},
            "tvRs": {k: r4(v) for k, v in sub(tv, tv_bench).items()},
            "tvCoverage": tv_cov,
            "maxSharesStaleDays": max(stales) if stales else None,
            "sharesStale": bool(stales and max(stales) > STALE_WARN_DAYS),
            "sharesSourceCounts": dict(src),
            "sharesFallbackCount": src.get("A3C", 0),
            "top": [brief(m) for m in ranked[:3]],
            "bottom": [brief(m) for m in ranked[-3:]][::-1],
        })

    groups.sort(key=lambda x: (x["rs"]["3m"] is None, -(x["rs"]["3m"] or 0)))
    return {
        "updatedAt": datetime.now(KST).isoformat(timespec="seconds"),
        "asOf": as_of,
        "market": market,
        "universeCount": len(rows),
        "unmappedTickers": unmapped,
        "minMembers": MIN_MEMBERS,
        "aggregation": "EW=그룹 내 종목 수익률의 중앙값 · TV=거래대금 가중 · CAP=시가총액 가중",
        "weightingNote": "TV·CAP 가중치는 **각 창의 시작 시점** 기준이다. 종료 시점으로 "
                         "잡으면 오른 종목에 오른 뒤의 비중이 가서 결과가 부풀려진다"
                         "(실측 6개월 벤치마크 +29.67%->+47.32%).",
        "benchmark": {k: r4(v) for k, v in bench.items()},
        "benchmarkNote": "동일 유니버스 전체(KR) 종목 수익률의 중앙값",
        "capBenchmark": {k: r4(v) for k, v in cap_bench.items()},
        "capBenchmarkNote": "Universe Cap-Weighted Benchmark - 이 유니버스"
                            "(코스피200+코스닥150, 우선주 제외)의 시총가중 수익률이다. "
                            "**KOSPI·KOSDAQ 지수가 아니다** (2026-09-04 실측 6개월: "
                            "이 벤치마크 +29.7% vs KOSPI +35.7%).",
        "tvBenchmark": {k: r4(v) for k, v in tv_bench.items()},
        "tvBenchmarkNote": "동일 유니버스의 거래대금 가중 수익률. 거래대금은 매수·매도 "
                           "합산 거래규모이지 순자금 유입이 아니다.",
        "sharesSource": "A3c istcTotqy(발행주식총수, availableFrom<=asOf·scanStatus=OK 중 최신). "
                        "KRX 시가총액은 자사주 포함 상장주식수 기준이라 distbStockCo가 아니다.",
        "sharesSourceCounts": dict(collections.Counter(
            r["sharesSource"] for r in rows if r["sharesSource"])),
        "sharesFallbackCount": sum(1 for r in rows if r["sharesSource"] == "A3C"),
        "sharesMissingCount": sum(1 for r in rows if not r["sharesSource"]),
        "sharesUnverified": sorted(unverified, key=lambda x: x["ticker"]),
        "krxMarketCapCheck": ({
            "n": len(cap_checks),
            "medianRatio": round(statistics.median(cap_checks), 5),
            "maxAbsDeviation": round(max(abs(x - 1) for x in cap_checks), 5),
            "beyond2pct": sum(1 for x in cap_checks if abs(x - 1) > A8_RATIO_TOLERANCE),
            "note": "재구성(조정주가 x listedShares) / KRX 시가총액. 검증용이고 "
                    "게이트가 아니다 - CAP 계산 기준은 재구성값 하나뿐이다.",
        } if cap_checks else None),
        "sharesGuard": {"splitUp": SPLIT_UP, "splitDown": round(SPLIT_DOWN, 4),
                        "staleWarnDays": STALE_WARN_DAYS,
                        "note": "주식수가 직전 공시 대비 급변하거나 수권주식수를 넘으면 "
                                "CAP 계산에서 제외한다(분자·분모 양쪽). stale 은 경고만 "
                                "하고 제외하지 않는다 - 오래됐다고 틀린 것은 아니다."},
        "quadrantAxes": {"x": "3개월 상대강도(rs.3m)", "y": "가속(rs.1m - rs.3m)",
                         "appliesTo": "EW only"},
        "disclaimer": "관찰용 지표다. Step 0 검증에서 섹터 주도권 신호는 난수 "
                      "바닥선을 넘지 못했다(findings/sector-leadership-step0-2026-09.md) - "
                      "예측력 주장이 아니라 현재 상태 표시다.",
        "groups": groups,
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--selftest", action="store_true")
    args = ap.parse_args()
    if args.selftest:
        return selftest()

    with open(PRICES, encoding="utf-8") as f:
        prices = json.load(f)
    k2g = load_rollup()
    as_of = max((r["d"][-1] for r in prices["byTicker"].values() if r.get("d")), default=None)
    sectors = load_sector_by_ticker(k2g)
    kr = [t for t, r in prices["byTicker"].items() if r.get("market") == "KR" and sectors.get(t)]
    closes = {t: dict(zip(prices["byTicker"][t].get("d") or [], prices["byTicker"][t].get("c") or []))
              for t in kr}
    snapshot = load_snapshot()
    a8 = load_a8_price_ratio(as_of, kr, closes)
    shares = resolve_shares(kr, snapshot, load_shares(as_of), a8, as_of)
    print("주식수 출처: KRX %d · A3C %d · 없음 %d (스냅샷 %d종목 · A8 참조 %d종목)" % (
        sum(1 for v in shares.values() if v["source"] == "KRX"),
        sum(1 for v in shares.values() if v["source"] == "A3C"),
        len(kr) - len(shares), len(snapshot), len(a8)))
    out = build(prices, sectors, shares_by_ticker=shares)
    with open(OUT, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, separators=(",", ":"))
    print("asOf {} · {}종목 · {}개 그룹 · 미매핑 {} · 주식수 확보 {} · UNVERIFIED {}".format(
        out["asOf"], out["universeCount"], len(out["groups"]), out["unmappedTickers"],
        len(shares), len(out["sharesUnverified"])))
    pc = lambda v: "{:>8}".format("None" if v is None else "{:+.1%}".format(v))
    print("  벤치마크 3M   EW {}  TV {}  CAP {}".format(
        pc(out["benchmark"]["3m"]), pc(out["tvBenchmark"]["3m"]), pc(out["capBenchmark"]["3m"])))
    print("  {:<20}{:>4}{:>8}{:>8}{:>8}{:>7}  {:<5} {}".format(
        "그룹", "n", "EW_RS", "TV_RS", "CAP_RS", "capCov", "분면", "capTop"))
    for g in out["groups"]:
        print("  {:<20}{:>4}{}{}{}{:>7}  {:<5} {} {}{}".format(
            g["group"], g["n"], pc(g["rs"]["3m"]), pc(g["tvRs"]["3m"]), pc(g["capRs"]["3m"]),
            "{:.0%}".format(g["capCoverage"]["3m"]) if g["capCoverage"]["3m"] is not None else "-",
            g["quadrant"] or "-",
            (g["capTop"] or {}).get("name", "-"),
            "" if g["capTopWeight"] is None else "{:.0%}".format(g["capTopWeight"]),
            "  ⚠stale" if g["sharesStale"] else ""))
    print("saved:", OUT)


def selftest():
    assert abs(ret([100, 110], 1) - 0.10) < 1e-12
    assert ret([100], 1) is None                    # 데이터 부족 -> None (0 아님)
    assert ret([0, 110], 1) is None                 # 0 가격 방어
    assert sma_pos([1, 2, 3, 10], 4) is True
    assert sma_pos([10, 3, 2, 1], 4) is False
    assert sma_pos([1, 2], 4) is None
    assert med([1, None, 3]) == 2 and med([None]) is None
    assert frac_true([True, False, None]) == 0.5 and frac_true([None]) is None
    assert quadrant(0.1, 0.1) == "주도" and quadrant(0.1, -0.1) == "둔화"
    assert quadrant(-0.1, 0.1) == "부상" and quadrant(-0.1, -0.1) == "약세"
    assert quadrant(None, 0.1) is None

    k2g = load_rollup()
    assert len(k2g) == 159, len(k2g)
    ks = list(k2g)
    g0 = k2g[ks[0]]

    # 소속 5종목 미만 그룹은 나오지 않는다 / 벤치마크 대비 RS 부호가 맞는다
    def series(step):
        return [100 + step * i for i in range(MIN_BARS + 1)]
    by = {}
    sec = {}
    for i in range(MIN_MEMBERS):
        t = "A%d" % i
        by[t] = {"name": t, "market": "KR", "c": series(1), "d": ["20260101"] * (MIN_BARS + 1)}
        sec[t] = g0
    other = next(k2g[k] for k in ks if k2g[k] != g0)
    for i in range(MIN_MEMBERS):                      # 대조군: 더 약하게 오른다
        t = "B%d" % i
        by[t] = {"name": t, "market": "KR", "c": series(0.1), "d": ["20260101"] * (MIN_BARS + 1)}
        sec[t] = other
    by["C0"] = {"name": "C0", "market": "KR", "c": series(5), "d": ["20260101"] * (MIN_BARS + 1)}
    sec["C0"] = next(k2g[k] for k in ks if k2g[k] not in (g0, other))

    # ── 가중 3종 (2026-09-06 추가) ────────────────────────────────
    assert d8("2025-08-14") == "20250814" and d8("20250515") == "20250515"
    assert d8(None) is None and d8("2025") is None          # 8자리 미만은 None
    assert stale_days("20260310", "20260904") == 178
    assert stale_days(None, "20260904") is None

    # wavg: 가중치 없는 종목은 분자·분모 양쪽에서 빠지고 커버리지에 남는다
    v, cov = wavg([(0.1, 1.0), (0.3, 1.0)])
    assert abs(v - 0.2) < 1e-12 and cov == 1.0
    v, cov = wavg([(0.1, 3.0), (0.3, 1.0)])          # 가중치가 실제로 먹는다
    assert abs(v - 0.15) < 1e-12 and cov == 1.0
    v, cov = wavg([(0.1, 1.0), (0.9, None)])
    assert v == 0.1 and cov == 0.5, (v, cov)                # 0.9를 0으로 치지 않는다
    assert wavg([(0.1, None)]) == (None, 0.0)
    assert wavg([]) == (None, None)

    # 가중치는 창 시작 기준 - 종료 기준이면 값이 달라진다
    cl = [10, 20, 40, 80]
    assert cap_weight(cl, 100, 3) == 1000 and cap_weight(cl, 100, 0) == 8000
    assert cap_weight(cl, None, 1) is None and cap_weight(cl, 100, 9) is None
    vol = [5] * 4
    assert tv_weight(cl, vol, 0) is None                    # 21세션 미달 -> None
    n_ok = TV_LOOKBACK
    c2, v2 = list(range(1, n_ok + 3)), [2] * (n_ok + 2)
    w_start, w_end = tv_weight(c2, v2, 1), tv_weight(c2, v2, 0)
    assert w_start is not None and w_end is not None and w_start < w_end

    # load_shares 가드: 급변(양방향)·수권초과는 UNVERIFIED, 정상은 통과
    def shares_of(rows):
        return {"T": rows}
    mk = lambda av, s, auth=None: {"ticker": "T", "availableFrom": av, "istcTotqy": s,
                                   "isuStockTotqy": auth, "scanStatus": "OK"}
    def guard(rows):
        h = {}
        for r in rows:
            h.setdefault(r["ticker"], []).append((d8(r["availableFrom"]), r["istcTotqy"],
                                                  r.get("isuStockTotqy")))
        t = "T"; rs = sorted(h[t]); av, sh, auth = rs[-1]
        if isinstance(auth, int) and auth > 0 and sh > auth:
            return "EXCEEDS_AUTHORIZED"
        if len(rs) >= 2:
            ratio = sh / rs[-2][1]
            if ratio >= SPLIT_UP or ratio <= SPLIT_DOWN:
                return "SHARES_JUMP"
        return None
    assert guard([mk("20250318", 100), mk("20260318", 500)]) == "SHARES_JUMP"   # 액면분할
    assert guard([mk("20250318", 500), mk("20260318", 100)]) == "SHARES_JUMP"   # 대규모 소각
    assert guard([mk("20250318", 100), mk("20260318", 101)]) is None            # 정상 변동
    assert guard([mk("20260318", 100, 50)]) == "EXCEEDS_AUTHORIZED"
    assert guard([mk("20260318", 100)]) is None                # 레코드 1개 -> 비교 불가
    # ★ 오래된 사건에는 발동하지 않는다 - 직전 레코드와만 비교한다
    assert guard([mk("20160518", 100), mk("20170518", 500),
                  mk("20250318", 500), mk("20260318", 500)]) is None
    # ×1000 단위 오류가 최신값이면 잡힌다(A3c 실측: 한국전력·태광산업 과거 행)
    assert guard([mk("20250318", 641964077), mk("20260318", 641964077000)]) == "SHARES_JUMP"

    out = build({"byTicker": by}, sec)
    names = [g["group"] for g in out["groups"]]
    assert g0 in names and other in names
    assert sec["C0"] not in names, "1종목 그룹이 표시됐다"
    a = next(g for g in out["groups"] if g["group"] == g0)
    b = next(g for g in out["groups"] if g["group"] == other)
    # 벤치마크가 중앙값이라 강한 그룹의 RS 가 0 일 수 있다 - 불변식은 순서와 약한 쪽 부호다
    assert a["rs"]["3m"] > b["rs"]["3m"] and b["rs"]["3m"] < 0, (a["rs"], b["rs"])
    assert out["groups"][0]["group"] == g0            # RS 내림차순 정렬
    assert a["n"] == MIN_MEMBERS and a["breadth20"] == 1.0
    assert len(a["top"]) == 3
    # market 필터
    by["US0"] = {"name": "US0", "market": "US", "c": series(9), "d": ["20260101"]}
    assert build({"byTicker": by}, sec)["universeCount"] == out["universeCount"]

    # CAP/TV 필드는 주식수·거래량이 없으면 조용히 0 이 되지 않고 None + 커버리지 0
    assert a["capRet"]["3m"] is None and a["capCoverage"]["3m"] == 0.0
    assert a["capTop"] is None and a["capTopWeight"] is None
    assert out["capBenchmark"]["3m"] is None
    assert a["quadrant"] is not None                  # 분면은 EW 에만 남는다
    assert "capQuadrant" not in a and "tvQuadrant" not in a

    # 주식수·거래량을 주면 CAP 이 실제로 대형주를 따라간다.
    # g0 그룹 5종목 중 A0 만 시총이 100배 - EW 중앙값과 CAP 이 갈려야 한다.
    for t in list(by):
        if by[t]["market"] == "KR":
            by[t]["v"] = [1000] * len(by[t]["c"])
    by["A0"]["c"] = [100 + 3 * i for i in range(MIN_BARS + 1)]      # 그룹 내 최강
    sh = {t: {"shares": 1, "asOf": "20260101", "unverified": None} for t in by if by[t]["market"] == "KR"}
    sh["A0"] = {"shares": 100, "asOf": "20260101", "unverified": None}
    o2 = build({"byTicker": by}, sec, shares_by_ticker=sh)
    a2 = next(g for g in o2["groups"] if g["group"] == g0)
    assert a2["capCoverage"]["3m"] == 1.0 and a2["tvCoverage"]["3m"] == 1.0
    assert a2["capTop"]["ticker"] == "A0" and a2["capTopWeight"] > 0.9
    assert a2["capRet"]["3m"] > a2["ret"]["3m"], (a2["capRet"], a2["ret"])   # 대형주가 끌어올린다
    assert o2["capBenchmark"]["3m"] is not None and o2["tvBenchmark"]["3m"] is not None

    # UNVERIFIED 종목은 CAP 분자·분모 양쪽에서 빠지고 커버리지에 드러난다
    sh["A0"] = {"shares": 100, "asOf": "20260101", "unverified": "SHARES_JUMP"}
    o3 = build({"byTicker": by}, sec, shares_by_ticker=sh)
    a3 = next(g for g in o3["groups"] if g["group"] == g0)
    assert a3["capCoverage"]["3m"] == 0.8, a3["capCoverage"]
    assert a3["capTop"]["ticker"] != "A0"
    assert any(u["ticker"] == "A0" for u in o3["sharesUnverified"])
    assert a3["capRet"]["3m"] < a2["capRet"]["3m"]      # 대형주가 빠지면 값이 내려간다

    # stale 은 경고만 하고 제외하지 않는다
    sh = {t: {"shares": 1, "asOf": "20200101", "unverified": None} for t in sh}
    o4 = build({"byTicker": by}, sec, shares_by_ticker=sh)
    a4 = next(g for g in o4["groups"] if g["group"] == g0)
    assert a4["sharesStale"] is True and a4["maxSharesStaleDays"] > STALE_WARN_DAYS
    assert a4["capCoverage"]["3m"] == 1.0, "stale 을 제외해 버렸다"

    # ── ★ EW 완전 불변 (2026-09-06) ─────────────────────────────
    # **같은 가격 입력에서 주식수만 바꿔** 비교한다. o2~o4 는 위에서 by 의 가격을
    # 한 번 바꾼 뒤에 만든 것이라 그 이전의 out 과 비교하면 안 된다(이 테스트를
    # 처음 그렇게 짰다가 스스로 걸렸다 - 기준을 잘못 잡으면 게이트가 오탐한다).
    EW_KEYS = ("ret", "rs", "accel", "breadth20", "breadth60", "quadrant", "n")
    # top/bottom 은 EW 순위지만 항목에 sharesAsOf·staleDays 가 함께 실려 있다.
    # 그건 주식수 출처에 따라 당연히 바뀌므로 EW 부분(순서·종목·수익률)만 본다.
    trim = lambda xs: [(x["ticker"], x["name"], x["ret1m"]) for x in xs]
    ew = lambda o: ({g["group"]: (tuple(g[k] for k in EW_KEYS), trim(g["top"]), trim(g["bottom"]))
                     for g in o["groups"]},
                    {k: o["benchmark"][k] for k in WINDOWS})
    o_nosh = build({"byTicker": by}, sec)              # 주식수 없음(전량 폴백 상황)
    base = ew(o_nosh)
    for other in (o2, o3, o4):
        assert ew(other) == base, "EW 값이 바뀌었다 - 이 시점에서 중단해야 한다"

    # ── resolve_shares 우선순위 (합성 fixture — 실제 종목/배율을 박지 않는다) ──
    snap = {"T1": {"listedShares": 150, "krxMarketCap": 300, "sourceDate": "20260904"}}
    a3c = {"T1": {"shares": 30, "asOf": "20260318", "unverified": None},
           "T2": {"shares": 30, "asOf": "20260318", "unverified": None},
           "T3": {"shares": 30, "asOf": "20260318", "unverified": None}}
    # T1·T2 는 배율이 크게 어긋난 상태(주식수 30 vs 참조 150 -> 비 0.2)
    # a8_ratio 는 (날짜, 배율) 시계열이다. T1·T2 는 공시일 이후에 기준이 바뀐 모양
    # (공시일 직후 0.2 였다가 사건이 지나 1.0 으로 복귀) - '최신 하나'만 보면 못 잡는다.
    a8r = {"T1": [("20260401", 0.2), ("20260814", 1.0)],
           "T2": [("20260401", 0.2), ("20260814", 1.0)],
           "T3": [("20260401", 1.001), ("20260814", 1.0)]}
    res = resolve_shares(["T1", "T2", "T3"], snap, a3c, a8r, "20260904")
    # KRX 가 있으면 A8 배율이 아무리 어긋나도 제외하지 않는다(진단으로만 남긴다)
    assert res["T1"]["source"] == "KRX" and res["T1"]["shares"] == 150
    assert res["T1"]["unverified"] is None and res["T1"]["a8Ratio"] == 1.0   # 진단은 마지막 값
    # KRX 가 없으면 A3c + A8 게이트가 걸린다
    assert res["T2"]["source"] == "A3C" and res["T2"]["unverified"] == "PRICE_BASIS_MISMATCH"
    # 배율이 허용 범위 안이면 통과
    assert res["T3"]["source"] == "A3C" and res["T3"]["unverified"] is None
    # ★ '최신 배율 하나'로 보면 1.0 이라 못 잡는다 - 공시일 이후 구간을 봐야 한다
    assert worst_ratio_since(a8r["T2"], "20260318")["ratio"] == 0.2
    assert worst_ratio_since(a8r["T2"], "20260501")["ratio"] == 1.0      # 공시가 사건 뒤면 정상
    assert worst_ratio_since(a8r["T2"], "20270101") is None              # 참조할 날 없음
    assert worst_ratio_since([], "20260318") is None
    # 공시일이 사건 이후면 기준이 같으므로 통과해야 한다
    res3 = resolve_shares(["T2"], {}, {"T2": {"shares": 30, "asOf": "20260501", "unverified": None}},
                          a8r, "20260904")
    assert res3["T2"]["unverified"] is None

    # A3c 자체 가드(SHARES_JUMP)가 A8 게이트보다 앞선다
    res2 = resolve_shares(["T2"], {}, {"T2": {"shares": 30, "asOf": "20260318", "unverified": "SHARES_JUMP"}},
                          a8r, "20260904")
    assert res2["T2"]["unverified"] == "SHARES_JUMP"
    # 어느 출처에도 없으면 아예 안 담는다(0 으로 지어내지 않는다)
    assert resolve_shares(["ZZ"], {}, {}, {}, "20260904") == {}

    # UNVERIFIED 는 분자·분모 동시 제외 - 합성 fixture 로 확인
    sh5 = {t: {"shares": 1, "asOf": "20260901", "source": "KRX", "unverified": None,
               "krxMarketCap": None, "a8Ratio": None} for t in by if by[t]["market"] == "KR"}
    sh5["A0"] = {"shares": 100, "asOf": "20260901", "source": "A3C",
                 "unverified": "PRICE_BASIS_MISMATCH", "krxMarketCap": None, "a8Ratio": 0.2}
    o5 = build({"byTicker": by}, sec, shares_by_ticker=sh5)
    assert ew(o5) == base, "EW 값이 바뀌었다"
    a5 = next(g for g in o5["groups"] if g["group"] == g0)
    assert a5["capCoverage"]["3m"] == 0.8 and a5["sharesFallbackCount"] == 1
    assert o5["sharesSourceCounts"].get("A3C") == 1
    assert any(u["ticker"] == "A0" and u["reason"] == "PRICE_BASIS_MISMATCH"
               for u in o5["sharesUnverified"])
    print("selftest ok (76건)")


if __name__ == "__main__":
    main()
