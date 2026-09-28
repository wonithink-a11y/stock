# -*- coding: utf-8 -*-
"""K1 재현용 새 코인 표본 수집 — 사전등록 findings/crypto-k1-replication-preregistration-2026-09.md §1.

1) data.binance.vision 목록(S3)에서 USDT 무기한 심볼 전부(상장폐지 포함) → 제외 규칙 적용 → 목록 파일(_universe.json)
2) 코인마다 metrics 일별 파일 목록을 S3 로 받아 **있는 날만** 내려받는다(OI 금액 열 포함)
3) markPriceKlines 1시간: 월별 파일(2026-08 까지) + 2026-09 일별
출력 data/crypto/k1/{metrics,mark1h}/{SYM}.parquet (gitignore). 이어받기: 이미 있는 코인은 건너뛴다.

  python research/strategy-lab/collect_binance_k1_universe.py [--workers 16]
"""
import argparse
import hashlib
import io
import json
import re
import urllib.request
import zipfile
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pandas as pd

LAB = Path(__file__).resolve().parent
OUT = LAB / "data" / "crypto" / "k1"
S3 = "https://s3-ap-northeast-1.amazonaws.com/data.binance.vision?delimiter=/&prefix={p}&marker={m}"
BASE = "https://data.binance.vision/"
STABLE = {"USDC", "BUSD", "TUSD", "FDUSD", "USDP", "DAI", "EUR", "AEUR", "USDE"}
INDEX = ("BTCDOM", "DEFI", "FOOTBALL", "BLUEBIRD")
LAST_START = "2025-06-30"
MCOLS = ["create_time", "sum_open_interest", "sum_open_interest_value", "count_toptrader_long_short_ratio"]


def get(url, tries=3):
    for i in range(tries):
        try:
            with urllib.request.urlopen(url, timeout=60) as r:
                return r.read()
        except urllib.error.HTTPError as e:
            if e.code == 404:
                return None
            if i == tries - 1:
                raise
        except Exception:  # noqa: BLE001
            if i == tries - 1:
                raise


def s3_list(prefix):
    """(하위 prefix 목록, 파일 key 목록) — 1,000개씩 넘긴다."""
    subs, keys, marker = [], [], ""
    while True:
        x = get(S3.format(p=prefix, m=marker)).decode()
        subs += re.findall(r"<Prefix>([^<]*)</Prefix>", x)[1:]
        keys += re.findall(r"<Key>([^<]*)</Key>", x)
        if "<IsTruncated>true" not in x:
            return subs, keys
        marker = (keys or subs)[-1]


def universe():
    f = OUT / "_universe.json"
    if f.exists():
        return json.loads(f.read_text(encoding="utf-8"))
    subs, _ = s3_list("data/futures/um/daily/metrics/")
    syms = sorted(s.rstrip("/").split("/")[-1] for s in subs)
    old = {p.name.replace("_1h.parquet", "") for p in (LAB / "data" / "crypto" / "basis" / "1h").glob("*_1h.parquet")}
    keep = [s for s in syms if s.endswith("USDT") and "_" not in s and s not in old
            and s[:-4] not in STABLE and not s.startswith(INDEX)]
    u = {"all": len(syms), "kept": keep, "excluded_28": sorted(old & set(syms))}
    OUT.mkdir(parents=True, exist_ok=True)
    f.write_text(json.dumps(u, ensure_ascii=False, indent=1), encoding="utf-8")
    return u


def read_zip_csv(b, cols=None, header="infer"):
    z = zipfile.ZipFile(io.BytesIO(b))
    df = pd.read_csv(z.open(z.namelist()[0]), header=header)
    return df[[c for c in cols if c in df.columns]] if cols else df


def one_coin(sym, workers):
    mf, pf = OUT / "metrics" / f"{sym}.parquet", OUT / "mark1h" / f"{sym}.parquet"
    if mf.exists() and pf.exists():
        return sym, "skip"
    _, keys = s3_list(f"data/futures/um/daily/metrics/{sym}/")
    days = sorted(set(re.findall(r"metrics-(\d{4}-\d{2}-\d{2})\.zip", " ".join(keys))))
    if not days or days[0] > LAST_START:
        return sym, f"start {days[0] if days else None} — 제외(⑤)"
    with ThreadPoolExecutor(workers) as ex:
        blobs = list(ex.map(lambda d: get(f"{BASE}data/futures/um/daily/metrics/{sym}/{sym}-metrics-{d}.zip"), days))
    m = pd.concat([read_zip_csv(b, MCOLS) for b in blobs if b], ignore_index=True)
    months = pd.period_range(days[0][:7], "2026-08", freq="M").strftime("%Y-%m")
    urls = [f"{BASE}data/futures/um/monthly/markPriceKlines/{sym}/1h/{sym}-1h-{mo}.zip" for mo in months]
    urls += [f"{BASE}data/futures/um/daily/markPriceKlines/{sym}/1h/{sym}-1h-2026-09-{d:02d}.zip" for d in range(1, 28)]
    with ThreadPoolExecutor(workers) as ex:
        kb = list(ex.map(get, urls))
    frames = []
    for b in kb:
        if not b:
            continue
        k = read_zip_csv(b, header=None)
        if str(k.iloc[0, 0]).startswith("open"):          # 최근 파일은 머리줄이 있다
            k = k.iloc[1:]
        frames.append(k.iloc[:, :2].set_axis(["open_time", "mark_open"], axis=1))
    if not frames:
        return sym, "가격 없음"
    p = pd.concat(frames, ignore_index=True).astype(float).drop_duplicates("open_time")
    (OUT / "metrics").mkdir(parents=True, exist_ok=True)
    (OUT / "mark1h").mkdir(parents=True, exist_ok=True)
    m.to_parquet(mf, index=False)
    p.sort_values("open_time").to_parquet(pf, index=False)
    return sym, f"metrics {len(days)}일 · 가격 {len(p)}봉"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--workers", type=int, default=16)
    a = ap.parse_args()
    u = universe()
    print(f"목록 {u['all']} → 후보 {len(u['kept'])} (28종 제외 {len(u['excluded_28'])})",
          "sha", hashlib.sha256(json.dumps(u['kept']).encode()).hexdigest()[:12], flush=True)
    for i, s in enumerate(u["kept"]):
        try:
            print(i, *one_coin(s, a.workers), flush=True)
        except Exception as e:  # noqa: BLE001 — 한 코인 실패가 전체를 멈추지 않는다(다음 실행이 이어 간다)
            print(i, s, "ERR", repr(e)[:150], flush=True)


if __name__ == "__main__":
    main()
