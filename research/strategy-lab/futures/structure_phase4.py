#!/usr/bin/env python3
"""차트 구조형 단기 신호 4차 — 사전등록 `findings/structure-patterns-preregistration-2026-09.md`.

    python research/strategy-lab/futures/structure_phase4.py            # 실행
    python research/strategy-lab/futures/structure_phase4.py --selftest

셀·파라미터·비용·바닥선·판정·이웃 검증 규칙은 사전등록 문서에 고정. 여기서 바꾸지 않는다.
모든 탐지기는 (행 x 시간) 2차원 배열에서 j 루프로 도는 벡터 형태이고, 행당 **첫 이벤트만** 낸다
(KR = 종목-일, 크립토 = 종목 x 48시간 블록). 관측 단위는 날짜별 평균이다(phase2 와 동일).
"""
from __future__ import annotations

import glob
import json
import sys
import warnings
from pathlib import Path

import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from short_horizon_study import tstat, null_bar  # noqa: E402
from short_horizon_phase2 import load_grid, MARKS, MI, J1520, day_splitter  # noqa: E402

warnings.filterwarnings("ignore", category=RuntimeWarning)     # 전부 NaN 슬라이스
CACHE = HERE.parent / ".cache"
CRYPTO = HERE.parent / "data" / "crypto"
SEED = 20260924

# ---- 비용 (사전등록 §2) ---------------------------------------------------------
KR_FIXED_BP = 0.72 + 20.0    # 유관기관 ~0.36bp x 2 (수수료 0 = KIS 무료 가정) + 매도 거래세·농특세 0.20%
KR_TICK_K, KR_TICK_K2 = 1.0, 2.0
CR_COST, CR_COST2, CR_COST_FREE = 10.0, 20.0, 3.0
_TICK_THR = np.array([2000, 5000, 20000, 50000, 200000, 500000])
_TICK_VAL = np.array([1, 5, 10, 50, 100, 500, 1000])


def tick_bp(px):
    px = np.asarray(px, float)
    return _TICK_VAL[np.searchsorted(_TICK_THR, px, side="right")] / px * 1e4


# ---- 파라미터 (사전등록 §3, 이웃 검증이 이 값들을 x0.75 / x1.33 으로 흔든다) --------
KR_P = {"m": 0.001, "reclaim": 3, "lb": 12, "pre": 6, "mss": 6, "retr": 12, "vol": 3.0, "rng": 0.5,
        "abs_lb": 12, "move": 0.01, "box": 18, "wmax": 0.015, "drive": 0.015, "depth": 0.38, "bo": 0.003}
CR_P = {"m": 0.001, "reclaim": 3, "lb": 24, "pre": 6, "mss": 6, "retr": 12, "vol": 3.0, "rng": 0.5,
        "abs_lb": 12, "move": 0.03, "box": 48, "wmax": 0.06}
INT_KEYS = {"reclaim", "lb", "pre", "mss", "retr", "abs_lb", "box"}


def _col(x, j):
    return x[:, j] if x.shape[1] > 1 else x[:, 0]


def _first(a, mask, j):
    m = mask & (a < 0)
    a[m] = j


# ---- 탐지기 --------------------------------------------------------------------
# 입력 A: dict(h,l,c,v 2차원 (n,T) / lo,hi 수준 (n,T) 또는 (n,1) / open (n,1)),
# j0,j1: 결정 인덱스 범위 [j0, j1]. 반환 dec (n,) = 결정 인덱스(-1 = 없음).
def d_sweep(A, p, j0, j1, side):
    """전일 저/고 스윕 -> 3봉 안 복귀(종가). side=+1 저점 스윕(롱), -1 고점 스윕(숏)."""
    h, l, c = A["h"], A["l"], A["c"]
    n = len(c)
    s = np.full(n, -1)
    dec = np.full(n, -1)
    for j in range(j0, j1 + 1):
        lv = _col(A["lo" if side > 0 else "hi"], j)
        hit = (l[:, j] < lv * (1 - p["m"])) if side > 0 else (h[:, j] > lv * (1 + p["m"]))
        _first(s, hit & (dec < 0), j)
        back = (c[:, j] > lv) if side > 0 else (c[:, j] < lv)
        m = (s >= 0) & (dec < 0) & (j <= s + p["reclaim"] - 1) & back
        dec[m] = j
        s[(s >= 0) & (dec < 0) & (j >= s + p["reclaim"] - 1)] = -1      # 복귀 실패 -> 재무장
    return dec


