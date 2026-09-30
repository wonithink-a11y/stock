#!/usr/bin/env python3
"""거래량이 늘어난 종목에 올라타고, 거래량이 줄면 내린다 — 일 단위 시험. 실행 전 고정 설계(2026-09-30). 자문 아님.

    python research/strategy-lab/daily_volume_exit_test.py --selftest
    python research/strategy-lab/daily_volume_exit_test.py    # -> findings/daily-volume-exit-results-2026-09.json

월 패널 시험(leader_riding_test T2)은 이탈 신호가 한 달 늦게 잡히는 한계가 있었다. 여기서는 일봉으로 재현한다.
자료: data/backfill/price/a2a/*.jsonl.gz(A2a 일봉, 수정주가 + 원값 거래량), 2015 는 지표 워밍업, 표본 2016-01~2026-08.
- 적격(신호일 T, T 제외 직전 20일 평균 '종가 x 거래량' 거래대금 >= 20억원), 진입일 시가 유효(거래정지 아님).
- 거래량 지표: V5 = 최근 5일 평균 거래량, V20 = 그 5일 직전 20일 평균 거래량, 비 r = V5 / V20.
- 진입(주 시험): 종가 기준 r >= 1.5 가 오늘 **처음** 된 날(어제 r < 1.5) AND 최근 5일 종가 수익 >= +3%(가격이 오르면서 거래량이 는 것, 분할 오염도 걸러진다). 진입은 T+1 시가.
  기록 전용 변형: 가격 조건 없이 r >= 1.5 첫 날.
- 퇴출 규칙 6개(신호는 종가 관측, 체결은 다음 날 시가, 최대 60거래일):
  E5·E20·E60 = 5·20·60일 보유(고정) · VOL = r < 1.0 이 되는 첫 날(5일 평균 거래량이 진입 전 수준 아래로 소진) ·
  PEAK = V5 가 진입 후 최고치의 절반 미만이 되는 첫 날 · STOP = 종가가 진입 후 최고 종가 대비 -10% 아래(가격 기준 기준선: 거래량 신호가 가격 손절보다 정보가 더 있는지 대조).
- 수익: 진입 시가 → 퇴출 시가, 초과 = 종목 - 같은 기간 적격 종목 등가중(일 시가대시가 복리). 총 · 비용 후(왕복 33.5bp = 에피소드당 고정 차감).
  지표: 에피소드 평균 초과(bp)·중앙·승률·평균 보유일·'일당'(총 초과 합 / 총 보유일 합, bp/일). 12개월 블록 부트스트랩 2,000회(진입월 블록), 난수 진입 플라시보 100회(같은 수 이내 무작위 적격 종목-일, 최대 60,000).
- 구간(기록): TRAIN <= 2020 · VALID 2021~22 · TEST 2023~.
- 판정(결과 전 고정): (a) 진입 우위 = E20 평균이 플라시보 p95 초과 & 구간 하한 > 0 & 세 구간 부호 같음. (b) 반대 방향 = E20 평균이 플라시보 p5 미만 & 구간 상한 < 0.
  (c) 거래량 이탈이 낫다 = VOL 또는 PEAK 의 (E20 대비) 짝지은 차이 하한 > 0 이고 (STOP 대비) 차이 하한 > 0. 결과를 보고 임계(1.5·+3%·0.5·-10%)를 바꾸지 않는다.
- 한계: 상·하한가·거래정지·동시호가 체결 불가 미반영, 폐지 종목 제외(생존 편향 — 편승 우위를 부풀리므로 반대 방향 결론에는 보수적), 거래대금은 수정주가 x 원값 거래량 근사.
"""
from __future__ import annotations

import gzip
import json
import math
import sys
from pathlib import Path

import numpy as np
import pandas as pd

LAB = Path(__file__).resolve().parent
REPO = LAB.parents[1]
A2A = REPO / "data" / "backfill" / "price" / "a2a"
RES = LAB / "findings" / "daily-volume-exit-results-2026-09.json"
RULES = ["E5", "E20", "E60", "VOL", "PEAK", "STOP"]
MAXH = 60
RT = 0.00335


def load():
    frames = []
    for y in range(2015, 2027):
        f = A2A / f"{y}.jsonl.gz"
        if not f.exists():
            continue
        rows = []
        with gzip.open(f, "rt", encoding="utf-8") as fh:
            for line in fh:
                d = json.loads(line)
                rows.append((d["ticker"], d["date"], d["open"], d["close"], d["volume"]))
        frames.append(pd.DataFrame(rows, columns=["ticker", "date", "open", "close", "volume"]))
    df = pd.concat(frames).drop_duplicates(["ticker", "date"])
    df["date"] = pd.to_datetime(df["date"])
    df["ticker"] = df["ticker"].astype(str)
    pv = lambda c: df.pivot(index="date", columns="ticker", values=c).sort_index().astype("float32")
    return pv("open"), pv("close"), pv("volume")


