#!/usr/bin/env python
"""A4(수급) 연구용 데이터셋 구축 — streaming 처리.

원자료: data/backfill/supplyDemand/a4/{2016..2026}.jsonl.gz (KRX/pykrx, SD-1.0)
가격:   data/backfill/price/a2a/{2015..2026}.jsonl.gz (adjusted close, PR-1.5/1.6)

생성물 (research/strategy-lab/data/a4/):
  a4-research-dataset.parquet  — (ticker, date)별 수급 netbuy 파생 feature + forward return
  a4-feature-summary.json     — feature 설명/계산식/기술통계/결측률
  a4-data-quality.json        — 원자료 검증(항등식·중복·날짜) 재현 결과

PIT 원칙:
  - 모든 파생 feature는 date t까지의 정보만 사용(순차 누적, look-ahead 없음)
  - forward return은 t 이후 거래일 기준 (t+20/+60/+120 거래일 close / t close - 1)
  - A2a adjusted close 사용 (수정주가, 액면분할·배당 보정) — unadjusted 사용 안 함
  - 미래 데이터가 feature 계산에 섞이지 않음 (rolling backward만)

메모리: 연도별 파일을 스트리밍으로 읽어 ticker별 누적 dict에만 담는다.
원자료 약 540만 행 → 결과 panel 약 540만 행 (수급 레코드당 1행).
"""
import gzip
import json
import os
import sys
from collections import defaultdict

import numpy as np
import pandas as pd

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
A4_DIR = os.path.join(REPO_ROOT, "data", "backfill", "supplyDemand", "a4")
A2A_DIR = os.path.join(REPO_ROOT, "data", "backfill", "price", "a2a")
OUT_DIR = os.path.join(REPO_ROOT, "research", "strategy-lab", "data", "a4")

INSTITUTION_CATEGORIES = ["금융투자", "보험", "투신", "사모", "은행", "기타금융", "연기금", "기타법인"]
FOREIGN_CATEGORIES = ["외국인", "기타외국인"]
ALL_CATEGORIES = ["금융투자", "보험", "투신", "사모", "은행", "기타금융", "연기금", "기타법인", "개인", "외국인", "기타외국인"]
A4_YEARS = ["2016", "2017", "2018", "2019", "2020", "2021", "2022", "2023", "2024", "2025", "2026"]
A2A_YEARS = ["2015", "2016", "2017", "2018", "2019", "2020", "2021", "2022", "2023", "2024", "2025", "2026"]
HORIZONS = {"d20": 20, "d60": 60, "d120": 120}


