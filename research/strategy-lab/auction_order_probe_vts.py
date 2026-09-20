#!/usr/bin/env python3
"""KIS 모의투자 동시호가 주문 1주 시험 — docs/control/단기규칙-모의실행-설계-2026-09-20.md §5.

질문 하나: **모의계좌가 동시호가 시간대 주문을 받고, 그 체결가가 공식 종가·시가와 정확히 일치하는가.**
O2b·O3u 모의 실행(종가 단일가 매수 → 익일 시가 단일가 매도)의 전제다. 실패하면 그 실험을 중단한다.

  python research/strategy-lab/auction_order_probe_vts.py buy               # 시험(dry-run): 아무것도 안 낸다
  python research/strategy-lab/auction_order_probe_vts.py buy --execute     # 평일 15:20~15:29 KST 시장가 매수 1주
  python research/strategy-lab/auction_order_probe_vts.py verify            # 15:30 이후: 매수 체결가 vs 공식 종가
  python research/strategy-lab/auction_order_probe_vts.py sell --execute    # 다음 영업일 08:30~08:59 시장가 매도 1주
  python research/strategy-lab/auction_order_probe_vts.py verify            # 09:00 이후: 매도 체결가 vs 공식 시가
  python research/strategy-lab/auction_order_probe_vts.py status            # 기록 보기
  python research/strategy-lab/auction_order_probe_vts.py --selftest        # 네트워크 없음

- **모의(VTS) 도메인만** 쓴다(KisVtsClient). 실계좌 경로가 없다.
- 수량은 **1주로 고정**이다(옵션 없음). 종목은 기본 005930(삼성전자), --symbol 로 바꿀 수 있다.
- 시간창 밖이면 --execute 여도 **주문을 내지 않고 끝난다**(정규장 주문이 섞이면 시험이 무효다). 강제 옵션 없음.
- 기록: data/paper/auction_test_vts.json (gitignore). 주문 거부 메시지도 그대로 남긴다 — 모의가 이 시간대를 안 받으면 그 자체가 결과다.
- 시가 매도는 **08:45 전후**를 권한다. 08:30~08:40 은 장전 시간외 종가 구간과 겹쳐 모의가 어떻게 다루는지 모른다(미확인).
"""
import argparse
import json
import os
import sys
from datetime import datetime, time, timedelta, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

STATE = HERE / "data" / "paper" / "auction_test_vts.json"
QTY = 1                                   # 고정 — 옵션으로 열지 않는다
DEFAULT_SYMBOL = "005930"
BUY_WINDOW = (time(15, 20, 0), time(15, 29, 59))     # 종가 동시호가
SELL_WINDOW = (time(8, 30, 0), time(8, 59, 59))      # 시가 동시호가
KST = timezone(timedelta(hours=9))


def now_kst():
    return datetime.now(KST)


def in_window(t, window):
    return window[0] <= t <= window[1]


def is_weekday(d):
    return d.weekday() < 5


def load_state():
    if STATE.exists():
        return json.loads(STATE.read_text(encoding="utf-8"))
    return {"note": "KIS 모의 동시호가 1주 시험 기록", "buy": None, "sell": None}


def save_state(s):
    STATE.parent.mkdir(parents=True, exist_ok=True)
    STATE.write_text(json.dumps(s, ensure_ascii=False, indent=1), encoding="utf-8")


def bars_from_output2(rows):
    """일봉 응답 → {'YYYY-MM-DD': {open, high, low, close}} (시세는 수정주가 0 = 원주가)."""
    out = {}
    for r in rows or []:
        d = r.get("stck_bsop_date") or ""
        if len(d) == 8 and r.get("stck_clpr") and r.get("stck_oprc"):
            out[f"{d[:4]}-{d[4:6]}-{d[6:8]}"] = {
                "open": float(r["stck_oprc"]), "high": float(r["stck_hgpr"]),
                "low": float(r["stck_lwpr"]), "close": float(r["stck_clpr"])}
    return out


def compare(fill_price, official_price):
    """정확히 일치해야 통과(호가단위 정수 가격). 차이는 bp 로 남긴다."""
    if fill_price is None or official_price is None:
        return {"pass": False, "diff_bp": None, "reason": "체결가 또는 공식가 없음"}
    diff = fill_price - official_price
    return {"pass": diff == 0, "diff": diff, "diff_bp": round(diff / official_price * 1e4, 2) if official_price else None}


