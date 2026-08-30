#!/usr/bin/env python
"""Step 18A — basis manifest.json을 실제 parquet 상태와 일치하도록 재생성.

- build_crypto_basis_data.py의 qa_from_df/qa_join/write_manifest 재사용 (동일 스키마).
- 기존 manifest의 사실과 다른 exception("basis NaN" 밴 노트)은 갱신.
- mark/index 비대칭, premium 극단값 노트는 유지.
- 신규: basis 시작 지연(real_gap)이 Binance API 원천 결측임을 기록.
- 네트워크 사용 없음(오프라인). parquet 외 파일 일절 수정 없음.
"""
import json
import sys

import pandas as pd

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

import build_crypto_basis_data as B

OUT_DIR = B.OUT_DIR

old = json.loads((OUT_DIR / "manifest.json").read_text(encoding="utf-8"))

EXCEPTIONS_NEW = [
    {
        "note": "basis 컬럼은 재수집 성공으로 채워짐(2026-08-29 추가 수집). 최초 fill은 이 워크스테이션 "
                "egress IP에서 basis endpoint가 418 -1003 밴(794s~2034s)으로 전량 NaN이었으나, 밴 해소 후 "
                "재시도로 26종목 전량 + gap 종목의 활성 기간 커버리지를 채움.",
        "steps": "fill_basis_step18.py + fix_basis_cols (2026-08-29)",
    },
    {
        "note": "mark/index kline 최초 시각 비대칭: INJ index 2020-10-30 vs mark 2022-08-16(퍼프 재상장 추정); "
                "SOL index 2020-08-14 vs mark 2020-09-13; LTC/TRX index 2019-12-23 vs mark 2020-01; "
                "ATOM index 2020-02-04 vs mark 2020-02-06; DOGE index 2020-07-08 vs mark 2020-07-10. "
                "주요 종목(BTC/ETH/BNB/BCH) mark/index 공히 2019-12-23 시작 — BTC funding은 2019-09-10부터 존재하여 "
                "2019-09~12 구간 funding 이벤트(약 310건)는 premium join 불가(원자료 없음).",
        "steps": "manifest per-symbol first_mark/first_index 참조",
    },
    {
        "note": "premium_open |.|>5% 이상 극단값은 전부 상장 후 첫 수일 또는 SOL 2022-11-09 FTX 크래시 구간에 집중 "
                "(FIL 20회·SOL 3회·UNI 2회·AVAX/DOT/DOGE/SHIB/LINK 각 1회) — 데이터 오염 아님, 실제 프리미엄 디스로케이션.",
        "steps": "QA premium_extreme_gt5pct 참조",
    },
    {
        "note": "'mark 존재 & basis 결측'(real_gap)은 전 종목에서 mark(리스팅) 시작 직후 수 일~6주 구간에만 존재하며 "
                "(BNB 147행:2019-12-23~2020-02-10, ADA 36행, XMR 45행, 그 외 1~6행), Binance /futures/data/basis가 "
                "해당 구간을 원천적으로 반환하지 않음(직접 조회 확인: BNB 첫 basis 2020-02-10 08:00, INJ 첫 2022-08-17 00:00). "
                "수집 누락이 아니라 API 데이터 기원상의 부재 → 재수집 대상 아님.",
        "steps": "step18a_gaps / binance basis endpoint probe 2026-08-29",
    },
]

# 원래 EXCEPTIONS들 중 보존할 것 (mark/index, premium 극단값) — 사실과 다른 밴 노트는 제외
# 여기서는 위 EXCEPTIONS_NEW로 대체하는 방식 (기존 3개 중 2,3번이 사실이므로 명시 유지)


def make_manifest():
    manifest = {
        "end_target_utc": "2026-08-28T23:59 (grid floor 2026-08-29 00:00Z)",
        "grid_8h": "00:00/08:00/16:00 UTC",
        "symbols": {},
        "exceptions": EXCEPTIONS_NEW,
    }
    for p in sorted(OUT_DIR.glob("*.parquet")):
        sym = p.stem
        d8 = pd.read_parquet(p)
        d1p = OUT_DIR / "1h" / (sym + "_1h.parquet")
        r = B.qa_from_df(d8)
        r["rows_1h"] = int(len(pd.read_parquet(d1p))) if d1p.exists() else 0
        r["join"] = B.qa_join(sym, d8)
        # real_gap 분리: mark 존재 & basis 결측 (API 원천 결측 가능 정량화)
        real_gap = int((d8["mark_open"].notna() & d8["basis"].isna()).sum())
        r["mark_basis_gap"] = real_gap
        manifest["symbols"][sym] = r
    (OUT_DIR / "manifest.json").write_text(
        json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8")
    return manifest


m = make_manifest()
print("symbols:", len(m["symbols"]))
print("exceptions:", len(m["exceptions"]))
for sym in m["symbols"]:
    r = m["symbols"][sym]
    print(f"  {sym:16s} rows={r['rows_8h']:6d} basis_present={r['basis_present']:6d} "
          f"gap={r.get('mark_basis_gap', 0):4d} join={r['join']['match_ratio'] if r['join'] else '-'}")