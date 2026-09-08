#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""DMA + Stochastic-50 진입신호 이벤트 스터디 (분봉 1년).

`dma_stoch_kr_intraday_1y.py` 는 규칙 **전체**(진입+청산+비용)를 재서 죽었다.
이 스크립트는 **진입 신호만 떼어내** 어느 시간축에서 우위가 있는지 본다.
청산 규칙이 문제인지, 진입 신호 자체에 정보가 없는지를 가른다.

  측정   신호 bar t -> 체결 bar t+1 open. 거기서 h bar 뒤 open 까지의 수익률.
         h = 1 · 5 · 10 · 30 · 60 · 120 분
  기준   **같은 분의 유니버스 횡단면 평균을 뺀 상대수익**이다. 이 1년은 KOSPI 가
         +115% 라 절대수익으로 재면 아무 신호나 양수가 나온다.
  범위   세션 안에서 h bar 가 남는 신호만 쓴다(오버나이트·장마감 절단 없음).
  바닥선 하루 단위 원형이동(circular shift) 난수 신호. 개수·종목분포는 그대로 두고
         시점만 깬다 - 이 저장소가 t>=2.0 을 난수로도 만들어 본 전례가 있다.

판정선: 왕복 30bp 를 넘는 상대우위가 어느 horizon 에도 없으면 진입 신호가 죽은
것이고, 특정 horizon 에서만 양이면 죽은 것은 청산 규칙이다.

  python dma_stoch_kr_event_study.py --selftest
  python dma_stoch_kr_event_study.py --universe 200
