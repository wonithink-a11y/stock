#!/usr/bin/env python3
"""급등일 뉴스 보고 바로 샀다면 — 사후 기술(EXPLORATORY, 판정 없음).

    python research/strategy-lab/news_chase_study.py     # → findings/news-chase-2025-08-2026-10.md

사건 = 분봉 기간(2025-08-08 ~ 2026-10-08) 일 +15% 이상 마감·전일 시총 2,000억↑ 종목-날(.cache/surge_events_ext.csv).
뉴스 = 구글 뉴스 RSS 날짜 범위(전날~다음 날) 제목, 종목명 포함만(.cache/google_news/, 커밋 안 함). 기사 시각은 RSS 가 날짜 단위라 모른다 —
그래서 '뉴스 보고 산 시점'을 장중 알림 시점(10분 점검에서 처음 전일 대비 +5%)으로 근사한다. 그 시점에 뉴스가 이미 나와 있었는지는 보장 못 한다.
결과에 급등일 자체를 고른 선택 편향이 있다: 진입 뒤 그날 +15% 까지 간 종목만 모았다 → 당일 종가 수익은 위로 치우친다(그래서 다음 날·5일이 핵심).
"""
from __future__ import annotations

import glob
import json
import re
import sys
from pathlib import Path

import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import why_surge as ws  # noqa: E402

OUT = HERE / "findings" / "news-chase-2025-08-2026-10.md"
GN = HERE / ".cache" / "google_news"
COST = 0.00335
RECAP = re.compile(r"특징주|급등|급락|상한가|하한가|강세|약세|신고가|\d+(\.\d+)?%|주가|투자분석|이격도|무슨 회사|오늘의|마감|장중|시황|종목\s*(분석|진단)|대박|예감")
CAUSES = [("허가·임상", r"FDA|임상|승인|허가|품목|신약|기술이전|라이선스|학회"),
          ("수주·계약", r"수주|공급\s*계약|계약\s*체결|납품|공급사"),
          ("실적", r"실적|영업이익|흑자|매출|어닝|분기"),
          ("M&A·지분", r"인수|매각|합병|지분|최대주주|경영권|공개매수|M&A"),
          ("주주환원", r"자사주|소각|배당|주주환원|밸류업"),
          ("정책·정부", r"정부|정책|국책|클러스터|예산|법안|규제|국토부|산업부|대통령|특별법|공약"),
          ("해외·업황", r"엔비디아|미국|중국|수출|관세|트럼프|업황|가격\s*인상|유가|비트코인"),
          ("신사업·기술", r"신사업|개발|양산|전고체|로봇|AI|HBM|원전|우주|진출|협력|MOU|파트너")]


def cause_of(titles):
    if titles is None:
        return "조회 실패"
    if not titles:
        return "뉴스 없음"
    body = " ".join(s for s in titles if not RECAP.search(s))
    for k, pat in CAUSES:
        if re.search(pat, body):
            return k
    allt = " ".join(titles)
    for k, pat in CAUSES:
        if re.search(pat, allt):
            return k + "(시황 속)"
    return "시황 기사만"


def fwd_table():
    fs = sorted(glob.glob(str(HERE / "data" / "krx-daily-ext" / "2025-*.parquet"))) + sorted(glob.glob(str(HERE / "data" / "krx-daily-ext" / "2026-*.parquet")))
    e = pd.concat([pd.read_parquet(f, columns=["BAS_DD", "ISU_CD", "TDD_CLSPRC", "FLUC_RT", "MKTCAP"]) for f in fs], ignore_index=True)
    e["r"] = pd.to_numeric(e.FLUC_RT, errors="coerce") / 100
    e["prev"] = e.TDD_CLSPRC / (1 + e.r)
    e = e.sort_values(["ISU_CD", "BAS_DD"])
    e["fwd5"] = np.expm1(e.groupby("ISU_CD")["r"].transform(lambda s: np.log1p(s.clip(-0.31, 0.31)).shift(-1).rolling(5).sum().shift(-4)))
    e["cap0"] = e.groupby("ISU_CD").MKTCAP.shift(1)
    return e.set_index(["BAS_DD", "ISU_CD"])