def check_sell_allowed(state, today_str):
    """매도는 체결된 매수가 있고, 그 날짜보다 뒤이며, 아직 매도 기록이 없을 때만."""
    b = state.get("buy")
    if not b or not b.get("fill_qty"):
        return False, "체결된 매수 기록이 없다 — 먼저 buy --execute 와 verify"
    if state.get("sell"):
        return False, "이미 매도 기록이 있다"
    if today_str <= b["date"]:
        return False, "매수한 날 이후(다음 영업일)에만 매도한다"
    return True, ""


def load_vts_env():
    """VM 에서 저장소 밖 ~/collector-venv/.env 를 쓴다 — 없는 KIS_VTS_* 3개만 채운다."""
    p = Path.home() / "collector-venv" / ".env"
    if not p.exists():
        return
    for line in p.read_text(encoding="utf-8").splitlines():
        k, _, v = line.partition("=")
        k = k.strip()
        if k in ("KIS_VTS_APP_KEY", "KIS_VTS_APP_SECRET", "KIS_VTS_ACCOUNT_NO") and not os.environ.get(k):
            os.environ[k] = v.strip()


def client():
    load_vts_env()
    from engine.live.kisVtsClient import KisVtsClient
    return KisVtsClient()


def official_bar(c, symbol, date_str):
    from engine.live import kisVtsClient as m
    d = date_str.replace("-", "")
    _, resp = m._call("GET", m.BASE_URL + "/uapi/domestic-stock/v1/quotations/inquire-daily-itemchartprice",
                      f"일봉 조회 실패({symbol})", headers=c._headers("FHKST03010100"),
                      params={"FID_COND_MRKT_DIV_CODE": "J", "FID_INPUT_ISCD": symbol,
                              "FID_INPUT_DATE_1": d, "FID_INPUT_DATE_2": d,
                              "FID_PERIOD_DIV_CODE": "D", "FID_ORG_ADJ_PRC": "0"}, timeout=30)
    return bars_from_output2(resp.get("output2")).get(date_str)


def cmd_order(side, symbol, execute):
    n = now_kst()
    win = BUY_WINDOW if side == "BUY" else SELL_WINDOW
    state = load_state()
    print(f"현재 {n:%Y-%m-%d %H:%M:%S} KST · {side} {symbol} {QTY}주 시장가 · 허용 창 {win[0]:%H:%M}~{win[1]:%H:%M}")
    if not is_weekday(n):
        print("주말이다 — 주문하지 않는다.")
        return 1
    if not in_window(n.time(), win):
        print("시간창 밖이다 — 주문하지 않는다(정규장 주문이 섞이면 시험이 무효).")
        return 1
    today = str(n.date())
    if side == "BUY":
        prev = state.get("buy")
        if prev and prev.get("order_no"):            # 주문이 실제로 접수된 기록만 재시도를 막는다(접수 실패는 다시 시도할 수 있다)
            print("이미 접수된 매수 기록이 있다 — verify/sell 로 이어서 진행한다(중복 매수 금지).")
            return 1
    else:
        ok, why = check_sell_allowed(state, today)
        if not ok:
            print("매도 불가:", why)
            return 1
    if not execute:
        print("[dry-run] --execute 가 없어 주문하지 않는다.")
        return 0
    c = client()
    rec = {"date": today, "symbol": symbol, "side": side, "qty": QTY, "ordered_at": n.isoformat(timespec="seconds"),
           "order_no": None, "error": None, "fill_qty": None, "fill_price": None}
    try:
        resp = c.order_cash(side, symbol, QTY, ord_dvsn="01", ord_unpr="0")
        rec["order_no"] = resp["output"]["ODNO"]
        print("주문 접수 — 주문번호", rec["order_no"])
    except Exception as e:                       # 모의가 이 시간대를 안 받으면 그 메시지가 결과다
        rec["error"] = str(e)
        print("주문 실패(기록함):", e)
    state["buy" if side == "BUY" else "sell"] = rec
    save_state(state)
    return 0 if rec["order_no"] else 2


