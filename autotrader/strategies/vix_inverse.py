"""VIX 인버스 규칙(SVIX 또는 SVXY) — VIX 일봉 종가 ≥20 이면 매수, ≤16 이면 전량 매도, 20·25·30·35 처음 넘을 때 1/4 씩 분할.

규칙 상태 기계는 `scripts/vix-inverse-check.py` 의 `run()` 을 그대로 부른다(여기서 다시 짜지 않는다).
근거·한계: research/strategy-lab/findings/vix-level-product-era-results-2026-11.md — 사전등록 OOS 기준(p 0.071)을 통과하지 못한 규칙이다.

params(프로필 파일):
    symbol              "SVIX" | "SVXY"
    capital_usd         이 전략에 배정한 총액(달러). 분할 한 칸 = capital_usd / 4
    split               true = 수준 분할 · false = 한번에(진입 즉시 100%)
    join_current_cycle  false(기본) = 프로필을 만든 시점에 이미 진행 중인 사이클은 건너뛰고 다음 새 진입부터 시작
    limit_slack_pct     지정가 여유(기본 0.5) — 매수는 시세 위, 매도는 시세 아래로 이만큼
    qn_warn_days        면제(QN) 만료까지 이 일수 미만이면 알림 노트(기본 21). SVIX 만 확인 가능

계약:
  - 계좌가 정본이다. 보유 칸 수 = 보유 원가 / (capital_usd/4). 목표 칸 수보다 0.25 칸 이상 모자랄 때만 사고, 줄이는 것은 청산(전량 매도)뿐이다.
  - 신호는 **직전 마감된 미국 거래일**의 VIX 종가다. 실행 시점의 미완성 일봉은 버린다(야후는 장중 값을 일봉으로 준다).
  - 데이터가 낡았거나 정규장 밖이면 주문 없이 노트만 남긴다. QN 만료 임박은 **알림 노트만** — 매도를 막지 않는다.
  - 미체결 취소·재조회는 엔진이 먼저 한다. 같은 날 다시 돌려도 계좌 상태에서 같은 계획이 나온다(멱등).
"""
from __future__ import annotations

import datetime as dt
import importlib.util
from typing import List, Optional

from autotrader.config import REPO_ROOT
from autotrader.models import Intent
from autotrader.strategy import Context, Strategy

MIN_GAP = 0.25                  # 모자란 칸 수가 이보다 작으면 사지 않는다(부분체결·호가 단위 잔차)
MAX_STALE_BDAYS = 2             # 마지막 VIX 일봉이 미국 날짜보다 평일 기준 이만큼 넘게 낡으면 주문하지 않는다(휴장 하루 여유)
SESSION_ET = (dt.time(9, 35), dt.time(15, 30))   # 이 안에서만 주문 — 서머타임 전환으로 run_at 이 어긋나도 장외에 내지 않는다


def _chk():
    spec = importlib.util.spec_from_file_location("vix_inverse_check", REPO_ROOT / "scripts" / "vix-inverse-check.py")
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


def _vix_closes() -> List[tuple]:                       # 테스트가 바꿔 끼운다(네트워크 없이)
    import yfinance as yf
    x = yf.download("^VIX", period="3y", progress=False, auto_adjust=False)
    x.columns = x.columns.get_level_values(0)
    return [(d.date(), float(v)) for d, v in x["Close"].dropna().items()]


def _qn_posted() -> Optional[dt.date]:                  # 테스트가 바꿔 끼운다
    return _chk().qn_posted()


def _et(now: dt.datetime) -> dt.datetime:
    from zoneinfo import ZoneInfo
    return now.astimezone(ZoneInfo("America/New_York"))


def _bdays(a: dt.date, b: dt.date) -> int:
    """a 다음날부터 b 까지의 평일 수(b ≤ a 이면 0)."""
    return sum(1 for i in range(1, (b - a).days + 1) if (a + dt.timedelta(days=i)).weekday() < 5)