def d_mss_fvg(A, p, j0, j1, side):
    """스윕(스윙 저/고, lb봉) -> MSS(직전 pre봉 고/저 종가 돌파) -> FVG.
    반환 (dec_mss, t_fvg, px_fvg): MSS 결정 인덱스 / FVG 재진입 인덱스 / FVG 가장자리 가격."""
    h, l, c = A["h"], A["l"], A["c"]
    n = len(c)
    s, q, t = (np.full(n, -1) for _ in range(3))
    ref = np.full(n, np.nan)
    gap = np.full(n, np.nan)
    fv = np.zeros(n, bool)
    lb = p["lb"]
    for j in range(max(j0, lb + 2), j1 + p["retr"] + p["mss"] + 1):
        if j >= c.shape[1]:
            break
        if j <= j1:
            sw = np.nanmin(l[:, j - lb:j - 2], 1) if side > 0 else np.nanmax(h[:, j - lb:j - 2], 1)
            hit = (l[:, j] < sw * (1 - p["m"])) if side > 0 else (h[:, j] > sw * (1 + p["m"]))
            new = hit & (s < 0) & (q < 0)
            s[new] = j
            ref[new] = (np.nanmax(h[:, j - p["pre"]:j], 1) if side > 0 else np.nanmin(l[:, j - p["pre"]:j], 1))[new]
        arm = (s >= 0) & (q < 0) & (j > s) & (j <= s + p["mss"])
        brk = (c[:, j] > ref) if side > 0 else (c[:, j] < ref)
        mq = arm & brk
        q[mq] = j
        gapok = (l[:, j] > h[:, j - 2]) if side > 0 else (h[:, j] < l[:, j - 2])
        fv[mq] = gapok[mq]
        gap[mq] = (h[:, j - 2] if side > 0 else l[:, j - 2])[mq]
        s[(s >= 0) & (q < 0) & (j > s + p["mss"])] = -1
        touch = ((l[:, j] <= gap) if side > 0 else (h[:, j] >= gap))
        m = (q >= 0) & fv & (t < 0) & (j > q) & (j <= q + p["retr"]) & touch
        t[m] = j
    return q, t, gap


def d_absorb(A, p, j0, j1, side):
    """거래량 >= vol x 평균 이면서 봉 범위 <= rng x 평균(노력 대비 결과 작음) + 직전 abs_lb봉 이동 조건.
    side=+1: 하락 후(<= -move), side=-1: 상승 후(>= +move)."""
    h, l, c, v = A["h"], A["l"], A["c"], A["v"]
    n = len(c)
    dec = np.full(n, -1)
    lb = p["abs_lb"]
    rg = h - l
    for j in range(max(j0, lb), j1 + 1):
        vs = v[:, j] >= p["vol"] * np.nanmean(v[:, j - lb:j], 1)
        rs = rg[:, j] <= p["rng"] * np.nanmean(rg[:, j - lb:j], 1)
        mv = c[:, j] / c[:, j - lb] - 1
        cond = vs & rs & ((mv <= -p["move"]) if side > 0 else (mv >= p["move"]))
        _first(dec, cond, j)
    return dec


def d_spring(A, p, j0, j1, side):
    """박스(box봉, 폭 <= wmax) 하단 이탈 후 같은 봉 종가 복귀(Spring, side=+1) / 상단 이탈(Upthrust, -1)."""
    h, l, c = A["h"], A["l"], A["c"]
    n = len(c)
    dec = np.full(n, -1)
    bx = p["box"]
    for j in range(max(j0, bx + 3), j1 + 1):
        lo = np.nanmin(l[:, j - bx:j - 3], 1)
        hi = np.nanmax(h[:, j - bx:j - 3], 1)
        narrow = (hi - lo) / c[:, j - 4] <= p["wmax"]
        cond = narrow & ((l[:, j] < lo * (1 - p["m"])) & (c[:, j] > lo) if side > 0
                         else (h[:, j] > hi * (1 + p["m"])) & (c[:, j] < hi))
        _first(dec, cond, j)
    return dec


