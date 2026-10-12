#!/usr/bin/env python3
"""장중 뉴스 1분 뒤 매수 forward 기록기. 사전등록: findings/news-minute-forward-preregistration-2026-10.md

기사 원장 = VM news-alert(scripts/fetch-news-kr.js)가 쌓는 ~/collector-venv/news/news-log.jsonl
(관심종목 국내 353개 · 제목에 종목명 · 네이버 pubDate 분 단위). 분봉 = VM ~/minute-raw.
기사 갈래(제목으로, 우선순위 순): MOVE 시황(이미 움직인 뒤 '○% 급등' 류) > DISC 공시성 > OTHER 기타.

    python research/strategy-lab/run_news_minute_forward.py --sync      # VM 원장·새 분봉 복사(읽기 전용)
    python research/strategy-lab/run_news_minute_forward.py             # outcome 추가 기록(건수만 출력)
    python research/strategy-lab/run_news_minute_forward.py --judge     # 갈래별 판정 — 시점 전엔 거부
    python research/strategy-lab/run_news_minute_forward.py --selftest
먼저 DART 공시 캐시 증분: python research/strategy-lab/collect_dart_event_titles.py --update (dart 칸, 없으면 None)
"""
from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[1]
sys.path.insert(0, str(HERE))
import why_surge as ws  # noqa: E402

FREEZE, COST = "20261014", 33.5
FIRST, LAST = "09:00", "15:18"                 # 기사 시각 창 — 진입(+1분)이 15:19 연속 매매 안에 들게
STAGES = {1: (150, 6), 2: (300, 12)}           # (건수, 달 수)
REPORT = HERE / "reports" / "2026-10-news-minute-forward"
LOG, OBS = REPORT / "news_log.jsonl", REPORT / "observations.jsonl"
KST = timezone(timedelta(hours=9))
CATS = ("MOVE", "DISC", "OTHER")
MOVE_RE = re.compile(r"\d+(\.\d+)?\s*%|급등|급락|상승|하락|강세|약세|상한가|하한가|특징주|신고가|신저가|오름세|내림세|반등|반락|"
                     r"폭등|폭락|추락|들썩|껑충|훨훨|뚝|주가|↑|↓")
DISC_RE = re.compile(r"공시|공급계약|단일판매|수주|유상증자|무상증자|자사주|자기주식|전환사채|신주인수권|교환사채|합병|분할|최대주주|"
                     r"지분|잠정|실적|영업이익|매출액|순이익|배당|소각|상장폐지|거래정지|감자|소송|횡령|배임|불성실")
HORIZONS = ("m5", "m30", "close", "next")


def now_kst():
    return datetime.now(KST).strftime("%Y-%m-%d %H:%M:%S")


def read_jsonl(p):
    return [json.loads(l) for l in open(p, encoding="utf-8") if l.strip()] if p.exists() else []


def classify(title):
    return "MOVE" if MOVE_RE.search(title) else "DISC" if DISC_RE.search(title) else "OTHER"


def sync():
    REPORT.mkdir(parents=True, exist_ok=True)
    subprocess.run(["scp", "-q", "stock-new:~/collector-venv/news/news-log.jsonl", str(LOG)], check=True, timeout=120)
    print(f"원장 {len(read_jsonl(LOG))}행")
    import run_close_weakness_forward as cw
    cw.sync()


def events(rows):
    """원장 → 갈래별 그날 첫 기사(종목·날짜·갈래당 1건). 장중 창 밖·동결일 전은 버린다."""
    best = {}
    for r in rows:
        if not r.get("pubDate"):
            continue
        p = datetime.fromisoformat(r["pubDate"].replace("Z", "+00:00")).astimezone(KST)
        d, hm = p.strftime("%Y%m%d"), p.strftime("%H:%M")
        if d < FREEZE or not FIRST <= hm <= LAST:
            continue
        k = (r["code"], d, classify(r["title"]))
        if k not in best or hm < best[k]["pub_hm"]:
            best[k] = dict(ticker=r["code"], name=r["name"], date=d, pub_hm=hm, cat=k[2], level=r.get("level"),
                           flags=r.get("flags", []), title=r["title"][:80], link=r["link"])
    return sorted(best.values(), key=lambda e: (e["date"], e["pub_hm"], e["ticker"]))


def grid(m):
    """분봉 → 분 × 종목 종가표(거래 없는 분은 직전 종가). 15:30 은 종가 단일가."""
    piv = m.pivot_table(index="hm", columns="ticker", values="close", aggfunc="last")
    t = pd.date_range("2000-01-01 09:00", "2000-01-01 15:19", freq="min").strftime("%H:%M").tolist() + ["15:30"]
    return piv.reindex(sorted(set(t) | set(piv.index))).ffill().reindex(t)


