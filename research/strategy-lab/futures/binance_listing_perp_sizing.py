#!/usr/bin/env python3
"""바이낸스 신규 상장 7일 숏 무기한 — 크기·손절 설계. 사전등록 findings/binance-listing-perp-sizing-preregistration-2026-11.md (5be42813).

격자 16칸(손절 4 × 첫날 급등 건너뜀 2 × 코인당 명목 2) 을 1시간봉 경로로 시뮬레이션하고, 위험 한도(A 수익·B MDD·C 한 건·D 부트스트랩)로 라벨을 단다. 기록 전용.

    python research/strategy-lab/futures/binance_listing_perp_sizing.py --collect   # 1시간봉(시가·고가) → data/crypto/listing_perp/{sym}_perp1hOHLC.parquet
    python research/strategy-lab/futures/binance_listing_perp_sizing.py             # 판정 → futures/binance-listing-perp-sizing.json, findings/...-results-2026-11.md
    python research/strategy-lab/futures/binance_listing_perp_sizing.py --selftest
"""
from __future__ import annotations

import json
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import binance_listing as bl  # noqa: E402
import binance_listing_perp as bp  # noqa: E402
import coinbase_premium as cp  # noqa: E402
import coinbase_premium_robustness as rb  # noqa: E402

DATA, D, H, END = bp.DATA, bp.D, bp.H, bp.END
HR = pd.Timedelta(hours=1)
HOLD = 24 * H                                           # 168 시간
OUT_JSON = HERE / "binance-listing-perp-sizing.json"
OUT_MD = HERE.parent / "findings" / "binance-listing-perp-sizing-results-2026-11.md"
T0 = pd.Timestamp("2023-01-01", tz="UTC")               # 시뮬레이션 시작(VALID+TEST)
PUMP = 0.50                                             # 첫날 급등(binance_listing_tail 조건 #3)
STOPS = (None, 0.30, 0.50, 1.00)
FRACS = (0.02, 0.05)
CAP = 1.0                                               # 코인 다리 명목 합 상한 = 평가액의 100%
COST, COST_S, SLIP, SLIP_S = 10.0, 30.0, 100.0, 300.0   # bp
MDD_MAX, LOSS_MAX, P_MAX, BOOT_N, SEED = 0.25, 0.03, 0.05, 500, 20261114
MH = 744                                                # 부트스트랩 월 블록 길이(시간, 31일)
LIQ = {"3x격리": 0.328, "2x격리": 0.495, "1x": 0.995}


def klines_1h(sym: str, months: list[str]) -> pd.DataFrame:
    fr = []
    for m in months:
        d = bp._csv(f"{bp.UM}/klines/{sym}/1h/{sym}-1h-{m}.zip")
        if len(d):
            s = pd.DataFrame({"open": d[1].astype(float).to_numpy(), "high": d[2].astype(float).to_numpy()}, index=bp._ms(d[0]))
            fr.append(s[s.index.tz_convert(None).to_period("M") == pd.Period(m, "M")])
    return pd.concat(fr).sort_index() if fr else pd.DataFrame(columns=["open", "high"])


def collect():
    m = json.loads((DATA / "match.json").read_text(encoding="utf-8"))
    ev = bl.events_table(json.loads((bl.DATA / "months.json").read_text(encoding="utf-8")))

    def one(e):
        sym, f = m.get(e["sym"]), DATA / f"{e['sym']}_perp1hOHLC.parquet"
        if sym is None or f.exists():
            return 0
        p = pd.Period(e["first"], "M")
        klines_1h(sym, [str(p + k) for k in range(3)]).to_parquet(f)
        return 1
    with ThreadPoolExecutor(8) as ex:
        n = sum(ex.map(one, ev))
    print("수집", n)


def classify(first_day: pd.Timestamp, t0: pd.Timestamp) -> str:
    return "C" if first_day < t0 else ("D" if first_day == t0 else "X")


