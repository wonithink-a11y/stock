#!/usr/bin/env python3
"""국내 상장 ETF 장기 성과 순위 — 실행 전 고정한 설계(2026-09-30). 자문 아님.

    python research/strategy-lab/etf_longterm_rank.py --selftest
    python research/strategy-lab/etf_longterm_rank.py     # -> findings/etf-longterm-rank-results-2026-09.json

입력: data/etf-ohlc/*.jsonl(KRX, 폐지 ETF 포함) · findings/etf-cross-section-universe-2026-09.csv(분류·기초지수명)
- 시작일 D0 두 개: 2016-09-21(10년) · 2021-09-21(5년). 종료 = 데이터 마지막 날(2026-09-21).
- 시작일 코호트(사후 우승자 고르기 방지): D0 에 상장돼 있고 순자산 ≥ 500억원 · 직전 20일 평균 거래대금 ≥ 1억원 · 같은 기초지수는 순자산 최대 1개.
- 분류: 국내 주식(국내주식형) · 해외 주식(사유 '해외:*') · 금(사유 '원자재·통화:골드/금현물/GOLD') · 채권(사유 '채권·금리·현금성' 또는 '수동: 채권'). 레버리지·인버스·커버드콜·리츠·합성 등 '구조가 다른 상품'은 제외.
- 수익 = NAV 기준 D0→종료(폐지된 ETF 는 마지막 NAV 까지, 표시). **분배금 미포함** — 고분배(채권·배당) ETF 는 과소.
- 지표: 연환산 수익 · 연변동성(월) · 샤프(무위험 0) · MDD · 폐지 여부. 카테고리별 상위 5 를 연환산 수익순·샤프순으로 낸다. 종합 점수는 만들지 않는다(임의 가중 방지).
- NAV 일 변동 ±30% 초과(분할 등 추정)인 ETF 는 제외하고 개수를 밝힌다.
- 한계: 과거 순위가 미래를 보장하지 않는다(앞선 시험에서 섹터 주도권 지속 근거 없음). 분배금·환·세금 미반영.
"""
from __future__ import annotations

import json
import math
import sys
from pathlib import Path

import numpy as np
import pandas as pd

LAB = Path(__file__).resolve().parent
OUT_JSON = LAB / "findings" / "etf-longterm-rank-results-2026-09.json"
STARTS = {"10y": "2016-09-21", "5y": "2021-09-21"}
END = "2026-09-21"


def load():
    recs = {}
    for f in sorted((LAB / "data" / "etf-ohlc").glob("*.jsonl")):
        with open(f, encoding="utf-8") as fh:
            for line in fh:
                if '"ISU_CD"' not in line:
                    continue
                d = json.loads(line)
                try:
                    nav = float(d["NAV"])
                except (ValueError, KeyError):
                    continue
                if nav <= 0:
                    continue
                recs.setdefault(d["ISU_CD"], {})[d["BAS_DD"]] = (nav, float(d["ACC_TRDVAL"]), float(d["INVSTASST_NETASST_TOTAMT"]), d["ISU_NM"])
    return recs


import re
NOT_EQUITY = re.compile(r"레버리지|인버스|2X|커버드콜|원유|농산물|달러|엔선물|구리|WTI|천연가스|콩|옥수수|선물\(H\)?$")


def category(reason: str, cls: str, name: str = ""):
    if cls != "국내주식형" and NOT_EQUITY.search(name or "") and (reason or "").startswith("해외"):
        return None
    if cls == "국내주식형":
        return "국내 주식"
    r = reason or ""
    if r.startswith("구조가 다른 상품"):
        return None
    if r.startswith("해외"):
        return "해외 주식"
    if r.startswith("원자재·통화:골드") or r.startswith("원자재·통화:금현물") or r.startswith("원자재·통화:GOLD"):
        return "금"
    if r.startswith("채권·금리·현금성") or r.startswith("수동: 채권"):
        return "채권"
    return None


def stats_between(series: pd.Series, d0: pd.Timestamp):
    s = series[series.index >= d0]
    if len(s) < 60:
        return None
    m = s.resample("ME").last().dropna()
    r = m.pct_change().dropna()
    yrs = (s.index[-1] - s.index[0]).days / 365.25
    wl = s / s.iloc[0]
    return dict(cagr=float(wl.iloc[-1] ** (1 / yrs) - 1), vol=float(r.std() * math.sqrt(12)),
                sharpe=float(r.mean() * 12 / (r.std() * math.sqrt(12))) if r.std() > 0 else None,
                mdd=float((wl / wl.cummax() - 1).min()), total=float(wl.iloc[-1] - 1), yrs=float(yrs))


