"""KRX 공식 Open API 일별 전종목(KOSPI·KOSDAQ) 수집 2010-01-04 ~ 2016-01-29 — 사전등록
findings/kr-own-pbr-band-preregistration-2026-09.md §1·§7. 수익률은 계산하지 않는다(게이트용 대조만).

  python research/strategy-lab/collect_krx_daily_2010.py           # 수집(재개 가능, 월 단위 파일)
  python research/strategy-lab/collect_krx_daily_2010.py gate      # 수집 게이트(FLUC_RT 가 기업행사를 반영하는가)
  python research/strategy-lab/collect_krx_daily_2010.py --selftest

저장(gitignore): data/krx-pbr-history/daily/YYYY-MM.parquet · 커밋: daily_manifest.json(월별 행수·sha256·게이트)
★ 응답의 BAS_DD 가 요청일과 다르면 실패로 센다(교훈81). 휴장일은 0행 — 건너뛴다.
"""
import argparse
import hashlib
import json
import ssl
import sys
import time
import urllib.request
from datetime import date, timedelta
from pathlib import Path

import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
REPO = HERE.parent.parent
OUT = HERE / "data" / "krx-pbr-history"
D0, D1 = date(2010, 1, 4), date(2016, 1, 29)
PATHS = {"KOSPI": "sto/stk_bydd_trd", "KOSDAQ": "sto/ksq_bydd_trd"}
KEEP = ["BAS_DD", "ISU_CD", "ISU_NM", "MKT_NM", "TDD_CLSPRC", "FLUC_RT", "ACC_TRDVAL", "MKTCAP", "LIST_SHRS"]
NUM = ["TDD_CLSPRC", "FLUC_RT", "ACC_TRDVAL", "MKTCAP", "LIST_SHRS"]


def key():
    for line in (REPO / ".env").read_text(encoding="utf-8").splitlines():
        if line.startswith("KRX_OPENAPI_KEY="):
            return line.split("=", 1)[1].strip().strip('"')
    raise SystemExit("KRX_OPENAPI_KEY 가 없다")


def get(path, d, k, ctx):
    req = urllib.request.Request(f"https://data-dbg.krx.co.kr/svc/apis/{path}?basDd={d}",
                                 headers={"AUTH_KEY": k, "User-Agent": "Mozilla/5.0 stock-research"})
    for attempt in range(3):
        try:
            with urllib.request.urlopen(req, timeout=60, context=ctx) as r:
                return json.loads(r.read().decode("utf-8")).get("OutBlock_1") or []
        except Exception:
            if attempt == 2:
                raise
            time.sleep(5)


def collect():
    k, ctx = key(), ssl.create_default_context()
    (OUT / "daily").mkdir(parents=True, exist_ok=True)
    months = pd.period_range(D0.strftime("%Y-%m"), D1.strftime("%Y-%m"), freq="M")
    for mo in months:
        f = OUT / "daily" / f"{mo}.parquet"
        if f.exists():
            continue
        parts, d = [], max(mo.start_time.date(), D0)
        while d <= min(mo.end_time.date(), D1):
            if d.weekday() < 5:
                for mkt, path in PATHS.items():
                    rows = get(path, d.strftime("%Y%m%d"), k, ctx)
                    if rows:
                        bad = {r["BAS_DD"] for r in rows} - {d.strftime("%Y%m%d")}
                        if bad:
                            raise SystemExit(f"{d} {mkt}: 응답 날짜 {bad} ≠ 요청일 — 멈춘다")
                        parts.append(pd.DataFrame(rows)[KEEP].assign(market=mkt))
                    time.sleep(0.1)
            d += timedelta(days=1)
        df = pd.concat(parts, ignore_index=True)
        for c in NUM:
            df[c] = pd.to_numeric(df[c].astype(str).str.replace(",", ""), errors="coerce")
        df.to_parquet(f, index=False)
        print(f"  {mo}: {df['BAS_DD'].nunique()}거래일 · {len(df)}행", flush=True)
    manifest()


def load():
    return pd.concat([pd.read_parquet(f) for f in sorted((OUT / "daily").glob("*.parquet"))], ignore_index=True)


def fluc_check(df):
    """일별 종가비와 FLUC_RT 대조. 반환 (일치 비율, 분할형 사건 수, 사건 예시)."""
    df = df.sort_values(["ISU_CD", "BAS_DD"])
    prev = df.groupby("ISU_CD")["TDD_CLSPRC"].shift()
    raw = (df["TDD_CLSPRC"] / prev - 1) * 100
    diff = (df["FLUC_RT"] - raw).abs()
    ok = diff[prev.notna() & (prev > 0)]
    ratio = df["TDD_CLSPRC"] / prev
    split = df[(diff > 1) & (ratio < 0.6) & (df["FLUC_RT"].abs() < 30)]
    return float((ok <= 0.01).mean()), len(split), split[["BAS_DD", "ISU_CD", "ISU_NM", "TDD_CLSPRC", "FLUC_RT"]].head(5)


def gate():
    df = load()
    share, n_split, ex = fluc_check(df)
    days = df.groupby("BAS_DD")["market"].nunique()
    g = {"trading_days": int(len(days)), "days_missing_a_market": int((days < 2).sum()),
         "fluc_match_share": round(share, 5), "split_like_events": n_split,
         "rule": "fluc_match_share ≥ 0.99 · split_like_events ≥ 3 · days_missing_a_market = 0",
         "passed": bool(share >= 0.99 and n_split >= 3 and (days < 2).sum() == 0)}
    print(json.dumps(g, ensure_ascii=False)); print(ex.to_string(index=False))
    manifest(g)
    return g["passed"]


def manifest(g=None):
    p = OUT / "daily_manifest.json"
    m = json.loads(p.read_text(encoding="utf-8")) if p.exists() else {}
    m["by_month"] = {f.stem: {"rows": int(len(pd.read_parquet(f))), "sha256": hashlib.sha256(f.read_bytes()).hexdigest()[:16]}
                     for f in sorted((OUT / "daily").glob("*.parquet"))}
    if g:
        m["gate"] = g
    p.write_text(json.dumps(m, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")


def selftest():
    d = pd.DataFrame({"ISU_CD": ["A"] * 4, "BAS_DD": ["1", "2", "3", "4"], "ISU_NM": "x",
                      "TDD_CLSPRC": [10000, 10100, 2040, 2060], "FLUC_RT": [0.0, 1.0, 1.0, 0.98]})
    share, n, _ = fluc_check(d)
    assert n == 1, "1:5 분할(10100→2040)인데 FLUC_RT 는 +1% — 분할형 사건 1건"
    assert abs(share - 2 / 3) < 1e-9, "분할일만 불일치"
    print("collect_krx_daily_2010 selftest: 통과")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", nargs="?", choices=["gate"])
    ap.add_argument("--selftest", action="store_true")
    a = ap.parse_args()
    if a.selftest:
        sys.exit(selftest())
    sys.exit(0 if (gate() if a.cmd == "gate" else collect() or True) else 1)
