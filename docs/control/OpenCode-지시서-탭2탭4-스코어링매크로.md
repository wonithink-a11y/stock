# TASK: 탭2(스코어링) + 탭4(매크로)

3개 병렬 작업 중 하나다(이 작업만 탭 2개를 맡는다 - 둘 다 "기존 데이터를
읽기 좋게 보여주기"라 성격이 비슷해서 한 작업으로 묶었다). 다른 두 작업이
같은 시각에 다른 탭을 만들고 있으니 **이 문서에 없는 파일은 절대 건드리지
않는다** - `ui/index.html`·`ui/app.js`·`ui/style.css`는 이미 완성된 공유
셸이다.

## 대상 파일

**신규 파일 두 개만**: `ui/tabs/scoring.js`, `ui/tabs/macro.js`

## 셸 계약

```js
window.TABS = window.TABS || {};
window.TABS.scoring = { title: "스코어링", render: async function (container) { ... } };
```
```js
window.TABS.macro = { title: "매크로", render: async function (container) { ... } };
```
(각각 자기 파일에 하나씩. `container`는 빈 `<section>`)

`ui/style.css`의 `.panel`·`.grid`/`.grid-2`/`.grid-3`/`.grid-4`(카드 그리드)·
`.badge`·`.stat-value`/`.stat-label`(숫자 강조용)·`.up`/`.down`(한국 관례
빨강=상승/파랑=하락)·`.mono`를 재사용한다.

## 비주얼 퀄리티 - 이게 중요하다

**표 하나 던지고 끝내는 수준이면 반려한다.** 블룸버그 터미널·증권사 HTS
매크로 화면을 참고해서:
- 매크로 탭은 지표 카드 그리드(`.grid-3`나 `.grid-4`)로 - 각 카드에 지표명·
  현재값(`.stat-value`)·미니 스파크라인(작은 라인차트) 정도는 넣는다.
- 스코어링 탭도 종목 카드/표에 점수·추천 여부를 배지·색상으로 한눈에
  보이게(점수가 높을수록 강조되는 식).
- 숫자만 나열하지 말고 시각적 위계(중요한 값은 크게, 부가정보는 작고
  흐리게 `.dim`)를 신경 쓴다.

## 탭2 - 스코어링

이 저장소가 매일 자동 갱신하는 **별개의 운영 시스템**(주식 스코어링·
모니터링, Paper Trading Engine과 무관) 데이터를 보여준다. 이미 GitHub에
공개돼 있어 raw URL로 직접 fetch한다:

```
https://raw.githubusercontent.com/wonithink-a11y/stock/main/docs/data/latest.json
https://raw.githubusercontent.com/wonithink-a11y/stock/main/docs/data/recommendations.json
https://raw.githubusercontent.com/wonithink-a11y/stock/main/docs/data/portfolio.json
```

**이 파일들의 정확한 내부 스키마는 이 지시서에 없다** - 실제로 fetch해서
구조를 스스로 파악한 뒤 종목 스코어·추천·포트폴리오 조언을 카드/테이블로
보여준다(형식 자유). 필드가 예상과 다르거나 없으면 그 부분만 비우고
나머지는 정상 렌더(fail-soft).

## 탭4 - 매크로

`ui/data/macro.json`을 fetch(경로: `../data/macro.json`):

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

`series`의 10개 지표를 카드+스파크라인으로. `usRegimeSnapshot`은 미국
매크로 레짐 스냅샷(최신값만) - 별도 섹션. **`notAvailable`에 있는 항목
(금·은·S&P500·나스닥100)은 "데이터 없음 - 추가 예정" 같은 문구로 명시적
으로 표시한다** - 빈칸으로 조용히 빼거나 다른 값으로 채우지 않는다.

## 인수 조건 (자체 검증 코드/체크리스트로 포함할 것)

1. `ui/tabs/scoring.js`·`ui/tabs/macro.js` 어디에도 `koreainvestment`
   문자열이 없다
2. `window.TABS.scoring`·`window.TABS.macro` 둘 다 title·render를 갖고
   등록된다
3. 데이터 fetch 실패 시 해당 탭만 안내 문구, 다른 탭엔 영향 없음
4. 탭2: 점수/추천/포트폴리오 정보가 카드/표로 보인다
5. 탭4: 10개 시계열 카드 + `usRegimeSnapshot` + `notAvailable` 4개 항목이
   "없음"으로 명시적으로 보인다(임의 수치로 지어내지 않음)

## 금지 사항

- `ui/tabs/scoring.js`·`ui/tabs/macro.js` 외 다른 파일 생성·수정 절대
  금지(다른 두 작업과 충돌한다)
- KIS API 호출 코드 / 시크릿 하드코딩 / git commit·git push
- `notAvailable` 항목에 임의 수치를 지어내서 채우기
