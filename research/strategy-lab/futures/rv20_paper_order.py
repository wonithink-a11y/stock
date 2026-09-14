#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""RV20 sizing 규칙(동결, futures-rv20-sizing-rule-freeze-2026-09-13.md,
Rule B: Q5->0x) 신호를 KIS 모의투자 선물 계좌에 실제로 반영하는 오케스트레이션.

절차(전부 이 순서를 지킨다 - 순서를 바꾸지 않는다):
1. rv20_sizing_paper_signal.compute_today_signal() - 동결 규칙 그대로,
   네트워크 없이 목표 익스포저(0/1x)를 계산.
2. KIS 계좌 잔고 조회(읽기 전용) - 현재 보유 계약 수 확인.
3. 전광판에서 오늘 front-month 계약 코드를 조회(읽기 전용).
4. 목표 계약수 - 현재 보유 = 주문 수량. 0이면 아무 것도 안 한다.
5. **기본값은 항상 dry-run**이다 - 실제 주문은 `--confirm-live`를
   명시적으로 줘야만 나간다.
6. `--confirm-live`가 있어도 `rv20_automation_enabled.json`의 `enabled`가
   false면 주문을 내지 않는다(dry-run으로 강등, 이유를 출력) - VM
   자동실행(deploy/rv20-futures-paper-order.timer)이 매일 이 스크립트를
   `--confirm-live`로 부르지만, 이 파일이 꺼져 있으면 아무 일도 안
   일어난다. 이 파일은 저장소에 커밋돼 있어 GitHub 웹 편집이나
   `.github/workflows/rv20-futures-automation-toggle.yml`(Actions 탭)로
   켜고 끈다 - VM은 매 실행 전 `git pull`로 최신값을 그대로 읽는다.

    python rv20_paper_order.py --capital 250000000                # dry-run(기본)
    python rv20_paper_order.py --capital 250000000 --confirm-live  # 실제 주문(enabled=true일 때만)
