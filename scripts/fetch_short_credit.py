#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
fetch_short_credit.py (v1.0)

한국 관심종목의 **공매도 잔고·거래 비중**과 (가능하면) **신용융자 잔고**를 수집해
docs/data/short_credit.json 으로 저장합니다. 대시보드의 리스크 지표용입니다.

── 왜 필요한가 ────────────────────────────────────────────────────
공매도 잔고비중이 높은 종목은 (1) 하락에 베팅한 자금이 쌓여 있다는 뜻이고,
(2) 반대로 급등 시 숏커버링으로 과열될 수 있습니다. 방향을 단정하는 신호가 아니라
"이 종목은 지금 양방향 변동성이 크다"는 **맥락**입니다.
신용융자 잔고는 반대매매 위험 — 급락 시 강제청산이 하락을 증폭시킵니다.

── 데이터 소스 ────────────────────────────────────────────────────
 공매도: pykrx (KRX). 로그인 불필요하나 KRX_ID/KRX_PW 가 있으면 함께 씁니다.
 신용융자: pykrx 미지원. KRX getJsonData 직접 호출을 **best-effort** 로 시도하고,
          실패하면 결측으로 남깁니다(워크플로를 실패시키지 않음).
          프로젝트 교훈 #4 — getJsonData 파라미터가 까다로워 확실치 않은 경로는
          '되면 좋고' 로 취급하고, 안 되면 조용히 채우지 않습니다.

⚠ 공매도 잔고는 T+2 공시라 최신일이 2~3영업일 전입니다. 거래량은 T+1 입니다.
   "오늘 데이터가 없다"가 아니라 제도상 정상입니다.

── 사용법 ─────────────────────────────────────────────────────────
   python scripts/fetch_short_credit.py
   python scripts/fetch_short_credit.py --days 30 --only 005930,000660
   python scripts/fetch_short_credit.py --with-credit     # 신용융자 시도(기본 off)
   python scripts/fetch_short_credit.py --selftest        # 네트워크 없이 계산식 검증
