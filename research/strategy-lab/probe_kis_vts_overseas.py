#!/usr/bin/env python3
"""KIS 모의투자 계좌에 **해외주식이 열려 있는지** 읽기 전용으로 확인한다.

    python research/strategy-lab/probe_kis_vts_overseas.py

★ 주문을 내지 않는다. 조회 TR_ID(VTTS3012R 잔고 · VTRP6504R 체결기준현재잔고)만
  쓴다. 도메인은 kisVtsClient 와 같은 모의투자 도메인 하나뿐이라 실전을 칠 방법이
  코드에 없다(그 파일의 설계 원칙을 그대로 따른다).

왜 먼저 재는가: 해외주식 모의투자는 계좌마다 별도로 열려 있을 수도, 아닐 수도 있다.
열려 있지 않으면 주문 배선 전체가 무의미하므로, 코드를 짜기 전에 응답으로 확인한다
(교훈50 — 잴 수 없는 계약은 계약이 아니다).
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from engine.live.kisVtsClient import BASE_URL, KisVtsClient, KisVtsError, _request

PATH_BALANCE = "/uapi/overseas-stock/v1/trading/inquire-balance"
PATH_PRESENT = "/uapi/overseas-stock/v1/trading/inquire-present-balance"
PATH_PSAMOUNT = "/uapi/overseas-stock/v1/trading/inquire-psamount"
TR_BALANCE = "VTTS3012R"   # 해외주식 잔고 (모의투자)
TR_PRESENT = "VTRP6504R"   # 해외주식 체결기준현재잔고 (모의투자)
TR_PSAMOUNT = "VTTS3007R"  # 해외주식 매수가능금액 (모의투자) — 달러 예수금의 대리지표


def _probe(client: KisVtsClient, label: str, path: str, tr_id: str, params: dict) -> dict:
    """rt_cd 를 성공으로 읽지 않는다 — 응답 본문까지 보고 판정한다(교훈81)."""
    r = _request("GET", BASE_URL + path, headers=client._headers(tr_id),
                 params=params, timeout=20)
    try:
        body = r.json()
    except ValueError:
        return {"label": label, "ok": False, "why": f"JSON 아님 (HTTP {r.status_code})"}
    ok = r.status_code == 200 and body.get("rt_cd") == "0"
    return {
        "label": label, "ok": ok, "http": r.status_code,
        "rt_cd": body.get("rt_cd"), "msg_cd": body.get("msg_cd"),
        "msg1": (body.get("msg1") or "").strip(),
        "body": body,
    }


def main() -> int:
    try:
        c = KisVtsClient()
    except KisVtsError as e:
        print(f"자격증명 없음: {e}")
        return 1

    print(f"도메인 {BASE_URL}")
    print(f"계좌   {c.cano}-{c.acnt_prdt_cd}\n")

    common = {"CANO": c.cano, "ACNT_PRDT_CD": c.acnt_prdt_cd,
              "CTX_AREA_FK200": "", "CTX_AREA_NK200": ""}
    results = [
        _probe(c, "해외 잔고 (NASD/USD)", PATH_BALANCE, TR_BALANCE,
               {**common, "OVRS_EXCG_CD": "NASD", "TR_CRCY_CD": "USD"}),
        _probe(c, "해외 체결기준현재잔고", PATH_PRESENT, TR_PRESENT,
               {**common, "WCRC_FRCR_DVSN_CD": "02", "NATN_CD": "840",
                "TR_MKET_CD": "00", "INQR_DVSN_CD": "00"}),
        _probe(c, "매수가능금액 (TQQQ @ $71.6)", PATH_PSAMOUNT, TR_PSAMOUNT,
               {"CANO": c.cano, "ACNT_PRDT_CD": c.acnt_prdt_cd,
                "OVRS_EXCG_CD": "NASD", "OVRS_ORD_UNPR": "71.60", "ITEM_CD": "TQQQ"}),
    ]

    enabled = False
    for x in results:
        mark = "OK  " if x["ok"] else "FAIL"
        print(f"{mark} {x['label']}")
        print(f"     HTTP {x.get('http')} · rt_cd {x.get('rt_cd')} · "
              f"{x.get('msg_cd')} {x.get('msg1')}")
        if x["ok"]:
            enabled = True
            b = x["body"]
            rows = b.get("output1") or []
            if isinstance(rows, dict):
                rows = [rows]
            print(f"     보유 {len(rows)}종목")
            for row in rows[:5]:
                print(f"       {row.get('ovrs_pdno', '?'):8} {row.get('ovrs_cblc_qty', '?'):>8}주")
            o2 = b.get("output2")
            if isinstance(o2, dict):
                for k in ("frcr_dncl_amt1", "frcr_buy_amt_smtl1", "ovrs_rlzt_pfls_amt",
                          "tot_evlu_pfls_amt", "frcr_evlu_tota"):
                    if k in o2:
                        print(f"       {k} = {o2[k]}")
            o = b.get("output")
            if isinstance(o, dict):
                for k, v in o.items():
                    print(f"       {k} = {v}")
        print()

    print("판정:", "해외주식 모의투자 사용 가능" if enabled
          else "해외주식 모의투자가 이 계좌에 열려 있지 않다 (또는 TR/파라미터 불일치)")
    return 0 if enabled else 2


if __name__ == "__main__":
    raise SystemExit(main())
