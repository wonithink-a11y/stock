---
track: us
factor: us-market-data-source-check
date: 2026-08-23
verdict: UNCLASSIFIED
criteria_version: backfill-v1
reason: "미국/글로벌 7종 데이터 소스 확인 - DEXKOUS·VIXCLS·DGS10·NASDAQ100·SP500(10년 한계 명시)은 fred() 무변경 재사용 가능, SOX/Yahoo 장기 인출·TR 원천은 UNKNOWN - 조사만 수행"
---

# 미국/글로벌 시장 데이터 소스 확인 — 2026-08

목적: 한국 주식 Market Regime Layer와 향후 연금저축/IRP 장기 리밸런싱 연구에 쓸
미국/글로벌 데이터 7종(S&P500 · NASDAQ100 · VIX · 미 10Y · Russell2000 · SOX ·
USD/KRW)의 소스를 확정한다.

방법·제약: **조사만 실행** — 라이브 프로브(존재·시작일·커버리지만 확인, 데이터 저장
없음) + FRED 공식 페이지 노트 직접 열람 + 저장소 기존 코드 대조. 백필·코드 작성·운영
변경 없음. commit/push 없음. 확인 못 한 것은 **UNKNOWN**으로 명시한다.
선행 문서: `findings/market-regime-data-source-check-2026-08.md`(2026-08-23, USD/KRW·VIX를
이미 라이브 검증 — 본 문서가 나머지 5종으로 확장), `findings/market-regime-data-inventory-2026-08.md`.

---

## 0. 요약 표 (7항목 × 5질문)

| # | 데이터 | 제공처·series | 일별 시작~최신(실측) | 무료 연구 사용 | 기존 코드 재사용 | 한국 D일 PIT 규칙 |
|---|---|---|---|---|---|---|
| 1 | S&P 500 | FRED `SP500`(S&P DJI LLC) | **2016-08-22**~2026-08-21, 2,514유효행 — **최근 10년만**(FRED-S&P 계약) | ○(FRED 인용 조건, 재배포는 사전 서면허가) | ○ `fred()` 무변경 | §5 공통 규칙 |
| 1b | (장기 SPX) | FRED 불가 → stooq/Yahoo 후보 | **UNKNOWN**(stooq 차단 실측, Yahoo 장기 해상도 미확인) | △ 비공식 | △ `stooq_daily()` **현재 차단** | 동일 |
| 2 | NASDAQ-100 | FRED `NASDAQ100`(Nasdaq, Inc.) | **1986-01-02**~2026-08-21, 10,240유효행 | ○(동일 조건) | ○ `fred()` | 동일 |
| 3 | VIX | FRED `VIXCLS`(CBOE) | 1990-01-02~2026-08-20(전회 검증) | ○(CBOE 저작권·FRED 재인쇄 허가) | ○ `fetch_macro.py` 이미 사용 중 | 동일 |
| 4 | 미 10Y 금리 | FRED `DGS10`(연준 이사회 H.15) | **1962-01-02**~2026-08-20, 16,144유효행 | ◎(미 정부 데이터) | ○ `fred()` | 동일 |
| 5 | Russell 2000 | FRED **404 확인** → Yahoo `^RUT`뿐 | Yahoo first 1987-09-01(2y 일별 501행 정상) | △ Yahoo 비공식(ToS 제약) | △ `yahoo_daily()`은 range=2y 고정 | 동일 |
| 6 | SOX | FRED **없음** → Yahoo `^SOX` | Yahoo first **1994-06-01**(2y 일별 501행 정상) | △ Yahoo 비공식 | △ 동상 + 장기 인출 검증 UNKNOWN | 동일 |
| 7 | USD/KRW | FRED `DEXKOUS`(H.10 정오매입률) | 1981-04-13~2026-08-14(전회 검증, KR거래일 커버 100% 대조) | ◎(미 정부 데이터) | ○ `fred()` + `ago()/pct_change()` | **asOf=D+1**(§5) |

TR(Total Return) 구분: **SP500은 가격지수**(FRED 노트 명시 "price index and not a total
return index... does not contain dividends"). NASDAQ100도 표준 가격지수(FRED 노트에 TR 언급
없음, `NASDAQ100TR`/`SP500TR`은 **404 실측**) → **무료 공식 TR 원천: 미발견(UNKNOWN)**.

