#!/usr/bin/env python3
"""마감 30분 약세 대형주 forward 기록기. 사전등록: findings/close-weakness-reversal-preregistration-2026-10.md (커밋 71122107).

    python research/strategy-lab/run_close_weakness_forward.py --sync    # VM ~/minute-raw 의 새 날짜를 .cache/minute_raw 로 복사(읽기 전용)
    python research/strategy-lab/run_close_weakness_forward.py           # pick·outcome 추가 기록(건수만 출력)
    python research/strategy-lab/run_close_weakness_forward.py --judge   # 250 성숙일 전에는 거부
    python research/strategy-lab/run_close_weakness_forward.py --selftest
먼저 그달 KRX 일별: python research/strategy-lab/collect_krx_daily_ext.py <YYYY-MM>
"""
from __future__ import annotations

import argparse
import glob
import json
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import why_surge as ws  # noqa: E402

FREEZE = "20261014"
MIN_CAP, Q, MIN_N, COST = 2e12, 0.2, 25, 23.5
STAGES = {1: 250, 2: 500}
REPORT = HERE / "reports" / "2026-10-close-weakness-forward"
OBS = REPORT / "observations.jsonl"


def now_kst():
    return datetime.now(timezone(timedelta(hours=9))).strftime("%Y-%m-%d %H:%M:%S")


def read_jsonl(p):
    return [json.loads(l) for l in open(p, encoding="utf-8") if l.strip()] if p.exists() else []


def sync():
    have = {p.name for p in ws.MIN.glob("date=*")}
    out = subprocess.run(["ssh", "stock-new", "ls ~/minute-raw"], capture_output=True, text=True, timeout=60).stdout.split()
    new = sorted(d for d in out if d.startswith("date=") and d not in have and d.replace("-", "")[5:] >= "20261009")
    for d in new:
        subprocess.run(["scp", "-q", "-r", f"stock-new:~/minute-raw/{d}", str(ws.MIN)], check=True, timeout=600)
        print("복사", d)
    print(f"새 날짜 {len(new)}")


def caps():
    fs = sorted(glob.glob(str(HERE / "data" / "krx-daily-ext" / "2026-*.parquet"))) + sorted(glob.glob(str(HERE / "data" / "krx-daily-ext" / "2027-*.parquet")))
    e = pd.concat([pd.read_parquet(f, columns=["BAS_DD", "ISU_CD", "MKTCAP"]) for f in fs], ignore_index=True).sort_values(["ISU_CD", "BAS_DD"])
    e["cap0"] = e.groupby("ISU_CD").MKTCAP.shift(1)
    return e.set_index(["BAS_DD", "ISU_CD"]).cap0


def day_bars(d):
    m = ws.minutes(d)
    if m is None:
        return None
    m = m[m.ticker.str.endswith("0")].sort_values("hm")
    g = m.groupby("ticker")
    return pd.DataFrame({"open": g.open.first(), "close": g.close.last(), "c1459": m[m.hm <= "14:59"].groupby("ticker").close.last()})


def select(bars, cap0):
    """유니버스·마감 30분 수익·하위 20% 선택(동률 종목코드 순). 반환 (유니버스 index, 선택 list)."""
    b = bars.join(cap0.rename("cap0"), how="inner")
    b = b[(b.cap0 >= MIN_CAP) & b.close.notna() & b.c1459.notna() & (b.c1459 > 0)].copy()
    if len(b) < MIN_N:
        return b.index, []
    b["l30"] = b.close / b.c1459 - 1
    b = b.reset_index().sort_values(["l30", "ticker"])
    k = int(np.floor(len(b) * Q))
    return pd.Index(b.ticker), list(b.ticker.iloc[:k])