def d_drive(A, p, side):
    """장초 드라이브(0930 까지 open 대비 +-drive) -> 되돌림(고점-open 폭의 depth) -> 재개(종가>직전 고가). KR 전용."""
    h, l, c = A["h"], A["l"], A["c"]
    op = A["open"][:, 0]
    n = len(c)
    j30 = MI["0930"]
    move = c[:, j30] / op - 1
    on = (move >= p["drive"]) if side > 0 else (move <= -p["drive"])
    pb = np.full(n, -1)
    dec = np.full(n, -1)
    for j in range(MI["0935"], MI["1100"] + 1):
        if side > 0:
            pk = np.nanmax(h[:, :j + 1], 1)
            dep = (pk - c[:, j]) / (pk - op)
        else:
            pk = np.nanmin(l[:, :j + 1], 1)
            dep = (c[:, j] - pk) / (op - pk)
        _first(pb, on & (dep >= p["depth"]), j)
        res = (c[:, j] > h[:, j - 1]) if side > 0 else (c[:, j] < l[:, j - 1])
        m = on & (pb >= 0) & (dec < 0) & (j > pb) & res
        dec[m] = j
    return dec


def d_retest(A, p):
    """ORB 돌파(고가 > ORH x (1+bo)) 후 12봉 안 ORH 재접촉(저가 <= ORH x 1.001) + 종가 유지. KR 전용, 롱."""
    h, l, c = A["h"], A["l"], A["c"]
    n = len(c)
    orh = np.nanmax(h[:, :3], 1)
    b = np.full(n, -1)
    dec = np.full(n, -1)
    for j in range(3, MI["1100"] + 1):
        _first(b, c[:, j] > orh * (1 + p["bo"]), j)
        m = (b >= 0) & (dec < 0) & (j > b) & (j <= b + 12) & (l[:, j] <= orh * 1.001) & (c[:, j] > orh)
        dec[m] = j
    return dec


# ---- 셀 정의 (사전등록 §4) -------------------------------------------------------
# id -> (탐지기, 방향 +1 롱/-1 숏, 진입 종류, 청산 종류 a/b, 플래그)
LONG = {"long_only": True}
INFO = {"info_only": True}
KR_CELLS = {
    "K1a": ("sweep", 1, "next", "a", LONG), "K1b": ("sweep", 1, "next", "b", LONG),
    "K1s": ("sweep_s", -1, "next", "b", INFO),
    "K2ma": ("mss", 1, "next", "a", LONG), "K2mb": ("mss", 1, "next", "b", LONG),
    "K2fa": ("fvg", 1, "limit", "a", LONG), "K2fb": ("fvg", 1, "limit", "b", LONG),
    "K2s": ("mss_s", -1, "next", "b", INFO),
    "K3da": ("abs_d", 1, "next", "a", LONG), "K3db": ("abs_d", 1, "next", "b", LONG),
    "K3ua": ("abs_u", 1, "next", "a", LONG), "K3ub": ("abs_u", 1, "next", "b", LONG),
    "K4a": ("spring", 1, "next", "a", LONG), "K4b": ("spring", 1, "next", "b", LONG),
    "K4s": ("upthrust", -1, "next", "b", INFO),
    "K5a": ("drive", 1, "next", "a", LONG), "K5b": ("drive", 1, "next", "b", LONG),
    "K5s": ("drive_s", -1, "next", "b", INFO),
    "K6a": ("retest", 1, "next", "a", LONG), "K6b": ("retest", 1, "next", "b", LONG),
}
CR_CELLS = {
    "C1a": ("mss", 1, "next", "a", LONG), "C1b": ("mss", 1, "next", "b", LONG),
    "C1fa": ("fvg", 1, "limit", "a", LONG), "C1fb": ("fvg", 1, "limit", "b", LONG),
    "C1s": ("mss_s", -1, "next", "b", INFO),
    "C3a": ("sweep", 1, "next", "a", LONG), "C3b": ("sweep", 1, "next", "b", LONG),
    "C3s": ("sweep_s", -1, "next", "b", INFO),
    "C4da": ("abs_d", 1, "next", "a", LONG), "C4db": ("abs_d", 1, "next", "b", LONG),
    "C4ua": ("abs_u", 1, "next", "a", LONG), "C4ub": ("abs_u", 1, "next", "b", LONG),
    "C5a": ("spring", 1, "next", "a", LONG), "C5b": ("spring", 1, "next", "b", LONG),
    "C5s": ("upthrust", -1, "next", "b", INFO),
}