def build_event(px: pd.DataFrame, fu: pd.DataFrame, btc: pd.Series, E: pd.Timestamp, stop: float | None, slip_bp: float) -> dict | None:
    """E 에서 진입한 숏(코인)+롱(BTC) 한 건. 반환: X(정리 시각, E+X시간) · m(h=1..X-1 의 단위 명목 평가손익, 불리한 경로) · real(정리 시 단위 손익, 비용 전) · stopped.
    px: 코인 1시간봉(open·high). 필요한 봉이 하나라도 없으면 None."""
    idx = pd.date_range(E, periods=HOLD + 1, freq="h")
    o, hi, b = px["open"].reindex(idx).to_numpy(), px["high"].reindex(idx).to_numpy(), btc.reindex(idx).to_numpy()
    if np.isnan(o).any() or np.isnan(hi[:HOLD]).any() or np.isnan(b).any():
        return None
    p0, b0 = o[0], b[0]
    fd = np.zeros(HOLD + 1)                       # 펀딩: (E, E+h] 정산 합 — 정산이 E+h 이하인 첫 h 에 반영
    if len(fu):
        f = fu[(fu.index > E) & (fu.index <= idx[-1])]
        np.add.at(fd, np.ceil(np.asarray((f.index - E) / HR, dtype=float)).astype(int), f["rate"].to_numpy())
    cum = np.cumsum(fd)
    k, X = None, HOLD
    if stop is not None:
        trig = p0 * (1 + stop)
        hit = np.nonzero(hi[:HOLD] >= trig)[0]
        if len(hit):
            k = int(hit[0])
            X = k + 1
    if k is None:
        fill = o[HOLD]
    else:
        fill = max(o[k], p0 * (1 + stop)) * (1 + slip_bp / 1e4)
    real = -((fill / p0 - 1) - (b[X] / b0 - 1)) + cum[X]
    h = np.arange(1, X)
    m = -((hi[h - 1] / p0 - 1) - (b[h] / b0 - 1)) + cum[h]
    return {"X": X, "m": m, "real": real, "stopped": k is not None, "maxhigh": float(hi[:HOLD].max() / p0 - 1)}


def prep_events() -> list[dict]:
    m = json.loads((DATA / "match.json").read_text(encoding="utf-8"))
    btc = rb._read(DATA / "BTCUSDT_perp1h.parquet")["open"]
    ev = bl.events_table(json.loads((bl.DATA / "months.json").read_text(encoding="utf-8")))
    rows, cov = [], {"전체후보": 0, "무기한없음": 0, "X제외": 0, "봉부족": 0, "청산>END": 0}
    for e in ev:
        spot = rb._read(bl.DATA / f"{e['sym']}.parquet")["open"]
        if not len(spot):
            continue
        L = spot.index[0]
        if L + D + H * D > END:
            cov["청산>END"] += 1
            continue
        cov["전체후보"] += 1
        pf, hf = DATA / f"{e['sym']}_perp.parquet", DATA / f"{e['sym']}_perp1hOHLC.parquet"
        if m.get(e["sym"]) is None or not pf.exists() or not hf.exists():
            cov["무기한없음"] += 1
            continue
        pd_ = rb._read(pf)["open"]
        if not len(pd_):
            cov["무기한없음"] += 1
            continue
        t0 = L + D
        g = classify(pd_.index[0], t0)
        if g == "X":
            cov["X제외"] += 1
            continue
        px = pd.read_parquet(hf)
        px.index = pd.to_datetime(px.index, utc=True)
        if not len(px):
            cov["봉부족"] += 1
            continue
        E = t0 if g == "C" else px.index[0] + HR
        fu = rb._read(DATA / f"{e['sym']}_funding.parquet") if (DATA / f"{e['sym']}_funding.parquet").exists() else pd.DataFrame(columns=["rate", "ivl"])
        day1 = spot.get(t0, np.nan) / spot.iloc[0] - 1
        row = {"sym": e["sym"], "L": L, "E": E, "grp": g, "split": cp.split(L), "pump": bool(np.isfinite(day1) and day1 >= PUMP), "day1": float(day1)}
        bad = False
        for s in STOPS:
            for slip in (SLIP, SLIP_S):
                r = build_event(px, fu, btc, E, s, slip)
                if r is None:
                    bad = True
                    break
                row[(s, slip)] = r
            if bad:
                break
        if bad:
            cov["봉부족"] += 1
            continue
        rows.append(row)
    return rows, cov


