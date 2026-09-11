"""backfill-paper-equity-history.py — 모의계좌 총평가액 이력을 체결내역으로
되살린다. ui/data/equity-history.json 의 **과거 구간**을 한 번 채우는 도구다.

왜 필요한가: build_ui_feed.py 가 하루 한 줄을 적기 시작한 게 2026-09-11 이고,
그 전은 아무도 안 적었다(교훈75). 그런데 이 계좌는 그보다 앞선 2026-09-04 에
첫 체결이 났다 - 벤치마크 비교에서 그 구간이 통째로 빈다.

되살릴 수 있는 이유는 **체결내역이 3개월치라 계좌의 전 생애를 덮기 때문**이다.
KIS 일별주문체결 + 일봉 종가 두 가지로 매일의 보유·평가액이 결정된다.

  보유[t]     = 체결 누적 (매수 - 매도)                    ← 체결내역
  순투입[t]   = 체결금액 누적 (매수 - 매도)                 ← 체결내역
  주식평가[t] = Σ 보유[t][종목] x 종가[종목][t]             ← 일봉
  총평가[t]   = K + 주식평가[t] - 순투입[t]

K 는 상수다(초기 예수금 - 누적 비용). **추정하지 않고 오늘 값으로 역산한다** -
K = 오늘 총평가 - 오늘 주식평가 + 오늘 순투입. 수수료·세금은 K 안에 흡수되므로
과거 구간이 그 차이(전체 회전율의 0.014% 수준)만큼만 어긋난다.

검증 세 가지를 실행할 때마다 찍는다. 통과가 정보를 주는 것들이다(교훈61·72):
  1. 체결 매수합  == 계좌 pchs_amt_smtl_amt      (체결내역이 완전한가)
  2. 재구성 보유   == 계좌 실제 보유수량          (독립 출처 두 개의 대조)
  3. 역산한 K      가 초기 입금액으로 말이 되는가 (사람이 본다)

2번이 어긋나면 체결내역이 잘렸거나(연속조회 실패) 3개월 창 밖에 거래가 있다는
뜻이다 - 그때는 쓰지 않는다. 부분 재구성을 전체인 척 쓰면 곡선이 조용히 틀린다.

  python scripts/backfill-paper-equity-history.py --dry-run
  python scripts/backfill-paper-equity-history.py
"""
import argparse
import json
import os
import sys
from collections import defaultdict
from datetime import datetime, timedelta, timezone

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(REPO, "research", "strategy-lab"))
OUT_PATH = os.path.join(REPO, "ui", "data", "equity-history.json")
KST = timezone(timedelta(hours=9))
LOOKBACK_DAYS = 90          # KIS 일별주문체결 조회 상한이 3개월이다


def reconstruct(executions, closes_by_symbol, anchor_total):
    """순수 함수 - 네트워크 없이 테스트된다.

    executions: list[{date, symbol, side, filledQty, amountKrw}] (체결분만)
    closes_by_symbol: {symbol: {date: close}}
    anchor_total: 오늘(=마지막 날) 계좌 총평가액

    반환: (rows, K). rows 는 날짜 오름차순 [{date, totalKrw, stockKrw, ...}].
    """
    by_date = defaultdict(list)
    for e in executions:
        by_date[e["date"]].append(e)
    if not by_date:
        return [], None

    dates = sorted({d for m in closes_by_symbol.values() for d in m}
                   if closes_by_symbol else by_date)
    dates = [d for d in dates if d >= min(by_date)]

    held = defaultdict(int)
    spent = 0
    snaps = []
    for d in dates:
        for e in by_date.get(d, []):
            sign = -1 if e["side"] == "SELL" else 1
            held[e["symbol"]] += sign * e["filledQty"]
            spent += sign * e["amountKrw"]
        stock = 0.0
        missing = 0
        for sym, qty in held.items():
            if qty <= 0:
                continue
            close = closes_by_symbol.get(sym, {}).get(d)
            if close is None:
                missing += 1          # 그날 거래정지 등 - 0 으로 세지 않는다
                continue
            stock += close * qty
        snaps.append({"date": d, "stock": stock, "spent": spent, "missing": missing})

    # K 를 오늘로 역산한다. 추정하지 않는다.
    last = snaps[-1]
    k = anchor_total - last["stock"] + last["spent"]
    rows = [{"date": s["date"],
             "totalKrw": round(k + s["stock"] - s["spent"]),
             "stockKrw": round(s["stock"]),
             "cashKrw": round(k - s["spent"]),
             "reconstructed": True}
            for s in snaps]
    return rows, k


