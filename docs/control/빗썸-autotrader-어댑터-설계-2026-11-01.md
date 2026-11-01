# 빗썸 autotrader 어댑터 설계 (2026-11-01)

> **설계만이다. 코드는 아직 없다.** 실계좌 주문 코드를 새로 여는 일이라 🔴 — 아래 '결정 3건'에 사용자 GO 뒤 구현한다. Claude 는 실계좌를 켜지 않고 **실주문도 직접 내지 않는다**(소액 검증 주문은 사용자가 낸다).
> 목표: 업비트에서 만든 것(전략 `crypto_weights` · 웹 비율·금액·킬 스위치 · 크립토 화면)을 **빗썸 계좌에도 같은 방식으로** 쓴다.

## 1. 지금 있는 것 · 없는 것 (코드를 읽고 확인)

| | 있음 | 없음·위험 |
|---|---|---|
| 클라이언트 `research/strategy-lab/engine/live/bithumbClient.py` | 시세·호가·마켓 목록(공개), 잔고, 주문가능, 주문 생성·취소·조회 | 키를 `.env` 의 `BITHUMB_ACCESS_KEY` 고정 이름으로 읽는다(프로필 키 접두사 불가) · **종료 주문 목록 조회 없음**(체결 기록·손익용) · **주문 식별자(identifier) 없음**(중복 주문 방지가 약하다) · 주문 생성 '테스트' 엔드포인트 없음(업비트의 `probe` 불가) |
| 주문 유형 | 지정가(`limit`)는 공식 예제로 확인 | **시장가 `price`(원 금액 매수)·`market`(수량 매도)은 '미검증'** — 클라이언트 docstring 이 직접 적어 둠. `get_order` 도 '미검증 엔드포인트' |
| 웹 | 실계좌 요약에 빗썸 읽기 전용 표시 | autotrader 프로필·주문 경로 없음 |
| 인증 | HS256 JWT + timestamp + 단순 `key=value&` 쿼리 해시(업비트는 HS512) · 주문은 `/v2/orders`, 조회는 `/v1/...` | 두 버전이 섞여 실수하기 쉬움 |

**결론: 어댑터는 만들 수 있지만, 시장가 주문과 주문 조회 응답 모양을 실제로 한 번 확인하기 전에는 켜면 안 된다.** 업비트는 '주문 생성 테스트'로 권한·IP 를 주문 없이 확인했지만 빗썸은 그 수단이 없다.

## 2. 설계

