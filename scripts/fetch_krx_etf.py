#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
KRX Open API로 ETF/ETN/금시장 스냅샷을 받아 docs/data/etf_snapshot.json을
만든다. fetch_macro.py의 KOSPI200 선물과 같은 인증키(KRX_OPENAPI_KEY,
AUTH_KEY 헤더) 재사용 - 별도 발급 불필요.

이 데이터는 지표(gauge)가 아니라 표(table)라 macro.json과 성격이 달라
별도 스크립트·파일로 분리했다. 각 API가 하루 스냅샷만 주므로(과거 조회 없음)
이력 누적도 안 한다 - 매일 그날 값만 정직하게 보여준다.

  python fetch_krx_etf.py
"""
import json
import os
import ssl
import sys
import urllib.request
from datetime import date, timedelta

UA = "Mozilla/5.0 (etf-fetch; +https://github.com)"
CTX = ssl.create_default_context()
OUT = "docs/data/etf_snapshot.json"
KEY = os.environ.get("KRX_OPENAPI_KEY", "")

# 관심종목 - 사용자 확정 목록(2026-08-27). 코스피/코스닥 대표 + 미국 3대
# 노출(S&P500·나스닥100·배당다우존스=SCHD 클론) + 반도체(regime.json의 수동
# "반도체 업황 사이클" 필드를 자동 지표로 보완) + 매그니피센트7
CURATED_ETF = [
    ("069500", "KODEX 200"),
    ("229200", "KODEX 코스닥150"),
    ("360750", "TIGER 미국S&P500"),
    ("133690", "TIGER 미국나스닥100"),
    ("458730", "TIGER 미국배당다우존스"),
    ("381180", "TIGER 미국필라델피아반도체나스닥"),
    ("465580", "ACE 미국빅테크TOP7 Plus"),
]
# VIX ETN 기본(1x)+인버스(-0.5x) 1개씩 - "반대로 움직이는지" 눈으로 보는
# 용도라 발행사 통일보다 실측 유동성이 나은 쪽을 골랐다(2026-08-27 확정)
CURATED_ETN = [
    ("500095", "신한 VIX ETN (정방향)"),   # 신한 S&P500 VIX S/T선물 ETN E -
                                            # research/strategy-lab/findings/
                                            # vix-domestic-etn-etf-data-
                                            # source-2026-08.md 에서 기검증
    ("530131", "삼성 VIX ETN (인버스0.5X)"),  # 삼성 인버스0.5X S&P500 VIX S/T선물 ETN B
]
GOLD_CODE = "04020000"   # 금 99.99_1kg


def krx_get(path, bas_dd):
    req = urllib.request.Request(
        "https://data-dbg.krx.co.kr/svc/apis/" + path + "?basDd=" + bas_dd,
        headers={"AUTH_KEY": KEY, "User-Agent": UA})
    with urllib.request.urlopen(req, timeout=20, context=CTX) as r:
        return json.loads(r.read().decode("utf-8")).get("OutBlock_1") or []


def biz_days(n=5):
    out, d = [], date.today()
    while len(out) < n:
        if d.weekday() < 5:
            out.append(d.strftime("%Y%m%d"))
        d -= timedelta(days=1)
    return out


def fetch_first_nonempty(path):
    """최근 영업일부터 거슬러 올라가며 첫 비어있지 않은 응답(휴장일 skip)."""
    for bas_dd in biz_days():
        rows = krx_get(path, bas_dd)
        if rows:
            return bas_dd, rows
    return None, []


def row_summary(r):
    return {
        "code": r.get("ISU_CD"),
        "name": r.get("ISU_NM"),
        "close": r.get("TDD_CLSPRC"),
        "change": r.get("CMPPREVDD_PRC"),
        "pct": r.get("FLUC_RT"),
        "volume": r.get("ACC_TRDVOL"),
        "value": r.get("ACC_TRDVAL"),
    }


def main():
    if not KEY:
        print("KRX_OPENAPI_KEY not set", file=sys.stderr)
        sys.exit(1)

    bas_dd, etf_rows = fetch_first_nonempty("etp/etf_bydd_trd")
    by_code = {r["ISU_CD"]: r for r in etf_rows}
    curated = []
    for code, label in CURATED_ETF:
        r = by_code.get(code)
        if r:
            s = row_summary(r)
            s["label"] = label
            curated.append(s)
        else:
            print("curated ETF missing:", code, label, file=sys.stderr)

    ranked = sorted(etf_rows, key=lambda r: float(r.get("ACC_TRDVAL") or 0), reverse=True)
    top50 = [row_summary(r) for r in ranked[:50]]

    _, etn_rows = fetch_first_nonempty("etp/etn_bydd_trd")
    etn_by_code = {r["ISU_CD"]: r for r in etn_rows}
    vix_etns = []
    for code, label in CURATED_ETN:
        r = etn_by_code.get(code)
        if r:
            s = row_summary(r)
            s["label"] = label
            vix_etns.append(s)
        else:
            print("curated ETN missing:", code, label, file=sys.stderr)

    _, gold_rows = fetch_first_nonempty("gen/gold_bydd_trd")
    gold = next((row_summary(r) for r in gold_rows if r.get("ISU_CD") == GOLD_CODE), None)

    data = {
        "updatedAt": bas_dd,
        "curated": curated,
        "top50": top50,
        "vixEtn": vix_etns,
        "gold": gold,
    }
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    with open(OUT, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    print("wrote %s (curated=%d, top50=%d, vixEtn=%d, gold=%s)" %
          (OUT, len(curated), len(top50), len(vix_etns), bool(gold)))


if __name__ == "__main__":
    main()