def _merge(existing, rows):
    """이미 적힌 날짜는 건드리지 않는다 - 실측 기록이 재구성보다 우선이다."""
    have = {r["date"] for r in existing}
    merged = existing + [r for r in rows if r["date"] not in have]
    merged.sort(key=lambda r: r["date"])
    return merged


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true", help="파일을 쓰지 않고 결과만 출력")
    args = ap.parse_args()

    import engine.live.kisVtsClient as kis
    from engine.live.kisVtsClient import KisVtsClient

    # 130종목을 연속으로 치는 일회성 도구다. 유량 제한은 **계좌 단위**라
    # VM 의 10분 폴링과 겹치면 이 프로세스의 리미터로는 못 막는다
    # (test_kis_vts_balance_paging 의 EGW00201 주석 참고) - 간격을 넉넉히 두고
    # 재시도도 늘린다. 급할 일이 없는 백필이라 느려도 된다.
    kis._RATE_LIMITER.min_interval_sec = max(kis._RATE_LIMITER.min_interval_sec, 2.0)

    client = KisVtsClient()
    today = datetime.now(KST).date()
    start = today - timedelta(days=LOOKBACK_DAYS)

    holdings, _, eval_total, summary = client.inquire_balance(with_summary=True)
    anchor_total = float(eval_total)
    acct_qty = {h["pdno"]: int(h["hldg_qty"]) for h in holdings}

    rows_raw = client.list_executions(start.strftime("%Y%m%d"), today.strftime("%Y%m%d"))
    fills = [r for r in rows_raw if r["filledQty"] > 0]
    print(f"체결 {len(fills)}건 · 종목 {len({f['symbol'] for f in fills})}개 "
          f"· {min(f['date'] for f in fills)} ~ {max(f['date'] for f in fills)}")

    # 검증 1 - 체결내역이 완전한가
    buy_sum = sum(f["amountKrw"] for f in fills if f["side"] == "BUY")
    pchs = float(summary.get("pchs_amt_smtl_amt") or 0)
    sell_sum = sum(f["amountKrw"] for f in fills if f["side"] == "SELL")
    print(f"[검증1] 체결 매수합 {buy_sum:,} vs 계좌 매입금액합 {pchs:,.0f} "
          f"{'OK' if sell_sum == 0 and abs(buy_sum - pchs) < 1 else '— 매도가 있으면 이 등식은 성립 안 함(참고)'}")

    # 검증 2 - 재구성 보유 == 계좌 실제 보유 (독립 출처 둘)
    recon_qty = defaultdict(int)
    for f in fills:
        recon_qty[f["symbol"]] += (-1 if f["side"] == "SELL" else 1) * f["filledQty"]
    recon_qty = {k: v for k, v in recon_qty.items() if v}
    diff = {k: (recon_qty.get(k, 0), acct_qty.get(k, 0))
            for k in set(recon_qty) | set(acct_qty)
            if recon_qty.get(k, 0) != acct_qty.get(k, 0)}
    if diff:
        print(f"[검증2] ✗ 보유수량 불일치 {len(diff)}종목 - 체결내역이 잘렸거나 "
              f"3개월 창 밖 거래가 있다. 재구성을 쓰지 않는다.")
        for k, (a, b) in list(diff.items())[:10]:
            print(f"         {k}  재구성 {a}  계좌 {b}")
        sys.exit(1)
    print(f"[검증2] OK 보유 {len(recon_qty)}종목이 계좌와 수량까지 일치")

    symbols = sorted(recon_qty) + sorted(set(f["symbol"] for f in fills) - set(recon_qty))
    print(f"일봉 조회 {len(symbols)}종목 (약 {len(symbols) * 1.2 / 60:.1f}분)...")
    closes = {}
    for i, sym in enumerate(symbols, 1):
        closes[sym] = client.get_daily_closes(sym, start.strftime("%Y%m%d"),
                                               today.strftime("%Y%m%d"), retries=6)
        if i % 25 == 0:
            print(f"  {i}/{len(symbols)}")

    rows, k = reconstruct(fills, closes, anchor_total)
    if not rows:
        print("재구성할 것이 없다")
        return
    print(f"[검증3] 역산한 K(초기 예수금 - 누적비용) = {k:,.0f}")
    print(f"        오늘 총평가 {anchor_total:,.0f} · 순투입 {buy_sum - sell_sum:,}")
    miss = sum(1 for r in rows if r.get("missing"))
    print()
    for r in rows:
        print(f"  {r['date']}  총평가 {r['totalKrw']:>14,}  "
              f"(주식 {r['stockKrw']:>13,} · 현금 {r['cashKrw']:>13,})")

    if args.dry_run:
        print("\n--dry-run - 파일을 쓰지 않았다")
        return

    existing = []
    if os.path.exists(OUT_PATH):
        with open(OUT_PATH, encoding="utf-8") as f:
            existing = json.load(f).get("history") or []
    merged = _merge(existing, rows)
    os.makedirs(os.path.dirname(OUT_PATH), exist_ok=True)
    with open(OUT_PATH, "w", encoding="utf-8") as f:
        json.dump({"updatedAt": datetime.now(KST).isoformat(), "history": merged},
                  f, ensure_ascii=False, indent=2)
    print(f"\n저장: {OUT_PATH} ({len(merged)}일, 새로 채운 것 {len(merged) - len(existing)}일)")


if __name__ == "__main__":
    main()