- **브로커** `autotrader/bithumb.py` — `BithumbBroker(Broker)`, 시장 이름 `BITHUMB`, 업비트 어댑터와 같은 모양: `positions` · `cash`(원화) · `quote` · `market_info`(공개 API: 거래대금·유의 — `crypto_weights` 의 '기타' 선정용) · `order_request`/`place`(시장가: 매수 = 원 금액 `price`, 매도 = 수량 `market`) · `order_fill`(주문 조회로 체결량·평균가·수수료·상태) · `cancel`.
- **키**: 프로필 `key_prefix`(예 `BITHUMB_TRADE`) → `BITHUMB_TRADE_ACCESS_KEY/_SECRET_KEY`. 클라이언트에 선택 인자(`access_key`, `secret_key`)를 추가한다(기본 동작 불변 — 모의 브로커·기존 테스트 영향 없음). 조회용 `BITHUMB_ACCESS_KEY` 는 고를 수 없게 막는다(업비트와 같은 규칙).
- **중복 주문 방지(식별자 없음)**: ① 엔진 원장의 같은 `clientId` 가 이미 `executed` 면 보내지 않는다(브로커 앞단 가드) ② 주문 직전 미체결 주문 조회로 같은 코인의 대기 주문이 있으면 보내지 않는다 ③ 프로필 `max_orders_per_run`·`max_daily_value` 한도(기존). 식별자가 있는 업비트보다 약하다는 점을 문서·화면에 적는다.
- **체결 기록**: 종료 주문 목록이 없어서 `fills()`(실현손익·체결 알림)는 **우리가 낸 주문(원장 `orderNo`)을 하나씩 `get_order` 로 조회**하는 방식으로 만든다 — 계좌 전체 체결을 훑지 않으니 개인 거래가 섞이지 않는다.
- **설정·한도**: `broker: "bithumb"` → `markets ["BITHUMB"]`·`mode live` 고정, `RISK_DEFAULTS["BITHUMB"]`(업비트와 같은 모양: 주문당·하루·보유 한도, 최소 주문 5,000원). 기존 실계좌 게이트(`live.enabled` · `tr_ids_reviewed` · `AUTOTRADER_ALLOW_LIVE` · `--execute` · 패스키 켜기)를 그대로 지난다.
- **전략 일반화**: `crypto_weights` 의 시장 이름을 프로필 `params.market`(기본 `UPBIT`)으로 받는다. 종목 표기는 빗썸 신 API 도 `KRW-BTC` 형식이라 그대로. `coinbase_premium` 은 업비트 전용으로 둔다(BTC 프리미엄 규칙, 이번 범위 밖).
- **웹**: `is_crypto()` 가 `broker bithumb` 도 크립토로 센다 → 크립토 화면에 빗썸 프로필 카드·킬 스위치·금액·비율이 같은 모양으로 나온다. 코인 그림에 거래소 이름('업비트'/'빗썸')을 붙인다.
- **회귀**: 가짜 빗썸 클라이언트로 — 시장가 요청 본문(매수 `price`·매도 `volume`, 필드명 `order_type`) · 서명(HS256) 형식 · 중복 가드(원장·미체결) · 체결 확인 상태 처리 · 키 접두사 규칙 · 한도·킬 스위치 · `crypto_weights` 의 `market` 전환(업비트 기존 테스트 불변).

## 3. 단계와 검증 (모두 '켜기' 전)

1. **P0 문서 확인**: 빗썸 공식 API 문서(apidocs.bithumb.com)에서 시장가 주문 파라미터(`order_type`: `price`/`market`)와 주문 조회 응답 필드를 직접 읽어 클라이언트 '미검증' 표시를 확인한다(브라우저 패널로 Claude 가 한다).
2. **P1 어댑터 + 가짜 클라이언트 회귀**(Claude).
3. **P2 소액 실검증 — 사용자가 직접**: 빗썸에 원화 5,000~10,000원을 입금해 **빗썸 앱에서** 시장가 매수 1회 → 전량 매도 1회(또는 우리 어댑터를 `--execute` 로 1회 — 이 경우 사용자가 명령을 실행). 결과(`get_order` 응답 원문, 가려진 키 제외)를 Claude 에게 보여 주면 응답 필드와 어댑터 파싱을 맞춘다. 이 단계 전에는 `live.enabled` 를 켜지 않는다.
4. **P3 dry-run 며칠**(계획만) → **P4 소액 실가동**(README §11 켜는 순서와 같다).

## 4. 결정 3건 (사용자)

| # | 결정 | 권고 |
|---|---|---|
| 1 | 빗썸 API 키 발급 — 권한 **자산조회·주문조회·주문하기만**(출금 금지)·허용 IP `129.225.145.14`, 주문 전용 이름 `BITHUMB_TRADE_ACCESS_KEY/_SECRET_KEY` 로 VM `.env` 에 | 권고대로(키는 사용자만 다룬다) |
| 2 | P2 소액 실검증을 사용자가 직접 할지 | **직접 한다**(5,000~10,000원). 시장가·조회 응답을 실제로 한 번 보지 않고는 켤 수 없다 |
| 3 | 업비트 가동 순서 — 업비트 `crypto_weights` dry-run → 소액 실가동 결과를 본 뒤 빗썸 P2 로 | 병행해도 되지만 **업비트 먼저**가 안전(같은 전략·웹이라 문제를 한쪽에서 먼저 잡는다) |

## 5. 하지 않는 것

빗썸에서 코인베이스 프리미엄 전략(BTC 프리미엄 규칙 — 업비트 전용) · 지정가·선물·레버리지 · 키·한도를 웹에서 바꾸기 · 빗썸 자동 켜기.