def simulate(evs: list[dict], T: int, stop, skip_pump: bool, f: float, cost: float, slip: float) -> dict:
    """evs: 각 건 {Ei(시간 인덱스), pump, (stop,slip)→경로}. 진입 시각 순으로 크기를 정하고 1시간 평가액 경로를 만든다."""
    mtm, delta = np.zeros(T + HOLD + 2), np.zeros(T + HOLD + 2)
    open_, realized_sum, taken, skipped = [], 0.0, [], 0
    for e in sorted(evs, key=lambda x: (x["Ei"], x["sym"])):
        if skip_pump and e["pump"]:
            skipped += 1
            continue
        Ei, r = e["Ei"], e[(stop, slip)]
        for j in [j for j in open_ if j["Ei"] + j["r"]["X"] <= Ei]:     # 이미 정리된 건은 실현 손익으로
            realized_sum += j["N"] * j["net"]
            open_.remove(j)
        eq = 1.0 + realized_sum + sum(j["N"] * (j["r"]["m"][Ei - j["Ei"] - 1] if 1 <= Ei - j["Ei"] <= len(j["r"]["m"]) else 0.0) for j in open_)
        N = f * eq
        if sum(j["N"] for j in open_) + N > CAP:
            skipped += 1
            continue
        net = r["real"] - cost / 1e4
        j = {"Ei": Ei, "r": r, "N": N, "net": net, "eq": eq}
        open_.append(j)
        taken.append(j)
        mtm[Ei + 1: Ei + r["X"]] += N * r["m"]
        delta[Ei + r["X"]] += N * net
    eqpath = 1.0 + mtm + np.cumsum(delta)
    eqpath = eqpath[: T + HOLD + 1]
    peak = np.maximum.accumulate(np.r_[1.0, eqpath])
    mdd = float(((peak[1:] - eqpath) / peak[1:]).max())
    worst = min((f * j["net"] for j in taken), default=0.0)
    return {"final": float(eqpath[-1]), "mdd": mdd, "worst1": float(worst), "n": len(taken), "skipped": skipped, "path": eqpath,
            "stopped": sum(j["r"]["stopped"] for j in taken)}


def attach_idx(rows: list[dict]) -> tuple[list[dict], int]:
    ev = [dict(r, Ei=int((r["E"] - T0) / HR)) for r in rows if r["L"] >= T0]
    return ev, int((END + 8 * D - T0) / HR)


def bootstrap(ev: list[dict], T: int, cell: tuple, rng: np.random.Generator) -> np.ndarray:
    """OOS 상장 월(E 기준 달력월)을 복원 추출해 월 블록을 이어 붙인 뒤 같은 시뮬레이션. 반환 MDD 배열."""
    stop, skip, f = cell
    mon = {}
    for e in ev:
        mon.setdefault(pd.Period(e["E"].tz_convert(None), "M"), []).append(e)
    keys = sorted(mon)
    out = []
    for _ in range(BOOT_N):
        evs = []
        for pos, k in enumerate(rng.integers(0, len(keys), len(keys))):
            src = mon[keys[k]]
            base = min(e["Ei"] for e in src)             # 블록 안 상대 위치 유지
            for e in src:
                evs.append(dict(e, Ei=pos * MH + (e["Ei"] - base)))
        out.append(simulate(evs, len(keys) * MH, stop, skip, f, COST, SLIP)["mdd"])
    return np.array(out)