def prepare(O: pd.DataFrame, C: pd.DataFrame, V: pd.DataFrame):
    O = O.where(O > 0)            # 거래정지일 시가 0 기록은 결측(정제, 설계 밖)
    V = V.where(V > 0)
    v5 = V.rolling(5, min_periods=4).mean()
    v20 = V.shift(5).rolling(20, min_periods=15).mean()
    r = v5 / v20
    tv = (C * V).shift(1).rolling(20, min_periods=15).mean()
    liquid = tv >= 2e9
    ret5 = C / C.shift(5) - 1
    oo = O / O.shift(1) - 1
    oo = oo.clip(-0.35, 0.35)
    bm = oo.where(liquid.shift(1, fill_value=False)).mean(axis=1)
    cum = np.log1p(bm.fillna(0.0)).cumsum().values
    return dict(O=O.values, C=C.values, V5=v5.values, R=r.values, liquid=liquid.values, ret5=ret5.values, cum=cum, dates=O.index, cols=list(O.columns))


def entries(P, price_cond=True):
    R, ret5, liq = P["R"], P["ret5"], P["liquid"]
    D, N = R.shape
    fresh = (R >= 1.5) & ~(np.vstack([np.full((1, N), np.nan), R[:-1]]) >= 1.5)
    m = fresh & liq & (ret5 >= 0.03 if price_cond else True)
    start = int(np.searchsorted(P["dates"], pd.Timestamp("2016-01-04")))
    m[:start] = False
    m[D - MAXH - 3:] = False
    # 진입 시가 유효
    nxt = np.vstack([P["O"][1:], np.full((1, N), np.nan)])
    m &= ~np.isnan(nxt)
    return np.argwhere(m)


def evaluate(P, idx):
    t_i, j_i = idx[:, 0], idx[:, 1]
    n = len(t_i)
    O, C, V5, R, cum = P["O"], P["C"], P["V5"], P["R"], P["cum"]
    eo = O[t_i + 1, j_i]
    pk_v5 = V5[t_i, j_i].copy()          # PEAK 기준: 진입 후 관측일 V5 최고(진입 신호일 포함)
    pk_c = C[t_i, j_i].copy()
    hit = {r: np.zeros(n, bool) for r in ("VOL", "PEAK", "STOP")}
    hk = {r: np.full(n, MAXH) for r in ("VOL", "PEAK", "STOP")}
    for k in range(1, MAXH + 1):
        e = t_i + k
        ck, vk, rk = C[e, j_i], V5[e, j_i], R[e, j_i]
        pk_v5 = np.fmax(pk_v5, vk)
        pk_c = np.fmax(pk_c, ck)
        c = {"VOL": ~(rk >= 1.0), "PEAK": ~(vk >= 0.5 * pk_v5), "STOP": ~(ck >= 0.9 * pk_c)}
        for r in c:
            new = c[r] & ~hit[r]
            hk[r] = np.where(new, k, hk[r])
            hit[r] |= new
    out = {}
    for r in RULES:
        if r.startswith("E"):
            H = np.full(n, int(r[1:]))
        else:
            H = hk[r]
        x = t_i + 1 + H
        xo = O[x, j_i]
        xo = np.where(np.isnan(xo), C[x - 1, j_i], xo)
        stock = xo / eo - 1
        bench = np.exp(cum[x] - cum[t_i + 1]) - 1
        ex = stock - bench
        ex = np.where(np.isfinite(ex), ex, np.nan)
        out[r] = (ex, H)
    return t_i, out


def wmean(ex, H, w):
    ok = ~np.isnan(ex)
    return float(np.sum(w[ok] * ex[ok]) / np.sum(w[ok])), float(np.sum(w[ok] * ex[ok]) / np.sum(w[ok] * H[ok]))


