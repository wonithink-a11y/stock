#!/usr/bin/env python3
"""2026-08 ~ 현재 하루 단위 순환매·개별 급등·미국 선후행 진단 — 사후 기술(판정 없음, 예측 아님).

    python research/strategy-lab/diag_daily_rotation_2026.py [시작 YYYYMMDD]   # → findings/daily-rotation-2026-08-10.md

자료: KRX 일별(data/krx-daily-ext, FLUC_RT = 종가 대비) · 업종 롤업·테마 트리(diag_sideways_sectors.labels) ·
DART 공시 제목 캐시(data/dart_event_titles, A5 패널 1,724종목) · 미국 종가(.cache/us_rotation_close.csv, yfinance).
표본이 두 달 남짓(≈45거래일)이라 상관 하나의 표준오차가 약 0.15다 — 패턴 '후보'이지 검증이 아니다.
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
import diag_sideways_sectors as dss  # noqa: E402

OUT = HERE / "findings" / "daily-rotation-2026-08-10.md"
MIN_CAP = 3e11            # 개별 종목 분석 최소 시총 3,000억(잡음 축소)
SURGE = 0.15
US_MAP = {"반도체": ["^SOX", "NVDA"], "전자부품·디스플레이": ["^SOX"], "전력·전기장비": ["GRID", "XLU"], "2차전지": ["LIT"],
          "항공·방산": ["ITA"], "바이오·헬스케어": ["XBI", "XLV"], "금융": ["XLF", "KRE"], "IT·소프트웨어": ["XLK", "^IXIC"],
          "건설·부동산·건자재": ["XLB", "XLRE"], "화학·소재": ["XLB"], "조선·해운·운송": ["XLI"], "유통·소비재": ["XLY", "XLP"],
          "자동차·부품": ["XLY"], "철강·비철금속": ["XLB"]}
CAUSES = [("공급·수주 계약", r"공급계약|수주|판매ㆍ공급"), ("실적", r"영업\(잠정\)실적|매출액또는손익|손익구조"),
          ("자사주·주주환원", r"자기주식|소각|배당"), ("증자·사채(희석)", r"유상증자|전환사채|신주인수권|교환사채"),
          ("무상증자·분할", r"무상증자|주식분할|액면분할"), ("M&A·지분", r"타법인주식|합병|영업양수|최대주주|공개매수"),
          ("시설투자·특허", r"시설투자|신규시설|특허"), ("조회공시·풍문", r"조회공시|풍문|해명")]


def load(start):
    fs = sorted(glob.glob(str(HERE / "data" / "krx-daily-ext" / "2026-0[6789].parquet"))) + \
        sorted(glob.glob(str(HERE / "data" / "krx-daily-ext" / "2026-1*.parquet")))
    e = pd.concat([pd.read_parquet(f) for f in fs], ignore_index=True)
    e["r"] = pd.to_numeric(e.FLUC_RT, errors="coerce") / 100
    e = e.sort_values(["ISU_CD", "BAS_DD"])
    e["cap0"] = e.groupby("ISU_CD").MKTCAP.shift(1)
    e = e[(e.BAS_DD >= start) & e.r.notna() & (e.cap0 > 0) & e.ISU_CD.str.endswith("0")]
    e["r"] = e.r.clip(-0.31, 0.31)
    sec, th = dss.labels(e.ISU_CD.unique())
    e["sector"], e["theme"] = e.ISU_CD.map(sec), e.ISU_CD.map(th)
    return e


def cw(g):
    return np.average(g.r, weights=g.cap0)


def rotation(e):
    """반도체가 시장 시총의 절반이라 '시장 대비'는 반도체와 기계적으로 음의 상관이 된다 → 기준 = 반도체 업종을 뺀 시장(M2)."""
    mkt = e.groupby("BAS_DD").apply(cw, include_groups=False)
    m2 = e[e.sector != "반도체"].groupby("BAS_DD").apply(cw, include_groups=False)
    S = e.groupby(["BAS_DD", "sector"]).apply(cw, include_groups=False).unstack()
    n = e.groupby("sector").ISU_CD.nunique()
    S = S[[c for c in S.columns if n.get(c, 0) >= 15 and c != "미분류"]]
    X = S.sub(m2, axis=0)                                    # 반도체 뺀 시장 대비
    semi = X["반도체"]                                       # 반도체 상대 강도
    lo, hi = semi <= semi.quantile(1 / 3), semi >= semi.quantile(2 / 3)
    kospi_dn = mkt <= -0.01
    tab = pd.DataFrame({
        "누적초과": (1 + S).prod() - (1 + m2).prod(),
        "반도체 상대강도와 동시 상관": X.corrwith(semi),
        "다음날 상관": X.shift(-1).corrwith(semi),
        "반도체 약한 날": X[lo].mean(), "반도체 강한 날": X[hi].mean(),
        "시장 −1%↓ 날": X[kospi_dn].mean()})
    return tab.drop(index="반도체"), mkt, S, X, int(kospi_dn.sum()), int(lo.sum()), m2


def weekly_leaders(S):
    w = (1 + S).groupby(pd.to_datetime(S.index).to_period("W-FRI")).prod() - 1
    return {str(k.start_time.date()): list(r.sort_values(ascending=False).index[:3]) + ["/"] + list(r.sort_values().index[:2]) for k, r in w.iterrows()}


def persistence(e, X):
    """지난 5일 → 다음 5일 순위 상관(업종: 반도체 뺀 시장 대비 / 종목: 시총 3,000억 이상 원수익). 5일 간격 표본."""
    xs = []
    for i in range(5, len(X) - 5, 5):
        a, b = X.iloc[i - 5:i].sum(), X.iloc[i:i + 5].sum()
        xs.append(a.corr(b, method="spearman"))
    big = e[e.cap0 >= MIN_CAP].pivot_table(index="BAS_DD", columns="ISU_CD", values="r")
    st = []
    for i in range(5, len(big) - 5, 5):
        a, b = np.log1p(big.iloc[i - 5:i]).sum(min_count=5), np.log1p(big.iloc[i:i + 5]).sum(min_count=5)
        st.append(a.corr(b, method="spearman"))
    return float(np.mean(xs)), len(xs), float(np.mean(st)), len(st), xs, st


def down_day_winners(e, mkt):
    dn = mkt[mkt <= -0.01].index
    big = e[e.cap0 >= MIN_CAP]
    piv = big.pivot_table(index="BAS_DD", columns="ISU_CD", values="r")
    m = mkt.reindex(piv.index)
    beta = piv.apply(lambda s: s.cov(m) / m.var())
    up_dn = (piv.loc[dn] > 0).mean()
    tot = (1 + piv).prod() - 1
    info = big.groupby("ISU_CD").agg(name=("ISU_NM", "last"), sector=("sector", "last"), theme=("theme", "last"), cap=("cap0", "last"))
    d = info.assign(up_on_down=up_dn, n_dn=len(dn), beta=beta, total=tot, dn_mean=piv.loc[dn].mean()).dropna(subset=["up_on_down"])
    return d.sort_values(["up_on_down", "dn_mean"], ascending=False)


def titles_index():
    corp = {}
    for line in open(HERE.parents[1] / "data" / "backfill" / "dart" / "corpcode.jsonl", encoding="utf-8"):
        j = json.loads(line)
        if j.get("ticker"):
            corp[j["ticker"]] = j["corp"]
    return corp


def surge_causes(e):
    corp = titles_index()
    tdir = HERE / "data" / "dart_event_titles"
    days = sorted(e.BAS_DD.unique())
    prev = {d: days[i - 1] if i else d for i, d in enumerate(days)}
    s = e[(e.r >= SURGE) & (e.cap0 >= 2e11)].copy()
    # 같은 날 같은 업종에서 +5% 이상 오른 종목 수(동반 상승)
    hot = e[e.r >= 0.05].groupby(["BAS_DD", "sector"]).size()
    s["peers"] = [int(hot.get((d, sc), 1)) - 1 for d, sc in zip(s.BAS_DD, s.sector)]
    rows, cover = [], 0
    for r in s.itertuples():
        p = tdir / f"{corp.get(r.ISU_CD, '')}.json"
        cause, title = [], ""
        if p.exists():
            cover += 1
            j = json.load(open(p, encoding="utf-8"))
            ts = [x["nm"].strip() for k in ("I", "B") for x in j.get(k, []) if prev[r.BAS_DD] <= x["d"] <= r.BAS_DD]
            for nm, pat in CAUSES:
                if any(re.search(pat, t.replace(" ", "")) for t in ts):
                    cause.append(nm)
            title = ts[0][:40] if ts else ""
        kind = "공시: " + "·".join(cause) if cause else ("업종 동반" if r.peers >= 3 else ("공시 없음(캐시 있음)" if p.exists() else "공시 캐시 없음"))
        rows.append(dict(date=r.BAS_DD, ticker=r.ISU_CD, name=r.ISU_NM, sector=r.sector, theme=r.theme, r=r.r, peers=r.peers, kind=kind, title=title))
    return pd.DataFrame(rows), cover, len(s)


def us_leadlag(X, S):
    us = pd.read_csv(HERE / ".cache" / "us_rotation_close.csv", index_col=0, parse_dates=True).pct_change(fill_method=None)
    kd = pd.to_datetime(S.index)
    out = []
    for sec, tks in US_MAP.items():
        if sec not in S.columns:
            continue
        for tk in tks:
            u = us[tk].dropna()
            prev_us = pd.Series([u[u.index < d].iloc[-1] if (u.index < d).any() else np.nan for d in kd], index=S.index)
            same_us = pd.Series([u.get(d, np.nan) for d in kd], index=S.index)          # 한국 장 마감 뒤 열리는 같은 날짜 미국
            k = S[sec]
            out.append(dict(sector=sec, us=tk,
                            prevUS_to_KR=k.corr(prev_us),                 # 밤사이 전달(시가 갭에 반영 — 매매 불가)
                            prevUS_to_KRnext=k.shift(-1).corr(prev_us),   # 하루 늦은 전달(매매 가능한 쪽)
                            KR_to_sameUS=k.corr(same_us),                 # 한국이 먼저 → 같은 날 미국
                            n=int(k.notna().sum())))
    return pd.DataFrame(out)


def pc(x):
    return "—" if pd.isna(x) else f"{x * 100:+.1f}%"


def main():
    start = sys.argv[1] if len(sys.argv) > 1 else "20260803"
    e = load(start)
    tab, mkt, S, X, n_dn, n_lo, m2 = rotation(e)
    wl = weekly_leaders(S)
    ps, nps, pst, npst, xs, st = persistence(e, X)
    dw = down_day_winners(e, mkt)
    sc, cover, n_s = surge_causes(e)
    ll = us_leadlag(X, S)
    days = sorted(e.BAS_DD.unique())
    L = ["---", "track: kr", "factor: daily-rotation-2026-08-10", "date: 2026-10-13", "verdict: EXPLORATORY", "reason: >-",
         f"  사후 기술(판정 없음, 예측 아님). {days[0]}~{days[-1]} {len(days)}거래일 하루 단위 업종 순환·하락일 강세 종목·급등 원인(공시 대조)·미국 선후행.", "---", "",
         "# 2026-08 ~ 10 하루 단위 순환매·개별 급등·미국 선후행 진단", "",
         f"`diag_daily_rotation_2026.py` 출력. {len(days)}거래일이라 상관 하나의 표준오차 ≈ {1 / np.sqrt(len(days)):.2f} — **패턴 후보이지 검증이 아니다.** 투자 자문이 아니다.", "",
         f"## 1. 업종 순환 (시총가중, 코스피+코스닥, **반도체 뺀 시장 대비** 초과) — 시장 −1% 이하 {n_dn}일 · 반도체 약한 날 {n_lo}일", "",
         "반도체가 시총의 절반이라 전체 시장 대비로 재면 다른 업종이 모두 반도체와 기계적으로 음의 상관이 된다 — 그래서 반도체 업종을 뺀 시장을 기준으로 쓴다.", "",
         "| 업종 | 누적 초과 | 반도체 상대강도와 동시 상관 | 다음날 상관 | 반도체 약한 날 | 반도체 강한 날 | 시장 −1%↓ 날 |", "|---|---:|---:|---:|---:|---:|---:|"]
    for k, r in tab.sort_values("반도체 상대강도와 동시 상관").iterrows():
        L.append(f"| {k} | {pc(r['누적초과'])} | {r['반도체 상대강도와 동시 상관']:+.2f} | {r['다음날 상관']:+.2f} | {pc(r['반도체 약한 날'])} | "
                 f"{pc(r['반도체 강한 날'])} | {pc(r['시장 −1%↓ 날'])} |")
    L += ["", "주별 주도(상위 3 / 하위 2, 업종 원수익):", ""] + [f"- {k}: {' · '.join(v)}" for k, v in wl.items()]
    L += ["", f"지속성(지난 5일 → 다음 5일 순위 상관 평균): 업종 {ps:+.2f}({nps}회) · 종목(시총 3,000억↑) {pst:+.2f}({npst}회). "
          "양이면 오른 것이 계속 오르는 쪽, 음이면 되돌림.", ""]
    top = dw[(dw.n_dn > 0)].head(25)
    L += ["", f"## 2. 시장 하락일(−1% 이하 {n_dn}일)에도 오른 종목 — 시총 3,000억 이상", "",
          f"전체 평균: 하락일 상승 비율 {dw.up_on_down.mean():.0%} · 베타 {dw.beta.median():.2f}. 상위 25 평균 베타 {top.beta.mean():.2f} · 구간 수익 중앙값 {pc(top.total.median())}.", "",
          "| 종목 | 업종 | 테마 | 하락일 상승 비율 | 하락일 평균 | 베타 | 구간 수익 |", "|---|---|---|---:|---:|---:|---:|"]
    for t, r in top.iterrows():
        L.append(f"| {r['name']}({t}) | {r.sector} | {r.theme or ''} | {r.up_on_down:.0%} | {pc(r.dn_mean)} | {r.beta:.2f} | {pc(r.total)} |")
    sect = top.sector.value_counts().head(6)
    L += ["", "상위 25 업종 분포: " + " · ".join(f"{k} {v}" for k, v in sect.items()), ""]
    kc = sc.kind.str.split(":").str[0].value_counts()
    L += [f"## 3. 급등일(+{SURGE:.0%} 이상, 전일 시총 2,000억 이상) {n_s}건 — 원인 대조", "",
          f"DART 제목 캐시가 있는 종목 {cover}건. 분류: " + " · ".join(f"{k} {v}" for k, v in kc.items()), "",
          "공시로 잡힌 원인: " + " · ".join(f"{k} {v}" for k, v in sc[sc.kind.str.startswith('공시:')].kind.str[4:].str.split('·').explode().value_counts().items()), "",
          "| 날짜 | 종목 | 업종 | 테마 | 당일 | 같은 업종 +5%↑ | 분류 | 공시 제목(첫 건) |", "|---|---|---|---|---:|---:|---|---|"]
    for r in sc.sort_values("r", ascending=False).head(40).itertuples():
        L.append(f"| {r.date} | {r.name} | {r.sector} | {r.theme or ''} | {pc(r.r)} | {r.peers} | {r.kind} | {r.title} |")
    L += ["", "## 4. 미국 선후행 (상관, 일 수익)", "",
          "- 밤사이 전달: 전날 미국 → 오늘 한국 업종(종가 대비). 시가 갭에 들어가므로 **매매로 못 먹는 쪽**.",
          "- 하루 늦은 전달: 전날 미국 → 내일 한국 업종. **매매 가능한 쪽** — 0 근처면 정보가 하루 안에 다 반영된 것.",
          "- 한국 → 같은 날짜 미국(한국 마감 뒤 열림).", "",
          "| 한국 업종 | 미국 | 밤사이 전달 | 하루 늦은 전달 | 한국 → 미국 | 일수 |", "|---|---|---:|---:|---:|---:|"]
    for r in ll.sort_values("prevUS_to_KR", ascending=False).itertuples():
        L.append(f"| {r.sector} | {r.us} | {r.prevUS_to_KR:+.2f} | {r.prevUS_to_KRnext:+.2f} | {r.KR_to_sameUS:+.2f} | {r.n} |")
    OUT.write_text("\n".join(L) + "\n", encoding="utf-8")
    print("\n".join(L))
    dw.to_csv(HERE / ".cache" / "down_day_winners.csv", encoding="utf-8-sig")
    sc.to_csv(HERE / ".cache" / "surge_causes.csv", encoding="utf-8-sig", index=False)


if __name__ == "__main__":
    main()
