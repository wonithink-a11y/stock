#!/usr/bin/env python3
"""급락 후 반등(crash)·연속 하락 셀 C(streak) forward 기록.
사전등록 findings/crash-rebound-forward-preregistration-2026-11.md · findings/streak-drop-c-forward-preregistration-2026-11.md

    python research/strategy-lab/run_drop_events_forward.py            # 월간 점검(자주 돌려도 됨, 수십 초) → reports/ 커밋
    python research/strategy-lab/run_drop_events_forward.py --judge    # 판정 시점 전에는 건수만
    python research/strategy-lab/run_drop_events_forward.py --selftest

기록 전용 — 매매·알림 없음. 사건·결과 행은 처음 본 값을 한 번만 쓰고 고쳐 쓰지 않는다.
"""
from __future__ import annotations

import argparse
import json
import math
import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
OUT = ROOT / "reports" / "2026-11-drop-events-forward"
START = pd.Timestamp("2026-11-18")
BASE_END = pd.Timestamp("2026-11-06")          # 무조건 평균 기준 구간 끝(동결)
ALPHA, K_MIN, WAVE_DAYS = 0.05 / 4, 7, 30
CRASH_MK = {k: k for k in ["^KS11", "^KQ11", "^SOX", "^NDX", "^N225", "^HSI", "^GDAXI", "^GSPC"]}
STREAK_MK = {"SPY": "SPY", "QQQ": "QQQ", "반도체SOX": "^SOX", "닛케이": "^N225", "DAX": "^GDAXI", "항셍": "^HSI", "코스피": "^KS11",
             "코스닥": "^KQ11", "대만가권": "^TWII", "상해종합": "000001.SS", "FTSE": "^FTSE", "CAC40": "^FCHI"}
ARMS = {"crash": dict(mk=CRASH_MK, hs=(21, 63), jh=63, m1=24, m2=60),
        "streak": dict(mk=STREAK_MK, hs=(1, 5, 21, 63), jh=21, m1=12, m2=36)}


def fetch(tk: str) -> pd.Series:
    import yfinance as yf
    for n in range(4):
        try:
            x = yf.download(tk, start="1990-01-01", auto_adjust=True, progress=False)
            x.columns = x.columns.get_level_values(0)
            s = x["Close"].dropna()
            assert len(s) > 1000, f"{tk} 행 {len(s)}"                         # 빈 응답을 성공으로 세지 않는다(교훈 81)
            today = pd.Timestamp.now(tz="Asia/Seoul").tz_localize(None).normalize()
            return s[s.index < today]                                          # 당일 봉은 미완성일 수 있다
        except Exception:
            if n == 3:
                raise
            time.sleep(2 ** (n + 1))


def detect_crash(p: np.ndarray):
    """20일 −20% ∧ 252일 최고 종가 대비 −30%, 직전 조건 충족일에서 40거래일 넘게 지난 첫 날."""
    n = len(p)
    r20 = np.full(n, np.nan)
    r20[20:] = p[20:] / p[:-20] - 1
    hi = pd.Series(p).rolling(252, min_periods=1).max().to_numpy()
    cond = (r20 <= -0.20) & (p / hi - 1 <= -0.30)
    ev, last = [], -999
    for i in range(n):
        if cond[i] and i - last > 40:
            ev.append(i)
        if cond[i]:
            last = i
    return ev, cond


def detect_streak(p: np.ndarray, lmin=5, dmin=0.10, gap=10):
    """연속 lmin 일 하락 ∧ 누적 −dmin 이하를 처음 만족하는 날(streak_drop_events.py 와 같은 루프)."""
    n = len(p)
    L = np.zeros(n, dtype=int)
    for i in range(1, n):
        L[i] = L[i - 1] + 1 if p[i] < p[i - 1] else 0
    ev, last, hit = [], -999, False
    for i in range(1, n):
        if L[i] == 0:
            hit = False
        if L[i] >= lmin and not hit and p[i] / p[i - L[i]] - 1 <= -dmin and i - last > gap:
            ev.append(i)
            last, hit = i, True
    return ev


def baseline(p: np.ndarray, idx: pd.DatetimeIndex, hs) -> dict:
    nb = int(idx.searchsorted(BASE_END, side="right"))
    return {str(h): round(float(np.mean(p[h:nb] / p[:nb - h] - 1) * 100), 4) for h in hs if nb - h > 0}


