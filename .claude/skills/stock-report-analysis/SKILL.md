---
name: stock-report-analysis
description: 학회(KUVIC·SNUSMIC·YIG·S.T.A.R)·한국IR협의회 종목 리포트(또는 미국 종목 리포트)를 읽고 DART·SEC 공시와 대조해 대시보드 '종목 리포트' 칸에 올리는 절차. "리포트 분석해줘", "이 리포트 올려줘", "한국IR협의회 최신 리포트", "종목 리포트 추가", "KUVIC 리포트", "reports.json 갱신" 같은 말이 나오면 반드시 이 스킬을 쓴다. 리포트의 의견·목표가를 판단 근거로 쓰라는 요청이면 먼저 절대 규칙 1(맥락 전용)을 짚는다.
---

# 종목 리포트 분석 → 대시보드 올리기

남의 콘텐츠를 **읽고 검증한 기록**을 만든다. 매수·매도 판단이 아니다. 점수·매매에 연결하지 않는다(절대 규칙 1). 리포트의 의견·목표가는 근거로 쓰지 않는다.
저장소는 공개라 **분석 원본·원문 PDF 는 저장소에 넣지 않는다**(원문은 링크만).

## 0. 어디에 무엇이 있나

```
PC 원본   reports/market-weekly-private/rr/reports.json   (gitignore, 개인 열람용)
VM 서비스  ~/collector-venv/rr/reports.json  → GET https://wonithink-stock.duckdns.org/rr  (X-Pin-Key, 핸들러가 요청마다 파일을 읽어 재시작 불필요)
화면      대시보드 이벤트·뉴스 > '종목 리포트' (docs/index.html renderRr)
갱신      scp reports/market-weekly-private/rr/reports.json stock-new:collector-venv/rr/reports.json
```

## 1. 원문 받기 (다운로드는 사용자가 시킨 대상만)

- **한국IR협의회**: 목록 `https://www.kirs.or.kr/research/research22_1.html`(로그인 없음). 종목 링크는 브라우저 패널 `find` 로 `href` 를 읽고 `https://w4.kirs.or.kr/download/research/…pdf`. 의견·목표가 없는 소개 보고서(거래소·예탁결제원·증권금융 출연, 무상).
- **KUVIC**: `https://www.kuvic.com/` 의 Download 링크(`/_files/ugd/…pdf`). 일부는 **이미지 PDF**(텍스트 추출 0자) — 그땐 `pymupdf` 로 쪽을 PNG 로 만들어 핵심 쪽만 본다(요약·재무 표·리스크·밸류에이션).
- **YIG**: 사이트 버튼이 주소를 숨긴다. 페이지 HTML 의 썸네일 주소에서 폴더명을 얻고 `https://storage.googleapis.com/storage/v1/b/yighub/o?prefix=research-report-files/<날짜>&fields=items(name,size)` 로 파일명을 찾아 같은 버킷에서 받는다.
- **미국 종목(MSFT 등)**: DART 대신 SEC `https://data.sec.gov/api/xbrl/companyconcept/CIK<10자리>/us-gaap/<태그>.json` (헤더 `User-Agent: stock-research-script/1.0` — **사용자 이메일을 넣지 않는다**). 매출은 `RevenueFromContractWithCustomerExcludingAssessedTax`.
- 받는 곳은 **스크래치패드의 새 폴더**(신뢰 못 하는 파일). 파이썬은 `python -I`, 파일 경로는 인자로. 건당 크기·출처를 사용자에게 말하고 받는다.

## 2. 읽기

- `pymupdf` 로 쪽별 텍스트 → 숫자 줄이 많아 토큰이 크므로 **긴 줄(서술)만 거른 사본**과 표 쪽(표지·재무제표·밸류에이션·비교 표)을 따로 본다. 건당 전체를 읽을 때도 한 번에 2만 토큰을 넘기지 않게 offset 으로 나눈다.
- 반드시 잡는 것: ①주장 한 줄 ②가정(결과를 좌우하는 것) ③밸류에이션(목표 PER·기준 연도·피어·할인) ④리포트가 적은 리스크 / **안 보이는 리스크** ⑤읽은 범위(못 읽은 쪽은 `readCoverage`·`unknown` 에 적는다).

