#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""VIX(FRED VIXCLS) 백필 — market-regime 연구용.

설계 문서: findings/market-regime-build-plan-2026-08.md §2·§3·§4-1.
`fetch_macro.py`가 이미 쓰는 것과 동일 series — 소스는 바뀌지 않는다
(findings/market-regime-data-source-check-2026-08.md §3). 이 스크립트가
바꾸는 건 저장 방식뿐이다: 운영 쪽 `weekly(cap=80)` 압축 없이 원본 전체를
KR 거래일 asOf-join까지 마쳐 보존한다.

공통 로직(fred() 조회, KR 거래일 asOf 조인, PIT 규칙)은 macro_common.py —
build_usdkrw_backfill.py와 공유한다.

산출(전부 이 저장소의 research/strategy-lab 안, data/backfill/과 무관):
  data/macro/vixcls_raw.parquet    fred('VIXCLS') 원본 그대로(압축 없음)
  data/macro/vix_daily_kr.parquet  KR 거래일별 asOf-join 결과(최종 소비용)
  data/macro/_manifest_vix.json    재현성 기록(BF-1.1 정식 manifest 아님)

사용:
    python build_vix_backfill.py --selftest   # 네트워크 없이 로직만 검증
    python build_vix_backfill.py --dry-run    # FRED 조회만 하고 저장 안 함
    python build_vix_backfill.py              # 실제 조회 + 저장
"""
import argparse
import json
import sys
import time
from datetime import datetime, timezone

import pandas as pd

from macro_common import OUT_DIR, asof_join_kr, fred, load_kr_calendar, selftest_asof_join

SERIES_ID = "VIXCLS"
VALUE_COL = "vixLevel"


def selftest():
    checks = selftest_asof_join(VALUE_COL)
    ok = all(c for _, c in checks)
    for name, c in checks:
        print(("  PASS  " if c else "  FAIL  ") + name)
    print()
    print("통과 %d · 실패 %d" % (sum(c for _, c in checks), sum(not c for _, c in checks)))
    return 0 if ok else 1


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--selftest", action="store_true")
    ap.add_argument("--dry-run", action="store_true",
                     help="FRED 조회는 하되 파일을 쓰지 않는다")
    args = ap.parse_args()

    if args.selftest:
        return selftest()

    t0 = time.time()
    print("fetching FRED %s ..." % SERIES_ID)
    fred_rows = fred(SERIES_ID)
    print("  %d rows, %s..%s (%.1fs)" %
          (len(fred_rows), fred_rows[0][0], fred_rows[-1][0], time.time() - t0))

    kr_days = load_kr_calendar()
    print("KR 거래일 %d개 (%s..%s)" % (len(kr_days), kr_days[0], kr_days[-1]))

    joined = asof_join_kr(fred_rows, kr_days, VALUE_COL)

    n_missing = int(joined[VALUE_COL].isna().sum())
    print("asOf-join 결과: %d행, 결측 %d행(FRED 이력 이전 구간)" %
          (len(joined), n_missing))

    if args.dry_run:
        print("--dry-run: 저장하지 않음")
        print(joined.head(3).to_string(index=False))
        print(joined.tail(3).to_string(index=False))
        return 0

    OUT_DIR.mkdir(parents=True, exist_ok=True)

    raw_df = pd.DataFrame(fred_rows, columns=["date", "value"])
    raw_path = OUT_DIR / "vixcls_raw.parquet"
    raw_df.to_parquet(raw_path, index=False)

    out_path = OUT_DIR / "vix_daily_kr.parquet"
    joined.to_parquet(out_path, index=False)

    manifest = {
        "generatedAtUTC": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "seriesId": SERIES_ID,
        "sourceUrl": "https://fred.stlouisfed.org/graph/fredgraph.csv?id=" + SERIES_ID,
        "fredRows": len(fred_rows),
        "fredDateRange": [fred_rows[0][0], fred_rows[-1][0]],
        "krTradingDays": len(kr_days),
        "krDateRange": [kr_days[0], kr_days[-1]],
        "missingRows": n_missing,
        "pitRule": "asOf(D) = FRED date < D (backward, allow_exact_matches=False)",
        "note": "BF-1.1 정식 manifest 아님 — research 재현성 기록용 경량 버전 "
                "(findings/market-regime-build-plan-2026-08.md §2-3)",
        "files": {"raw": raw_path.name, "joined": out_path.name},
    }
    (OUT_DIR / "_manifest_vix.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")

    print("wrote", raw_path)
    print("wrote", out_path)
    print("wrote", OUT_DIR / "_manifest_vix.json")
    return 0


if __name__ == "__main__":
    sys.exit(main())