def cell_name(stop, skip, f) -> str:
    return f"s{'없음' if stop is None else f'+{int(stop * 100)}%'}|급등{'건너뜀' if skip else '진입'}|f{int(f * 100)}%"


def run() -> dict:
    rows, cov = prep_events()
    ev, T = attach_idx(rows)
    train = [r for r in rows if r["L"] < T0]
    # 건 단위 기록
    unit = {}
    for s in STOPS:
        for skip in (False, True):
            xs = [e[(s, SLIP)] for e in ev if not (skip and e["pump"])]
            net = np.array([x["real"] * 1e4 - COST for x in xs])
            unit[(s, skip)] = {"n": len(xs), "meanNet10bp": round(float(net.mean()), 1) if len(net) else None, "stopShare": round(float(np.mean([x["stopped"] for x in xs])), 3) if xs else None,
                               "worstNetBp": round(float(net.min()), 1) if len(net) else None}
    day = pd.DataFrame({"L": [e["L"] for e in ev], "o": [e[(None, SLIP)]["real"] * 1e4 for e in ev]}).groupby("L")["o"].mean()
    repro = {"oosDays": int(len(day)), "net10_dayMean": round(float(day.mean() - COST), 1)}
    cells, rng = {}, np.random.default_rng(SEED)
    for s in STOPS:
        for skip in (False, True):
            for f in FRACS:
                a = simulate(ev, T, s, skip, f, COST, SLIP)
                st = simulate(ev, T, s, skip, f, COST_S, SLIP_S)
                pa = a["path"]
                ix = lambda ts: int((pd.Timestamp(ts, tz="UTC") - T0) / HR)  # noqa: E731
                per = {"2023": pa[ix("2024-01-01")] / 1.0 - 1, "2024": pa[ix("2025-01-01")] / pa[ix("2024-01-01")] - 1, "2025~": pa[-1] / pa[ix("2025-01-01")] - 1}
                A = a["final"] > 1.0 and st["final"] > 1.0
                B, C = a["mdd"] <= MDD_MAX, a["worst1"] >= -LOSS_MAX
                c = {"final": round(a["final"], 3), "mdd": round(a["mdd"], 3), "worst1Pct": round(a["worst1"] * 100, 2), "n": a["n"], "skipped": a["skipped"], "stopped": a["stopped"],
                     "stressFinal": round(st["final"], 3), "stressMdd": round(st["mdd"], 3), "periodRet": {k: round(float(v), 3) for k, v in per.items()}, "A": bool(A), "B": bool(B), "C": bool(C)}
                if A and B and C:
                    mdds = bootstrap(ev, T, (s, skip, f), rng)
                    c["bootP_mdd_gt25"] = round(float((mdds > MDD_MAX).mean()), 3)
                    c["boot_mdd_p95"] = round(float(np.quantile(mdds, 0.95)), 3)
                    c["D"] = c["bootP_mdd_gt25"] <= P_MAX
                else:
                    c["D"] = None
                c["pass"] = bool(A and B and C and c["D"])
                cells[cell_name(s, skip, f)] = c
    passed = {k: v for k, v in cells.items() if v["pass"]}
    anyA = [k for k, v in cells.items() if v["A"]]
    if passed:
        label = "설계 가능"
        rec = min(passed, key=lambda k: (passed[k]["boot_mdd_p95"], -passed[k]["final"]))
    else:
        label = "설계 불가(위험)" if anyA else "경제성 없음"
        rec = None
    liq = {}
    for g, name in (("TRAIN", "TRAIN"), ("OOS", "OOS")):
        sel = train if g == "TRAIN" else ev
        liq[name] = {k: round(float(np.mean([e[(None, SLIP)]["maxhigh"] >= v for e in sel])), 3) if sel else None for k, v in LIQ.items()}
    dgap = {"D건": sum(e["grp"] == "D" for e in ev), "C건": sum(e["grp"] == "C" for e in ev)}
    out = {"label": label, "recommended": rec, "passed": list(passed), "coverage": cov, "oosEvents": len(ev), "trainEvents": len(train), "groups": dgap, "pumpEvents": sum(e["pump"] for e in ev),
           "repro": repro, "unit": {f"{'없음' if s is None else int(s * 100)}|급등건너뜀={skip}": v for (s, skip), v in unit.items()}, "cells": cells, "liquidationNear": liq,
           "trainUnitNoStopMeanNet10": round(float(np.mean([e[(None, SLIP)]["real"] * 1e4 - COST for e in train])), 1) if train else None}
    OUT_JSON.write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
    return out


