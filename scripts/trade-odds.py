#!/usr/bin/env python3
"""
단기 매매 승률 시뮬레이터 — '목표가 먼저냐, 손절가 먼저냐'를 오늘 남은 장으로 미리 돌려 본다.

day-trader-skill 의 '타임머신'(11-23 인스타 검증)을 우리 방식으로 다시 만들었다. 차이는 셋:
  1) 막대 재표본(그쪽 방식)만 쓰면 추세·연속성이 지워져 결과가 손절·목표 거리로 정해진다.
     그래서 **과거 하루 경로를 통째로 다시 돌린 값(연속성 보존)** 과 **무작위 보행 기준선** 을 같이 낸다.
     세 값이 비슷하면 이 종목의 최근 장중 흐름에 '정보가 없다'는 뜻이다.
  2) 비용(왕복)을 빼고 기대값·손익분기를 낸다. 기본 KR 33.5bp · US 50bp(KIS 해외 0.25%×2, 미확인 — --cost-bp 로 바꾼다).
  3) 한 막대 안에서 손절·목표가 같이 닿으면 **손절 먼저**로 센다(보수적).

자료: 야후 5분봉 정규장 최근 60일(무료·비공식, 지연·누락 가능). 주문·알림 없음, 출력 전용. 매매 판정이 아니다.

  python scripts/trade-odds.py TSLA --stop-pct 1.5 --target-pct 3
  python scripts/trade-odds.py 005930.KS --entry 55000 --stop 54000 --target 57000 --at 10:00
  python scripts/trade-odds.py --selftest
"""
import argparse
import json
import math
import sys
import urllib.request
from zoneinfo import ZoneInfo
from datetime import datetime

import numpy as np

N_PATHS, SEED = 10_000, 19


def fetch(sym):
    """야후 5분봉 60일 → {날짜: [(HH:MM, open, high, low, close)]} 정규장만."""
    url = f"https://query1.finance.yahoo.com/v8/finance/chart/{sym}?range=60d&interval=5m"
    with urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"}), timeout=20) as r:
        res = json.load(r)["chart"]["result"][0]
    tz = ZoneInfo(res["meta"].get("exchangeTimezoneName") or "UTC")
    q = res["indicators"]["quote"][0]
    days = {}
    for i, ts in enumerate(res.get("timestamp") or []):
        o, h, l, c = q["open"][i], q["high"][i], q["low"][i], q["close"][i]
        if None in (o, h, l, c):
            continue
        t = datetime.fromtimestamp(ts, tz)
        days.setdefault(t.date(), []).append((t.strftime("%H:%M"), o, h, l, c))
    return days


def rel_table(days, after):
    """at 이후 막대들의 상대 고·저·종(직전 종가 대비). 반환: slots, hi/lo/cl [일, 슬롯] (없으면 nan)."""
    slots = sorted({b[0] for bars in days.values() for b in bars if b[0] > after})
    idx = {s: k for k, s in enumerate(slots)}
    D = len(days)
    hi, lo, cl = (np.full((D, len(slots)), np.nan) for _ in range(3))
    for d, bars in enumerate(days.values()):
        prev = None
        for s, o, h, l, c in bars:
            base = prev if prev else o
            if s in idx:
                k = idx[s]
                hi[d, k], lo[d, k], cl[d, k] = h / base, l / base, c / base
            prev = c
    return slots, hi, lo, cl


def walk(hi, lo, cl, entry, stop, target):
    """경로 [n, 슬롯] → (목표 먼저, 손절 먼저, 장 마감 미결, 미결 종가 수익률 배열). 같은 막대면 손절 먼저."""
    n, S = cl.shape
    px = np.full(n, float(entry))
    state = np.zeros(n, int)          # 0 미결 · 1 목표 · -1 손절
    for k in range(S):
        h, l, c = hi[:, k], lo[:, k], cl[:, k]
        ok = ~np.isnan(c) & (state == 0)
        hit_s = ok & (px * l <= stop)
        hit_t = ok & ~hit_s & (px * h >= target)
        state[hit_s], state[hit_t] = -1, 1
        px = np.where(ok & ~hit_s & ~hit_t, px * c, px)
    open_ = state == 0
    return (state == 1).mean(), (state == -1).mean(), open_.mean(), px[open_] / entry - 1


