"""VIX 인버스 규칙 체결 시점 비교 — 설명용 계산(새 규칙 선택 아님, 문턱·비용 불변).

    python research/strategy-lab/vix_fill_timing.py

같은 규칙(진입 ≥20 · 청산 ≤16, 한번에 / 수준 분할 {20,25,30,35})을 체결 가정 세 가지로 비교:
  A 신호일 종가(시간외·종가 근처 체결의 이상화)  B 다음 거래일 시가(현행 백테스트)  C 다음 거래일 종가
규칙 상태 기계는 scripts/vix-inverse-check.py 의 step() 을 그대로 쓴다(중복 구현 없음).
대상: 실제 SVIX(2022-03-30~) · 실제 SVXY(2022-03~) · 장기 −0.5x(합성+SVXY, 2011~). 비용 편도 5bp(왕복 10bp).
"""
import importlib.util
import json
import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))
import vix_level_product_era as V  # noqa: E402

_s = importlib.util.spec_from_file_location("vixchk", ROOT.parents[1] / "scripts" / "vix-inverse-check.py")
chk = importlib.util.module_from_spec(_s)
_s.loader.exec_module(chk)

OUT = ROOT / "findings/vix-fill-timing-results.json"
COST = 0.0005          # 편도
FILLS = {"A": ("close", 0), "B": ("open", 1), "C": ("close", 1)}


def targets(vix, split):
    """종가 뒤 목표 비중(0~1) 열 + 신호 상태. 비중은 분할이면 n/4, 아니면 보유 1."""
    st, w = (False, 0), []
    for v in vix:
        st, _ = chk.step(st, v)
        w.append(st[1] / len(chk.LEVELS) if split else float(st[0]))
    return np.array(w)


def sim(O, C, vix, split, fill):
    """O,C: 상품 시가·종가(배열), vix: 같은 날짜의 VIX 종가. 반환 통계 dict."""
    kind, lag = FILLS[fill]
    n = len(C)
    i0 = 0                                                    # 백테스트 관례: 첫날 현금(대기)에서 시작
    w = targets(vix, split)
    w[:i0] = 0.0
    cash, sh = 1.0, 0.0
    eq = np.full(n, np.nan)
    cyc, cur = [], None                                       # 사이클: 비중 0→>0 에서 시작, >0→0 에서 끝
    held = 0.0
    for d in range(i0, n):
        sig = d - lag                                          # 이 날 체결할 신호 = sig 일 종가에 확정된 목표
        if sig >= i0:
            px = O[d] if kind == "open" else C[d]
            tgt = w[sig]
            tot = cash + sh * px
            diff = tgt * tot - sh * px
            sh += diff / px
            cash -= diff + abs(diff) * COST
            if held == 0 and tgt > 0:
                cur = dict(start=tot, peak=tot, mdd=0.0)
            held = tgt
        tot_c = cash + sh * C[d]
        eq[d] = tot_c
        if cur is not None:
            cur["peak"] = max(cur["peak"], tot_c)
            cur["mdd"] = min(cur["mdd"], tot_c / cur["peak"] - 1)
            if held == 0:
                cur["ret"] = tot_c / cur["start"] - 1
                cyc.append(cur)
                cur = None
    open_cycle = cur is not None                              # 진행 중 사이클은 통계에서 제외, 표시만
    e = eq[i0:]
    r = np.array([c["ret"] for c in cyc])
    return dict(cycles=len(cyc), win=float((r > 0).mean()) if len(r) else None,
                mean=float(r.mean()) if len(r) else None, worst=float(r.min()) if len(r) else None,
                worst_intra_mdd=float(min(c["mdd"] for c in cyc)) if cyc else None,
                total=float(e[-1] / e[0] - 1), mdd=float((e / np.maximum.accumulate(e) - 1).min()),
                open_cycle=open_cycle)


def main():
    us = V.us_frames()
    vixfull = us["vix_full"]
    frames = {}
    for sym in ("SVIX", "SVXY"):
        x = V.dl(sym, "2022-03-01")[["Open", "Close"]].dropna()
        frames[f"{sym} 실제"] = (x.Open.to_numpy(float), x.Close.to_numpy(float), x.index)
    O, C = V.chain(us["inv"])
    frames["장기 -0.5x(합성+SVXY)"] = (O, C, us["inv"].index)
    res = {}
    for nm, (o, c, idx) in frames.items():
        vx = vixfull.reindex(idx).ffill().to_numpy(float)
        res[nm] = {}
        for split in (False, True):
            for f in "ABC":
                res[nm][f"{'분할' if split else '한번에'}-{f}"] = sim(o, c, vx, split, f)
    OUT.write_text(json.dumps(res, ensure_ascii=False, indent=1), encoding="utf-8")
    sys.stdout.reconfigure(encoding="utf-8")
    pc = lambda x: "-" if x is None else f"{x * 100:+.1f}%"
    for nm, d in res.items():
        print(f"\n## {nm}")
        print("| 방식-체결 | 사이클 | 승률 | 평균 | 최악 | 사이클중 최대낙폭 | 누적 | MDD |")
        print("|---|---|---|---|---|---|---|---|")
        for k, s in d.items():
            print(f"| {k} | {s['cycles']}{'+진행' if s['open_cycle'] else ''} | {pc(s['win'])} | {pc(s['mean'])} | "
                  f"{pc(s['worst'])} | {pc(s['worst_intra_mdd'])} | {pc(s['total'])} | {pc(s['mdd'])} |")


if __name__ == "__main__":
    main()
