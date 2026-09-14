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


def to_rows(client, accounts):
    """잔고 0(청산 완료 잔여 레코드)은 뺀다. KRW는 환산 없이 그대로,
    그 외 통화는 시세 조회로 원화 평가액을 계산한다 - 조회 실패한 자산은
    건너뛰지 않고 evalKrw=None으로 남긴다(교훈57 - 모르는 건 0이 아니다)."""
    rows = []
    for a in accounts:
        currency = a.get("currency")
        balance = float(a.get("balance") or 0) + float(a.get("locked") or 0)
        if balance <= 0:
            continue
        unit = a.get("unit_currency") or "KRW"
        if currency == unit:
            rows.append({"currency": currency, "balance": balance, "evalKrw": balance})
            continue
        try:
            price = client.get_ticker(f"{unit}-{currency}")
            eval_krw = balance * price
        except Exception:
            eval_krw = None
        rows.append({"currency": currency, "balance": balance, "evalKrw": eval_krw})
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
    ]
    rows = to_rows(_FakeClient(), accounts)
    assert len(rows) == 2, "0잔고 통화는 빠져야 한다"
    krw_row = next(r for r in rows if r["currency"] == "KRW")
    assert krw_row["evalKrw"] == 500000, "KRW는 환산 없이 그대로여야 한다"
    btc_row = next(r for r in rows if r["currency"] == "BTC")
    assert btc_row["evalKrw"] == 100_000.0, "BTC 평가액이 잘못됐다"
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

    payload = {
        "exchange": args.exchange,
        "generatedAtKST": datetime.now(KST).isoformat(),
        "totalKrw": total_krw,
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
