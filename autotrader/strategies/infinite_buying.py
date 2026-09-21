"""무한매수법(분할매수 사이클) — `research/strategy-lab/run_infinite_buying_daily.py` 의 vts 경로를 플러그인으로 옮긴 것.

계산은 **같은 엔진**(`infinite_buying_engine`)을 그대로 부른다 — 규칙을 여기서 다시 짜지 않는다.
규칙 값은 이 파일에 없다. 로컬 전용 규칙 파일(`params.rules_file`, 원작자 재배포 금지라 gitignore)에서만 온다.

params(프로필 파일):
    rules_file        규칙 JSON 경로(VM: /home/ubuntu/collector-venv/infbuy/_rules.local.json)
    tickers           ["TQQQ", "SOXL"]
    seed_usd          슬리브당 배정액(달러)
    splits            분할수 20|30|40 — 보유가 남은 채로 바꾸면 실행을 막는다(T 의 분모가 바뀐다)
    import_state_dir  (선택) 옛 러너의 상태 폴더. 이 전략에 그 종목 상태가 아직 없을 때 한 번만 T 를 이어받는다

러너와 같은 계약:
  - 미체결 취소 → (그 뒤에) 계좌 조회 → 재계획 → 재접수. 취소·재확인은 autotrader 엔진이 먼저 한다(US 정합).
  - 보유·평단은 **계좌가 정본**. T 는 브로커가 안 주므로 매수는 체결금액/직전 1회매수금, 매도는 남은 수량 비율로 잇는다.
  - 잔금 = min(배정액 − 이미 투입한 원가, 주문가능 외화).
  - 계획 기준은 마지막 완료 세션 종가(recent_bars 전체).
주문 유형: 모의투자(paper)는 LOC 를 못 받으므로 지정가로 낸다(러너 vts 와 같다 — 이 숫자는 전략 판정용이 아니다).
실전(live)은 LOC 그대로. **MOC(역전 첫날 매도)는 autotrader 에 없는 주문이라 건너뛰고 기록만 한다** — 실전에서는 규칙과 다르다.
"""
from __future__ import annotations

import json
import sys
from dataclasses import asdict
from pathlib import Path
from typing import List

from autotrader.config import REPO_ROOT
from autotrader.models import Intent
from autotrader.strategy import Context, Strategy

_LAB = REPO_ROOT / "research" / "strategy-lab"
if str(_LAB) not in sys.path:
    sys.path.insert(0, str(_LAB))


def _bars(ticker: str) -> List[dict]:                    # 테스트가 바꿔 끼운다(네트워크 없이)
    import run_infinite_buying_daily as R
    return R.recent_bars(ticker)


def _import_old(dir_: str, ticker: str) -> dict:
    """옛 러너의 <종목>_vts.json 에서 엔진 상태·lastUnit·splits 를 가져온다. 없으면 빈 dict."""
    p = Path(dir_).expanduser() / f"{ticker}_vts.json"
    if not p.exists():
        return {}
    d = json.loads(p.read_text(encoding="utf-8"))
    return {"state": d.get("state") or {}, "lastUnit": d.get("lastUnit"), "splits": d.get("splits"),
            "importedFrom": str(p), "importedLastDate": d.get("lastDate")}


class InfiniteBuying(Strategy):
    name = "infinite_buying"
    markets = ["US"]

    def decide(self, ctx: Context) -> List[Intent]:
        import infinite_buying_engine as E
        pr = ctx.params
        rules_path = Path(pr["rules_file"]).expanduser()
        seed, splits = float(pr["seed_usd"]), int(pr["splits"])
        live = ctx.mode == "live"
        book = ctx.state.setdefault("tickers", {})
        out: List[Intent] = []
        for tk in pr["tickers"]:
            st = book.get(tk)
            if st is None:
                st = _import_old(pr["import_state_dir"], tk) if pr.get("import_state_dir") else {}
                st.setdefault("state", {})
            prev = st.get("splits")
            if prev is not None and prev != splits and int(st["state"].get("qty") or 0) > 0:
                raise ValueError(f"{tk}: 분할수가 {prev} -> {splits} 로 바뀌었는데 보유가 남아 있다 — 사이클을 끝내고 바꾼다")
            r = E.Rules.load(rules_path, tk, splits, seed=seed)
            s = E.State(**{k: v for k, v in st["state"].items() if k in E.State.__dataclass_fields__})
            qty_before, cost_before = s.qty, s.cost

            pos = ctx.positions("US").get(tk)                 # 계좌가 정본
            s.qty = pos.qty if pos else 0
            s.cost = (pos.qty * pos.avg_price) if pos else 0.0
            last_unit = float(st.get("lastUnit") or 0.0)
            if s.qty > qty_before and last_unit > 0:
                s.t += max(0.0, s.cost - cost_before) / last_unit
            elif qty_before and s.qty < qty_before:
                s.t = s.t * (s.qty / qty_before)
            s.cash = max(0.0, min(seed - s.cost, ctx.cash("US", tk)))

            bars = _bars(tk)
            orders = E.plan_orders(s, r, [b["close"] for b in bars])
            skipped_moc = 0
            merged: dict = {}
            for side, kind, limit, q in orders:
                if limit is None or q <= 0:
                    skipped_moc += 1
                    continue
                otype = "loc" if (kind == "LOC" and live) else "limit"
                # 모의에선 LOC·LIMIT 이 둘 다 지정가가 되어 같은 가격이 겹칠 수 있다(T≈0 에서 별% = 기준%) —
                # 같은 방향·유형·가격은 한 주문으로 합친다(지정가라 체결 효과가 같고, 엔진 중복 검사에 안 걸린다).
                k = (side.upper(), otype, float(limit))
                prev_q, kinds = merged.get(k, (0, []))
                merged[k] = (prev_q + int(q), kinds + [kind])
            for (side, otype, limit), (q, kinds) in merged.items():
                out.append(Intent(tk, side, q, market="US", order_type=otype, limit_price=limit,
                                  reason=f"무한매수 {'+'.join(kinds)} T {s.t:.2f}"))
            st.update({"state": asdict(s), "lastUnit": E.unit_amount(s, r), "splits": splits,
                       "lastDate": bars[-1]["date"] if bars else None, "skippedMOC": skipped_moc})
            book[tk] = st
        return out


STRATEGY = InfiniteBuying
