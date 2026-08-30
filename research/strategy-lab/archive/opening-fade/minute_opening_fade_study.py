#!/usr/bin/env python
"""분봉 오더닝 페이드/모멘텀 signal study - [RESEARCH HYPOTHESIS] (첫 실행, 튜닝 없음).

가설[RESEARCH HYPOTHESIS]: 시가(09:00) 대비 09:05 수익률의 부호가 그날 나머지
구간(09:05→종가)을 예측하는가 - "초반 모멘텀 지속"인가 "페이드(되돌림)"인가.

설계 (지시문 그대로):
  - 대상: MinuteProvider 미러(.cache/minute_raw, 252거래일 전체 유니버스)
  - 분류: 같은 날 유니버스 안에서 09:00→09:05 수익률 5분위(quintile, 각 20%)
  - 결과: 09:05 기준 당일 내 수익률 - 09:05→10:00 / →11:00 / →종가(15:30)
    (하루 안에서 끝나는 신호라 다일 지평은 사용하지 않음)
  - 벤치마크: 그날 유니버스 전체 동일가중. 초과수익은 날짜 동일가중 평균(V1~V9 관례)
  - 보조: 부호 그룹(양/음)도 나란히 보고

정의 고정(임의 선택 최소화):
  - P0900 = ts 09:00 봉의 open(장 시작 시가), P0905 = ts 09:05 봉의 close
  - 09:00 또는 09:05 봉이 없으면 그 종목-일 제외; 10:00/11:00/15:30 결측은 해당
    호라이즌만 NaN
  - 분위 경계는 날짜 내 rank(method='first', pct=True) 기반(동률은 티커 순으로
    결정적 처리)

  python minute_opening_fade_study.py
"""
import glob
import io
import json
import os
import sys
import time

import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
MINUTE_DIR = os.path.join(REPO_ROOT, "research", "strategy-lab", ".cache", "minute_raw")
OUT_DIR = os.path.join(REPO_ROOT, "research", "strategy-lab", "findings", "minute-opening-fade")
HORIZONS = {"h1000": "p1000", "h1100": "p1100", "hClose": "p1530"}


def day_frame(date_dir, date_str):
    frames = []
    for part in sorted(glob.glob(os.path.join(date_dir, "part-*.parquet"))):
        d = pd.read_parquet(part, columns=["ticker", "ts", "open", "close"])
        frames.append(d)
    if not frames:
        return None
    df = pd.concat(frames, ignore_index=True)
    # ts는 'YYYY-MM-DDTHH:MM+09:00' 형태의 문자열(파이프라인 출력) - 전량
    # to_datetime을 하지 않고 슬라이싱으로 시각만 추출한다(속도).
    s = df["ts"]
    hhmm = s.astype(str).str.slice(11, 16) if not hasattr(s, "dt") else s.dt.strftime("%H:%M")
    keep = hhmm.isin(["09:00", "09:05", "10:00", "11:00", "15:30"])
    df = df[keep]
    df = df[(df["open"] > 0) & (df["close"] > 0)]
    df = df.assign(hhmm=hhmm[keep][df.index])

    def at(hhmm_val, col):
        sub = df.loc[df["hhmm"] == hhmm_val, ["ticker", col]].copy()
        name = "p0900" if col == "open" else f"p{hhmm_val.replace(':', '')}"
        sub.columns = ["ticker", name]
        return sub

    out = at("09:00", "open").merge(at("09:05", "close"), on="ticker", how="inner") \
                             .merge(at("10:00", "close"), on="ticker", how="left") \
                             .merge(at("11:00", "close"), on="ticker", how="left") \
                             .merge(at("15:30", "close"), on="ticker", how="left")
    out.insert(0, "date", date_str)
    return out


