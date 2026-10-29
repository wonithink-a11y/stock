#!/usr/bin/env python3
"""코인베이스 프리미엄 C24 — 업비트 KRW-BTC 롱 모의 슬리브. 매시 1회 실행.
사전등록: findings/coinbase-premium-paper-sleeve-preregistration-2026-10.md

    python research/strategy-lab/run_coinbase_premium_paper.py             # dry-run(기본, 상태 안 씀)
    python research/strategy-lab/run_coinbase_premium_paper.py --execute   # 상태·원장 기록(모의 체결)
    python research/strategy-lab/run_coinbase_premium_paper.py --judge     # 청산 40건 전에는 거부
    python research/strategy-lab/run_coinbase_premium_paper.py --selftest  # 네트워크 없음

브로커는 UpbitPaperBroker(로컬 시뮬레이션)뿐이다 — 업비트 인증 메서드를 부르지 않아 키 없이 돈다. 실주문 경로가 없다.
z 는 연구 함수 futures/coinbase_premium.zscore 를 그대로 부른다(규칙을 다시 쓰지 않는다).

상태(VM): ~/collector-venv/cbprem-paper/ — state.json(차단 해제 시각·보유·마지막 처리 시각) · runs.jsonl · trades.jsonl.
★ state.json 을 지우면 첫 실행처럼 과거 창으로 차단을 다시 세운다(거래는 안 한다). trades.jsonl 은 판정 원장이라 지우지 않는다.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE / "futures"))
import coinbase_premium as cp  # noqa: E402  연구 규칙(동결본)
sys.path.insert(0, str(HERE.parent.parent))   # 저장소 루트 — autotrader.notify(텔레그램 전송·매매 방 고르기)
from autotrader.notify import send_telegram, trade_chat  # noqa: E402

H = pd.Timedelta(hours=1)
HOLD = pd.Timedelta(hours=24)
FETCH_HOURS = 800                 # z 창 720 + 여유
ZTH = cp.ZTH
MAX_ENTRY_DELAY_MIN = 30
NOTIONAL_KRW = 1_000_000
COST_BP = 10.0
MARKET = "KRW-BTC"
JUDGE_N, EXTEND_N = 40, 80
# 가상 청산(기록 전용, 사전등록 coinbase-premium-paper-shadow-exits) — 실제 슬리브 규칙·판정과 무관
SHADOWS = {"T48": ("time", 48), "T72": ("time", 72), "Zm0.5": ("z", -0.5)}
SHADOW_MAX_H = 72
DEFAULT_DIR = os.path.expanduser("~/collector-venv/cbprem-paper")

for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(errors="replace")
    except Exception:
        pass


# ---------- 시세 (공개 엔드포인트만) ----------
def _get(url, params=None):
    import requests
    for k in range(5):
        try:
            r = requests.get(url, params=params, timeout=30)
            if r.status_code == 200:
                return r.json()
        except requests.RequestException:
            pass
        time.sleep(2 ** k)
    raise RuntimeError(f"시세 요청 실패: {url}")


def fetch_coinbase(T: pd.Timestamp) -> pd.Series:
    """BTC-USD 1시간 봉 종가(봉 시작 시각 인덱스), [T−FETCH_HOURS, T−1h]."""
    out, t = {}, T - FETCH_HOURS * H
    while t < T:
        e = min(t + 300 * H, T)
        rows = _get("https://api.exchange.coinbase.com/products/BTC-USD/candles",
                    {"granularity": 3600, "start": f"{t:%Y-%m-%dT%H:%M:%SZ}", "end": f"{(e - H):%Y-%m-%dT%H:%M:%SZ}"})
        for ts, lo, hi, op, cl, vol in rows:
            ts = pd.Timestamp(ts, unit="s", tz="UTC")
            if t <= ts < e:                                   # 요청 구간 안만 (교훈81)
                out[ts] = float(cl)
        t = e
        time.sleep(0.15)
    return pd.Series(out, dtype=float).sort_index()


def fetch_binance(T: pd.Timestamp) -> pd.DataFrame:
    """BTCUSDT 1시간 봉 open·close, [T−FETCH_HOURS, T] — T 봉은 open 만 확정."""
    rows = _get("https://data-api.binance.vision/api/v3/klines",
                {"symbol": "BTCUSDT", "interval": "1h", "limit": 1000,
                 "startTime": int((T - FETCH_HOURS * H).timestamp() * 1000), "endTime": int(T.timestamp() * 1000)})
    df = pd.DataFrame({"open": [float(r[1]) for r in rows], "close": [float(r[4]) for r in rows]},
                      index=pd.to_datetime([int(r[0]) for r in rows], unit="ms", utc=True))
    return df[(df.index >= T - FETCH_HOURS * H) & (df.index <= T)]


# ---------- 규칙 ----------
def premium_z(cb_close: pd.Series, bn_close: pd.Series, T: pd.Timestamp) -> pd.Series:
    """연구와 같은 정의: P(t) = CB_close[t−1h] / BN_close[t−1h] − 1, z = cp.zscore(P)."""
    grid = pd.date_range(T - (FETCH_HOURS - 1) * H, T, freq="h")
    p = pd.Series(cb_close.reindex(grid - H).to_numpy() / bn_close.reindex(grid - H).to_numpy() - 1, index=grid)
    return cp.zscore(p), p


def scan_events(z: pd.Series, start: pd.Timestamp, blocked_until: pd.Timestamp | None) -> tuple[list, pd.Timestamp | None]:
    """start 이후 z 에서 사건을 찾는다. 사건이 나면 방향과 무관하게 +24h 차단(연구 events 의 차단)."""
    ev = []
    for t, v in z[z.index >= start].items():
        if not np.isfinite(v) or abs(v) < ZTH:
            continue
        if blocked_until is not None and t < blocked_until:
            continue
        ev.append((t, float(v)))
        blocked_until = t + HOLD
    return ev, blocked_until


# ---------- 상태 ----------
def _load(d: Path) -> dict:
    f = d / "state.json"
    return json.loads(f.read_text(encoding="utf-8")) if f.exists() else {}


def _append(d: Path, name: str, rec: dict):
    with open(d / name, "a", encoding="utf-8") as f:
        f.write(json.dumps(rec, ensure_ascii=False) + "\n")


def _ts(x):
    return pd.Timestamp(x) if x else None


def _kst(t) -> str:
    return pd.Timestamp(t).tz_convert("Asia/Seoul").strftime("%m-%d %H:%M")


def notify_trade_room(text: str, env=None, sender=None, log=print) -> bool:
    """매매 방(TELEGRAM_TRADE_CHAT_ID, 없으면 1:1 방)으로 보낸다. 실패해도 슬리브는 계속 — 원장이 정본이다."""
    env = os.environ if env is None else env
    token, chat = env.get("TELEGRAM_BOT_TOKEN"), trade_chat(env)
    if not token or not chat:
        log("[알림 생략] TELEGRAM_BOT_TOKEN 또는 방 ID 없음")
        return False
    try:
        (sender or send_telegram)(token, chat, text)
        return True
    except Exception as e:                       # noqa: BLE001 — send_telegram 이 토큰을 뺀 문구만 던진다
        log(f"[알림 실패] {e}")
        return False


def shadow_target(leg: dict, z: pd.Series, T: pd.Timestamp):
    """가상 다리가 닫힐 시각(아직 아니면 None). z 갈래는 신호 + 1h 이후 z ≤ 문턱인 첫 정시, 없으면 신호 + 72h."""
    sigT = _ts(leg["signalT"])
    kind, arg = SHADOWS[leg["rule"]]
    if kind == "time":
        t = sigT + arg * H
        return t if T >= t else None
    zz = z[(z.index >= sigT + H) & (z.index <= min(T, sigT + SHADOW_MAX_H * H))]
    hit = zz[zz <= arg]
    if len(hit):
        return hit.index[0]
    t = sigT + SHADOW_MAX_H * H
    return t if T >= t else None


def run(now: datetime, cb: pd.Series, bn: pd.DataFrame, broker, state_dir: Path, execute: bool, log=print,
        notifier=None) -> dict:
    T = pd.Timestamp(now).floor("h")
    delay_min = (pd.Timestamp(now) - T).total_seconds() / 60
    st = _load(state_dir)
    z, p = premium_z(cb, bn["close"], T)
    last = _ts(st.get("lastScanned"))
    first_run = last is None
    start = z.first_valid_index() if first_run else last + H
    blocked = _ts(st.get("blockedUntil"))
    events, blocked = scan_events(z, start, blocked) if start is not None else ([], blocked)
    rec = {"T": str(T), "runAt": str(pd.Timestamp(now)), "delayMin": round(delay_min, 1),
           "P_bp": None if pd.isna(p.get(T)) else round(float(p[T]) * 1e4, 2),
           "z": None if pd.isna(z.get(T)) else round(float(z[T]), 3), "firstRun": first_run, "actions": []}
    pos = st.get("position")
    trades, msgs = [], []
    shadows, shadow_closed = list(st.get("shadows", [])), []
    _px = {}

    def cur():                                   # 한 실행에서 현재가는 한 번만 받는다
        if "p" not in _px:
            _px["p"] = float(broker.current_price(MARKET))
        return _px["p"]

    # 0) 가상 청산(기록 전용) — 실제 청산·진입과 무관
    still = []
    for leg in shadows:
        tgt = shadow_target(leg, z, T)
        if tgt is None:
            still.append(leg)
            continue
        px = cur()
        g = (px / leg["entryPrice"] - 1) * 1e4
        shadow_closed.append({**leg, "targetT": str(tgt), "exitAt": str(pd.Timestamp(now)), "exitPrice": px,
                              "hours": (tgt - _ts(leg["signalT"])) / H, "delayH": round((T - tgt) / H, 2),
                              "grossBp": round(g, 2), "netBp": round(g - COST_BP, 2)})
    shadows = still
    tag = "코인베이스 프리미엄 C24 · 모의(실주문 아님)"

    # 1) 청산 — 신호 시각 + 24h 이후 첫 실행
    if pos and T >= _ts(pos["signalT"]) + HOLD:
        px = cur()
        sigT = _ts(pos["signalT"])
        bo = bn["open"]
        bn_ret = (bo.get(sigT + HOLD, np.nan) / bo.get(sigT, np.nan) - 1) * 1e4
        gross = (px / pos["entryPrice"] - 1) * 1e4
        tr = {**pos, "exitAt": str(pd.Timestamp(now)), "exitPrice": px, "grossBp": round(gross, 2),
              "netBp": round(gross - COST_BP, 2), "binanceSameEventBp": None if np.isnan(bn_ret) else round(bn_ret, 2)}
        trades.append(tr)
        rec["actions"].append(f"청산 {gross - COST_BP:+.1f}bp(net)")
        msgs.append(("exit", f"💰 모의 청산 · {tag}\n{MARKET} @ {px:,.0f}원 (매수 {pos['entryPrice']:,.0f}원)\n"
                             f"수익 {gross:+.1f}bp · 수수료 뒤 {gross - COST_BP:+.1f}bp · 신호 {_kst(sigT)} KST"))
        pos = None

    # 2) 사건 처리
    for t, v in events:
        kind = "LONG" if v > 0 else "SHORT"
        if first_run and t < T:
            rec["actions"].append(f"초기 차단 seed {t:%m-%d %H}시 {kind}")
            continue
        if t < T:
            rec["actions"].append(f"놓침 {t:%m-%d %H}시 {kind} z={v:+.2f}(거래 없음, 차단만)")
            if kind == "LONG":
                msgs.append(("missed", f"⚠️ 놓친 롱 신호 · {tag}\n{_kst(t)} KST z={v:+.2f} — 그 시각 실행이 없어 매수하지 않았다(24시간 차단만)"))
            continue
        if kind == "SHORT":
            rec["actions"].append(f"숏 사건 z={v:+.2f}(거래 안 함, 24h 차단)")
        elif delay_min > MAX_ENTRY_DELAY_MIN:
            rec["actions"].append(f"롱 사건 z={v:+.2f} — 지연 {delay_min:.0f}분 > {MAX_ENTRY_DELAY_MIN}분, 진입 안 함")
            msgs.append(("late", f"⚠️ 롱 신호 지연 · {tag}\n{_kst(t)} KST z={v:+.2f} — 실행이 {delay_min:.0f}분 늦어 매수하지 않았다"))
        elif pos is not None:
            rec["actions"].append("롱 사건 — 보유 중(있을 수 없는 상태), 진입 안 함")
        else:
            px = cur()
            shadows += [{"signalT": str(t), "rule": r, "entryPrice": px} for r in SHADOWS]
            pos = {"signalT": str(t), "z": round(v, 3), "entryAt": str(pd.Timestamp(now)), "entryPrice": px,
                   "qty": NOTIONAL_KRW / px, "notionalKrw": NOTIONAL_KRW}
            rec["actions"].append(f"매수 {MARKET} {px:,.0f} z={v:+.2f}")
            msgs.append(("buy", f"🛒 모의 매수 · {tag}\n{MARKET} {NOTIONAL_KRW:,}원 @ {px:,.0f}원\n"
                                f"신호 {_kst(t)} KST z={v:+.2f} · 청산 예정 {_kst(t + HOLD)} KST"))

    if shadow_closed:
        rec["actions"].append("가상 청산 " + ", ".join(f"{x['rule']} {x['netBp']:+.1f}bp" for x in shadow_closed))
    rec["blockedUntil"] = str(blocked) if blocked is not None else None
    log(json.dumps(rec, ensure_ascii=False))
    if execute:
        state_dir.mkdir(parents=True, exist_ok=True)
        for tr in trades:
            _append(state_dir, "trades.jsonl", tr)
        for x in shadow_closed:
            _append(state_dir, "shadow.jsonl", x)
        _append(state_dir, "runs.jsonl", rec)
        # T 의 P 가 아직 없으면(코인베이스 봉 지연) T 를 처리 완료로 치지 않는다 — 다음 실행이 T 를 다시 본다(사건이면 '놓침'으로 남는다)
        done = T if rec["P_bp"] is not None else T - H
        new = {"lastScanned": str(done), "blockedUntil": rec["blockedUntil"], "position": pos, "shadows": shadows}
        (state_dir / "state.json").write_text(json.dumps(new, ensure_ascii=False, indent=1), encoding="utf-8")
        if notifier is not None:                 # 원장을 먼저 쓰고 보낸다 — 전송 실패가 기록을 막지 않는다
            if trades:
                n = len((state_dir / "trades.jsonl").read_text(encoding="utf-8").splitlines())
                msgs = [(k, m + (f"\n누적 청산 {n}건(판정은 {JUDGE_N}건에서 1회)" if k == "exit" else "")) for k, m in msgs]
            for _, m in msgs:
                notifier(m)
    return {"rec": rec, "trades": trades, "position": pos, "messages": [k for k, _ in msgs],
            "shadows_open": shadows, "shadow_closed": shadow_closed}


# ---------- 판정 ----------
def judge(state_dir: Path, force_count_only=False) -> dict:
    f = state_dir / "trades.jsonl"
    tr = [json.loads(x) for x in f.read_text(encoding="utf-8").splitlines()] if f.exists() else []
    n = len(tr)
    sf = state_dir / "shadow.jsonl"
    sh = [json.loads(x) for x in sf.read_text(encoding="utf-8").splitlines()] if sf.exists() else []
    if n < JUDGE_N or force_count_only:
        return {"closed": n, "judge": f"거부 — 청산 {n}건 < {JUDGE_N}건(사전등록 §3)",
                "shadow_closed_counts": {r: sum(1 for x in sh if x["rule"] == r) for r in SHADOWS}}
    use = tr[:EXTEND_N] if n >= EXTEND_N else tr[:JUDGE_N]
    net = np.array([t["netBp"] for t in use])
    t_ = float(net.mean() / (net.std(ddof=1) / np.sqrt(len(net))))
    if len(use) == JUDGE_N:
        v = "REJECT" if net.mean() <= 0 else ("KEEP 후보" if t_ >= 1.0 else "INCONCLUSIVE — 80건까지 연장")
    else:
        v = "KEEP 후보" if net.mean() > 0 and t_ >= 1.5 else "REJECT"
    gap = [t["grossBp"] - t["binanceSameEventBp"] for t in use if t.get("binanceSameEventBp") is not None]
    real = {t["signalT"]: t["netBp"] for t in use}
    shadow = {}
    for r in SHADOWS:                           # 기록 전용 — 같은 매수에서 (가상 − 실제 24h)
        d = np.array([x["netBp"] - real[x["signalT"]] for x in sh if x["rule"] == r and x["signalT"] in real])
        hrs = [x["hours"] for x in sh if x["rule"] == r and x["signalT"] in real]
        shadow[r] = {"n": int(len(d)), "diff_vs_24h_bp": round(float(d.mean()), 1) if len(d) else None,
                     "t": round(float(d.mean() / (d.std(ddof=1) / np.sqrt(len(d)))), 2) if len(d) > 2 and d.std(ddof=1) > 0 else None,
                     "avg_hours": round(float(np.mean(hrs)), 1) if hrs else None}
    return {"closed": n, "used": len(use), "net_mean_bp": round(float(net.mean()), 1), "t": round(t_, 2), "verdict": v,
            "record_upbit_minus_binance_bp": round(float(np.mean(gap)), 1) if gap else None,
            "record_shadow_exits": shadow}


# ---------- 시험 ----------
def selftest():
    import tempfile
    rng = np.random.default_rng(29)
    failed = 0

    def ok(c, label):
        nonlocal failed
        print(("  ok   " if c else "  FAIL ") + label)
        failed += 0 if c else 1

    T = pd.Timestamp("2026-11-02 05:00", tz="UTC")
    idx = pd.date_range(T - FETCH_HOURS * H, T, freq="h")
    bn_close = pd.Series(100 * np.exp(np.cumsum(rng.normal(0, 0.003, len(idx)))), index=idx)
    prem = rng.normal(0, 0.0004, len(idx))
    prem[-2] = 0.01                                            # T 에 끝나는 봉(T−1h)에서 프리미엄 급등 → z(T) ≫ 2
    cb = bn_close * (1 + prem)
    bn = pd.DataFrame({"open": bn_close.shift(1).bfill(), "close": bn_close})

    # 1) 연구 함수와 같은 정의: cp.premium 은 2018~2026-10 격자라 겹치는 구간으로 비교
    z, p = premium_z(cb, bn["close"], T)
    ref = pd.Series(cb.reindex(z.index - H).to_numpy() / bn_close.reindex(z.index - H).to_numpy() - 1, index=z.index)
    ok(np.allclose(p.dropna(), ref.dropna()) and np.allclose(z.dropna(), cp.zscore(ref).dropna()), "P·z 가 연구 정의와 같다")
    ok(z[T] > ZTH, f"T 의 z 가 문턱 위 ({z[T]:.1f})")

    # 2) 차단 규칙이 연구 events 와 같은 사건을 고른다(가격이 다 있을 때)
    zz = pd.Series(rng.normal(0, 1.3, 400), index=pd.date_range("2026-01-01", periods=400, freq="h", tz="UTC"))
    o = pd.Series(100.0, index=pd.date_range("2025-12-31", periods=500, freq="h", tz="UTC"))
    mine, _ = scan_events(zz, zz.index[0], None)
    ok([t for t, _ in mine] == list(cp.events(zz, o, 24).index), "차단 규칙 = 연구 events")

    class FakeBroker:
        def __init__(self, px):
            self.px = px

        def current_price(self, m):
            return self.px

    with tempfile.TemporaryDirectory() as d:
        d = Path(d)
        # 3) 첫 실행: 과거 사건은 차단 seed 만, T 의 롱 사건은 매수
        sent = []
        out = run(T.to_pydatetime().replace(minute=2), cb, bn, FakeBroker(1.0e8), d, execute=True, log=lambda *a: None,
                  notifier=sent.append)
        ok(len(sent) == 1 and "모의 매수" in sent[0] and "실주문 아님" in sent[0], "매수 알림 1통(모의 표시)")
        ok(out["position"] is not None and out["position"]["signalT"] == str(T), "지금 시각 롱 사건 → 매수")
        # 4) 같은 시각 재실행은 중복 매수 없음
        out2 = run(T.to_pydatetime().replace(minute=40), cb, bn, FakeBroker(1.0e8), d, execute=True, log=lambda *a: None)
        ok(not any("매수" in a for a in out2["rec"]["actions"]), "같은 시각 재실행에 중복 매수 없음")
        # 5) 24h 뒤 청산, net = gross − 10
        T2 = T + HOLD
        idx2 = pd.date_range(T2 - FETCH_HOURS * H, T2, freq="h")
        bc2 = bn_close.reindex(idx2).ffill().fillna(100.0)
        cb2 = bc2 * 1.0
        bn2 = pd.DataFrame({"open": bc2, "close": bc2})
        out3 = run(T2.to_pydatetime().replace(minute=3), cb2, bn2, FakeBroker(1.01e8), d, execute=True, log=lambda *a: None,
                   notifier=sent.append)
        ok(any("모의 청산" in m and "누적 청산 1건" in m for m in sent[1:]), "청산 알림에 누적 건수")
        ok(len(out3["trades"]) == 1 and abs(out3["trades"][0]["netBp"] - 90.0) < 1e-6, "24h 뒤 청산 net = gross − 10")
        ok(out3["position"] is None, "청산 뒤 보유 없음")
        ok("거부" in judge(d)["judge"], "40건 전 --judge 거부")

    with tempfile.TemporaryDirectory() as d:
        d = Path(d)
        # 6) 지연 > 30분이면 진입 안 함 · dry-run 은 아무것도 안 쓴다
        out = run(T.to_pydatetime().replace(minute=45), cb, bn, FakeBroker(1.0e8), d, execute=True, log=lambda *a: None)
        ok(out["position"] is None, "지연 45분 → 진입 안 함")
        d2 = d / "dry"
        sent2 = []
        run(T.to_pydatetime().replace(minute=2), cb, bn, FakeBroker(1.0e8), d2, execute=False, log=lambda *a: None,
            notifier=sent2.append)
        ok(sent2 == [], "dry-run 은 알림도 없다")
        ok(not d2.exists(), "dry-run 은 상태를 안 쓴다")

    with tempfile.TemporaryDirectory() as d:
        d = Path(d)
        # 7) 숏 사건은 거래하지 않고 차단만
        cbs = bn_close * (1 + np.where(np.arange(len(idx)) == len(idx) - 2, -0.01, prem))
        out = run(T.to_pydatetime().replace(minute=2), cbs, bn, FakeBroker(1.0e8), d, execute=True, log=lambda *a: None)
        ok(out["position"] is None and pd.Timestamp(out["rec"]["blockedUntil"]) == T + HOLD, "숏 사건 → 거래 없음·24h 차단")

    # 8) 가상 청산(기록 전용): 실제 매수 때 3갈래 열림 → 24h 실제 청산과 무관하게 각자 닫힘
    long_idx = pd.date_range(T - FETCH_HOURS * H, T + 80 * H, freq="h")
    bl = pd.Series(100 * np.exp(np.cumsum(rng.normal(0, 0.003, len(long_idx)))), index=long_idx)
    pl = rng.normal(0, 0.0004, len(long_idx))
    i0 = long_idx.get_loc(T - H)
    pl[i0 - 30:i0] = 0.0                       # 직전 하루는 평온하게 — 우연한 |z| ≥ 2 가 T 진입을 차단하지 않게
    pl[i0] = 0.01
    cbl = bl * (1 + pl)

    def at(k):
        Tk = T + k * H
        sl = slice(Tk - FETCH_HOURS * H, Tk)
        return Tk, cbl[sl], pd.DataFrame({"open": bl[sl], "close": bl[sl]})

    with tempfile.TemporaryDirectory() as d:
        d = Path(d)
        Tk, c_, b_ = at(0)
        r0 = run(Tk.to_pydatetime().replace(minute=2), c_, b_, FakeBroker(1.0e8), d, execute=True, log=lambda *a: None)
        ok(len(r0["shadows_open"]) == 3, "매수 때 가상 다리 3개")
        Tk, c_, b_ = at(24)
        z24, _ = premium_z(c_, b_["close"], Tk)
        hits = z24[(z24.index >= T + H) & (z24.index <= Tk) & (z24 <= -0.5)]
        r24 = run(Tk.to_pydatetime().replace(minute=2), c_, b_, FakeBroker(1.02e8), d, execute=True, log=lambda *a: None)
        ok(len(r24["trades"]) == 1, "실제 청산은 24h 그대로")
        zc = [x for x in r24["shadow_closed"] if x["rule"] == "Zm0.5"]
        ok(len(hits) == 0 or (len(zc) == 1 and zc[0]["targetT"] == str(hits.index[0])
                               and abs(zc[0]["delayH"] - (Tk - hits.index[0]) / H) < 1e-9), "Zm0.5 = z ≤ −0.5 첫 정시, 지연 기록")
        ok({x["rule"] for x in r24["shadows_open"]} >= {"T48", "T72"}, "T48·T72 는 24h 뒤에도 열려 있음")
        Tk, c_, b_ = at(48)
        r48 = run(Tk.to_pydatetime().replace(minute=2), c_, b_, FakeBroker(1.03e8), d, execute=True, log=lambda *a: None)
        t48 = [x for x in r48["shadow_closed"] if x["rule"] == "T48"]
        ok(len(t48) == 1 and t48[0]["hours"] == 48 and abs(t48[0]["netBp"] - 290.0) < 1e-6, "T48 은 48h 에 닫힘(+3% − 10bp)")
        Tk, c_, b_ = at(72)
        r72 = run(Tk.to_pydatetime().replace(minute=2), c_, b_, FakeBroker(0.99e8), d, execute=True, log=lambda *a: None)
        ok(not r72["shadows_open"] and any(x["rule"] == "T72" for x in r72["shadow_closed"]), "72h 에 남은 다리 모두 닫힘")
        rows = [json.loads(x) for x in (d / "shadow.jsonl").read_text(encoding="utf-8").splitlines()]
        ok(sorted(x["rule"] for x in rows) == ["T48", "T72", "Zm0.5"], "shadow.jsonl 에 3줄")
        jd = judge(d)
        ok("거부" in jd["judge"] and jd["shadow_closed_counts"] == {"T48": 1, "T72": 1, "Zm0.5": 1}, "40건 전 judge 는 가상도 건수만")
    zflat = pd.Series(0.0, index=pd.date_range(T, T + 80 * H, freq="h"))
    leg = {"signalT": str(T), "rule": "Zm0.5", "entryPrice": 1.0}
    ok(shadow_target(leg, zflat, T + 71 * H) is None and shadow_target(leg, zflat, T + 72 * H) == T + 72 * H,
       "z 가 안 내려오면 72h 에 닫힘")

    # 9) 알림 경로: 매매 방 우선 · 키 없으면 생략 · 전송 실패해도 예외 없음
    got = []
    ok(notify_trade_room("x", {"TELEGRAM_BOT_TOKEN": "t", "TELEGRAM_TRADE_CHAT_ID": "TR", "TELEGRAM_CHAT_ID": "DM"},
                         sender=lambda tk, ch, tx: got.append(ch), log=lambda *a: None) and got == ["TR"], "매매 방으로 보낸다")
    ok(not notify_trade_room("x", {}, log=lambda *a: None), "토큰 없으면 생략")

    def boom(*a):
        raise RuntimeError("telegram 전송 실패(URLError)")
    ok(not notify_trade_room("x", {"TELEGRAM_BOT_TOKEN": "t", "TELEGRAM_CHAT_ID": "DM"}, sender=boom, log=lambda *a: None),
       "전송 실패는 False(슬리브 계속)")

    print(f"\n{'FAILED' if failed else 'PASSED'} - {failed} failure(s)")
    return 1 if failed else 0


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--execute", action="store_true", help="상태·원장을 기록한다(모의 체결). 기본은 dry-run")
    ap.add_argument("--judge", action="store_true")
    ap.add_argument("--selftest", action="store_true")
    ap.add_argument("--state-dir", default=os.environ.get("CBPREM_PAPER_DIR", DEFAULT_DIR))
    a = ap.parse_args()
    d = Path(a.state_dir)
    if a.selftest:
        return selftest()
    if a.judge:
        print(json.dumps(judge(d), ensure_ascii=False, indent=1))
        return 0
    from engine.live.upbitPaperBroker import UpbitPaperBroker
    now = datetime.now(timezone.utc)
    T = pd.Timestamp(now).floor("h")
    run(now, fetch_coinbase(T), fetch_binance(T), UpbitPaperBroker(), d, execute=a.execute,
        notifier=notify_trade_room if a.execute else None)
    return 0


if __name__ == "__main__":
    sys.exit(main())