def waves(rows) -> list[float]:
    """[(date, excess)] → 첫 사건일부터 WAVE_DAYS 안에 드는 사건을 한 wave 로 묶은 wave 평균."""
    out, start, cur = [], None, []
    for d, x in sorted(rows):
        if start is None or (d - start).days > WAVE_DAYS:
            if cur:
                out.append(float(np.mean(cur)))
            start, cur = d, []
        cur.append(x)
    if cur:
        out.append(float(np.mean(cur)))
    return out


def upper_tail(k: int, m: int) -> float:
    return sum(math.comb(k, j) for j in range(m, k + 1)) / 2 ** k


def verdict(w: list[float]) -> str:
    k = len(w)
    mean = float(np.mean(w))
    if mean > 0 and upper_tail(k, sum(x > 0 for x in w)) <= ALPHA:
        return "CONFIRMED_UP"
    if mean < 0 and upper_tail(k, sum(x < 0 for x in w)) <= ALPHA:
        return "CONFIRMED_DOWN"
    return "INCONCLUSIVE"


def judge(arm: str, events: list[dict], outs: list[dict], base: dict, today: pd.Timestamp) -> dict:
    cfg = ARMS[arm]
    jh = cfg["jh"]
    ev = [e for e in events if e["arm"] == arm and e["kind"] == "event"]
    got = {(o["mk"], o["date"]): o["ret"] for o in outs if o["arm"] == arm and o["h"] == jh}
    rows = [(pd.Timestamp(e["date"]), got[(e["mk"], e["date"])] - base[arm][e["mk"]][str(jh)])
            for e in ev if (e["mk"], e["date"]) in got and e["mk"] in base.get(arm, {})]
    w = waves(rows)
    k, age = len(w), (today - START).days
    info = {"events": len(ev), "matured": len(rows), "waves": k, "ageDays": age}
    final = age >= cfg["m2"] * 30
    main = age >= cfg["m1"] * 30 and k >= K_MIN
    if not (final or main):
        return {**info, "judge": f"거부 — wave {k}/{K_MIN} · {age}/{cfg['m1'] * 30}일(사전등록 §판정)"}
    if k < K_MIN:
        return {**info, "verdict": "INCONCLUSIVE(종결, 표본 부족)"}
    v = verdict(w)
    if v == "INCONCLUSIVE" and not final:
        v = "INCONCLUSIVE(연장 — 최종 시점 재판정)"
    return {**info, "waveMean": round(float(np.mean(w)), 3), "wavePos": sum(x > 0 for x in w), "verdict": v}


def _read(name):
    p = OUT / name
    return [json.loads(l) for l in p.read_text(encoding="utf-8").splitlines() if l.strip()] if p.exists() else []


def _append(name, rows):
    if rows:
        OUT.mkdir(parents=True, exist_ok=True)
        with open(OUT / name, "a", encoding="utf-8") as f:
            for r in rows:
                f.write(json.dumps(r, ensure_ascii=False) + "\n")


def run() -> int:
    today = pd.Timestamp.now(tz="Asia/Seoul").tz_localize(None).normalize()
    OUT.mkdir(parents=True, exist_ok=True)
    bf = OUT / "baseline.json"
    base = json.loads(bf.read_text(encoding="utf-8")) if bf.exists() else {}
    events, outs = _read("events.jsonl"), _read("outcomes.jsonl")
    seen_e = {(e["arm"], e["mk"], e["date"]) for e in events}
    seen_o = {(o["arm"], o["mk"], o["date"], o["h"]) for o in outs}
    cohort_file = OUT / "cohort.json"
    cohort = None if cohort_file.exists() else {}
    new_e, new_o = [], []
    for arm, cfg in ARMS.items():
        for name, tk in cfg["mk"].items():
            s = fetch(tk)
            p, idx = s.to_numpy(float), s.index
            ev, cond = detect_crash(p) if arm == "crash" else (detect_streak(p), None)
            base.setdefault(arm, {}).setdefault(name, baseline(p, idx, cfg["hs"]))      # 한 번만, 고쳐 쓰지 않는다
            for i in ev:
                d = str(idx[i].date())
                if idx[i] >= START and (arm, name, d) not in seen_e:
                    new_e.append(dict(arm=arm, mk=name, date=d, close=round(float(p[i]), 4), kind="event"))
                    seen_e.add((arm, name, d))
            if arm == "crash" and cohort is not None and cond[-1] and idx[-1] < START:        # 상태 코호트(기록 전용)
                d = str(idx[-1].date())
                cohort[name] = d
                new_e.append(dict(arm=arm, mk=name, date=d, close=round(float(p[-1]), 4), kind="state"))
            for e in [x for x in events + new_e if x["arm"] == arm and x["mk"] == name]:
                i = int(idx.get_loc(pd.Timestamp(e["date"])))
                for h in cfg["hs"]:
                    key = (arm, name, e["date"], h)
                    if i + h < len(p) and key not in seen_o:
                        new_o.append(dict(arm=arm, mk=name, date=e["date"], h=h, kind=e["kind"],
                                          ret=round(float((p[i + h] / p[i] - 1) * 100), 4),
                                          mn=round(float((p[i + 1:i + h + 1].min() / p[i] - 1) * 100), 4)))
                        seen_o.add(key)
    bf.write_text(json.dumps(base, ensure_ascii=False, indent=1), encoding="utf-8")
    if cohort is not None:
        note = {"members": cohort} if today < START else {"skipped": "첫 실행이 2026-11-18 이후라 코호트를 만들지 않음"}
        cohort_file.write_text(json.dumps({"asOf": str(today.date()), **note}, ensure_ascii=False, indent=1), encoding="utf-8")
    _append("events.jsonl", new_e)
    _append("outcomes.jsonl", new_o)
    allev, allout = events + new_e, outs + new_o
    summ = {"runAt": time.strftime("%Y-%m-%dT%H:%M:%S%z"), "newEvents": len(new_e), "newOutcomes": len(new_o),
            **{arm: judge(arm, allev, allout, base, today) for arm in ARMS}}
    (OUT / "_summary.json").write_text(json.dumps(summ, ensure_ascii=False, indent=1), encoding="utf-8")
    print(json.dumps(summ, ensure_ascii=False))
    return 0