def analyze(P, idx, dates_month, rng, n_plc=100):
    t_i, out = evaluate(P, idx)
    n = len(t_i)
    months = pd.Series(P["dates"][t_i]).dt.to_period("M")
    mi = (months.dt.year * 12 + months.dt.month).values
    mi0 = mi - mi.min()
    T = int(mi0.max()) + 1
    yr = pd.Series(P["dates"][t_i]).dt.year.values
    per = np.where(yr <= 2020, "TRAIN", np.where(yr <= 2022, "VALID", "TEST"))
    res = {}
    boots = {r: [] for r in RULES}
    pday = {r: [] for r in RULES}
    diffs = {k: [] for k in ("VOL-E20", "PEAK-E20", "VOL-STOP", "PEAK-STOP")}
    nb = math.ceil(T / 12)
    for _ in range(2000):
        st = rng.integers(0, T, nb)
        cnt = np.bincount(np.concatenate([(s0 + np.arange(12)) % T for s0 in st])[:T], minlength=T).astype(float)
        w = cnt[mi0]
        if w.sum() == 0:
            continue
        me = {}
        for r in RULES:
            e, H = out[r]
            me[r] = wmean(e, H, w)
            boots[r].append(me[r][0])
            pday[r].append(me[r][1])
        diffs["VOL-E20"].append(me["VOL"][0] - me["E20"][0])
        diffs["PEAK-E20"].append(me["PEAK"][0] - me["E20"][0])
        diffs["VOL-STOP"].append(me["VOL"][0] - me["STOP"][0])
        diffs["PEAK-STOP"].append(me["PEAK"][0] - me["STOP"][0])
    # 플라시보
    liq = P["liquid"].copy()
    D, N = liq.shape
    start = int(np.searchsorted(P["dates"], pd.Timestamp("2016-01-04")))
    liq[:start] = False
    liq[D - MAXH - 3:] = False
    liq &= ~np.isnan(np.vstack([P["O"][1:], np.full((1, N), np.nan)]))
    allv = np.argwhere(liq)
    plc = {r: [] for r in RULES}
    plc_pd = {r: [] for r in RULES}
    m = min(n, 60000, len(allv))
    for _ in range(n_plc):
        pick = allv[rng.choice(len(allv), size=m, replace=False)]
        _, o2 = evaluate(P, pick)
        for r in RULES:
            e, H = o2[r]
            a, b = wmean(e, H, np.ones(len(e)))
            plc[r].append(a)
            plc_pd[r].append(b)
    for r in RULES:
        e, H = out[r]
        ok = ~np.isnan(e)
        q = lambda a, p: float(np.quantile(a, p) * 1e4)
        lo, hi = np.quantile(e[ok], [.01, .99])
        res[r] = dict(n=int(ok.sum()), mean_bp=float(np.mean(e[ok]) * 1e4), mean_wins_bp=float(np.mean(np.clip(e[ok], lo, hi)) * 1e4), net_bp=float((np.mean(e[ok]) - RT) * 1e4), median_bp=float(np.median(e[ok]) * 1e4),
                      hit=float((e[ok] > 0).mean()), avg_hold=float(H[ok].mean()), per_day_bp=float(np.sum(e[ok]) / np.sum(H[ok]) * 1e4),
                      ci=[q(boots[r], .025), q(boots[r], .975)], ci_per_day=[q(pday[r], .025), q(pday[r], .975)],
                      placebo_mean_bp=float(np.mean(plc[r]) * 1e4), placebo_p5_bp=q(plc[r], .05), placebo_p95_bp=q(plc[r], .95),
                      placebo_per_day_bp=float(np.mean(plc_pd[r]) * 1e4),
                      periods={p: float(np.mean(e[ok & (per == p)]) * 1e4) if (ok & (per == p)).sum() else None for p in ("TRAIN", "VALID", "TEST")},
                      periods_n={p: int((ok & (per == p)).sum()) for p in ("TRAIN", "VALID", "TEST")})
    res["diffs"] = {k: dict(mean=float(np.mean(v) * 1e4), ci=[q(v, .025), q(v, .975)]) for k, v in diffs.items()}
    e20 = res["E20"]
    res["edge"] = bool(e20["mean_bp"] > e20["placebo_p95_bp"] and e20["ci"][0] > 0 and len({np.sign(v) for v in e20["periods"].values() if v is not None}) == 1)
    res["reverse"] = bool(e20["mean_bp"] < e20["placebo_p5_bp"] and e20["ci"][1] < 0)
    res["vol_exit_better"] = bool(any(res["diffs"][f"{a}-E20"]["ci"][0] > 0 and res["diffs"][f"{a}-STOP"]["ci"][0] > 0 for a in ("VOL", "PEAK")))
    res["n_entries"] = int(n)
    return res


def main():
    O, C, V = load()
    P = prepare(O, C, V)
    rng = np.random.default_rng(51)
    out = {"days": len(P["dates"]), "stocks": len(P["cols"]), "first": str(P["dates"][0].date()), "last": str(P["dates"][-1].date())}
    out["main"] = analyze(P, entries(P, True), None, rng)
    out["no_price_cond"] = analyze(P, entries(P, False), None, rng, n_plc=50)
    RES.write_text(json.dumps(out, ensure_ascii=False, indent=1, default=float), encoding="utf-8")
    print("done", out["days"], out["stocks"], out["main"]["n_entries"], out["no_price_cond"]["n_entries"])


def selftest():
    D, N = 200, 3
    dates = pd.bdate_range("2015-06-01", periods=D)
    O = pd.DataFrame(100.0, index=dates, columns=list("abc"))
    C = O.copy()
    V = pd.DataFrame(1e9, index=dates, columns=list("abc"))
    V.iloc[120:125, 0] = 5e9                      # a 종목 거래량 급증
    C.iloc[115:125, 0] = np.linspace(100, 110, 10)
    P = prepare(O.astype("float32"), C.astype("float32"), V.astype("float32"))
    # 워밍업/구간 조건 때문에 진입 없음(2016 이전) -> 직접 idx 로 평가
    idx = np.array([[130, 0]])
    t_i, out = evaluate(P, idx)
    assert abs(out["E20"][0][0]) < 1e-6 and out["E20"][1][0] == 20      # 가격 불변, 벤치 0 -> 초과 0
    assert out["STOP"][1][0] <= MAXH
    print("selftest ok")


if __name__ == "__main__":
    selftest() if "--selftest" in sys.argv else main()