## 3. 공시 대조 (이 절차의 핵심)

- 한국 종목: DART `fnlttSinglAcntAll.json`(키 `.env` 의 `DART_API_KEY`, 법인코드 `data/cache/corpCodeMap.json` 의 `map[종목코드]`). 연결(CFS) 우선, 연간 `11011`·반기 `11012`·1Q `11013`·3Q `11014`.
  콘솔이 cp949 라 계정명이 깨진다 → 스크립트에서 `sys.stdout.reconfigure(encoding='utf-8')` 로 출력하거나 UTF-8 파일에 써서 Read 로 본다. `python -I` 는 환경변수를 무시하므로 인코딩은 코드에서.
- 비교 항목: 최근 2~3개 연도 매출·영업이익·순이익, **직전 반기 실적(리포트가 본문에 안 쓴 경우가 많다)**, 부채·차입·전환사채, 표지 숫자(시총·PER)의 산술.
- **순이익은 당기순이익(지배)과 총포괄손익을 구분**한다(에이직랜드 사례: 리포트 표기가 총포괄손익과 같았다).
- **산술 검산**: 반기+반기=연간, 분기 합, PER=시총÷순이익, 상승여력=목표÷현재, 시나리오 PER 민감도.
- 같은 날 마감 리포트(`reports/market-daily/`)의 지수·환율로 리포트의 시장값(표지 KOSPI·KOSDAQ)을 대조하고, **상승여력 기준 주가가 폭락 전 값이면** `flags` 에 적는다.
- 판정 표기: `일치` / `불일치` / `소폭 차이` / `리포트에 없음`. 내 산술은 반드시 "내 계산"이라고 쓴다. 확신 못 하는 해석은 `unknown` 으로.

## 4. reports.json 항목 (스키마)

`id`(`<티커>-<출처>-<yyyymmdd>`) `ticker` `name` `source` `title` `published` `url` `analyzedAt` `readCoverage` `stance` `verdict` `claim` `assumptions[{k,v}]` `valuation{summary,rows[{k,v}]}` `counter[{type:'stated'|'missing',text}]` `checks[{item,report,dart,result}]` `mismatches[]` `unknown[]` `nextDates[{date,what}]`, 그리고 한눈 요약 `dash`:
`headline`(≤34자) `opinion{label,target,price,upside}` `val{l,v,s}` `scenarios[{l,pct}]`(목표가 있는 건만) `fin{unit,years,rows[{l,v[]}]}` `flags[{lv:'hi'|'mid'|'lo',t}]`(≤5, 한 줄) `keys[]`(핵심 가정 3개).
`hi`=결과를 크게 좌우하거나 원문 오류, `mid`=확인 필요, `lo`=참고. 기존 항목을 본보기로 연다.
`python` 으로 항목을 추가할 땐 `json.load → items 갱신 → json.dump(ensure_ascii=False, indent=2)` (id 같으면 교체). 한글 치환은 스크립트를 **Write 로 UTF-8 파일**로 만들어 실행(heredoc 은 cp949 로 깨질 수 있다).

## 5. 올리기와 확인

1. `scp` 로 VM 갱신. 사용자 확인 불필요(정형 운영, 이미 등록된 경로).
2. 확인: `curl -H "X-Pin-Key: $(ssh stock-new 'cat ~/collector-venv/pins/key')" https://wonithink-stock.duckdns.org/rr | python -c "import json,sys;print(len(json.load(sys.stdin)['items']))"` — 키 값은 출력하지 않는다. 키 없이 부르면 401 이어야 한다.
3. 화면 모양을 바꿨으면 `dashboard-phone-check` 스킬로 폰 폭 확인.
4. 인수인계에 새로 추가한 건과 미확인을 2~3줄.

## 하지 않는 것

- 원문 PDF·분석 원본을 저장소에 커밋(공개 저장소, 재배포 금지 조항 있음).
- 의견·목표가·상승여력을 점수·매매·추천에 연결.
- 리포트 한 건의 결론으로 종목을 "좋다/나쁘다" 단정(분석은 '주장이 숫자와 맞는가'까지).
