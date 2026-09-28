# -*- coding: utf-8 -*-
"""바이낸스 USDT 무기한 metrics(5분: OI·롱숏 비율·테이커 비율) 일별 파일 수집 — 크립토 포지션 쏠림 연구 전용.

사전등록: findings/crypto-positioning-preregistration-2026-09.md. 출처 data.binance.vision(공개, 키 없음).
코인 = data/crypto/basis/1h 의 28종. 코인별 parquet 을 data/crypto/metrics/ 에 쓴다(gitignore 확인 후 사용).
이어받기: 이미 받은 날짜·404(상장 전) 날짜는 _state.json 에 남겨 다시 안 받는다.

  python research/strategy-lab/collect_binance_metrics.py [--start 2020-09-01] [--end 2026-09-27] [--workers 8]
"""
import argparse
import datetime as dt
import io
import json
import urllib.error
import urllib.request
import zipfile
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pandas as pd

LAB = Path(__file__).resolve().parent
OUT = LAB / "data" / "crypto" / "metrics"
STATE = OUT / "_state.json"
URL = "https://data.binance.vision/data/futures/um/daily/metrics/{s}/{s}-metrics-{d}.zip"
COLS = ["create_time", "sum_open_interest", "count_toptrader_long_short_ratio", "sum_taker_long_short_vol_ratio"]


def fetch(sym, d):
    try:
        with urllib.request.urlopen(URL.format(s=sym, d=d), timeout=30) as r:
            z = zipfile.ZipFile(io.BytesIO(r.read()))
        df = pd.read_csv(z.open(z.namelist()[0]))
        return sym, d, df[[c for c in COLS if c in df.columns]]
    except urllib.error.HTTPError as e:
        return sym, d, (404 if e.code == 404 else e)
    except Exception as e:  # noqa: BLE001
        return sym, d, e


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--start", default="2020-09-01")
    ap.add_argument("--end", default=(dt.date.today() - dt.timedelta(days=1)).isoformat())
    ap.add_argument("--workers", type=int, default=8)
    a = ap.parse_args()
    OUT.mkdir(parents=True, exist_ok=True)
    syms = sorted(p.name.replace("_1h.parquet", "") for p in (LAB / "data" / "crypto" / "basis" / "1h").glob("*_1h.parquet"))
    st = json.loads(STATE.read_text(encoding="utf-8")) if STATE.exists() else {}
    days = pd.date_range(a.start, a.end).strftime("%Y-%m-%d").tolist()
    for sym in syms:
        seen = st.setdefault(sym, {"done": [], "missing": []})
        todo = [d for d in days if d not in seen["done"] and d not in seen["missing"]]
        if not todo:
            continue
        frames, errs = [], 0
        with ThreadPoolExecutor(a.workers) as ex:
            for s, d, res in ex.map(lambda d: fetch(sym, d), todo):
                if isinstance(res, pd.DataFrame):
                    frames.append(res.assign(symbol=s)); seen["done"].append(d)
                elif isinstance(res, int):
                    if d <= days[-3]:                  # 상장 전 — 최근 이틀 404 는 미게시일 수 있어 다음 실행에 다시 본다
                        seen["missing"].append(d)
                else:
                    errs += 1
        f = OUT / f"{sym}.parquet"
        if frames:
            new = pd.concat(frames, ignore_index=True)
            if f.exists():
                new = pd.concat([pd.read_parquet(f), new], ignore_index=True).drop_duplicates("create_time")
            new.sort_values("create_time").to_parquet(f, index=False)
        STATE.write_text(json.dumps(st), encoding="utf-8")     # 파일을 쓴 뒤에 상태
        print(f"{sym}: +{len(frames)}일 · 404 {len(seen['missing'])} · 오류 {errs}", flush=True)


if __name__ == "__main__":
    main()
