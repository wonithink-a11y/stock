#!/usr/bin/env python3
"""바이낸스 신규 상장 7일 숏 무기한 — 체결 비용 대리 측정. 사전등록 findings/binance-listing-perp-cost-proxy-preregistration-2026-11.md (fa652a7d).

1분봉 거래대금으로 주문 참여율·손절 갭·코인당 명목 상한을 재고, 크기·손절 설계의 슬리피지 가정(100/300bp)이 낙관적인지 라벨을 단다. 기록 전용.
표본·진입은 binance_listing_perp_1m(51314a6b) 그대로.

    python research/strategy-lab/futures/binance_listing_perp_cost_proxy.py
    python research/strategy-lab/futures/binance_listing_perp_cost_proxy.py --selftest
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import binance_listing_perp_1m as m1  # noqa: E402

sz = m1.sz
OUT_JSON = HERE / "binance-listing-perp-cost-proxy.json"
OUT_MD = HERE.parent / "findings" / "binance-listing-perp-cost-proxy-results-2026-11.md"
SIZES = (10_000, 100_000, 1_000_000)
PART = (0.01, 0.05, 0.20)
STOPS = (0.30, 0.50, 1.00)


def q(x, p) -> float | None:
    x = np.asarray(x, dtype=float)
    return None if not len(x) else round(float(np.quantile(x, p)), 3)


def entry_metrics(w: pd.DataFrame) -> dict:
    qv = w["qv"].to_numpy()
    q60 = float(qv[:60].sum())
    hi, lo = w["high"].to_numpy()[:60], w["low"].to_numpy()[:60]
    rng = np.where(lo > 0, hi / lo - 1, np.nan)
    return {"q60": q60, "impactBp": float(np.nanmean(rng) * 1e4)}


def stop_metrics(w: pd.DataFrame, stop: float) -> dict | None:
    o, hi, qv = w["open"].to_numpy(), w["high"].to_numpy(), w["qv"].to_numpy()
    p0 = o[0]
    hit = np.nonzero(hi[: m1.NM] >= p0 * (1 + stop))[0]
    if not len(hit):
        return None
    k = int(hit[0])
    return {"gapBp": float((max(o[k], p0 * (1 + stop)) / (p0 * (1 + stop)) - 1) * 1e4), "q5": float(qv[k: k + 5].sum())}


def part(S: float, Q: float) -> float:
    return float("inf") if Q <= 0 else S / Q


def run() -> dict:
    rows, cov = m1.prep_events_1m()
    oos = [r for r in rows if r["L"] >= sz.T0]
    train = [r for r in rows if r["L"] < sz.T0]
    ent, stp = {}, {s: [] for s in STOPS}
    for name, grp in (("OOS", oos), ("TRAIN", train)):
        L = []
        for r in grp:
            w, _ = m1.window(m1.load_1m(r["sym"]), r["E"])
            em = entry_metrics(w)
            em.update(sym=r["sym"], pump=r["pump"], year=r["L"].year)
            L.append(em)
            if name == "OOS":
                for s in STOPS:
                    sm = stop_metrics(w, s)
                    if sm:
                        stp[s].append(sm)
        ent[name] = L
    E = ent["OOS"]
    q60 = np.array([e["q60"] for e in E])
    out = {"coverage": cov, "oosEvents": len(oos), "trainEvents": len(train), "entry": {}, "stop": {}, "capacity5pct": {}, "record": {}}
    for S in SIZES:
        p = np.array([part(S, x) for x in q60])
        out["entry"][f"S={S}"] = {"median": q(p[np.isfinite(p)], 0.5) if np.isfinite(p).any() else None, "p90": q(p[np.isfinite(p)], 0.9) if np.isfinite(p).any() else None,
                                  "zeroVolume": int((~np.isfinite(p)).sum()), **{f">{int(t * 100)}%": round(float((p > t).mean()), 3) for t in PART}}
    out["entryImpactBpMedian"] = q([e["impactBp"] for e in E], 0.5)
    cap = 0.05 * q60
    out["capacity5pct"] = {"p25": q(cap, 0.25), "median": q(cap, 0.5), "p75": q(cap, 0.75)}
    for s in STOPS:
        g = np.array([x["gapBp"] for x in stp[s]])
        row = {"n": int(len(g)), "gapMedian": q(g, 0.5), "gapP90": q(g, 0.9), "gapMax": q(g, 1.0), "gt100": round(float((g > 100).mean()), 3) if len(g) else None,
               "gt300": round(float((g > 300).mean()), 3) if len(g) else None}
        for S in SIZES:
            p = np.array([part(S, x["q5"]) for x in stp[s]])
            row[f"S={S}"] = {"median": q(p[np.isfinite(p)], 0.5) if np.isfinite(p).any() else None, ">5%": round(float((p > 0.05).mean()), 3) if len(p) else None}
        out["stop"][f"+{int(s * 100)}%"] = row
    out["record"] = {"pumpVsNonPump_S100k_median": {"pump": q([part(1e5, e["q60"]) for e in E if e["pump"] and e["q60"] > 0], 0.5), "nonPump": q([part(1e5, e["q60"]) for e in E if not e["pump"] and e["q60"] > 0], 0.5)},
                     "q60MedianByYear": {str(y): q([e["q60"] for e in E if e["year"] == y], 0.5) for y in sorted({e["year"] for e in E})},
                     "q60MedianTrain": q([e["q60"] for e in ent["TRAIN"]], 0.5)}
    g30 = out["stop"]["+30%"]
    if g30["n"] < 20:
        lab = "정보 부족"
    elif g30["gapMedian"] <= 100 and g30["gapP90"] <= 300 and (out["entry"]["S=100000"]["median"] or 1e9) <= 0.05:
        lab = "슬리피지 가정 적절"
    else:
        lab = "슬리피지 가정 낙관"
    out["label"] = lab
    OUT_JSON.write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
    return out


def fmt(x, pct=False) -> str:
    return "-" if x is None else (f"{x:.1%}" if pct else f"{x:,.1f}")


def write_md(o: dict) -> None:
    e, g30 = o["entry"], o["stop"]["+30%"]
    L = ["---", "track: crypto", "factor: binance-listing-perp-cost-proxy", "date: 2026-11-14", f"verdict: {o['label']}",
         "criteria_version: research-only (binance-listing-perp-cost-proxy-preregistration-2026-11, 사전등록 fa652a7d)", "reason: >-",
         f"  신호: 해당 없음 · 경제성: 해당 없음(가정 점검). 라벨 {o['label']} — +30% 손절 발동 {g30['n']}건 갭 중앙 {fmt(g30['gapMedian'])}bp·90분위 {fmt(g30['gapP90'])}bp, "
         f"S=100,000 진입 참여율 중앙 {fmt(e['S=100000']['median'], True)}(상장 직후 60분 거래대금 대비). 코인당 명목 상한(참여율 5%) 중앙 {fmt(o['capacity5pct']['median'])} USDT. 기록 전용.",
         "---", "", "# 바이낸스 신규 상장 무기한 — 체결 비용 대리 측정 — 결과", "",
         f"사전등록 fa652a7d 그대로. OOS(2023~) 건 {o['oosEvents']} · TRAIN {o['trainEvents']}(기록). 1분 거래대금(`quote volume`)·거래 없는 분은 0.", "",
         f"**라벨: {o['label']}**", "",
         "## 1. 진입 — 주문 크기별 참여율 (S / E 분부터 60분 거래대금)", "", "| 주문 S (USDT) | 참여율 중앙 | 90분위 | > 1% | > 5% | > 20% | 거래 없음 |", "|---|---|---|---|---|---|---|"]
    for S in (10_000, 100_000, 1_000_000):
        v = e[f"S={S}"]
        L.append(f"| {S:,} | {fmt(v['median'], True)} | {fmt(v['p90'], True)} | {v['>1%']:.1%} | {v['>5%']:.1%} | {v['>20%']:.1%} | {v['zeroVolume']} |")
    L += ["", f"진입 충격 대리(첫 60분 1분 범위 평균 `고가/저가−1`, 중앙) {fmt(o['entryImpactBpMedian'])}bp. 코인당 명목 상한(진입 참여율 5% 이하가 되는 S): 25분위 {fmt(o['capacity5pct']['p25'])} · 중앙 {fmt(o['capacity5pct']['median'])} · 75분위 {fmt(o['capacity5pct']['p75'])} USDT.", "",
          "## 2. 손절 — 갭(슬립 가산 전)과 손절 주문 참여율", "", "| 손절 | 발동 | 갭 중앙(bp) | 90분위 | 최대 | 갭>100bp | 갭>300bp | 참여율 중앙 S=1만 | S=10만 | S=100만 | (>5%: S=10만) |", "|---|---|---|---|---|---|---|---|---|---|---|"]
    for k, v in o["stop"].items():
        L.append(f"| {k} | {v['n']} | {fmt(v['gapMedian'])} | {fmt(v['gapP90'])} | {fmt(v['gapMax'])} | {fmt(v['gt100'], True)} | {fmt(v['gt300'], True)} | "
                 f"{fmt(v['S=10000']['median'], True)} | {fmt(v['S=100000']['median'], True)} | {fmt(v['S=1000000']['median'], True)} | {fmt(v['S=100000']['>5%'], True)} |")
    r = o["record"]
    L += ["", "## 3. 기록 (판정 불사용)", "", f"- S=100,000 진입 참여율 중앙 — 첫날 급등 건 {fmt(r['pumpVsNonPump_S100k_median']['pump'], True)} · 그 밖 {fmt(r['pumpVsNonPump_S100k_median']['nonPump'], True)}",
          f"- 진입 후 60분 거래대금(Q60) 중앙(USDT) 연도별: {r['q60MedianByYear']} · TRAIN {fmt(r['q60MedianTrain'])}",
          f"- 커버리지 {o['coverage']}", "",
          "## 4. 읽는 법·한계", "",
          "- 이 실험은 슬리피지의 실측이 아니다. 호가 깊이가 없어 **내 주문이 가격을 얼마나 밀지는 모른다** — 참여율(내 주문 / 그 시간 거래대금)과 분 시가 갭만 본다. 참여율 5% 는 관행적 상한이지 근거 있는 임계가 아니다.",
          "- 손절 갭 0bp 는 분 시가 기준이고, 같은 분 안에서 트리거를 지나 더 오른 뒤 체결되는 비용은 포함하지 않는다(그 비용은 슬립 가정 100/300bp 가 담당).",
          "- 같은 표본의 점검이다. 문턱·S 격자 변경, 재절단 금지. 실계좌·모의 슬리브·정책 불변."]
    OUT_MD.write_text("\n".join(L) + "\n", encoding="utf-8")


def selftest():
    idx = pd.date_range("2024-03-02", periods=m1.NM + 1, freq="min", tz="UTC")
    w = pd.DataFrame({"open": 100.0, "high": 100.0, "low": 100.0, "close": 100.0, "qv": 10.0, "n": 1.0}, index=idx)
    w.loc[idx[0:60], "high"] = 101.0
    w.loc[idx[100], ["open", "high"]] = [140.0, 141.0]
    em = entry_metrics(w)
    assert abs(em["q60"] - 600.0) < 1e-9 and abs(em["impactBp"] - 100.0) < 1e-6, em
    sm = stop_metrics(w, 0.30)
    assert sm and abs(sm["gapBp"] - (140 / 130 - 1) * 1e4) < 1e-6 and abs(sm["q5"] - 50.0) < 1e-9, sm
    assert stop_metrics(w, 1.0) is None and part(10, 0) == float("inf")
    print("selftest OK")


if __name__ == "__main__":
    if "--selftest" in sys.argv:
        selftest()
    else:
        o = run()
        write_md(o)
        print(o["label"], o["entry"], o["stop"]["+30%"])
