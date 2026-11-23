"""놀이터 공용 — 종목 사건 시험 엔진 (국내 유동 500 · 미국 S&P500 PIT). 판정 아님.

사용:
    from event_engine import panels, study
    P = panels()                                  # {"kr": (ret, close, mem, tv), "us": (ret, close, mem, None)}
    def rule(ret, close, mem, tv):                # 같은 모양의 bool DataFrame (그날 종가에 진입)
        return (ret > 0.10) & mem
    study("이름", rule, P)

결과: 사건(종목별 gap 일 간격) → h ∈ (5, 21, 63) 일 종목 수익 − 같은 날 유니버스 '사서 들고 있기' 평균. 사건 단위 평균·중앙·양수 + 월 군집 t(같은 달 사건 평균 한 점), 시기 칸.
국내 수익 = KRX 등락률(폐지 뒤 0 — 손실 과소 쪽 오차). 비용 미반영(국내 왕복 33.5bp·미국 5bp 를 참고로 같이 출력).
"""
import sys
from functools import lru_cache
from pathlib import Path

import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE)); sys.path.insert(0, str(HERE.parent / "strategy-lab"))
from cross_section_us_kr import us_panel, kr_panel   # noqa: E402

LAB = HERE.parent / "strategy-lab"
PER = [("~2015", "1900", "2015-12-31"), ("2016~23", "2016-01-01", "2023-12-31"), ("2024", "2024-01-01", "2024-12-31"), ("2025~", "2025-01-01", "2100")]
COST = {"kr": 0.00335, "us": 0.0005}


@lru_cache(maxsize=1)
def panels():
    r, c, m = kr_panel()
    fs = sorted((LAB / "data/krx-daily-ext").glob("*.parquet"))
    d = pd.concat(pd.read_parquet(f, columns=["BAS_DD", "ISU_CD", "ACC_TRDVAL", "MKTCAP"]) for f in fs)
    d["date"] = pd.to_datetime(d["BAS_DD"].astype(str))
    for k in ("ACC_TRDVAL", "MKTCAP"):
        d[k] = pd.to_numeric(d[k].astype(str).str.replace(",", ""), errors="coerce")
    d = d.drop_duplicates(["ISU_CD", "date"])
    tv = d.pivot(index="date", columns="ISU_CD", values="ACC_TRDVAL").reindex_like(r)
    ur, uc, um = us_panel()
    return {"kr": (r, c, m, tv), "us": (ur, uc, um, None)}


def run_events(flag, ret, mem, horizons=(5, 21, 63), gap=21):
    lvl = (1 + ret.fillna(0)).cumprod()
    # 기준 = 같은 날 유니버스를 사서 들고 있기 평균(매일 재조정 등가중은 국내 63일 +5.8%p 과대 — 11-24 정정)
    bh = {h: (lvl.shift(-h) / lvl - 1).where(mem).mean(axis=1).to_numpy() for h in horizons}
    rows = []
    F = flag.reindex_like(ret).fillna(False).to_numpy(bool) & mem.reindex_like(ret).fillna(False).to_numpy(bool)
    L, idx, cols = lvl.to_numpy(), ret.index, ret.columns
    n = len(idx)
    for j in range(F.shape[1]):
        last = -10**9
        for i in np.flatnonzero(F[:, j]):
            if i - last < gap:
                continue
            last = i
            for h in horizons:
                if i + h < n and L[i, j] > 0:
                    rows.append((idx[i], cols[j], h, L[i + h, j] / L[i, j] - 1 - bh[h][i]))
    return pd.DataFrame(rows, columns=["date", "tk", "h", "ex"])


def summarize(df, smp, label, horizons=(5, 21, 63)):
    lines = []
    for h in horizons:
        x = df[df.h == h].set_index("date").ex
        if len(x) < 10:
            lines.append(f"  [{smp}] {label} {h}일: 사건 {len(x)} (부족)"); continue
        mth = x.groupby(x.index.to_period("M")).mean()
        t = mth.mean() / (mth.std(ddof=1) / np.sqrt(len(mth))) if len(mth) > 2 else np.nan
        per = " · ".join(f"{k} {x[(x.index >= a) & (x.index <= b)].mean():+.1%}" for k, a, b in PER if len(x[(x.index >= a) & (x.index <= b)]) >= 5)
        lines.append(f"  [{smp}] {label} {h}일: n={len(x)} · 평균 {x.mean():+.2%} (비용 {COST[smp]:.2%} 참고) · 중앙 {x.median():+.2%} · 양수 {(x > 0).mean():.0%}"
                     f" · 월군집 t {t:+.2f}({len(mth)}개월) | {per}")
    return lines


def study(label, rule, P=None, markets=("kr", "us"), gap=21, horizons=(5, 21, 63)):
    P = P or panels()
    out = []
    for smp in markets:
        ret, close, mem, tv = P[smp]
        flag = rule(ret, close, mem, tv) if smp == "kr" or tv is not None else rule(ret, close, mem, None)
        if flag is None:
            out.append(f"  [{smp}] {label}: 자료 없음"); continue
        out += summarize(run_events(flag, ret, mem, horizons, gap), smp, label, horizons)
    print(f"■ {label}"); print("\n".join(out), flush=True)
    return out