def detect(name, A, p, j0, j1):
    """반환 (dec, entry_col, entry_px). dec<0 이면 이벤트 없음."""
    c = A["c"]
    rows = np.arange(len(c))

    def nxt(dec):
        e = dec + 1
        ok = (dec >= 0) & (e < c.shape[1])
        px = np.full(len(c), np.nan)
        px[ok] = c[rows[ok], e[ok]]
        return dec, e, px

    if name == "sweep":
        return nxt(d_sweep(A, p, j0, j1, 1))
    if name == "sweep_s":
        return nxt(d_sweep(A, p, j0, j1, -1))
    if name in ("mss", "mss_s", "fvg"):
        side = -1 if name == "mss_s" else 1
        q, t, gap = d_mss_fvg(A, p, j0, j1, side)
        if name == "fvg":
            ok = t >= 0
            return np.where(ok, q, -1), np.where(ok, t, -1), np.where(ok, gap, np.nan)
        return nxt(np.where(q >= 0, q, -1))
    if name in ("abs_d", "abs_u"):
        return nxt(d_absorb(A, p, j0, j1, 1 if name == "abs_d" else -1))
    if name in ("spring", "upthrust"):
        return nxt(d_spring(A, p, j0, j1, 1 if name == "spring" else -1))
    if name in ("drive", "drive_s"):
        return nxt(d_drive(A, p, 1 if name == "drive" else -1))
    if name == "retest":
        return nxt(d_retest(A, p))
    raise KeyError(name)


# ---- 이벤트 -> 셀 관측 -----------------------------------------------------------
def make_obs(dec, e, px, exit_col, direction, c, idx, dates, cost_fn, ok_exit):
    """행 단위 이벤트를 (날짜, info, gross, cost, cost2) 로. idx = 시장지수 (n,T) 또는 gather 함수."""
    rows = np.arange(len(c))
    x = exit_col(e)
    ok = (dec >= 0) & (e >= 0) & np.isfinite(px) & ok_exit(e, x)
    r, ee, xx, pp = rows[ok], e[ok], x[ok], px[ok]
    gross = direction * (c[r, xx] / pp - 1) * 1e4
    mkt = direction * (idx(r, xx) / idx(r, ee) - 1) * 1e4
    good = np.isfinite(gross) & np.isfinite(mkt)
    r, gross, mkt, pp = r[good], gross[good], mkt[good], pp[good]
    c1, c2 = cost_fn(pp)
    df = pd.DataFrame({"d": dates[r], "i": (gross - mkt), "g": gross, "c": c1, "c2": c2}).groupby("d").mean()
    return [(d, row.i, row.g, row.c, row.c2) for d, row in df.iterrows()]


