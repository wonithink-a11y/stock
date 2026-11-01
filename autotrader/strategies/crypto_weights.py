"""크립토 목표 비중 — 업비트 여러 코인을 정한 비중으로 들고 가고, 어긋나면 되맞춘다
(설계 docs/control/크립토-목표비중-전략-설계-2026-11-01.md). **신호가 없고 수익을 주장하지 않는다.**

★ 이 전략이 **직접 체결한 수량만** 센다 — 계좌에 따로 가진 같은 코인은 보지도 팔지도 않는다(`coinbase_premium` 과 같은 방식).
   주문의 원장 행(clientId)을 다음 실행에서 찾아 업비트 체결량을 읽은 뒤에만 보유·현금이 바뀐다.
   dry-run·위험 검사 거부로 주문이 안 나갔으면 원장 행이 없으니 보유도 안 변한다(계획만 기록에 남는다).
★ 비중은 `capital_krw`(이 전략이 쓰는 자본) 기준이다. 계좌 전체 원화가 아니다.

params(프로필):
    weights          {"KRW-BTC": 0.5, "KRW-ETH": 0.3, "KRW-XRP": 0.2} — 합 ≤ 1(나머지는 원화로 둔다)
    capital_krw      이 전략의 자본(원, ≥ 5,000)
    band_pct         목표 대비 허용 오차(%p, 기본 5.0) — 안쪽이면 건드리지 않는다
    max_order_krw    한 주문의 최대 금액(원, 기본 capital_krw 의 20%) — 처음 진입을 며칠에 나눠 들어간다
    other_weight     '기타' 묶음 비중(0~1, 기본 0) — weights 합 + other_weight ≤ 1
    other_candidates 기타 후보 코인 목록(["KRW-XRP", ...]) — **서버 프로필이 정한다**. 이 안에서만 고르고, 프로필 symbol_allowlist 에도 있어야 주문이 나간다
    other_top_n      기타에 담을 코인 수(기본 5) — 후보 중 24시간 거래대금 상위(투자유의 제외), **월 1회만 갱신**
    other_mode       기타 안의 비중: "equal"(균등, 기본) | "volume"(24시간 거래대금에 비례 — 선정 시점 값을 그 달 동안 고정)
                     '한 바구니'(권고): weights {} · other_weight 1.0 · other_mode "volume" — BTC·ETH 가 거래대금이 커서 자연히 큰 비중
    market           거래소 시장 이름 "UPBIT"(기본) | "BITHUMB" — 프로필 broker/markets 와 같아야 한다
    web_weights      true 면 웹에서 바꾼 비율(weights_override.json)이 weights·other_weight 를 덮는다
허용 종목·한도·킬 스위치는 엔진이 강제한다(프로필 symbol_allowlist 에 weights 의 코인이 모두 있어야 주문이 나간다).
"""
from __future__ import annotations

import math
import re
from typing import Dict, List

from ..engine import Ledger
from ..models import Intent
from ..strategy import Strategy

TAG = "cw"
MIN_ORDER_KRW = 5_000
_SYM = re.compile(r"^KRW-[A-Z0-9]{2,10}$")


def _floor8(q: float) -> float:
    return math.floor(q * 1e8) / 1e8


def parse_params(pr: dict) -> dict:
    """설정 검사 — 틀리면 ValueError(엔진이 '전략 오류'로 멈추고 주문은 안 낸다)."""
    w = pr.get("weights")
    if not isinstance(w, dict):                  # 빈 {} 는 허용 — 웹에서 전부 0%(원화로)로 둔 경우: 새로 사지 않고 자기 보유만 정리한다
        raise ValueError("params.weights 가 필요하다 — 예 {\"KRW-BTC\": 0.5}")
    for s, v in w.items():
        if not _SYM.match(str(s)):
            raise ValueError(f"weights 의 종목은 KRW-XXX 형식: {s!r}")
        if isinstance(v, bool) or not isinstance(v, (int, float)) or not 0 < v <= 1:
            raise ValueError(f"weights 의 비중은 0 초과 1 이하 숫자: {s}={v!r}")
    if sum(w.values()) > 1.0 + 1e-9:
        raise ValueError(f"weights 의 합이 1 을 넘는다: {sum(w.values()):.3f}")
    cap = pr.get("capital_krw")
    if isinstance(cap, bool) or not isinstance(cap, (int, float)) or cap < MIN_ORDER_KRW:
        raise ValueError(f"params.capital_krw 가 필요하다(≥ {MIN_ORDER_KRW:,}원)")
    band = float(pr.get("band_pct", 5.0))
    if band < 0:
        raise ValueError("band_pct 는 0 이상")
    mo = float(pr.get("max_order_krw", cap * 0.2))
    if mo < MIN_ORDER_KRW:
        raise ValueError(f"max_order_krw 는 {MIN_ORDER_KRW:,}원 이상")
    ow = pr.get("other_weight", 0) or 0
    if isinstance(ow, bool) or not isinstance(ow, (int, float)) or not 0 <= ow <= 1:
        raise ValueError(f"other_weight 는 0~1 숫자: {ow!r}")
    if sum(w.values()) + ow > 1.0 + 1e-9:
        raise ValueError(f"weights 합 + other_weight 가 1 을 넘는다: {sum(w.values()) + ow:.3f}")
    cands = pr.get("other_candidates") or []
    if not isinstance(cands, list) or any(not _SYM.match(str(c)) for c in cands):
        raise ValueError("other_candidates 는 KRW-XXX 목록")
    if ow > 0 and not cands:
        raise ValueError("other_weight > 0 이면 other_candidates(서버가 정한 후보 코인)가 필요하다")
    top_n = int(pr.get("other_top_n", 5))
    if top_n < 1:
        raise ValueError("other_top_n 은 1 이상")
    market = pr.get("market", "UPBIT")
    if market not in ("UPBIT", "BITHUMB"):
        raise ValueError('market 은 "UPBIT" 또는 "BITHUMB"')
    mode = pr.get("other_mode", "equal")
    if mode not in ("equal", "volume"):
        raise ValueError('other_mode 는 "equal" 또는 "volume"')
    return {"weights": {str(s): float(v) for s, v in w.items()}, "capital": float(cap), "band": band, "max_order": mo,
            "other": float(ow), "cands": [str(c) for c in cands], "top_n": top_n, "mode": mode, "market": market}