class VixInverse(Strategy):
    name = "vix_inverse"
    markets = ["US"]

    def decide(self, ctx: Context) -> List[Intent]:
        pr = ctx.params
        sym, capital = pr["symbol"], float(pr["capital_usd"])
        if sym not in ("SVIX", "SVXY"):
            raise ValueError(f"symbol 은 SVIX|SVXY: {sym!r}")
        chk = _chk()
        tranche_usd = capital / len(chk.LEVELS)
        et = _et(ctx.now)
        us_day = et.date()
        st = ctx.state

        closes = [(d, v) for d, v in _vix_closes() if d < us_day]        # 오늘(미완성) 일봉 제외
        if not closes:
            ctx.notes.append("VIX 일봉을 받지 못했다 — 주문 없음")
            return []
        last_day = closes[-1][0]
        if _bdays(last_day, us_day) > MAX_STALE_BDAYS:
            ctx.notes.append(f"VIX 마지막 일봉 {last_day} 이 낡았다(미국 {us_day}) — 주문 없음")
            return []
        try:
            (holding, n_rule), sig, info, _ = chk.run(closes)
        except SystemExit as e:                         # run() 은 VIX ≤16 인 날이 창에 없으면 SystemExit — 엔진이 못 잡는 예외라 바꾼다
            raise ValueError(f"VIX 상태 확정 불가: {e}") from None
        if not pr.get("split", True):
            n_rule = len(chk.LEVELS) if holding else 0

        pos = ctx.positions("US").get(sym)
        qty = pos.qty if pos else 0
        cost = (pos.qty * pos.avg_price) if pos else 0.0

        # 첫 실행에 이미 진행 중인 사이클이면 합류 여부를 정한다(기본: 건너뛴다). 건너뛰는 것은 그 사이클(진입일로 식별)뿐이다.
        if "skip_entry" not in st:
            st["skip_entry"] = str(info.get("entry_date")) if holding and qty == 0 and not pr.get("join_current_cycle", False) else None
        st["skip_cycle"] = bool(holding and st["skip_entry"] and str(info.get("entry_date")) == st["skip_entry"])
        n_target = 0 if st["skip_cycle"] else n_rule

        st.update({"lastBar": str(last_day), "lastVix": closes[-1][1], "signal": sig, "holding": holding,
                   "ruleTranche": n_rule, "targetTranche": n_target, "heldQty": qty, "skipCycle": st["skip_cycle"],
                   "runDate": str(us_day)})
        if st["skip_cycle"]:
            ctx.notes.append(f"VIX {closes[-1][1]:.1f} 보유 구간이나 진행 중 사이클({info.get('entry_date')} 진입)은 건너뛴다(join_current_cycle=false)")

        out: List[Intent] = []
        in_session = SESSION_ET[0] <= et.time() <= SESSION_ET[1]
        want_trade = (n_target == 0 and qty > 0) or (n_target > 0 and n_target - cost / tranche_usd >= MIN_GAP)
        if want_trade and not in_session:
            ctx.notes.append(f"정규장 밖(미국 동부 {et:%H:%M}) — 주문 없음. 다음 실행에서 계좌 기준으로 다시 계산한다")
            want_trade = False
        if want_trade:
            self._qn_note(ctx, chk, sym, pr)
            px = ctx.quote(sym, "US")
            slack = float(pr.get("limit_slack_pct", 0.5)) / 100
            if n_target == 0:
                out.append(Intent(sym, "SELL", qty, market="US", order_type="limit", limit_price=round(px * (1 - slack), 2),
                                  reason=f"VIX {closes[-1][1]:.1f}({last_day}) ≤16 청산 신호 전량"))
            else:
                lim = round(px * (1 + slack), 2)
                add = int((n_target - cost / tranche_usd) * tranche_usd // lim)
                if add > 0:
                    out.append(Intent(sym, "BUY", add, market="US", order_type="limit", limit_price=lim,
                                      reason=f"VIX {closes[-1][1]:.1f}({last_day}) {sig} 목표 {n_target}/{len(chk.LEVELS)}칸"))
        return out

    @staticmethod
    def _qn_note(ctx, chk, sym, pr):
        """면제 만료 임박 알림. 매도를 막지 않는다 — 노트만."""
        if sym != "SVIX":
            ctx.notes.append(f"{sym} 원천징수 면제(QN)는 이 출처로 확인 못 한다 — 증권사 PTP 목록 확인")
            return
        try:
            posted = _qn_posted()
        except Exception as e:                          # noqa: BLE001 — 확인 실패도 알린다(조용히 넘기지 않는다)
            ctx.notes.append(f"SVIX 면제(QN) 확인 실패: {e}"[:160])
            return
        left = (posted + dt.timedelta(days=92) - ctx.now.date()).days
        if left < int(pr.get("qn_warn_days", 21)):
            ctx.notes.append(f"SVIX 원천징수 면제(QN) 만료 D-{left}(공시 {posted}) — 매도금액의 10% 원천징수 가능, 증권사 공지 확인")


STRATEGY = VixInverse