def run_update():
    days = sorted(p.name[5:].replace("-", "") for p in ws.MIN.glob("date=*"))
    obs = read_jsonl(OBS)
    picked = {r["date"]: r for r in obs if r["type"] == "pick"}
    done = {r["date"] for r in obs if r["type"] == "outcome"}
    C = caps()
    new = []
    for i, d in enumerate(days):
        if d < FREEZE:
            continue
        if d not in picked:
            bars = day_bars(d)
            try:
                cap0 = C.xs(d, level=0)
            except KeyError:
                continue                                  # 그날 KRX 일별 없음 — 일별 갱신 뒤 다시
            uni, picks = select(bars, cap0)
            if not picks:
                continue
            r = dict(type="pick", date=d, n_universe=len(uni), picks=picks, universe=list(uni), recorded_at=now_kst())
            picked[d] = r
            new.append(r)
        if d in done or i + 1 >= len(days):
            continue
        cur, nxt = day_bars(d), day_bars(days[i + 1])
        pr = picked[d]
        u = [t for t in pr["universe"] if t in cur.index and t in nxt.index]
        rc = (nxt.close.reindex(u) / cur.close.reindex(u) - 1).dropna()
        ro = (nxt.open.reindex(u) / cur.close.reindex(u) - 1).dropna()
        sel = [t for t in pr["picks"] if t in rc.index]
        if not sel:
            continue
        new.append(dict(type="outcome", date=d, next_date=days[i + 1], n_sel=len(sel), raw_bp=float(rc[sel].mean() * 1e4), mkt_bp=float(rc.mean() * 1e4),
                        raw_open_bp=float(ro.reindex(sel).mean() * 1e4), mkt_open_bp=float(ro.mean() * 1e4), recorded_at=now_kst()))
    if new:
        REPORT.mkdir(parents=True, exist_ok=True)
        with open(OBS, "a", encoding="utf-8", newline="\n") as f:
            for r in new:
                f.write(json.dumps(r, ensure_ascii=False) + "\n")
    allr = obs + new
    print(f"새 pick {sum(r['type'] == 'pick' for r in new)} · 새 outcome {sum(r['type'] == 'outcome' for r in new)} · 누적 outcome {sum(r['type'] == 'outcome' for r in allr)}")


def verdict(df, final):
    x = (df.raw_bp - df.mkt_bp) / 1e4
    m = x.groupby(df.date.str[:6]).mean()
    t = m.mean() / (m.std(ddof=1) / np.sqrt(len(m))) if len(m) > 1 else float("nan")
    raw = df.raw_bp.mean()
    if not x.mean() > 0:
        v = "REJECT"
    elif t >= 2:
        v = "SUPPORTED" if raw - COST > 0 else "INFORMATION"
    else:
        v = "REJECT" if final else "INCONCLUSIVE"
    return dict(verdict=v, days=int(len(df)), excess_bp=float(x.mean() * 1e4), t=float(t), raw_bp=float(raw), raw_net_bp=float(raw - COST))


def run_judge():
    df = pd.DataFrame([r for r in read_jsonl(OBS) if r["type"] == "outcome"])
    f1, f2 = REPORT / "judge_stage1.json", REPORT / "judge_stage2.json"
    n = len(df)
    if not f1.exists() and n >= STAGES[1]:
        st = 1
    elif f1.exists() and not f2.exists() and json.load(open(f1, encoding="utf-8"))["verdict"] == "INCONCLUSIVE" and n >= STAGES[2]:
        st = 2
    else:
        print(f"판정 시점 아님(또는 끝) — 성숙 {n}일 · 1차 {STAGES[1]} · 연장 {STAGES[2]}")
        return
    res = verdict(df.sort_values("date").head(STAGES[st]), final=(st == 2))
    res.update(stage=st, judged_at=now_kst())
    json.dump(res, open(f1 if st == 1 else f2, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print(json.dumps(res, ensure_ascii=False, indent=1))


def selftest():
    bars = pd.DataFrame({"open": 100.0, "close": [99, 101, 100, 98] * 10, "c1459": 100.0},
                        index=pd.Index([f"{i:05d}0" for i in range(40)], name="ticker"))
    cap0 = pd.Series(3e12, index=bars.index)
    cap0.iloc[0] = 1e12                                   # 시총 미달 1종목
    uni, picks = select(bars, cap0)
    assert len(uni) == 39 and len(picks) == 7             # floor(39 × 0.2)
    assert all(bars.close[t] == 98 for t in picks)       # 가장 약한 쪽부터
    df = pd.DataFrame({"date": [f"2026{m:02d}15" for m in range(1, 13)], "raw_bp": [60.0] * 12, "mkt_bp": [20.0 + (m % 2) for m in range(12)]})
    assert verdict(df, False)["verdict"] == "SUPPORTED"
    df2 = df.assign(raw_bp=20.0)
    assert verdict(df2, False)["verdict"] == "REJECT"
    print("selftest 통과")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    g = ap.add_mutually_exclusive_group()
    for k in ("sync", "judge", "selftest"):
        g.add_argument(f"--{k}", action="store_true")
    a = ap.parse_args()
    (sync if a.sync else run_judge if a.judge else selftest if a.selftest else run_update)()