"""
import argparse
import json
import os
import sys
from datetime import datetime, timezone, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

ENABLED_FLAG_PATH = Path(__file__).resolve().parent / "rv20_automation_enabled.json"
# Overview "RV20 선물" 서브탭이 읽는 스냅샷 - 홈 디렉터리 격리(다른 실계좌
# 파일들과 같은 원칙, 절대 git에 안 올라간다). ★ 선물 잔고조회(output2) 필드
# 이름은 이 저장소 어디서도 검증된 적이 없다(스톡 TR의 dnca_tot_amt류와
# 스키마가 다를 수 있음) - 임의로 재해석하지 않고 원문 그대로(summary)
# 통째로 남긴다. 화면 쪽도 필드명을 안다고 가정하지 않고 그대로 나열한다.
KST = timezone(timedelta(hours=9))
HOLDINGS_PATH = Path(os.environ.get("RV20_HOLDINGS_PATH") or (Path.home() / ".rv20-futures-holdings.json"))


def automation_enabled() -> bool:
    if not ENABLED_FLAG_PATH.exists():
        return False
    try:
        return bool(json.loads(ENABLED_FLAG_PATH.read_text(encoding="utf-8")).get("enabled", False))
    except (ValueError, OSError):
        return False

from rv20_sizing_paper_signal import compute_today_signal
from engine.live.kisVtsFuturesClient import KisVtsFuturesClient, KisVtsFuturesError

MULT = 250_000.0


def write_holdings_snapshot(positions, summary, held_qty, front):
    """Overview "RV20 선물" 서브탭용 스냅샷. summary(output2)는 필드명을
    검증한 적이 없어 그대로 통째로 남긴다 - held_qty·front(둘 다 이미 이
    스크립트가 검증해 쓰고 있는 값)만 별도 필드로 뽑아 화면이 최소한
    "몇 계약 보유 중인지"는 확실히 알 수 있게 한다. 쓰기 실패는 조용히
    넘어간다(홈 디렉터리 문제로 본 주문 로직까지 죽이지 않는다)."""
    try:
        payload = {
            "generatedAtKST": datetime.now(KST).isoformat(),
            "heldContracts": held_qty,
            "frontMonth": {"code": front.get("code"), "name": front.get("name"), "price": front.get("price")},
            "rawSummary": summary,
        }
        HOLDINGS_PATH.parent.mkdir(parents=True, exist_ok=True)
        HOLDINGS_PATH.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        try:
            os.chmod(HOLDINGS_PATH, 0o600)
        except Exception:
            pass
    except Exception as e:
        print(f"[경고] 잔고 스냅샷 쓰기 실패(주문 로직과 무관, 계속 진행): {e}")


def current_position_qty(positions):
    """잔고 output1에서 순보유수량 합계(선물은 매수/매도 각각 행이 올 수 있어
    부호 있는 수량으로 합산 - 필드명은 실제 응답에서 확인, hldg_qty 계열
    없으면 0으로 취급하지 않고 예외를 낸다(교훈57 - 모르는 건 0이 아니다)."""
    if not positions:
        return 0
    qty_keys = [k for k in positions[0] if "qty" in k.lower()]
    if not qty_keys:
        raise KisVtsFuturesError(
            f"잔고 응답에 수량 필드를 못 찾음 - 필드 목록 확인 필요: {list(positions[0].keys())}")
    total = 0
    for p in positions:
        for k in qty_keys:
            v = p.get(k)
            if v not in (None, ""):
                try:
                    total += int(v)
                except ValueError:
                    pass
                break
    return total


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--capital", type=float, required=True, help="이 실험에 배정한 자본(원)")
    ap.add_argument("--confirm-live", action="store_true", help="실제로 주문을 낸다(기본은 dry-run)")
    args = ap.parse_args()

    live_requested = args.confirm_live
    if live_requested and not automation_enabled():
        print(f"[자동실행 꺼짐] {ENABLED_FLAG_PATH.name}의 enabled=false - "
              f"--confirm-live를 받았지만 dry-run으로 강등한다.")
        print(f"켜려면: GitHub Actions 'rv20-futures-automation-toggle' 워크플로 실행"
              f" 또는 {ENABLED_FLAG_PATH} 직접 편집(enabled: true).\n")
        args.confirm_live = False

    print("=== 1) 동결 규칙 신호 계산 (네트워크 없음) ===")
    signal = compute_today_signal()
    print(f"기준일 {signal['asOfDate']}  percentile={signal['pctRv20Rolling252']:.3f}"
          f"  ->  목표 익스포저 {signal['targetWeight']}x")

    client = KisVtsFuturesClient()

    print("\n=== 2) 계좌 잔고 조회 (읽기 전용) ===")
    positions, summary = client.inquire_balance()
    held_qty = current_position_qty(positions)
    print(f"현재 보유 계약수: {held_qty}")

    print("\n=== 3) Front-month 계약 조회 (읽기 전용) ===")
    front = client.resolve_front_month()
    print(f"front: {front['name']} ({front['code']})  현재가 {front['price']}  "
          f"매도호가 {front['ask']}  매수호가 {front['bid']}  거래량 {front['volume']}")

    write_holdings_snapshot(positions, summary, held_qty, front)

    notional_per_contract = front["price"] * MULT
    target_notional = args.capital * signal["targetWeight"]
    target_qty = int(round(target_notional / notional_per_contract)) if notional_per_contract > 0 else 0
    delta = target_qty - held_qty

    print(f"\n=== 4) 목표 대비 차이 ===")
    print(f"배정자본 {args.capital:,.0f}원 / 계약당 명목가치 {notional_per_contract:,.0f}원"
          f"  ->  목표 계약수 {target_qty} (현재 {held_qty}, 차이 {delta:+d})")

    if delta == 0:
        print("\n조정 불필요 - 주문 없음.")
        return

    side = "BUY" if delta > 0 else "SELL"
    qty = abs(delta)
    # 즉시 체결 가능성을 높이려고 상대편 최우선호가를 지정가로 쓴다
    # (매수는 매도호가, 매도는 매수호가) - 시장가(NMPR_TYPE_CD=02) 지원
    # 여부가 모의투자에서 미검증이라 지정가로 우회하는 방식.
    limit_price = front["ask"] if side == "BUY" else front["bid"]

    print(f"\n=== 5) 주문 미리보기 ({'실주문' if args.confirm_live else 'DRY-RUN'}) ===")
    result = client.order(side, front["code"], qty, limit_price, dry_run=not args.confirm_live)
    print(f"side={side}  code={front['code']}  qty={qty}  limit_price={limit_price}"
          f"  (상대편 최우선호가 - 즉시체결 노림)")
    print("요청 바디:", result["requestBody"])
    if args.confirm_live:
        print("응답:", result.get("response", {}).get("msg1"))
        print("주문번호:", (result.get("response", {}).get("output") or {}).get("ODNO"))
    else:
        print("\n(dry-run - 아직 아무 것도 전송하지 않았다. --confirm-live를 붙이면 실제로 나간다.)")


if __name__ == "__main__":
    main()