def main():
    ev = pd.read_csv(HERE / ".cache" / "surge_events_ext.csv", dtype={"date": str, "ticker": str})
    D = fwd_table()
    days = sorted(p.name[5:].replace("-", "") for p in ws.MIN.glob("date=*"))
    nxt_day = {d: days[i + 1] for i, d in enumerate(days[:-1])}
    rows = []
    for d, g in ev.groupby("date"):
        m = ws.minutes(d)
        if m is None:
            continue
        piv = m.pivot_table(index="hm", columns="ticker", values="close").ffill()
        mn = ws.minutes(nxt_day[d]) if d in nxt_day else None
        nopen = mn.sort_values("hm").groupby("ticker").open.first() if mn is not None else pd.Series(dtype=float)
        checks = [h for h in piv.index if h.endswith("0")]
        for r in g.itertuples():
            if r.ticker not in piv.columns or (d, r.ticker) not in D.index:
                continue
            dd = D.loc[(d, r.ticker)]
            s = piv[r.ticker]
            hit = [h for h in checks if s.get(h, np.nan) / dd.prev - 1 >= 0.05]
            if not hit:
                continue
            h = hit[0]
            pe = s[h]
            close = s.iloc[-1]
            no = nopen.get(r.ticker, np.nan)
            f5 = dd.fwd5
            p = GN / f"{r.name}_{d}.json"
            titles = json.loads(p.read_text(encoding="utf-8")) if p.exists() else None
            rows.append(dict(date=d, ticker=r.ticker, name=r.name, cap0=dd.cap0, entry_at=h, entry_gain=pe / dd.prev - 1,
                             r_close=close / pe - 1, r_next_open=no / pe - 1, r_5d=close / pe * (1 + f5) - 1 if np.isfinite(f5) else np.nan,
                             r_nextopen_5d=(close * (1 + f5)) / no - 1 if np.isfinite(f5) and no > 0 else np.nan, cause=cause_of(titles)))
    x = pd.DataFrame(rows)
    x.to_csv(HERE / ".cache" / "news_chase_events.csv", index=False, encoding="utf-8-sig")
    x = x[x.cause != "조회 실패"]
    x["cause1"] = x.cause.str.replace(r"\(시황 속\)", "", regex=True)
    x["half"] = np.where(x.date < "20260301", "앞", "뒤")
    cols = [("r_next_open", "알림 시점 → 다음 날 시가"), ("r_5d", "알림 시점 → 5일 뒤 종가"), ("r_nextopen_5d", "다음 날 시가 → 5일 뒤 종가"), ("r_close", "알림 시점 → 당일 종가(편향)")]

    def agg(s):
        s = s.dropna()
        return f"{s.mean() * 100:+.2f}% / {s.median() * 100:+.2f}% / {(s > 0).mean():.0%}" if len(s) else "—"

    L = ["---", "track: kr", "factor: news-chase", "date: 2026-10-13", "verdict: EXPLORATORY", "reason: >-",
         f"  사후 기술(판정 없음). 분봉 기간 급등 {len(x)}건(일 +15% 마감, 시총 2,000억↑)을 구글 뉴스 제목으로 원인 분류하고 장중 알림 시점(+5%)에 샀다면의 수익. '알림 시점' 칸은 결과로 고른 표본이라 무효 — 다음 날 시가 진입 칸만 유효.", "---", "",
         "# 급등일 뉴스 보고 바로 샀다면 (2025-08 ~ 2026-10)", "",
         "`news_chase_study.py` 출력. 칸 = 평균 / 중앙값 / 이긴 비율. 비용 33.5bp 전. **★ 급등일(그날 +15% 마감)만 모았으므로 '알림 시점 →' 세 칸은 전부 그날 남은 상승을 미리 알고 산 값이다(결과로 고른 표본) — 전략 수익으로 읽으면 안 된다. 치우침 없는 칸은 '다음 날 시가 → 5일 뒤 종가' 하나뿐이다.** 결과를 모르는 표본은 news-chase-unbiased 문서.", "",
         f"사건 {len(x)} · 뉴스 있음 {(x.cause != '뉴스 없음').mean():.0%} · 원인 키워드 잡힘 {(~x.cause1.isin(['뉴스 없음', '시황 기사만'])).mean():.0%}", "",
         "## 1. 원인별", "", "| 원인 | 건수 | " + " | ".join(n for _, n in cols) + " |", "|---|---:|" + "---|" * len(cols)]
    for c, g in sorted(x.groupby("cause1"), key=lambda kv: -len(kv[1])):
        L.append(f"| {c} | {len(g)} | " + " | ".join(agg(g[k]) for k, _ in cols) + " |")
    L.append(f"| **전체** | {len(x)} | " + " | ".join(agg(x[k]) for k, _ in cols) + " |")
    L += ["", "## 2. 반기별(전체)", "", "| 반기 | 건수 | " + " | ".join(n for _, n in cols) + " |", "|---|---:|" + "---|" * len(cols)]
    for hname, g in x.groupby("half"):
        L.append(f"| {hname} | {len(g)} | " + " | ".join(agg(g[k]) for k, _ in cols) + " |")
    L += ["", "## 3. 알림 시각별(전체, 알림 시점 → 5일)", "", "| 시각 | 건수 | 평균 / 중앙값 / 이긴 비율 |", "|---|---:|---|"]
    for hh, g in x.groupby(x.entry_at.str[:2]):
        L.append(f"| {hh}시 | {len(g)} | {agg(g.r_5d)} |")
    L += ["", f"비용 33.5bp 를 빼면 각 평균에서 0.34%p 를 더 뺀다. 원인 분류는 제목 키워드 근사(스팸성 제목 오분류 있음).", ""]
    OUT.write_text("\n".join(L), encoding="utf-8")
    print("\n".join(L))


if __name__ == "__main__":
    main()
