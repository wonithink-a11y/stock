#!/usr/bin/env python3
"""급락 뒤 횡보 국면 M forward 기록기. 사전등록: findings/sideways-regime-forward-preregistration-2026-10.md (커밋 a50a9cfd).
국면·순위·매매 규칙은 sideways_regime_sector.py(adfb0ce1) 그대로이며 결과를 보고 바꾸지 않는다.

    python research/strategy-lab/run_sideways_regime_forward.py --collect   # KRX 로그인 경로로 업종지수 19개 + KOSPI 증분
    python research/strategy-lab/run_sideways_regime_forward.py             # signal·outcome 추가 기록(건수만 출력)
    python research/strategy-lab/run_sideways_regime_forward.py --report    # 기록 전용: 국면 아닌 달 M 값
    python research/strategy-lab/run_sideways_regime_forward.py --judge     # 국면 달 24·48개 전에는 거부
    python research/strategy-lab/run_sideways_regime_forward.py --selftest
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import kospi_sector_momentum as ksm  # noqa: E402
import sideways_regime_sector as srs  # noqa: E402

FREEZE = pd.Timestamp("2026-10-13")
STAGES = {1: 24, 2: 48}
REPORT = HERE / "reports" / "2026-10-sideways-regime-forward"
OBS = REPORT / "observations.jsonl"


def now_kst():
    return datetime.now(timezone(timedelta(hours=9))).strftime("%Y-%m-%d %H:%M:%S")


def read_jsonl(p):
    return [json.loads(l) for l in open(p, encoding="utf-8") if l.strip()] if p.exists() else []


def collect():
    import collect_krx_pbr_monthly as c
    c.load_login()
    from pykrx import stock
    end = datetime.now(timezone(timedelta(hours=9))).strftime("%Y%m%d")
    for tk in list(ksm.SECT) + ["1001"]:
        p = ksm.D / f"{tk}.parquet"
        old = pd.read_parquet(p)
        start = (old.index.max() - pd.Timedelta(days=15)).strftime("%Y%m%d")
        new = pd.DataFrame({"close": stock.get_index_ohlcv(start, end, tk)["종가"].astype(float)})
        if tk != "1001":
            new = new.join(stock.get_index_fundamental(start, end, tk)[["배당수익률"]].rename(columns={"배당수익률": "dy"}), how="left")
        new.index.name = "date"
        df = pd.concat([old[old.index < new.index.min()], new])
        df.to_parquet(p)
        print(tk, df.index.max().date(), len(new))


def load():
    C, Y = ksm.load()
    P = pd.read_parquet(ksm.D / "1001.parquet")["close"].astype(float)
    return C, Y, srs.regime(P)


def signals(C, R):
    """신호일 ≥ FREEZE 이고 다음 거래일이 있는 월말마다 (날짜, A, B, 선택, 40일 수익)."""
    cal = C.index
    out = []
    for s in ksm.month_ends(cal):
        i = cal.get_loc(s)
        if s < FREEZE or i + 1 >= len(cal) or i < srs.VOL_WIN:
            continue
        rg = R.loc[:s]
        a, b = bool(rg["A"].iloc[-1]), bool(rg["B"].iloc[-1])
        rs = (C.iloc[i] / C.iloc[i - srs.RANGE_WIN] - 1).dropna()
        ok = [t for t in rs.index if np.isfinite(C.iloc[i + 1][t])]
        picks = sorted(ok, key=lambda t: (-rs[t], t))[:srs.K]
        out.append(dict(signal=str(s.date()), A=a, B=b, on=a and b, picks=picks, rs40={t: round(float(rs[t]), 5) for t in picks}))
    return out


def run_update():
    C, Y, R = load()
    obs = read_jsonl(OBS)
    seen = {(r["type"], r["signal"]) for r in obs}
    sig = {r["signal"]: r for r in obs if r["type"] == "signal"}
    new = []
    for r in signals(C, R):
        if ("signal", r["signal"]) not in seen:
            r.update(type="signal", data_end=str(C.index.max().date()), recorded_at=now_kst())
            new.append(r)
            sig[r["signal"]] = r
    for r in srs.build(C, Y, R, "M"):
        d = str(r["signal"].date())
        if r["signal"] < FREEZE or ("outcome", d) in seen:
            continue
        new.append(dict(type="outcome", signal=d, picks=r["picks"], ret=r["ret"], top=r["top"], ew=r["ew"], turnover=r["turnover"],
                        X=r["X"], repick_differs=set(r["picks"]) != set(sig.get(d, {}).get("picks", [])),
                        data_end=str(C.index.max().date()), recorded_at=now_kst()))
    if new:
        REPORT.mkdir(parents=True, exist_ok=True)
        with open(OBS, "a", encoding="utf-8", newline="\n") as f:
            for r in new:
                f.write(json.dumps(r, ensure_ascii=False) + "\n")
    allr = obs + new
    print(f"데이터 끝 {C.index.max().date()} · 새 signal {sum(r['type'] == 'signal' for r in new)} · 새 outcome {sum(r['type'] == 'outcome' for r in new)} · "
          f"누적 국면 달 {sum(r['type'] == 'signal' and r['on'] for r in allr)} · 누적 outcome {sum(r['type'] == 'outcome' for r in allr)}")


def run_report():
    C, Y, R = load()
    rows = [r for r in srs.build(C, Y, R, "M", mode="notAB") if r["signal"] >= FREEZE]
    print(f"국면 아닌 달(기록 전용) {len(rows)}개" + (f" · 평균 X {np.mean([r['X'] for r in rows]) * 1e4:+.0f}bp" if rows else ""))


def stage_of(n, done1, done2, v1):
    if not done1:
        return 1 if n >= STAGES[1] else None
    if v1 == "CONTINUE" and not done2:
        return 2 if n >= STAGES[2] else None
    return None


def verdict(mx, p, final):
    if mx > 0 and p < 0.05:
        return "SUPPORTED"
    if final or mx <= 0:
        return "REJECT"
    return "CONTINUE"


def run_judge():
    outs = [r for r in read_jsonl(OBS) if r["type"] == "outcome"]
    f1, f2 = REPORT / "judge_stage1.json", REPORT / "judge_stage2.json"
    v1 = json.load(open(f1, encoding="utf-8"))["verdict"] if f1.exists() else None
    st = stage_of(len(outs), f1.exists(), f2.exists(), v1)
    if st is None:
        print(f"판정 시점 아님(또는 판정 끝) — 국면 달 outcome {len(outs)}개 · 1차 {STAGES[1]} · 최종 {STAGES[2]}")
        return
    rows = outs[:STAGES[st]]
    mx, p, nm = ksm.null_p(rows, n=srs.N_NULL, seed=srs.SEED)
    res = dict(stage=st, months=len(rows), mean_X=mx, p=p, null_mean=nm, verdict=verdict(mx, p, st == 2), judged_at=now_kst())
    json.dump(res, open(f1 if st == 1 else f2, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print(json.dumps(res, ensure_ascii=False, indent=1))


def selftest():
    assert stage_of(23, False, False, None) is None and stage_of(24, False, False, None) == 1
    assert stage_of(40, True, False, "CONTINUE") is None and stage_of(48, True, False, "CONTINUE") == 2
    assert stage_of(60, True, False, "REJECT") is None and stage_of(60, True, True, "CONTINUE") is None
    assert verdict(0.004, 0.01, False) == "SUPPORTED" and verdict(-0.001, 0.9, False) == "REJECT"
    assert verdict(0.004, 0.2, False) == "CONTINUE" and verdict(0.004, 0.2, True) == "REJECT"
    # 신호: FREEZE 이전·다음 거래일 없는 월말은 빠진다
    cal = pd.bdate_range("2026-06-01", "2026-12-02")
    C = pd.DataFrame({tk: 100 * (1 + 0.0001 * j) ** np.arange(len(cal)) for j, tk in enumerate(ksm.SECT)}, index=cal)
    R = pd.DataFrame({"A": True, "B": True}, index=cal)
    s = signals(C, R)
    assert [x["signal"] for x in s] == ["2026-10-30", "2026-11-30"] and all(set(x["picks"]) == set(list(ksm.SECT)[-3:]) for x in s)
    print("selftest 통과")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    g = ap.add_mutually_exclusive_group()
    for k in ("collect", "report", "judge", "selftest"):
        g.add_argument(f"--{k}", action="store_true")
    a = ap.parse_args()
    {"collect": collect, "report": run_report, "judge": run_judge, "selftest": selftest}.get(
        next((k for k in ("collect", "report", "judge", "selftest") if getattr(a, k)), ""), run_update)()
