"""KRX 정보데이터시스템 PBR 월말 단면 수집 — 사전등록 findings/kr-own-pbr-band-preregistration-2026-09.md §1·§7.

수익률은 계산하지 않는다(동결 순서: 수집 → 구현 커밋 → 1회 실행). 로그인 경로(pykrx 1.2.8, KRX_ID/KRX_PW)는
비공식이라 연구 표본 수집에만 쓴다(docs/operations/data-source-availability.md 2026-09-26).

  python research/strategy-lab/collect_krx_pbr_monthly.py            # 2005-01 ~ 지난달 (재개 가능)
  python research/strategy-lab/collect_krx_pbr_monthly.py --selftest # 네트워크 없음

저장(gitignore): data/krx-pbr-history/pbr/YYYY-MM.parquet (date, ticker, BPS, PER, PBR, EPS, DIV, DPS)
커밋: data/krx-pbr-history/pbr_manifest.json (월별 행수·PBR>0 비율·sha256)
거래일 달력은 삼성전자 일별 PBR 시계열의 날짜로 만든다 — 휴장일에 단면을 요청하지 않는다(교훈81: 응답이 날짜를 안 담는다).
"""
import argparse
import hashlib
import json
import os
import sys
import time
from datetime import date
from pathlib import Path

import pandas as pd

HERE = Path(__file__).resolve().parent
REPO = HERE.parent.parent
OUT = HERE / "data" / "krx-pbr-history"
START = "2005-01"


def load_login():
    for line in (REPO / ".env").read_text(encoding="utf-8").splitlines():
        for k in ("KRX_ID", "KRX_PW"):
            if line.startswith(k + "=") and not os.environ.get(k):
                os.environ[k] = line.split("=", 1)[1].strip().strip('"')
    if not (os.environ.get("KRX_ID") and os.environ.get("KRX_PW")):
        raise SystemExit("KRX_ID/KRX_PW 가 없다 — setup-keys.bat 로 .env 에 넣는다")


def month_ends(days, start, last_month):
    """거래일 목록 → 월별 마지막 거래일. start ≤ 월 ≤ last_month."""
    s = pd.Series(pd.to_datetime(days)).sort_values()
    m = s.groupby(s.dt.strftime("%Y-%m")).max()
    return {k: v for k, v in m.items() if start <= k <= last_month}


def main_collect():
    load_login()
    from pykrx import stock  # 로그인 환경변수를 넣은 뒤 import 해야 세션이 붙는다

    (OUT / "pbr").mkdir(parents=True, exist_ok=True)
    cal = stock.get_market_fundamental_by_date("20041201", date.today().strftime("%Y%m%d"), "005930")
    if cal is None or len(cal) < 4000:
        raise SystemExit(f"거래일 달력 이상: {0 if cal is None else len(cal)}행")
    last_month = (pd.Timestamp(date.today()).to_period("M") - 1).strftime("%Y-%m")
    ends = month_ends(cal.index, START, last_month)
    todo = [k for k in ends if not (OUT / "pbr" / f"{k}.parquet").exists()]
    print(f"월말 {len(ends)}개 · 남은 {len(todo)}", flush=True)
    for i, k in enumerate(todo, 1):
        d = ends[k].strftime("%Y%m%d")
        df = stock.get_market_fundamental_by_ticker(d, market="ALL")
        if df is None or len(df) < 500:
            raise SystemExit(f"{k}({d}) 단면 행수 이상: {0 if df is None else len(df)} — 멈춘다(빈 달을 성공으로 세지 않는다)")
        df = df.reset_index().rename(columns={"티커": "ticker"})
        df.insert(0, "date", ends[k].date().isoformat())
        df.to_parquet(OUT / "pbr" / f"{k}.parquet", index=False)
        print(f"  [{i}/{len(todo)}] {k} {d}: {len(df)}행 · PBR>0 {(df['PBR'] > 0).mean():.2f}", flush=True)
        time.sleep(1.0)
    write_manifest()


def write_manifest():
    rows = {}
    for f in sorted((OUT / "pbr").glob("*.parquet")):
        df = pd.read_parquet(f)
        rows[f.stem] = {"date": df["date"].iloc[0], "rows": len(df), "pbr_pos_share": round(float((df["PBR"] > 0).mean()), 3),
                        "sha256": hashlib.sha256(f.read_bytes()).hexdigest()[:16]}
    (OUT / "pbr_manifest.json").write_text(json.dumps({"source": "pykrx 1.2.8 get_market_fundamental_by_ticker(market=ALL), 로그인",
                                                       "months": len(rows), "by_month": rows}, ensure_ascii=False, indent=1) + "\n",
                                           encoding="utf-8")
    print(f"manifest {len(rows)}개월")


def selftest():
    days = ["2005-01-28", "2005-01-31", "2005-02-28", "2005-03-30", "2005-03-31", "2004-12-30"]
    m = month_ends(days, "2005-01", "2005-02")
    assert list(m) == ["2005-01", "2005-02"] and str(m["2005-01"].date()) == "2005-01-31"
    print("collect_krx_pbr_monthly selftest: 통과")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--selftest", action="store_true")
    sys.exit(selftest() if ap.parse_args().selftest else main_collect())