def plus(hm, k):
    h, m = map(int, hm.split(":"))
    x = h * 60 + m + k
    return "15:30" if x > 15 * 60 + 19 else f"{x // 60:02d}:{x % 60:02d}"


def outcome(ev, piv, nxt_close):
    """진입 = 기사 분 + 1분 봉의 종가(초 단위가 59초여도 1분 이상 뒤). 반환 (raw_bp, mkt_bp) 또는 None."""
    e = plus(ev["pub_hm"], 1)
    t = ev["ticker"]
    if t not in piv.columns or pd.isna(piv.at[e, t]):
        return None
    p0, all0 = piv.at[e, t], piv.loc[e]
    ends = {"m5": piv.loc[plus(e, 5)], "m30": piv.loc[plus(e, 30)], "close": piv.loc["15:30"], "next": nxt_close}
    raw, mkt = {}, {}
    for h, row in ends.items():
        r = (row.reindex(piv.columns) / all0 - 1).dropna()
        raw[h] = float(r[t] * 1e4) if t in r.index else None
        mkt[h] = float(r.mean() * 1e4)
    return raw, mkt


def dart_titles(ticker, d, corp):
    """그날 DART 거래소공시·주요사항 제목. 캐시가 그날까지 안 왔거나 대상 밖이면 None(잴 수 없음 ≠ 없음)."""
    p = HERE / "data" / "dart_event_titles" / f"{corp.get(ticker, '_')}.json"
    if not p.exists():
        return None
    j = json.load(open(p, encoding="utf-8"))
    if j.get("_through", "") < d:
        return None
    return [x["nm"].strip()[:40] for k in ("I", "B") for x in j.get(k, []) if x["d"] == d]


def run_update():
    days = sorted(p.name[5:].replace("-", "") for p in ws.MIN.glob("date=*"))
    obs = read_jsonl(OBS)
    done = {(r["ticker"], r["date"], r["cat"]) for r in obs}
    corp = {}
    for line in open(REPO / "data" / "backfill" / "dart" / "corpcode.jsonl", encoding="utf-8"):
        j = json.loads(line)
        if j.get("ticker"):
            corp[j["ticker"]] = j["corp"]
    todo = [e for e in events(read_jsonl(LOG)) if (e["ticker"], e["date"], e["cat"]) not in done]
    new, waiting, cache = [], 0, {}
    for e in todo:
        d = e["date"]
        if d not in days or days.index(d) + 1 >= len(days):
            waiting += 1                                    # 분봉 또는 다음 거래일 분봉 대기
            continue
        if d not in cache:
            nd = days[days.index(d) + 1]
            cache = {d: (grid(ws.minutes(d)), grid(ws.minutes(nd)).loc["15:30"], nd)}
        piv, nxt, nd = cache[d]
        o = outcome(e, piv, nxt)
        if o is None:
            continue
        new.append(dict(e, type="outcome", entry_hm=plus(e["pub_hm"], 1), next_date=nd, raw_bp=o[0], mkt_bp=o[1],
                        dart=dart_titles(e["ticker"], d, corp), recorded_at=now_kst()))
    if new:
        REPORT.mkdir(parents=True, exist_ok=True)
        with open(OBS, "a", encoding="utf-8", newline="\n") as f:
            for r in new:
                f.write(json.dumps(r, ensure_ascii=False) + "\n")
    allr = obs + new
    by = {c: sum(r["cat"] == c for r in allr) for c in CATS}
    print(f"새 outcome {len(new)} · 대기 {waiting} · 누적 {' · '.join(f'{c} {n}' for c, n in by.items())} · "
          f"dart 미확인 {sum(r['dart'] is None for r in new)}/{len(new)} · 판정은 갈래별 {STAGES[1][0]}건·{STAGES[1][1]}개월 뒤 — 그 전엔 기록만")


def verdict(df, final):
    """주 지표 = 종가 청산 초과(raw − 같은 구간 시장 평균), 월평균의 t. 원수익이 비용 33.5bp 를 넘어야 ECONOMIC."""
    x = df.raw_close - df.mkt_close
    mo = x.groupby(df.date.str[:6]).mean()
    t = mo.mean() / (mo.std(ddof=1) / np.sqrt(len(mo))) if len(mo) > 1 else float("nan")
    raw = df.raw_close.mean()
    if not x.mean() > 0:
        v = "REJECT"
    elif t >= 2:
        v = "ECONOMIC" if raw - COST > 0 else "INFORMATION"
    else:
        v = "REJECT" if final else "INCONCLUSIVE"
    return dict(verdict=v, n=int(len(df)), months=int(len(mo)), excess_bp=float(x.mean()), t=float(t),
                raw_bp=float(raw), raw_net_bp=float(raw - COST))


