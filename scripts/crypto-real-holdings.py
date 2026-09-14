#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""crypto-real-holdings.py — 업비트·빗썸 실계좌 잔고조회(읽기 전용).

kis-portfolio-holdings.py와 같은 원칙: 결과(홈 디렉터리 ~/.upbit-holdings.json·
~/.bithumb-holdings.json)는 절대 git에 올리지 않는다 - 실제 보유자산·평가금액은
이 저장소가 공개라 노출되면 안 되는 정보다. kis-minute-history-api.py의
/accounts 엔드포인트가 이 파일을 직접 읽어 UI에 뿌린다.

거래소 클라이언트(UpbitClient·BithumbClient)의 get_accounts()는 이미
probe-{upbit,bithumb}-key-check.py로 실측 검증된 필드(currency·balance·
locked)를 그대로 반환한다 - 새로 설계하지 않았다. 원화 환산은 KRW 통화 항목은
그대로, 그 외 통화는 get_ticker("KRW-{currency}")로 환산한다.

주문 코드(place_order)는 이 스크립트가 전혀 참조하지 않는다 - 잔고조회만.

사용:
    python scripts/crypto-real-holdings.py --exchange upbit
    python scripts/crypto-real-holdings.py --exchange bithumb
    python scripts/crypto-real-holdings.py --exchange upbit --selftest
    python scripts/crypto-real-holdings.py --exchange upbit --dry-run   # 조회만 하고 파일에 안 씀
