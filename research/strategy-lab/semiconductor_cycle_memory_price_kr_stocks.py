#!/usr/bin/env python3
"""메모리 가격(DRAM 대용치) → 삼성전자·SK하이닉스 주가 선행수익률.

사용자 GO(2026-09-13) — "DRAM 가격 변화가 SOXL이 아니라 개별 메모리기업
(삼성전자·SK하이닉스) 주가와 관련있는지"를 확인. `soxl-semiconductor-
industry-fundamentals-line-closure`의 REJECT(대상=SOXL)를 뒤집는 게
아니다 — 대상 자체가 다르고(개별 KR 종목), 검증하는 경제 메커니즘도
다르다(같은 산업 노출이라도 SOXL은 미국 30여개 반도체주 바스켓이라
개별 기업 신호가 희석될 수 있다는 게 이 파일럿의 전제).

★ 중요한 사실 확인: "DRAM 가격" 자체는 무료로 장기 이력을 못 구한다.
  - TrendForce/DRAMeXchange: DDR4/DDR5 spot·contract 있지만 historical
    다운로드는 유료 회원 전용(사용자가 이미 확인).
  - VLSI Market(market.vlsi.kr): DDR4/DDR5/NAND 고정가 계열이 있지만
    실측 이력이 **2025-01~2026-08(20개월)뿐**이다 — 이 배터리의 최소
    표본(min_n=20)에도 겨우 걸치는 수준이라 통계적으로 무의미. 제3자
    비공식 집계 사이트라 신뢰도도 별도 검증이 안 됐다. 채택 안 함.
  - 한국은행 ECOS 생산자물가지수(404Y016, 품목별): 실측으로 항목을
    전수 조회했는데 **"D램" 단독 품목 자체가 없다.** 메모리 관련은
    "플래시메모리"(30911202AA, NAND, 2005-01~2026-07, 259개월)뿐이고
    "시스템반도체"(30911203AA, 로직칩, 1985~)는 메모리가 아니다.

  그래서 이 파일럿은 **진짜 DRAM 가격이 아니라 두 개의 대용치**를 쓴다:
  ① ECOS 플래시메모리(NAND) PPI — 메모리는 맞지만 D램이 아니다.
  ② 기존에 이미 REJECT난 FRED 반도체 PPI(PCU3344133441) — DRAM도
     NAND도 아닌 반도체 전체 평균이지만, 이번엔 대상(005930/000660)이
     달라졌으니 재사용이지 반복이 아니다.
  둘 다 "DRAM 자체는 아니다"라는 한계를 그대로 finding에 남긴다.

대상 주가: `data/backfill/price/a2a/*.jsonl.gz`(이 저장소 KR 메인
파이프라인이 이미 수집한 일별 시세, 읽기 전용 — 신규 수집 없음, 이
스크립트는 그 디렉터리에 아무것도 쓰지 않는다).

PIT: ECOS PPI는 통계청 CPI(macro_common.CPI_LAG_DAYS=5)보다 훨씬 늦게
나온다 — 한국은행 생산자물가지수는 관례상 다음 달 12~14일 발표. 실제
발표일 캘린더는 이번 스코프에서 확인 안 함(PPI 파일럿과 동일 판단) —
**월말+20일**로 보수적 가정(FRED PPI 때와 같은 값, 같은 근거).

    python research/strategy-lab/semiconductor_cycle_memory_price_kr_stocks.py
"""
import gzip
import json
from pathlib import Path

import pandas as pd

from macro_common import ecos, fred
from soxl_leadlag_common import load_fwd_returns, run_battery

ROOT = Path(__file__).resolve().parents[2]
OUT_DIR = Path(__file__).resolve().parent / "data" / "semiconductor-cycle"
PIT_LAG_DAYS = 20
TICKERS = {"005930": "s005930", "000660": "s000660"}
FLASH_MEMORY_ITEM = "30911202AA"  # ECOS 404Y016 플래시메모리(NAND)