---

## 1. 항목별 상세 (실측 근거)

프로브 방법: FRED `https://fred.stlouisfed.org/graph/fredgraph.csv?id=<ID>` GET(전 행
파싱해 첫/마지막 유효일·행수만 출력, 저장 없음). 조회 시각 **2026-08-23**(이하 모든
실측치 동일 시점). Stooq `q/d/l/?s=<SYM>&i=d`, Yahoo `query1.finance.yahoo.com/v8/finance/chart/<SYM>`.

### 1. S&P 500
- **FRED `SP500` 존재 확인.** 단 첫 유효일이 **2016-08-22 = 조회일 기준 정확히 10년**.
  FRED 시리즈 노트(공식 페이지 직접 열람)가 이유를 명시한다: *"The Federal Reserve Bank
  of St. Louis and S&P Dow Jones Indices LLC have reached a new agreement ... FRED will
  include **10 years of daily history**"*.
- 노트 추가 확인: *"Since this is a **price index and not a total return index**, the S&P 500
  index here does not contain dividends"* — **가격지수 확정**. 저작권: *"Reproduction ...
  prohibited except with the prior written permission of S&P"*, 태그 "Copyrighted: Pre-Approval
  Required" → 개인 연구·내부 사용은 FRED 인용 조건으로 가능하나 **재배포 불가**.
- 10년 이전 장기: FRED 불가. stooq `^spx`는 **안티봇 JS 챌린지 페이지로 차단(원본 UA
  `macro-fetch`로 재시도도 동일 — 실측)**. Yahoo `^GSPC`는 range=max에서 first=1984-12-01이
  반환되지만 **rows=168로 일별 전체가 아닌 압축 응답** — 장기 일별 인출 가능 여부
  **UNKNOWN**(period1/period2 청크 분할 시도는未실행). GitHub Actions 환경에서의 stooq
  동작도 미확인.
- 운영 증거: 최신 `docs/data/macro.json`(updatedAt 2026-08-21) `_diagnostics`에서
  IWF/IWD/RSP/SPY가 전부 **"yahoo OK"** — fetch_macro.py는 stooq 먼저 시도하고 실패 시
  yahoo로 폴백하므로, **최근 운영 런에서 stooq 경로가 실패하고 yahoo가 성공했다**는 뜻이다.

### 2. NASDAQ-100
- **FRED `NASDAQ100`**: 1986-01-02~2026-08-21, 10,602행(유효 10,240). 10년 한계 노트 없음 —
  **전체 이력 제공**. Source: "Nasdaq, Inc." / Release "Nasdaq Daily Index Data".
  저작권 표기(Copyright NASDAQ OMX Group)는 있으나 SP500류의 "Pre-Approval Required"
  재배포 금지 문구는 노트에서 관측되지 않았다(재배포 가능 여부 자체는 **UNKNOWN** —
  개인 연구 사용과 재배포는 별개).
- TR 여부: 노트에 TR 언급 없음(표준 NDX는 가격지수). `NASDAQ100TR` 404 실측 → FRED에 TR 없음.
  참고: `NASDAQCOM`(나스닥 종합)도 존재 — 1971-02-05~, 필요 시 보조.

### 3. VIX
- 전회 문서에서 라이브 확정: `VIXCLS` 1990-01-02~2026-08-20, 9,558행. FRED 노트:
  Source "Chicago Board Options Exchange", *"Copyright, 2016, Chicago Board Options Exchange,
  Inc. **Reprinted with permission**"* → FRED 경유 연구 사용 가능, 재배포는 별개.
- `fetch_macro.py`가 이미 `fred("VIXCLS")` 호출 중 — **재사용 논쟁 없음**.

### 4. 미국 10년물 금리
- **FRED `DGS10`**: 1962-01-02~2026-08-20, 16,863행(유효 16,144). Source "Board of Governors
  of the Federal Reserve System (US)", Release H.15 Selected Interest Rates.
  미 연준 발행 공공데이터로 라이선스 제약이 가장 적은 계열. `fred()` 재사용 그대로.

