# TASK: 탭3 - 리서치랩 (Strategy Lab 실험 결과)

3개 병렬 작업 중 하나다. 다른 두 작업이 같은 시각에 다른 탭을 만들고
있으니 **이 문서에 없는 파일은 절대 건드리지 않는다** - `ui/index.html`·
`ui/app.js`·`ui/style.css`는 이미 완성된 공유 셸이다.

## 대상 파일

**신규 파일 딱 하나만**: `ui/tabs/research.js`

## 셸 계약

```js
window.TABS = window.TABS || {};
window.TABS.research = {
  title: "리서치랩",
  render: async function (container) { /* container는 빈 <section> */ }
};
```

`ui/style.css`의 `.panel`·`.mono`·`.loading`·`.empty` 클래스를 재사용한다.

## 비주얼 퀄리티 - 이게 중요하다

**목록 하나 던지고 끝내는 수준이면 반려한다.** 실제 리서치 아카이브/노트
도구(Notion 데이터베이스, GitHub 이슈 리스트, 블룸버그 리서치 패널 같은)
를 참고해서:
- 좌측(또는 상단) 목록 + 우측(또는 하단) 본문 뷰어의 2단 레이아웃 정도는
  갖춘다(목록 클릭 → 본문 전환).
- 제목·날짜만 나열하지 말고 한눈에 훑을 수 있게 카드형이나 리스트+구분선
  스타일로, 최근 항목이 눈에 띄게.
- 검색/필터(제목에 포함된 단어)를 넣으면 76개나 되는 목록에서 실사용성이
  크게 올라간다 - 꼭 필요하다.
- 본문(마크다운)은 최소한 `#`/`##` 제목과 줄바꿈 정도는 구분해서 보여준다
  (완벽한 마크다운 렌더러일 필요는 없다, `<pre>`로 그냥 통짜로 보여주는
  건 지양).

## 데이터 - `ui/data/findings.json`을 fetch (경로: `../data/findings.json`)

```json
{"count": 76, "findings": [
  {"file": "research/strategy-lab/findings/....md",
   "title": "P0-1 후속: 5DC-v1A-P Risk-Off ... (2026-08-24)",
   "date": "2026-08-24", "bodyMarkdown": "# 제목\n\n본문 전체(마크다운)..."}
]}
```

이미 최신순으로 정렬돼 있다. `date`가 `null`인 항목도 있을 수 있다(날짜를
못 뽑은 경우) - 목록 맨 아래나 별도로 처리, 에러 내지 않는다.

## 인수 조건 (자체 검증 코드/체크리스트로 포함할 것)

1. `ui/tabs/research.js`에 `koreainvestment` 문자열이 없다
2. `window.TABS.research`가 title·render를 갖고 등록된다
3. `findings.json` fetch 실패해도 페이지가 안 깨지고 안내 문구를 보여준다
4. 76건 전부 목록에 보이고, 클릭 시 본문이 렌더된다
5. 제목 검색/필터가 동작한다

## 금지 사항

- `ui/tabs/research.js` 외 다른 파일 생성·수정 절대 금지(다른 두 작업과
  충돌한다)
- KIS API 호출 코드 / 시크릿 하드코딩 / git commit·git push