"""

import argparse
import json
import os
import sys
import time
import datetime as dt
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
WATCHLIST_PATH = ROOT / "config" / "watchlist.json"
OUT_PATH = ROOT / "docs" / "data" / "short_credit.json"

SLEEP_SEC = float(os.environ.get("SHORT_SLEEP", "0.4"))

# 경고 임계값 — 절대적 기준은 없습니다. 한국 시장에서 잔고비중 3%면 상위권,
# 5% 이상이면 확실히 눈에 띄는 수준이라는 경험적 선입니다. 점수에는 반영하지 않고
# 대시보드 경고로만 씁니다(검증되지 않은 지표를 점수에 넣지 않는다는 원칙).
WARN_BALANCE_RATIO = 3.0
DANGER_BALANCE_RATIO = 5.0
WARN_VOLUME_RATIO = 15.0  # 당일 거래량 중 공매도 비중(%)


# ════════════════════════════════════════════════════════════════
# 계산 유틸 (순수 함수 — --selftest 로 검증)
# ════════════════════════════════════════════════════════════════

def r2(x, nd=2):
    if x is None:
        return None
    try:
        f = float(x)
        if f != f:  # NaN
            return None
    except (TypeError, ValueError):
        return None
    return round(f, nd)


def pick_col(df, candidates):
    """pykrx 컬럼명이 버전마다 달라 후보 목록에서 먼저 있는 것을 씁니다."""
    if df is None or getattr(df, "empty", True):
        return None
    for c in candidates:
        if c in df.columns:
            return c
    return None


def series_to_days(df, col_map):
    """
    DataFrame → [{date, ...}] (과거→최신). col_map: {출력키: 실제컬럼명}
    인덱스가 날짜라고 가정하며, 없는 컬럼은 None 으로 채웁니다.
    """
    out = []
    if df is None or getattr(df, "empty", True):
        return out
    for idx, row in df.iterrows():
        d = str(idx)[:10].replace("-", "")
        item = {"date": d}
        for k, col in col_map.items():
            item[k] = r2(row[col]) if col and col in df.columns else None
        out.append(item)
    return out


def summarize(days):
    """
    일별 시계열 → 요약 지표.
      balanceRatio      최신 공매도 잔고비중(%)
      balanceRatio20dAgo / change20d  20영업일 전 대비 증감(%p)  ← 추세가 수준보다 중요
      volRatio5d        최근 5일 공매도 거래비중 평균(%)
    """
    out = {
        "balanceRatio": None,
        "balanceRatio20dAgo": None,
        "balanceChange20dPP": None,
        "volRatio5d": None,
        "lastDate": None,
    }
    if not days:
        return out
    out["lastDate"] = days[-1]["date"]

    br = [d.get("balanceRatio") for d in days if d.get("balanceRatio") is not None]
    if br:
        out["balanceRatio"] = br[-1]
        if len(br) >= 21:
            out["balanceRatio20dAgo"] = br[-21]
            out["balanceChange20dPP"] = r2(br[-1] - br[-21])
        elif len(br) >= 2:
            out["balanceRatio20dAgo"] = br[0]
            out["balanceChange20dPP"] = r2(br[-1] - br[0])

    vr = [d.get("volRatio") for d in days if d.get("volRatio") is not None]
    if vr:
        last5 = vr[-5:]
        out["volRatio5d"] = r2(sum(last5) / len(last5))
    return out


def build_flags(summary):
    """경고 태그. 점수가 아니라 '함께 읽어야 할 맥락'입니다."""
    flags = []
    br = summary.get("balanceRatio")
    ch = summary.get("balanceChange20dPP")
    vr = summary.get("volRatio5d")
    if br is not None:
        if br >= DANGER_BALANCE_RATIO:
            flags.append("shortBalanceHigh")
        elif br >= WARN_BALANCE_RATIO:
            flags.append("shortBalanceElevated")
    if ch is not None and ch >= 1.0:
        flags.append("shortBalanceRising")
    if ch is not None and ch <= -1.0:
        flags.append("shortCovering")
    if vr is not None and vr >= WARN_VOLUME_RATIO:
        flags.append("shortVolumeHeavy")
    return flags


# ════════════════════════════════════════════════════════════════
# 수집
# ════════════════════════════════════════════════════════════════

def load_kr_tickers(only=None):
    wl = json.loads(WATCHLIST_PATH.read_text(encoding="utf-8"))
    items = [t for t in wl.get("tickers", []) if (t.get("market") or "KR") == "KR"]
    if only:
        want = {c.strip() for c in only.split(",") if c.strip()}
        items = [t for t in items if t["code"] in want]
    return items


def fetch_one(stock, code, fromdate, todate):
    """공매도 잔고 + 거래량 시계열. 실패한 쪽은 빈 리스트."""
    bal_days, vol_days = [], []

    try:
        df = stock.get_shorting_balance_by_date(fromdate, todate, code)
        col_ratio = pick_col(df, ["비중", "공매도잔고비중", "잔고비중"])
        col_qty = pick_col(df, ["공매도잔고", "잔고수량", "공매도 잔고"])
        bal_days = series_to_days(df, {"balanceRatio": col_ratio, "balanceQty": col_qty})
    except Exception as e:
        print(f"    [경고] {code} 공매도 잔고 실패: {type(e).__name__} {e}")

    try:
        df = stock.get_shorting_volume_by_date(fromdate, todate, code)
        col_ratio = pick_col(df, ["비중", "공매도비중"])
        col_vol = pick_col(df, ["공매도", "공매도거래량", "공매도 거래량"])
        vol_days = series_to_days(df, {"volRatio": col_ratio, "shortVolume": col_vol})
    except Exception as e:
        print(f"    [경고] {code} 공매도 거래량 실패: {type(e).__name__} {e}")

    # 두 시계열을 날짜 기준으로 병합
    merged = {}
    for d in bal_days:
        merged.setdefault(d["date"], {"date": d["date"]}).update(
            {"balanceRatio": d.get("balanceRatio"), "balanceQty": d.get("balanceQty")}
        )
    for d in vol_days:
        merged.setdefault(d["date"], {"date": d["date"]}).update(
            {"volRatio": d.get("volRatio"), "shortVolume": d.get("shortVolume")}
        )
    return [merged[k] for k in sorted(merged)]


def fetch_credit_balance(codes):
    """
    신용융자 잔고 — pykrx 미지원이라 KRX getJsonData 를 직접 시도합니다(best-effort).
    bld 코드가 KRX 개편으로 바뀌면 실패하며, 그 경우 결측으로 남깁니다.
    성공 여부를 _diagnostics.creditSource 에 남겨 나중에 원인을 추적할 수 있게 합니다.
    """
    import urllib.request
    import urllib.parse

    url = "http://data.krx.co.kr/comm/bldAttendant/getJsonData.cmd"
    today = dt.date.today()
    # 최근 영업일을 정확히 모르므로 며칠 거슬러 올라가며 시도합니다.
    for back in range(1, 8):
        d = (today - dt.timedelta(days=back)).strftime("%Y%m%d")
        for bld in ("dbms/MDC/STAT/standard/MDCSTAT02501", "dbms/MDC/STAT/srt/MDCSTAT30301"):
            try:
                data = urllib.parse.urlencode(
                    {"bld": bld, "locale": "ko_KR", "trdDd": d, "share": "1", "money": "1", "csvxls_isNo": "false"}
                ).encode()
                req = urllib.request.Request(
                    url,
                    data=data,
                    headers={
                        "User-Agent": "Mozilla/5.0",
                        "Referer": "http://data.krx.co.kr/contents/MDC/MDI/mdiLoader/index.cmd",
                        "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
                    },
                )
                with urllib.request.urlopen(req, timeout=20) as res:
                    j = json.loads(res.read().decode("utf-8"))
                rows = j.get("OutBlock_1") or j.get("output") or []
                if not rows:
                    continue
                out = {}
                for r in rows:
                    code = str(r.get("ISU_SRT_CD") or r.get("ISU_CD") or "").strip()
                    if code in codes:
                        out[code] = {
                            "creditBalanceQty": r2(str(r.get("LOAN_BAL_QTY", "")).replace(",", "") or None, 0),
                            "creditBalanceRatio": r2(str(r.get("LOAN_BAL_RTO", "")).replace(",", "") or None),
                            "date": d,
                        }
                if out:
                    print(f"  신용융자 수집 성공: bld={bld}, 기준일={d}, {len(out)}종목")
                    return out, f"{bld}@{d}"
            except Exception:
                continue
    print("  [정보] 신용융자 수집 실패 — 결측으로 둡니다(bld 코드 변경 가능)")
    return {}, None


# ════════════════════════════════════════════════════════════════
# 메인
# ════════════════════════════════════════════════════════════════

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--days", type=int, default=40, help="조회 기간(달력일). 기본 40 ≈ 영업일 27")
    ap.add_argument("--only", help="쉼표로 구분한 종목코드만")
    ap.add_argument("--with-credit", action="store_true", help="신용융자 잔고 수집 시도")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--selftest", action="store_true")
    args = ap.parse_args()

    if args.selftest:
        return selftest()

    from pykrx import stock

    tickers = load_kr_tickers(args.only)
    if not tickers:
        print("한국 종목이 watchlist 에 없습니다.")
        return 0

    todate = dt.date.today().strftime("%Y%m%d")
    fromdate = (dt.date.today() - dt.timedelta(days=args.days)).strftime("%Y%m%d")
    print(f"공매도 수집: {len(tickers)}종목, {fromdate}~{todate}")

    by_ticker = {}
    failed = []
    for i, t in enumerate(tickers, 1):
        code, name = t["code"], t.get("name", t["code"])
        days = fetch_one(stock, code, fromdate, todate)
        summary = summarize(days)
        flags = build_flags(summary)
        by_ticker[code] = {
            "name": name,
            **summary,
            "flags": flags,
            # 파일 크기를 위해 최근 20영업일만 보관 (대시보드 스파크라인용)
            "days": days[-20:],
        }
        if summary["balanceRatio"] is None:
            failed.append(code)
        if i % 20 == 0 or i == len(tickers):
            print(f"  [{i}/{len(tickers)}] 진행")
        time.sleep(SLEEP_SEC)

    credit, credit_src = ({}, None)
    if args.with_credit:
        credit, credit_src = fetch_credit_balance(set(by_ticker))
        for code, c in credit.items():
            by_ticker[code].update(c)

    # 상위 노출용 랭킹 — 대시보드에서 "지금 공매도가 몰린 종목"을 바로 보기 위한 것
    ranked = sorted(
        [
            {"code": k, "name": v["name"], "balanceRatio": v["balanceRatio"], "flags": v["flags"]}
            for k, v in by_ticker.items()
            if v["balanceRatio"] is not None
        ],
        key=lambda x: x["balanceRatio"],
        reverse=True,
    )[:15]

    out = {
        "updatedAt": dt.datetime.utcnow().isoformat() + "Z",
        "note": "공매도 잔고는 T+2 공시라 최신일이 2~3영업일 전입니다. 점수에는 반영되지 않는 맥락 지표입니다.",
        "thresholds": {
            "warnBalanceRatio": WARN_BALANCE_RATIO,
            "dangerBalanceRatio": DANGER_BALANCE_RATIO,
            "warnVolumeRatio": WARN_VOLUME_RATIO,
        },
        "topShorted": ranked,
        "byTicker": by_ticker,
        "_diagnostics": {
            "requested": len(tickers),
            "withBalance": len(tickers) - len(failed),
            "failed": failed[:30],
            "creditSource": credit_src,
            "creditCount": len(credit),
        },
    }

    print(f"\n완료: 잔고 {len(tickers) - len(failed)}/{len(tickers)}종목")
    if ranked:
        print("공매도 잔고비중 상위 5:")
        for r in ranked[:5]:
            print(f"  {r['name']}({r['code']}) {r['balanceRatio']}%  {','.join(r['flags'])}")
    if failed:
        print(f"⚠ 잔고 결측 {len(failed)}종목: {', '.join(failed[:10])}")

    if args.dry_run:
        print("\n--dry-run: 저장 생략")
        return 0

    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUT_PATH.write_text(json.dumps(out, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"\n→ {OUT_PATH.relative_to(ROOT)}")
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

    print("요약 계산 검증")
    days = [{"date": f"2026070{i}", "balanceRatio": 1.0 + i * 0.1, "volRatio": 10.0 + i} for i in range(1, 9)]
    s = summarize(days)
    check("최신 잔고비중", s["balanceRatio"], 1.8)
    check("최초 대비 증감(표본<21)", s["balanceChange20dPP"], 0.7)
    check("5일 공매도 거래비중 평균", s["volRatio5d"], 16.0)
    check("lastDate", s["lastDate"], "20260708")

    print("\n20영업일 이상 표본")
    days21 = [{"date": str(20260600 + i), "balanceRatio": 2.0 + i * 0.05} for i in range(1, 25)]
    s2 = summarize(days21)
    check("20일 전 값 사용", s2["balanceRatio20dAgo"], round(2.0 + 4 * 0.05, 2))
    check("증감 = 최신-20일전", s2["balanceChange20dPP"], 1.0)

    print("\n경고 플래그")
    check("5% 이상", build_flags({"balanceRatio": 5.2, "balanceChange20dPP": 0, "volRatio5d": 1}), ["shortBalanceHigh"])
    check("3~5%", build_flags({"balanceRatio": 3.4, "balanceChange20dPP": 0, "volRatio5d": 1}), ["shortBalanceElevated"])
    check(
        "증가 + 거래비중 과다",
        build_flags({"balanceRatio": 1.0, "balanceChange20dPP": 1.5, "volRatio5d": 20.0}),
        ["shortBalanceRising", "shortVolumeHeavy"],
    )
    check("숏커버링", build_flags({"balanceRatio": 1.0, "balanceChange20dPP": -1.4, "volRatio5d": 5}), ["shortCovering"])
    check("정상", build_flags({"balanceRatio": 0.5, "balanceChange20dPP": 0.1, "volRatio5d": 5}), [])
    check("결측이면 플래그 없음", build_flags({"balanceRatio": None, "balanceChange20dPP": None, "volRatio5d": None}), [])

    print("\n결측 안전성")
    check("빈 시계열", summarize([])["balanceRatio"], None)
    check("NaN 처리", r2(float("nan")), None)

    print("\n" + ("전체 통과" if ok else "실패 항목 있음"))
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
