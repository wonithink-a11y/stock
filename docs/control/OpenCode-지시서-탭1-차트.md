# TASK: 탭1 - 차트 (Paper Trading)

3개 병렬 작업 중 하나다. 다른 두 작업이 같은 시각에 다른 탭을 만들고
있으니 **이 문서에 없는 파일은 절대 건드리지 않는다** - 특히 `ui/index.html`·
`ui/app.js`·`ui/style.css`는 이미 완성돼 있고 다른 작업도 같이 쓰는
공유 셸이다.

## 대상 파일

**신규 파일 딱 하나만**: `ui/tabs/chart.js`

## 셸 계약 (이미 구현돼 있음, 그대로 맞춰야 함)

`ui/app.js`가 아래 형태로 등록된 탭을 찾아서 nav 버튼을 만들고, 탭을 처음
열 때 `render(container)`를 한 번 호출한다:

```js
window.TABS = window.TABS || {};
window.TABS.chart = {
  title: "차트",
  render: async function (container) {
    // container는 빈 <section> DOM 엘리먼트 - 여기 안에 innerHTML/appendChild로 그린다
  }
};
```

색상·표·버튼 스타일은 새로 만들지 말고 `ui/style.css`에 이미 있는 클래스를
쓴다: `.panel`(카드형 박스, 안에 `<h2>`로 소제목) · `table`/`th`/`td`(숫자는
기본 오른쪽 정렬) · `.up`(상승=빨강)/`.down`(하락=파랑, 한국 관례) ·
`.btn.buy`/`.btn.sell`(매수/매도 버튼) · `.mono`(고정폭 숫자) ·
`.loading`/`.empty`(로딩중·빈 상태 문구).

## 데이터 - `ui/data/positions.json`을 fetch

```json
{
  "updatedAt": "2026-08-25T09:15:00+09:00",
  "historyAsOf": "2026-08-03",
  "account": {"cashKrw": 9998735.0, "totalValueKrw": 9998735.0},
  "strategies": {
    "pbr_value_v1": {"positions": [
      {"symbol": "021820", "status": "PENDING_ENTRY", "quantity": 16,
       "history": [{"date": "2026-06-01", "close": 12000.0}, ...],
       "avgEntryPrice": 12345.0, "currentPrice": 12500.0,
       "unrealizedPnlKrw": 2480.0, "unrealizedPnlPct": 1.25}
    ]},
    "lowmom60_v1": {"positions": [...]}
  }
}
```

경로는 `../data/positions.json`(이 JS 파일이 `ui/tabs/`에 있으므로 `ui/`
기준 상대경로 조심).

**주의(전부 정상 상태, 예외 아님):**
- `status`는 `PENDING_ENTRY`·`ENTRY_SUBMITTED`·`OPEN`·`EXIT_SUBMITTED` 중
  하나. 앞의 둘은 아직 KIS 체결 전이라 `avgEntryPrice`·`currentPrice`·
  `unrealizedPnl*` 필드가 아예 없을 수 있다 - "체결 대기중"으로 표시,
  0이나 null로 지어내지 않는다.
- `account`가 `{"cashKrw": null, "totalValueKrw": null}`일 수 있다(KIS
  조회 일시 실패, 흔함) - "계좌 정보 일시 조회 실패"로 표시, 나머지는
  정상 렌더.
- `history`는 실시간이 아니다. `historyAsOf` 날짜까지의 일봉이고 화면
  어딘가에 그 날짜를 반드시 표시한다.

## 비주얼 퀄리티 - 이게 중요하다

**단순한 HTML 표 하나 던지는 수준이면 반려한다.** 블룸버그 터미널·
TradingView·국내 증권사 HTS(키움 영웅문, 이베스트 e-Best 등) 같은 실제
트레이더용 화면을 참고해서 만든다:
- 종목 목록은 표 하나로 끝내지 말고 카드/행마다 상태 배지(`PENDING_ENTRY`
  는 노랑 계열 `.warn`, `OPEN`은 초록 계열 - 필요하면 style.css에 클래스
  추가 가능), 손익은 색상 + 화살표(▲▼)로 즉각 눈에 띄게.
- 차트는 단순 꺾은선 하나로 끝내지 말고 최소한 그리드선·현재가 기준선·
  hover 시 날짜/가격 툴팁 정도는 넣는다(과하게 복잡할 필요는 없다).
- 여백·타이포그래피 위계(제목/부제/숫자 크기 차등)를 신경 써서 "정보가
  빽빽하지만 읽기 편한" 느낌을 낸다 - 실제 트레이더가 하루 종일 보는
  화면이라는 전제로 만든다.
- 인터랙션(행 hover 시 강조, 버튼 hover/active 상태, 선택된 종목 강조)을
  넣어 "그냥 정적 페이지"가 아니라 "쓰는 도구"처럼 느껴지게 한다.

## 기능

1. 계좌 요약(현금·평가금액) 패널
2. 전략별(`pbr_value_v1`·`lowmom60_v1`) 포지션 테이블 - symbol·status·
   quantity·avgEntryPrice·currentPrice·unrealizedPnlKrw/Pct
3. 종목 하나를 선택하면(테이블 행 클릭 등) 그 종목의 `history` 배열로
   라인차트를 그린다(캔들 아니어도 됨, `<canvas>`나 SVG 직접 그려도 되고
   외부 차트 라이브러리 CDN을 써도 된다)
4. 매수/매도 버튼 - 누르면 `ui/orders/pending/<timestamp>_<symbol>_<side>.json`에
   아래 스키마로 파일 하나를 쓰는 것으로 끝(체결 대기·폴링 불필요,
   실제 KIS 처리는 이 작업 범위 밖):
   ```json
   {"symbol": "005930", "side": "BUY", "quantity": 10,
    "reason": "chart_trader_manual", "requestedAt": "2026-08-25T10:15:00+09:00"}
   ```
   버튼을 누르면 "요청 접수됨" 정도만 표시하면 된다. **★ 브라우저 JS는
   임의 파일을 직접 쓸 수 없다** - `fetch()`로 POST하는 간단한 로컬
   저장 방식을 쓰거나(예: `fetch('/orders/pending/...', {method:'PUT', body:...})`
   가 서버가 없으면 실패한다는 걸 감안해), 서버가 없는 환경에서는 그냥
   `localStorage`에 쌓아두고 "다운로드" 버튼으로 JSON 파일을 저장하게
   하는 등 **실행 가능한 방식으로 알아서 구현**해도 된다 - 핵심은 스키마를
   지키는 것이지 저장 메커니즘이 아니다.

## 인수 조건 (자체 검증 코드/체크리스트로 포함할 것)

1. `ui/tabs/chart.js`에 `koreainvestment` 문자열이 없다
2. `window.TABS.chart`가 title·render를 갖고 등록된다
3. `positions.json` fetch 실패해도 페이지가 안 깨지고 안내 문구를 보여준다
4. 계좌 요약 + 전략별 포지션 테이블 + historyAsOf 표시 + 종목 선택 시
   차트 + 매수/매도 액션이 전부 동작한다

## 금지 사항

- `ui/tabs/chart.js` 외 다른 파일 생성·수정 절대 금지(다른 두 작업과
  충돌한다)
- KIS API 호출 코드
- 시크릿 하드코딩
- git commit·git push