def summarize(name, res, entry, stop, target, cost):
    pt, ps, po, r_open = res
    gain, loss = target / entry - 1, stop / entry - 1
    ev = pt * gain + ps * loss + po * (r_open.mean() if len(r_open) else 0)
    return {"방법": name, "목표먼저": pt, "손절먼저": ps, "미결": po, "기대값gross": ev, "기대값net": ev - cost}


def baseline(entry, stop, target):
    """무표류 무작위 보행에서 '어느 쪽이든 닿는다면' 목표가 먼저일 확률(로그 거리 비). 시간 제한 무시."""
    up, dn = math.log(target / entry), math.log(entry / stop)
    return dn / (up + dn)


def run(a):
    days = fetch(a.sym)
    if len(days) < 10:
        raise SystemExit(f"5분봉 일수 {len(days)} — 너무 적다")
    dates = list(days)
    full = max(len(v) for v in days.values())
    if len(days[dates[-1]]) < full:               # 진행 중인 오늘은 표본에서 빼고 현재가·시각만 쓴다
        today = days.pop(dates[-1])
    else:
        today = None
    last = (today or days[dates[-1]])[-1]
    at = a.at or (today[-1][0] if today else "00:00")
    entry = a.entry or last[4]
    stop = a.stop or entry * (1 - a.stop_pct / 100)
    target = a.target or entry * (1 + a.target_pct / 100)
    if not stop < entry < target:
        raise SystemExit("롱 기준: 손절 < 진입 < 목표 여야 한다")
    kr = a.sym.endswith((".KS", ".KQ"))
    cost = (a.cost_bp if a.cost_bp is not None else (33.5 if kr else 50)) / 1e4
    slots, hi, lo, cl = rel_table(days, at)
    if not slots:
        raise SystemExit(f"{at} 뒤에 남은 막대가 없다(장 마감 뒤?) — --at 으로 시각을 준다")
    D = hi.shape[0]
    rng = np.random.default_rng(a.seed)
    pick = rng.integers(0, D, size=(a.paths, len(slots)))     # 슬롯마다 과거 날을 따로 뽑는다(그쪽 방식)
    cols = np.arange(len(slots))
    H, L, C = hi[pick, cols], lo[pick, cols], cl[pick, cols]
    flip = rng.random(H.shape) < 0.5                          # 부호 대칭 기준선: 같은 막대·같은 시간, 방향만 동전
    Hn, Ln, Cn = np.where(flip, 1 / L, H), np.where(flip, 1 / H, L), np.where(flip, 1 / C, C)
    rows = [summarize("기준선(방향 무작위)", walk(Hn, Ln, Cn, entry, stop, target), entry, stop, target, cost),
            summarize("막대 재표본(연속성 제거)", walk(H, L, C, entry, stop, target), entry, stop, target, cost),
            summarize(f"과거 하루 통째({D}일, 연속성 보존)", walk(hi, lo, cl, entry, stop, target), entry, stop, target, cost)]
    print(f"{a.sym} · 진입 {entry:,.2f} · 손절 {stop:,.2f}({stop / entry - 1:+.2%}) · 목표 {target:,.2f}({target / entry - 1:+.2%})"
          f" · {at} 뒤 {len(slots)}막대 · 표본 {D}일({min(days)}~{max(days)}) · 왕복 비용 {cost * 1e4:.1f}bp")
    print(f"{'방법':<26}{'목표먼저':>8}{'손절먼저':>8}{'미결':>7}{'기대gross':>10}{'기대net':>9}")
    for r in rows:
        print(f"{r['방법']:<26}{r['목표먼저']:>8.1%}{r['손절먼저']:>8.1%}{r['미결']:>7.1%}{r['기대값gross']:>+10.3%}{r['기대값net']:>+9.3%}")
    print(f"참고: 시간 제한 없는 무표류 보행이면 닿는 쪽 중 목표 먼저 {baseline(entry, stop, target):.1%}")
    print("읽는 법: '하루 통째'가 '기준선'과 몇 %p 안이면 최근 장중 흐름에 방향 정보가 없다(손절·목표 거리와 변동성의 결과일 뿐)."
          f" 표본 {D}일이라 ±{100 / math.sqrt(D):.0f}%p 안팎 차이는 우연 범위다. 기대값net 이 음이면 비용을 못 넘는다."
          " 시뮬레이션이지 예측이 아니다 — 실적·급변 뉴스는 60일 안에 없다.")