def load_stock_close(ticker: str) -> pd.Series:
    """data/backfill/price/a2a/{year}.jsonl.gz에서 한 종목의 일별 종가만
    뽑는다. 읽기 전용 — 이 함수는 그 경로에 아무것도 쓰지 않는다."""
    rows = []
    for path in sorted((ROOT / "data" / "backfill" / "price" / "a2a").glob("*.jsonl.gz")):
        if path.stem.startswith("price-quality"):
            continue
        with gzip.open(path, "rt", encoding="utf-8") as f:
            for line in f:
                rec = json.loads(line)
                if rec.get("ticker") == ticker:
                    rows.append((rec["date"], rec["close"]))
    s = pd.DataFrame(rows, columns=["date", "close"]).drop_duplicates("date")
    s["date"] = pd.to_datetime(s["date"])
    return s.sort_values("date").set_index("date")["close"]


def build_factor_df(rows: list[tuple[str, float]]) -> pd.DataFrame:
    """rows의 날짜는 ecos()="YYYYMM", fred()="YYYY-MM-DD" 두 형식이 섞여
    들어올 수 있다 — 길이로 판별한다(6자리 vs 10자리)."""
    df = pd.DataFrame(rows, columns=["periodEnd", "ppi"])
    fmt = "%Y%m" if len(str(df["periodEnd"].iloc[0])) == 6 else None
    df["periodEnd"] = pd.to_datetime(df["periodEnd"], format=fmt) + pd.offsets.MonthEnd(0)
    df = df.sort_values("periodEnd").reset_index(drop=True)
    df["availableFrom"] = df["periodEnd"] + pd.Timedelta(days=PIT_LAG_DAYS)
    df["ppi_yoy"] = df["ppi"].pct_change(12) * 100
    df["ppi_chg3m"] = df["ppi"].pct_change(3) * 100
    df["ppi_chg6m"] = df["ppi"].pct_change(6) * 100
    df["ppi_yoy_accel"] = df["ppi_yoy"].diff(1)
    return df


def selftest() -> int:
    fails = []

    def ck(name, cond):
        print(("ok   " if cond else "FAIL ") + name)
        if not cond:
            fails.append(name)

    close = load_stock_close("005930")
    ck("005930 종가 1000행 이상", len(close) > 1000)
    ck("종가 전부 양수", (close > 0).all())
    ck("날짜 중복 없음", not close.index.duplicated().any())

    fake_rows = [("202001", 100.0), ("202002", 101.0), ("202003", 102.0)]
    fdf = build_factor_df(fake_rows)
    ck("periodEnd가 월말로 정렬됨", (fdf["periodEnd"] == fdf["periodEnd"] + pd.offsets.MonthEnd(0)).all())
    ck("availableFrom = periodEnd+20일",
       (fdf["availableFrom"] - fdf["periodEnd"]).dt.days.eq(20).all())

    total = 5
    print(f"\nselftest {total - len(fails)}/{total}" + ("" if not fails else f"  FAILED: {fails}"))
    return 1 if fails else 0


def main():
    flash = ecos("404Y016", "M", "200501", pd.Timestamp.today().strftime("%Y%m"), FLASH_MEMORY_ITEM)
    fred_ppi = fred("PCU3344133441")

    sources = {
        "ecos_flash_nand": build_factor_df(flash),
        "fred_semiconductor_ppi": build_factor_df(fred_ppi),
    }

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    for src_name, df in sources.items():
        for ticker, prefix in TICKERS.items():
            close = load_stock_close(ticker)
            merged = load_fwd_returns(df, close, prefix)
            out = OUT_DIR / f"memory_price_{src_name}_{ticker}.parquet"
            merged.to_parquet(out, index=False)
            print(f"\n{'='*70}\n{src_name} -> {ticker} ({out.name})\n{'='*70}")
            run_battery(merged, ["ppi_yoy", "ppi_chg3m", "ppi_chg6m", "ppi_yoy_accel"],
                        target_prefix=prefix)


if __name__ == "__main__":
    import sys
    if "--selftest" in sys.argv:
        raise SystemExit(selftest())
    main()
