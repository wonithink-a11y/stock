"""KRX Open API 일별 전종목(KOSPI·KOSDAQ, 우선주 포함) 2016-02-01 ~ 오늘 — collect_krx_daily_2010.py 의 연장(같은 요청·같은 날짜 대조).

  python research/strategy-lab/collect_krx_daily_ext.py [YYYY-MM]   # 재개 가능, 월 단위 파일(시작 월을 주면 병렬로 나눠 받을 수 있다)

저장(gitignore): data/krx-daily-ext/YYYY-MM.parquet — 2010 수집분(data/krx-pbr-history/daily/)과 폴더를 나눠 옛 연구 입력을 바꾸지 않는다.
이번 달 파일은 매번 다시 받는다(월이 끝나지 않았으므로).
"""
import ssl
import sys
import time
from datetime import date, timedelta
from pathlib import Path

import pandas as pd

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import collect_krx_daily_2010 as base

OUT = HERE / "data" / "krx-daily-ext"
D0 = date(2016, 2, 1)


def main():
    k, ctx = base.key(), ssl.create_default_context()
    OUT.mkdir(parents=True, exist_ok=True)
    today = date.today()
    start = sys.argv[1] if len(sys.argv) > 1 else D0.strftime("%Y-%m")      # 병렬 수집용 시작 월(선택)
    for mo in pd.period_range(start, today.strftime("%Y-%m"), freq="M"):
        f = OUT / f"{mo}.parquet"
        current = mo == pd.Period(today, "M")
        if f.exists() and not current:
            continue
        parts, d = [], mo.start_time.date()
        while d <= min(mo.end_time.date(), today):
            if d.weekday() < 5:
                for mkt, path in base.PATHS.items():
                    rows = base.get(path, d.strftime("%Y%m%d"), k, ctx)
                    if rows:
                        bad = {r["BAS_DD"] for r in rows} - {d.strftime("%Y%m%d")}
                        if bad:
                            raise SystemExit(f"{d} {mkt}: 응답 날짜 {bad} ≠ 요청일 — 멈춘다")
                        parts.append(pd.DataFrame(rows)[base.KEEP].assign(market=mkt))
                    time.sleep(0.1)
            d += timedelta(days=1)
        if not parts:
            continue
        df = pd.concat(parts, ignore_index=True)
        for c in base.NUM:
            df[c] = pd.to_numeric(df[c].astype(str).str.replace(",", ""), errors="coerce")
        df.to_parquet(f, index=False)
        print(f"  {mo}: {df['BAS_DD'].nunique()}거래일 · {len(df)}행", flush=True)


if __name__ == "__main__":
    main()
