#!/usr/bin/env python3
"""build-market-breadth.py — 국내 시장 심리 맥락 4항목 → docs/data/market-breadth.json

**합산 점수 없음 · 매매 신호 아님.** 시장 타이밍 규칙은 이 저장소에서 여섯 갈래 모두 근거가 없었다
(findings/fear-position-sizing-overlay-2026-08.md 등). 항목마다 '이력 중 지금 위치'만 보여 준다.

대상: KRX 코스피+코스닥 보통주(우선주·스팩 제외, build-market-movers.py 와 같은 판정). 가격은 KRX FLUC_RT 를 누적한
지수라 액면분할에 흔들리지 않는다. 폐지 종목도 상장 기간에는 들어간다(생존편향 없음).
  adv1 / adv20  상승 종목 비율 = FLUC_RT > 0 ÷ 거래된 종목(거래대금 > 0). adv20 = 20거래일 평균(위치는 adv20 으로)
  above200      200일 이동평균 위 종목 비율(직전 200거래일 모두 값이 있는 종목)
  nh / nl       종가 기준 52주 신고가·신저가 = 직전 250거래일(240일 이상 값) 최고 이상·최저 이하. 위치는 적격 종목 대비 비율로
  rv20          코스피 시총가중(전일 시총) 일수익의 20거래일 실현 변동성, 연율
위치(pct) = 이력(최근 10년, 2017-02 부터) 중 오늘 값 이하인 날의 비율.

  이력  data/market-breadth/history.json (커밋, 하루 한 줄)
  패널  .cache/market-breadth/panel.parquet (Actions 캐시 — 최근 320거래일. 없으면 KRX 에서 다시 받는다, 약 640콜)
    python scripts/build-market-breadth.py --seed DIR   # DIR/*.parquet(collect_krx_daily_ext.py 산출) 전체로 이력을 처음부터
    python scripts/build-market-breadth.py              # 패널 증분(KRX_OPENAPI_KEY) + 이력 추가 + 화면 파일
    python scripts/build-market-breadth.py --selftest
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import os
import sys
import time
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
HIST = ROOT / "data" / "market-breadth" / "history.json"
PANEL = ROOT / ".cache" / "market-breadth" / "panel.parquet"
OUT = ROOT / "docs" / "data" / "market-breadth.json"
KST = timezone(timedelta(hours=9))
COLS = ["d", "adv1", "adv20", "above200", "n200", "nh", "nl", "n52", "rv20"]
KEEP_ROWS = 320          # 패널에 남길 거래일(52주 250 + 여유)
WARM = 260               # 이보다 앞선 날은 지표가 덜 데워져 이력에 안 넣는다
SERIES_DAYS = 250

spec = importlib.util.spec_from_file_location("mm", ROOT / "scripts" / "build-market-movers.py")
mm = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mm)


def compute(panel):
    """panel: BAS_DD·ISU_CD·ISU_NM·FLUC_RT·ACC_TRDVAL·MKTCAP·market → 날짜별 지표(덜 데워진 앞 WARM 행 제외)."""
    p = panel[[not mm.is_preferred(c) and not mm.is_spac(n or "") for c, n in zip(panel.ISU_CD, panel.ISU_NM)]].copy()
    p["d"] = pd.to_datetime(p.BAS_DD.astype(str))
    for c in ("FLUC_RT", "ACC_TRDVAL", "MKTCAP"):
        p[c] = pd.to_numeric(p[c], errors="coerce")
    ret = p.pivot_table(index="d", columns="ISU_CD", values="FLUC_RT", aggfunc="last") / 100
    tv = p.pivot_table(index="d", columns="ISU_CD", values="ACC_TRDVAL", aggfunc="last").reindex_like(ret)
    traded = ret.notna() & (tv > 0)
    adv1 = ((ret > 0) & traded).sum(axis=1) / traded.sum(axis=1).replace(0, np.nan)
    idx = (1 + ret.fillna(0)).cumprod().where(ret.notna())
    ma = idx.rolling(200, min_periods=200).mean()
    e200 = idx.notna() & ma.notna()
    hi = idx.rolling(250, min_periods=240).max().shift(1)
    lo = idx.rolling(250, min_periods=240).min().shift(1)
    e52 = idx.notna() & hi.notna()
    k = p[p.market == "KOSPI"]
    cap = k.pivot_table(index="d", columns="ISU_CD", values="MKTCAP", aggfunc="last").reindex(ret.index)
    kr = ret.reindex(columns=cap.columns)
    w = cap.shift(1).where(kr.notna())
    mret = (w * kr).sum(axis=1) / w.sum(axis=1).replace(0, np.nan)
    out = pd.DataFrame({
        "adv1": adv1, "adv20": adv1.rolling(20).mean(),
        "above200": ((idx > ma) & e200).sum(axis=1) / e200.sum(axis=1).replace(0, np.nan), "n200": e200.sum(axis=1),
        "nh": ((idx >= hi) & e52).sum(axis=1), "nl": ((idx <= lo) & e52).sum(axis=1), "n52": e52.sum(axis=1),
        "rv20": mret.rolling(20).std() * np.sqrt(252)})
    return out.iloc[WARM:].dropna()


def load_hist():
    if not HIST.exists():
        return pd.DataFrame(columns=COLS[1:])
    h = json.loads(HIST.read_text(encoding="utf-8"))
    return pd.DataFrame(h["rows"], columns=h["cols"]).set_index("d").rename(index=pd.Timestamp)


def save_hist(h):
    rows = [[d.strftime("%Y-%m-%d"), *[round(float(v), 5) if c not in ("n200", "nh", "nl", "n52") else int(v)
                                       for c, v in r.items()]] for d, r in h[COLS[1:]].iterrows()]
    HIST.parent.mkdir(parents=True, exist_ok=True)
    HIST.write_text(json.dumps({"cols": COLS, "rows": rows}, separators=(",", ":")) + "\n", encoding="utf-8")


def fetch(key, ymd):
    """KRX 하루치. 응답 날짜가 요청일과 다르면 버린다(교훈 81). 휴장일·아직 안 올라온 날은 빈 목록.
    시간 초과는 5번까지 다시 묻는다(첫 실행 640콜 중 한 번 끊겨 실행 전체가 죽은 실측, 2026-10-18).
    끝내 실패하면 예외 — 중간 날짜가 빠진 패널을 저장하면 200일선이 조용히 틀리므로 이어 붙이지 않는다."""
    for k in range(5):
        try:
            got = mm.fetch_day(key, ymd)
            break
        except Exception as e:
            if k == 4:
                raise
            print(f"  {ymd} 재시도 {k + 1} ({type(e).__name__})")
            time.sleep(5 * (k + 1))
    rows = [r for r in got if str(r.get("BAS_DD")) == ymd]
    return [{"BAS_DD": ymd, "ISU_CD": r.get("ISU_CD"), "ISU_NM": r.get("ISU_NM"), "FLUC_RT": mm.num(r.get("FLUC_RT")),
             "ACC_TRDVAL": mm.num(r.get("ACC_TRDVAL")), "MKTCAP": mm.num(r.get("MKTCAP")), "market": r.get("_mk")}
            for r in rows]


def update_panel(key):
    panel = pd.read_parquet(PANEL) if PANEL.exists() else None
    today = datetime.now(KST).date()
    if panel is not None and len(panel):
        d = datetime.strptime(str(panel.BAS_DD.max()), "%Y%m%d").date() + timedelta(days=1)
    else:
        d = today - timedelta(days=int(KEEP_ROWS * 1.45))
        print(f"패널 없음 — {d} 부터 다시 받는다")
    new = []
    while d <= today:
        if d.weekday() < 5:
            new += fetch(key, d.strftime("%Y%m%d"))
        d += timedelta(days=1)
    if new:
        panel = pd.concat([panel, pd.DataFrame(new)], ignore_index=True) if panel is not None else pd.DataFrame(new)
    keep = sorted(panel.BAS_DD.astype(str).unique())[-KEEP_ROWS:]
    panel = panel[panel.BAS_DD.astype(str).isin(keep)]
    PANEL.parent.mkdir(parents=True, exist_ok=True)
    panel.to_parquet(PANEL, index=False)
    print(f"패널 {len(keep)}거래일 ~{keep[-1]} (새 행 {len(new)})")
    return panel


def pct(series, v):
    s = series.dropna()
    return round(float((s <= v).mean() * 100), 1) if len(s) else None


def render(h):
    h = h[h.index >= h.index.max() - pd.DateOffset(years=10)].copy()
    h["nh_r"], h["nl_r"] = h.nh / h.n52, h.nl / h.n52
    last = h.iloc[-1]
    items = []

    def item(key, label, col, value, sub, fmt):
        s = h[col]
        items.append({"key": key, "label": label, "value": value, "sub": sub, "pct": pct(s, last[col]),
                      "min": fmt(s.min()), "median": fmt(s.median()), "max": fmt(s.max()),
                      "series": [round(float(x), 4) for x in s.iloc[-SERIES_DAYS:]]})
    p100 = lambda x: f"{x * 100:.0f}%"
    item("adv", "상승 종목 비율(20일 평균)", "adv20", p100(last.adv20), f"오늘 {last.adv1 * 100:.0f}%", p100)
    item("above200", "200일선 위 종목 비율", "above200", p100(last.above200), f"{int(last.n200):,}종목 중", p100)
    item("nh", "52주 신고가", "nh_r", f"{int(last.nh)}종목", f"적격 {int(last.n52):,}종목의 {last.nh_r * 100:.1f}%",
         lambda x: f"{x * 100:.1f}%")
    item("nl", "52주 신저가", "nl_r", f"{int(last.nl)}종목", f"적격 {int(last.n52):,}종목의 {last.nl_r * 100:.1f}%",
         lambda x: f"{x * 100:.1f}%")
    item("rv20", "코스피 실현 변동성(20일, 연율)", "rv20", p100(last.rv20), "시총가중 일수익 기준", p100)
    doc = {"asOf": h.index[-1].strftime("%Y-%m-%d"), "since": h.index[0].strftime("%Y-%m-%d"), "days": len(h),
           "note": "맥락 전용 — 합산 점수 없음, 매매 신호 아님. 위치 = 이력 중 오늘 값 이하인 날의 비율.",
           "items": items}
    OUT.write_text(json.dumps(doc, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    print(f"→ {OUT.relative_to(ROOT)} asOf {doc['asOf']} · " + " · ".join(f"{i['key']} {i['value']}({i['pct']})" for i in items))


def selftest():
    days = pd.bdate_range("2020-01-01", periods=WARM + 30)
    rows = []
    for i, d in enumerate(days):
        for c, r in (("000010", 1.0), ("000020", -1.0 if i % 2 else 0.5), ("000035", 9.0)):   # 000035 = 우선주(끝자리 5)
            rows.append({"BAS_DD": d.strftime("%Y%m%d"), "ISU_CD": c, "ISU_NM": "가", "FLUC_RT": r, "ACC_TRDVAL": 1,
                         "MKTCAP": 100, "market": "KOSPI"})
    rows.append({**rows[-1], "ISU_CD": "000040", "ISU_NM": "가나스팩1호", "FLUC_RT": 5.0})   # 스팩 제외
    o = compute(pd.DataFrame(rows))
    assert len(o) == 30, len(o)
    x = o.iloc[-1]
    assert x.n200 == 2 and x.above200 == 0.5, x             # 매일 오르는 000010 만 200일선 위
    assert x.nh == 1, x                                      # 000010 은 매일 신고가
    assert 0.5 <= x.adv1 <= 1 and x.rv20 > 0, x
    assert pct(pd.Series([1, 2, 3, 4]), 3) == 75.0
    print("selftest OK")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--seed", metavar="DIR")
    ap.add_argument("--selftest", action="store_true")
    a = ap.parse_args()
    if a.selftest:
        return selftest()
    if a.seed:
        files = sorted(Path(a.seed).glob("*.parquet"))
        h = compute(pd.concat([pd.read_parquet(f) for f in files], ignore_index=True))
        save_hist(h)
        print(f"이력 {len(h)}일 {h.index[0].date()} ~ {h.index[-1].date()} ← {len(files)}개 파일")
    else:
        key = os.environ.get("KRX_OPENAPI_KEY", "")
        if not key:
            print("KRX_OPENAPI_KEY 가 없다")
            return 1
        new = compute(update_panel(key))
        h = load_hist()
        add = new[new.index > (h.index.max() if len(h) else pd.Timestamp(0))]
        h = pd.concat([h, add]).sort_index()
        save_hist(h)
        print(f"이력 +{len(add)}일 → {len(h)}일")
    render(load_hist())


if __name__ == "__main__":
    sys.exit(main())