def run():
    uni = pd.read_csv(LAB / "findings" / "etf-cross-section-universe-2026-09.csv", dtype=str, encoding="utf-8").set_index("code")
    recs = load()
    out = {"end": END}
    for tag, d0s in STARTS.items():
        d0 = pd.Timestamp(d0s)
        rows, jumps = [], 0
        for code, dd in recs.items():
            if code not in uni.index:
                continue
            cat = category(uni.at[code, "reason"], uni.at[code, "class"], next(iter(dd.values()))[3])
            if cat is None:
                continue
            ser = pd.Series({pd.Timestamp(k): v[0] for k, v in dd.items()}).sort_index()
            tv = pd.Series({pd.Timestamp(k): v[1] for k, v in dd.items()}).sort_index()
            na = pd.Series({pd.Timestamp(k): v[2] for k, v in dd.items()}).sort_index()
            if ser.index[0] > d0 + pd.Timedelta(days=7):
                continue
            base = ser[ser.index <= d0]
            if base.empty:
                continue
            d_start = base.index[-1]
            if na[na.index <= d0].iloc[-1] < 5e10 or tv[(tv.index <= d0)].tail(20).mean() < 1e8:
                continue
            if ser.pct_change().abs().max() > 0.30:
                jumps += 1
                continue
            st = stats_between(ser, d_start)
            if st is None:
                continue
            idx = str(uni.at[code, "index_names"]).split("|")[0].strip()
            rows.append(dict(code=code, name=dd[max(dd)][3], cat=cat, index=idx, nav0_eok=float(na[na.index <= d0].iloc[-1] / 1e8),
                             alive=bool(ser.index[-1] >= pd.Timestamp(END)), last=str(ser.index[-1].date()), **st))
        df = pd.DataFrame(rows)
        df = df.sort_values("nav0_eok", ascending=False).drop_duplicates("index")
        res = {"n": len(df), "excluded_jump": jumps, "cats": {}}
        for cat, g in df.groupby("cat"):
            def top(k, asc=False):
                return g.sort_values(k, ascending=asc).head(5)[["code", "name", "cagr", "vol", "sharpe", "mdd", "nav0_eok", "alive"]].to_dict("records")
            res["cats"][cat] = dict(n=len(g), delisted=int((~g.alive).sum()), median_cagr=float(g.cagr.median()), mean_cagr=float(g.cagr.mean()),
                                    top_cagr=top("cagr"), top_sharpe=top("sharpe"), worst_cagr=top("cagr", True))
        bm = df[df.code == "069500"]
        res["kodex200"] = bm[["cagr", "vol", "sharpe", "mdd"]].to_dict("records")
        out[tag] = res
    out["core"] = core_table()
    OUT_JSON.write_text(json.dumps(out, ensure_ascii=False, indent=1, default=float), encoding="utf-8")
    print("wrote", OUT_JSON)


CORE = re.compile(r"S&P ?500|NASDAQ.?100|나스닥 ?100|Nasdaq", re.I)
CORE_X = re.compile(r"레버리지|인버스|2X|커버드콜|혼합|채권|배당|동일|위클리|프리미엄|타겟|ESG|Value|Growth|TOP|Top|고배당|모멘텀|퀄리티|Quality|엔화|빅테크|반도체|헬스|바이오", re.I)


def core_table():
    """S&P500·나스닥100 국내 상장 ETF — 코호트 규모 조건 없이 상장 후 자료로(핵심 관심 대상). 공통 5년(2021-09-21~)·10년(2016-09-21~) 창."""
    uni = pd.read_csv(LAB / "findings" / "etf-cross-section-universe-2026-09.csv", dtype=str, encoding="utf-8").set_index("code")
    recs = load()
    rows = []
    for code, dd in recs.items():
        if code not in uni.index:
            continue
        idxn = str(uni.at[code, "index_names"])
        nm = next(iter(dd.values()))[3]
        if not CORE.search(idxn) or CORE_X.search(nm):
            continue
        ser = pd.Series({pd.Timestamp(k): v[0] for k, v in dd.items()}).sort_index()
        tv = pd.Series({pd.Timestamp(k): v[1] for k, v in dd.items()}).sort_index()
        na = pd.Series({pd.Timestamp(k): v[2] for k, v in dd.items()}).sort_index()
        if ser.pct_change().abs().max() > 0.30:
            continue
        row = dict(code=code, name=dd[max(dd)][3], index=idxn.split("|")[0].strip(), first=str(ser.index[0].date()), alive=bool(ser.index[-1] >= pd.Timestamp(END)),
                   nav_eok=float(na.iloc[-1] / 1e8), tv20_eok=float(tv.tail(20).mean() / 1e8))
        for tag, d0s in STARTS.items():
            d0 = pd.Timestamp(d0s)
            if ser.index[0] <= d0 + pd.Timedelta(days=7):
                st = stats_between(ser, ser[ser.index <= d0].index[-1])
                row[tag] = st
        if ser.index[0] < pd.Timestamp("2021-09-21"):
            row["since_listing"] = stats_between(ser, ser.index[0])
        rows.append(row)
    return rows


def selftest():
    s = pd.Series(np.linspace(100, 200, 800), index=pd.bdate_range("2020-01-01", periods=800))
    st = stats_between(s, s.index[0])
    assert st["cagr"] > 0.2 and st["mdd"] == 0.0
    assert category("해외:미국", "제외", "TIGER 미국S&P500") == "해외 주식" and category("해외:미국", "제외", "KIWOOM 미국달러선물레버리지") is None
    assert category("해외:미국", "제외") == "해외 주식" and category("구조가 다른 상품:레버리지", "제외") is None
    assert category("", "국내주식형") == "국내 주식" and category("수동: 채권(x)", "제외") == "채권"
    print("selftest ok")


if __name__ == "__main__":
    selftest() if "--selftest" in sys.argv else run()