def write_md(o: dict) -> None:
    c = o["cells"]
    bp_ = lambda x: f"{x:+.1f}"  # noqa: E731
    L = ["---", "track: crypto", "factor: binance-listing-perp-sizing", "date: 2026-11-14", f"verdict: {o['label']}",
         "criteria_version: research-only (binance-listing-perp-sizing-preregistration-2026-11, 사전등록 5be42813)", "reason: >-"]
    nA = sum(v["A"] for v in c.values())
    L.append(f"  신호: 해당 없음 · 경제성: {'통과(수익 칸 존재)' if nA else '미달'}. 격자 16칸 중 A(수익·스트레스) {nA}칸, A~C {sum(1 for v in c.values() if v['A'] and v['B'] and v['C'])}칸, 전부 통과 {len(o['passed'])}칸"
             f"{' — 추천 ' + o['recommended'] if o['recommended'] else ''}. 같은 표본 설계라 forward 확인 전 운용 근거 아님. 기록 전용.")
    L += ["---", "", "# 바이낸스 신규 상장 7일 숏 무기한 — 크기·손절 설계 — 결과", "",
          f"사전등록 5be42813 그대로. OOS(2023~) 건 {o['oosEvents']} (C {o['groups']['C건']} · D {o['groups']['D건']}) · 첫날 급등 {o['pumpEvents']}건 · TRAIN {o['trainEvents']}건(기록). 커버리지 {o['coverage']}.", "",
          f"**라벨: {o['label']}**" + (f" · 추천 칸(위험 최소): {o['recommended']}" if o["recommended"] else ""), "",
          "## 1. 칸별 결과 (주: 10bp·슬립 100bp / 스트레스: 30bp·슬립 300bp)", "",
          "| 칸 | 최종 | MDD | 한 건 최악 | 진입·건너뜀·손절 | 스트레스 최종 | A | B | C | D(부트 P>25%) | 통과 |", "|---|---|---|---|---|---|---|---|---|---|---|"]
    for k, v in c.items():
        d = "-" if v["D"] is None else f"{'O' if v['D'] else 'X'} ({v['bootP_mdd_gt25']:.1%})"
        L.append(f"| {k} | {v['final']:.3f} | {v['mdd']:.1%} | {v['worst1Pct']:.2f}% | {v['n']}·{v['skipped']}·{v['stopped']} | {v['stressFinal']:.3f} | {'O' if v['A'] else 'X'} | {'O' if v['B'] else 'X'} | {'O' if v['C'] else 'X'} | {d} | {'**통과**' if v['pass'] else ''} |")
    L += ["", "## 2. 시기 세 칸 (기록) — 칸별 구간 수익률", "", "| 칸 | 2023 | 2024 | 2025~ |", "|---|---|---|---|"]
    for k, v in c.items():
        p = v["periodRet"]
        L.append(f"| {k} | {p['2023']:+.1%} | {p['2024']:+.1%} | {p['2025~']:+.1%} |")
    L += ["", "## 3. 건 단위 (명목 1, 비용 10bp 뒤, 손절 슬립 100bp)", "", "| 손절·급등 | 건 | 평균 순bp | 손절 발동 | 최악 순bp |", "|---|---|---|---|---|"]
    for k, v in o["unit"].items():
        L.append(f"| {k} | {v['n']} | {bp_(v['meanNet10bp'])} | {v['stopShare']:.1%} | {bp_(v['worstNetBp'])} |")
    L += ["", f"재현 점검: 손절 없음 OOS 상장일 평균(10bp 뒤) = {bp_(o['repro']['net10_dayMean'])}bp ({o['repro']['oosDays']}일) — 교정 판정 +1,018.9bp 와 대조. TRAIN 건 평균 {o['trainUnitNoStopMeanNet10']}bp(기록).",
          f"청산 근접(기록, 코인 1시간 고가가 진입가 대비 +32.8%/+49.5%/+99.5% 에 닿은 비율): OOS {o['liquidationNear']['OOS']} · TRAIN {o['liquidationNear']['TRAIN']}", "",
          "## 4. 읽는 법·한계", "",
          "- 슬리피지(100/300bp)·비용은 가정값이다(호가·체결 자료 없음). 1시간봉 고가는 장중 순서를 모르므로 손절 발동은 트리거 도달로만 판정했다.",
          "- 교차 마진·개별 청산 미모사. 평가액 경로는 불리하게(코인 고가) 잡은 값이라 MDD 가 실제보다 클 수 있다.",
          "- 같은 표본에서 칸을 고른 것이므로 통과·추천은 가설이다. 확인은 2026-10 이후 상장 forward(별도 사전등록 + 사용자 GO). 같은 표본 재절단·격자 변경 금지. 실계좌·모의 슬리브·정책 불변."]
    OUT_MD.write_text("\n".join(L) + "\n", encoding="utf-8")