"""
import argparse
import json
import os
import sys
from datetime import datetime, timezone, timedelta
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "research" / "strategy-lab"))

KST = timezone(timedelta(hours=9))

OUT_PATH_BY_EXCHANGE = {
    "upbit": Path(os.environ.get("UPBIT_HOLDINGS_PATH") or (Path.home() / ".upbit-holdings.json")),
    "bithumb": Path(os.environ.get("BITHUMB_HOLDINGS_PATH") or (Path.home() / ".bithumb-holdings.json")),
}


class CryptoHoldingsError(RuntimeError):
    pass


def _client_for(exchange):
    if exchange == "upbit":
        from engine.live.upbitClient import UpbitClient, UpbitError
        return UpbitClient(), UpbitError
    if exchange == "bithumb":
        from engine.live.bithumbClient import BithumbClient, BithumbError
        return BithumbClient(), BithumbError
    raise CryptoHoldingsError(f"알 수 없는 거래소: {exchange}")


# 거래 지원이 끊겨 시세 자체가 없는 통화 - get_ticker를 불러봐야 항상
# 실패하니(교훈57과 반대 방향: 이건 "모르는 값"이 아니라 "낼 수 없는 값"이다)
# 아예 조회하지 않고 건너뛴다. PSG - 업비트 유의종목 지정 후 거래지원 종료
# (2026-09-15 사용자 확인, 대시보드에 "시세 조회 실패"로만 뜨던 걸 신고).
UNSUPPORTED_CURRENCIES = {"PSG"}


def to_rows(client, accounts):
    """잔고 0(청산 완료 잔여 레코드)은 뺀다. KRW는 환산 없이 그대로,
    그 외 통화는 시세 조회로 원화 평가액을 계산한다 - 조회 실패한 자산은
    건너뛰지 않고 evalKrw=None으로 남긴다(교훈57 - 모르는 건 0이 아니다).

    avg_buy_price(평균매입단가)는 업비트·빗썸 계좌조회 응답에 이미 있다 -
    거래소가 계산한 값을 그대로 쓰고 재계산하지 않는다. avg_buy_price가
    0이거나 없으면(무상 입금 등) costKrw·pnlKrw를 안 낸다(0으로 채우면
    거짓 손익이 된다)."""
    rows = []
    for a in accounts:
        currency = a.get("currency")
        if currency in UNSUPPORTED_CURRENCIES:
            continue
        balance = float(a.get("balance") or 0) + float(a.get("locked") or 0)
        if balance <= 0:
            continue
        unit = a.get("unit_currency") or "KRW"
        avg_buy_price = float(a.get("avg_buy_price") or 0) or None
        if currency == unit:
            rows.append({"currency": currency, "balance": balance, "evalKrw": balance,
                         "avgBuyPrice": None, "costKrw": None, "pnlKrw": None, "pnlPct": None})
            continue
        try:
            price = client.get_ticker(f"{unit}-{currency}")
            eval_krw = balance * price
        except Exception:
            eval_krw = None
        cost_krw = balance * avg_buy_price if avg_buy_price else None
        pnl_krw = (eval_krw - cost_krw) if (eval_krw is not None and cost_krw is not None) else None
        pnl_pct = (pnl_krw / cost_krw * 100) if (pnl_krw is not None and cost_krw) else None
        rows.append({"currency": currency, "balance": balance, "evalKrw": eval_krw,
                     "avgBuyPrice": avg_buy_price, "costKrw": cost_krw, "pnlKrw": pnl_krw, "pnlPct": pnl_pct})
    return rows


def selftest():
    class _FakeClient:
        def get_ticker(self, market):
            assert market == "KRW-BTC", market
            return 100_000_000.0

    accounts = [
        {"currency": "KRW", "balance": "500000", "locked": "0", "unit_currency": "KRW"},
        {"currency": "BTC", "balance": "0.001", "locked": "0", "unit_currency": "KRW"},
        {"currency": "ETH", "balance": "0", "locked": "0", "unit_currency": "KRW"},  # 0잔고 - 제외
        {"currency": "PSG", "balance": "0.2", "locked": "0", "unit_currency": "KRW"},  # 거래지원 종료 - 제외, get_ticker도 안 불림
    ]
    rows = to_rows(_FakeClient(), accounts)
    assert len(rows) == 2, "0잔고·거래지원종료 통화는 빠져야 한다"
    assert not any(r["currency"] == "PSG" for r in rows), "PSG는 목록에 없어야 한다"
    krw_row = next(r for r in rows if r["currency"] == "KRW")
    assert krw_row["evalKrw"] == 500000, "KRW는 환산 없이 그대로여야 한다"
    assert krw_row["pnlKrw"] is None, "KRW는 손익 개념이 없어야 한다"
    btc_row = next(r for r in rows if r["currency"] == "BTC")
    assert btc_row["evalKrw"] == 100_000.0, "BTC 평가액이 잘못됐다"
    assert btc_row["avgBuyPrice"] is None and btc_row["pnlKrw"] is None, \
        "avg_buy_price 없으면 손익도 없어야 한다(0으로 채우면 거짓 손익)"

    accounts2 = [{"currency": "BTC", "balance": "0.001", "locked": "0",
                  "unit_currency": "KRW", "avg_buy_price": "80000000"}]
    rows2 = to_rows(_FakeClient(), accounts2)
    assert rows2[0]["costKrw"] == 80_000.0, "매입원가 계산이 틀렸다"
    assert rows2[0]["pnlKrw"] == 20_000.0, "평가손익 계산이 틀렸다"
    assert round(rows2[0]["pnlPct"], 2) == 25.0, "수익률 계산이 틀렸다"
    print("selftest OK")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--exchange", choices=["upbit", "bithumb"], required=False)
    ap.add_argument("--selftest", action="store_true")
    ap.add_argument("--dry-run", action="store_true", help="조회만 하고 파일에 쓰지 않는다")
    args = ap.parse_args()
    if args.selftest:
        return selftest()
    if not args.exchange:
        ap.error("--exchange가 필요하다(--selftest 제외)")

    client, error_cls = _client_for(args.exchange)
    try:
        accounts = client.get_accounts()
    except error_cls as e:
        raise CryptoHoldingsError(f"{args.exchange} 잔고 조회 실패: {e}") from e

    rows = to_rows(client, accounts)
    total_krw = sum(r["evalKrw"] for r in rows if r["evalKrw"] is not None)
    unresolved = [r["currency"] for r in rows if r["evalKrw"] is None]
    # 총 손익은 avg_buy_price가 있는(=원가를 아는) 보유만 더한다 - 모르는 걸
    # 0으로 채우면 실제보다 손익이 부풀거나 줄어 보인다(교훈57).
    priced = [r for r in rows if r["pnlKrw"] is not None]
    total_pnl_krw = sum(r["pnlKrw"] for r in priced) if priced else None
    total_cost_krw = sum(r["costKrw"] for r in priced) if priced else None

    payload = {
        "exchange": args.exchange,
        "generatedAtKST": datetime.now(KST).isoformat(),
        "totalKrw": total_krw,
        "totalPnlKrw": total_pnl_krw,
        "totalCostKrw": total_cost_krw,
        "unresolvedCurrencies": unresolved,  # 시세 조회 실패 - 합계에서 빠졌다는 걸 숨기지 않는다
        "holdings": rows,
    }
    if args.dry_run:
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        return

    out_path = OUT_PATH_BY_EXCHANGE[args.exchange]
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    try:
        os.chmod(out_path, 0o600)
    except Exception:
        pass
    print(f"wrote {out_path} (holdings={len(rows)}, totalKrw={total_krw:.0f})")


if __name__ == "__main__":
    main()