### 5. Russell 2000
- **FRED에 없음을 실측으로 확인: `RUSSELL2000` → HTTP 404.**
- Yahoo `^RUT`: range=max first=1987-09-01(rows=157 — 압축 응답), range=2y&interval=1d는
  **501행 정상 일별**. 즉 Yahoo는 최근창 일별은 되지만 장기 전체 일별 인출은 미확인.
- FTSE Russell 원천의 무료 공식 배포 경로: **UNKNOWN**(이번 범위에서 미발견).

### 6. SOX (PHLX 반도체 지수)
- **FRED에 SOX 계열 없음**(`SP500/NASDAQ100/DGS10` 외 반도체 지수 시리즈 미확인 —
  fredgraph 404 패턴과 카테고리 열람 기준; 전수 대조는 아님).
- Yahoo `^SOX`: range=max first=**1994-06-01**(rows=388 — 역시 압축 응답),
  range=2y 일별 **501행 정상**. 즉 **Yahoo에 1994년까지 소급되는 SOX 이력이 존재한다는
  사실은 확인**했으나, 그 전체를 일별로 인출할 수 있는지는 **UNKNOWN**(청크 probe 미실행).
- stooq `^sox`: 차단 실측(위와 동일). Stooq 심볼 체계(^ndx vs ^ndq 등) 식별도 차단으로 **UNKNOWN**.
- 한국 regime 연구에서 SOX 중요도는 높다(수출 주도 구조 — inventory 문서 §6 feature 후보) —
  그래서 소스 검증만 남은 B단계 과제다.

### 7. USD/KRW
- 전회 문서 확정분 인용: FRED `DEXKOUS` 1981-04-13~2026-08-14, 11,830행 중 유효 11,333
  (결측 497 = 전부 미국 공휴일 빈 문자열), **KR 거래일 71/71 전량 커버 직접 대조 완료**.
  방향·스케일이 네이버 `usdKrwLevel`과 동일("Korean Won to One U.S. Dollar").
- Source: Board of Governors(H.10 **noon buying rate**) — 미 정부 공공데이터.
- 참고: Yahoo `USDKRW=X`는 first=2003-12-01(range=max, rows=274 압축) — 보조 후보로만.

---

## 2. 라이선스/재배포 정리 (확인된 것만)

| 소스 | 확인된 내용 | 출처 |
|---|---|---|
| FRED `SP500` | S&P DJI와의 계약으로 **일별 10년만** 제공. *"Reproduction ... prohibited except with the prior written permission of S&P"*, 재생산 허가는 spdji 연락처로 별도 신청 | FRED 시리즈 페이지 노트(2026-08-23 열람) |
| FRED `NASDAQ100` | Source "Nasdaq, Inc.", Copyright NASDAQ OMX 표기. 재배포 조건 문구는 노트에서 관측 안 됨 — **재배포 가능 여부 UNKNOWN** | 동상 |
| FRED `VIXCLS` | CBOE 저작권, *"Reprinted with permission"* — FRED가 허가 받아 재게재. 다운스트림 재배포 조건 **UNKNOWN** | 동상 |
| FRED `DGS10`·`DEXKOUS` | 연준 이사회(H.15/H.10) 발행 — 미 정부 저작물 | 동상 |
| Yahoo Finance chart API | 공식 개발자 API 아닌 엔드포인트. ToS상 스크레이핑 제약 통상적이나 **본 조사에서 ToS 원문 검증은 안 함 — UNKNOWN**. 운영 fallback이 실제로 yahoo 사용 중(macro.json 진단) | macro.json `_diagnostics` |
| Stooq | `q/d/l` CSV가 JS 챌린지로 차단(2026-08-23 실측, UA 무관). 이용약관 검증 **UNKNOWN**. 프로젝트 정책상 비공식 스크레이핑의 production PRIMARY 승격 금지 원칙(data-source-availability.md)이 그대로 적용된다 | 실측 + 저장소 정책 문서 |

프로젝트 원칙 적용: 미국 데이터도 한국과 동일하게 **"비공식 스크레이핑(stooq/yahoo)은
research sandbox 전용, production PRIMARY 승격 금지"**를 기본으로 두는 것이 기존 정책과
일관된다. FRED 계열은 공식·무료·키 불요라 예외 없이 안전한 쪽이다.

## 3. 기존 코드 재사용 판정