def judge(parts, bar, long_only=False, info_only=False):
    tr_i = parts["TRAIN"][0]
    s = np.sign(tr_i.mean()) if len(tr_i) else 0
    va_i, te_i = parts["VALID"][0], parts["TEST"][0]
    info = (abs(tstat(tr_i)) >= bar and len(va_i) and len(te_i)
            and np.sign(va_i.mean()) == s and np.sign(te_i.mean()) == s)
    g = np.concatenate([parts["VALID"][1], parts["TEST"][1]])
    c1 = np.concatenate([parts["VALID"][2], parts["TEST"][2]])
    c2 = np.concatenate([parts["VALID"][3], parts["TEST"][3]])
    net1, net2 = s * g - c1, s * g - c2
    capped = info_only or (long_only and s < 0)
    eco = bool(info) and not capped and len(g) and net1.mean() > 0 and net2.mean() > 0
    rob = eco and abs(tstat(s * g)) >= 2
    v = ("판정불가" if len(te_i) < 20 else "ROBUST" if rob else "ECONOMIC" if eco
         else "INFORMATION" if info else "REJECT")
    r = {"verdict": v, "train_sign": int(s), "t_train": round(tstat(tr_i), 2),
         "t_oos_dir": round(tstat(s * g), 2) if len(g) > 2 else None,
         "net1_oos_bp": round(float(net1.mean()), 2) if len(g) else None,
         "net2_oos_bp": round(float(net2.mean()), 2) if len(g) else None,
         "cost_bp": round(float(c1.mean()), 2) if len(g) else None}
    for k in ("TRAIN", "VALID", "TEST"):
        i, gg = parts[k][0], parts[k][1]
        r[k] = {"n": int(len(i)), "info_bp": round(float(i.mean()), 2) if len(i) else None,
                "gross_bp": round(float(gg.mean()), 2) if len(gg) else None, "t": round(tstat(i), 2)}
    return r


def family(cells, splitter, rng, flags):
    parts = {}
    for cid, ev in cells.items():
        p = {k: ([], [], [], []) for k in ("TRAIN", "VALID", "TEST")}
        for dt, i, g, c1, c2 in ev:
            b = p[splitter(dt)]
            b[0].append(i); b[1].append(g); b[2].append(c1); b[3].append(c2)
        parts[cid] = {k: tuple(np.array(x, float) for x in v) for k, v in p.items()}
    live = [c for c in parts if len(parts[c]["TRAIN"][0]) > 2]
    bar = null_bar([parts[c]["TRAIN"][0] for c in live], rng)
    return {"bar": round(bar, 2),
            "cells": {c: (judge(parts[c], bar, **flags[c]) if c in live else {"verdict": "판정불가"}) for c in parts}}


def neighbor_params(p):
    """한 번에 하나씩 x0.75 / x1.33 (정수 키는 반올림, 최소 1). 이웃 검증용(사전등록 §5)."""
    out = []
    for k, v in p.items():
        for f in (0.75, 1.33):
            q = dict(p)
            q[k] = max(1, int(round(v * f))) if k in INT_KEYS else v * f
            if q[k] != v:
                out.append((k, f, q))
    return out


# ---- KR ------------------------------------------------------------------------
class KR:
    def __init__(self):
        meta, A = load_grid()
        self.meta, self.A = meta, A
        self.dates = meta["date"].to_numpy()
        panel = pd.read_parquet(CACHE / "intraday_panel.parquet", columns=["date", "ticker", "day_high", "day_low"])
        panel["date"] = panel["date"].astype(str)
        panel = panel.sort_values(["ticker", "date"])
        panel["pdh"] = panel.groupby("ticker")["day_high"].shift(1)
        panel["pdl"] = panel.groupby("ticker")["day_low"].shift(1)
        m = meta.merge(panel[["date", "ticker", "pdh", "pdl"]], on=["date", "ticker"], how="left")
        self.A["lo"] = m["pdl"].to_numpy(float)[:, None]
        self.A["hi"] = m["pdh"].to_numpy(float)[:, None]
        self.A["open"] = meta["open_price"].to_numpy(float)[:, None]
        rel = self.A["c"] / self.A["c"][:, [0]]
        ix = pd.DataFrame(rel).groupby(self.dates).mean()
        self.I = ix.loc[self.dates].to_numpy()

    def cells(self, p, ids=None):
        A = self.A
        cache, out = {}, {}
        j0 = MI["0920"]
        for cid, (det, d, entry, ex, _) in KR_CELLS.items():
            if ids is not None and cid not in ids:
                continue
            if det not in cache:
                jr = (j0, MI["1400"])
                cache[det] = detect(det, A, p, *jr)
            dec, e, px = cache[det]
            exit_col = (lambda ee: ee + 6) if ex == "a" else (lambda ee: np.full(len(ee), J1520))
            out[cid] = make_obs(dec, e, px, exit_col, d, A["c"], lambda r, k: self.I[r, k], self.dates,
                                lambda pp: (KR_FIXED_BP + KR_TICK_K * tick_bp(pp), KR_FIXED_BP + KR_TICK_K2 * tick_bp(pp)),
                                lambda ee, xx: (ee <= J1520) & (xx <= J1520) & (xx > ee))
        return out, {k: int((v[0] >= 0).sum()) for k, v in cache.items()}


