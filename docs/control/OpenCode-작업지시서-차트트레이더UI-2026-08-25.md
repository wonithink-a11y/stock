# TASK: Paper Trading Engine 차트 트레이더 UI (4탭 확장판)

이 문서는 v1(단일 대시보드)을 4개 탭으로 확장한 버전이다 - v1 인수조건은
그대로 유지하고 탭 3개를 더한다.

## 배경

`research/strategy-lab/engine/live/`의 Paper Trading Engine(KIS 모의투자
연동 완료, 실제 계좌와 왕복검증 끝남)이 지금 화면이 전혀 없다 - 사용자가
"잘 되고 있는지 안 보인다"고 요청해서 대시보드 겸 단기매매용 차트 UI를
만든다. **전문 트레이더들이 쓰는 HTS/차트 터미널 같은 느낌**을 원한다 -
어두운 배경에 정보밀도 높은 패널 레이아웃(Bloomberg 터미널·TradingView류),
장난감 같은 UI가 아니라 실제 트레이딩 데스크 화면처럼.

**★ 이 작업은 KIS API를 절대 직접 호출하지 않는다.** 앱키·시크릿은 이 작업
범위 밖이고, 이 UI 코드 어디에도 KIS 도메인(`koreainvestment.com`)이나 주문
API가 등장하면 안 된다. 모든 탭은 `ui/data/*.json`(전부 Claude가 미리
채워둔 정적 스냅샷)만 읽는다 - 어떤 탭도 실시간으로 외부 API를 직접
호출하지 않는다(예외: 이미 GitHub에 공개된 `docs/data/*.json`은 raw URL로
fetch해도 된다, 아래 탭2 참고 - 이것도 KIS가 아니라 이 저장소 자신의
공개 데이터다).

## 대상 파일

- 신규: `ui/` 아래 전부(`ui/index.html`·필요한 CSS/JS, 파일 구성은 자유.
  탭 구조 - 상단 또는 좌측에 탭 4개, 클릭으로 전환)
- **건드리지 않음**: `ui/data/`(Claude가 채움) · 이 목록 밖 저장소 전체

## 탭 1 - 차트 (Paper Trading)

`ui/data/positions.json` 읽기:

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

주의(전부 정상 상태, 예외 아님):
- `status`는 `PENDING_ENTRY`·`ENTRY_SUBMITTED`·`OPEN`·`EXIT_SUBMITTED` 중
  하나. 앞 둘은 아직 KIS 체결 전이라 `avgEntryPrice` 등 필드가 아예 없을
  수 있다 - "체결 대기중"으로 표시, 0이나 null로 지어내지 않는다.
- `account`가 `{"cashKrw": null, ...}`일 수 있다(KIS 조회 일시 실패, 흔함)
  - "계좌 정보 일시 조회 실패"로 표시하고 나머지는 정상 렌더.
- `history`는 실시간이 아니다. `historyAsOf` 날짜까지의 일봉이고 화면에
  반드시 그 날짜를 표시한다.
- 종목 선택 시 `history`로 라인 차트(캔들 아니어도 됨). 매수/매도 버튼은
  `ui/orders/pending/<timestamp>_<symbol>_<side>.json`에
  `{"symbol": "005930", "side": "BUY", "quantity": 10, "reason": "chart_trader_manual", "requestedAt": "..."}`
  형식으로 파일 하나 쓰고 "요청 접수됨" 표시로 끝(체결 대기·폴링 불필요 -
  실제 KIS 처리는 별도 감시 스크립트 몫, 이 작업 범위 밖).

## 탭 2 - 스코어링 (운영 대시보드 데이터)

이 저장소가 매일 자동 갱신하는 **별개의 운영 시스템**(주식 스코어링·모니터링,
Paper Trading Engine과 무관) 데이터를 보여준다. 이미 GitHub에 공개돼 있어
raw URL로 직접 fetch 가능:

```
https://raw.githubusercontent.com/wonithink-a11y/stock/main/docs/data/latest.json
https://raw.githubusercontent.com/wonithink-a11y/stock/main/docs/data/recommendations.json
https://raw.githubusercontent.com/wonithink-a11y/stock/main/docs/data/portfolio.json
https://raw.githubusercontent.com/wonithink-a11y/stock/main/docs/data/macro.json
```

**이 4개 파일의 정확한 내부 스키마는 이 지시서에 없다** - 파일을 실제로
fetch해서 구조를 스스로 파악한 뒤 종목 스코어·추천·포트폴리오 조언을
테이블/카드로 보여준다(형식은 자유, "이미 있는 데이터를 읽기 쉽게"가
목표). 필드가 예상과 다르거나 없으면 그 부분만 비우고 나머지는 정상
렌더(fail-soft, 탭1과 같은 원칙).

## 탭 3 - 리서치랩 (Strategy Lab 실험 결과)

`ui/data/findings.json` 읽기:

```json
{"count": 76, "findings": [
  {"file": "research/strategy-lab/findings/....md",
   "title": "P0-1 후속: 5DC-v1A-P Risk-Off ... (2026-08-24)",
   "date": "2026-08-24", "bodyMarkdown": "# 제목\n\n본문 전체(마크다운)..."}
]}
```

목록(최신순, 이미 정렬돼 있음)에서 하나를 클릭하면 `bodyMarkdown`을
렌더링(마크다운 파서 라이브러리 써도 되고, 최소한 줄바꿈·`#`제목 정도만
처리해도 됨 - 완벽한 마크다운 렌더링은 필수 아님). 검색/필터(제목에 포함된
단어로) 있으면 좋음, 필수 아님.

## 탭 4 - 매크로

`ui/data/macro.json` 읽기:

```json
{
  "seriesAsOf": "2026-08-14",
  "series": {
    "usdKrwLevel": {"label": "환율 (USD/KRW)", "history": [{"date":"...","value":1418.0}, ...]},
    "vixLevel": {...}, "usFedFundsRate": {...}, "usTreasury10y": {...},
    "usNasdaq": {"label": "나스닥 종합지수 (FRED NASDAQCOM - 나스닥100 아님)", "history": [...]},
    "krKospi": {...}, "krTreasury3y": {...}, "krCorpAA3y": {...},
    "krCpi": {...}, "krCreditSpreadBp": {...}
  },
  "usRegimeSnapshot": [{"key": "vix", "value": 16.0, "display": "16.0", "asOf": "2026-08-20", ...}, ...],
  "notAvailable": ["gold", "silver", "sp500", "nasdaq100"]
}
```

`series`의 10개 지표를 각각 라인차트나 카드로. `usRegimeSnapshot`은 미국
매크로 레짐 스냅샷(최신값만, `docs/data/macro.json`과 같은 원본) - 별도
섹션으로. **`notAvailable`에 있는 항목(금·은·S&P500·나스닥100)은 "데이터
없음 - 추가 예정" 같은 문구로 명시적으로 표시한다** - 빈칸으로 조용히
빼거나 다른 값으로 채우지 않는다(이 프로젝트 절대 규칙 1).

## 스타일 가이드

- 다크 테마 기본(밝은 배경 지양). 숫자 밀도 높은 테이블/패널 레이아웃.
- 상승/하락 색상은 이 프로젝트가 한국 시장 데이터를 다루므로 **한국
  관례**(상승=빨강, 하락=파랑)를 따른다.
- 폰트는 고정폭(모노스페이스) 위주로 숫자 정렬이 깔끔하게.
- 반응형 필수는 아님(데스크톱 모니터 가정) - 다만 페이지 자체가 안 깨질
  정도의 최소 대응은 한다.

## 제약

- 순수 정적 웹(HTML/CSS/바닐라 JS). 빌드 도구 불필요.
- 외부 CDN 스크립트 사용 가능(차트 라이브러리 등) - 새 의존성 추가 전
  바닐라 JS로 충분한지 먼저 확인.
- `ui/data/*.json` 중 어느 것이든 없을 수 있다(아직 안 만들었을 때) - 그
  탭만 "데이터 없음, build_ui_*.py를 먼저 실행하세요" 안내, 다른 탭은
  정상 동작.

## 인수 조건 (자체 검증 코드로 포함할 것)

1. `ui/` 어떤 파일에도 `koreainvestment` 문자열이 없다
2. 탭 4개가 전부 존재하고 클릭으로 전환된다
3. 탭1: 계좌 요약 + 전략별 포지션 테이블 + 종목 선택 시 라인차트 +
   `historyAsOf` 표시 + 매수/매도 버튼이 `ui/orders/pending/`에 정확한
   스키마로 파일을 쓴다
4. 탭2: `docs/data/*.json`을 raw URL로 fetch해 점수/추천/포트폴리오 정보를
   렌더한다(구조는 스스로 파악)
5. 탭3: findings 76건 목록 표시, 클릭 시 본문 렌더
6. 탭4: 10개 시계열 + `usRegimeSnapshot` 표시, `notAvailable` 4개 항목이
   "없음"으로 명시적으로 보인다
7. `ui/data/*.json` 중 하나가 없거나 파싱 실패해도 그 탭만 안내 문구를
   보여주고 나머지 탭은 정상 동작한다(전체 페이지가 하얗게 안 깨짐)

## 반환 형식

신규 파일이라 전체 코드로 반환한다.

## 금지 사항

- `ui/data/` 안 파일을 직접 만들거나 커밋(런타임/빌드 산출물, Claude가 채움)
- KIS API 호출 코드(도메인·TR_ID·주문 API 어떤 형태로든)
- 시크릿·API 키 하드코딩
- git commit·git push(오픈코드는 이 저장소에서 항상 커밋하지 않는다,
  `AGENTS.md` §3)
- `ui/` 밖 파일 수정
- 탭4의 `notAvailable` 항목에 임의 수치를 지어내서 채우기