def selftest():
    t0 = pd.Timestamp("2024-03-02", tz="UTC")
    idx = pd.date_range(t0, periods=HOLD + 1, freq="h")
    px = pd.DataFrame({"open": 100.0, "high": 100.0}, index=idx)
    px.loc[idx[5], "high"] = 135.0                                  # 5번째 봉에서 +35% 고가
    px.loc[idx[HOLD], "open"] = 80.0
    btc = pd.Series(50.0, index=idx)
    fu = pd.DataFrame({"rate": [-0.001, -0.001], "ivl": [8.0, 8.0]}, index=[t0 + 8 * HR, t0 + 200 * HR])
    r = build_event(px, fu, btc, t0, None, SLIP)                    # 손절 없음: 7일 −20%, 펀딩 창 안 1건
    assert r["X"] == HOLD and abs(r["real"] - (0.2 - 0.001)) < 1e-9 and not r["stopped"], r
    r = build_event(px, fu, btc, t0, 0.30, SLIP)                    # +30% 손절: 봉 5 에서 발동, 정리 6시간째, 체결 130×1.01
    assert r["stopped"] and r["X"] == 6 and abs(r["real"] - (-(1.3 * 1.01 - 1) + 0.0)) < 1e-9 and len(r["m"]) == 5, r
    px.loc[idx[5], "open"] = 140.0                                  # 갭: 봉 시가가 트리거 위
    r = build_event(px, fu, btc, t0, 0.30, SLIP)
    assert abs(r["real"] - (-(1.4 * 1.01 - 1))) < 1e-9, r
    assert build_event(px.drop(idx[10]), fu, btc, t0, None, SLIP) is None
    # 시뮬레이션: 한 건, 평가액 1 + N*net
    e = {"sym": "A", "Ei": 0, "pump": False, (None, SLIP): {"X": 3, "m": np.array([-0.1, -0.2]), "real": -0.5, "stopped": False}}
    s = simulate([e], 10, None, False, 0.05, 0.0, SLIP)
    assert abs(s["final"] - (1 - 0.05 * 0.5)) < 1e-12 and abs(s["mdd"] - 0.05 * 0.5) < 1e-12 and abs(s["worst1"] + 0.025) < 1e-12, s
    print("selftest OK")


if __name__ == "__main__":
    if "--selftest" in sys.argv:
        selftest()
    elif "--collect" in sys.argv:
        collect()
    else:
        o = run()
        write_md(o)
        print(o["label"], o["recommended"], o["passed"], o["repro"])