# ---- 크립토 ----------------------------------------------------------------------
HIST, ACT, TAIL, STEP = 54, 48, 54, 48          # 행 = [과거 54 | 결정 48 | 꼬리 54] = 156열


class Crypto:
    def __init__(self):
        syms, ser = [], {}
        for f in sorted(glob.glob(str(CRYPTO / "basis" / "1h" / "*_1h.parquet"))):
            sym = Path(f).name.replace("_1h.parquet", "")
            b = pd.read_parquet(f, columns=["time", "mark_open", "mark_high", "mark_low", "mark_close"])
            a = pd.read_parquet(CRYPTO / "activity" / f"{sym}_1h.parquet", columns=["time", "volume"])
            b["time"], a["time"] = pd.to_datetime(b["time"]), pd.to_datetime(a["time"])
            d = b.merge(a, on="time", how="left").drop_duplicates("time").set_index("time").sort_index().asfreq("1h")
            ser[sym] = d
            syms.append(sym)
        t0 = min(d.index[0] for d in ser.values())
        t1 = max(d.index[-1] for d in ser.values())
        self.axis = pd.date_range(t0, t1, freq="1h")
        ret = pd.DataFrame({s: d["mark_close"].reindex(self.axis).pct_change(fill_method=None) for s, d in ser.items()})
        self.I = (1 + ret.mean(axis=1).fillna(0)).cumprod().to_numpy()
        W = HIST + ACT + TAIL
        arrs = {k: [] for k in ("h", "l", "c", "v", "lo", "hi")}
        self.row_t0, self.row_sym = [], []
        for s, d in ser.items():
            d = d.reindex(self.axis)
            day = d.index.floor("D")
            pdl = d["mark_low"].groupby(day).min().shift(1).reindex(day).to_numpy()
            pdh = d["mark_high"].groupby(day).max().shift(1).reindex(day).to_numpy()
            cols = {"h": d["mark_high"].to_numpy(), "l": d["mark_low"].to_numpy(), "c": d["mark_close"].to_numpy(),
                    "v": d["volume"].to_numpy(), "lo": pdl, "hi": pdh}
            N = len(d)
            starts = np.arange(0, N - ACT + 1, STEP)          # 결정 구간 시작
            for k, a in cols.items():
                pad = np.concatenate([np.full(HIST, np.nan), a, np.full(TAIL + ACT, np.nan)])
                arrs[k].append(np.stack([pad[st:st + W] for st in starts]))
            self.row_t0.extend(self.axis[0] + pd.Timedelta(hours=int(st - HIST)) for st in starts)
            self.row_sym.extend([s] * len(starts))
        self.A = {k: np.vstack(v) for k, v in arrs.items()}
        self.row_pos = np.array([(t - self.axis[0]) / pd.Timedelta(hours=1) for t in self.row_t0], int)
        self.dates = np.array([(t + pd.Timedelta(hours=HIST)).strftime("%Y-%m-%d") for t in self.row_t0])
        self.ok_rows = np.isfinite(self.A["c"][:, HIST:HIST + ACT]).any(1)

    def idx(self, r, k):
        pos = np.clip(self.row_pos[r] + k, 0, len(self.I) - 1)
        return self.I[pos]

    def cells(self, p, ids=None):
        A = self.A
        cache, out = {}, {}
        for cid, (det, d, entry, ex, _) in CR_CELLS.items():
            if ids is not None and cid not in ids:
                continue
            if det not in cache:
                cache[det] = detect(det, A, p, HIST, HIST + ACT - 1)
            dec, e, px = cache[det]
            hold = 12 if ex == "a" else 24
            out[cid] = make_obs(dec, e, px, lambda ee, h=hold: ee + h, d, A["c"], self.idx, self.dates,
                                lambda pp: (np.full(len(pp), CR_COST), np.full(len(pp), CR_COST2)),
                                lambda ee, xx: (xx < A["c"].shape[1]))
        return out, {k: int((v[0] >= 0).sum()) for k, v in cache.items()}


