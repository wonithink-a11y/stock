#!/usr/bin/env python3
"""기타법인 순매수 강도(ETC10) forward 기록. 사전등록 findings/etc-flow-forward-preregistration-2026-10.md.

    python research/strategy-lab/run_etc_flow_forward.py            # 월간 점검(A2a·A4 증분 뒤, 약 5분) → reports/ 커밋
    python research/strategy-lab/run_etc_flow_forward.py --judge    # 성숙 신호월 24 ∧ 24개월 전에는 건수만
    python research/strategy-lab/run_etc_flow_forward.py --selftest

신호·대조·청산은 investor_type_flow(51c8f938)의 prepare / events 를 그대로 쓴다(셀 ETC10 만). 기록 전용 — 점수·매매·알림 없음.
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(HERE))

OUT = ROOT / "reports" / "2026-10-etc-flow-forward"
START = pd.Timestamp("2026-10-01")
CELL, COST = "ETC10", 33.5
GATE, MONTHS, EXT, EXT_MONTHS, T_KEEP, MIN_A4 = 24, 24, 48, 48, 1.65, 500


def _read(name):
    p = OUT / name
    return [json.loads(l) for l in p.read_text(encoding="utf-8").splitlines() if l.strip()] if p.exists() else []


def _append(name, rows):
    if rows:
        OUT.mkdir(parents=True, exist_ok=True)
        with open(OUT / name, "a", encoding="utf-8") as f:
            for r in rows:
                f.write(json.dumps(r, ensure_ascii=False) + "\n")


def compute():
    import investor_type_flow as itf
    import surge_day_continuation as s
    dates, tick, raw = s.load_raw()
    O, C, V = (np.where(raw[k] > 0, raw[k], np.nan) for k in ("open", "close", "volume"))
    net, tot = itf.load_a4(dates, tick)
    B, I = itf.base(O, C, V), itf.intensity(net, tot)
    # 반도체 제외 표시 = investor_type_flow.load_all 과 같은 정의
    themes = json.load(open(ROOT / "config/themeTree.json", encoding="utf-8"))["themes"]
    sset = {x["t"] for g in themes["AI·반도체"].values() for x in g}
    for line in open(ROOT / "data/backfill/universe/a1a/current.jsonl", encoding="utf-8"):
        r = json.loads(line)
        if r.get("sector") == "반도체 제조업":
            sset.add(r["ticker"])
    semi_mask = np.array([t in sset for t in tick])
    rows, wait = [], []
    import short_balance_dtc as sb
    for i in sb.month_end_rows(dates):
        d = dates[i]
        if d < START:
            continue
        a4n = int((~np.isnan(tot[i])).sum())
        if i + itf.H >= len(dates) or a4n < MIN_A4:
            wait.append({"date": str(d.date()), "mature": bool(i + itf.H < len(dates)), "a4Tickers": a4n})
            continue
        rows.append(i)
    df, _ = itf.events(B, I, rows, dates, semi_mask)
    df = df[df.cell == CELL] if len(df) else df
    months, evs = [], []
    for i in rows:
        d = dates[i]
        sub = df[df.date == d] if len(df) else df
        months.append({"date": str(d.date()), "n": int(len(sub)), "info": round(float(sub["info"].mean()), 4) if len(sub) else None,
                       "g": round(float(sub.g.mean()), 4) if len(sub) else None,
                       "info_ex_semis": round(float(sub[~sub.semi]["info"].mean()), 4) if len(sub) and (~sub.semi).any() else None})
        for _, r in sub.iterrows():
            evs.append({"date": str(d.date()), "ticker": tick[int(r.j)], "info": round(float(r["info"]), 4), "g": round(float(r.g), 4)})
    return months, evs, wait


def merge(obs, fresh):
    seen = {o["date"]: o for o in obs}
    new, drift = [], []
    for r in fresh:
        o = seen.get(r["date"])
        if o is None:
            new.append(r)
        elif o["n"] != r["n"] or (o["info"] is not None and r["info"] is not None and abs(o["info"] - r["info"]) > 1e-3):
            drift.append({"date": r["date"], "first": o, "now": r})
    return new, drift


def judge(obs, today):
    good = [o for o in obs if o["info"] is not None]
    if not good:
        return {"n": 0, "judge": "거부 — 관측 없음"}
    first = pd.Timestamp(min(o["date"] for o in good))
    age_m = (today.year - first.year) * 12 + today.month - first.month
    n = len(good)
    stage = "EXT" if n >= EXT and age_m >= EXT_MONTHS else "MAIN" if n >= GATE and age_m >= MONTHS else None
    if stage is None:
        return {"n": n, "ageMonths": age_m, "judge": f"거부 — {n}/{GATE} 신호월 · {age_m}/{MONTHS}개월(사전등록 §2)"}
    x = np.array([o["info"] for o in good])
    m = float(x.mean())
    t = float(m / (x.std(ddof=1) / np.sqrt(n))) if n > 2 and x.std(ddof=1) > 0 else 0.0
    v = "CONFIRMED" if m > 0 and t >= T_KEEP else "REJECT" if m <= 0 else "INCONCLUSIVE"
    if v == "INCONCLUSIVE" and stage == "EXT":
        v = "INCONCLUSIVE(종결)"
    g = np.array([o["g"] for o in good])
    return {"n": n, "stage": stage, "info_bp": round(m, 1), "t": round(t, 2), "net_bp": round(float(g.mean() - COST), 1), "verdict": v}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--judge", action="store_true")
    ap.add_argument("--selftest", action="store_true")
    a = ap.parse_args()
    if a.selftest:
        return selftest()
    obs = _read("observations.jsonl")
    today = pd.Timestamp.now(tz="Asia/Seoul").tz_localize(None).normalize()
    if a.judge:
        print(json.dumps(judge(obs, today), ensure_ascii=False, indent=1))
        return 0
    months, evs, wait = compute()
    new, drift = merge(obs, months)
    newd = {r["date"] for r in new}
    _append("observations.jsonl", new)
    _append("events.jsonl", [e for e in evs if e["date"] in newd])
    _append("drift.jsonl", drift)
    summ = {"runAt": time.strftime("%Y-%m-%dT%H:%M:%S%z"), "months": len(obs) + len(new), "newMonths": len(new), "drift": len(drift),
            "waiting": wait, "judge": judge(obs + new, today).get("judge")}
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "_summary.json").write_text(json.dumps(summ, ensure_ascii=False, indent=1), encoding="utf-8")
    print(json.dumps(summ, ensure_ascii=False))
    return 0


def selftest():
    ok = 0
    o = [{"date": "2026-10-30", "n": 70, "info": 50.0, "g": 80.0}]
    new, drift = merge(o, [{"date": "2026-10-30", "n": 70, "info": 50.0, "g": 80.0}, {"date": "2026-11-30", "n": 71, "info": -10.0, "g": 5.0}])
    assert [r["date"] for r in new] == ["2026-11-30"] and not drift; ok += 1
    _, drift = merge(o, [{"date": "2026-10-30", "n": 69, "info": 50.0, "g": 80.0}])
    assert len(drift) == 1; ok += 1
    assert "거부" in judge(o, pd.Timestamp("2027-06-01"))["judge"]; ok += 1
    rng = np.random.default_rng(1)
    fake = [{"date": str(d.date()), "n": 70, "info": float(v), "g": float(v) + 30}
            for d, v in zip(pd.date_range("2026-10-31", periods=24, freq="ME"), rng.normal(120, 150, 24))]
    assert judge(fake, pd.Timestamp("2028-11-01"))["verdict"] == "CONFIRMED"; ok += 1
    neg = [dict(f, info=-abs(f["info"])) for f in fake]
    assert judge(neg, pd.Timestamp("2028-11-01"))["verdict"] == "REJECT"; ok += 1
    print(f"selftest OK ({ok})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