def run_judge():
    rows = [dict(r, raw_close=r["raw_bp"]["close"], mkt_close=r["mkt_bp"]["close"]) for r in read_jsonl(OBS)]
    df = pd.DataFrame(rows)
    for c in CATS:
        s = df[df.cat == c].sort_values(["date", "pub_hm"]) if len(df) else df
        f1, f2 = REPORT / f"judge_{c}_stage1.json", REPORT / f"judge_{c}_stage2.json"
        n = len(s)
        months = s.date.str[:6].nunique() if n else 0
        if not f1.exists() and n >= STAGES[1][0] and months >= STAGES[1][1]:
            st = 1
        elif (f1.exists() and not f2.exists() and json.load(open(f1, encoding="utf-8"))["verdict"] == "INCONCLUSIVE"
              and n >= STAGES[2][0] and months >= STAGES[2][1]):
            st = 2
        else:
            print(f"{c}: 판정 시점 아님(또는 끝) — {n}건 · {months}개월 · 1차 {STAGES[1]} · 연장 {STAGES[2]}")
            continue
        res = verdict(s, final=(st == 2))
        res.update(cat=c, stage=st, judged_at=now_kst())
        json.dump(res, open(f1 if st == 1 else f2, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
        print(json.dumps(res, ensure_ascii=False))


def selftest():
    assert classify("에코프로, 2차전지 강세에 7% 급등") == "MOVE"
    assert classify("삼성전자, 3조 규모 자사주 매입 결정") == "DISC"
    assert classify("HLB, 美 FDA 허가 획득") == "OTHER"
    assert classify("○○, 수주 공시에 상한가") == "MOVE"            # 이미 움직인 뒤 기사가 우선
    rows = [{"code": "000010", "name": "가", "pubDate": "2026-10-14T01:05:00.000Z", "title": "가 공급계약 체결", "link": "a"},
            {"code": "000010", "name": "가", "pubDate": "2026-10-14T01:20:00.000Z", "title": "가 수주", "link": "b"},
            {"code": "000010", "name": "가", "pubDate": "2026-10-14T01:30:00.000Z", "title": "가 10% 급등", "link": "c"},
            {"code": "000010", "name": "가", "pubDate": "2026-10-13T23:30:00.000Z", "title": "가 공시", "link": "d"},   # 장 전
            {"code": "000010", "name": "가", "pubDate": "2026-10-13T02:00:00.000Z", "title": "가 공시", "link": "e"}]   # 동결 전
    ev = events(rows)
    assert [(e["pub_hm"], e["cat"]) for e in ev] == [("10:05", "DISC"), ("10:30", "MOVE")]
    m = pd.DataFrame({"ticker": ["000010"] * 3 + ["000020"] * 2, "hm": ["10:06", "10:11", "15:30", "10:06", "15:30"],
                      "close": [100.0, 102, 110, 50, 50]})
    piv = grid(m)
    assert piv.at["10:08", "000010"] == 100 and piv.at["15:19", "000010"] == 102          # 거래 없는 분은 직전 종가
    raw, mkt = outcome(ev[0], piv, pd.Series({"000010": 99.0, "000020": 55.0}))
    assert abs(raw["m5"] - 200) < 1e-9 and abs(raw["close"] - 1000) < 1e-9 and abs(raw["next"] + 100) < 1e-9
    assert abs(mkt["close"] - 500) < 1e-9 and abs(mkt["next"] - 450) < 1e-9
    assert plus("15:10", 30) == "15:30" and plus("09:59", 1) == "10:00"
    df = pd.DataFrame({"date": [f"2026{m:02d}15" for m in range(1, 13)], "raw_close": [60.0] * 12,
                       "mkt_close": [10.0 + (m % 2) for m in range(12)]})
    assert verdict(df, False)["verdict"] == "ECONOMIC"
    assert verdict(df.assign(raw_close=20.0), False)["verdict"] == "INFORMATION"
    assert verdict(df.assign(raw_close=5.0), False)["verdict"] == "REJECT"
    print("selftest 통과")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    g = ap.add_mutually_exclusive_group()
    for k in ("sync", "judge", "selftest"):
        g.add_argument(f"--{k}", action="store_true")
    a = ap.parse_args()
    (sync if a.sync else run_judge if a.judge else selftest if a.selftest else run_update)()
