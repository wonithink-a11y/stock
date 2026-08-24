# TASK: Paper Trading Engine 차트 트레이더 UI

## 배경

`research/strategy-lab/engine/live/`의 Paper Trading Engine(KIS 모의투자 연동
완료, 실제 계좌와 왕복검증 끝남)이 지금 화면이 전혀 없다 - 사용자가 "잘 되고
있는지 안 보인다"고 요청해서 대시보드 겸 단기매매용 차트 UI를 만든다.

**★ 이 작업은 KIS API를 절대 직접 호출하지 않는다.** 앱키·시크릿은 이 작업
범위 밖이고, 이 UI 코드 어디에도 KIS 도메인(`koreainvestment.com`)이나 주문
API가 등장하면 안 된다. 대신:
- 화면에 보여줄 데이터는 `ui/data/positions.json`을 읽기만 한다(아래 스키마).
- 매수/매도 버튼을 누르면 `ui/orders/pending/`에 요청 파일 하나를 쓰기만
  한다(아래 스키마) - 실제 KIS 주문은 별도 감시 스크립트(이 작업 범위 밖,
  Claude가 나중에 짠다)가 그 파일을 읽어서 처리한다.

## 대상 파일

- 신규: `ui/` 아래 전부(`ui/index.html`·필요한 CSS/JS, 파일 구성은 자유)
- **건드리지 않음**: `ui/data/`·`ui/orders/`(이 두 폴더 안 파일을 직접
  만들거나 커밋하지 않는다 - 런타임에 생기는 데이터/요청함이다)
- **건드리지 않음**: 이 목록 밖 저장소 전체(읽기도 필요 없음)

## 입력 계약 - `ui/data/positions.json`

`research/strategy-lab/build_ui_feed.py`가 주기적으로 채우는 파일. 스키마:

```json
{
  "updatedAt": "2026-08-25T09:15:00+09:00",
  "historyAsOf": "2026-08-03",
  "account": {"cashKrw": 9998735.0, "totalValueKrw": 9998735.0},
  "strategies": {
    "pbr_value_v1": {
      "positions": [
        {
          "symbol": "021820", "status": "PENDING_ENTRY", "quantity": 16,
          "history": [{"date": "2026-06-01", "close": 12000.0}, ...],
          "avgEntryPrice": 12345.0, "currentPrice": 12500.0,
          "unrealizedPnlKrw": 2480.0, "unrealizedPnlPct": 1.25
        }
      ]
    },
    "lowmom60_v1": {"positions": [...]}
  }
}
```

주의할 점 (전부 실제로 지금 관측되는 정상 상태다, 예외 아님):
- `status`는 `PENDING_ENTRY`·`ENTRY_SUBMITTED`·`OPEN`·`EXIT_SUBMITTED` 중 하나다.
  `PENDING_ENTRY`/`ENTRY_SUBMITTED`인 동안은 아직 KIS 체결 전이라
  `avgEntryPrice`·`currentPrice`·`unrealizedPnl*` 필드 자체가 없을 수 있다
  (없으면 "체결 대기중"처럼 표시, 0이나 null로 지어내지 않는다).
- `account`가 `{"cashKrw": null, "totalValueKrw": null}`일 수 있다(KIS 조회
  일시 실패 - 흔한 일이다). 이때는 "계좌 정보 일시 조회 실패"라고 표시하고
  나머지 화면은 정상 렌더한다.
- `history`는 **실시간이 아니다.** `historyAsOf` 날짜까지의 일봉이다(그 이후
  공백이 있을 수 있음, 정상). 화면 어딘가에 `historyAsOf`를 반드시 표시해서
  "이 차트가 언제까지의 데이터인지" 사용자가 알 수 있게 한다.
- `strategies`에 없는 종목은 애초에 이 파일럿 대상이 아니다 - 임의 종목
  검색/추가 기능은 이번 범위 밖이다.

## 출력 계약 - `ui/orders/pending/<timestamp>_<symbol>_<side>.json`

매수/매도 버튼을 누르면 아래 스키마로 파일 하나를 쓴다(파일명 예:
`20260825T101500_005930_BUY.json`):

```json
{
  "symbol": "005930",
  "side": "BUY",
  "quantity": 10,
  "reason": "chart_trader_manual",
  "requestedAt": "2026-08-25T10:15:00+09:00"
}
```

이 파일을 쓰는 것 자체가 최종 동작이다 - 실제 KIS 응답을 기다리거나 폴링할
필요 없다(그건 감시 스크립트 몫). 버튼을 누른 뒤에는 "요청 접수됨"만 표시하면
된다.

## 제약

- 순수 정적 웹(HTML/CSS/바닐라 JS). 빌드 도구·프레임워크 불필요 - 브라우저에서
  파일을 열거나 아주 단순한 정적 서버로 띄우는 것만 가정한다.
- 차트는 `history` 배열(날짜·종가)로 그리는 라인 차트면 충분하다 - 캔들스틱
  같은 고급 차트가 필요하면 만들어도 되지만 필수 아니다.
- 외부 CDN 스크립트 사용 가능(이 페이지는 로컬 실행이라 Artifact의 CSP 제약이
  없다) - 다만 새 의존성을 추가하기 전에 바닐라 JS로 충분한지 먼저 확인한다.
- `ui/data/positions.json`이 아예 없을 수도 있다(build_ui_feed.py를 아직 한
  번도 안 돌렸을 때) - 이때 화면이 깨지지 않고 "데이터 없음, build_ui_feed.py를
  먼저 실행하세요" 안내를 보여준다.

## 인수 조건 (자체 검증 코드로 포함할 것)

1. `ui/` 어떤 파일에도 `koreainvestment` 문자열이 없다(grep으로 확인 가능한
   형태로 - 예: README나 커밋 메시지에 남긴다)
2. `positions.json`을 로드해 계좌 요약(cashKrw·totalValueKrw, null이면 "조회
   실패" 표시)을 렌더한다
3. 전략별(`pbr_value_v1`·`lowmom60_v1`) 포지션 테이블을 렌더한다(symbol·
   status·quantity·avgEntryPrice·currentPrice·unrealizedPnlKrw/Pct, 없는
   필드는 빈칸/"체결대기"로 처리하고 0이나 임의값으로 채우지 않는다)
4. 종목 하나를 선택하면 그 종목의 `history`로 라인 차트를 그린다
5. `historyAsOf`가 화면에 보인다
6. 매수/매도 버튼이 `ui/orders/pending/`에 위 스키마대로 파일을 쓴다
7. `positions.json`이 없거나 JSON 파싱에 실패해도 페이지가 하얗게 안 깨지고
   안내 메시지를 보여준다

## 반환 형식

신규 파일이라 전체 코드로 반환한다.

## 금지 사항

- `ui/data/`·`ui/orders/` 안 파일을 직접 만들거나 커밋(런타임 산출물)
- KIS API 호출 코드(도메인·TR_ID·주문 API 어떤 형태로든)
- 시크릿·API 키 하드코딩
- git commit·git push(오픈코드는 이 저장소에서 항상 커밋하지 않는다,
  `AGENTS.md` §3)
- `ui/` 밖 파일 수정