| 코드 | 용도 | 판정 |
|---|---|---|
| `scripts/fetch_macro.py` `fred(series)` | FRED 전반 | **무변경 재사용** — SP500/NASDAQ100/VIXCLS/DGS10/DEXKOUS 전부 이 함수 하나로 호출됨. 단 `weekly(cap=80)` 압축은 백필에 절대 사용 금지(전회 문서와 동일) |
| `scripts/fetch_macro.py` `stooq_daily(sym)` | stooq 일별 CSV | **현재 차단** — 함수 로직 문제가 아니라 상대측 안티봇. 폴백이 있어 운영은 yahoo로 생존 중 |
| `scripts/fetch_macro.py` `yahoo_daily(sym)` | Yahoo chart API | **range=2y 하드코딩** — 2y 이내 검증·대조엔 그대로 usable, 장기 백필엔 파라미터 확장 필요(수정은 별도 승인 대상) |
| `scripts/collect.js` `fetchUsdKrw()` | 네이버 FX 현재값 | pageSize=21 설계라 백필 불가 — FRED DEXKOUS가 정답(전회 확정) |

research/strategy-lab 자체에는 미국 데이터 수집기가 없다 — 위 저장소 공통 함수를
연구 백필 스크립트에서 import/copy해 쓰는 것이 정확한 "재사용" 경로다(build_usdkrw_backfill.py가
이미 그 패턴으로 `fred()`를 복사 사용 중).

## 4. PIT — 한국 거래일 D 기준 asOf/shift 규칙

미국 세션은 KST 기준 **다음날 새벽(~05:00-06:00)** 에 닫힌다. 따라서:

| 사용 시점 | 사용 가능한 최신 미국 세션 | 규칙 |
|---|---|---|
| D일 장중·마감(15:30 KST) | 미국 날짜 ≤ **D−1** | `merge_asof(direction='backward')`로 미국 날짜 ≤ D 조인 — D일 미국 값은 존재 자체를 전제하지 않는다 |
| D 마감 후~D+1 개장 전(한국 저녁~새벽) | 미국 날짜 ≤ **D**(세션 종료는 D+1 05:00~06:00 KST) | D+1 한국 세션 의사결정부터 D일 미국 종가 반영 가능 |
| FRED 게시 시점 | 종가 후 당일 저녁 ET(예: SP500 "Updated Aug 21, 7:16 PM CDT" = KST 8월22일 오전) → **KST 다음날 아침** | 보수적 규칙: **FRED 경유 값은 미국 날짜 t를 한국 t+1 거래일부터 사용** |

- **공통 shift 규칙(권장)**: 한국 feature 산출일 D에 대해 "미국 날짜 ≤ D−1" 값을 쓴다면
  어떤 실행 시간에도 안전하다(look-ahead 0). D일 미국 값은 "D+1 한국 세션 이후"로 한정.
- **`DEXKOUS` 추가 지연**: H.10 정오매입률은 t일치를 t+1(미국 영업일) 16:00 ET 발표 →
  실효 asOf = **t+2 KST 아침**. 이전 세션이 관측한 9일 지연(§4-2)의 원인(H.10 주간
  게시 사이클 추정)은 **미확인** — 백필엔 무관하나 운영 현재값 사용 시 재확인 과제.
- **revision**: 전 회 문서와 동일 — FRED 스냅샷 조회로는 과거 개정 여부 미확인(**UNKNOWN**,
  필요 시 재조회 대조).
- **휴일 어긋남**: 미국만 쉬는 날(독립기념일 등)에 한국은 거래일 → 그 날짜의 미국 값은
  존재하지 않음. 처리는 KR 거래일 캘린더 기준 backward asof join(가장 가까운 과거값)이
  자연스럽고, 전회 DEXKOUS 71거래일 대조에서 결측 0건이었다. 이번 창 밖을 포함한 전 기간
  보증은 하지 않는다.

## 5. 한국 regime 연구에 필요한 최소 데이터 / 불필요 데이터

**필수 최소 5종**: `DEXKOUS`(환율 — 갭 1순위), `VIXCLS`(변동성), `DGS10`(금리 —
2022년 국면이 PnL 98.6%였던 원인 분석과 직결), `SP500`(글로벌 위험선호 기준, 최근 10년이라도),
`^SOX`(반도체 — 수출 주도 구조의 핵심 프록시, 소스만 확정되면).

