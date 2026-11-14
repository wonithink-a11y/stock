#!/usr/bin/env python3
"""바이낸스 신규 상장 7일 숏 무기한 — 크기·손절 1분봉 해상도 재측정. 사전등록 findings/binance-listing-perp-sizing-1m-preregistration-2026-11.md (fa652a7d).

격자·표본·진입·판정 문턱은 binance_listing_perp_sizing(9998570e)을 그대로 쓰고, 경로 해상도만 1분봉으로 바꾼다(sz.prep_events 만 교체). 기록 전용.

    python research/strategy-lab/futures/binance_listing_perp_1m.py --collect   # 1분봉 → data/crypto/listing_perp/{sym}_perp1m.parquet, BTCUSDT_perp1m.parquet
    python research/strategy-lab/futures/binance_listing_perp_1m.py             # 판정 → futures/binance-listing-perp-sizing-1m.json, findings/...-1m-results-2026-11.md
    python research/strategy-lab/futures/binance_listing_perp_1m.py --selftest
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
import binance_listing_perp_sizing as sz  # noqa: E402
import coinbase_premium as cp  # noqa: E402
import coinbase_premium_robustness as rb  # noqa: E402

DATA, D, H, END, HOLD, HR = sz.DATA, sz.D, sz.H, sz.END, sz.HOLD, sz.HR
MIN = pd.Timedelta(minutes=1)
NM = HOLD * 60                                                  # 10,080 분
OUT_JSON = HERE / "binance-listing-perp-sizing-1m.json"
OUT_MD = HERE.parent / "findings" / "binance-listing-perp-sizing-1m-results-2026-11.md"
PREV_JSON = HERE / "binance-listing-perp-sizing.json"           # 1시간봉 결과(5be42813 / 9998570e)
WORST_1H_30 = -4803.8                                           # 사전등록 §3: 1시간봉 +30% 손절 건 단위 최악(순bp)


def klines_1m(sym: str, months: list[str], lo: pd.Timestamp | None, hi: pd.Timestamp | None, full_open_only: bool = False) -> pd.DataFrame:
    fr = []
    for m in months:
        d = bp._csv(f"{bp.UM}/klines/{sym}/1m/{sym}-1m-{m}.zip")
        if not len(d):
            continue
        ix = bp._ms(d[0])
        if full_open_only:
            s = pd.DataFrame({"open": d[1].astype(float).to_numpy()}, index=ix)
        else:
            s = pd.DataFrame({"open": d[1].astype(float).to_numpy(), "high": d[2].astype(float).to_numpy(), "low": d[3].astype(float).to_numpy(),
                              "close": d[4].astype(float).to_numpy(), "qv": d[7].astype(float).to_numpy(), "n": d[8].astype(float).to_numpy()}, index=ix)
        s = s[s.index.tz_convert(None).to_period("M") == pd.Period(m, "M")]
        if lo is not None:
            s = s[(s.index >= lo) & (s.index <= hi)]
        fr.append(s)
    return pd.concat(fr).sort_index() if fr else pd.DataFrame()


def collect():
    m = json.loads((DATA / "match.json").read_text(encoding="utf-8"))
    ev = bl.events_table(json.loads((bl.DATA / "months.json").read_text(encoding="utf-8")))

    def one(e):
        sym, f = m.get(e["sym"]), DATA / f"{e['sym']}_perp1m.parquet"
        if sym is None or f.exists() or not (DATA / f"{e['sym']}_perp1hOHLC.parquet").exists():
            return 0
        p = pd.Period(e["first"], "M")
        spot = rb._read(bl.DATA / f"{e['sym']}.parquet")["open"]
        if not len(spot):
            return 0
        t0 = spot.index[0] + D
        d = klines_1m(sym, [str(p + k) for k in range(3)], t0, t0 + 10 * D)           # t0 ~ t0+10일 창만 저장
        d.to_parquet(f)
        return 1
    with ThreadPoolExecutor(8) as ex:
        n = sum(ex.map(one, ev))
    bf = DATA / "BTCUSDT_perp1m.parquet"
    if not bf.exists():
        months = [str(p) for p in pd.period_range("2019-09", "2026-10", freq="M")]
        with ThreadPoolExecutor(8) as ex:
            parts = list(ex.map(lambda mm: klines_1m("BTCUSDT", [mm], None, None, True), months))
        pd.concat(parts).sort_index().to_parquet(bf)
    print("수집", n)


def load_1m(sym: str) -> pd.DataFrame:
    d = pd.read_parquet(DATA / f"{sym}_perp1m.parquet")
    d.index = pd.to_datetime(d.index, utc=True)
    return d


def window(px: pd.DataFrame, E: pd.Timestamp) -> tuple[pd.DataFrame, float] | None:
    """E 분부터 NM+1 분 격자. 빠진 분은 이전 종가로 채움(거래 없음). E 분이 없으면 None. 반환 (격자 DataFrame, 채움 비율)."""
    if E not in px.index:
        return None
    idx = pd.date_range(E, periods=NM + 1, freq="min")
    w = px.reindex(idx)
    miss = w["open"].isna().to_numpy()
    c = w["close"].ffill()
    for col in ("open", "high", "low"):
        w[col] = w[col].fillna(c)
    w["qv"] = w["qv"].fillna(0.0)
    w["n"] = w["n"].fillna(0.0)
    w["close"] = c
    if w["open"].isna().any():
        return None
    return w, float(miss.mean())


def build_event(w: pd.DataFrame, fu: pd.DataFrame, btc: pd.Series, E: pd.Timestamp, stop: float | None, slip_bp: float) -> dict | None:
    """sz.build_event 와 같은 반환 모양(X 는 시간 단위로 올림). 손절은 1분 고가·분 시가 갭으로 판정."""
    idx = w.index
    o, hi = w["open"].to_numpy(), w["high"].to_numpy()
    b = btc.reindex(idx).to_numpy()
    if np.isnan(b).any():
        bb = btc.reindex(idx).ffill().to_numpy()
        if np.isnan(bb).any():
            return None
        b = bb
    p0, b0 = o[0], b[0]
    fd = np.zeros(NM + 1)                                       # 펀딩: (E, E+j분] 정산 합
    if len(fu):
        f = fu[(fu.index > E) & (fu.index <= idx[-1])]
        np.add.at(fd, np.ceil(np.asarray((f.index - E) / MIN, dtype=float)).astype(int), f["rate"].to_numpy())
    cum = np.cumsum(fd)
    k, Xm = None, NM
    if stop is not None:
        hit = np.nonzero(hi[:NM] >= p0 * (1 + stop))[0]
        if len(hit):
            k = int(hit[0])
            Xm = k + 1
    fill = o[NM] if k is None else max(o[k], p0 * (1 + stop)) * (1 + slip_bp / 1e4)
    real = -((fill / p0 - 1) - (b[Xm] / b0 - 1)) + cum[Xm]
    Xh = -(-Xm // 60)                                           # ceil
    hh = hi[:NM].reshape(HOLD, 60).max(axis=1)                  # 시간별 1분 고가 최대
    h = np.arange(1, Xh)
    m = -((hh[h - 1] / p0 - 1) - (b[h * 60] / b0 - 1)) + cum[h * 60]
    return {"X": Xh, "m": m, "real": real, "stopped": k is not None, "maxhigh": float(hi[:NM].max() / p0 - 1), "gapBp": None if k is None else float((max(o[k], p0 * (1 + stop)) / (p0 * (1 + stop)) - 1) * 1e4)}


FILL = {}


def prep_events_1m():
    m = json.loads((DATA / "match.json").read_text(encoding="utf-8"))
    btc = rb._read(DATA / "BTCUSDT_perp1m.parquet")["open"]
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
        pf, hf, mf = DATA / f"{e['sym']}_perp.parquet", DATA / f"{e['sym']}_perp1hOHLC.parquet", DATA / f"{e['sym']}_perp1m.parquet"
        if m.get(e["sym"]) is None or not pf.exists() or not hf.exists() or not mf.exists():
            cov["무기한없음"] += 1
            continue
        pd_ = rb._read(pf)["open"]
        if not len(pd_):
            cov["무기한없음"] += 1
            continue
        t0 = L + D
        g = sz.classify(pd_.index[0], t0)
        if g == "X":
            cov["X제외"] += 1
            continue
        h1 = pd.read_parquet(hf)
        h1.index = pd.to_datetime(h1.index, utc=True)
        if not len(h1):
            cov["봉부족"] += 1
            continue
        E = t0 if g == "C" else h1.index[0] + HR
        w = window(load_1m(e["sym"]), E)
        if w is None:
            cov["봉부족"] += 1
            continue
        w, fill = w
        fu = rb._read(DATA / f"{e['sym']}_funding.parquet") if (DATA / f"{e['sym']}_funding.parquet").exists() else pd.DataFrame(columns=["rate", "ivl"])
        day1 = spot.get(t0, np.nan) / spot.iloc[0] - 1
        row = {"sym": e["sym"], "L": L, "E": E, "grp": g, "split": cp.split(L), "pump": bool(np.isfinite(day1) and day1 >= sz.PUMP), "day1": float(day1), "fill": fill}
        bad = False
        for s in sz.STOPS:
            for slip in (sz.SLIP, sz.SLIP_S):
                r = build_event(w, fu, btc, E, s, slip)
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
    FILL["rows"] = rows
    return rows, cov


def run() -> dict:
    sz.prep_events = prep_events_1m
    sz.OUT_JSON = OUT_JSON
    o = sz.run()
    rows = FILL["rows"]
    oos = [r for r in rows if r["L"] >= sz.T0]
    gaps = {}
    for s in (0.30, 0.50, 1.00):
        g = np.array([r[(s, sz.SLIP)]["gapBp"] for r in oos if r[(s, sz.SLIP)]["stopped"]])
        gaps[f"+{int(s * 100)}%"] = {"n": int(len(g)), "median": round(float(np.median(g)), 1) if len(g) else None, "p90": round(float(np.quantile(g, 0.9)), 1) if len(g) else None,
                                      "max": round(float(g.max()), 1) if len(g) else None}
    o["extras"] = {"fillShareMedian": round(float(np.median([r["fill"] for r in rows])), 3), "fillShareP90": round(float(np.quantile([r["fill"] for r in rows], 0.9)), 3), "gapBpOOS": gaps}
    OUT_JSON.write_text(json.dumps(o, ensure_ascii=False, indent=1), encoding="utf-8")
    return o


def labels(o: dict, prev: dict) -> tuple[str, str]:
    w1m = o["unit"]["30|급등건너뜀=False"]["worstNetBp"]
    gap = "갭 실재" if abs(w1m) >= 0.7 * abs(WORST_1H_30) else "1시간봉 영향이 컸다"
    same = set(o["passed"]) == set(prev["passed"])
    return gap, "유지" if same else "변경"


def write_md(o: dict, prev: dict) -> None:
    gap, setlab = labels(o, prev)
    c, p = o["cells"], prev["cells"]
    add, drop = sorted(set(o["passed"]) - set(prev["passed"])), sorted(set(prev["passed"]) - set(o["passed"]))
    nA = sum(v["A"] for v in c.values())
    L = ["---", "track: crypto", "factor: binance-listing-perp-sizing-1m", "date: 2026-11-14", f"verdict: {gap}",
         "criteria_version: research-only (binance-listing-perp-sizing-1m-preregistration-2026-11, 사전등록 fa652a7d)", "reason: >-",
         f"  신호: 해당 없음 · 경제성: {'통과(수익 칸 존재)' if nA else '미달'}. 해상도 라벨 {gap}(+30% 손절 건 단위 최악 1분 {o['unit']['30|급등건너뜀=False']['worstNetBp']:+.1f}bp vs 1시간 {WORST_1H_30:+.1f}bp) · "
         f"설계 라벨 {o['label']} · 통과 칸 집합 {setlab}(1분 {len(o['passed'])}칸 / 1시간 {len(prev['passed'])}칸). 기록 전용.",
         "---", "", "# 바이낸스 신규 상장 무기한 크기·손절 — 1분봉 해상도 재측정 — 결과", "",
         f"사전등록 fa652a7d 그대로(코드 sz=9998570e 의 판정·시뮬레이션 재사용, 경로만 1분봉). OOS 건 {o['oosEvents']} (C {o['groups']['C건']} · D {o['groups']['D건']}) · 급등 {o['pumpEvents']}건 · TRAIN {o['trainEvents']}건.",
         f"분 채움 비율(거래 없는 분) 중앙 {o['extras']['fillShareMedian']:.1%} · 90분위 {o['extras']['fillShareP90']:.1%}. 커버리지 {o['coverage']}.", "",
         f"**해상도 라벨: {gap} · 통과 칸 집합: {setlab} · 설계 라벨: {o['label']}**" + (f" · 추천 {o['recommended']}" if o["recommended"] else ""), ""]
    if add or drop:
        L += [f"통과 칸 변화 — 추가: {add or '없음'} · 제외: {drop or '없음'}", ""]
    L += ["## 1. 건 단위 — 1분 vs 1시간 (명목 1, 비용 10bp 뒤, 손절 슬립 100bp)", "", "| 손절·급등 | 건 | 평균 순bp (1분) | 평균 (1시간) | 손절 발동 (1분/1시간) | 최악 순bp (1분) | 최악 (1시간) |", "|---|---|---|---|---|---|---|"]
    for k, v in o["unit"].items():
        q = prev["unit"][k]
        L.append(f"| {k} | {v['n']} | {v['meanNet10bp']:+.1f} | {q['meanNet10bp']:+.1f} | {v['stopShare']:.1%}/{q['stopShare']:.1%} | {v['worstNetBp']:+.1f} | {q['worstNetBp']:+.1f} |")
    L += ["", "## 2. 칸별 결과 (1분봉; 괄호는 1시간 결과)", "", "| 칸 | 최종 | MDD | 한 건 최악 | 스트레스 최종 | A | B | C | D | 통과 |", "|---|---|---|---|---|---|---|---|---|---|"]
    for k, v in c.items():
        q = p[k]
        d = "-" if v["D"] is None else f"{'O' if v['D'] else 'X'} ({v['bootP_mdd_gt25']:.1%})"
        L.append(f"| {k} | {v['final']:.3f} ({q['final']:.3f}) | {v['mdd']:.1%} ({q['mdd']:.1%}) | {v['worst1Pct']:.2f}% ({q['worst1Pct']:.2f}%) | {v['stressFinal']:.3f} | "
                 f"{'O' if v['A'] else 'X'} | {'O' if v['B'] else 'X'} | {'O' if v['C'] else 'X'} | {d} | {'**통과**' if v['pass'] else ''} |")
    L += ["", "## 3. 시기 세 칸 (기록) — 칸별 구간 수익률", "", "| 칸 | 2023 | 2024 | 2025~ |", "|---|---|---|---|"]
    for k, v in c.items():
        r = v["periodRet"]
        L.append(f"| {k} | {r['2023']:+.1%} | {r['2024']:+.1%} | {r['2025~']:+.1%} |")
    L += ["", "## 4. 기록", "", f"- 재현: 손절 없음 OOS 상장일 평균(10bp 뒤) {o['repro']['net10_dayMean']:+.1f}bp ({o['repro']['oosDays']}일) — 기준 +1,018.9bp(±1bp 이내여야 함).",
          f"- 손절 갭(분 시가가 트리거를 넘은 정도, 슬립 가산 전) OOS: {o['extras']['gapBpOOS']}",
          f"- 청산 근접(1분 고가 기준, 코인 고가가 진입가 대비 +32.8%/+49.5%/+99.5%): OOS {o['liquidationNear']['OOS']} · TRAIN {o['liquidationNear']['TRAIN']}", "",
          "## 5. 읽는 법·한계", "",
          "- 1분봉도 분 안 순서는 모른다(고가 도달 = 트리거 발동). 거래 없는 분은 이전 종가로 채웠다. 슬립 100/300bp·교차 마진은 가정값. 평가액 경로는 1시간 격자·불리한 고가 기준.",
          "- 같은 표본의 해상도 재측정이다 — 통과·추천은 가설이며 운용 근거가 아니다. 같은 표본 재절단·격자 변경 금지. 실계좌·모의 슬리브·정책 불변."]
    OUT_MD.write_text("\n".join(L) + "\n", encoding="utf-8")


def selftest():
    t0 = pd.Timestamp("2024-03-02", tz="UTC")
    idx = pd.date_range(t0, periods=NM + 1, freq="min")
    w = pd.DataFrame({"open": 100.0, "high": 100.0, "low": 100.0, "close": 100.0, "qv": 1.0, "n": 1.0}, index=idx)
    w.loc[idx[300], ["open", "high"]] = [100.0, 135.0]               # 5시간째 분 300 에서 +35% 고가
    w.loc[idx[NM], "open"] = 80.0
    btc = pd.Series(50.0, index=idx)
    fu = pd.DataFrame({"rate": [-0.001, -0.001], "ivl": [8.0, 8.0]}, index=[t0 + 8 * HR, t0 + 200 * HR])
    r = build_event(w, fu, btc, t0, None, sz.SLIP)
    assert r["X"] == HOLD and abs(r["real"] - (0.2 - 0.001)) < 1e-9 and not r["stopped"], r
    r = build_event(w, fu, btc, t0, 0.30, sz.SLIP)                   # 분 300 발동 → 정리 분 301 → 시간 6
    assert r["stopped"] and r["X"] == 6 and abs(r["real"] - (-(1.3 * 1.01 - 1))) < 1e-9 and len(r["m"]) == 5 and abs(r["gapBp"]) < 1e-9, r
    w.loc[idx[300], "open"] = 140.0                                  # 분 시가 갭
    r = build_event(w, fu, btc, t0, 0.30, sz.SLIP)
    assert abs(r["real"] - (-(1.4 * 1.01 - 1))) < 1e-9 and abs(r["gapBp"] - (140 / 130 - 1) * 1e4) < 1e-6, r
    px = w.drop(idx[10])                                             # 빠진 분은 이전 종가로 채움
    ww, fillshare = window(px.iloc[:], t0)
    assert fillshare > 0 and ww.loc[idx[10], "open"] == 100.0 and ww.loc[idx[10], "qv"] == 0.0
    assert window(px.drop(idx[0]), t0) is None                       # E 분이 없으면 제외
    print("selftest OK")


if __name__ == "__main__":
    if "--selftest" in sys.argv:
        selftest()
    elif "--collect" in sys.argv:
        collect()
    else:
        o = run()
        write_md(o, json.loads(PREV_JSON.read_text(encoding="utf-8")))
        print(o["label"], o["recommended"], o["passed"], o["repro"], o["extras"])