## 6. P0 결과 — 공식 문서 확인 (11-01, apidocs.bithumb.com 을 브라우저 패널에서 직접 읽음)

§1 의 '없음·위험' 상당수가 문서로 해소됐다. **설계 §1·§2 는 아래로 갱신한다.**

| 항목 | 문서 확인 결과 |
|---|---|
| 시장가 주문 | `POST /v2/orders` — `order_type`: `limit` 지정가 · **`price` 시장가 매수(`price` = 주문 총액 원)** · **`market` 시장가 매도(`volume` 필수)** · `best` 최유리. 클라이언트의 '미검증 유추'가 **맞다**(업비트와 같은 비대칭). 응답 201 에 `order_id`·`client_order_id` |
| **주문 식별자** | **있다 — `client_order_id`**(사용자 지정 고유 ID, 영문·숫자·`-`·`_`, 1~36자). 업비트 `identifier` 와 같은 용도 → 중복 주문 방지가 업비트와 같은 수준으로 된다. **클라이언트가 아직 안 보낸다(추가 필요)**. 우리 `clientId`(`cw-2026110209-BTC-buy` 등)는 36자 이하·허용 문자라 그대로 쓸 수 있다 |
| 개별 주문 조회 | **`GET /v1/order`** — `uuid` 또는 `client_order_id`. 응답: `state`(wait/watch/done/cancel) · `executed_volume` · `executed_funds` · `paid_fee` · `trades[{price,volume,funds}]` — 업비트와 같은 모양이라 `_avg`·체결 확인 로직을 거의 그대로 쓴다 |
| **클라이언트 버그** | `bithumbClient.get_order` 는 `GET /v2/order` + `order_id` 로 부른다 — **문서의 조회는 `/v1/order` + `uuid`(또는 `client_order_id`)**. 그대로 쓰면 틀린 경로. 어댑터에서 바로잡는다(모의 브로커 `check_fill` 도 같은 경로를 쓰므로 영향 확인 필요) |
| 종료 주문 목록 | **있다 — `GET /v2/orders/history`**(`market`·`state`·`start_time`·`end_time` 최대 7일·`limit` ≤ 1000·`next_key` 페이지) — §1 의 '종료 주문 목록 없음' 은 **틀렸다**(클라이언트에 없었을 뿐). 체결 알림·손익 기록은 업비트처럼 7일 창으로 만들 수 있다 |
| 대기 주문 | `GET` 대기 주문 목록(wait/watch) 있다 — 어댑터 `open_orders` 용 |
| 투자 경보 | **`GET /v1/market/virtual_asset_warning`**(공개) — `market`·`warning_type`·`warning_step`(CAUTION/WARNING/DANGER)·`end_date`. `crypto_weights` '기타' 에서 빗썸 **경보 코인 제외**에 쓴다(업비트 `market_warning` 대응) |
| 주문 '테스트' | 문서 목록에 **주문 생성 테스트 엔드포인트가 없다**(업비트와 달리) — 소액 실검증(P2)이 여전히 필요하다 |
| 기타 | `time_in_force`(ioc/fok/post_only) 는 `limit`·`best` 전용 — 시장가엔 안 쓴다. 자전거래 방지(`stp_type: cancel_taker`)가 응답에 붙는다 |

**남은 불확실(P2 로 확인)**: 시장가 매수 `price` 가 수수료 포함 총액인지(예약 수수료 `reserved_fee`) · `POST /v2/orders` 의 실제 201 응답 필드 · 주문 취소 접수 `DELETE /v2/order` 의 정확한 파라미터(`order_id` vs `uuid`) · 최소 주문 금액.

**갱신된 중복 주문 방지**: `client_order_id` 를 보내면 업비트 `identifier` 와 같이 거래소가 같은 값을 거절하는지는 문서에 명시가 없다 — P2 에서 같은 ID 로 두 번 보내 보는 시험이 필요하다. 그 전까지는 §2 의 원장 가드·미체결 조회를 같이 쓴다.