def main():
    t0 = time.time()
    date_dirs = sorted(glob.glob(os.path.join(MINUTE_DIR, "date=*")))
    print(f"partitions={len(date_dirs)} ({date_dirs[0].split('=')[-1]}~{date_dirs[-1].split('=')[-1]})")

    chunks = []
    n_days = 0
    for dd in date_dirs:
        fr = day_frame(dd, dd.split("=")[-1])
        if fr is None or fr.empty:
            continue
        # 유효성: 가격 > 0
        pc = [c for c in fr.columns if c.startswith("p")]
        ok = np.ones(len(fr), dtype=bool)
        for c in pc:
            ok &= fr[c].fillna(0).gt(0).to_numpy() | fr[c].isna().to_numpy()
        fr = fr[ok]
        fr = fr[fr["p0900"].notna()]
        chunks.append(fr)
        n_days += 1
        if n_days % 50 == 0:
            print(f"  {n_days} days done ({time.time()-t0:.0f}s)")
    df = pd.concat(chunks, ignore_index=True)
    print(f"ticker-days={len(df)}, days={n_days}, tickers/day~{len(df)/max(1,n_days):.0f} ({time.time()-t0:.0f}s)")

    df["r05"] = df["p0905"] / df["p0900"] - 1
    for key, col in (("r1000", "p1000"), ("r1100", "p1100"), ("rclose", "p1530")):
        df[key] = df[col] / df["p0905"] - 1

    # 분위(날짜 내, 동률은 티커순 결정적 처리)
    base = df[df["r05"].notna()].sort_values(["date", "ticker"]).reset_index(drop=True)
    base["q"] = base.groupby("date")["r05"].transform(
        lambda s: np.minimum(np.ceil(s.rank(method="first", pct=True) * 5), 5).astype(int))

    horizons = {"09:05→10:00": "r1000", "09:05→11:00": "r1100", "09:05→close": "rclose"}
    results = {}
    for h_label, col in horizons.items():
        d = base[base[col].notna()]
        bench = d.groupby("date")[col].mean().rename("bench")
        dq = d.merge(bench, on="date")
        dq["excess"] = dq[col] - dq["bench"]
        gmean = dq.groupby(["date", "q"])["excess"].mean().groupby("q").mean()
        cnt = dq.groupby(["date", "q"]).size().groupby("q").mean()
        block = {
            "excessByQuintile": {f"Q{q}": round(float(gmean.get(q, float('nan'))), 6) for q in range(1, 6)},
            "avgTickersPerDayPerQ": {f"Q{q}": round(float(cnt.get(q, float('nan'))), 1) for q in range(1, 6)},
            "topMinusBottom": round(float(gmean.get(5, float('nan')) - gmean.get(1, float('nan'))), 6),
            "universeMean": round(float(dq.groupby('date')[col].mean().mean()), 6),
        }
        # 부호 그룹
        sg = {}
        for label, m in (("pos", dq["r05"] > 0), ("neg", dq["r05"] < 0)):
            e = dq[m].groupby("date")["excess"].mean()
            sg[label] = round(float(e.mean()), 6)
        block["signGroupsExcess"] = sg
        results[h_label] = block
        print(h_label, json.dumps(block, ensure_ascii=False)[:220])

    diag = {
        "days": int(n_days),
        "tickerDays": int(len(base)),
        "avgTickersPerDay": round(len(base) / max(1, n_days), 1),
        "r05MedianAbsBp": round(float(base["r05"].abs().median()) * 1e4, 1),
        "posShare": round(float((base["r05"] > 0).mean()), 4),
    }
    print("diag:", diag)

    os.makedirs(OUT_DIR, exist_ok=True)
    out_path = os.path.join(OUT_DIR, "study_results.json")
    with open(out_path, "w", encoding="utf-8") as fh:
        json.dump({
            "generatedAt": time.strftime("%Y-%m-%dT%H:%M:%S"),
            "label": "[RESEARCH HYPOTHESIS] - 영상 출처 없는 순수 연구 가설",
            "context": "분봉 오더닝 페이드/모멘텀 최소 signal study - 첫 실행, threshold 튜닝 없음",
            "dataSources": ["engine/data/minuteProvider.py 미러 .cache/minute_raw "
                            "(252거래일 비공식 VM 미러, MN-1.0 매니페스트 없음)"],
            "definitions": {
                "signal": "P(09:05 close)/P(09:00 open) - 1 의 날짜 내 5분위",
                "outcomes": "P(h)/P(09:05)-1, h=10:00/11:00/close(15:30) - 당일 한정",
                "benchmark": "같은 날 유니버스 전체 동일가중, 초과수익은 날짜 동일가중 평균",
                "quintileTieBreak": "날짜 내 rank(method='first') - 티커 순 결정적",
                "exclusions": "09:00/09:05 봉 결측 또는 가격<=0 종목-일 제외",
            },
            "pitNote": "신호는 09:05까지 정보만 사용, 결과는 09:05 이후 - look-ahead 구조적으로 없음. "
                       "실행은 09:05 종가 근사(비용 미반영)",
            "diagnostics": diag,
            "results": results,
        }, fh, ensure_ascii=False, indent=2)
    print("saved:", out_path)


if __name__ == "__main__":
    main()