def crypto_splitter(dt):
    y = int(str(dt)[:4])
    return "TRAIN" if y <= 2022 else ("VALID" if y == 2023 else "TEST")


# ---- 실행 ------------------------------------------------------------------------
def run_family(name, src, P, cells_def, splitter):
    rng = np.random.default_rng(SEED + (0 if name == "K" else 1))
    obs, counts = src.cells(P)
    flags = {c: cells_def[c][4] for c in cells_def}
    res = family(obs, splitter, rng, flags)
    res["event_counts"] = counts
    # 이웃 검증: ECONOMIC 셀만, 파라미터를 하나씩 x0.75/x1.33 (사전등록 §5). 이웃은 같은 셀의 판정 지표만 본다.
    for cid, r in res["cells"].items():
        if r.get("verdict") not in ("ECONOMIC", "ROBUST"):
            continue
        nb = []
        for k, f, q in neighbor_params(P):
            o, _ = src.cells(q, ids=[cid])
            rr = family({cid: o[cid]}, splitter, np.random.default_rng(SEED), {cid: cells_def[cid][4]})["cells"][cid]
            nb.append({"param": k, "x": f, "verdict": rr["verdict"], "net1_oos_bp": rr.get("net1_oos_bp"),
                       "train_sign": rr.get("train_sign")})
        pos = sum(1 for x in nb if x["net1_oos_bp"] is not None and x["net1_oos_bp"] > 0
                  and x["train_sign"] == r["train_sign"])
        r["neighbors"] = {"n": len(nb), "net_positive_same_sign": pos, "detail": nb,
                          "plateau": bool(nb) and pos / len(nb) >= 0.75}
        r["verdict_final"] = "ROBUST-PLATEAU" if r["neighbors"]["plateau"] and r["verdict"] in ("ECONOMIC", "ROBUST") \
            else "ECONOMIC-FRAGILE"
    return res


def show(fam, res):
    print(f"== {fam} bar |t|={res['bar']}  events {res['event_counts']}")
    for cid, r in res["cells"].items():
        if "TRAIN" not in r:
            print(cid, r["verdict"])
            continue
        print(f"{cid:5s} {r.get('verdict_final', r['verdict']):15s} s{r['train_sign']:+d} tTR {r['t_train']:6.2f} "
              f"n {r['TRAIN']['n']}/{r['VALID']['n']}/{r['TEST']['n']} info {r['TRAIN']['info_bp']}/"
              f"{r['VALID']['info_bp']}/{r['TEST']['info_bp']} gross {r['TRAIN']['gross_bp']}/{r['VALID']['gross_bp']}/"
              f"{r['TEST']['gross_bp']} cost {r['cost_bp']} netOOS {r['net1_oos_bp']}/{r['net2_oos_bp']}")


def main():
    out = {}
    kr = KR()
    sd = sorted(kr.meta["date"].unique())
    out["K"] = run_family("K", kr, KR_P, KR_CELLS, day_splitter(sd))
    out["K"]["span"] = [sd[0], sd[-1], len(sd)]
    show("K", out["K"])
    del kr
    cr = Crypto()
    out["C"] = run_family("C", cr, CR_P, CR_CELLS, crypto_splitter)
    show("C", out["C"])
    (HERE / "structure-phase4.json").write_text(json.dumps(out, ensure_ascii=False, indent=1, default=str),
                                                encoding="utf-8")