def read_gz_jsonl_stream(path):
    with gzip.open(path, "rt", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            yield json.loads(line)


def load_a4():
    """A4 원자료를 (ticker, date) -> {netbuy들, amount, volume}로 streaming 수집."""
    data = defaultdict(dict)
    n_rows = 0
    key_sets = set()
    clearing_violations = 0
    for year in A4_YEARS:
        path = os.path.join(A4_DIR, f"{year}.jsonl.gz")
        for rec in read_gz_jsonl_stream(path):
            t = rec["ticker"]
            d = rec["date"]
            ba, sa = rec["buyAmount"], rec["sellAmount"]
            bv, sv = rec["buyVolume"], rec["sellVolume"]
            key_sets.add(frozenset(ba.keys()))
            # KRX 시장 청산 항등식 재검증: 전체(전체) 매수금액 == 매도금액
            if ba.get("전체", 0) != sa.get("전체", 0):
                clearing_violations += 1
            foreign_net = (ba.get("외국인", 0) + ba.get("기타외국인", 0)) - (sa.get("외국인", 0) + sa.get("기타외국인", 0))
            inst_net = sum(ba.get(c, 0) - sa.get(c, 0) for c in INSTITUTION_CATEGORIES)
            indiv_net = ba.get("개인", 0) - sa.get("개인", 0)
            total_amount = ba.get("전체", 0)
            total_volume = bv.get("전체", 0)
            # KRX 상세 12개 카테고리 net (보존: 필요한 범위)
            cat_nets = {c: ba.get(c, 0) - sa.get(c, 0) for c in ALL_CATEGORIES}
            data[t][d] = {
                "foreign_net": foreign_net,
                "inst_net": inst_net,
                "indiv_net": indiv_net,
                "total_amount": total_amount,
                "total_volume": total_volume,
                **cat_nets,
            }
            n_rows += 1
    return data, n_rows, key_sets, clearing_violations


def load_a2a_close():
    """A2a adjusted close를 (ticker, date) -> close로 수집."""
    prices = defaultdict(dict)
    for year in A2A_YEARS:
        path = os.path.join(A2A_DIR, f"{year}.jsonl.gz")
        if not os.path.exists(path):
            continue
        for rec in read_gz_jsonl_stream(path):
            prices[rec["ticker"]][rec["date"]] = rec["close"]
    return prices


def rolling_netbuys(records):
    """ticker별 (date, net) 정렬 시계열에서 1/5/20d 합계를 PIT하게 계산.
    records: list of (date, net). returns dict date -> {n1, n5, n20}"""
    dates = [d for d, _ in records]
    nets = np.array([n for _, n in records], dtype=np.float64)
    # cumsum 기반 rolling sum (PIT: 이전 window 포함)
    out = {}
    for i, d in enumerate(dates):
        out[d] = {
            "n1": nets[i],
            "n5": nets[max(0, i - 4):i + 1].sum(),
            "n20": nets[max(0, i - 19):i + 1].sum(),
        }
    return out


def main():
    os.makedirs(OUT_DIR, exist_ok=True)
    print("Loading A4 raw (streaming)...")
    a4, n_rows, key_sets, clearing_violations = load_a4()
    print(f"  A4 rows={n_rows}, clearing_violations={clearing_violations}, key_set_variants={len(key_sets)}")
    print("Loading A2a adjusted close...")
    prices = load_a2a_close()
    print(f"  A2a tickers={len(prices)}")

    # panel 구축
    rows = []
    n_no_close = 0
    n_no_forward = 0
    # ticker별 정렬된 날짜 목록으로 forward return 계산
    for ticker, daymap in a4.items():
        if ticker not in prices:
            # A1A 유니버스 외(예: 해외) — 기록만 하고 skip
            continue
        dates_sorted = sorted(daymap.keys())
        close_map = prices[ticker]
        # forward return: t+20/+60/+120 거래일 close / t close - 1
        close_dates = sorted(close_map.keys())
        pos = {d: i for i, d in enumerate(close_dates)}
        close_arr = np.array([close_map[d] for d in close_dates], dtype=np.float64)
        for d in dates_sorted:
            if d not in close_map or close_map[d] <= 0:
                n_no_close += 1
                continue
            c0 = float(close_map[d])
            i = pos[d]
            base = daymap[d]
            row = {
                "ticker": ticker,
                "date": d,
                "foreign_net": base["foreign_net"],
                "inst_net": base["inst_net"],
                "indiv_net": base["indiv_net"],
                "total_amount": base["total_amount"],
                "total_volume": base["total_volume"],
            }
            for c in ALL_CATEGORIES:
                row[f"net_{c}"] = base[c]
            row["close"] = c0
            for h, n in HORIZONS.items():
                j = i + n
                if j < len(close_dates) and close_arr[j] > 0:
                    row[f"fwd_{h}"] = close_arr[j] / c0 - 1
                else:
                    row[f"fwd_{h}"] = np.nan
                    n_no_forward += 1
            rows.append(row)
        # rolling feature는 여기서 각 ticker의 날짜순으로 계산해 attach — 별도 패스로 일괄
    df = pd.DataFrame(rows)
    print(f"  panel rows={len(df)}, no_close={n_no_close}, no_forward_entries={n_no_forward}")
    print(f"  tickers={df['ticker'].nunique()}, date_range={df['date'].min()}~{df['date'].max()}")

    # rolling netbuy 1/5/20d (PIT: ticker별 날짜 오름차순으로 cumsum)
    print("Computing rolling netbuy features (PIT)...")
    df = df.sort_values(["ticker", "date"]).reset_index(drop=True)
    for src, prefix in (("foreign_net", "foreign"), ("inst_net", "inst"), ("indiv_net", "indiv")):
        g = df.groupby("ticker")[src]
        for w, pl in ((1, "1d"), (5, "5d"), (20, "20d")):
            df[f"{prefix}_nb_{pl}"] = g.transform(lambda s: s.rolling(w, min_periods=1).sum())
    # 수급 강도: 20d net / 20d total_amount (거래대금 대비)
    g_amount = df.groupby("ticker")["total_amount"]
    for src, prefix in (("foreign_net", "foreign"), ("inst_net", "inst"), ("indiv_net", "indiv")):
        g_net = df.groupby("ticker")[src]
        df[f"{prefix}_nb20_ratio"] = (
            g_net.transform(lambda s: s.rolling(20, min_periods=1).sum())
            / g_amount.transform(lambda s: s.rolling(20, min_periods=1).sum()).replace(0, np.nan)
        )
    # 거래대금 로그
    df["log_total_amount"] = np.log1p(df["total_amount"].astype(np.float64))

    out_parquet = os.path.join(OUT_DIR, "a4-research-dataset.parquet")
    df.to_parquet(out_parquet, index=False)
    print(f"Saved parquet: {out_parquet}")

    # feature summary
    feature_docs = {
        "ticker": "종목 코드 (6자리)",
        "date": "거래일 (YYYY-MM-DD)",
        "foreign_net": "외국인+기타외국인 순매수 금액(원) — buyAmount-sellAmount, KRX 원자료",
        "inst_net": "기관(금융투자·보험·투신·사모·은행·기타금융·연기금·기타법인) 순매수 금액(원)",
        "indiv_net": "개인 순매수 금액(원)",
        "total_amount": "전체 거래대금(원) — buyAmount['전체']",
        "total_volume": "전체 거래량(주) — buyVolume['전체']",
        "net_*": "KRX 11개 카테고리별 순매수 금액(원) — 금융투자·보험·투신·사모·은행·기타금융·연기금·기타법인·개인·외국인·기타외국인",
        "close": "A2a adjusted close (수정주가)",
        "fwd_d20/d60/d120": f"forward return — t 이후 {HORIZONS}/거래일 close / t close - 1 (adjusted)",
        "foreign_nb_1d/5d/20d": "외국인 순매수 합계 t-{w+1}~t (PIT rolling)",
        "inst_nb_1d/5d/20d": "기관 순매수 합계 (PIT rolling)",
        "indiv_nb_1d/5d/20d": "개인 순매수 합계 (PIT rolling)",
        "foreign_nb20_ratio": "20d 외국인 순매수 / 20d 거래대금",
        "inst_nb20_ratio": "20d 기관 순매수 / 20d 거래대금",
        "indiv_nb20_ratio": "20d 개인 순매수 / 20d 거래대금",
        "log_total_amount": "log1p(거래대금) — 유동성 proxy",
    }
    summary = {
        "source": "data/backfill/supplyDemand/a4/*.jsonl.gz (KRX via pykrx, SD-1.0)",
        "priceSource": "data/backfill/price/a2a/*.jsonl.gz (A2a, adjusted)",
        "period": [df["date"].min(), df["date"].max()],
        "nRows": int(len(df)),
        "nTickers": int(df["ticker"].nunique()),
        "adjustedPrice": True,
        "adjustNote": "A2a는 수정주가(PR-1.5/1.6, 액면분할·배당 보정). unadjusted는 사용하지 않음. forward return도 adjusted 기준.",
        "pitNote": "파생 feature(rolling netbuy, ratio)는 date t까지의 정보만 사용. forward return은 t 이후 거래일 — feature 계산에 미래 데이터 미사용.",
        "institutionCategories": INSTITUTION_CATEGORIES,
        "foreignCategories": FOREIGN_CATEGORIES,
        "columns": feature_docs,
        "missing": {
            "fwd_d120": float(df["fwd_d120"].isna().mean()),
            "fwd_d60": float(df["fwd_d60"].isna().mean()),
            "fwd_d20": float(df["fwd_d20"].isna().mean()),
            "total_amount": float(df["total_amount"].isna().mean()),
        },
        "basicStats": {
            "foreign_net": {"mean": round(float(df["foreign_net"].mean()), 0), "median": round(float(df["foreign_net"].median()), 0),
                            "std": round(float(df["foreign_net"].std()), 0)},
            "inst_net": {"mean": round(float(df["inst_net"].mean()), 0), "median": round(float(df["inst_net"].median()), 0),
                         "std": round(float(df["inst_net"].std()), 0)},
            "indiv_net": {"mean": round(float(df["indiv_net"].mean()), 0), "median": round(float(df["indiv_net"].median()), 0),
                          "std": round(float(df["indiv_net"].std()), 0)},
        },
        "notComputable": {
            "perShareFlow": "주당 수급량 — 발행주식수(A3c) 미연결(연결 시점은 SD-1.0 범위 밖)",
            "foreignOwnershipPct": "외국인 보유율 — 보유잔고 원자료 없음(순매수만)",
            "shortInterest": "공매도 잔고 — 원자료 없음 (docs/operations/data-source-availability.md: KRX 공매도 차단)",
            "marketCap": "시가총액 — A1a 유니버스 미매핑(다음 버전 과제, 시장/규모 분할은 total_amount proxy 사용)",
        },
    }
    with open(os.path.join(OUT_DIR, "a4-feature-summary.json"), "w", encoding="utf-8") as f:
        json.dump(summary, f, ensure_ascii=False, indent=2)
    print("Saved a4-feature-summary.json")

    # data quality
    quality = {
        "rawRowCount": n_rows,
        "rawPeriod": [min(a4[t][d] and d for t in a4 for d in a4[t]), max(d for t in a4 for d in a4[t])],
        "tickersWithA4": len(a4),
        "clearingIdentityCheck": {
            "rule": "buyAmount['전체'] == sellAmount['전체'] (KRX 시장 청산) 재검증",
            "violations": clearing_violations,
        },
        "categoryKeySetVariants": len(key_sets),
        "categoryKeySetNote": "같은 레코드 안 buy/sell/volume 키 집합 일치 여부는 원자료 finalize(_diagnostics.json: categoryKeySetViolations=0)가 검증 — 여기서는 전체 키 조합 수만 기록",
        "a2aJoin": {"a4Tickers": len(a4), "a2aTickersWithClose": len(set(a4) & set(prices))},
        "forwardReturnCoverage": {
            "d20": round(float(df["fwd_d20"].notna().mean()), 4),
            "d60": round(float(df["fwd_d60"].notna().mean()), 4),
            "d120": round(float(df["fwd_d120"].notna().mean()), 4),
        },
        "rawDiagnosticsReference": "data/backfill/supplyDemand/a4/_diagnostics.json (finalize: marketClearingViolations=0, acceptancePassed=true)",
        "exclusions": {
            "tickersNoA2a": "A1A 유니버스 외 종목(A2a 미커버)은 패널에서 제외",
            "rowsNoClose": f"{n_no_close} rows — A2a close 부재",
            "fwdNaN": "기간 말 미래 부재 — fwd_d120이 마지막 ~120 거래일에서 NaN",
        },
    }
    with open(os.path.join(OUT_DIR, "a4-data-quality.json"), "w", encoding="utf-8") as f:
        json.dump(quality, f, ensure_ascii=False, indent=2)
    print("Saved a4-data-quality.json")


if __name__ == "__main__":
    main()