def selftest() -> int:
    ok = 0
    p = np.r_[np.full(30, 100.0), 100 * 0.975 ** np.arange(1, 8)]                  # 7일 연속 −2.5%
    assert detect_streak(p) == [34], detect_streak(p); ok += 1                      # 5번째 하락일 −11.9% 에서 첫 충족
    assert detect_streak(np.r_[p, p[-1] * 0.975 ** 3 * np.ones(1)]) == [34]; ok += 1  # 같은 연속 안에서 반복 없음
    q = np.r_[np.full(300, 100.0), np.linspace(100, 65, 20), np.full(60, 65.0)]     # 20일 −35%
    ev, cond = detect_crash(q)
    assert len(ev) == 1 and 300 <= ev[0] < 320 and cond[-1] == False, (ev, cond[-1]); ok += 1  # 낙폭이 252일 창에서 안 빠짐
    d = pd.Timestamp("2027-01-01")
    w = waves([(d, 1.0), (d + pd.Timedelta(days=20), 3.0), (d + pd.Timedelta(days=60), -2.0)])
    assert w == [2.0, -2.0], w; ok += 1                                             # 30일 안은 한 wave
    assert abs(upper_tail(7, 7) - 1 / 128) < 1e-12 and upper_tail(7, 6) > ALPHA; ok += 1  # 7/7 만 통과
    assert verdict([1.0] * 7) == "CONFIRMED_UP" and verdict([-1.0] * 7) == "CONFIRMED_DOWN"; ok += 1
    assert verdict([1, 1, 1, 1, 1, 1, -1.0]) == "INCONCLUSIVE"; ok += 1
    ev1 = [dict(arm="streak", mk="SPY", date="2026-12-01", kind="event")]
    j = judge("streak", ev1, [], {"streak": {"SPY": {"21": 1.0}}}, pd.Timestamp("2027-06-01"))
    assert "거부" in j["judge"]; ok += 1                                            # 시점·표본 전에는 건수만
    assert judge("streak", ev1, [], {}, pd.Timestamp("2030-01-01"))["verdict"].startswith("INCONCLUSIVE(종결"); ok += 1
    print(f"selftest OK ({ok})")
    return 0


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--judge", action="store_true")
    ap.add_argument("--selftest", action="store_true")
    a = ap.parse_args()
    if a.selftest:
        return selftest()
    if a.judge:
        today = pd.Timestamp.now(tz="Asia/Seoul").tz_localize(None).normalize()
        bf = OUT / "baseline.json"
        base = json.loads(bf.read_text(encoding="utf-8")) if bf.exists() else {}
        print(json.dumps({arm: judge(arm, _read("events.jsonl"), _read("outcomes.jsonl"), base, today) for arm in ARMS},
                         ensure_ascii=False, indent=1))
        return 0
    return run()


if __name__ == "__main__":
    sys.exit(main())