def selftest():
    # 호가단위 경계와 비용
    px = np.array([1000, 2000, 4999, 5000, 19999, 20000, 49999, 50000, 199999, 200000, 500000])
    assert np.allclose(tick_bp(px) * px / 1e4, [1, 5, 5, 10, 10, 50, 50, 100, 100, 500, 1000])
    assert abs(tick_bp(10000) - 10.0) < 1e-9                    # 1만원 종목 = 한 호가 10원 = 10bp

    def mk(n, T, **kw):
        base = np.full((n, T), 100.0)
        return {"h": base + 0.5, "l": base - 0.5, "c": base.copy(), "v": np.full((n, T), 1000.0),
                "lo": np.full((n, 1), 95.0), "hi": np.full((n, 1), 105.0), "open": np.full((n, 1), 100.0)}

    # 스윕: 저가가 PDL(95) x 0.999 아래로 가고 다음 봉에서 종가 복귀
    A = mk(2, 40)
    A["l"][0, 20] = 94.0; A["c"][0, 20] = 94.5; A["c"][0, 21] = 96.0
    dec = d_sweep(A, KR_P, 5, 35, 1)
    assert dec[0] == 21 and dec[1] == -1, dec                     # 복귀한 봉이 결정, 안 건드린 행은 없음
    A["c"][0, 21] = 94.0; A["c"][0, 22] = 94.0; A["c"][0, 23] = 94.0
    assert d_sweep(A, KR_P, 5, 35, 1)[0] == -1                    # 3봉 안에 복귀 못 하면 없음

    # 스윕 -> MSS -> FVG 재진입
    A = mk(1, 60)
    A["l"][0, 30] = 97.0                                          # 스윙 저점(99.5) 아래로 이탈
    A["c"][0, 30] = 99.0
    A["c"][0, 31] = 100.4; A["h"][0, 31] = 100.9                  # 직전 6봉 고가(100.5) 돌파 -> MSS
    q, t, gap = d_mss_fvg(A, KR_P, 25, 50, 1)
    assert q[0] == -1, q                                          # c31=100.4 < 직전 고가 100.5 -> MSS 없음
    A["c"][0, 31] = 101.0; A["h"][0, 31] = 101.5; A["l"][0, 31] = 100.6
    A["h"][0, 29] = 100.5
    q, t, gap = d_mss_fvg(A, KR_P, 25, 50, 1)
    assert q[0] == 31 and abs(gap[0] - A["h"][0, 29]) < 1e-9, (q, gap)
    A["l"][0, 32:] = 101.0
    A["l"][0, 34] = 100.4
    q, t, gap = d_mss_fvg(A, KR_P, 25, 50, 1)
    assert t[0] == 34, t                                          # 갭 위 가장자리 재터치 = 진입

    # 흡수: 거래량 4배 + 범위 작음 + 12봉 -1% 하락
    A = mk(2, 40)
    A["c"][0, :] = np.linspace(103, 100.9, 40)
    A["c"][0, 25] = 100.8
    A["v"][0, 25] = 4000
    A["h"][0, 25] = A["c"][0, 25] + 0.1; A["l"][0, 25] = A["c"][0, 25] - 0.1
    assert d_absorb(A, KR_P, 14, 35, 1)[0] == 25
    assert d_absorb(A, KR_P, 14, 35, 1)[1] == -1                  # 조건 없는 행

    # Spring: 좁은 박스(폭 1%) 하단 이탈 후 같은 봉 복귀
    A = mk(1, 50)
    A["l"][0, 40] = 99.0; A["c"][0, 40] = 99.8
    assert d_spring(A, KR_P, 30, 45, 1)[0] == 40
    A["c"][0, 40] = 98.9                                          # 복귀 못 함
    assert d_spring(A, KR_P, 30, 45, 1)[0] == -1

    # 이웃 파라미터
    nb = neighbor_params({"m": 0.001, "lb": 24})
    assert len(nb) == 4 and any(q["lb"] == 18 for _, _, q in nb) and any(q["lb"] == 32 for _, _, q in nb)
    print("selftest ok (14건)")


if __name__ == "__main__":
    selftest() if "--selftest" in sys.argv else main()
