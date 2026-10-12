#!/usr/bin/env python3
"""뉴스 보고 바로 샀다면 — 결과를 모르는 표본(EXPLORATORY, 판정 없음).

    python research/strategy-lab/news_chase_unbiased.py    # → findings/news-chase-unbiased-2026-10.md

표본 = 장 초반 실험(early_session_herd)의 '09:10 에 전일 대비 +5% 이상'(전일 시총 2,000억↑) 사건 10,107건에서 무작위 1,200건(시드 20261013).
그날 결과와 무관하게 뽑혔다 → 09:10 진입 수익이 공정하다.
뉴스 = 구글 뉴스 RSS(전날~다음 날) 제목+날짜, 종목명 포함만(.cache/google_news_dated/, 커밋 안 함). 기사 시각이 날짜 단위라:
  '전날 뉴스' = KST 날짜가 사건 전날인 기사(장 시작 전에 있던 것이 확실) · '당일 뉴스' = 사건 날짜(시각 불명 — 급등 뒤 시황 기사 포함 가능).
"""
from __future__ import annotations

import glob
import json
import re
import sys
import time
import urllib.parse
import urllib.request
from datetime import timedelta, timezone
from email.utils import parsedate_to_datetime
from pathlib import Path

import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import news_chase_study as ncs  # noqa: E402

OUT = HERE / "findings" / "news-chase-unbiased-2026-10.md"
GN = HERE / ".cache" / "google_news_dated"
N, SEED, COST = 1200, 20261013, 33.5
KST = timezone(timedelta(hours=9))


def fetch(name, d):
    p = GN / f"{name}_{d}.json"
    if p.exists():
        return json.loads(p.read_text(encoding="utf-8"))
    a = (pd.to_datetime(d, format="%Y%m%d") - pd.Timedelta(days=1)).strftime("%Y-%m-%d")
    b = (pd.to_datetime(d, format="%Y%m%d") + pd.Timedelta(days=1)).strftime("%Y-%m-%d")
    u = "https://news.google.com/rss/search?" + urllib.parse.urlencode({"q": f'"{name}" after:{a} before:{b}', "hl": "ko", "gl": "KR", "ceid": "KR:ko"})
    x = urllib.request.urlopen(urllib.request.Request(u, headers={"User-Agent": "Mozilla/5.0"}), timeout=20).read().decode("utf-8", "replace")
    items = []
    for blk in re.findall(r"<item>(.*?)</item>", x, re.S):
        t = re.search(r"<title>(.*?)</title>", blk, re.S)
        pd_ = re.search(r"<pubDate>(.*?)</pubDate>", blk, re.S)
        if not t:
            continue
        title = re.sub(r"\s+-\s+[^-]+$", "", re.sub(r"<!\[CDATA\[|\]\]>", "", t.group(1)))
        if name not in title:
            continue
        kst = ""
        if pd_:
            try:
                kst = parsedate_to_datetime(pd_.group(1)).astimezone(KST).strftime("%Y%m%d")
            except Exception:
                kst = ""
        items.append([title, kst])
    GN.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(items, ensure_ascii=False), encoding="utf-8")
    time.sleep(1.5)
    return items


def names():
    fs = sorted(glob.glob(str(HERE / "data" / "krx-daily-ext" / "2025-*.parquet"))) + sorted(glob.glob(str(HERE / "data" / "krx-daily-ext" / "2026-*.parquet")))
    e = pd.concat([pd.read_parquet(f, columns=["BAS_DD", "ISU_CD", "ISU_NM"]) for f in fs], ignore_index=True)
    return e.set_index(["BAS_DD", "ISU_CD"]).ISU_NM