def selftest():
    rng = np.random.default_rng(0)
    D, S = 400, 60
    steps = rng.normal(0, 0.002, (D, S))
    cl = np.exp(steps)
    hi, lo = cl * 1.0005, cl * 0.9995
    pt, ps, po, _ = walk(hi, lo, cl, 100, 99, 101)
    assert abs(pt - ps) < 0.08, (pt, ps)                    # 대칭 거리·무표류 → 거의 반반
    assert abs(pt + ps + po - 1) < 1e-9
    # 같은 막대에서 둘 다 닿으면 손절 먼저
    r = walk(np.array([[1.05]]), np.array([[0.95]]), np.array([[1.0]]), 100, 99, 101)
    assert r[1] == 1.0 and r[0] == 0.0
    # 목표가 먼저 닿는 경로
    r = walk(np.array([[1.0, 1.02]]), np.array([[0.999, 1.0]]), np.array([[1.0, 1.01]]), 100, 99, 101)
    assert r[0] == 1.0
    # nan 슬롯은 건너뛴다(그날 막대 없음)
    r = walk(np.array([[np.nan, 1.0]]), np.array([[np.nan, 1.0]]), np.array([[np.nan, 1.0]]), 100, 99, 101)
    assert r[2] == 1.0 and r[3][0] == 0.0
    assert abs(baseline(100, 99, 101) - 0.5) < 0.01 and baseline(100, 98, 101) > 0.6
    # rel_table: 첫 막대는 시가 대비, 이후는 직전 종가 대비, at 이후만
    days = {"d1": [("09:30", 10, 10, 10, 10), ("09:35", 10, 11, 9, 10.5), ("09:40", 10.5, 10.5, 10.5, 10.5)]}
    slots, h, l, c = rel_table(days, "09:30")
    assert slots == ["09:35", "09:40"] and abs(h[0, 0] - 1.1) < 1e-12 and abs(c[0, 1] - 1.0) < 1e-12
    print("selftest 통과")


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("sym", nargs="?")
    ap.add_argument("--entry", type=float)
    ap.add_argument("--stop", type=float)
    ap.add_argument("--target", type=float)
    ap.add_argument("--stop-pct", type=float, default=1.5)
    ap.add_argument("--target-pct", type=float, default=3.0)
    ap.add_argument("--at", help="이 시각(거래소 현지 HH:MM) 뒤부터 시뮬. 기본: 장중이면 마지막 막대, 아니면 장 시작")
    ap.add_argument("--cost-bp", type=float)
    ap.add_argument("--paths", type=int, default=N_PATHS)
    ap.add_argument("--seed", type=int, default=SEED)
    ap.add_argument("--selftest", action="store_true")
    a = ap.parse_args()
    if a.selftest:
        selftest()
    elif not a.sym:
        ap.error("종목 기호가 필요하다(예: TSLA, 005930.KS)")
    else:
        run(a)