def cmd_verify():
    state = load_state()
    n = now_kst()
    c = None
    for leg, price_key, when in (("buy", "close", time(15, 40)), ("sell", "open", time(9, 5))):
        rec = state.get(leg)
        if not rec or not rec.get("order_no"):
            print(f"[{leg}] 주문 기록 없음" + (f" — 오류: {rec['error']}" if rec and rec.get("error") else ""))
            continue
        if rec.get("verdict"):
            print(f"[{leg}] 이미 판정됨: {rec['verdict']}")
            continue
        due = datetime.combine(datetime.fromisoformat(rec["date"]).date(), when, KST)
        if n < due:
            print(f"[{leg}] {due:%H:%M} 이후에 확인한다(공식 {'종가' if price_key == 'close' else '시가'} 확정 전).")
            continue
        c = c or client()
        st = c.get_order_status(rec["order_no"], rec["date"].replace("-", ""), QTY)
        bar = official_bar(c, rec["symbol"], rec["date"])
        official = bar[price_key] if bar else None
        rec["fill_qty"], rec["fill_price"] = st["filledQty"], st["avgPrice"]
        rec["official_" + price_key] = official
        rec["status"] = {k: st[k] for k in ("fullyFilled", "rejected", "pending")}
        cmp_ = compare(st["avgPrice"], official)
        rec["compare"] = cmp_
        rec["verdict"] = "PASS" if (st["fullyFilled"] and cmp_["pass"]) else "FAIL"
        print(f"[{leg}] {rec['verdict']} · 체결 {st['filledQty']}주 @ {st['avgPrice']} · 공식 {price_key} {official} · 차이 {cmp_.get('diff')} ({cmp_.get('diff_bp')}bp)"
              f" · 상태 {rec['status']}")
    save_state(state)
    b, s = state.get("buy"), state.get("sell")
    if b and s and b.get("verdict") and s.get("verdict"):
        ok = b["verdict"] == "PASS" and s["verdict"] == "PASS"
        print("\n== 1단계 시험 결과:", "통과 — 설계 §5 의 다음 단계로" if ok else "실패 — 이 실험을 중단하고 사유를 문서화한다(설계 §5, 새 GO 없이 대체 체결 방식으로 가지 않는다)")
    return 0


def cmd_status():
    print(json.dumps(load_state(), ensure_ascii=False, indent=1))
    return 0


def selftest():
    ok = True

    def check(n, c):
        nonlocal ok
        print(("PASS " if c else "FAIL ") + n)
        ok = ok and bool(c)

    check("매수 창 15:20~15:29:59", in_window(time(15, 20), BUY_WINDOW) and in_window(time(15, 29, 59), BUY_WINDOW)
          and not in_window(time(15, 19, 59), BUY_WINDOW) and not in_window(time(15, 30), BUY_WINDOW))
    check("매도 창 08:30~08:59:59", in_window(time(8, 30), SELL_WINDOW) and not in_window(time(9, 0), SELL_WINDOW))
    check("평일 판별", is_weekday(datetime(2026, 9, 21)) and not is_weekday(datetime(2026, 9, 20)))
    check("일치 = PASS(bp 0)", compare(70000.0, 70000.0) == {"pass": True, "diff": 0.0, "diff_bp": 0.0})
    check("불일치 = FAIL, bp 기록", (lambda r: (not r["pass"]) and r["diff_bp"] == 14.29)(compare(70100.0, 70000.0)))
    check("체결가 없음 = FAIL", not compare(None, 70000.0)["pass"])
    rows = [{"stck_bsop_date": "20260918", "stck_oprc": "70000", "stck_hgpr": "71000", "stck_lwpr": "69500", "stck_clpr": "70500"},
            {"stck_bsop_date": "", "stck_clpr": "1"}]
    b = bars_from_output2(rows)
    check("일봉 파싱(시가·종가)", b == {"2026-09-18": {"open": 70000.0, "high": 71000.0, "low": 69500.0, "close": 70500.0}})
    st = {"buy": {"date": "2026-09-21", "fill_qty": 1}, "sell": None}
    check("매도: 다음 영업일 이후만", check_sell_allowed(st, "2026-09-22")[0] and not check_sell_allowed(st, "2026-09-21")[0])
    check("매도: 매수 기록 없으면 불가", not check_sell_allowed({"buy": None, "sell": None}, "2026-09-22")[0])
    check("매도: 이미 매도했으면 불가", not check_sell_allowed({"buy": st["buy"], "sell": {"x": 1}}, "2026-09-22")[0])
    check("수량은 1주 고정", QTY == 1)
    print("ALL PASS" if ok else "FAILED")
    return 0 if ok else 1


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", nargs="?", choices=["buy", "sell", "verify", "status"])
    ap.add_argument("--execute", action="store_true")
    ap.add_argument("--symbol", default=DEFAULT_SYMBOL)
    ap.add_argument("--selftest", action="store_true")
    a = ap.parse_args()
    if a.selftest:
        sys.exit(selftest())
    if not a.cmd:
        ap.error("buy | sell | verify | status")
    sys.exit({"buy": lambda: cmd_order("BUY", a.symbol, a.execute), "sell": lambda: cmd_order("SELL", a.symbol, a.execute),
              "verify": cmd_verify, "status": cmd_status}[a.cmd]())


if __name__ == "__main__":
    main()