def main():
    ev = pd.read_parquet(HERE / ".cache" / "early_herd_events.parquet").dropna(subset=["ret_close"])
    s = ev.sample(n=min(N, len(ev)), random_state=SEED).copy()
    nm = names()
    s["name"] = [nm.get((d, t), "") for d, t in zip(s.date, s.ticker)]
    s = s[s.name != ""]
    pre, same = [], []
    for i, r in enumerate(s.itertuples(), 1):
        try:
            it = fetch(r.name, r.date)
        except Exception as ex:
            print("실패", r.name, r.date, ex, flush=True)
            time.sleep(10)
            it = None
        prev_day = [t for t, k in (it or []) if k and k < r.date]
        today = [t for t, k in (it or []) if k == r.date]
        pre.append(None if it is None else ncs.cause_of(prev_day))
        same.append(None if it is None else ncs.cause_of(today))
        if i % 100 == 0:
            print(f"  {i}/{len(s)}", flush=True)
    s["pre"], s["same"] = pre, same
    s = s[s.pre.notna()]
    s.to_csv(HERE / ".cache" / "news_chase_unbiased.csv", index=False, encoding="utf-8-sig")
    strip = lambda c: c.replace("(시황 속)", "")
    s["pre1"], s["same1"] = s.pre.map(strip), s.same.map(strip)
    real = lambda c: c not in ("뉴스 없음", "시황 기사만")
    s["grp"] = np.select([s.pre1.map(real), s.same1.map(real), (s.pre1 == "시황 기사만") | (s.same1 == "시황 기사만")],
                         ["전날 재료 뉴스 있음", "당일 재료 뉴스만", "시황 기사만"], "뉴스 없음")
    cols = [("ret_close", "09:10 → 당일 종가"), ("ret_next_open", "09:10 → 다음 날 시가"), ("ret_5d", "09:10 → 5일 뒤 종가")]
    agg = lambda x: f"{x.mean() * 1e4:+.0f}bp / {x.median() * 1e4:+.0f}bp / {(x > 0).mean():.0%}" if len(x.dropna()) else "—"
    L = ["---", "track: kr", "factor: news-chase-unbiased", "date: 2026-10-13", "verdict: EXPLORATORY", "reason: >-",
         f"  사후 기술(판정 없음). 09:10 +5% 사건(결과 무관) 무작위 {len(s)}건에 구글 뉴스를 붙여, 뉴스가 있는 급등을 09:10 에 샀다면의 수익.", "---", "",
         "# 뉴스 보고 바로 샀다면 — 결과를 모르는 표본", "",
         "`news_chase_unbiased.py`. 칸 = 평균 / 중앙값 / 이긴 비율, 비용 33.5bp 전. 투자 자문이 아니다.", "",
         "| 뉴스 | 건수 | " + " | ".join(n for _, n in cols) + " |", "|---|---:|" + "---|" * len(cols)]
    for g, x in sorted(s.groupby("grp"), key=lambda kv: -len(kv[1])):
        L.append(f"| {g} | {len(x)} | " + " | ".join(agg(x[c]) for c, _ in cols) + " |")
    L.append(f"| **전체** | {len(s)} | " + " | ".join(agg(s[c]) for c, _ in cols) + " |")
    L += ["", "전날 재료 뉴스의 원인별(09:10 → 당일 종가):", "", "| 원인 | 건수 | 09:10 → 종가 | 5일 |", "|---|---:|---|---|"]
    for c, x in s[s.grp == "전날 재료 뉴스 있음"].groupby("pre1"):
        L.append(f"| {c} | {len(x)} | {agg(x.ret_close)} | {agg(x.ret_5d)} |")
    L += ["", "유형별(장 초반 실험 분류) × 뉴스:", "", "| 유형 | 뉴스 | 건수 | 09:10 → 종가 |", "|---|---|---:|---|"]
    for (k, g), x in s.groupby(["kind", "grp"]):
        if len(x) >= 15:
            L.append(f"| {k} | {g} | {len(x)} | {agg(x.ret_close)} |")
    L += ["", f"비용 {COST}bp(연속 매매 왕복). '당일 재료 뉴스'는 기사 시각을 몰라 급등 뒤에 나온 해설 기사가 섞인다.", ""]
    OUT.write_text("\n".join(L), encoding="utf-8")
    print("\n".join(L))


if __name__ == "__main__":
    main()