class CryptoWeights(Strategy):
    name = "crypto_weights"
    markets = ["UPBIT", "BITHUMB"]

    def decide(self, ctx) -> List[Intent]:
        p = parse_params(ctx.params)
        weights, st, mk = p["weights"], ctx.state, p["market"]
        log: List[str] = []
        out: List[Intent] = []

        # 0) 자본 — 처음엔 capital_krw, 나중에 값을 바꾸면 차액만큼 현금이 늘고 준다
        if "cash" not in st:
            st["cash"], st["capital"], st["holdings"] = p["capital"], p["capital"], {}
        elif abs(p["capital"] - st.get("capital", p["capital"])) > 1e-9:
            st["cash"] += p["capital"] - st["capital"]
            log.append(f"자본 {st['capital']:,.0f} → {p['capital']:,.0f}원")
            st["capital"] = p["capital"]
        holdings: Dict[str, float] = st.setdefault("holdings", {})
        pending: Dict[str, dict] = st.setdefault("pending", {})

        # 1) 지난 실행이 낸 주문의 결과 — 원장(clientId)과 업비트 체결량으로 확인
        ours = {r["clientId"]: r for r in Ledger(ctx.state_dir).rows()
                if r.get("kind") == "order" and r.get("executed") and r.get("clientId")}
        for cid, pd_ in list(pending.items()):
            r = ours.get(cid)
            if r is None:
                log.append(f"{cid} 주문 기록 없음(dry-run 또는 거부) — 변화 없음")
                pending.pop(cid)
                continue
            f = ctx.order_fill(r["orderNo"], mk)
            if f["state"] in ("wait", "watch"):
                log.append(f"{cid} 아직 체결 대기 — 다음 실행에 다시 본다")
                continue
            sym, q, px, fee = pd_["symbol"], float(f["qty"]), float(f["price"] or 0), float(f.get("fee") or 0)
            if q > 0:
                if pd_["side"] == "BUY":
                    holdings[sym] = _floor8(holdings.get(sym, 0.0) + q)
                    st["cash"] -= q * px + fee
                else:
                    holdings[sym] = _floor8(max(0.0, holdings.get(sym, 0.0) - q))
                    st["cash"] += q * px - fee
                log.append(f"{cid} 체결 {q:.8f} @ {px:,.0f}")
            else:
                ctx.notes.append(f"크립토 목표 비중: 주문 {r['orderNo']} 체결 0 — 변화 없음")
            pending.pop(cid)

        # 2) 아직 결과를 못 본 주문이 있으면 이번엔 새 주문을 내지 않는다(겹침 방지)
        if pending:
            log.append("대기 주문 있음 — 이번 실행은 새 주문 없음")
            return self._finish(st, ctx, log, out)

        # 3) 목표 — 고정 코인 + '기타'(후보 중 거래대금 상위 N, 월 1회 고정, 균등)
        targets: Dict[str, float] = dict(weights)
        if p["other"] > 0:
            picked = self._other_symbols(ctx, p, st, log)
            for s_, sh in picked.items():
                targets[s_] = targets.get(s_, 0.0) + p["other"] * sh
        for s_, q_ in holdings.items():                                # 목표에서 빠진 코인의 자기 보유는 비중 0 으로 정리
            if q_ > 0 and s_ not in targets:
                targets[s_] = 0.0
        prices: Dict[str, float] = {}
        for s_ in list(targets):
            try:
                prices[s_] = ctx.quote(s_, mk)
            except Exception:                                         # noqa: BLE001 — 시세를 못 얻는 코인(상폐 등)은 이번엔 건너뛴다
                ctx.notes.append(f"크립토 목표 비중: {s_} 시세를 못 읽어 건너뜀")
                targets.pop(s_)
        base = st["cash"] + sum(holdings.get(s_, 0.0) * prices[s_] for s_ in targets)
        if base <= 0:
            return self._finish(st, ctx, log, out)
        acct = ctx.positions(mk)
        acct_cash = ctx.cash(mk)
        sells, buys = [], []
        for s_, w in targets.items():
            px, held = prices[s_], holdings.get(s_, 0.0)
            diff = w * base - held * px
            if w > 0 and abs(diff) / base * 100 < p["band"]:
                continue
            amount = min(abs(diff), p["max_order"])
            if diff < 0:                                              # 초과 → 자기 수량까지만, 계좌에 그만큼 없으면 있는 만큼
                have = acct.get(s_).qty if acct.get(s_) else 0.0
                qty = _floor8(min(amount / px, held, have))
                if held > have + 1e-12:
                    ctx.notes.append(f"크립토 목표 비중: 기록 {s_} {held:.8f} 이 계좌 {have:.8f} 보다 많다 — 수동 확인 필요")
                if qty * px >= MIN_ORDER_KRW:
                    sells.append((s_, qty, px, w))
            elif w > 0:
                buys.append((s_, amount, px, w, diff))
        for s_, qty, px, w in sells:
            cid = f"{TAG}-{ctx.now:%Y%m%d%H}-{s_[4:]}-sell"
            out.append(Intent(s_, "SELL", qty, market=mk, order_type="market", client_id=cid,
                              reason=f"목표 {w:.0%} 초과분 정리"))
            pending[cid] = {"symbol": s_, "side": "SELL"}
            log.append(f"매도 {s_} {qty:.8f} (≈{qty * px:,.0f}원)")
        budget = min(st["cash"], acct_cash)                           # 팔아서 생길 현금은 다음 실행에 쓴다
        for s_, amount, px, w, diff in sorted(buys, key=lambda x: -x[4]):
            krw = math.floor(min(amount, budget))
            if krw < MIN_ORDER_KRW:
                continue
            budget -= krw
            cid = f"{TAG}-{ctx.now:%Y%m%d%H}-{s_[4:]}-buy"
            out.append(Intent(s_, "BUY", krw / px, market=mk, order_type="market", client_id=cid,
                              reason=f"목표 {w:.0%} 미달분 매수"))
            pending[cid] = {"symbol": s_, "side": "BUY"}
            log.append(f"매수 {s_} {krw:,.0f}원")
        return self._finish(st, ctx, log, out)

    @staticmethod
    def _other_symbols(ctx, p: dict, st: dict, log: List[str]) -> Dict[str, float]:
        """'기타' 코인 → 비중(합 1) — 달이 바뀌었거나 아직 없을 때만 다시 고른다(매일 바뀌면 불필요한 매매가 생긴다).
        후보 중 고정 코인 제외 · 투자유의 제외 · 24시간 거래대금 상위 N. 비중은 균등 또는 선정 시점의 거래대금 비례(그 달 고정).
        조회가 실패하면 직전 목록을 유지한다."""
        month = f"{ctx.now:%Y-%m}"
        cur = st.get("other") or {}
        cands = [c for c in p["cands"] if c not in p["weights"]]
        if cur.get("month") == month and cur.get("shares") and cur.get("cands") == cands and cur.get("mode") == p["mode"]:
            return dict(cur["shares"])
        try:
            info = ctx.market_info(p["market"], cands)
        except Exception as e:                                        # noqa: BLE001
            ctx.notes.append(f"크립토 목표 비중: 기타 후보 시세 조회 실패({type(e).__name__}) — 직전 목록 유지")
            return dict(cur.get("shares") or {})
        ranked = sorted((c for c in cands if c in info and not info[c].get("warning")),
                        key=lambda c: (-float(info[c].get("value24h") or 0), c))
        picked = ranked[:p["top_n"]]
        if not picked:
            ctx.notes.append("크립토 목표 비중: 기타 후보 중 고를 코인이 없다(투자유의·시세 없음) — 기타 비중은 이번엔 원화로 둔다")
            return dict(cur.get("shares") or {})
        vals = {c: float(info[c].get("value24h") or 0) for c in picked}
        tot = sum(vals.values())
        shares = {c: (vals[c] / tot if p["mode"] == "volume" and tot > 0 else 1 / len(picked)) for c in picked}
        st["other"] = {"month": month, "symbols": picked, "shares": shares, "cands": cands, "mode": p["mode"]}
        log.append(f"기타 목록 갱신 {month}: " + ", ".join(f"{c[4:]} {shares[c]:.0%}" for c in picked))
        return shares

    @staticmethod
    def _finish(st, ctx, log, out):
        st.setdefault("log", []).append({"at": ctx.now.isoformat(), "cash": round(st["cash"]), "holdings": dict(st["holdings"]),
                                         "actions": log})
        st["log"] = st["log"][-200:]
        return out


STRATEGY = CryptoWeights
