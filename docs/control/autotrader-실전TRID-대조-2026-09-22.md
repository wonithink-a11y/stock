# autotrader 실전 TR_ID 대조 (2026-09-22)

README §4-3·§9 의 "실전 TR_ID 를 공식 예제와 대조" 단계. 대조 대상: KIS 공식 저장소
`koreainvestment/open-trading-api` @ `b4e6249`(2026-08-26), `examples_llm/`(API 하나당 파일 하나) + `examples_user/`.
우리 쪽: `autotrader/kis.py` 의 `TR_IDS`·`PATHS`·`_order_payload`·`cancel`.

## TR_ID·경로 — 13개 전부 일치

| 시장·용도 | 우리 모의 / 실전 | 공식 모의 / 실전 | 경로 |
|---|---|---|---|
| KR 매수 | VTTC0012U / TTTC0012U | 같음 | order-cash ✓ |
| KR 매도 | VTTC0011U / TTTC0011U | 같음 | order-cash ✓ |
| KR 잔고 | VTTC8434R / TTTC8434R | 같음 | inquire-balance ✓ |
| KR 체결 | VTTC0081R / TTTC0081R | 같음 — 단 **3개월 이내** 전용(이전은 CTSC9215R). 우리는 최근 7일만 조회(`pnl.LOOKBACK_DAYS`)라 해당 없음 | inquire-daily-ccld ✓ |
| KR 시세 | FHKST01010100 공통 | 같음 | inquire-price ✓ |
| US 매수 | VTTT1002U / TTTT1002U | 같음 | order ✓ |
| US 매도 | VTTT1001U / **TTTT1006U** | 같음 — 모의·실전 번호가 다른 유일한 쌍, 공식과 일치 | order ✓ |
| US 정정취소 | VTTT1004U / TTTT1004U | 같음 | order-rvsecncl ✓ |
| US 잔고 | VTTS3012R / TTTS3012R | 같음 | inquire-balance ✓ |
| US 미체결 | VTTS3018R / TTTS3018R | 실전 TTTS3018R(공식 예제는 실전만) | inquire-nccs ✓ |
| US 매수가능 | VTTS3007R / TTTS3007R | 같음 | inquire-psamount ✓ |
| US 체결 | VTTS3035R / TTTS3035R | 같음 | inquire-ccnl ✓ |
| US 시세 | HHDFS00000300 공통 | 같음 | overseas-price/quotations/price ✓ |

해외 매도 `SLL_TYPE`: 공식은 매도 `"00"`, 매수 `""`. 우리는 매도 `"00"` ✓, 매수는 키를 안 보낸다(빈 값과 같다고 봄 — 사소).

## 차이 — 실계좌 연결 전에 고칠 것

| # | 차이 | 공식 | 우리 | 위험 |
|---|---|---|---|---|
| D1 | **해외 주문 거래소 코드** | 주문 `OVRS_EXCG_CD` 는 거래소별 `NASD`(나스닥)·`NYSE`·`AMEX` | 모든 주문·취소를 `NASD` | SOXL(NYSE Arca = KIS 분류 AMEX)을 `NASD` 로 주문. 모의는 받았지만(09-22 VM 8/8) **실전이 받는지 공식 근거 없음** — 거절되거나 다르게 처리될 수 있다 |
| D2 | **국내 주문 거래소 구분** | `EXCG_ID_DVSN_CD` **[필수]** (`KRX`), 매도 `SLL_TYPE`(01 일반매도) | 필드 없음 | 넥스트레이드(NXT) 이후 필수 필드. 빠지면 실전 거절 또는 기본값(SOR 등)으로 처리될 수 있다 |
| D3 | 해외 매수가능 조회 거래소 | psamount 는 거래소별 코드 | `NASD` 고정 | 조회만 — 틀리면 금액이 0/실패로 나와 위험 검사가 주문을 막는 쪽(안전 쪽). **D1 수정에 함께 포함**(같은 거래소 코드) |

잔고(`NASD` = 실전 "미국전체")·미체결(`NASD` 만 미국전체)은 공식 규칙과 맞다 — 고칠 것 없음.

## 결론

- TR_ID 자체는 **전부 일치** — "V→T 유도"가 맞았다(US 매도 1006U 포함).
- 그러나 **주문 본문 2건(D1·D2)이 공식과 다르다.** 이 둘을 고치고 회귀를 붙이기 전에는 `live.tr_ids_reviewed: true` 로 표시하지 않는다.
- **D1·D2 수정 완료**(2026-09-22 사용자 GO) — 회귀 `test-autotrader` 86→93, 변이 검사로 두 수정 모두 회귀가 잡는 것 확인.
  - D1: `KisBroker.us_order_exchange` — 시세에서 값이 나온 거래소를 주문 코드로(NAS→NASD·AMS→AMEX·NYS→NYSE). 주문·취소·매수가능에 쓴다.
    거래소를 못 찾으면 **추측하지 않고 주문 거부**.
  - D2: 국내 주문에 `EXCG_ID_DVSN_CD: "KRX"`·`SLL_TYPE`(매도 01)·`CNDT_PRIC: ""`. 해외도 공식 필드 순서대로 `CTAC_TLNO`·`MGCO_APTM_ODNO` 빈 값.
- **남은 확인**: 모의 서버가 새 본문을 받는지 실제 모의 주문 1건씩(국내 장중·미국 장중). 받으면 사용자가 설정에
  `live.tr_ids_reviewed: true` 를 적는다(서버 파일, Claude 는 안 켠다).
- 원래 적은 고칠 방향:
  - D1: 시세 조회에서 값이 나온 거래소(NAS/AMS/NYS)를 주문 코드(NASD/AMEX/NYSE)로 바꿔 주문·취소·매수가능에 쓴다.
  - D2: 국내 주문에 `EXCG_ID_DVSN_CD: "KRX"`, 매도에 `SLL_TYPE: "01"` 을 넣는다(공식 예제 그대로). 모의에서 먼저 받는지 확인.
