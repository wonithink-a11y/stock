"""KRX 정보데이터시스템 PER/PBR/BPS 정찰 — 2016 이전 국내 PBR 이력을 받을 수 있는가(2026-09-26).

동기: '자기 과거 대비 PBR 밴드' 가설을 국내에서 시험하려면 2016 이전 PBR 이 새 표본으로 필요하다.
KRX 공식 Open API(stk_bydd_trd)는 2010~ 이고 PER/PBR 필드가 없다(같은 날 실측). 2026-08-05 실측에서
PER/PBR 은 로그인 없이 차단 — 로그인 세션(pykrx 1.2.8, KRX_ID/KRX_PW)으로는 재확인한 적 없다.

확인하는 것(아무것도 커밋하지 않는다 — 결과는 artifact JSON 만):
  1. 개별종목 시계열: 얼마나 과거부터 · 어떤 열
  2. 과거 날짜의 전종목 단면: 행 수(지금은 없는 종목 포함 여부 = 생존편향)
  3. BPS 가 바뀌는 날짜 — 결산 공시(3월 말) 뒤인가, 연초인가(PIT 인가)
"""
import json
import os
import traceback

from pykrx import stock

OUT = "probe-fundamental-krx-result.json"
res = {"login": bool(os.environ.get("KRX_ID"))}


def rec(name, fn):
    try:
        res[name] = fn()
    except Exception as e:  # 정찰 — 실패도 결과다
        res[name] = {"error": f"{type(e).__name__}: {e}", "trace": traceback.format_exc()[-600:]}
    print(name, json.dumps(res[name], ensure_ascii=False, default=str)[:900], flush=True)


def series(tk):
    df = stock.get_market_fundamental_by_date("20000101", "20161231", tk)
    if df is None or df.empty:
        return {"rows": 0}
    bps = df["BPS"]
    changes = [str(d.date()) for d, v, p in zip(df.index[1:], bps.values[1:], bps.values[:-1]) if v != p]
    return {"rows": len(df), "first": str(df.index.min().date()), "last": str(df.index.max().date()),
            "columns": list(df.columns), "pbr_nonzero": int((df["PBR"] > 0).sum()),
            "bps_change_dates": changes[:40], "head": df.head(2).reset_index().astype(str).to_dict("records")}


def snapshot(d):
    df = stock.get_market_fundamental_by_ticker(d, market="ALL")
    if df is None or df.empty:
        return {"rows": 0}
    return {"rows": len(df), "columns": list(df.columns), "pbr_positive": int((df["PBR"] > 0).sum()),
            "sample": df.head(3).reset_index().astype(str).to_dict("records")}


rec("series_005930", lambda: series("005930"))
rec("series_000660", lambda: series("000660"))
for d in ("20050103", "20100104", "20150102"):
    rec(f"snapshot_{d}", lambda d=d: snapshot(d))

with open(OUT, "w", encoding="utf-8") as f:
    json.dump(res, f, ensure_ascii=False, indent=2, default=str)