**부가(우선순위 낮음)**: `NASDAQ100` — 성장주 스타일 축이긴 하나 프로젝트가 이미
IWF/IWD ratio(style proxy)를 보유해 중복성이 있다. 굳이 추가한다면 FRED 전체 이력이라
비용이 거의 없어 함께 받는 것도 무방.

**불필요/보류**: `Russell 2000` — 미국 소형주는 한국 국면 분류에 직접 정보가 적고,
소형주 상태는 자체 A2a EW 지표가 더 잘 represent한다. 연금저축/IRP 연구에서 미국
소형주 자산편성 질문이 생기면 그때 검토. **TR 버전** — regime *분류*에는 방향성만
있으면 되므로 불요. TR이 꼭 필요한 건 "미국 자산 보유 성과 귀속" 단계(리밸런싱 백테스트
결과 해석)이며, 그때까지 무료 공식 원천이 없으면 보류가 정답이다.

---

## 6. 결론 (A/B/C)

### A. 지금 바로 백필할 데이터 (소스·라이선스·코드 재사용 모두 확인됨)
1. **USD/KRW — FRED `DEXKOUS`** (1981~, KR거래일 커버 대조 완료, `fred()` 무변경)
2. **VIX — FRED `VIXCLS`** (1990~, 기존 사용 중)
3. **미 10Y — FRED `DGS10`** (1962~, 미 정부 데이터)
4. **NASDAQ-100 — FRED `NASDAQ100`** (1986~ 전체 이력, 비용 거의 0)
5. **S&P 500 최근 10년 — FRED `SP500`** (2016-08-22~ — **10년 한계를 명시하고** 받는다;
   2016~현재 한국 regime 연구 창과 정확히 겹쳐 실익이 크다)

→ 전부 `fred()` 함수 하나로 호출 가능. 필요한 구현은 "전체 이력 저장" 백필 스크립트와
KR 캘린더 backward-asof join + asOf 규칙뿐(수집 로직 신규 없음).

### B. 소스 확인 후 백필할 데이터 (데이터는 존재 확인됐지만 경로·인출 검증이 남음)
1. **SOX 장기 일별** — Yahoo `^SOX`에 1994-06~ 이력 존재 확인. 남은 검증: period1/period2
   청크로 전 기간 일별 인출 가능 여부(2y 창은 501행 정상 확인됨). 한국 regime 중요도가
   높아 C가 아니라 B다.
2. **S&P 500 10년 이전 장기** — 무료 공식 경로 없음(FRED 10년 한계). stooq는 차단 실측,
   Yahoo 장기 해상도 UNKNOWN. 필요성이 생기면 (a)Yahoo 청크 인출 검증 또는 (b)유료/공식
   라이선스 검토 — 둘 다 별도 확인 후.
3. (선택) **Russell 2000** — Yahoo `^RUT` 경로만 존재. SOX와 같은 청크 검증을 통과하면
   함께 받을 수 있으나, 한국 regime 기여도가 낮아 우선순위는 SOX 다음.

### C. 현재는 보류할 데이터
1. **S&P 500 / NASDAQ-100 Total Return** — 무료 공식 원천 미발견(FRED 404 실측,
   S&P 재배포는 유료 허가 체계). regime 분류에는 가격지수로 충분하고, TR이 필요해지는
   시점은 "미국 자산 성과 귀속이 필요한 IRP/연금 백테스트 해석 단계" — 그때 소스 재조사.
2. **stooq 경로 전반** — 안티봇 차단 실측 + 비공식 스크레이핑 production 부적합 정책.
   차단이 풀려도 보조 소스로만.
3. **Yahoo 장기(range=max) 원본 사용** — 압축 응답 실측(rows 168~388)으로 일별 보장이
   안 되므로, 청크 인출 검증(B) 없이는 어떤 데이터도 이 경로로 확정하지 않는다.

---
*검증 실행: 2026-08-23. FRED fredgraph.csv 8개 ID + stooq 7심볼 + Yahoo 9심볼 최소 프로브
(저장 없음), FRED 시리즈 페이지 노트 4건 직접 열람, docs/data/macro.json 진단 기록 대조.
원본 데이터·기존 코드 무변경. commit/push 없음.*