"""
import argparse
import json
import sys
import time
from collections import defaultdict
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

from dma_stoch_kr_intraday_1y import (SIGNAL_END_HHMM, day_matrices, day_signals,  # noqa: E402
                                      pick_universe)
from dma_stoch_kr_smoke import build_variants  # noqa: E402
from intraday import loader  # noqa: E402

OUT_DIR = HERE / "findings" / "dma-stoch50-kr-intraday-1y"
HORIZONS = (1, 5, 10, 30, 60, 120)
HURDLE_BP = 30.0          # 왕복 비용. 이 선을 넘어야 전략화 여지가 있다


class Acc:
    """스트리밍 1·2차 적률. 신호 수가 백만 단위라 배열로 안 들고 있는다."""

    __slots__ = ("n", "s", "ss", "pos")

    def __init__(self):
        self.n = self.s = self.ss = self.pos = 0.0

    def add(self, x):
        x = x[np.isfinite(x)]
        if x.size:
            self.n += x.size
            self.s += float(x.sum())
            self.ss += float((x * x).sum())
            self.pos += float((x > 0).sum())

    def stats(self):
        if self.n < 2:
            return {"n": int(self.n)}
        mean = self.s / self.n
        var = max(self.ss / self.n - mean * mean, 0.0) * self.n / (self.n - 1)
        se = (var / self.n) ** 0.5
        return {"n": int(self.n),
                "meanBp": round(mean * 1e4, 3),
                "t": round(mean / se, 2) if se > 0 else None,
                "hitRate": round(100 * self.pos / self.n, 2)}


def relative_forward(O, priced, horizons=None):
    """horizon 별 (상대수익 행렬, 유효마스크). 상대 = 그 분의 유니버스 평균 대비."""
    out = {}
    T = O.shape[0]
    for h in (horizons or HORIZONS):
        if T <= h:
            continue
        with np.errstate(invalid="ignore", divide="ignore"):
            fwd = O[h:] / O[:-h] - 1.0                     # (T-h) x N, 시작 bar 기준
        ok = np.isfinite(fwd) & priced[:-h] & priced[h:]
        cnt = ok.sum(axis=1)
        base = np.where(cnt > 0, np.where(ok, fwd, 0.0).sum(axis=1) / np.maximum(cnt, 1), 0.0)
        out[h] = (np.where(ok, fwd - base[:, None], np.nan), ok)
    return out


def entry_defs():
    """진입 정의만 뽑는다 - 청산은 이 실험의 대상이 아니다."""
    seen, defs = set(), []
    for v in build_variants():
        key = (v["ma"], v["n"], tuple(v["stoch"]), v["line"], v["entry"])
        if key in seen:
            continue
        seen.add(key)
        defs.append(v)
    return defs


def run(n_universe, max_days):
    t0 = time.time()
    dates = loader.list_dates()
    if max_days:
        dates = dates[:max_days]
    tickers, _ = pick_universe(dates, n_universe)
    N = len(tickers)
    defs = entry_defs()
    print("universe=%d dates=%d 진입정의=%d (%.0fs)" % (N, len(dates), len(defs), time.time() - t0),
          flush=True)

    half = dates[len(dates) // 2]
    acc = defaultdict(Acc)          # (entry_id, horizon, bucket) -> Acc
    counts = defaultdict(int)
    rng = np.random.default_rng(42)

    for di, date in enumerate(dates):
        mats = day_matrices(date, tickers)
        if mats is None or len(mats["grid"]) < 40:
            continue
        O = mats["open"].values
        priced = np.isfinite(O)
        rel = relative_forward(O, priced)
        bucket = "H1" if date <= half else "H2"

        for v in defs:
            en, _ = day_signals(mats, v)
            fill = np.vstack([np.zeros((1, N), bool), en[:-1]])   # 신호 t -> 체결 t+1
            counts[v["id"]] += int(fill.sum())
            shift = int(rng.integers(1, fill.shape[0]))
            plc = np.roll(fill, shift, axis=0)
            for h, (r, ok) in rel.items():
                m = fill[:r.shape[0]] & ok
                acc[(v["id"], h, "ALL")].add(r[m])
                acc[(v["id"], h, bucket)].add(r[m])
                acc[(v["id"], h, "PLACEBO")].add(r[plc[:r.shape[0]] & ok])
        if di % 40 == 0:
            print("  [%d/%d] %s (%.0fs)" % (di, len(dates), date, time.time() - t0), flush=True)

    results = []
    for v in defs:
        row = {"id": v["id"], "entry": v["entry"],
               "spec": {k: v[k] for k in ("ma", "n", "stoch", "line")},
               "signals": counts[v["id"]], "horizons": {}}
        for h in HORIZONS:
            row["horizons"][str(h)] = {b: acc[(v["id"], h, b)].stats()
                                       for b in ("ALL", "H1", "H2", "PLACEBO")}
        results.append(row)

    out = {
        "experiment": "DMA + Stochastic-50 진입신호 이벤트 스터디 (분봉 1년)",
        "question": "규칙 전체가 아니라 진입 신호만 떼어냈을 때 어느 시간축에 우위가 있는가",
        "sourceCaveat": "Claude 는 원본 영상을 보지 못했다. 사용자가 옮겨 적은 규칙만 입력이다.",
        "measure": "체결 bar(t+1) open -> h bar 뒤 open, 같은 분 유니버스 횡단면 평균 대비 상대수익(bp)",
        "why_relative": "이 1년은 KOSPI +115%. 절대수익으로 재면 아무 신호나 양수가 된다",
        "hurdleBp": HURDLE_BP,
        "placebo": "하루 단위 원형이동 - 신호 개수·종목분포 유지, 시점만 파괴",
        "splits": {"H1": "%s ~ %s" % (dates[0], half), "H2": "%s ~ %s" % (half, dates[-1])},
        "data": {"dates": len(dates), "from": dates[0], "to": dates[-1], "universe": N},
        "results": results,
        "elapsedSeconds": round(time.time() - t0, 1),
    }
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    (OUT_DIR / "event_study.json").write_text(json.dumps(out, ensure_ascii=False, indent=2,
                                                        allow_nan=False), encoding="utf-8")
    print("\nwritten: %s (%ss)" % (OUT_DIR / "event_study.json", out["elapsedSeconds"]))
    return out


def selftest():
    # Acc 의 평균·t 가 numpy 와 일치하는지
    x = np.array([0.001, -0.002, 0.003, 0.0005, -0.0011])
    a = Acc()
    a.add(x)
    st = a.stats()
    assert st["n"] == 5 and abs(st["meanBp"] - x.mean() * 1e4) < 1e-6, st
    exp_t = x.mean() / (x.std(ddof=1) / np.sqrt(5))
    assert abs(st["t"] - round(exp_t, 2)) < 0.01, (st, exp_t)
    assert st["hitRate"] == 60.0, st
    a.add(np.array([np.nan, np.inf]))            # 비유한값은 안 센다
    assert a.stats()["n"] == 5

    # relative_forward: 횡단면 평균이 제거되는지 - 모든 종목이 같이 오르면 상대는 0
    T, N = 200, 3
    O = np.ones((T, N)) * 100.0
    O[:, 0] = np.linspace(100, 110, T)
    O[:, 1] = np.linspace(100, 110, T)
    O[:, 2] = np.linspace(100, 110, T)
    rel = relative_forward(O, np.isfinite(O))
    assert np.nanmax(np.abs(rel[10][0])) < 1e-12, "공통 상승이 상대수익에 남았다"

    # 한 종목만 더 오르면 그 종목은 양, 나머지는 음
    O[:, 0] = np.linspace(100, 130, T)
    rel = relative_forward(O, np.isfinite(O))
    r10 = rel[10][0]
    assert np.nanmean(r10[:, 0]) > 0 and np.nanmean(r10[:, 1]) < 0, r10[:5]
    assert abs(np.nanmean(np.nansum(r10, axis=1))) < 1e-12, "횡단면 합은 0 이어야 한다"

    # 체결 시프트: 신호 bar t 의 관측은 t+1 에서 시작한다 (same-bar lookahead 없음)
    en = np.zeros((5, 1), bool)
    en[1] = True
    fill = np.vstack([np.zeros((1, 1), bool), en[:-1]])
    assert list(fill[:, 0]) == [False, False, True, False, False], fill[:, 0]

    # 진입정의 중복 제거: 청산만 다른 변형은 하나로 합쳐진다
    d = entry_defs()
    assert len(d) < len(build_variants()) and len({(x["ma"], x["n"], tuple(x["stoch"]),
                                                    x["line"], x["entry"]) for x in d}) == len(d)
    print("selftest ok (9 assertions), 진입정의 %d개" % len(d))


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--universe", type=int, default=200)
    ap.add_argument("--days", type=int, default=0)
    ap.add_argument("--selftest", action="store_true")
    a = ap.parse_args()
    if a.selftest:
        selftest()
    else:
        run(a.universe, a.days)
